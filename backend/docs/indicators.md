# Follow-up indicator (DT-03)

## What it does

Open a patient, choose Indicators, and select Evaluate now. The backend checks each explicitly recorded follow-up task against today's date in the configured clinic timezone. No model is called.

- Open and due before today: Overdue (matched).
- Open and due today or later: Not overdue (not_matched).
- Open with no due date: Cannot determine (not_evaluable).
- Completed or cancelled: Not overdue, including when the old deadline has passed.
- No tasks: Cannot determine; there is no task to evaluate.

Example: a task due on 5 November that remains open on 6 November matches the rule. Completing the task makes the saved evaluation stale. Evaluating again creates a new result saying the task is closed. The earlier result remains available in the evaluation selector.

Acknowledge records that the clinician saw the reminder. Dismiss records that they do not intend to act on that reminder. Neither changes the computed outcome or completes the follow-up. Each result can be reviewed once. Comments and reviewer identity are retained.

## Code and persistence

`app/api/indicators.py` contains the pure `follow_up_result` decision function, scoped API routes, input snapshots and freshness checks. `IndicatorRun` stores encrypted inputs and computed results separately from encrypted review decisions. Reviews leave the original input/result payload unchanged. This is enforced by the API; there is no database-level immutable-row trigger in this milestone.

Rule version 1 uses the fixed DT-03 condition from documentation section 8.6. There are no adjustable parameters for this rule. Inputs are actual clinician-created FollowUp records, not AI-proposed follow-up facts. Source links lead to the patient's Follow-ups section.

The current date, rule version and complete task snapshot form a fingerprint. Changing a task, adding a task, or reaching a new clinic date makes earlier results stale. Evaluating unchanged inputs reuses the latest run and preserves its reviews. Patient locking serializes evaluation with task writes and reviews. Review requests include the evaluation ID and expected version; conflicts return 409.

`GET /api/v1/patients/{id}/indicators` returns the latest run.
`POST .../indicators/evaluate` evaluates recorded tasks.
`POST .../indicators/{indicatorId}/review` records acknowledge/dismiss with evaluationId, expectedVersion and optional comment.
`GET .../indicators/history/runs` lists the 50 most recent runs.
`GET .../indicators/history/runs/{runId}` reads a retained run with review actions disabled.

Clinical reads require patient scope. Evaluation/review additionally requires indicators:write. Archived patients are read-only. Administrative roles alone cannot read clinical indicator results. Successful actions are audited without including clinical text in the audit entry.

## Setup and checks

Run `alembic upgrade head`, then restart FastAPI. No new dependency or background worker is needed. The frontend Indicators tab is connected to the real API and updates results in place after review.

Tests cover yesterday/today/tomorrow, missing/invalid dates, closed tasks, encrypted persistence, repeated evaluation, stale results, review conflicts, access isolation, archival and audit rollback. The live PostgreSQL test verifies concurrent evaluation, review and retained history through the frontend proxy using disposable synthetic records.

## Remaining indicator work

DT-01 repeated concerns, DT-02 rating increases and DT-03 follow-up outstanding are implemented. DT-04 medication changes and DT-05 required information are also implemented with their default settings. They need appropriate confirmed typed inputs and/or a published template. Concern codes, named numeric scales and medication-change status must not be guessed by parsing free-text summaries. Bounded rule publication and those typed-input review controls are subsequent work. Reports, administrative access workflows, backup/restore, authorized deletion and deployment verification remain separate milestones.


## Confirmed ratings and DT-02

The requirements document specifies this feature in FR-11 and section 8.6, decision table DT-02. The explicit rating-entry form is an implementation choice for obtaining clinician-confirmed typed inputs without guessing from AI prose.

Apply migration `0010_ratings`. Under Patient → Indicators → Confirmed ratings, select a current finalized source note, name the documented 0–10 scale, enter its value and specify what higher means. Confirm that you checked the note. The date comes from the selected note, not a separate guessed date. A historical value mentioned in today's note must not be entered as today's rating.

