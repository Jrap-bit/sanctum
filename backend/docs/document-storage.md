# Document upload and storage

Implemented on 5 November 2026. This slice stores originals. Local OCR and processing jobs were subsequently added; see [OCR processing](ocr-processing.md). Extracted-page review and confirmed import are now implemented; see [document review](document-review.md). Withdrawal remains unfinished.

## Simple workflow

Open a patient you can access, choose Documents, select a PDF/JPEG/PNG, and upload. The backend validates the file, encrypts it and saves it with its patient association. Refreshing the screen lists the persisted original. Download original retrieves the exact original bytes after checking access again.

Uploading a file does not create a session note or approve its contents. It adds an undated “Document uploaded” entry to the patient timeline. The upload timestamp is not treated as the historical clinical date.

## Code and purpose

- `app/api/documents.py`: upload, validation, duplicate detection, listing and protected downloads.
- `StoredDocument` in `app/db/models.py`: stores the patient/uploader IDs, encrypted filename, encrypted original, byte count, page count, media type and content digest. Original bytes are loaded only when needed, not when listing files.
- Migration `0005_documents`: creates this storage table and a database uniqueness rule for patient plus content digest.
- Existing encryption key: encrypts the originals and filenames. Each ciphertext includes its patient/document identity, so swapping encrypted records fails validation.
- Existing audit system: records upload, list and download actions without filenames or document contents. Upload and audit/timeline records commit together. An audit-storage failure rolls the upload back.
- Documents page: handles real upload progress, validation errors, retry after failure, success and original downloads. It distinguishes bytes sent from validation/save completion. It does not advertise OCR completion or show a review link before that action is available.

## Endpoints

All paths are under `/api/v1/patients/{patientId}/documents`.

| Method/path | Result |
| --- | --- |
| POST empty suffix | Multipart field named `file`; returns document metadata with HTTP 201 |
| GET empty suffix | `{items: [...]}` |
| GET `/{documentId}/original` | Original bytes as an attachment, with no-store and nosniff headers |

Metadata fields: `id`, `filename`, `uploadedAt`, `uploader`, `pageCount`, `sizeBytes`, `mediaType`, `reviewState`, `jobState`, `version`, `allowedActions`. Before extraction, `reviewState="unreviewed"`, `jobState="not_started"`, `version=1`, `allowedActions=["download"]`. Processing updates job state/progress and adds the extraction-view action when completed.

Uploads require `documents:write`, `clinical:read`, a valid login and access to that particular patient. List/download require clinical read and patient access. Administrators have no implicit clinical-document access. Archived patients retain download access for authorised users but reject new uploads.

## Validation and limits

- One multipart file per request; no additional form fields.
- File limit: 25 MiB. Entire streamed multipart body: 25 MiB plus 64 KiB overhead, enforced even without Content-Length.
- Files stay in memory during parsing until encrypted, avoiding plaintext temporary-file spooling. Concurrent large uploads therefore consume memory; production deployment needs request concurrency and resource limits.
- Supported extensions and declared types must agree. The file's actual PDF/image structure is checked too.
- PDFs must parse, be unlocked, and contain 1–500 pages.
- JPEG/PNG images must decode, contain one frame and be at most 20 megapixels.
- Empty, corrupt, unsupported and oversized files are rejected with actionable errors.
- Exact duplicate bytes for the same patient return 409, even under another filename. A file may legitimately be stored for a different patient. Duplicate overrides are not implemented.
- Validation is format checking, not antivirus/content sanitisation. Originals download as attachments; they are never embedded in this application.

The encrypted bytes live in PostgreSQL, not a public upload folder. This keeps the original and its metadata in one transaction. Database growth should be monitored. The encryption key must be preserved with recovery material; a database copy alone cannot decrypt records. Automated backup/restore remains unfinished.

## Setup on another machine

From the backend folder, with its virtual environment active:

```sh
pip install -r requirements.txt
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload --reload-dir app
```

New dependencies: python-multipart for form parsing, pypdf for PDF validation/page counting, and Pillow for image validation. The local development migration has already been applied.

## Verification

71 backend tests passed, including 17 document cases covering valid PDF/PNG/JPEG files, encryption, duplicates, patient isolation, admin denial, revoked access, archived patients, invalid files, upload limits, filename handling, ciphertext tampering and audit rollback. Frontend type-checking passed. PostgreSQL migration/model comparison passed. A live HTTP check through the frontend proxy uploaded/listed/downloaded an original and confirmed that a fresh Python process could decrypt it. Temporary test records were removed. This does not claim a browser-interaction test of the new upload controls.

Library references: [Starlette form parsing](https://starlette.dev/requests/), [pypdf reader](https://pypdf.readthedocs.io/en/latest/modules/PdfReader.html), [Pillow security](https://pillow.readthedocs.io/en/stable/handbook/security.html).
