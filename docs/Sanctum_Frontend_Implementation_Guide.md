# Sanctum frontend implementation guide

**Audience:** Frontend developer using Next.js and TypeScript  
**Project:** Team 01 Software Engineering and Management semester project  
**Status:** Implementation guide based on the agreed SRS; routes and API shapes below are proposed contracts to finalize with the backend developer.  
**Design revision:** 25 October 2026. The visual and interaction decisions in Sections 2, 4 and 5 incorporate the accepted frontend design iterations and take precedence over earlier sidebar or decorative-dashboard suggestions. API and clinical requirements remain subject to backend enforcement.  
**Source of requirements:** `Sanctum_Concise_SRS_and_Design.pdf` (version 1.1), especially FR-01–FR-50, UC-01–UC-17 and Chapter 7.

## 1. What you are building

Sanctum is a clinic-controlled application for therapy records. Its main user is an individual therapist, psychologist or counsellor. A clinic can have multiple practitioners, an administrative user and a person with explicit clinical oversight. A solo practitioner can have the relevant capabilities on one account. The frontend must support patient records, session notes, practitioner handover, reviewed English handwritten-document import, local AI suggestions, deterministic documentation indicators, reports, audit and operations.

The complete clinical journey is:

```text
Sign in → find an assigned patient → create a session → save and finalize a note
        → review a historical scan if present → generate a local AI draft
        → review the summary and confirm suggested facts separately
        → evaluate indicators → preview and export a report
```

Clinicians decide what to approve. The UI must present OCR and AI output as drafts until reviewed, preserve source links, distinguish an unknown value from a negative finding, and never describe an indicator as a diagnosis or validated risk score. Development and demonstrations use synthetic patient data only. The current semester scope excludes patient portals, appointments, billing, synchronization between installations and cloud inference.

The frontend is an interface to the FastAPI backend. The backend owns authentication, permissions, patient scope, persistence, note versions, OCR and LLM jobs, rule evaluation, audit, encryption, backup and PDF creation. Hiding a button in Next.js is a usability measure; the backend decides whether an action is permitted.

## 2. Permissions and navigation

Use **capabilities returned by `GET /api/v1/auth/me`**, not hard-coded role-name comparisons. A person can hold more than one capability. In particular, administrative permission does not grant access to clinical notes, scans, summaries or reports.

| Capability | Navigation and actions |
| --- | --- |
| Practitioner with an active patient assignment | Read permitted patient history; write/finalize/amend permitted notes; upload and review imports; generate/review AI; evaluate/review indicators; preview/export reports. |
| Administrative user | Create/deactivate accounts; see minimum patient identity and assignment information; assign/handover patients; inspect operational audit; run backup/restore. No automatic clinical content access. |
| Clinical oversight holder with patient scope | Read only the explicitly granted clinical scope; approve clinical grants when designated; publish bounded rule versions when designated. |
| Combined administrative and scoped clinical oversight user | May perform actions requiring both permissions, including deliberate patient deletion, after reauthentication and a reason. |

Build an app shell with a stable, compact **floating horizontal navigation header**. Use visible icon-and-text links on desktop; use an explicit Menu button and a dropdown on smaller screens. Do not restore the hover-expanding sidebar or an icon-only collapsed rail. Put current-account identity and sign-out in an accessible account menu. Show database/storage/OCR/LLM details on System health and dependency-specific task screens, rather than repeating global service badges. Only show links relevant to effective capabilities. The patient header should display the patient ID/name, assignment, archive state and actions. After handover or grant revocation, the next request must recheck access; clear the now-inaccessible patient view and show access denied. A queued job result must never be shown just because the user started the job earlier.

## 3. Route map

These are **19 routes, not 19 separate visual systems**. Patient pages share one layout and reusable components. A tab, drawer or dialog is suitable when a task does not need its own URL. All patient routes use opaque IDs in the URL, never patient names or clinical text.

| Route | Page purpose | Who can open it | Use cases |
| --- | --- | --- | --- |
| `/login` | Sign in and explain session or service state | Anyone | UC-01 |
| `/activate` | One-use account activation or credential reset | Invited/reset user | UC-02 |
| `/patients` | Scoped patient directory | Practitioner or admin, with different fields | UC-04 |
| `/patients/new` | Create patient and establish initial assignment | Authorized admin or clinician | UC-04 |
| `/patients/[patientId]` | Patient profile, timeline, follow-ups and history | Assigned practitioner or scoped oversight; limited admin metadata view | UC-04, UC-05, UC-07, UC-17 |
| `/patients/[patientId]/sessions/new` | Start a session note | Assigned practitioner | UC-05 |
| `/patients/[patientId]/sessions/[sessionId]` | Edit draft, read finalized versions or add amendment | Permitted practitioner or oversight | UC-05, UC-06 |
| `/patients/[patientId]/documents` | Upload and manage historical files and OCR jobs | Assigned practitioner | UC-08 |
| `/patients/[patientId]/documents/[documentId]/review` | Correct page transcription and commit historical session mapping | Assigned practitioner | UC-09 |
| `/patients/[patientId]/summaries/new` | Select eligible sources and request a session summary or briefing | Assigned practitioner | UC-10 |
| `/patients/[patientId]/summaries/[summaryId]` | Review AI summary and proposed facts separately | Assigned practitioner | UC-11 |
| `/patients/[patientId]/indicators` | Evaluate, explain and review decision indicators | Assigned practitioner | UC-12 |
| `/patients/[patientId]/reports/new` | Select, preview and export a structured PDF report | Practitioner or scoped oversight | UC-14 |
| `/admin/users` | Accounts and credential administration | Administrative capability | UC-02 |
| `/admin/assignments` | Patient assignments and handovers | Administrative capability | UC-03 |
| `/access/grants` | Request, approve/deny and inspect clinical grants | Admin requester or designated clinical approver | UC-02 |
| `/oversight/rules` | Configure and publish five bounded decision tables | Designated clinical oversight publisher | UC-13 |
| `/audit` | Search role-filtered operational events | Admin; clinical context only within clinical scope | UC-15 |
| `/admin/operations` | Health, job status, backup and restore | Administrative capability | UC-16 |

