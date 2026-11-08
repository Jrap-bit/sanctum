from fastapi import APIRouter
from fastapi import Query
from fastapi import Request

from ..services import audit_log as audit_log_service
from .deps import CurrentUser
from .deps import Db


router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


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
    return audit_log_service.list_audit_events(
        db,
        user,
        request,
        from_date=from_date,
        to=to,
        actorId=actorId,
        actor=actor,
        action=action,
        limit=limit,
        before=before,
    )
