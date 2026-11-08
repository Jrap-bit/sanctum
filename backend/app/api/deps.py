from fastapi import Depends
from fastapi import Request
from sqlalchemy.orm import Session
from typing import Annotated

from ..core.database import get_db
from ..db.models import User
from ..services.auth import user_from_request


Db = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: Db) -> User:
    return user_from_request(request, db)


CurrentUser = Annotated[User, Depends(get_current_user)]