`/` may redirect to `/patients` after authentication. Add shared `loading`, `error`, `not-found` and access-denied views. Permanent deletion is a restricted action in the patient page's **Danger zone**, not an everyday navigation item.

## 4. Page specifications

### 4.1 Login and activation — `/login`, `/activate`

**Presentation:** a full-screen, single-column login experience on a restrained navy/teal abstract background. Center a large Sanctum logo and wordmark above the sign-in card. The brand is the main landing-page heading; a short definition explains the product: “Therapy records, organized.” Follow it with “Notes, documents, and AI drafts you review.” Keep supporting copy at 16 px with strong contrast and a narrow, balanced line length (approximately 30–38 characters). Avoid long explanatory sentences. Break account/password help into two short lines; present optional demo usernames and password as labelled rows. Do not use a left/right split, a miniature corner-only brand, a promotional feature wall, or an additional navigation bar before authentication. Use a wide card (approximately 570 px maximum) with comfortable field widths. Keep the default desktop page within 1280×720 and 1366×768 viewports; keep error feedback visible rather than clipping it to enforce a fixed height. Mobile and expanded optional content may scroll naturally.

**Login fields and actions:** username, password, show/hide password, sign in, generic invalid-credential message, local service availability, forgotten/reset instructions supplied by the clinic, and an expired-session message. In synthetic demo mode, show a clearly labelled, keyboard-accessible disclosure for demo credentials; keep it separate from production messaging. Successful login loads `/auth/me` and sends the user to `/patients` or a validated local return path. Logout invalidates the server session and clears protected frontend state. The server enforces inactivity and absolute expiry; the SRS targets 15 minutes and 8 hours respectively. Show a warning for unsaved work before a manual logout when the session is still valid. Do not claim an unavailable LLM means login failed.

**Activation:** accept the one-use token through the backend's agreed flow; collect and confirm a new password; show token expired/used states without revealing account details unnecessarily. Do not store credentials or tokens in browser storage. The backend rate-limits failed authentication and invalidates sessions on credential changes.

**Done when:** an unauthenticated protected request leads to sign-in; a deactivated account cannot sign in; logout/expiry clears clinical content and the next protected request fails. Covers FR-01, FR-02, FR-06 and FR-46.

### 4.2 Patient directory — `/patients`

Provide search, active/archived filter, list or table, loading/empty/error states, clear create action and a link to each authorized patient. A practitioner sees only assigned or explicitly scoped patients. An administrative-only user sees minimum identity and assignment metadata, without presenting concerns or clinical history. Do not place patient names in URL query parameters or general logs; agree on a body-based search endpoint if the backend cannot safely handle search terms elsewhere. The archive filter must reveal archived records to authorized users without placing them in the default active list.

**Core workflow shortcuts:** place a compact set of genuine action tiles above the directory, with distinctive but restrained colour, clear icons and short functional labels. The five clinical entries are:

| Shortcut | What selecting a patient opens | Capability gate |
| --- | --- | --- |
| New session | `/patients/[patientId]/sessions/new` | `clinical:read` and `clinical:write` |
| Import & OCR | `/patients/[patientId]/documents` | `clinical:read` and `documents:write` |
| AI summary | `/patients/[patientId]/summaries/new` | `clinical:read` and `summaries:write` |
| Indicators | `/patients/[patientId]/indicators` | `clinical:read`; evaluation/review retain their own permissions |
| Build report | `/patients/[patientId]/reports/new` | `clinical:read` and `reports:write` |

These buttons must do real work. From the global directory, open a patient-selection dialog for the chosen workflow. Fetch the active patient list afresh, filter to patients whose effective `allowedActions` include `clinical:read`, support local name/ID search, and navigate to the selected patient's actual task route. Do not send every tile to a `#patient-list` anchor, guess a patient, or start generation/export as a side effect of selecting the tool. Provide loading, empty, denied/error and retry states. Keep search text out of URLs and storage. Use a native modal dialog or equivalent focus containment, Escape dismissal and focus restoration. Every destination still rechecks access through the backend.

Administrative-only accounts receive appropriate clinic tools (accounts, assignments, access requests, system health), never clinical tool tiles. Combined and oversight capabilities remain additive; hide unavailable actions rather than inventing access.

**Directory layout:** keep Patients and Add patient as the page header; put search, active/archived filter, refresh, result count and the actual records immediately below the workflow shortcuts. Use a readable table on desktop and a compact stacked record layout on mobile. On small screens, condense workflow tiles into a two-column button grid, keep the tool names/icons visible and omit secondary tile captions so records start sooner; a final unpaired action can span the row. Show name, opaque ID, practitioner assignment, status and Open record. Do not reintroduce greetings, “Your home base”, “A clear view of your clinic”, “Scoped”/“Local” statistic cards or a second generic welcome banner.

