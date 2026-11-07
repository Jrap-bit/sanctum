# Rule settings

Apply migration `0013_rule_versions` and restart FastAPI. Sign in with the oversight role (rules:publish capability), then open Rule settings / Decision rules. Ordinary clinicians and administrators cannot publish. No account is granted new privileges by this feature.

Available settings:
- Repeated concerns: sessions checked W, and sessions with the concern K. Both integers from 2 to 10; K cannot exceed W.
- Rating increase: minimum increase D, integer 1–10. The comparable-rating date window remains fixed at 30 days.
- Medication changes: lookback L, integer 1–90 days, inclusive.
- Overdue follow-up and required documentation: enable/disable only; their conditions/template are fixed.

All five rules can be enabled or disabled. A nonblank reason is required. Publishing creates a new version; it never updates a published revision. A stale expectedVersion is rejected. The PostgreSQL migration adds an UPDATE/DELETE-blocking trigger to rule_revisions. This protects ordinary database writes, not a database owner who disables the trigger. Re-enabling or reverting settings means publishing another version.

`app/rules.py` validates bounded parameters and permissions, records author/reason/history, and reads current revisions. `RuleHead` points to the current revision. `RuleRevision` retains each published settings snapshot. The initial version 1 is seeded by the migration. Publication locks the rule head, preventing two publishers from silently overwriting each other. Audit failures roll the transaction back. Boolean and fractional values are not accepted as integer parameters.

Indicator evaluations snapshot all current settings along with the confirmed inputs. The pure functions use those parameters, and results include the actual rule version/settings. A subsequent publication marks earlier evaluations stale without rewriting their original outcome or review decisions. Evaluation snapshots are consistent reads of all head/revision pairs. Disabled rules display Disabled with no calculated result and cannot be acknowledged/dismissed as a result. Historical runs retain their original enabled state.

The frontend gives each setting a plain label, displays bounds, and shows version history with author, reason and settings. A successful publish updates the page in place. Clinicians can inspect current rules through GET /api/v1/rules; publishers use GET /api/v1/oversight/rules and POST /api/v1/oversight/rules/{ruleId}/publish.

Verification: the existing 182 backend tests passed, plus 14 rule tests covering permissions, bounds, conflicts, history, disabled rules, freshness, real threshold behavior and audit rollback. Frontend type checking passed. An isolated PostgreSQL schema test verified concurrent publication (one success, one conflict) and immutable revisions; the schema was removed afterward. Active project rule settings were unchanged by testing.

Template-field customization is not included: the documentation template remains version 1. Reports, remaining access/assignment workflows, operations and deployment verification are separate milestones.
