# Frontend audit and fixes

Date: 5 November 2026. Baseline: `2cd42ea`. Scope: `frontend/` only.

The existing Plus Jakarta Sans, navy/jade navigation, workflow shortcuts and centered login remain the visual authority. This is an audit and repair of the operating interface, not a replacement design. Backend files were read to verify contracts; they were not edited. The older Notion implementation guide describes proposed contracts and superseded layout ideas; current source and the user's accepted design take precedence.

## Assessment

Implementation integrity: **pass with integration limitations**. Patient records, immutable note versions, extraction drafts and independent AI/fact review remain distinct. Permissions and resource scope shape available actions. The frontend now communicates failed, pending and unavailable states more accurately.

These are engineering assessments, not WCAG certification or measured Core Web Vitals scores.

| Dimension | Before / 4 | After / 4 | Evidence and limit |
| --- | --- | --- | --- |
| Accessibility | 2 | 3 | Native dialogs, unique labels, linked form hints/errors, required indicators, current tabs/steps, explicit failures. Full assistive-technology audit remains outstanding. |
| Performance | 2 | 3 | Aborted requests, serialized polling, batched lighting geometry reads, transform-based progress. No production performance profile was collected. |
| Responsive | 2 | 3 | Desktop/mobile route checks, 16px mobile form controls, 44px compact controls, bounded stepper scrolling, resilient long text. Other engines and full 200% text-scaling review remain outstanding. |
| Theming | 2 | 2 | Existing visual identity and semantic colors retained. Older literal colors still coexist with tokens; no new theme mode was introduced. |
| Implementation integrity | 2 | 3 | Verified success/error handling, permission-aware controls, shared patient context and current backend health contract. Several server workflows remain unfinished. |
| **Total** | **10 / 20** | **14 / 20** | **Good; remaining limits below.** |

## Findings and repairs

Fourteen verified groups: **1 P0, 7 P1, 6 P2**. The listed defects were repaired; limitations are recorded separately.

| Priority | Finding and user impact | Repair / source |
| --- | --- | --- |
| P0 | Synthetic draft GET responses removed edit actions, blocking the login-to-edit demonstration. | Align draft `allowedActions` with author, patient state and write capability in `src/app/demo-api/v1/[...path]/route.ts`. This remains a simulation, not a security test. |
| P1 | Destructive dialogs allowed background interaction, reused confirmation IDs and closed before async outcomes were known. | Shared native `components/modal.tsx`; `ConfirmAction` waits for the result, displays failure, blocks dismissal while pending and restores focus. Logout uses the same native containment. Relates to WCAG 2.1.1, 2.4.3 and 4.1.2. |
| P1 | Every 403 cleared an open patient view, potentially discarding edits after an unrelated denied action. | API events include the affected path; patient layout rechecks scope before clearing. The patient header and overview share `lib/patient.tsx`. Actual scope loss still clears protected content. |
| P1 | A previous route's resource could appear before its reload effect; repeated clicks could race before React updated pending state. | Key resource state by path, abort superseded requests and add an immediate action ref lock in `lib/hooks.ts`. |
| P1 | Failed archive/cancel requests could still show success or mark a job cancelled locally. | Only advance these states after acknowledgement; retain errors and retry context in patient overview and summary creation. |
| P1 | Read-only users saw indicator evaluation/review and summary/fact acceptance controls; metadata-only accounts saw clinical destinations. | Check write capabilities/resource actions; gate patient clinical children and tabs from the patient's allowed scope. Documents remain readable to authorized clinical readers. Backend authorization is still required. |
| P1 | Login could proceed after `/auth/me` failed, and a session-check outage left an unrecoverable workspace message. | Auth refresh rejects failures, exposes recovery state and prevents stale responses from restoring a session. Login distinguishes credential failure from connection/server errors and validates return paths. |
| P1 | Note links and transcription page navigation could discard unsaved changes. | Guard in-app links and browser reload/close in `lib/use-unsaved-changes.ts`; require saving before changing transcription pages or committing groups. Keep the session editor mounted by note identity. Browser Back/Forward is a remaining limitation below. |
| P2 | Form hints and server validation details were not connected to their controls. | Unique control IDs, explicit labels, `aria-describedby`, inline errors and required markers in `components/ui.tsx`; actionable field-error summaries remain visible. Relates to WCAG 1.3.1 and 3.3.1–3.3.2. |
| P2 | Small compact controls and sub-16px mobile inputs hindered touch use; workflow steps could overflow. | Shared touch sizes, readable inputs, local stepper scrolling and wrapping rules in `globals.css`. The first patient step is no longer marked complete while its name is empty. |
| P2 | The real `{status: "ok"}` health payload rendered empty service badges; missing endpoints looked like missing clinical records. | Optional health detail types, explicit API status, unknown LLM availability copy and `FEATURE_UNAVAILABLE` state in transport/UI. |
| P2 | Timer polling could overlap, update a departed screen or silently stop. | Recursive polling with abort/cleanup, retained job identity and explicit status retry. Source selection locks during processing; report selection locks while preview is pending. |
| P2 | Pointer lighting interleaved layout reads/writes; upload progress animated layout width. | Batch geometry reads and use `scaleX` for progress, retaining textual percentage and progressbar semantics. The detector's single `layout-transition` warning was verified and fixed; no unrelated style rewrite was performed. |
| P2 | Frontend README claimed the backend directory was empty and all paths were merely proposed. | Update `README.md` with implemented server areas, remaining contracts and reproducible frontend checks. |

