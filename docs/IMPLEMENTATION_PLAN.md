# Sanctum — Implementation Plan (rev 4)

**Target:** working prototype by **11 November 2026, 23:55** (course guidelines §10).
**Written:** 8 November 2026 · **rev 4** rebuilt against the real upstream code at `ddb6465`.
**Repo:** https://github.com/Jrap-bit/sanctum

> **Status, 9 November 2026: implementation complete on branch `feature/backend-hardening`.** What was run and what was not is recorded in `docs/evidence/verification-summary.md`, which supersedes the planning status below. Google sign-in is built and tested only with mocks. MinIO images could not be pulled, so `FilesystemStore` is the default.

Rev 1–3 were written against a stale local `main` and assumed an empty backend. Upstream actually
contains ~3,558 lines of app code, 1,714 lines of tests and 14 migrations. The code was surveyed by reading key modules and listing routes; **the test baseline is still pending, so nothing below marked "present" has been verified to work.** This revision is a
**gap analysis and remediation plan**, not a from-scratch build.

---

## 1. Crypto — library-based, but replaced anyway

`app/crypto.py` does not implement its own cipher: it wraps `cryptography.fernet.Fernet`. The custom part is the layer around it (context check inside the plaintext, raw key file, error mapping), and that layer does not match the documented design.

**Five defects justify replacing it:**

| # | Defect | Severity | Why it matters |
|---|---|---|---|
| C1 | **Fernet is AES-CBC+HMAC, not AES-GCM** | design deviation | ADR-09 and NFR-03 specify *"a vetted AES-GCM implementation and unique nonces"* and **key identifiers**. Fernet tokens carry no key id (rotation would need `MultiFernet` trial decryption). Authenticated, but not the documented design |
| C2 | **No DEK/KEK separation** | real gap | ADR-09 requires *"a data-encryption key wrapped by a master key held in an OS-protected credential facility or explicitly unlocked operator secret."* Current code reads one raw key from a file — no wrapping, no rotation path |
| C3 | **`cipher()` re-reads the key file on every encrypt and decrypt** | minor inefficiency | Unmeasured and probably small per request; fixed in passing by caching the key |
| C4 | **Context bound inside the plaintext, not as AAD** | correctness smell | It JSON-wraps `{"context":…, "data":…}` and compares after decrypting. AES-GCM AAD is the right primitive — it binds record identity at the crypto layer and fails there, without inflating ciphertext |
| C5 | **Integrity failure returns HTTP 503 and is swallowed with `ValueError, KeyError, TypeError`** | real defect | Tampered ciphertext is a **security event**, not an outage. NFR-03's verification explicitly requires testing *"wrong-key and modified-ciphertext failure"*, which is currently indistinguishable from a service outage. A plain JSON-shape bug also becomes a 503 |

**Replacement spec** — `app/adapters/crypto.py`:

- AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
- Envelope `b"SNCTM1" ‖ key_id(4) ‖ nonce(12) ‖ ciphertext‖tag`; random nonce per record.
- DEK wrapped by a master key supplied as an operator secret (env var in Docker, file outside the
  data store otherwise) — satisfies C2 and stays container-friendly.
- `context` passed as **AAD**, not embedded in plaintext (C4).
- Keys loaded once into a module cache with an explicit `reload_keys()` (C3).
- Distinct exception types: `CiphertextIntegrityError` vs `KeyUnavailableError`, mapped to different
  responses, with integrity failures audited (C5).
- `key_id` in the envelope enables rotation and decryption under a previous key (C1).
- Keep the `encrypt(dict, context)` / `decrypt(payload, context)` signatures (13 modules import them) and add `encrypt_bytes` / `decrypt_bytes` for originals; `documents.py:123` currently calls `cipher().encrypt` directly.
- **No re-encryption migration:** all data is synthetic, so the dev database is reset after the switch.

### 1.1 Other real defects found in the same pass

