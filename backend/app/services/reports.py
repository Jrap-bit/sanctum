from hashlib import sha256
from uuid import UUID
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import aliased

from ..adapters.crypto import decrypt
from ..adapters.crypto import encrypt
from ..adapters.report_pdf import render as render_pdf
from ..db.models import AISummary
from ..db.models import ClinicalNote
from ..db.models import Report
from ..db.models import now
from .audit import record_audit
from .authorization import require
from .authorization import scoped_patient
from .indicators import digest
from .indicators import latest
from .indicators import snapshot as indicator_snapshot
from .summaries import current_note
from .summaries import snapshot
from .summaries import snapshot as session_snapshot
from .summaries import sources_current


def create_preview(db, user, patient, source_versions) -> dict:
    selected_notes = []
    selected_snapshots = []
    for s in source_versions:
        note_id = str(s["id"])
        note = db.scalar(
            select(ClinicalNote).where(
                ClinicalNote.id == note_id,
                ClinicalNote.patient_id == patient.id,
            )
        )
        if note is None or not current_note(db, note) or note.version != s["version"]:
            raise HTTPException(409, "A selected record changed. Refresh the list and try again.")
        selected_notes.append(note)
        selected_snapshots.append(session_snapshot(note))

    selected_ids = {str(n.id) for n in selected_notes}

    # 1. Included session records
    session_records = []
    session_included = []
    for note, snap in zip(selected_notes, selected_snapshots):
        session_records.append({
            "kind": "session",
            "id": note.id,
            "version": note.version,
            "eventDate": snap["eventDate"],
            "title": snap["title"],
            "text": snap["text"],
        })
        session_included.append({
            "id": note.id,
            "label": snap["title"],
            "version": note.version,
            "reviewState": "finalized",
        })

    # 2. AISummaries
    summary_records = []
    summary_included = []
    summary_excluded = []
    summaries = db.scalars(
        select(AISummary)
        .where(AISummary.patient_id == patient.id)
        .order_by(AISummary.created_at, AISummary.id)
    ).all()

    for sm in summaries:
        spayload = decrypt(sm.payload, f"summary:{patient.id}:{sm.id}")
        rev_state = spayload.get("reviewState")
        src_current = sources_current(db, patient.id, spayload.get("sources", []))
        all_in_selection = all(str(src["id"]) in selected_ids for src in spayload.get("sources", []))

        if rev_state == "accepted" and src_current and all_in_selection:
            summary_records.append({
                "kind": "summary",
                "id": sm.id,
                "version": sm.version,
                "text": spayload["text"],
            })
            summary_included.append({
                "id": sm.id,
                "label": "AI summary",
                "version": sm.version,
                "reviewState": "accepted",
            })
        else:
            if rev_state == "pending":
                reason = "Awaiting review"
            elif rev_state == "rejected":
                reason = "Rejected"
            elif not src_current:
                reason = "Source changed since review"
            else:
                reason = "Source not selected"
            summary_excluded.append({
                "label": "AI summary",
                "reason": reason,
            })

    # 3. IndicatorRun
    indicator_records = []
    indicator_included = []
    indicator_excluded = []
    run = latest(db, patient.id)

    if run is not None:
        fresh_digest = digest(indicator_snapshot(db, patient.id))
        is_current = (run.input_digest == fresh_digest)
        run_payload = decrypt(run.payload, f"indicator-run:{patient.id}:{run.id}")
        run_reviews = decrypt(run.reviews, f"indicator-reviews:{patient.id}:{run.id}")

        for result in run_payload.get("results", []):
            rev = run_reviews.get(result["id"], {})
            rev_state = rev.get("state") if isinstance(rev, dict) else rev
            if is_current and rev_state in ("acknowledged", "dismissed"):
                indicator_records.append({
                    "kind": "indicator",
                    "id": result["id"],
                    "runId": run.id,
                    "name": result["name"],
                    "outcome": result["outcome"],
                    "explanation": result["explanation"],
                    "ruleVersion": result.get("ruleVersion", run.version),
                    "reviewState": rev_state,
                })
                indicator_included.append({
                    "id": result["id"],
                    "label": result["name"],
                    "version": run.version,
                    "reviewState": rev_state,
                })
            else:
                reason = "Inputs changed since evaluation" if not is_current else "Not yet reviewed"
                indicator_excluded.append({
                    "label": result["name"],
                    "reason": reason,
                })

    # Coverage
    dates = [snap["eventDate"] for snap in selected_snapshots if snap.get("eventDate")]
    if dates:
        coverage = f"{min(dates)} to {max(dates)}"
    else:
        coverage = "Undated records"

    # Patient Name
    profile = decrypt(patient.profile, f"patient:{patient.id}")
    patient_name = profile.get("displayName", "")

    report_id = str(uuid4())
    created_at = now().isoformat()

    all_included = session_included + summary_included + indicator_included
    all_records = session_records + summary_records + indicator_records
    all_excluded = summary_excluded + indicator_excluded

    manifest = {
        "id": report_id,
        "patientName": patient_name,
        "createdAt": created_at,
        "author": user.display_name,
        "coverage": coverage,
        "included": all_included,
        "excluded": all_excluded,
        "freshness": "current",
        "records": all_records,
    }

    report = Report(
        id=report_id,
        patient_id=patient.id,
        created_by=user.id,
        payload=encrypt(manifest, f"report:{patient.id}:{report_id}"),
        state="previewed",
    )
    db.add(report)
    db.flush()

    return {
        "id": manifest["id"],
        "patientName": manifest["patientName"],
        "createdAt": manifest["createdAt"],
        "author": manifest["author"],
        "coverage": manifest["coverage"],
        "included": manifest["included"],
        "excluded": manifest["excluded"],
        "freshness": manifest["freshness"],
    }