## Verification

- `npm test`: seven transport tests for same-origin cookies/cache settings, multipart boundaries, validation details, missing features versus missing records, path-scoped denials, authentication expiry, connection errors and aborts.
- `npm run typecheck` and `npm run build`: frontend type and production compilation checks.
- Browser batch: twenty route/role cases at 1440px and 390px (**40 cases**), checking horizontal overflow, visible form labels and 16px mobile form controls. Covered login/activation, directory/create/profile, session create/read, documents/extraction/review, summaries, indicators, reports, people, assignments, system health, audit, grants and rules.
- Targeted assertions across desktop login fit, failed session verification, field validation, native modal focus/inert background and restoration, failed archive acknowledgement, editable demo drafts, unsaved-link protection, rejected-save preservation/retry, read-only review controls, metadata-only access, current health response, mobile target size and reduced motion.
- Final confirmation also checked immediate error contrast, Escape dismissal, opaque menu entrance and malformed return-path fallback.
- Batched desktop/mobile screenshots compared with the incumbent UI. Error feedback is immediately visible; mobile menu entrance keeps its surface opaque.
- Impeccable detector run once across the frontend. Its sole finding was the progress width transition, repaired as described above.

Browser checks used synthetic frontend data and simulated failure/health responses. No live FastAPI database session, real clinical data, or OCR/LLM job was exercised. This verifies frontend behavior and representative contracts, not backend authorization, persistence or recovery acceptance.

## Remaining limitations

- Browser Back/Forward history navigation is not intercepted by the unsaved-link guard. Save or confirm edits before using history controls. A complete navigation-blocking solution needs a deliberate App Router strategy and cross-browser testing.
- The current backend implements authentication, accounts, patient profiles/timeline/follow-ups, session notes, document storage/extraction and job listings. AI summaries/facts, indicators, report generation/export, grants, handovers, bounded rule publication, and backup/restore still require their server endpoints. The frontend presents unavailable states; it does not implement these services.
- Existing token/literal-color drift remains a future theming task. The current brief specifies the established palette and motion, so this pass preserves them.
- Broader acceptance still needs real-backend permission/revocation/version tests, screen readers, additional browsers, 200% text scaling, long-lived job recovery and production performance measurements.

## Positive foundations

Keep the cookie-based same-origin transport, no browser storage for private drafts, server-versioned serialized note saves, explicit unknown values, source links, capability-based navigation, separate AI/fact approvals, and reduced-motion preference handling.

If continuing the UI work, prioritize `impeccable harden` for history and live-backend edge cases, `impeccable adapt` for additional device/text-scaling coverage, `impeccable extract` for token consolidation, then `impeccable polish` after those requirements are verified. No additional visual redesign is needed for this repair pass.
