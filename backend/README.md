# Sanctum backend

Implemented: PostgreSQL user accounts, Argon2id password hashing, cookie login/logout,
current-user endpoint, account creation/reset/activation/deactivation commands,
database-backed session expiry and login limits, authentication audit records,
Origin checks on writes, and frontend-compatible errors.

Patient profiles, patient-scoped access, encrypted profile/follow-up payloads, archive/reactivate,
profile updates with version checks, follow-ups and a persisted overview timeline are implemented.
Session drafts, finalization, linked amendments and earlier-version reading are implemented.
Staff account administration and one-use activation/reset links are implemented and connected to the People screen. OCR extraction is implemented; AI summaries, reports and recovery are still pending.
Use synthetic data while developing. No public self-registration or default account exists.

## First-time setup (from this directory)

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Only on first setup; do not overwrite an existing .env:
cp -n .env.example .env
docker compose up -d db
alembic upgrade head
python -m app.crypto
python -m app.manage create-user --username clinician --name "My Clinician" --role clinician
python -m uvicorn app.main:app --reload --reload-dir app
```

The account command asks for a password twice (12–128 characters). Typed passwords
are intentionally invisible in the terminal. Passwords are not printed or stored as plaintext.
Local PostgreSQL uses host port **5433** to avoid an existing service on 5432.

## Existing installation

Stop FastAPI with Control+C before installing the new password dependency. Then:

```sh
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.crypto
python -m app.manage create-user --username clinician --name "My Clinician" --role clinician
python -m uvicorn app.main:app --reload --reload-dir app
```

Run account creation only once per username. A duplicate is rejected, never overwritten.
Database migrations add the versioned tables; they do not reset existing data.

## Try login

Open http://127.0.0.1:8000/docs in one browser tab:

1. Expand POST /api/v1/auth/login → Try it out. Supply your chosen username and password.
2. Execute: expect 200 and `{"success": true}`. The browser retains an HTTP-only session cookie.
3. Execute GET /api/v1/auth/me: expect your ID, displayName, username and capabilities.
4. Execute POST /api/v1/auth/logout, then GET /api/v1/auth/me: expect 401.

The existing frontend uses the same endpoints through its Next.js proxy:
run `npm run dev` in ../frontend, with NEXT_PUBLIC_DEMO_MODE absent, and open
http://localhost:3000/login. After successful login it redirects to /patients.
Use Add patient, enter a synthetic name and optional birth date, and save. The overview
now loads the profile, timeline and follow-ups from PostgreSQL. Sessions now support draft saving, finalization and amendments. Documents, AI summaries,
Indicators and Reports still require their later backend implementations.
Cookies belong to the hostname: use localhost consistently or 127.0.0.1 consistently.

## Account maintenance

```sh
python -m app.manage reset-password --username clinician
python -m app.manage deactivate-user --username clinician
python -m app.manage activate-user --username clinician
```

These trusted local operator commands invalidate existing sessions. Each account change
is audited with a null actor, meaning the local host operator. Admin accounts have no
automatic clinical reading/writing capabilities. Patient-level checks are enforced on profile and overview routes. A practitioner only sees
patients with a patient_access row for that user. Administrators may manage basic profiles
and select an active practitioner when creating a patient; they receive no clinical grant.
General handover/grant management is still unimplemented.

## Configuration and security boundaries

- Sessions expire after 8 hours and store only token hashes in PostgreSQL. Logout deletes
  the session; /auth/me checks expiry and active user state every time.
- Login permits 10 attempts per normalized username and 100 per direct client address
  in each fixed 15-minute window. Limits survive app restarts. Behind the Next.js proxy,
  the address bucket may be shared by all browser users; forwarded IP headers are not trusted.
- Writes require an exact allowed Origin (also applies to scripts/curl). The local
  defaults allow localhost/127.0.0.1 on 3000 and 8000, for frontend and Swagger respectively.
- For HTTPS deployment set COOKIE_SECURE=true, ALLOWED_ORIGIN to the clinic origin,
  and ALLOWED_ORIGINS to a JSON list of only trusted HTTPS origins.
- Local HTTP cookies intentionally omit Secure. Do not use this configuration for deployment.
- Health reports application liveness only; it is not a database/AI readiness check.
- The Compose database credentials are development defaults. No clinical deployment is claimed.

## Tests

```sh
python -m pytest -q
alembic check
```

Tests use an isolated SQLite database and never reset the local PostgreSQL data.
They cover cookie behavior, token replay after logout, expiry, deactivation, invalid
credentials, Origin enforcement, login throttling, session rotation and safe validation errors.
`alembic check` checks the running PostgreSQL schema against model metadata.

## Next milestone

Document upload/storage, then extraction and human-reviewed historical import. Match the
frontend's camelCase request/response fields and `{ "items": [...] }` lists.

Implementation references:
- https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/ (password hashing)
- https://fastapi.tiangolo.com/advanced/response-cookies/ (response cookies)
- https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html (Origin checks)


## Patient module (current milestone)

- GET/POST /api/v1/patients: active/archived lists, optional q search, creation.
- GET/PATCH /api/v1/patients/{id}: profile detail/update; PATCH requires expectedVersion.
- POST /api/v1/patients/{id}/archive and /reactivate: require expectedVersion.
- GET /api/v1/patients/{id}/timeline: actual profile/follow-up events, clinical scope required.
- GET/POST /api/v1/patients/{id}/follow-ups: read/create tasks with optional due dates.
- PATCH /api/v1/patients/{id}/follow-ups/{taskId}: complete/cancel; checks both IDs.
- GET /api/v1/admin/users: active account list for the practitioner picker, admin-only.

Clinicians may initially link a new patient only to themselves. Administrators may
select an active clinical writer. The profile update schema cannot modify access grants.
Archived profiles retain their history; adding new follow-ups requires reactivation.
Existing follow-ups may still be completed/cancelled. No due date remains null; no
implicit overdue status is invented. Deletion remains unimplemented.

The timeline contains profile/follow-up events plus session drafts, finalized notes and
amendments with links to their editor/history. Unknown session dates remain null.
Document and summary events will be added with those modules.
The PATCH profile API exists, but the current frontend has no profile-edit form.
Lists currently return all authorized profiles; frontend search is local, with optional
server q filtering also available. This is intended for the small semester dataset;
pagination and indexed encrypted-search design are not implemented.

### Local encrypted storage

`python -m app.crypto` creates secrets/clinical.key with owner-only file permissions,
only if missing. Existing keys are retained. This path is excluded from Git. Names,
birth dates and follow-up content are encrypted using Fernet before database storage.
An encrypted record includes its context ID to detect copying ciphertext between records.
Status, IDs, ownership, versions and timestamps remain relational metadata.
The key is read separately from PostgreSQL; it is a local-development key file, **not**
the documented production OS-keychain/wrapped-key or tested recovery implementation.
Keep the key to decrypt saved records. Never replace it to fix a startup problem.
If missing/corrupted or a record is tampered with, protected operations fail with 503.

Audit events contain actor/action/opaque target/outcome/time/request ID, not patient
names or task text. Profile mutations and their audits commit together; a failed audit
rolls back the mutation. Authorized patient/overview reads also require audit commit.
The existing audit UI endpoint and comprehensive denied-access auditing are pending.

Patient tests cover scope isolation/revocation, admin versus clinical permissions,
validation, update conflicts, archive/reactivation, task ownership, encrypted storage,
missing keys/tampering, and transactional rollback when auditing fails.

References:
- https://docs.sqlalchemy.org/en/21/orm/versioning.html
- https://cryptography.io/en/latest/fernet/


## Session notes (current milestone)

Apply `alembic upgrade head` after pulling this change. No new dependency is needed.
The API paths under `/api/v1/patients/{patientId}/sessions` are:

- POST the collection: create a draft from `{ "eventDate": "2026-01-15" }` or null.
- GET `/{sessionId}`: read the note and earlier finalized ancestors.
- PATCH `/{sessionId}`: save a full content snapshot with expectedVersion.
- POST `/{sessionId}/finalize`: finalize the saved version; expectedVersion required.
- POST `/{sessionId}/amendments`: create a linked new draft; reason and expectedVersion required.

`ClinicalNote` stores encrypted text, structured entries and amendment reason. Patient,
author, date, state, timestamps and version remain relational metadata. Only the draft
originator may save or finalize it; another authorized practitioner can create an
attributed amendment to a finalized note. All operations check patient scope again.
Archived patients are read-only for note workflows. Finalization rejects empty content.
Dates may be unknown; future dates are rejected. The editor sends complete snapshots,
so omission of required content arrays is rejected rather than clearing them silently.

Every successful draft save/finalization increments version. Old client versions return
409. An amendment has a new ID, points to the original via parent_id, and starts with a
version greater than its parent. The original row stays unchanged. Only one direct
amendment per parent is allowed; further amendments attach to the finalized child.
Duplicate amendment requests return 409 and the existing draft is reachable in the timeline.
Draft-save history is not retained; earlier finalized records are retained.

The PostgreSQL migration adds a BEFORE UPDATE trigger that rejects changes to finalized
notes and changes to note identity/authorship. This supplements API checks. It is not a
claim of protection against a database owner who disables triggers. Patient deletion,
which will require controlled removal, remains unimplemented.

The frontend waits for an in-flight autosave and any newer local edits before finalizing.
Conflict text remains visible until the user explicitly retries after comparing the
server copy. The editor honors allowedActions and shows earlier structured fields as
well as free text. The synthetic demo API advertises matching editor actions.

Tests cover lifecycle, empty finalization, structured semantics, old-version conflicts,
patient/author isolation, archive restrictions, preserved amendment chains, unknown dates,
deactivation/revocation and rollback when audit recording fails. The default SQLite
suite tests service behavior; the PostgreSQL trigger needs its separate integration check.


## Staff account management

Administrator account APIs now support invitations, one-use activation/reset links, deactivation and reactivation. Apply `alembic upgrade head` before running this version. See [the API contract and frontend handoff](docs/account-management-api.md) for endpoints, states, setup and remaining UI work. Issuing a reset immediately revokes sessions and blocks the old password until completion. No email is sent automatically.


## Document originals

Patient-scoped encrypted PDF/JPEG/PNG upload, listing and original download are now implemented. Install the updated requirements and apply migration `0005_documents`. See [document storage and setup](docs/document-storage.md). The Documents screen is connected; page review and confirmed historical import are now implemented. Local text extraction/OCR is now available through a separate worker.


## Local OCR worker

After installing requirements and applying migration `0006_extraction`, run `python -m app.worker` in a separate backend terminal. In Documents, choose **Start extraction**, then **View extracted text** when completed. Tesseract and its language data are required for scanned pages/images. Results remain unreviewed drafts. See [OCR workflow, setup and limitations](docs/ocr-processing.md).


## Review and import historical documents

Apply migration `0007_document_review`, then open **Review pages** after extraction. Correct and review each page, exclude unwanted/unreadable pages, group included pages, and confirm the import. Historical notes retain their source pages and are finalized; repeated confirmation does not duplicate them. See [review workflow and code explanation](docs/document-review.md).


## Local AI summary drafts

Apply migration `0008_ai_summaries`, keep Ollama running with the configured local model, and start `python -m app.summary_worker` in another backend terminal. Select finalized records in **New AI summary**, generate a referenced draft, then review the prose and suggested facts separately. See [setup, workflow, code explanation and limits](docs/ai-summaries.md).


## Follow-up indicators

Apply migration `0009_indicators` and restart FastAPI. The patient Indicators tab now evaluates the documented follow-up outstanding rule (DT-03), retains encrypted source/result snapshots, and supports acknowledgement/dismissal and historical views. No AI worker is needed for this deterministic check. The other four indicator rules remain pending. See [indicator workflow, setup and code explanation](docs/indicators.md).


## Confirmed ratings and rating-increase indicator

Apply migration `0010_ratings`, restart FastAPI, and open a patient’s Indicators tab. Confirm ratings against finalized notes, then choose Evaluate now. DT-02 compares the latest eligible pair on the same named 0–10 scale using the default increase threshold of 2. Incorrect ratings can be withdrawn and replaced without overwriting their history. See [rating workflow and comparison limits](docs/indicators.md#confirmed-ratings-and-dt-02).


## Repeated concerns

Apply migration `0011_concerns` and restart FastAPI. The Indicators tab supports source-linked concern confirmation and DT-01 using the latest three known-date finalized sessions. Confirmed present/current/patient concerns count; missing information is not treated as absence. See [workflow and limitations](docs/indicators.md#confirmed-concerns-and-dt-01).


## Documented medication changes

Apply migration `0012_medications` and restart FastAPI. Confirm source-linked medication entries in the patient Indicators tab, then Evaluate now. DT-04 checks the documented inclusive 30-day window and preserves uncertain entries as not evaluable. See [workflow and limits](docs/indicators.md#documented-medication-changes-dt-04).


## Required documentation indicator

DT-05 now checks the default session template: date status and at least one non-empty Concern, Observation or Intervention entry. Restart FastAPI and evaluate again; no new migration is needed. Open flagged notes and use amendments to correct finalized records. See [workflow and limits](docs/indicators.md#required-documentation-dt-05).


## Rule settings

Apply migration `0013_rule_versions`, restart FastAPI, and use an oversight account to publish bounded rule settings. Each publication retains its author, reason and prior versions. Evaluations preserve their original settings and become stale when current settings change. See [setup and verification](docs/rule-settings.md).
