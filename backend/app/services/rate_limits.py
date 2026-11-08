"""Persistent fixed-window limits shared across API processes."""
from datetime import datetime
from datetime import timezone
from sqlalchemy import delete
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from ..core.security import token_digest
from ..db.models import LoginBucket
from ..db.models import now


def consume_limits(db, buckets):
    current = now()
    window = int(current.timestamp()) // 900
    expires = datetime.fromtimestamp((window + 1) * 900, timezone.utc)
    db.execute(delete(LoginBucket).where(LoginBucket.expires_at <= current))
    permitted = True
    for scope, value, limit in buckets:
        key = token_digest(f"{scope}:{value}:{window}")
        try:
            with db.begin_nested():
                db.add(LoginBucket(key=key, attempts=0, expires_at=expires))
                db.flush()
        except IntegrityError:
            pass
        count = db.execute(update(LoginBucket).where(LoginBucket.key == key)
                           .values(attempts=LoginBucket.attempts + 1)
                           .returning(LoginBucket.attempts)).scalar_one()
        permitted = permitted and count <= limit
    db.commit()
    return permitted
