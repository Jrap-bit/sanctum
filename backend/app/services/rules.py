"""Bounded, versioned settings; no arbitrary rule code."""
from copy import deepcopy
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db.models import RuleHead, RuleRevision, User
from ..domain.rules.defaults import DEFAULTS
from .audit import record_audit
from .authorization import require


def current_rules(db):
    result = {
        key: {"id": key, **deepcopy(value), "version": 1, "enabled": True}
        for key, value in DEFAULTS.items()
    }
    revisions = db.scalars(
        select(RuleRevision).join(
            RuleHead,
            (RuleHead.id == RuleRevision.rule_id)
            & (RuleHead.current_version == RuleRevision.version),
        )
    ).all()
    for row in revisions:
        if row.rule_id in result:
            result[row.rule_id].update(
                version=row.version,
                enabled=row.enabled,
                parameters=row.parameters,
            )
    return result


def output(db):
    items = list(current_rules(db).values())
    for item in items:
        history = db.scalars(
            select(RuleRevision)
            .where(RuleRevision.rule_id == item["id"])
            .order_by(RuleRevision.version.desc())
        ).all()
        item["history"] = [
            {
                "version": r.version,
                "author": db.get(User, r.actor_id).display_name if r.actor_id else "Built-in defaults",
                "at": r.created_at,
                "reason": r.reason,
                "parameters": r.parameters,
                "enabled": r.enabled,
            }
            for r in history
        ]
    return {"items": items}


def list_rules(db, user, request):
    require(user, "rules:publish")
    result = output(db)
    record_audit(db, request, user, "rule.list", None)
    db.commit()
    return result


def inspect_rules(db, user, request):
    require(user, "clinical:read")
    result = {"items": list(current_rules(db).values())}
    record_audit(db, request, user, "rule.inspect", None)
    db.commit()
    return result


def publish(db, user, request, rule_id: str, data):
    require(user, "rules:publish")
    if rule_id not in DEFAULTS:
        raise HTTPException(404, "Rule unavailable.")
    bounds = DEFAULTS[rule_id]["bounds"]
    if (
        set(data.parameters) != set(bounds)
        or any(not bounds[k]["min"] <= v <= bounds[k]["max"] for k, v in data.parameters.items())
    ):
        raise HTTPException(422, "Use exactly the supported parameters within their displayed bounds.")
    if rule_id == "repeated-concern" and data.parameters["K"] > data.parameters["W"]:
        raise HTTPException(422, "Required sessions cannot exceed sessions checked.")
    head = db.scalar(select(RuleHead).where(RuleHead.id == rule_id).with_for_update())
    if head is None:
        head = RuleHead(id=rule_id, current_version=1)
        db.add(head)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "The rule changed. Refresh and try again.") from None
        db.add(
            RuleRevision(
                rule_id=rule_id,
                version=1,
                parameters=DEFAULTS[rule_id]["parameters"],
                enabled=True,
                reason="Built-in defaults",
            )
        )
    if head.current_version != data.expectedVersion:
        raise HTTPException(409, "A newer rule version exists. Refresh before publishing.")
    old = db.get(RuleRevision, (rule_id, head.current_version))
    if old and old.parameters == data.parameters and old.enabled == data.enabled:
        raise HTTPException(409, "These settings are already published.")
    version = head.current_version + 1
    db.add(
        RuleRevision(
            rule_id=rule_id,
            version=version,
            parameters=data.parameters,
            enabled=data.enabled,
            reason=data.reason,
            actor_id=user.id,
        )
    )
    head.current_version = version
    record_audit(db, request, user, "rule.publish", rule_id)
    db.flush()
    result = output(db)
    db.commit()
    return result
