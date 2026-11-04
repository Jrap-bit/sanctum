from hashlib import sha256
import secrets

from pwdlib import PasswordHash

passwords = PasswordHash.recommended()
# Unknown usernames still perform a real password verification.
dummy_hash = passwords.hash(secrets.token_urlsafe(32))
COOKIE_NAME = "sanctum_session"


def token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


ROLE_CAPABILITIES = {
    "clinician": ["patients:read", "patients:create", "clinical:read", "clinical:write",
                  "documents:write", "summaries:write", "indicators:write", "reports:write"],
    "admin": ["patients:read", "patients:create", "users:manage", "audit:read", "operations:manage"],
    "oversight": ["patients:read", "clinical:read", "grants:approve", "rules:publish"],
}
