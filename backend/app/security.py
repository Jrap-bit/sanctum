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

# Match the existing People-screen presets. Custom selections must fit within one
# preset; arbitrary mixed administrative/clinical authority is not accepted.
# These capabilities do not themselves create patient access links.
ACCOUNT_PRESETS = {
    "clinician": set(ROLE_CAPABILITIES["clinician"]) | {"grants:request"},
    "admin": set(ROLE_CAPABILITIES["admin"]) | {"assignments:manage", "grants:request"},
    "oversight": set(ROLE_CAPABILITIES["oversight"]) | {"reports:write", "audit:read"},
}
