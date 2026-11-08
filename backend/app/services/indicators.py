"""DT-03: deterministic follow-up results with retained source snapshots."""
from hashlib import sha256
import json
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select

from ..adapters.crypto import decrypt, encrypt
from ..db.models import FollowUp, IndicatorRun, now
from ..domain.rules.engine import compute
from .audit import record_audit
from .authorization import has_access, require, scoped_patient
from .concerns import concern_output, rows as concern_rows, session_snapshot
from .documentation import documentation_snapshot
from .medications import medication_output, rows as medication_rows
from .patients import clinic_today, task_output
from .ratings import rating_output, rows as rating_rows
from .rules import current_rules


RULE_VERSION = 1


def snapshot(db, patient_id):
    tasks = [
        task_output(t)
        for t in db.scalars(
            select(FollowUp)
            .where(FollowUp.patient_id == patient_id)
            .order_by(FollowUp.id)
        )
    ]
    # Explicit clinician-created tasks only; no dates inferred from prose or AI.
    return {
        "evaluationDate": clinic_today().isoformat(),
        "ruleVersion": RULE_VERSION,
        "tasks": tasks,
        "ratingRuleVersion": 1,
        "ratings": [rating_output(db, r) for r in rating_rows(db, patient_id)],
        "concernRuleVersion": 1,
        "concerns": [concern_output(db, r) for r in concern_rows(db, patient_id)],
        "sessions": session_snapshot(db, patient_id),
        "medicationRuleVersion": 1,
        "medications": [medication_output(db, r) for r in medication_rows(db, patient_id)],
        "documentationRuleVersion": 1,
        "documentation": documentation_snapshot(db, patient_id),
        "rules": current_rules(db),
    }


def digest(value):
    return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def latest(db, patient_id):
    return db.scalar(
        select(IndicatorRun)
        .where(IndicatorRun.patient_id == patient_id)
        .order_by(IndicatorRun.created_at.desc(), IndicatorRun.id.desc())
        .limit(1)
    )


def output(db, user, patient, run, live=None):
    can_write = (
        patient.status == "active"
        and has_access(db, user, patient.id, write=True)
        and "indicators:write" in user.capabilities
    )
    if run is None:
        return {"items": [], "allowedActions": ["evaluate"] if can_write else [], "evaluationId": None}
    payload = decrypt(run.payload, f"indicator-run:{patient.id}:{run.id}")
    reviews = decrypt(run.reviews, f"indicator-reviews:{patient.id}:{run.id}")
    current = run.input_digest == digest(live if live is not None else snapshot(db, patient.id))
    items = []
    for item in payload["results"]:
        review = reviews.get(item["id"], {})
        items.append({
            **item,
            "version": run.version,
            "evaluationId": run.id,
            "ruleVersion": item.get("ruleVersion", 1),
            "enabled": item.get("enabled", True),
            "freshness": "current" if current else "stale",
            "evaluatedAt": run.created_at,
            "reviewState": review.get("state", "unreviewed"),
            "reviewComment": review.get("comment"),
            "reviewedBy": review.get("actor"),
            "reviewedAt": review.get("at"),
            "allowedActions": (
                ["review"]
                if can_write and current and not review and item.get("enabled", True)
                else []
            ),
        })
    return {
        "items": items,
        "evaluationId": run.id,
        "allowedActions": ["evaluate"] if can_write else [],
    }


def get_indicators(db, user, request, patient_id):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    result = output(db, user, patient, latest(db, patient.id))
    record_audit(db, request, user, "indicator.list", patient.id)
    db.commit()
    return result


def evaluate(db, user, request, patient_id):
    require(user, "indicators:write")
    patient = scoped_patient(db, user, patient_id, clinical=True, lock=True)
    if patient.status != "active":
        raise HTTPException(409, "Reactivate the patient before evaluating indicators.")
    inputs = snapshot(db, patient.id)
    fingerprint = digest(inputs)
    run = latest(db, patient.id)
    # Repeated clicks with unchanged inputs preserve the existing evaluation/reviews.
    if run is None or run.input_digest != fingerprint:
        rid = str(uuid4())
        run = IndicatorRun(
            id=rid,
            patient_id=patient.id,
            created_by=user.id,
            input_digest=fingerprint,
            version=1,
            payload=encrypt(
                {"inputs": inputs, "results": compute(inputs, patient.id)},
                f"indicator-run:{patient.id}:{rid}",
            ),
            reviews=encrypt({}, f"indicator-reviews:{patient.id}:{rid}"),
        )
        db.add(run)
        db.flush()
        record_audit(db, request, user, "indicator.evaluate", rid)
    else:
        record_audit(db, request, user, "indicator.evaluation_reused", run.id)
    result = output(db, user, patient, run, inputs)
    db.commit()
    return result


def review_indicator(db, user, request, patient_id, indicator_id, data):
    require(user, "indicators:write")
    patient = scoped_patient(db, user, patient_id, clinical=True, lock=True)
    if patient.status != "active":
        raise HTTPException(409, "Archived patient indicators are read-only.")
    run = latest(db, patient.id)
    if run is None or run.id != str(data.evaluationId) or run.version != data.expectedVersion:
        raise HTTPException(409, "The evaluation changed. Refresh before recording your decision.")
    if run.input_digest != digest(snapshot(db, patient.id)):
        raise HTTPException(409, "The inputs or clinic date changed. Evaluate again before reviewing.")
    payload = decrypt(run.payload, f"indicator-run:{patient.id}:{run.id}")
    iid = str(indicator_id)
    item = next((i for i in payload["results"] if i["id"] == iid), None)
    if item is None:
        raise HTTPException(404, "Indicator unavailable.")
    if not item.get("enabled", True):
        raise HTTPException(409, "Disabled rules have no calculated result to review.")
    reviews = decrypt(run.reviews, f"indicator-reviews:{patient.id}:{run.id}")
    if iid in reviews:
        raise HTTPException(409, "This indicator already has a review decision.")
    reviews[iid] = {
        "state": "acknowledged" if data.decision == "acknowledge" else "dismissed",
        "comment": (data.comment or "").strip() or None,
        "actor": user.display_name,
        "actorId": user.id,
        "at": now().isoformat(),
    }
    run.reviews = encrypt(reviews, f"indicator-reviews:{patient.id}:{run.id}")
    run.version += 1
    record_audit(db, request, user, "indicator." + data.decision, iid)
    db.flush()
    result = output(db, user, patient, run)
    db.commit()
    return result


def history(db, user, request, patient_id):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    rows = db.scalars(
        select(IndicatorRun)
        .where(IndicatorRun.patient_id == patient.id)
        .order_by(IndicatorRun.created_at.desc())
        .limit(50)
    ).all()
    result = {"items": [{"id": r.id, "evaluatedAt": r.created_at} for r in rows]}
    record_audit(db, request, user, "indicator.history", patient.id)
    db.commit()
    return result


def historical_run(db, user, request, patient_id, run_id):
    patient = scoped_patient(db, user, patient_id, clinical=True)
    run = db.scalar(
        select(IndicatorRun).where(
            IndicatorRun.id == str(run_id),
            IndicatorRun.patient_id == patient.id,
        )
    )
    if run is None:
        raise HTTPException(404, "Evaluation unavailable.")
    result = output(db, user, patient, run)
    for item in result["items"]:
        item["allowedActions"] = []
    result["allowedActions"] = []
    record_audit(db, request, user, "indicator.history_read", run.id)
    db.commit()
    return result
