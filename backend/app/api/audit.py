from datetime import date
from datetime import datetime
from datetime import time
from datetime import timezone
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from sqlalchemy import select

from ..db.models import AuditEvent
from ..services.audit import record_audit
from ..services.authorization import require
from .deps import CurrentUser
from .deps import Db


router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


def parse_date(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value or not value.strip():
        return None
    val = value.strip()
    try:
        if len(val) == 10:
            d = date.fromisoformat(val)
            if end_of_day:
                return datetime.combine(d, time.max, tzinfo=timezone.utc)
            return datetime.combine(d, time.min, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise HTTPException(422, "Invalid date format.")


def parse_before(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise HTTPException(422, "Invalid date format.")


@router.get("")
def list_audit_events(
    user: CurrentUser,
    db: Db,
    request: Request,
    from_date: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    actorId: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    before: str | None = Query(default=None),
):
    require(user, "audit:read")

    statement = select(AuditEvent)

    from_dt = parse_date(from_date, end_of_day=False)
    if from_dt is not None:
        statement = statement.where(AuditEvent.created_at >= from_dt)

    to_dt = parse_date(to, end_of_day=True)
    if to_dt is not None:
        statement = statement.where(AuditEvent.created_at <= to_dt)

    actual_actor = actorId or actor
    if actual_actor and actual_actor.strip():
        statement = statement.where(AuditEvent.actor_id == actual_actor.strip())

    if action and action.strip():
        statement = statement.where(AuditEvent.action.contains(action.strip()))

    before_dt = parse_before(before)
    if before_dt is not None:
        statement = statement.where(AuditEvent.created_at < before_dt)

    statement = statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)

    rows = db.scalars(statement).all()

    items = [
        {
            "id": r.id,
            "action": r.action,
            "actorId": r.actor_id,
            "targetId": r.target_id,
            "result": r.outcome,
            "requestId": r.request_id,
            "at": r.created_at.isoformat(),
        }
        for r in rows
    ]

    next_before = rows[-1].created_at.isoformat() if len(rows) == limit else None

    record_audit(db, request, user, "audit.list", None)
    db.commit()

    return {
        "items": items,
        "nextBefore": next_before,
    }
