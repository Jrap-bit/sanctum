# Verification summary

What was actually run, and what was not. Companion evidence: `integration-tests.md`, `acceptance-tests.md`, `evaluation.md`. All data is synthetic. Nothing here is a claim of clinical validity or regulatory compliance.

## Functional requirements

All of FR-01 to FR-15 have passing automated evidence (T-01 to T-15), and IT-01 to IT-10 pass against the Docker Compose stack with real PostgreSQL, Redis, Tesseract, and a local model, including workers killed mid-job.

Partial implementation worth stating:

| Area | Limitation |
|---|---|
| FR-08 withdrawal | Available only before import. After import, corrections are made by amending the historical notes. |
| FR-01 Google sign-in | Tested with mocked Google responses. Never exercised against real Google. Off by default. |
| FR-06 object store | The filesystem store is the tested default. The S3 adapter is implemented but not exercised against a real S3 server; MinIO images could not be pulled in this environment. |
| FR-14 restore | Tested on one host. Fresh-host restore with a transferred deletion registry was not tested. |

## Non-functional requirements

| ID | Status | Basis |
|---|---|---|
| NFR-01 Privacy | Not formally tested | Designed for no external calls and Google sign-in is off by default, but no blocked-egress traffic capture was run. |
| NFR-02 Authorization | Pass on tested paths | Negative tests and IT-02, IT-06; not an exhaustive route-by-route matrix. Refusals are audited. WebSocket refusals are not. |
| NFR-03 Storage security | Pass | AES-256-GCM with key ids and a wrapped data key; wrong-key and tamper tests. Keys sit in a separate volume on the same host. |
| NFR-04 Transport | Partial | Caddy serves local TLS on port 8443, and internal ports are unpublished. Local certificate trust was not provisioned or tested, and the demo uses HTTP on port 8088. |
| NFR-05 Sessions | Pass, except cookie flag | 15-minute idle, 8-hour absolute, progressive delay. `Secure` cookies are off for local HTTP (`COOKIE_SECURE`). |
| NFR-06 Interactive latency | Not measured | |
| NFR-07 Summary latency | Met in a small sample | `qwen3:4b` p95 17.2 s against 90 s, warm, 5 cases rather than the specified 30. |
| NFR-08 OCR latency | Typed pages only | About 0.2 s per typed page. Handwriting not measured. |
| NFR-09 Failure isolation | Pass | IT-05 |
| NFR-10 Consistency | Pass | IT-10 |
| NFR-11 Recoverability | Restore verified, not timed | The 30-minute target was not measured. |
| NFR-12 Traceability | Pass on tested paths | Source versions, model, prompt version, digest, and reviewer are recorded. |
| NFR-13 Usability | Not tested | |
| NFR-14 Accessibility | Not tested | Labels and text status exist; no keyboard walkthrough or automated check was run. |
| NFR-15 Capacity | Not measured | |
| NFR-16 AI quality | Not established | Automated phrase proxy on 5 cases only, not the two-annotator study. |
| NFR-17 OCR usefulness | Not measured | Typed synthetic pages only. Add handwritten fixtures and re-run. |
| NFR-18 Rule correctness | Pass | Every row in section 8.6.2 plus boundary, negation, and missing-input cases. |
| NFR-19 Maintainability | Partial | Adapters sit behind factories with fake and real implementations; a shared contract suite was not written. |
| NFR-20 Repeatability | Partial | `backend/requirements.lock` and model digests are recorded; a full release manifest is not. The stack rebuilds and passes its smoke test from empty volumes. |

## Implemented differently from the documentation

These belong in chapter 13 of the documentation.

| Documented | Implemented |
|---|---|
| Section 8.3 API paths | Patient-scoped paths such as `/patients/{id}/summaries/{sid}/review`, `/admin/users`, `/access/grants`, `/oversight/rules` |
| Section 7.5 polling | WebSocket progress, with polling kept as the fallback |
| Section 3.4 CSRF token | `SameSite=Lax` cookies plus a required trusted `Origin` on every write |
| ADR-10 session persistence | Sessions in Redis, with immediate revocation |
| FR-07 retained transcription | Raw OCR text is encrypted in Redis for 24 hours and re-extracted from the original if it expires. Reviewed text is permanent in PostgreSQL. |
| Encrypted local object store | Object store behind a factory; filesystem default |
| Section 6.1 static assets | Next.js server behind Caddy |
| Section 3.4 upload limit of 20 pages | 500 pages |
| ADR-14 runtime | Model reached over HTTP by a configurable URL, with Ollama and OpenAI-compatible engines |
| Tesseract and PDF | Tesseract with PDFium, chosen by name through a factory |
| FR-02 administrators create accounts | With `GOOGLE_SELF_SIGNUP=true`, a Google sign-in creates its own account and chooses its own role, bypassing FR-02 and the separation tested by IT-06. Off by default; turned on for the local demo stack. |
| Added | Decommissioned handover screen, `clinical_admin` operator-only role, optional Google sign-in |
