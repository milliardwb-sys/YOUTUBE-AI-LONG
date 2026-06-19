from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import ConfigurationError, Settings

try:
    import jwt
    from jwt import PyJWKClient
except ImportError:  # pragma: no cover - local auth mode does not need PyJWT
    jwt = None
    PyJWKClient = None


class OIDCValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OIDCIdentity:
    issuer: str
    subject: str
    email: str | None
    name: str | None
    claims: dict[str, Any]


class OIDCService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._jwks_client = None
        if settings.oidc_enabled:
            if jwt is None or PyJWKClient is None:
                raise ConfigurationError("PyJWT[crypto] is required when OIDC_ENABLED=true")
            if not settings.oidc_jwks_url:
                raise ConfigurationError("OIDC_JWKS_URL is required when OIDC_ENABLED=true")
            self._jwks_client = PyJWKClient(settings.oidc_jwks_url)

    def metadata(self) -> dict[str, object]:
        return {
            "enabled": self.settings.oidc_enabled,
            "issuer_configured": bool(self.settings.oidc_issuer_url),
            "audience_configured": bool(self.settings.oidc_audience),
            "jwks_configured": bool(self.settings.oidc_jwks_url),
            "algorithms": self.settings.oidc_algorithms,
        }

    def verify_token(self, token: str) -> OIDCIdentity:
        if not self.settings.oidc_enabled:
            raise OIDCValidationError("OIDC is not enabled")
        if jwt is None or self._jwks_client is None:
            raise OIDCValidationError("OIDC verifier is not configured")
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=self.settings.oidc_algorithms,
                audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer_url,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except Exception as exc:  # noqa: BLE001 - PyJWT raises several validation errors
            raise OIDCValidationError(str(exc)) from exc
        subject = str(claims.get("sub") or "").strip()
        issuer = str(claims.get("iss") or "").strip()
        if not subject or not issuer:
            raise OIDCValidationError("OIDC token is missing required iss/sub claims")
        return OIDCIdentity(
            issuer=issuer,
            subject=subject,
            email=_optional_claim(claims.get(self.settings.oidc_email_claim)),
            name=_optional_claim(claims.get(self.settings.oidc_name_claim)),
            claims=dict(claims),
        )


def _optional_claim(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
