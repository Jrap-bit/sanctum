"""Model catalog API."""
from fastapi import APIRouter
from fastapi import HTTPException

from ..adapters import llm as ai
from ..core.config import get_settings
from .deps import CurrentUser


router = APIRouter(tags=["Model catalog"])


@router.get("/api/v1/models")
def list_models(user: CurrentUser):
    if not {"summaries:write", "operations:manage"} & set(user.capabilities):
        raise HTTPException(403, "This action is outside your permissions.")
    settings = get_settings()
    return {
        "default": settings.summary_model,
        "items": ai.status()["models"],
    }
