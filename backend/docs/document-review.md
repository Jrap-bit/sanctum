# Reviewed document import

## User workflow

1. Upload a document, start extraction and wait for completion.
2. Open **Review pages**. Compare the original-page image with the transcription.
3. Correct mistakes, decide whether to include the page, and select **Save reviewed page**. Do this for every page, including exclusions.
4. Unreadable pages must be excluded. If you manually transcribe them successfully, clear the unreadable flag and include them.
5. Group all included pages into sessions, assigning each page exactly once. Use known, approximate or unknown dates. Unknown dates remain blank; future historical dates are rejected.
6. Select **Confirm reviewed history**, then **Import history** in the confirmation dialog.
7. Open the created historical notes from the result links or the patient timeline.

Example: OCR reads “2 days”, but the original says “2 weeks”. Correct the transcription, save the review and assign that page to a historical session. The imported note contains the correction while the original extracted text is retained for comparison.

## What the code does and why

- `app/api/review.py` provides page review, safe previews and confirmed history import. It checks patient access and account permissions on every request.
- `app/adapters/preview_page.py` renders a PDF page or image to an inert PNG in a bounded subprocess. The review screen shows this PNG rather than embedding an active original PDF. Originals remain downloadable.
- `ExtractedPage.version` prevents stale edits overwriting a newer page review. Raw extraction and corrected text are stored separately in the encrypted page payload.
- `StoredDocument.review_version` changes whenever a page is reviewed. Confirmation checks this document-wide version, preventing import of a stale page-review snapshot.
- `DocumentImport` stores the encrypted confirmation result and request signature. Its document primary key permits only one confirmed import per document.
- Confirmation creates finalized `ClinicalNote` rows and audit records in the same transaction. All included pages must be reviewed, readable and assigned once. Excluded pages cannot be assigned. A group is limited to 100,000 characters.
- A repeated confirmation with the same groups and dates returns the original session IDs. Different groups after import return 409. Concurrent requests serialize through the existing patient row lock, so they cannot create duplicate historical notes.
- Imported pages become read-only. Later corrections use the existing session-amendment workflow; the original finalized note stays intact.

## Provenance and dates

Imported notes preserve document ID, filename, page numbers, page-review versions, importing account and import timestamp. The UI labels the importing clinician **Imported by**; it does not infer the original document author's identity. Amendments preserve source metadata.

Known, approximate and unknown date states are stored distinctly. Approximate dates are visibly labelled in the session and timeline. Upload time is never substituted for the clinical date. If an amendment changes the date, its date becomes known (or unknown if cleared); earlier versions retain the original date status.

## API

Base: `/api/v1/patients/{patientId}/documents/{documentId}`.

- `GET /pages`: raw and corrected text, review flags, page versions, document version, import result and available review action.
- `PATCH /pages/{pageNumber}`: `{correctedText, included, unreadable, expectedVersion}`. Returns the saved page plus `documentVersion`.
- `GET /pages/{pageNumber}/original`: protected PNG comparison preview. Invalid page numbers are rejected and access is checked again.
- `POST /confirm`: `{expectedVersion, groups:[{pageNumbers, dateStatus, eventDate}]}`. Returns document version and created session IDs/links.

Review requires clinical-read, document-write and patient access. Confirmation additionally requires clinical-write. Archived patients cannot be reviewed/imported until reactivated. Other clinicians without patient access and administrators without clinical access cannot view pages or previews.

## Conflict handling

The screen keeps unsaved text after a failed save. On 409 it offers comparison with the latest saved page, followed by an explicit choice to replace local edits. Save requests disable editing/navigation while pending. Page navigation and confirmation are blocked while the current page has unsaved changes. Full browser unload warns about unsaved changes.

## Setup and verification

Run `alembic upgrade head` from the backend virtual environment to apply `0007_document_review`. It has already been applied to this local database. No new dependencies were required. Other development machines need this migration before running the updated backend.

92 backend tests passed, and frontend type-checking passed. Tests cover review versions, group completeness/uniqueness, excluded and unreadable pages, known/approximate/unknown dates, source preservation through amendments, patient scope, archival, preview output and rollback on audit failure. A live check through the frontend proxy and PostgreSQL verified original-page preview, saved corrections and two simultaneous confirmations returning the same note IDs. Temporary test records were removed. These are API/integration checks, not a claim of automated browser interaction testing for the new review screen.

Current limits: a document is confirmed as one batch; all included pages must be assigned before import. A document with no includable pages stays stored/reviewed without creating a historical session. Page corrections after confirmed import use note amendments. Reviewed historical notes can now be selected for [local AI summary drafts](ai-summaries.md). Withdrawal, indicators and reports are later features.