**Done when:** an unauthorized patient never appears in search results; archived patients can be found with the filter; the admin view contains no clinical fields. Covers FR-04, FR-08 and FR-09.

### 4.3 New patient and patient workspace — `/patients/new`, `/patients/[patientId]`

**Create:** required display name, optional validated demographics, and initial assignment. Show field-level validation, including empty name and future birth date. The backend generates the patient ID and records creator/time. Keep additional clinical content out of the administrative form.

**Patient workspace:** use a persistent header and tabs or sections for **Timeline, Profile, Sessions, Documents, Summaries, Indicators, Reports and Follow-ups**. Only fetch clinical panels when access is granted. Profile editing uses the backend's allowed fields and expected version. Archive/reactivate controls preserve records and assignments. Follow-up tasks have title/details, optional due date, open/completed/cancelled state and source/provenance. An open task without a due date must not be labelled overdue.

**Workspace density:** preserve patient identity/ID, assignment and state once in the header. Use compact tabs for the actual clinical areas and a short metadata strip for date of birth, record-event count, open-follow-up count and archive/reactivate. Keep timeline and follow-ups easy to reach. Do not duplicate all tabs as large “Next step” cards or repeat the header data in a second Profile panel. A summary label or counter must represent real data.

**Timeline:** show dated sessions, historical imports, amendments and reviewed summaries in order. Display the clinical event date separately from the entry or upload timestamp. Put unknown-date historical entries in a clearly labelled **Undated** group. Include filters by date/type, original author, current/superseded/withdrawn status and links to exact source versions. Source links recheck permission. Provide earlier note, import, summary, fact and indicator review history where permitted.

**Danger zone:** show permanent deletion only when the backend reports both administrative and patient-scoped oversight permission. Show affected data, external-copy limitation, reauthentication, reason and explicit confirmation. While deletion is in progress, block further patient actions and show retryable cleanup state if the backend reports failure.

**Done when:** a historical import with unknown date is not placed at its upload date as a clinical event; an admin-only account cannot open clinical panels; prior authorship remains visible after handover. Covers FR-07–FR-09, FR-13, FR-38, FR-41 and FR-47.

### 4.4 Session editor and version viewer — session routes

**New/editable draft:** session date/status, free text, concerns, observations, interventions, medication information as *reported*, and follow-up tasks. Represent assertion and time accurately: present, denied, possible or unknown; current or historical. Unknown is never converted to false or zero. Support explicit Save and periodic autosave. Show `Unsaved changes`, `Saving…`, `Saved at [time]`, `Save failed` and `Conflict` according to **server acknowledgement**, not merely a local timer. Serialize saves or reconcile responses using expected versions so an old response cannot mark newer local changes saved.

**Finalize:** review the current content, validate that some note or structured content exists, then send the expected version. Once finalized, render the version read-only. **Amend:** collect new content and a reason, create a new attributed version linked to the original, show both in history and mark dependent current summaries/indicators/reports stale. A reviewer must never appear to edit the original author's finalized words in place.

**Conflict:** on `409`, preserve the user's unsaved local text in memory, show the latest saved version alongside it, and require an explicit choice to copy/reconcile and retry. On loss of network acknowledgement, show `Save not confirmed`; do not silently claim success. OCR/LLM failures must not prevent manual note save.

**Done when:** the core journey works through real API calls: login → assigned patient → new session → save → finalize → see timeline item. Refresh and verify persistence; race two draft updates and ensure the stale one cannot overwrite. Covers FR-10–FR-14 and NFR-09–NFR-10.

### 4.5 Historical documents — `/patients/[patientId]/documents`

Show the patient identity before upload, select PDF/JPEG/PNG, display published limits (proposed: 25 MB, 20 pages, 25 megapixels per decoded page), upload progress, document list and original/download action. For each document show uploader, upload time, page count, review state, OCR job state, per-page progress, failures and available retry/cancel. Display a duplicate warning **within this patient only**; allow a justified duplicate when the backend permits it. A wrong-patient file needs a deliberate **Withdraw** action with consequences for dependent outputs. Never present OCR text as approved history at this stage.

On OCR failure, keep the original accessible and explain that manual record work remains available. Retry a job as a linked attempt; cancelling must not create historical sessions. Original pages and thumbnails must always be requested through protected endpoints.

**Done when:** a valid multipage file is accepted; malformed/oversized/unsupported files receive safe errors; the original remains available after failed OCR; an unreviewed document cannot be selected as an AI source. Covers FR-15–FR-17 and FR-20–FR-22.

### 4.6 Transcription review — `/patients/[patientId]/documents/[documentId]/review`

Use a two-column layout: protected original page on one side, editable OCR transcription on the other. Provide page navigation, zoom, keyboard access, raw versus corrected text distinction, uncertainty/unreadable markers and saved review state. Let the practitioner group pages into one or more historical sessions. Before commit, review the selected patient, corrected text, included/excluded pages, session grouping and **date status** (known, approximate if supported, or unknown). Never silently use upload time as session date or invent an original external author.

