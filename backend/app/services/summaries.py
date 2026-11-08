from hashlib import sha256
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import aliased

from ..adapters import llm as ai
from ..adapters.crypto import decrypt
from ..adapters.crypto import encrypt
from ..core.cache import publish_progress
from ..db.models import AISummary
from ..db.models import ClinicalNote
from ..db.models import SummaryJob
from ..db.models import now
from .audit import record_audit
from .authorization import has_access
from .authorization import require
from .authorization import scoped_patient
from .sessions import content_of


def current_note(db, note):
    return (
        note is not None
        and note.state == "finalized"
        and not db.scalar(
            select(ClinicalNote.id).where(
                ClinicalNote.parent_id == note.id,
                ClinicalNote.state == "finalized",
            )
        )
    )


def snapshot(note):
    content = content_of(note)
    text = content["text"]
    for section in ("concerns", "observations", "interventions", "medicationReported"):
        for item in content[section]:
            text += f"\n{section}: {item['text']} [assertion={item['assertion']}; temporality={item['temporality']}]"
    return {
        "id": note.id,
        "version": note.version,
        "type": "session",
        "title": "Reviewed historical session" if content.get("source") else "Finalized session",
        "eventDate": note.event_date.isoformat() if note.event_date else None,
        "dateStatus": content.get("dateStatus", "known" if note.event_date else "unknown"),
        "href": f"/patients/{note.patient_id}/sessions/{note.id}",
        "text": text,
        "wordCount": len(text.split()),
        "byteCount": len(text.encode()),
    }


def sources_current(db, patient_id, sources):
    for source in sources:
        note = db.get(ClinicalNote, source["id"])
        if not current_note(db, note) or note.patient_id != patient_id or note.version != source["version"]:
            return False
    return True


def job_output(job):
    return {
        "id": job.id,
        "state": job.state,
        "progress": 100 if job.state == "completed" else 0,
        "resultId": job.summary_id,
        "message": job.message,
        "kind": "summary",
    }


def summary_output(db, user, patient, row):
    payload = decrypt(row.payload, f"summary:{patient.id}:{row.id}")
    current = sources_current(db, patient.id, payload["sources"])
    actions = []
    if (
        patient.status == "active"
        and has_access(db, user, patient.id, write=True)
        and current
        and "summaries:write" in user.capabilities
    ):
        if payload["reviewState"] == "pending":
            actions.append("review")
        if payload["reviewState"] != "rejected":
            actions.append("review_facts")
    return {
        "id": row.id,
        "kind": row.kind,
        "version": row.version,
        **payload,
        "freshness": "current" if current else "stale",
        "sources": [{k: v for k, v in s.items() if k != "text"} for s in payload["sources"]],
        "generatedAt": row.created_at,
        "allowedActions": actions,
    }


def read_summary(db, user, patient_id, summary_id, write=False):
    if write:
        require(user, "summaries:write")
    patient = scoped_patient(db, user, patient_id, clinical=True, lock=write)
    if write and patient.status != "active":
        raise HTTPException(409, "Reactivate the patient before reviewing summaries.")
    row = db.scalar(select(AISummary).where(AISummary.id == str(summary_id), AISummary.patient_id == patient.id))
    if row is None:
        raise HTTPException(404, "Summary unavailable.")
    return patient, row


def review_payload(db, patient, row, expected):
    if row.version != expected:
        raise HTTPException(409, "This review changed. Reload the latest version before deciding.")
    payload = decrypt(row.payload, f"summary:{patient.id}:{row.id}")
    if not sources_current(db, patient.id, payload["sources"]):
        raise HTTPException(409, "A source was superseded. Generate a new draft from current records.")
    return payload


def save_review(db, request, user, patient, row, payload, action):
    payload["reviewHistory"].append(
        {
            "action": action,
            "actor": user.display_name,
            "actorId": user.id,
            "at": now().isoformat(),
        }
    )
    row.version += 1
    row.payload = encrypt(payload, f"summary:{patient.id}:{row.id}")
    record_audit(db, request, user, action, row.id)
    db.flush()
    result = summary_output(db, user, patient, row)
    db.commit()
    return result