The rule groups scale names case-insensitively after trimming/reducing whitespace; it does not infer synonyms or equate different questionnaires. It uses the latest two confirmed current-source ratings for each scale. This implementation interprets the 30-day window as both ratings falling within the inclusive 30 days before the clinic evaluation date. Higher must mean more difficulty for both. Latest minus previous >= 2 matches. The threshold is currently fixed at the documented default, version 1; bounded rule publication is still pending.

Missing pairs, unknown/approximate dates, incompatible direction and ambiguous date ties produce Cannot determine. Superseded-source and withdrawn ratings are excluded and counted in the source snapshot. A changed rating, finalized source amendment or new evaluation date makes prior evaluations stale. Rating changes currently mark the whole saved evaluation run stale, including its follow-up results, so users reevaluate the complete input snapshot.

A mistaken confirmed rating is withdrawn with a reason, not overwritten. Its original encrypted payload is retained. Record a replacement afterward. There can be only one active rating per source note and normalized scale name. Different notes on the same day can hold ratings, but the comparison refuses to invent their ordering.

Code: `app/api/ratings.py` contains the scoped entry/withdrawal APIs and pure comparison function; `app/api/indicators.py` includes rating inputs/results in saved evaluations; `components/ratings-panel.tsx` implements the confirmation form. Creation and withdrawal require indicators:write and patient assignment. Archived patients remain read-only. Values are bounded to 0–10 and non-finite values are rejected. These are documentation indicators, not validated clinical cut-offs or diagnoses.

API: GET/POST `/api/v1/patients/{id}/ratings`; GET `/ratings/sources`; POST `/ratings/{ratingId}/withdraw` with expectedVersion and reason. Evaluation remains POST `/indicators/evaluate`.

Verification: 143 backend tests passed, including delta/date boundaries, different scales, unknown dates, withdrawal, amended sources, encryption and access checks. Frontend type checking passed. The live test confirms source-note creation, rating confirmation, a 4→6 matched result and concurrent evaluation through the frontend proxy and PostgreSQL.


## Confirmed concerns and DT-01

Apply migration `0011_concerns` and restart FastAPI. Open Patient → Indicators → Confirmed concerns. Choose a finalized note, select a category, classify whether it is present/denied/uncertain, when it applied and whom it concerns, and copy a supporting quotation. Confirm after checking the source. Repeat for the relevant sessions, then Evaluate now.

The initial controlled categories are sleep difficulty, anxiety, low mood, concentration difficulty, fatigue, irritability, social avoidance and work-related stress. They are implementation categories, not a diagnostic taxonomy specified by the document. Categories outside this list are not currently supported; do not map unrelated concerns into a category merely to obtain a result.

DT-01 uses the documented defaults W=3 and K=3, rule version 1. The window is chosen from all current finalized sessions with known dates, not just notes containing a recorded concern. Only confirmed present/current/patient entries count. Denied, historical and other-person entries do not count; missing/uncertain classifications produce Cannot determine instead of treating missing data as a negative finding. Unknown/approximate dates and superseded sources are excluded and reported in coverage.

Sessions are identified by note ID, so multiple entries cannot increase one session's count. Three same-day notes are three distinct recorded sessions; if a same-day tie crosses the three-session boundary, the rule returns Cannot determine rather than choosing arbitrarily. Finalizing an additional note can therefore make a prior evaluation stale even if no concern was recorded on that note.

One active concern per source/category is allowed. Wrong entries can be withdrawn with a reason and replaced. Original encrypted values are retained. Source finalization, permissions, archival and expected-version checks follow the rating workflow. Quotation checking verifies that text exists in the source; clinical interpretation still requires clinician review. AI fact confirmation does not automatically create these typed concern records.

Code: `app/api/concerns.py` contains entry/withdrawal routes, current-session snapshots and the pure repeated-concern evaluator. `app/api/indicators.py` retains concern/session input snapshots with evaluation results. `components/concerns-panel.tsx` provides entry and withdrawal controls. No new background worker or model dependency is required. Rule-parameter publication remains pending.

