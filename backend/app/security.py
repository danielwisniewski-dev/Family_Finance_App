"""Deployment policy and authenticated encryption. No secret values in errors."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


class RateLimitError(Exception):
    pass


class SecretError(RuntimeError):
    pass


class SecretBox:
    PREFIX = "sealed:v1:"

    def __init__(self, master_key: str, purpose: str):
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        if len(master_key) < 32:
            raise SecretError("Encryption key must contain at least 32 random characters")
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                   info=("family-finance/v1/" + purpose).encode()).derive(master_key.encode())
        self.cipher = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, value: bytes) -> bytes:
        return self.cipher.encrypt(value)

    def decrypt(self, value: bytes) -> bytes:
        from cryptography.fernet import InvalidToken
        try:
            return self.cipher.decrypt(value)
        except (InvalidToken, ValueError, TypeError) as exc:
            raise SecretError("Encrypted data cannot be opened with the configured key") from exc

    def seal(self, value: str) -> str:
        return self.PREFIX + self.encrypt(value.encode()).decode()

    def open(self, value: str) -> str:
        if not value.startswith(self.PREFIX):
            raise SecretError("Unencrypted token requires an explicit offline migration")
        return self.decrypt(value[len(self.PREFIX):].encode()).decode()


@dataclass(frozen=True)
class RuntimeSettings:
    hosted: bool = False
    setup_code: str = field(default="", repr=False)
    encryption_key: str = field(default="", repr=False)
    session_seconds: int = 7 * 24 * 60 * 60
    plaid_enabled: bool = False

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        mode = os.environ.get("FF_MODE", "local")
        if mode not in {"local", "hosted"}:
            raise ValueError("FF_MODE must be local or hosted")
        settings = cls(hosted=mode == "hosted", setup_code=os.environ.get("FF_SETUP_CODE", ""),
                       encryption_key=os.environ.get("FF_ENCRYPTION_KEY", ""),
                       plaid_enabled=os.environ.get("FF_PLAID_ENABLED", "false") == "true")
        if settings.hosted:
            ZoneInfo(os.environ.get("FF_TIMEZONE", "America/New_York"))
            if len(settings.setup_code) < 32 or len(settings.encryption_key) < 32:
                raise SecretError("Hosted mode requires FF_SETUP_CODE and FF_ENCRYPTION_KEY with at least 32 random characters each")
            if hmac.compare_digest(settings.setup_code, settings.encryption_key):
                raise SecretError("Setup and encryption keys must be different")
            if not settings.plaid_enabled and (os.environ.get("PLAID_ENV", "sandbox") != "sandbox" or os.environ.get("PLAID_SECRET")):
                raise ValueError("Stage 1 hosted mode does not allow bank credentials or production Plaid")
            if settings.plaid_enabled:
                if (os.environ.get("PLAID_ENV") != "production"
                        or os.environ.get("FF_PLAID_TRIAL_CONFIRMED") != "true"
                        or not os.environ.get("PLAID_CLIENT_ID") or not os.environ.get("PLAID_SECRET")
                        or not os.environ.get("PLAID_USAA_INSTITUTION_ID")
                        or os.environ.get("PLAID_PRODUCTS", "transactions") != "transactions"
                        or os.environ.get("PLAID_COUNTRY_CODES", "US") != "US"
                        or os.environ.get("PLAID_REDIRECT_URI")):
                    raise ValueError("Stage 2 requires verified Trial/USAA access, Transactions only, US, and native Android package registration")
            if os.environ.get("COACH_PROVIDER", "mock") != "mock" or os.environ.get("OPENAI_API_KEY"):
                raise ValueError("Stage 1 hosted mode requires the mock coach without provider credentials")
        elif settings.plaid_enabled or os.environ.get("PLAID_ENV", "sandbox") != "sandbox":
            raise ValueError("Production Plaid requires the encrypted hosted runtime")
        return settings

    def require_setup_code(self, supplied: object) -> None:
        if self.hosted and (not isinstance(supplied, str) or
                            not hmac.compare_digest(supplied.encode(), self.setup_code.encode())):
            raise PermissionError("A valid private setup code is required")

    def token_box(self) -> SecretBox | None:
        return SecretBox(self.encryption_key, "plaid-tokens") if self.encryption_key else None


def attempt_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