def export_pdf(db, user, request, patient, report_id) -> bytes:
    report = db.scalar(
        select(Report).where(
            Report.id == str(report_id),
            Report.patient_id == patient.id,
        )
    )
    if report is None:
        raise HTTPException(404, "Report unavailable.")

    manifest = decrypt(report.payload, f"report:{patient.id}:{report.id}")

    if patient.status == "deleting":
        raise HTTPException(409, "A record in this preview changed. Create a new preview.")

    records = manifest.get("records", [])

    for r in records:
        if r.get("kind") == "session":
            note = db.scalar(
                select(ClinicalNote).where(
                    ClinicalNote.id == r["id"],
                    ClinicalNote.patient_id == patient.id,
                )
            )
            if note is None or not current_note(db, note) or note.version != r["version"]:
                raise HTTPException(409, "A record in this preview changed. Create a new preview.")
        elif r.get("kind") == "summary":
            summary = db.scalar(
                select(AISummary).where(
                    AISummary.id == r["id"],
                    AISummary.patient_id == patient.id,
                )
            )
            if summary is None or summary.version != r["version"]:
                raise HTTPException(409, "A record in this preview changed. Create a new preview.")
            summary_payload = decrypt(summary.payload, f"summary:{patient.id}:{summary.id}")
            if summary_payload.get("reviewState") != "accepted" or not sources_current(db, patient.id, summary_payload.get("sources", [])):
                raise HTTPException(409, "A record in this preview changed. Create a new preview.")

    indicator_records = [r for r in records if r.get("kind") == "indicator"]
    if indicator_records:
        run = latest(db, patient.id)
        if run is None or run.id != indicator_records[0].get("runId"):
            raise HTTPException(409, "A record in this preview changed. Create a new preview.")
        fresh_digest = digest(indicator_snapshot(db, patient.id))
        if run.input_digest != fresh_digest:
            raise HTTPException(409, "A record in this preview changed. Create a new preview.")
        run_reviews = decrypt(run.reviews, f"indicator-reviews:{patient.id}:{run.id}")
        for r in indicator_records:
            rev = run_reviews.get(r["id"], {})
            rev_state = rev.get("state") if isinstance(rev, dict) else rev
            if rev_state != r.get("reviewState"):
                raise HTTPException(409, "A record in this preview changed. Create a new preview.")

    pdf = render_pdf(manifest)
    report.content_digest = sha256(pdf).hexdigest()
    report.state = "exported"
    report.exported_at = now()
    record_audit(db, request, user, "report.export", report.id)
    db.commit()
    return pdf


def eligible_sources(db, user, request, patient_id: UUID):
    require(user, "reports:write")
    patient = scoped_patient(db, user, patient_id, clinical=True)
    child = aliased(ClinicalNote)
    rows = db.scalars(
        select(ClinicalNote)
        .where(
            ClinicalNote.patient_id == patient.id,
            ClinicalNote.state == "finalized",
            ~select(child.id).where(child.parent_id == ClinicalNote.id, child.state == "finalized").exists(),
        )
        .order_by(ClinicalNote.created_at)
    ).all()
    items = [{k: v for k, v in snapshot(row).items() if k != "text"} for row in rows]
    record_audit(db, request, user, "report.sources_read", patient.id)
    db.commit()
    return {"items": items}


def preview(db, user, request, patient_id: UUID, body):
    require(user, "reports:write")
    patient = scoped_patient(db, user, patient_id, clinical=True)
    source_versions = [s.model_dump() if hasattr(s, "model_dump") else s for s in body.sourceVersions]
    manifest = create_preview(db, user, patient, source_versions)
    record_audit(db, request, user, "report.preview", manifest["id"])
    db.commit()
    return manifest


def export(db, user, request, patient_id: UUID, report_id: UUID) -> bytes:
    require(user, "reports:write")
    patient = scoped_patient(db, user, patient_id, clinical=True)
    return export_pdf(db, user, request, patient, report_id)