| # | File | Defect |
|---|---|---|
| S1 | `security.py` | **No preset grants `patients:delete`.** FR-15 requires deletion to need *both* administrative and oversight permission; no account can ever hold it, so FR-15 is unimplementable as configured |
| S2 | `security.py` | `ROLE_CAPABILITIES` and `ACCOUNT_PRESETS` duplicate the same authority model — two sources of truth that will drift. Collapse to one |
| S3 | `database.py` | `create_engine()` runs **at module import**, so importing the app requires reachable DB config, can't be reconfigured per process, and is hostile to testing. No `pool_size`/`pool_recycle` either, which matters once api+worker containers share Postgres |
| S4 | `rate_limits.py` | **Fixed 15-minute windows, not the progressive delay** §8.7 requires. A burst straddling a window boundary gets 2× the limit. Also calls `db.commit()` inside the limiter, committing whatever else the caller had pending, and runs a `DELETE` sweep on every login attempt |
| S5 | `auth.py`, `models.py` | **No 15-minute idle timeout.** Sessions are `LoginSession` rows with an absolute `session_hours` expiry only, so NFR-05 is half met. Fixed by the Redis session work |
| S6 | `main.py` | The origin check rejects requests with **absent** `Origin`. Correct for browsers, but it will reject the smoke test, non-browser clients, and needs re-checking once Caddy fronts everything (origin becomes Caddy's) |
| S7 | `config.py` | `summary_model = "qwen3:8b"` — **not present on this machine.** Only `gemma4:e2b` is. AI summaries cannot run at all until this is resolved |
| S8 | — | No `conftest.py`; the 16 test files have no shared fixtures |
| S9 | `ai.py:83-96,154` | **LLM is hard-wired to local Ollama.** `local_url()` rejects any host but localhost, so `host.docker.internal` fails from a container, and it calls native `/api/tags` and `/api/chat`. Blocks the decoupled-endpoint decision |
| S10 | `models.py:140` | **Originals are stored in Postgres** (`original_payload` LargeBinary), not an object store |
| S11 | `models.py:164`, `worker.py:116` | **Raw extracted text is persisted** in `extracted_pages`, against the agreed policy (raw text in Redis on a TTL, re-extract from the original; reviewed text in Postgres) |
| S12 | — | **No `GET /api/v1/audit`.** Events are written but cannot be read; the frontend audit page has no backend. Also absent: `/admin/assignments*` (handover is out of scope, so remove that page's dependency) |
| S13 | `documents/page.tsx`, `summaries/new/page.tsx` | Job progress is polled; WebSockets replace it, with polling kept as fallback |

**Not defects** — flagged so nobody wastes time on them: `token_digest` is a bare SHA-256 of the
session token, which is the standard and correct pattern for a *high-entropy random* token (no
brute-force surface, so no KDF needed). The import-time `dummy_hash` is deliberate and good — it
equalises timing for unknown usernames. The `grounded()` / passage-ID design in `ai.py` is genuinely
well done: the model selects passage **IDs** and the application attaches the real quotes, which
structurally prevents quote fabrication. Keep it.

---

## 2. File structure — and why this is not cosmetic

Everything is flat: 29 modules in `backend/app/*.py`, with routes, services, domain rules and
adapters interleaved in the same files.

The team's own documentation specifies a layout in **§9.1**, and **§13.1's evidence ledger commits to
specific paths** — `backend/app/services/authorization`, `backend/app/domain/sessions`,
`backend/app/domain/rules`, `backend/app/services/imports`, `backend/app/services/summaries`,
`backend/app/services/review`, `backend/app/services/reports`. **None of those paths exist.** The
documentation's §13 requires code and design to agree, so the restructure is what makes those paths true.

### Target layout

```
backend/app/
  main.py                      app factory, middleware, router wiring
  manage.py                    migrate | bootstrap | seed | worker | smoke-test | backup | restore
  core/
    config.py                  ← app/config.py  (+ redis, store, llm, crypto settings)
    database.py                ← app/database.py (lazy engine, pooled)
    cache.py                   NEW — Redis client
    security.py                ← password hashing, token digest only
    capabilities.py            ← single authority model (fixes S1, S2)
    errors.py                  ← handlers extracted from main.py
  db/
    models.py                  ← app/models.py
  api/
    auth.py patients.py sessions.py documents.py processing.py review.py
    summaries.py indicators.py ratings.py concerns.py medications.py
    rules.py grants.py admin_users.py
    health.py                  liveness only, as §8.3 specifies
    audit.py                   NEW — GET /audit (fixes S12)
    reports.py                 NEW — FR-13
    operations.py              NEW — FR-14 backup/restore, FR-15 deletion
    model_catalog.py           NEW — GET /api/v1/models
    ws.py                      NEW — WS /api/v1/ws/jobs/{id}
  services/
    authorization.py           ← require / scoped_patient / has_access
    audit.py                   ← record_audit
    accounts.py                ← app/account_service.py
    patients.py sessions.py imports.py summaries.py review.py
    rules.py reports.py operations.py
  domain/
    rules/
      engine.py
      dt01_repeated_concern.py … dt05_required_documentation.py
    states.py labels.py
  adapters/
    base.py registry.py        NEW — Protocols + factory
    crypto.py                  ← rewritten per §1
    text_pypdfium.py           ← embedded-text path
    ocr_tesseract.py           ← OCR path
    extract_page.py            ← stays a standalone subprocess entrypoint
    llm_openai_compat.py       ← HTTP half of app/ai.py
    objectstore.py             NEW — S3 / MinIO / filesystem
    report_pdf.py              NEW
  workers/
    extraction.py              ← app/worker.py
    summary.py                 ← app/summary_worker.py
```

**One trap:** `extract_page.py` is invoked as a subprocess via `sys.argv`, so moving it requires
updating the invocation in `worker.py`. It must stay independently runnable.

### 2.1 The restructure is conditional

A 29-file move, three days out, on code that currently works, is the highest-risk/lowest-visible-reward
change available. It is only sane because 16 test files exist as a safety net. Therefore:

1. **Gate: the existing suite must pass first.** If it does not, we fix it or skip the restructure.
   I will not reorganise code whose starting state is unverified.
2. The restructure is **one worker, one wave, alone** — it touches every file, so it conflicts with
   every other task and cannot be parallelised with them.
3. **Abort is cheap:** if `pytest` fails after the move, `git checkout ddb6465 -- backend/` reverts
   wholesale and we proceed flat. Bounded bet.

---

## 3. Gap analysis — FR coverage at `ddb6465`

| FR | Status (read, not run) | Work needed |
|---|---|---|
| FR-01 Authentication / access control | present | Redis sessions, idle timeout (S5), progressive rate limit (S4) |
| FR-02 Account management | present | — |
| FR-03 Patient profiles | present | — |
| FR-04 Session notes + immutable versions | present | — |
| FR-05 Clinical history / timeline | present | — |
| FR-06 Document upload / storage | present | move originals out of Postgres (S10) |
| FR-07 OCR / text extraction | present | factory; raw text to Redis (S11) |
| FR-08 Transcription review / import | present | reads raw text from Redis, re-extract when expired |
| FR-09 AI summaries / labels | present | decouple, multi-model, progress (S9) |
| FR-10 AI review / fact verification | present | — |
| FR-11 Rule indicators, all five DTs | present | move to `domain/rules/`; map the 28 existing tests in six rule files to the §8.6.2 rows and add what is missing |
| FR-12 Follow-up tasks | present | — |
| **FR-13 Reports / PDF export** | **absent** | whole feature + PDF renderer |
| **FR-14 audit read, backup / restore** | **absent** (audit writes exist) | `GET /audit`, backup, restore |
| **FR-15 patient deletion** | **absent** | route + S1 capability |

**All agreed additions are absent:** Redis, object store, WebSockets, multi-model LLM, adapter
factories, Docker app containers (`compose.yaml` has Postgres only), Google OAuth. The DB-backed job queue with leases already exists and stays.

---

## 4. Waves

**Execution order: baseline → Wave 1 (restructure) → Wave 0 (contracts) → Waves 2–5.** The contracts live at the new paths, so the move has to land first.

**Wave 0 — me (~2 h).** Contracts, so no worker needs a shared file.
All new settings into `core/config.py`, all new tables into
`db/models.py` + one Alembic migration, `core/cache.py`, `adapters/base.py` Protocols, router wiring in
`main.py`, `core/capabilities.py` (fixes S1/S2), lazy pooled engine (S3). Write `AGENT_CONTEXT.md` and
every spec, each naming exact files, signatures, the module to mirror, and the proving command. Resolve S7 (model default). `core/cache.py` includes a `publish_progress` helper so both pipeline workers share it.

**Wave 1 — restructure, one worker alone.** The §2 move, imports rewritten, `extract_page.py`
subprocess path updated. Gate: all 16 test files still pass. Abort = `git checkout ddb6465 -- backend/`.

**Wave 2 — 3 workers, parallel.**

| Worker | Scope |
|---|---|
| Docker | `backend/Dockerfile`, root `docker-compose.yml`, `Caddyfile`, `.dockerignore`, CPU LLM profile |
| Crypto + object store | `adapters/crypto.py` per §1, `adapters/objectstore.py`, rewire original upload/read, drop `original_payload` use (C1–C5, S10). One worker because both rewrite the same path. **Default `STORE=filesystem`** with the S3 adapter registered: `minio/minio` and `quay.io/minio/minio` both refused the pull here |
| Reports **FR-13** + audit read | `api/reports.py`, `services/reports.py`, `adapters/report_pdf.py`, `api/audit.py`, tests |

**Wave 3 — 3 workers, parallel.** Split so no two touch the same worker module.

| Worker | Scope |
|---|---|
| Identity | Redis session store, 15-min idle + 8-h absolute, progressive rate limit (S4, S5), **Google OAuth2** as an optional sign-in matched to existing active users only |
| OCR pipeline + live progress | OCR/PDF factories, `workers/extraction.py`, raw text to Redis + re-extract (S11), `api/ws.py` |
| LLM | OpenAI-compatible adapter replacing S9, model registry, `api/model_catalog.py`, per-request model, `workers/summary.py` progress |

**Wave 4 — 2 workers.** Deletion + backup/restore (`services/operations.py`, manage commands);
frontend (`lib/ws.ts`, progress bars replacing polling as primary, model picker, Google sign-in button, remove the assignments page dependency).

**Wave 5 — me.** Origin/Caddy reconciliation (S6), migrations, `docker compose up`, end-to-end
verification, rule-test mapping, evaluation harness, IT-01…10 evidence, README.

**Hard rules for `AGENT_CONTEXT.md`:** no worker edits `main.py`, `db/models.py` or `core/config.py`
(I pre-populate all three in wave 0 — this is what makes the waves parallel-safe); no worker runs
`docker compose`, `alembic` or touches a database; no worker invents a column or setting name.

---

## 5. Honest budget

| | Hours |
|---|---|
| Wave 0 contracts + baseline | 2 |
| Wave 1 restructure (+ gate, + possible abort) | 3–4 |
| Wave 2 (3 workers, wall clock) | 3 |
| Wave 3 (3 workers, wall clock) | 3 |
| Wave 4 (2 workers) | 2.5 |
| Wave 5 integration, verification, evidence | 6 |
| **Total (estimate)** | **~20 h** |

Lower than rev 3's 36 h because FR-01…FR-12 appear to exist; that depends on the pending test baseline. The restructure is the
single largest discretionary cost; dropping it saves 3–4 h at the price of leaving §13's evidence
ledger false.

**If time runs short, your call, in the order I would cut:** backup/restore depth → Google OAuth → the restructure.

---

## 6. Out of scope — document as limitations

Per §9.8 and §12.3: the 60-page handwriting evaluation at documented scale, usability study (NFR-13),
Playwright e2e, trusted local TLS certificates (NFR-04), timed clean-instance restore (NFR-11),
deletion-registry reconciliation on a fresh host (IT-08), PostgreSQL row-level security (R9), the
1000-patient/10000-session capacity benchmark (NFR-15).

## 7. Open items

0. **Test baseline** — running at the time of writing; the restructure is gated on it.
1. **Model default (S7)** — decided: `qwen3:4b`. Update `config.py` and `.env.example`.
3. **Documentation track (teammates):** algebraic specifications, DFD modelling, Activity Network,
   WBS, PERT charts, per-member contributions on page 1, git URL — none present.
4. **Deviations to record in §13:** raw-extraction retention (FR-07 wording); WebSockets replacing §7.5 polling; Redis sessions; origin-check
   CSRF instead of a token; LLM runtime decoupled behind an OpenAI-compatible URL; implemented API
   paths vs the §8.3 catalogue.
5. **Deadline:** documentation says 20 November and schedules work through 16–20 November; the
   guidelines say 11 November with no extension. Correct the schedule table before submission.