Allow partially reviewed pages to remain pending; they stay excluded from downstream generation. Confirmation commits reviewed text and session mapping together. A stale review version produces a conflict with local corrections preserved. Show exact page links in the resulting timeline; withdrawn originals remain visibly noncurrent according to backend policy.

**Done when:** a single PDF can become two confirmed historical sessions, an unknown date remains unknown, and only the confirmed versions appear among eligible summary sources. Covers FR-18–FR-20.

### 4.7 Summary source selection and job — `/patients/[patientId]/summaries/new`

Offer **single-session summary** and **longitudinal briefing**. List only finalized current note versions and confirmed historical transcription versions. Selection can be explicit sessions or a date range. Before submission show selected dates, exact source coverage, source count and size limits (proposed: up to 30 sessions or 30,000 input words). Refuse an over-limit selection with guidance or clearly display documented batching; never silently omit a session. Submit a local job and display queued, running, completed, failed and cancelled states, including bounded retry/cancel. Show separate OCR/LLM health; an unavailable LLM disables generation with an explanation while manual records remain usable.

The backend freezes source versions and validates model output. The UI should show model identifier, generation time and source manifest in a details panel, without claiming a rerun will produce identical prose. A source that changes during processing makes the draft stale or safely fails. Do not display model instructions found in imported text as application commands.

**Done when:** generation never overwrites a clinical note, unreviewed imports are refused, and a failed model job leaves all original records usable. Covers FR-23–FR-25, FR-29 and FR-31–FR-32.

### 4.8 Summary and fact review — `/patients/[patientId]/summaries/[summaryId]`

Show coverage and a review banner first. Each factual summary item must have an evidence link to its exact source version and passage or page. Opening a source uses the protected source viewer and keeps the review context visible. For the **summary**, offer **Accept**, **Edit and accept**, and **Reject**; preserve the generated original and each review action with actor/time. Rejection makes the draft ineligible for ordinary reports. Stale or invalid references block current acceptance until the backend refreshes the result.

Below the summary, show **suggested facts and descriptive labels as separate review cards**. Each card shows label, source, patient subject, assertion (present/denied/possible), temporality (current/historical/unknown) and proposed text. Offer **Confirm**, **Correct**, **Reject**, plus an explicit selected-batch confirm if implemented. Accepting the summary must not confirm any fact. Pending and rejected facts stay out of rule evaluation. The initial catalogue is SLEEP_CONCERN, WORK_STRESS, ACADEMIC_STRESS, FAMILY_CONFLICT, SOCIAL_CONCERN, MOOD_CONCERN, COPING_STRATEGY and FOLLOW_UP_ITEM; labels describe documented content and do not infer a disorder.

Keep review state and freshness separate: a previously accepted summary may later be `stale`. Its history stays readable, but it is excluded from current reports until regenerated and reviewed again.

**Done when:** all three summary actions persist; fact review remains independent; a denied concern is not displayed as confirmed present; every accepted factual item opens valid source evidence. Covers FR-25–FR-30.

### 4.9 Indicators — `/patients/[patientId]/indicators`

Provide Evaluate, evaluation history and cards for each published rule. On each card show **Matched**, **Not matched** or **Not evaluable**; show **Disabled** and **Stale** as separate states. Include rule version, actual conditions and values, source links, evaluation time and source coverage. Missing required input means `Not evaluable`, never `No concern` or `Normal`. Let the practitioner **Acknowledge** or **Dismiss** with an optional comment. This changes review state, not the computed condition. A later evaluation is a separate result.

The five rules are: repeated documented concern (default W=3 dated sessions, K=3; `2 ≤ K ≤ W ≤ 10`); increase on the same named 0–10 reported difficulty scale (latest comparable pair within 30 days, D=2; `1 ≤ D ≤ 10`); open follow-up whose due date is **before** the clinic's evaluation date; documented medication change within inclusive L=30 days (`1 ≤ L ≤ 90`); and missing required documentation fields. The UI displays the backend's versioned rule definition and explanation rather than recomputing these results independently. An open follow-up due today is not overdue under the specified rule.

**Done when:** pending/rejected/stale/wrong-patient/unreviewed inputs do not influence results; a missing rating is shown as not evaluable; dismissal does not erase the explanation. Covers FR-33–FR-34 and FR-36–FR-38.

### 4.10 Report builder — `/patients/[patientId]/reports/new`

Let the practitioner select sessions, approved current summaries and reviewed current indicators. Preview patient identification, event-date coverage, report author, selected exact source versions, review labels and exclusions. Pending, rejected, stale or unreviewed items appear in an **Excluded** explanation, not in the report body. The preview must be produced from the backend's report manifest. Export is an explicit second action. Before download, the backend rechecks current authority, source versions and review status; if a source changed or a handover revoked access, show `Report needs refresh` or access denied. Download the protected PDF. Do not send it by email or to a third-party service.

**Done when:** downloaded PDF matches the reviewed preview and identifies creator, time, coverage and review state; a concurrent source withdrawal blocks or refreshes publication. Covers FR-39–FR-40 and FR-50.

### 4.11 Users, assignments and clinical grants — administration routes

**`/admin/users`:** account list and create form with minimum details, separate capability display, issue one-use activation/reset credential, deactivate with warning that active sessions end while historical authored notes remain. Never show clinical content to an admin-only account.

