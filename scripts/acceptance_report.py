#!/usr/bin/env python3
"""Run the automated evidence for acceptance tests T-01..T-15 and write a report.

Usage, from the repository root: backend/.venv313/bin/python scripts/acceptance_report.py
"""
import re
import subprocess
import sys
import time
from pathlib import Path

MAPPING = [
    ("T-01", "FR-01", "Authentication and access control", ["test_auth.py", "test_access_audit.py", "test_oauth.py", "test_grants.py"]),
    ("T-02", "FR-02", "User account management", ["test_admin_users.py"]),
    ("T-03", "FR-03", "Patient profile management", ["test_patients.py"]),
    ("T-04", "FR-04", "Session notes and amendments", ["test_sessions.py"]),
    ("T-05", "FR-05", "Patient clinical history", ["test_patients.py", "test_document_review.py"]),
    ("T-06", "FR-06", "Document upload and storage", ["test_documents.py", "test_objectstore.py"]),
    ("T-07", "FR-07", "Local text extraction and OCR", ["test_processing.py", "test_extraction_adapters.py", "test_ws.py"]),
    ("T-08", "FR-08", "Transcription review and import", ["test_document_review.py"]),
    ("T-09", "FR-09", "AI summaries and labels", ["test_summaries.py", "test_llm_engines.py"]),
    ("T-10", "FR-10", "AI output review and fact verification", ["test_summaries.py"]),
    ("T-11", "FR-11", "Rule-based indicators", ["test_truth_tables.py", "test_indicators.py", "test_rules.py", "test_ratings.py", "test_concerns.py", "test_medications.py", "test_documentation.py"]),
    ("T-12", "FR-12", "Follow-up tasks", ["test_patients.py", "test_indicators.py"]),
    ("T-13", "FR-13", "Report generation and export", ["test_reports.py"]),
    ("T-14", "FR-14", "Audit and data recovery", ["test_audit.py", "test_operations.py"]),
    ("T-15", "FR-15", "Data security and deletion", ["test_crypto.py", "test_operations.py", "test_access_audit.py"]),
]


def run(files):
    paths = [f"tests/{name}" for name in files]
    result = subprocess.run([".venv313/bin/python", "-m", "pytest", *paths, "-q"], cwd="backend", capture_output=True, text=True)
    summary = result.stdout.strip().splitlines()[-1]
    return result.returncode, re.sub(r"\s+in [0-9.]+s.*$", "", re.sub(r",?\s*\d+ warnings?", "", summary)).strip("= ")


def main():
    revision = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    lines = ["# Acceptance tests T-01 to T-15", "",
             f"Automated evidence at application revision `{revision}`, run {time.strftime('%Y-%m-%d %H:%M %Z')}, using in-memory SQLite and fake Redis. "
             "Behaviour that depends on PostgreSQL, real workers, or a real model is covered separately in `integration-tests.md`.", "",
             "| Test | Requirement | Capability | Evidence (backend/tests) | Result |", "|---|---|---|---|---|"]
    failed = False
    for test, requirement, capability, files in MAPPING:
        code, summary = run(files)
        failed = failed or code != 0
        evidence = ", ".join(f"`{name}`" for name in files)
        lines.append(f"| {test} | {requirement} | {capability} | {evidence} | {'pass' if code == 0 else 'FAIL'}: {summary} |")
        print(test, "pass" if code == 0 else "FAIL", summary, flush=True)
    Path("docs/evidence/acceptance-tests.md").write_text("\n".join(lines) + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