def scoped_job(db, user, jid, write=False):
    job = db.get(SummaryJob, str(jid))
    if job is None:
        raise HTTPException(404, "Job unavailable.")
    scoped_patient(db, user, job.patient_id, clinical=True, lock=write)
    if write:
        require(user, "summaries:write")
        if job.requested_by != user.id:
            raise HTTPException(403, "Only the requester can change this generation job.")
        job = db.scalar(
            select(SummaryJob)
            .where(SummaryJob.id == job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return job


def model_status(user, model=None):
    if not {"summaries:write", "operations:manage"} & set(user.capabilities):
        raise HTTPException(403, "This action is outside your permissions.")
    return ai.status(model)


def eligible(db, user, request, patient_id):
    require(user, "summaries:write")
    patient = scoped_patient(db, user, patient_id, clinical=True)
    child = aliased(ClinicalNote)
    rows = db.scalars(
        select(ClinicalNote)
        .where(
            ClinicalNote.patient_id == patient.id,
            ClinicalNote.state == "finalized",
            ~select(child.id)
            .where(child.parent_id == ClinicalNote.id, child.state == "finalized")
            .exists(),
        )
        .order_by(ClinicalNote.created_at)
    ).all()
    items = [{k: v for k, v in snapshot(row).items() if k != "text"} for row in rows]
    record_audit(db, request, user, "summary.sources_listed", patient.id)
    db.commit()
    return {"items": items}


def create(db, user, request, patient_id, data):
    require(user, "summaries:write")
    patient = scoped_patient(db, user, patient_id, clinical=True, lock=True)
    if patient.status != "active":
        raise HTTPException(409, "Reactivate the patient before generating summaries.")
    canonical = {
        "kind": data.kind,
        "model": data.model,
        "sources": sorted(
            [s.model_dump(mode="json") for s in data.sourceVersions],
            key=lambda s: s["id"],
        ),
    }
    fingerprint = sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    old = db.scalar(
        select(SummaryJob).where(
            SummaryJob.requested_by == user.id,
            SummaryJob.request_key == str(data.requestKey),
        )
    )
    if old:
        if old.patient_id != patient.id or old.request_hash != fingerprint:
            raise HTTPException(409, "This request key belongs to a different source selection.")
        return job_output(old)
    sources = []
    for version in data.sourceVersions:
        note = db.scalar(
            select(ClinicalNote).where(
                ClinicalNote.id == str(version.id),
                ClinicalNote.patient_id == patient.id,
            )
        )
        if not current_note(db, note) or note.version != version.version:
            raise HTTPException(409, "A selected source is unavailable, unfinished or superseded. Refresh the source list.")
        sources.append(snapshot(note))
    sources.sort(key=lambda s: (s["eventDate"] or "9999", s["id"]))
    try:
        ai.check_size(sources, data.kind)
    except ValueError:
        raise HTTPException(422, "The selected records exceed the local model input limit. Choose fewer or shorter sources; nothing was truncated.") from None
    jid = str(uuid4())
    job = SummaryJob(
        id=jid,
        patient_id=patient.id,
        requested_by=user.id,
        request_key=str(data.requestKey),
        request_hash=fingerprint,
        model=data.model,
        kind=data.kind,
        payload=encrypt({"sources": sources}, f"summary-job:{patient.id}:{jid}"),
        state="queued",
    )
    db.add(job)
    record_audit(db, request, user, "summary.generation_requested", jid)
    db.flush()
    result = job_output(job)
    db.commit()
    return result


def list_summaries(db, user, request, patient_id):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    rows = db.scalars(
        select(AISummary)
        .where(AISummary.patient_id == patient.id)
        .order_by(AISummary.created_at.desc())
    ).all()
    result = {"items": [summary_output(db, user, patient, row) for row in rows]}
    record_audit(db, request, user, "summary.list", patient.id)
    db.commit()
    return result


def patient_jobs(db, user, request, patient_id):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    rows = db.scalars(
        select(SummaryJob)
        .where(SummaryJob.patient_id == patient.id, SummaryJob.requested_by == user.id)
        .order_by(SummaryJob.created_at.desc())
        .limit(20)
    ).all()
    result = {"items": [job_output(row) for row in rows]}
    record_audit(db, request, user, "summary.jobs_listed", patient.id)
    db.commit()
    return result


def get_summary(db, user, request, patient_id, summary_id):
    patient, row = read_summary(db, user, patient_id, summary_id)
    result = summary_output(db, user, patient, row)
    record_audit(db, request, user, "summary.read", row.id)
    db.commit()
    return result


def review_summary(db, user, request, patient_id, summary_id, data):
    patient, row = read_summary(db, user, patient_id, summary_id, True)
    payload = review_payload(db, patient, row, data.expectedVersion)
    if payload["reviewState"] != "pending":
        raise HTTPException(409, "This summary already has a review decision.")
    payload["reviewState"] = "rejected" if data.decision == "reject" else "accepted"
    if data.decision == "edit_accept":
        payload["text"] = data.text.strip()
    return save_review(db, request, user, patient, row, payload, "summary." + data.decision)


def review_fact(db, user, request, patient_id, summary_id, fact_id, data):
    patient, row = read_summary(db, user, patient_id, summary_id, True)
    payload = review_payload(db, patient, row, data.expectedVersion)
    fact = next((f for f in payload["facts"] if f["id"] == str(fact_id)), None)
    if fact is None:
        raise HTTPException(404, "Suggested fact unavailable.")
    if fact["state"] != "pending":
        raise HTTPException(409, "This fact already has a review decision.")
    if payload["reviewState"] == "rejected":
        raise HTTPException(409, "Facts from a rejected summary cannot be confirmed. Generate a new draft.")
    fact["state"] = "rejected" if data.decision == "reject" else "confirmed"
    if data.decision == "correct":
        fact.update(
            text=data.text.strip(),
            assertion=data.assertion,
            temporality=data.temporality,
            subject=data.subject,
        )
        if data.label is not None:
            fact["label"] = data.label
    return save_review(db, request, user, patient, row, payload, "summary.fact_" + data.decision)


def get_job(db, user, request, job_id):
    job = scoped_job(db, user, job_id)
    result = job_output(job)
    record_audit(db, request, user, "summary.job_read", job.id)
    db.commit()
    return result


def cancel_job(db, user, request, job_id):
    job = scoped_job(db, user, job_id, True)
    if job.state not in {"queued", "running"}:
        raise HTTPException(409, "This job is no longer active.")
    job.state = "cancelled"
    job.run_id = None
    job.lease_until = None
    record_audit(db, request, user, "summary.generation_cancelled", job.id)
    result = job_output(job)
    db.commit()
    publish_progress(job.id, state="cancelled", message=job.message)
    return result


def retry_job(db, user, request, job_id):
    job = scoped_job(db, user, job_id, True)
    if job.state not in {"failed", "cancelled"}:
        raise HTTPException(409, "Only failed or cancelled generation can be retried.")
    patient = scoped_patient(db, user, job.patient_id, clinical=True)
    if patient.status != "active":
        raise HTTPException(409, "Reactivate the patient first.")
    payload = decrypt(job.payload, f"summary-job:{job.patient_id}:{job.id}")
    if not sources_current(db, job.patient_id, payload["sources"]):
        raise HTTPException(409, "The source selection is stale. Create a new request.")
    job.state = "queued"
    job.run_id = None
    job.lease_until = None
    job.attempts = 0
    job.message = None
    record_audit(db, request, user, "summary.generation_retried", job.id)
    result = job_output(job)
    db.commit()
    return result