**`/admin/assignments`:** choose patient, incoming active practitioner, primary or additional access, outgoing practitioner's access policy, any independent oversight grant and a required handover reason. Preview the change; submit using the current assignment version; on `409`, reload and require review. Show original note authorship after transfer. Outgoing users must lose revoked access on their next request, including original downloads and queued job results; previously exported copies cannot be recalled.

**`/access/grants`:** admin can request clinical scope; a designated clinical oversight approver can approve or deny it. Show patient scope, capability, requester, approver, reason, effective state and history. Prevent a user from approving their own elevation. Frontend gates must mirror backend permission, but the backend remains authoritative.

**Done when:** an administrative-only account can assign a patient but cannot open their note; inactive recipients are rejected; grants and handovers show attribution. Covers FR-02–FR-05, FR-48–FR-49.

### 4.12 Rule configuration — `/oversight/rules`

Show the five current rule definitions and version history. A designated clinical oversight publisher can enable/disable a rule or change only allowed parameters through bounded forms. Display parameter limits, examples and truth-table preview before publication; collect a reason; publish a new immutable version with author/time. Reject out-of-range parameters locally for usability and rely on backend validation as the final check. Do not offer arbitrary scripts. Old indicator results retain their prior rule version until reevaluation.

**Done when:** an admin-only account cannot publish, invalid bounds are rejected, and changing a threshold creates a new version. Covers FR-35 and FR-49.

### 4.13 Audit and operations — `/audit`, `/admin/operations`

**Audit:** bounded date range, actor and action filters; result, time, opaque target ID and request ID. Only follow a clinical reference after ordinary patient authorization. Administrative-only search must not reveal clinical note bodies, credentials, patient names outside scope or clinical explanations. Event rows are read-only.

**Operations:** separate health for database, storage, OCR and LLM and the feature each failure affects. Show import/generation job status without bypassing patient scope. For backup, show scope, manifest and verification state; for restore, require reauthentication, maintenance mode, package selection, integrity validation and an explicit final action. Wrong key, corruption, incompatible schema, missing deletion registry or insufficient space must appear as safe failures; the UI must not claim a failed restore succeeded. After a successful restore, old login sessions are invalidated.

**Done when:** an LLM outage affects generation but not note save; audit filters do not expose clinical bodies; a corrupt backup is refused without replacing active data. Covers FR-42–FR-46.

## 5. Shared component inventory

| Component | Reuse and essential behavior |
| --- | --- |
| `AppShell` and `CapabilityNav` | Floating horizontal navigation derived from effective capabilities; responsive menu; account/sign-out; no hover-expanding rail or duplicate workspace pills. |
| `WorkflowLauncher` and patient picker | Capability-aware real task shortcuts; fresh active scoped-patient lookup; keyboard-accessible modal; direct navigation to the selected workflow. |
| `PatientHeader`, `PatientTabs`, `Timeline` | Patient identity, assignment, archive status, dated/undated events and filters. |
| `StatusBadge` | Words plus colour for draft/finalized, pending/accepted/rejected, current/stale and all rule outcomes. |
| `SourceViewer` and `SourceLink` | Protected exact note/document version and page/passage; loading, withdrawn and denied states. |
| `SessionEditor` and `SaveState` | Free text, structured fields, follow-ups, server-acknowledged autosave and conflict resolution. |
| `VersionHistory` | Immutable originals, attributed amendments, reviewer actions and current version. |
| `UploadQueue` and `JobProgress` | Upload and per-page processing, queue/run/failure, retry/cancel. |
| `TranscriptionReview` | Original page alongside editable text, unreadable markers, grouping and confirmation. |
| `SummaryReview` and `FactReviewCard` | Separate summary and proposed-fact actions; evidence and source coverage. |
| `IndicatorCard` | Rule result, actual conditions, explanation, source references and review action. |
| `ReportManifestPreview` | Included/excluded versions and explicit export. |
| `ProtectedActionDialog` | Consequence, reason/reauthentication when needed, focus handling and double-submit prevention. |
| `ErrorState` | Consistent 401, 403, 404, 409, validation and dependency-outage UX. |

Use a calm, readable visual system. Prioritize dense but legible record content, strong hierarchy, source evidence and obvious states over decorative charts. Support keyboard navigation, labelled controls, visible focus, text alternatives for statuses, accessible error messages and focus restoration after dialogs. Use responsive layouts so the source viewer can stack on narrower screens. Keep English as the only supported project language this semester.

### 5.1 Current visual and UX direction

The target is a modern clinical workbench: visually distinctive, concise and useful. Removing filler must not leave an undifferentiated white form catalogue. Use hierarchy, intentional surfaces and genuine action controls to provide character.

