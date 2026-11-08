# Acceptance tests T-01 to T-15

Automated evidence at application revision `6231761`, run 2026-11-09 01:43 IST, using in-memory SQLite and fake Redis. Behaviour that depends on PostgreSQL, real workers, or a real model is covered separately in `integration-tests.md`.

| Test | Requirement | Capability | Evidence (backend/tests) | Result |
|---|---|---|---|---|
| T-01 | FR-01 | Authentication and access control | `test_auth.py`, `test_access_audit.py`, `test_oauth.py`, `test_grants.py` | pass: 28 passed |
| T-02 | FR-02 | User account management | `test_admin_users.py` | pass: 12 passed |
| T-03 | FR-03 | Patient profile management | `test_patients.py` | pass: 16 passed |
| T-04 | FR-04 | Session notes and amendments | `test_sessions.py` | pass: 14 passed |
| T-05 | FR-05 | Patient clinical history | `test_patients.py`, `test_document_review.py` | pass: 28 passed |
| T-06 | FR-06 | Document upload and storage | `test_documents.py`, `test_objectstore.py` | pass: 29 passed |
| T-07 | FR-07 | Local text extraction and OCR | `test_processing.py`, `test_extraction_adapters.py`, `test_ws.py` | pass: 22 passed |
| T-08 | FR-08 | Transcription review and import | `test_document_review.py` | pass: 12 passed |
| T-09 | FR-09 | AI summaries and labels | `test_summaries.py`, `test_llm_engines.py` | pass: 31 passed |
| T-10 | FR-10 | AI output review and fact verification | `test_summaries.py` | pass: 20 passed |
| T-11 | FR-11 | Rule-based indicators | `test_truth_tables.py`, `test_indicators.py`, `test_rules.py`, `test_ratings.py`, `test_concerns.py`, `test_medications.py`, `test_documentation.py` | pass: 118 passed |
| T-12 | FR-12 | Follow-up tasks | `test_patients.py`, `test_indicators.py` | pass: 27 passed |
| T-13 | FR-13 | Report generation and export | `test_reports.py` | pass: 7 passed |
| T-14 | FR-14 | Audit and data recovery | `test_audit.py`, `test_operations.py` | pass: 17 passed |
| T-15 | FR-15 | Data security and deletion | `test_crypto.py`, `test_operations.py`, `test_access_audit.py` | pass: 23 passed |
