from fastapi import FastAPI
from fastapi import Request
from uuid import uuid4

from .api.admin_users import router as admin_router
from .api.auth import router as auth_router
from .api.concerns import router as concern_router
from .api.documents import router as document_router
from .api.grants import router as grant_router
from .api.indicators import router as indicator_router
from .api.medications import router as medication_router
from .api.patients import router as patient_router
from .api.processing import router as processing_router
from .api.ratings import router as rating_router
from .api.review import router as review_router
from .api.rules import router as rule_router
from .api.sessions import router as session_router
from .api.summaries import router as summary_router
from .core.config import get_settings


from .api.audit import router as audit_router
from .api.model_catalog import router as model_catalog_router
from .api.operations import router as operations_router
from .api.reports import router as report_router
from .api.ws import router as ws_router
from .core.errors import error, register_error_handlers

app = FastAPI(title="Sanctum API", version="0.5.0")
register_error_handlers(app)


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


@app.get("/api/v1/health", tags=["Health"])
def health():
    return {"status": "ok"}


app.include_router(auth_router)


app.include_router(admin_router)


app.include_router(patient_router)


app.include_router(session_router)


app.include_router(document_router)


app.include_router(processing_router)


app.include_router(review_router)


app.include_router(summary_router)


app.include_router(indicator_router)


app.include_router(rating_router)


app.include_router(concern_router)


app.include_router(medication_router)


app.include_router(rule_router)


app.include_router(grant_router)
app.include_router(report_router)
app.include_router(audit_router)
app.include_router(operations_router)
app.include_router(model_catalog_router)
app.include_router(ws_router)