- **Typography:** Plus Jakarta Sans throughout, self-hosted through `next/font`; no Inter or Roboto fallback as the visual identity. Keep the normal base at 16 px, form inputs at approximately 16 px, navigation at 14 px or above and meaningful supporting text around 13 px or above. Increase size before making a label faint. Use dark slate secondary text and visible placeholders on pale surfaces; target at least 4.5:1 contrast for normal text.
- **Brand:** a prominent centered logo/wordmark on login; a compact recognizable brand in the authenticated header. Login may carry a short factual product definition. The authenticated workspace emphasizes actions and clinical content.
- **Palette and surfaces:** a deep navy/green floating header, mint active navigation and a pale neutral workspace. Clinical workflow tiles can use distinct muted green, blue, violet, amber and slate treatments. Use restrained gradients, fine borders, approximately 12–23 px corner radii and subtle shadows. Avoid decorative charts, large empty hero banners, repeated frosted panels or excessive rounded pills.
- **Navigation:** stable desktop labels, clear active page, no expansion on hover. The responsive menu uses the same destinations. Keep account controls in one place. Do not add nonfunctional “Patient care” or “Local workspace” pills.
- **Useful emphasis:** the five workflow shortcuts expose the project's note → import/review → summary → indicator → report journey. Every action has a real destination or opens a patient/context selector. A short caption describes the action, rather than repeating a slogan.
- **Patient context:** opaque record IDs in URLs; patient names only in authorized content. Do not persist a “last selected patient” in browser storage. Recheck patient access on each task screen.
- **Interaction:** clear hover/focus states, 42–48 px primary touch targets, accessible dialogs and keyboard menus, reduced-motion support, loading/empty/error/conflict feedback. Do not use motion or faint text as the only cue.
- **Shared effects:** extend the workflow tiles' navy/jade surfaces, mint edge highlights and jewel-toned icons across navigation, primary actions, tabs, forms and dialogs. Keep reading panels pale with restrained pointer lighting; lift interactive cards and buttons rather than moving clinical content on hover. Use short, one-time entrances and hover sweeps, not continuous decorative animation. `effects.css` owns the shared tokens and treatments; `SurfaceEffects` delegates pointer tracking through one animation-frame-throttled listener without React state updates. Disable tracking and decorative motion for reduced-motion preferences and touch input, including when preferences change during use. Keep semantic warning/error colours distinct.
- **Density:** concise page titles, purposeful spacing, readable tables, compact metadata and status text. Keep clinical work above the fold where practical. Supporting instructions are retained when they explain a decision, a review requirement or a failure.
- **Truthful presentation:** “AI summary” opens reviewed-source selection; “Build report” opens preview/export; “Import & OCR” opens upload/review. A shortcut does not imply the backend, OCR model or local LLM is complete. Synthetic mode remains clearly identified. Human review, provenance, independent fact confirmation and stale-source exclusions remain mandatory.

The latest approved visual direction supersedes earlier examples of sidebars, split login layouts and decorative dashboard introductions in supporting material. Preserve the clinical requirements in this guide when adapting layout and wording.

**Style ownership:** `globals.css` contains the active base components, tokens and responsive layouts; `effects.css` contains shared lighting and motion. Import both once in the root layout. The legacy override stylesheet, sidebar/split-login rules and unused decorative cards have been removed. Add new styles to the relevant shared layer rather than reviving obsolete components or another parallel theme.

## 6. Data and state contracts to freeze with backend

All paths below are **proposed** and use the SRS `/api/v1` prefix. Agree on exact names, request bodies, response DTOs and error codes before implementing dependent pages. The backend should return `allowedActions` or effective capabilities with resource DTOs, plus opaque IDs and explicit version numbers.

| Frontend area | Minimum backend contract |
| --- | --- |
| Session | Login/logout/activation; `GET /auth/me`; session expiry; safe errors; `GET /health` with appropriately limited pre-login detail. |
| Patients | Scoped list/search, create/detail/update, archive/reactivate, allowed actions, assignment summary. |
| Sessions | Create/read; draft save with `expectedVersion`; finalize; amendment with reason; timeline and version history. |
| Documents | Multipart upload; protected original/page; document and OCR job status; corrected pages; confirm grouping; withdraw; retry/cancel. |
| Summaries | Eligible source list; generate/job status; read source-linked draft; review summary; independently review proposed facts. |
| Indicators | Published rule definitions; evaluate; list results/explanations; acknowledge/dismiss; rule version publication. |
| Reports | Resolve preview/manifest; protected export/download; refresh and stale-source errors. |
| Administration | Users and one-use credentials; assignment/handover; clinical grant requests/approvals; audit; backup/restore; deletion. |

Use a stable error envelope such as `{ code, message, fieldErrors?, requestId? }`. Agree on exact codes for `401` unauthenticated, `403` forbidden, `404` unavailable/unknown resource, `409` version conflict, validation errors and unavailable dependencies. An unauthorized patient/document/job ID must return no protected content. Do not infer permissions from a successful list load: each protected read, mutation, file download and job result is checked by the backend.

Represent independent state dimensions explicitly. Suggested frontend types (rename to match the backend):

```ts
type NoteState = 'draft' | 'finalized';
type JobState = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
type ReviewState = 'pending' | 'accepted' | 'rejected';
type FactState = 'pending' | 'confirmed' | 'rejected';
type Freshness = 'current' | 'stale';
type IndicatorOutcome = 'matched' | 'not_matched' | 'not_evaluable';
type Assertion = 'present' | 'denied' | 'possible' | 'unknown';
type Temporality = 'current' | 'historical' | 'unknown';
```

An edited-and-accepted summary is a review **action**, while its resulting review state is accepted. A finalized note with an amendment has a new current version; the previous version remains inspectable. `Disabled` is rule enablement, while `Stale` is result freshness. Store date-only clinical event dates separately from UTC timestamps. Unknown historical dates stay unknown. Display evaluation dates in the configured clinic timezone.

