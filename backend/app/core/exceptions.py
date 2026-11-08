"""Failures that adapters raise and the API maps to stable responses."""
from starlette.exceptions import HTTPException


class CiphertextIntegrityError(Exception):
    """Authentication failed: the ciphertext was altered, substituted, or wrapped under another key."""


class KeyUnavailableError(Exception):
    """Key material is missing or unreadable. This is an outage, not tampering."""


class AdapterConfigurationError(Exception):
    """An adapter name in configuration does not match a registered implementation."""


class AccessDenied(HTTPException):
    """An authorisation refusal, audited by the error handler without disclosing the resource."""

    def __init__(self, status_code, detail, actor_id, target_id=None):
        super().__init__(status_code, detail)
        self.actor_id = actor_id
        self.target_id = target_id
