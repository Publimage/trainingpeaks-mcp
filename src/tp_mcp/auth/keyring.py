"""Keyring-based credential storage for TrainingPeaks authentication."""

from dataclasses import dataclass, field

import keyring
from keyring.errors import KeyringError, NoKeyringError

SERVICE_NAME = "trainingpeaks-mcp"
USERNAME = "production_tpauth"


@dataclass
class CredentialResult:
    """Result of a credential operation."""

    success: bool
    message: str
    cookie: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        """Safe repr that never exposes cookie value."""
        cookie_status = "present" if self.cookie else "None"
        return f"CredentialResult(success={self.success}, cookie=<{cookie_status}>, message={self.message!r})"


def is_keyring_available() -> bool:
    """Check if a keyring backend is available."""
    try:
        backend = keyring.get_keyring()
        # Use the backend capability API: fail/null both have class name Keyring.
        return backend.priority > 0
    except (NoKeyringError, KeyringError, RuntimeError):
        return False


def store_credential(cookie: str) -> CredentialResult:
    """Store the TrainingPeaks auth cookie in the system keyring.

    Args:
        cookie: The Production_tpAuth cookie value.

    Returns:
        CredentialResult with success status.
    """
    if not cookie or not cookie.strip():
        return CredentialResult(success=False, message="Cookie value cannot be empty")

    try:
        keyring.set_password(SERVICE_NAME, USERNAME, cookie.strip())
        return CredentialResult(success=True, message="Credential stored in keyring")
    except NoKeyringError:
        return CredentialResult(success=False, message="No keyring backend available. Use encrypted file storage.")
    except KeyringError as e:
        return CredentialResult(success=False, message=f"Keyring error: {e}")


def get_credential() -> CredentialResult:
    """Retrieve the TrainingPeaks auth cookie from the system keyring.

    Returns:
        CredentialResult with cookie if found.
    """
    try:
        cookie = keyring.get_password(SERVICE_NAME, USERNAME)
        if cookie:
            return CredentialResult(success=True, message="Credential retrieved", cookie=cookie)
        return CredentialResult(success=False, message="No credential stored")
    except NoKeyringError:
        return CredentialResult(success=False, message="No keyring backend available. Use encrypted file storage.")
    except KeyringError as e:
        return CredentialResult(success=False, message=f"Keyring error: {e}")


def clear_credential() -> CredentialResult:
    """Remove the TrainingPeaks auth cookie from the system keyring.

    Returns:
        CredentialResult with success status.
    """
    try:
        keyring.delete_password(SERVICE_NAME, USERNAME)
        return CredentialResult(success=True, message="Credential cleared")
    except keyring.errors.PasswordDeleteError:
        # Password doesn't exist, that's fine
        return CredentialResult(success=True, message="No credential to clear")
    except NoKeyringError:
        return CredentialResult(success=False, message="No keyring backend available")
    except KeyringError as e:
        return CredentialResult(success=False, message=f"Keyring error: {e}")