For every async mutation, disable accidental double submission and display the backend result. For draft autosave, track the local edit revision and last acknowledged server version separately. If a response corresponds to an older local revision, do not display `Saved` for newer text. A `409` must keep unsaved local text for explicit reconciliation. After a `401`, clear protected state and navigate to login; after a `403`, clear that resource's content and show access denied. A stale cache must not re-expose revoked data.

## 7. Next.js structure and privacy choices

Use the App Router with route groups such as `(auth)` and `(workspace)`; route groups organize files without adding URL segments. Page shells and uncomplicated initial reads can be Server Components, while editors, upload progress, review actions and dialogs are Client Components. If Next.js fetches protected data on the server, deliberately forward the server session to the trusted local backend and check current permissions at the data access point. If the browser calls the same-origin API directly, configure credentials and CSRF protection with the backend. Pick one consistent pattern with the backend developer. Current Next.js references: [route groups](https://nextjs.org/docs/app/api-reference/file-conventions/route-groups), [Server and Client Components](https://nextjs.org/docs/app/getting-started/server-and-client-components), [authentication](https://nextjs.org/docs/app/guides/authentication), and [fetch options](https://nextjs.org/docs/app/api-reference/functions/fetch).

Suggested organization:

```text
frontend/src/
  app/
    (auth)/login/page.tsx
    (auth)/activate/page.tsx
    (workspace)/layout.tsx
    (workspace)/patients/page.tsx
    (workspace)/patients/new/page.tsx
    (workspace)/patients/[patientId]/layout.tsx
    (workspace)/patients/[patientId]/page.tsx
    (workspace)/patients/[patientId]/sessions/new/page.tsx
    (workspace)/patients/[patientId]/sessions/[sessionId]/page.tsx
    (workspace)/patients/[patientId]/documents/page.tsx
    (workspace)/patients/[patientId]/documents/[documentId]/review/page.tsx
    (workspace)/patients/[patientId]/summaries/new/page.tsx
    (workspace)/patients/[patientId]/summaries/[summaryId]/page.tsx
    (workspace)/patients/[patientId]/indicators/page.tsx
    (workspace)/patients/[patientId]/reports/new/page.tsx
    (workspace)/admin/users/page.tsx
    (workspace)/admin/assignments/page.tsx
    (workspace)/access/grants/page.tsx
    (workspace)/oversight/rules/page.tsx
    (workspace)/audit/page.tsx
    (workspace)/admin/operations/page.tsx
  components/
    app-shell/  patients/  sessions/  documents/  summaries/
    indicators/  reports/  admin/  shared/
  lib/
    api/         # typed client, DTOs and error handling
    auth/        # current-user and capability helpers
    dates/       # clinic timezone and unknown-date formatting
  styles/
```

Keep protected clinical responses out of public/static caches and service-worker storage. Use fresh reads for authorization-sensitive pages and result access; review the chosen Next.js version's caching behavior explicitly. Do not put note bodies, patient names, document text, credentials or one-use tokens in `localStorage`, URL query strings, analytics, console logs or general error reports. Prefer local fonts/assets so the normal clinical workflow makes no external requests. Protected original files and PDFs come from authenticated endpoints, never a publicly served `storage/` folder. The clinic host serves the browser over trusted local HTTPS; internal model/database ports are not browser endpoints.

## 8. Build dependencies and checkpoints

Work in **integrated slices**. The backend and frontend can work in parallel after agreeing on DTOs, expected-version rules, status vocabulary and one synthetic patient story.

| Stage | You can build now | Backend dependency | Exit check |
| --- | --- | --- | --- |
| 0. Contract and shell | Route skeleton, theme, navigation, shared statuses, typed API client, synthetic fixtures | Agree `/auth/me`, patient/session DTOs and error envelope | Frontend runs; fixtures clearly marked; no clinical data in browser storage. |
| 1. Core slice | Login, patient list/workspace, session editor, save/finalize, timeline | Auth, scoped patients, sessions, note versions | Real end-to-end login → assigned patient → finalized note in timeline. |
| 2. Permissions and history | Amendment, archive, conflicts, admin assignment/handover, grants | Expected versions, handover, grant approval, version history | Outgoing practitioner loses access; `409` keeps local draft; authorship survives. |
| 3. Historical import | Upload, per-page job, two-column review, grouping and confirmation | Protected files, OCR job, transcription versions | Confirmed pages become timeline sources; pending pages remain excluded. |
| 4. AI review | Eligible source selection, generation progress, evidence-linked review and separate facts | Local LLM job, source-reference validation, review persistence | Summary acceptance does not confirm facts; source links resolve. |
| 5. Indicators and reports | Result cards, rule publisher, report preview/export | Rules and versioning, PDF manifest/export | Not-evaluable/stale states are clear; PDF matches preview. |
| 6. Operations and polish | Audit, health, backup/restore, deletion flow, keyboard and failure walkthrough | Audit and operational endpoints | All visible actions use real endpoints; negative paths and access denial work. |

The documentation/test contributor can run browser walkthroughs on synthetic fixtures while you integrate. Do not wait for the complete OCR or LLM model to build their screens: use a **contract-conforming fake response** during development, then connect the real local job before claiming completion. Do not leave a fake response silently active in the final demo. Freeze interface labels and status meanings with the team, then have the docs owner update the SRS/API diagrams if the implementation contract changes.

## 9. Frontend acceptance checklist

The following checks are the minimum proof that the frontend and backend work together. They do not replace the SRS's full T-01–T-50 tests.

- [ ] An admin-only user sees assignment metadata but cannot open a note, scan, summary, indicator or report through navigation **or direct URL**.
- [ ] Direct unauthorized patient, document, page, job and export requests show no protected content.
- [ ] Login, logout, expiry and deactivation clear protected UI state; manual logout warns about unsaved work while still signed in.
- [ ] The note editor only says `Saved` after server acknowledgement; concurrent edits produce a visible conflict without losing local text.
- [ ] Finalized notes are read-only; amendments show reason, author and prior version; dependent current outputs become stale.
- [ ] Timeline separates clinical event date from upload/entry date; unknown-date imports are in an Undated group.
- [ ] Upload accepts the supported media and shows safe failures, duplicate warning, progress, retry, cancel and withdrawal.
- [ ] OCR page review shows the original beside editable text; multiple session groups and unknown dates can be confirmed.
- [ ] Unreviewed OCR pages are absent from summary source selection and rules.
- [ ] Generation shows every selected source, coverage, queue/failure state and a safe disabled state when the local LLM is unavailable.
- [ ] Every generated factual item has a working exact source link; summary review and proposed-fact review are independent.
- [ ] Indicator cards distinguish matched, not matched, not evaluable, disabled and stale; acknowledgement/dismissal preserves the computed explanation.
- [ ] Report preview explains excluded items, export requires an explicit action, and stale or revoked content cannot be published.
- [ ] Handover, grant approval, rule publication, backup/restore and deletion reflect their special permissions and confirmation requirements.
- [ ] Core flows work by keyboard, with labels, visible focus, readable error text and status text independent of colour.
- [ ] The final demo uses synthetic data; each required page either calls a real endpoint or is explicitly reported as incomplete.

### 9.1 Design regression checks

- [ ] At desktop widths, the header shows stable navigation labels without collapsing/expanding or overlapping the account control; the mobile menu opens, closes with Escape and restores focus.
- [ ] At 1280×720 and 1366×768, the centered login brand, definition, wide form and default demo indicator fit without page scrolling. Standard sign-in errors remain visible; expanded optional content is allowed to scroll.
- [ ] At 390×844, login, directory, tool tiles and patient-selection dialogs fit the viewport width with no horizontal scrolling or clipped controls.
- [ ] Each of the five clinical shortcuts selects a permitted patient and reaches the correct route, with no immediate mutation, AI generation or export.
- [ ] Closing the picker by Escape, close button or backdrop restores focus; failed/empty searches and retry remain usable by keyboard.
- [ ] Admin-only accounts see clinic tools and minimum identity/assignment data, with no clinical shortcut or protected content leakage.
- [ ] Supporting text, placeholders, selected navigation and primary buttons retain readable contrast on their actual backgrounds.
- [ ] No generic welcome banner, fake statistic, duplicated workspace label or decorative “Next step” card has replaced useful records/actions.

## 10. Requirement coverage map

This map lets you check every functional requirement against a screen. **API/backend enforcement remains necessary** even where a frontend control exists.

| Requirement IDs | Frontend coverage |
| --- | --- |
| FR-01–FR-06 | Login/activation, capability navigation, patient scope, accounts, handover, logout/expiry. |
| FR-07–FR-09 | Patient create, scoped directory and profile, archive/reactivate. |
| FR-10–FR-14 | Session editor, acknowledged draft save, finalization/amendments, timeline, structured facts and follow-ups. |
| FR-15–FR-22 | Protected document upload/original, OCR progress, side-by-side review, grouping/confirmation, duplicate/withdraw/retry/cancel. |
| FR-23–FR-32 | Summary source selection, generation status, evidence links, descriptive labels, separate summary/fact review, provenance and stale/failure states. |
| FR-33–FR-38 | Indicator evaluation/explanation/review, bounded rule publisher, result states and follow-up tasks. |
| FR-39–FR-43 | Report preview/export, version/review history and role-filtered audit. |
| FR-44–FR-50 | Backup/restore, service health, deliberate deletion, revoked-work handling, grant/rule authority and source-consistent export. |

Relevant nonfunctional requirements shape the UI: NFR-01–NFR-04 require local processing, authorization, protected storage/transport; NFR-05 session security; NFR-06 responsive record operations; NFR-07–NFR-08 honest AI/OCR progress; NFR-09 failure isolation; NFR-10 conflict safety; NFR-11 recovery visibility; NFR-12 exact provenance; NFR-13 usability; NFR-14 accessibility; NFR-15 capacity-aware pagination and job queue; NFR-16–NFR-17 honest evaluation of AI/OCR quality; NFR-18 rule state correctness; NFR-19 adapter independence; and NFR-20 repeatable release information. Numeric targets are goals until measured, not frontend claims.

## 11. Scope and handoff notes

The SRS makes all 50 functional requirements required for the semester. This guide gives a build order, not permission to discard late-stage pages. If a feature remains incomplete, list its exact FR IDs and demonstrate the implemented behavior honestly. The first strong demo milestone is one integrated patient story through real services; OCR, AI and reports then extend that same story.

Before coding detailed forms, ask the backend developer for sample JSON for `/auth/me`, a patient list item, patient detail, note draft/version, timeline event, document/page, job, summary/fact, indicator result, report manifest and the common error envelope. Once these are agreed, keep TypeScript types in one API module and make each page render explicit loading, empty, success, conflict, denied and dependency-failure states.

