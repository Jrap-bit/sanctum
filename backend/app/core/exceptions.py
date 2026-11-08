"""Failures that adapters raise and the API maps to stable responses."""


class CiphertextIntegrityError(Exception):
    """Authentication failed: the ciphertext was altered, substituted, or wrapped under another key."""


class KeyUnavailableError(Exception):
    """Key material is missing or unreadable. This is an outage, not tampering."""


class AdapterConfigurationError(Exception):
    """An adapter name in configuration does not match a registered implementation."""
