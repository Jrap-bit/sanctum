from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException

from .auth import router as auth_router
from .config import get_settings
from .patients import router as patient_router
from .sessions import router as session_router

app = FastAPI(title="Sanctum API", version="0.4.0")
app.include_router(auth_router)
app.include_router(patient_router)
app.include_router(session_router)


def error(request, status, code, message, fields=None):
    return JSONResponse(status_code=status, content={
        "code": code, "message": message, "fieldErrors": fields or {},
        "requestId": request.state.request_id,
    })


@app.middleware("http")
async def request_safety(request: Request, call_next):
    request.state.request_id = str(uuid4())
    settings = get_settings()
    # Browsers supply Origin on writes. Reject absent/null/untrusted origins,
    # including login, to prevent another website using this browser's cookies.
    origins = set(settings.allowed_origins) | {settings.allowed_origin}
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get("origin") not in origins:
        response = error(request, 403, "UNTRUSTED_ORIGIN", "Open Sanctum from its configured address.")
    else:
        response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    codes = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "VERSION_CONFLICT", 429: "RATE_LIMITED"}
    return error(request, exc.status_code, codes.get(exc.status_code, "REQUEST_FAILED"), str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    fields = {".".join(map(str, e["loc"][1:])): e["msg"] for e in exc.errors()}
    return error(request, 422, "VALIDATION_ERROR", "Check the submitted fields.", fields)


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    # Never expose SQL parameters (which can include credentials) in public errors.
    return error(request, 503, "DATABASE_UNAVAILABLE", "The records service is unavailable.")


@app.exception_handler(StaleDataError)
async def stale_update(request, exc):
    return error(request, 409, "VERSION_CONFLICT", "A newer version exists. Refresh and try again.")


@app.get("/api/v1/health", tags=["Health"])
def health():
    return {"status": "ok"}
