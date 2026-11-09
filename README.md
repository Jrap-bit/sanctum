# Sanctum

A clinic-controlled workspace for therapy records: session notes, reviewed import of historical documents, local AI summaries, explainable decision-table indicators, and PDF reports. AI output stays a draft until a practitioner reviews it. Use synthetic data only: this is a course prototype and is not validated for clinical use.

## Run it

You need Docker Desktop and, for full-speed summaries on a Mac, [Ollama](https://ollama.com) on the host.

```bash
ollama pull qwen3:4b                 # the default model
docker compose up -d --build         # builds and starts everything, runs migrations
docker compose exec -e SANCTUM_SEED_PASSWORD='choose-12-or-more-characters' api \
  python -m app.manage seed-synthetic
docker compose exec api python -m app.manage smoke-test
```

The last line of the smoke test should be `SANCTUM SMOKE TEST PASS`. Then open <http://localhost:8088> and sign in with the password you chose:

| Username | Can do |
|---|---|
| `clinician` | Patient records, notes, imports, AI review, reports |
| `admin` | Accounts and operations; no clinical access |
| `oversight` | Reviews access requests and publishes rule versions |
| `clinical_admin` | Admin and oversight together; the only role that can delete a patient |

To stop: `docker compose down`. Add `-v` to also erase all data and keys.

## Choosing the LLM runtime

The application calls the model over HTTP and never embeds it. Docker on macOS cannot use the Apple GPU, so the model runs outside the application containers by default. Set these in a `.env` file:

| Runtime | `LLM_ENGINE` | `LLM_BASE_URL` |
|---|---|---|
| Ollama on the host (default, Metal) | `ollama` | `http://host.docker.internal:11434/v1` |
| Docker Model Runner (Metal) | `openai_compat` | `http://model-runner.docker.internal/v1` |
| Ollama in a container (CPU only, any machine) | `ollama` | `http://llm:11434/v1` |

For the CPU option, also run `docker compose --profile cpu up -d` and `docker compose exec llm ollama pull qwen3:4b`.

Installed models are chosen on the summary screen. To change the list, set `LLM_MODELS` as a JSON array, and `SUMMARY_MODEL` for the default.

## Architecture

```
Browser -> Caddy (localhost:8088) -> web (Next.js)
                                  -> api (FastAPI) -> PostgreSQL   records, jobs, audit
                                                   -> Redis        sessions, progress, draft OCR text
                                                   -> object store encrypted originals
workers: extraction (OCR), summary (LLM)           -> model runtime over HTTP
```

```
backend/app/
  api/        routes and request models only
    access/       sign-in, accounts, access grants
    clinical/     patients, sessions, concerns, medications, ratings
    documents/    upload, OCR processing, page review
    insights/     AI summaries, model catalog, indicators, reports
    governance/   audit log, operations, decision rules
    deps.py, schemas.py, ws.py   shared dependencies and the WebSocket route
  services/   use cases: authorisation, transactions, audit
  domain/     pure logic, including decision tables DT-01 to DT-05
  adapters/   encryption, OCR, PDF text, LLM engines, object store, report PDF
  core/       settings, database, Redis, error handling
  db/         SQLAlchemy models
  workers/    extraction and summary job processes
```

Adapters are chosen by name in settings (`OCR_ENGINE`, `TEXT_EXTRACTOR`, `LLM_ENGINE`, `STORE_BACKEND`). `STORE_BACKEND=s3` with the `S3_*` settings uses any S3-compatible store.

## Operations

```bash
docker compose exec api python -m app.manage backup
docker compose exec api python -m app.manage restore --verify-first /data/backups/<id>.sncbak
docker compose exec api python -m app.manage create-user --username NAME --name "Full Name" --role clinician
```

Keep the `sanctum_secrets` volume safe and separate from backups of the data. Without its keys, nothing can be decrypted. Backups and administration are also available in the app under System health.

Google sign-in is optional and off by default. To enable it, set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI`. It matches existing active accounts by verified email, and password sign-in keeps working without internet access. Setting `GOOGLE_SELF_SIGNUP=true` is a prototype convenience that creates an account on first Google sign-in and lets that person pick any role, including administrator, so keep it off anywhere other people can reach.

## Verify

```bash
cd backend
python3.13 -m venv .venv313 && .venv313/bin/pip install -r requirements.txt
.venv313/bin/python -m pytest tests -q
.venv313/bin/python ../evaluation/run_eval.py --out ../docs/evidence
cd .. && SANCTUM_SEED_PASSWORD='your-seed-password' backend/.venv313/bin/python scripts/it_walkthrough.py
```

`scripts/it_walkthrough.py` kills workers, deletes data, and restores backups. It needs a freshly seeded stack, plus a second clinician named `e2e_clinician` with the same password, and must never run against real data. Results are recorded in [`docs/evidence/`](docs/evidence/).

## Known limitations

See [`docs/evidence/verification-summary.md`](docs/evidence/verification-summary.md) for what has and has not been measured.

`docs/IMPLEMENTATION_PLAN.md` records the build plan and its decisions.
