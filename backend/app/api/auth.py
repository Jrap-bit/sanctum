from fastapi import APIRouter
from fastapi import Request
from fastapi import Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from ..core.config import get_settings
from ..core.security import COOKIE_NAME
from ..services import auth as auth_service
from ..services.auth import UserOutput
from ..services.auth import issue_session
from ..services.auth import public_user
from .deps import CurrentUser
from .deps import Db


router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize(cls, value):
        return value.strip().lower()


class ActivateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=128)


@router.post("/login")
def login(data: LoginInput, request: Request, response: Response, db: Db):
    user_id = auth_service.login(db, request, data)
    old_token = request.cookies.get(COOKIE_NAME)
    issue_session(response, user_id, old_token=old_token)
    return {"success": True}


@router.get("/me", response_model=UserOutput)
def me(user: CurrentUser):
    return public_user(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Db):
    token = request.cookies.get(COOKIE_NAME)
    auth_service.logout(db, request, token)
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
    )
    return {"success": True}


@router.post("/ws-ticket")
def ws_ticket(user: CurrentUser):
    return auth_service.ws_ticket(user)


@router.post("/activate")
def activate(data: ActivateInput, request: Request, db: Db):
    return auth_service.activate(db, request, data)


@router.get("/providers")
def providers():
    return auth_service.providers()


@router.get("/google/login")
def google_login(next: str = "/patients"):
    auth_url = auth_service.google_login_url(next)
    return RedirectResponse(auth_url, status_code=302)


@router.get("/google/callback")
def google_callback(
    request: Request,
    db: Db,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    target_next, user_id = auth_service.google_callback(
        db, request, code=code, state=state, error=error
    )
    response = RedirectResponse(target_next, status_code=302)
    if user_id is not None:
        old_token = request.cookies.get(COOKIE_NAME)
        issue_session(response, user_id, old_token=old_token)
    return response
