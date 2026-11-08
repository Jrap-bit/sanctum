from hashlib import sha256
from pwdlib import PasswordHash
import secrets



passwords = PasswordHash.recommended()


# Unknown usernames still perform a real password verification.
dummy_hash = passwords.hash(secrets.token_urlsafe(32))


COOKIE_NAME = "sanctum_session"


def token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()
