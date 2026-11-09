"""Bounded, versioned settings; no arbitrary rule code."""
from fastapi import APIRouter
from fastapi import Request
from pydantic import Field
from pydantic import StrictBool
from pydantic import StrictInt
from pydantic import field_validator

from ...services import rules as rules_service
from ..deps import CurrentUser
from ..deps import Db
from ..schemas import VersionInput


router = APIRouter(tags=["Rule settings"])


@router.get("/api/v1/oversight/rules")
def list_rules(user: CurrentUser, db: Db, request: Request):
    return rules_service.list_rules(db, user, request)


@router.get("/api/v1/rules")
def inspect_rules(user: CurrentUser, db: Db, request: Request):
    return rules_service.inspect_rules(db, user, request)


class Publish(VersionInput):
    parameters: dict[str, StrictInt]
    enabled: StrictBool
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def clean(cls, v):
        if not v.strip():
            raise ValueError("Explain the change.")
        return v.strip()


@router.post("/api/v1/oversight/rules/{rule_id}/publish")
def publish(rule_id: str, data: Publish, user: CurrentUser, db: Db, request: Request):
    return rules_service.publish(db, user, request, rule_id, data)
