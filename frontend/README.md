# Sanctum frontend

Next.js App Router + TypeScript implementation of the frontend guide. All 19 specified routes are present. Normal mode uses live API requests. An explicitly marked synthetic demo API is available for UI review before FastAPI exists.

The interface uses a centered branded login, floating horizontal navigation, and direct workflow tools for session notes, imports/OCR, reviewed AI summaries, indicators, and reports. Global clinical shortcuts select an active authorized patient before opening the task. Admin-only accounts receive clinic tools. Critical review states, evidence links, and confirmation actions remain visible at the point of decision.

The current visual direction and interaction requirements are recorded in [Sanctum Frontend Implementation Guide](../docs/Sanctum_Frontend_Implementation_Guide.md), including the typography, contrast, responsive layouts, and patient-picker behavior.

## Check it now without a backend

```bash
cd frontend
npm install
npm run dev:demo
```

Open `http://localhost:3000/login` and sign in with one of these **synthetic demo accounts**, all using password `demo123`:

| Username | What to check |
| --- | --- |
| `clinician` | Patient directory, session editor, save/finalize, document review, summary/fact review, indicators and reports. |
| `admin` | Minimum patient identity, users, assignments, grants, audit and operations. Direct clinical URLs should be denied. |
| `oversight` | Scoped clinical view, grant approval and bounded rule publication. |

Use the preloaded synthetic patient **Avery Reed**. Try: Patients → Avery Reed → Sessions → Create draft → enter text → Save draft → Finalize. Return to Overview to see the new timeline item. Documents contains an example two-page synthetic transcription for review. The demo banner stays visible, and all edits live only in server memory; restarting the development server resets them. Demo login and operations are simulations, not security or recovery tests. Never enter real patient data in this mode.

To switch back to real integration, stop the dev server and use `npm run dev`. `NEXT_PUBLIC_DEMO_MODE=1` is set only by the demo script. Ensure it is absent from deployment settings.

## Run

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. Run FastAPI at the `BACKEND_URL` in `.env.local` (default `http://127.0.0.1:8000`). Next.js rewrites same-origin `/api/v1/*` requests to that backend. For production, run the browser and backend behind trusted local HTTPS. The backend must issue secure, HTTP-only session cookies and enforce CSRF protection on writes, permission checks, expiry and version conflicts. This frontend neither stores credentials nor patient records in browser storage.

`npm run typecheck` and `npm run build` check the app. In normal mode, the login and clinical workflows show real request errors until backend endpoints exist. Use synthetic records when integrating or demonstrating.

Base styles and responsive layouts live in `src/app/globals.css`; shared lighting and motion live in `src/app/effects.css`. Both are imported once in the root layout. TypeScript rejects unused imports, local variables and parameters. Keep the synthetic demo isolated from real API transport when adding features.

## Contract to align with FastAPI

The implementation guide labels endpoint names and DTO shapes as **proposed**, so the frontend centralizes types in `src/lib/types.ts` and transport/error handling in `src/lib/api.ts`. The backend developer should align them before the integrated demo. JSON request bodies use camelCase. List responses use `{ "items": [...] }`, resource responses return the resource directly, and the common error body is `{ "code": "...", "message": "...", "fieldErrors": {}, "requestId": "..." }`. All protected requests must recheck current access. `GET /auth/me` returns `{ id, displayName, username, capabilities, clinicTimezone? }`. Each patient/session/document/summary/indicator resource includes its `allowedActions` and numeric `version` where applicable. Capabilities are strings enumerated in `types.ts`; rename centrally if FastAPI chooses a different vocabulary.

| Area | Expected `/api/v1` paths |
| --- | --- |
| Login | `POST /auth/login`, `/auth/logout`, `/auth/activate`; `GET /auth/me`, `/health` |
| Patients | `GET/POST /patients`; `GET/DELETE /patients/:id`; `POST /patients/:id/archive`, `/reactivate`; `GET /patients/:id/timeline`, `/follow-ups`; `POST /patients/:id/follow-ups`; `PATCH /patients/:id/follow-ups/:taskId` |
| Notes | `POST /patients/:id/sessions`; `GET/PATCH /patients/:id/sessions/:sessionId`; `POST /patients/:id/sessions/:sessionId/finalize`, `/amendments` |
| Imports | `GET/POST /patients/:id/documents`; `GET /patients/:id/documents/:documentId/original`, `/pages`, `/pages/:number/original`; `PATCH /patients/:id/documents/:documentId/pages/:number`; `POST /patients/:id/documents/:documentId/confirm`, `/retry`, `/cancel`, `/withdraw` |
| AI | `GET /patients/:id/summaries/eligible-sources`; `POST /patients/:id/summaries`; `GET /jobs/:jobId`; `POST /jobs/:jobId/cancel`, `/retry`; `GET /patients/:id/summaries/:summaryId`; `POST /patients/:id/summaries/:summaryId/review`, `/facts/:factId/review` |
| Rules | `GET /patients/:id/indicators`; `POST /patients/:id/indicators/evaluate`, `/patients/:id/indicators/:resultId/review`; `GET /oversight/rules`; `POST /oversight/rules/:ruleId/publish` |
| Reports | `GET /patients/:id/reports/eligible-sources`; `POST /patients/:id/reports/preview`; `GET /patients/:id/reports/:manifestId/export` returns a protected PDF |
| Administration | `GET/POST /admin/users`; `POST /admin/users/:userId/reset-credential`, `/deactivate`; `GET /admin/assignments`; `POST /admin/assignments/handover`; `GET/POST /access/grants`; `POST /access/grants/:id/review`; `GET /audit`; `GET /admin/operations/backups`, `/jobs`; `POST /admin/operations/backups`, `/restore/validate`, `/restore` |

The backend should serve the original/page endpoints with protected content types and safe `Content-Disposition`. PDF export must validate the preview's source versions and user scope again. The current upload accepts PDF/JPEG/PNG up to 25 MB before server validation; page count, decoded pixel limits, duplicates and malware checks belong to the backend. For a duplicate, return a safe `409` with a documented override flow; the UI currently displays a warning and requires backend-specific override integration.

## Current behavior and integration gaps

- The primary patient story has live API wiring: sign in, open scoped patient, start a session, edit with serialized autosave and `expectedVersion`, finalize, refresh the timeline. `409` preserves local note text and offers an explicit retry against the latest version.
- Documents, page correction/grouping, summary and independent fact review, indicators, report preview/export, users, handover, grants, rule publication, audit and operations have connected screens. They require the proposed FastAPI endpoints and matching DTOs. The backend directory in this repository is currently empty.
- Some advanced details from the SRS still need backend contract decisions and integration: source passage viewer preserving review context, protected duplicate override, server verified truth-table preview for rule publication, precise restore manifest/maintenance state, clinic timezone formatting, pagination and automated end-to-end permission/revocation tests. Do not claim the full 50 FR acceptance suite has passed until those are built and verified.
- Demo data is confined to the opt-in `/demo-api/v1` route and stored in server memory. Normal mode never calls it. The demo responses are for layout and flow checks; they do not prove FastAPI behavior, persistence, security, OCR/LLM quality or PDF acceptance.

## Route layout

Authentication lives under `(auth)`; scoped workspace pages under `(workspace)`. Patient tabs share a patient layout, and the app shell shows capability-filtered navigation and an account/sign-out menu. Service health belongs on System health and relevant task screens. UI gates help users, while the backend remains the source of permission decisions.
