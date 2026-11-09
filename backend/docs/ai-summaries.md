# Local AI summary drafts

## Simple explanation

A clinician finalizes a session note, or reviews an uploaded document and confirms its historical notes. They select these records on **New AI summary**. FastAPI saves a generation job; a separate worker asks Ollama to produce a draft on this machine. Each paragraph has source references and supporting quotations. The clinician accepts, edits and accepts, or rejects the prose, then reviews each suggested fact separately. The progress indicator advances to Review facts after acceptance and shows every step complete once all facts have decisions. Decisions save immediately; no additional finalization is required.

Example: a finalized note says “The patient denied alcohol use.” The draft must preserve that denial. A suggested fact remains pending until a clinician confirms or corrects it. Accepting the summary alone never confirms facts.

## Run it

From the backend directory, with the virtual environment activated:

```sh
alembic upgrade head
python -m app.workers.summary
```

Keep that terminal running alongside FastAPI, the frontend, and the separate OCR worker (`python -m app.workers.extraction`). Ollama must also be running locally. Defaults in `.env.example` are `OLLAMA_URL=http://127.0.0.1:11434` and `SUMMARY_MODEL=qwen3:8b`. The current development machine already has that model installed. On another machine, install Ollama and download the configured local model (`ollama pull qwen3:8b`), or configure another compatible installed model. Model quality and resource requirements vary; test a replacement before relying on it. **Check model** refreshes availability.

No cloud model API or API key is used. Only loopback HTTP addresses are accepted, proxy environment variables are ignored, redirects are disabled, and generation requires an installed non-remote model. Administrators must keep the local Ollama installation and model configuration trusted.

## Code map

- `app/adapters/llm.py`: prepares the prompt and JSON schema, splits sources into numbered exact passages, asks Ollama to cite passage IDs, attaches the original text itself, and validates output shape and references. The model no longer has to reproduce quotations. Unknown references and unsupported quotations fail the job.
- `app/api/insights/summaries.py`: checks permissions and patient assignment, selects finalized current records, queues jobs, serves summaries, and records version-checked review decisions.
- `app/workers/summary.py`: claims durable jobs, calls the model outside the database transaction, rechecks access and source versions, and saves encrypted drafts. Cancellation prevents late output from being saved.
- `app/db/models.py` and migration `0008_ai_summaries`: encrypted summary/job payloads and relational queue metadata.
- Summary frontend pages: source selection, availability, progress, cancel/retry, previous drafts, quotations and separate review controls.

Sources include the exact saved note versions. Original generated prose, facts, model digest, prompt version and review history are retained. A finalized amendment makes summaries using the older source stale; stale summaries cannot be accepted or have facts confirmed. A draft amendment alone does not replace the finalized source.

## API

- `GET /api/v1/ai/status`
- `GET /api/v1/patients/{id}/summaries/eligible-sources`
- `POST /api/v1/patients/{id}/summaries`: kind (`single_session` or `longitudinal`), `sourceVersions` (id/version/type=session), unique UUID `requestKey`. Repeating an identical request key returns the same job.
- `GET /api/v1/patients/{id}/summaries` and `/generation-jobs`
- `GET /api/v1/jobs/{id}`; `POST /cancel` or `/retry` beneath that job URL
- `GET /api/v1/patients/{id}/summaries/{summaryId}`
- `POST .../{summaryId}/review`: expectedVersion, decision accept/edit_accept/reject; edited acceptance requires text.
- `POST .../{summaryId}/facts/{factId}/review`: expectedVersion, decision confirm/correct/reject. Correction requires text, assertion, temporality and subject.

Patient assignment and clinical access are checked for reads; summary-write capability is additionally required for generation/review. Only a job's requester may cancel or retry it. Archived patients cannot generate or review summaries. Administrative processing lists show job status, not clinical text.

## Limits and recovery

A selection is limited to 30 sources, 2,000 words, 8,000 UTF-8 source bytes and a conservative total prompt/schema size. Larger selections are rejected, never silently truncated. Raw OCR and unfinished session drafts are ineligible. Unknown/approximate dates are passed explicitly. All model output remains a proposal; quote matching verifies the quoted text exists, **not that the model interpreted it correctly**. No clinical accuracy claim is made.

The worker uses a 360-second lease and a unique run ID. Interrupted work is reclaimed after lease expiry, with at most three attempts before failure. Explicit retry resets attempts. A failed/cancelled job can only retry while its source versions remain current. Cancellation discards output; it does not immediately interrupt an already-running model call. A stopped worker leaves jobs queued until restarted.

Facts and prose are independently reviewed. Future indicator/report code must deliberately choose eligible current records and confirmed facts; accepting prose must never be treated as fact confirmation. This milestone does not implement indicators, report exports or automated diagnosis.

## Verification

`python -m pytest -q` covers encryption, scope isolation, idempotent submission, source eligibility, stale review conflicts, amendment freshness, separate fact review, cancellation during generation, retry and quotation rejection. Frontend verification uses `npx tsc --noEmit`. A separate live integration check uses synthetic records through the frontend proxy, PostgreSQL and the real local model; it removes its temporary records afterward.


## Fact review and category safeguards

The fact card shows plain descriptions for whether a statement was reported/denied, its time relative to the source session, and who it concerns. Editing controls are inside **Correct this suggestion**. Corrections can change the category alone while preserving the original wording; original generated facts remain retained.

Prompt v3 defines categories and contrasts patient progress/ratings with clinician-delivered treatment. Narrow deterministic checks classify explicit “rated … N/10” statements as observations when supported by their quotation, and downgrade intervention labels without explicit clinician-action wording to Other / unclear. Changed categories retain modelProposedLabel and a reviewNote. These checks can flag valid interventions phrased differently, and do not prove semantic correctness or prevent all hallucinations. Clinician review remains necessary. Existing saved drafts are not rewritten automatically.
