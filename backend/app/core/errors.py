"""One flat error envelope for every failure the API reports."""
from uuid import uuid4

from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException

from .database import get_db
from .exceptions import AccessDenied, CiphertextIntegrityError, KeyUnavailableError

CODES = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "VERSION_CONFLICT", 429: "RATE_LIMITED"}


def error(request, status, code, message, fields=None):
    return JSONResponse(status_code=status, content={
        "code": code, "message": message, "fieldErrors": fields or {},
        "requestId": request.state.request_id,
    })


def _record_event(request, action, outcome, actor_id=None, target_id=None):
    # A separate transaction: the refused or failed request's own session is discarded.
    from ..db.models import AuditEvent

    provider = request.app.dependency_overrides.get(get_db, get_db)
    sessions = provider()
    try:
        db = next(sessions)
        db.add(AuditEvent(action=action, outcome=outcome, actor_id=actor_id, target_id=target_id,
                          request_id=getattr(request.state, "request_id", str(uuid4()))))
        db.commit()
    except SQLAlchemyError:
        pass
    finally:
        sessions.close()


def register_error_handlers(app):
    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if isinstance(exc, AccessDenied):
            await run_in_threadpool(_record_event, request, "access.denied", "denied", exc.actor_id, exc.target_id)
        response = error(request, exc.status_code, CODES.get(exc.status_code, "REQUEST_FAILED"), str(exc.detail))
        response.headers.update(exc.headers or {})
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = {".".join(map(str, e["loc"][1:])): e["msg"] for e in exc.errors()}
        return error(request, 422, "VALIDATION_ERROR", "Check the submitted fields.", fields)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        # Never expose SQL parameters, which can include credentials.
        return error(request, 503, "DATABASE_UNAVAILABLE", "The records service is unavailable.")

    @app.exception_handler(StaleDataError)
    async def stale_update(request, exc):
        return error(request, 409, "VERSION_CONFLICT", "A newer version exists. Refresh and try again.")

    @app.exception_handler(KeyUnavailableError)
    async def key_unavailable(request, exc):
        return error(request, 503, "KEY_UNAVAILABLE", "Protected storage is unavailable. Check the encryption key.")

    @app.exception_handler(CiphertextIntegrityError)
    async def integrity_failure(request, exc):
        await run_in_threadpool(_record_event, request, "crypto.integrity_failure", "failure")
        return error(request, 500, "RECORD_INTEGRITY_FAILED", "A protected record failed its integrity check.")