Verification: 155 backend tests passed. Tests cover 3/3, denied/historical/other-person exclusion, uncertain/missing input, date coverage, duplicates, same-day boundaries, quotation validation, source amendment, access isolation and withdrawal. Live PostgreSQL/frontend-proxy verification created three synthetic source notes and confirmed concerns, verified a matched result, checked existing rating/follow-up workflows and removed the temporary records afterward.


## Documented medication changes (DT-04)

Apply migration `0012_medications` and restart FastAPI. Under Patient → Indicators → Confirmed medications, select a finalized source note, enter the medication name as documented, choose changed/no change/uncertain, and copy a supporting quotation. Confirm that the entry describes the patient's medication status at that session, not an older event, another person or a future plan. The application validates quotation presence, not its clinical interpretation.

DT-04 version 1 uses the documented default L=30 days, inclusive of both boundary dates. Each current confirmed entry receives its own result: changed within the window matches; explicitly no change or a dated change outside the window does not match; uncertain status, unknown/approximate date or future date is not evaluable. Separate results preserve partial coverage. No entries is not evaluable, never evidence that no medication changes occurred. No medication recommendations or inferred doses are generated.

The source date is the documentation date. The rule describes a change documented within the window, not proof of when the patient actually changed medication. Entries not about the source session should not be confirmed through this form. Correction uses withdrawal with a reason followed by a replacement entry; the original encrypted payload remains stored. Superseded-source and withdrawn entries are excluded, and saved indicator runs become stale when inputs change.

Code: `app/api/medications.py` implements scoped confirmation/withdrawal and the pure evaluator; `components/medications-panel.tsx` provides the controls. APIs are GET/POST `/patients/{id}/medications`, GET `/medications/sources` and POST `/medications/{id}/withdraw` under `/api/v1`. Access, archive, source-version, duplicate and expected-version checks follow the concern/rating workflows. Confirmations, reads and withdrawals are audited.

Verified with 168 backend tests and frontend type checking. Tests cover the 30-day boundary, missing dates, uncertain status, excluded sources, encryption, permissions and history. A live synthetic PostgreSQL/frontend-proxy check exercised medication confirmation and all four currently implemented indicators. Threshold publication and the fifth rule remain pending.


## Required documentation (DT-05)

No new database migration or dependency is required for this milestone. Restart FastAPI and choose Evaluate now in the Indicators tab. Existing evaluations become stale when the expanded input snapshot is introduced; their original results remain readable.

The built-in Session note template, version 1, follows the documented default: a date status and at least one non-empty Concern, Observation or Intervention entry. A recorded unknown date status is valid. Known/approximate status needs a valid date. Free text and Medication as reported alone do not satisfy the structured-section requirement. Blank entries do not count. This is completeness, not a judgment about clinical quality or an absence of symptoms.

The scope is all current finalized notes, including reviewed imported history. Drafts and superseded originals are excluded. Imported free-text history may be flagged for missing structured entries; corrections follow the existing amendment workflow. No finalized note is edited automatically. No eligible notes produces Cannot determine. A finalized amendment changes the input fingerprint and makes saved evaluations stale; a new evaluation checks the amendment while retaining earlier results.

`app/services/documentation.py` creates the source-version and completeness snapshot, stores the template definition in the evaluation inputs, and produces per-note missing-field lists, explanations and source links. It reuses the encrypted evaluation/review/history and patient-scope infrastructure. The template is built in, not yet configurable or published through the oversight UI. Rule publication and configurable templates remain pending.

Verification: 182 backend tests and frontend type checking passed. Tests cover the required sections, medication-only/free-text notes, whitespace, known/unknown/approximate dates, draft exclusion, finalized amendments, retained history and access isolation. A live PostgreSQL/frontend-proxy test verified a missing structured section and its correction through amendment alongside the other four rules; temporary synthetic records were removed.


## Published settings

The fixed-default descriptions above describe the initial version. Bounded rule publication is now available for W/K, D and L, plus enable/disable for all five rules. Evaluations use the current published versions and retain their snapshots. The documentation template fields remain fixed. See [rule settings](rule-settings.md).
