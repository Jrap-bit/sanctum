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
    ("T-01", "FR-01", "Authentication and access control", ["integration/test_auth.py", "integration/test_access_audit.py", "integration/test_oauth.py", "integration/test_grants.py"]),
    ("T-02", "FR-02", "User account management", ["integration/test_admin_users.py"]),
    ("T-03", "FR-03", "Patient profile management", ["integration/test_patients.py"]),
    ("T-04", "FR-04", "Session notes and amendments", ["integration/test_sessions.py"]),
    ("T-05", "FR-05", "Patient clinical history", ["integration/test_patients.py", "integration/test_document_review.py"]),
    ("T-06", "FR-06", "Document upload and storage", ["integration/test_documents.py", "integration/test_objectstore.py", "unit/test_objectstore_registry.py"]),
    ("T-07", "FR-07", "Local text extraction and OCR", ["integration/test_processing.py", "unit/test_extraction_adapters.py", "integration/test_ws.py"]),
    ("T-08", "FR-08", "Transcription review and import", ["integration/test_document_review.py"]),
    ("T-09", "FR-09", "AI summaries and labels", ["integration/test_summaries.py", "unit/test_summary_grounding.py", "unit/test_llm_engines.py"]),
    ("T-10", "FR-10", "AI output review and fact verification", ["integration/test_summaries.py", "unit/test_summary_grounding.py"]),
    ("T-11", "FR-11", "Rule-based indicators", ["unit/test_truth_tables.py", "integration/test_indicators.py", "unit/test_followup_rule.py", "integration/test_rules.py", "unit/test_rule_thresholds.py", "integration/test_ratings.py", "unit/test_rating_rule.py", "integration/test_concerns.py", "unit/test_concern_rule.py", "integration/test_medications.py", "unit/test_medication_rule.py", "integration/test_documentation.py", "unit/test_documentation_rule.py"]),
    ("T-12", "FR-12", "Follow-up tasks", ["integration/test_patients.py", "integration/test_indicators.py", "unit/test_followup_rule.py"]),
    ("T-13", "FR-13", "Report generation and export", ["integration/test_reports.py"]),
    ("T-14", "FR-14", "Audit and data recovery", ["integration/test_audit.py", "integration/test_operations.py"]),
    ("T-15", "FR-15", "Data security and deletion", ["integration/test_crypto.py", "integration/test_operations.py", "integration/test_access_audit.py"]),
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
