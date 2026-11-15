"""Authentication: Cognito ID tokens (when configured) or dev mode, plus single-use WebSocket tickets.

Dev mode (no Cognito settings): no token -> user "dev-user"; any token -> a stable dev user derived from it,
so two browsers with different dev tokens do not see each other's conversations. Never use dev mode in public.
"""
import hashlib
import secrets
import threading
import time
from datetime import datetime, timezone

import jwt

from server.config import Settings


class AuthError(Exception):
    pass


def bearer_token(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


class Authenticator:
    def __init__(self, settings: Settings, jwks_client=None):
        self.settings = settings
        self._jwks = jwks_client
        if settings.auth_mode == "cognito":
            self.issuer = (f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
                           f"{settings.cognito_pool_id}")
            if self._jwks is None:
                self._jwks = jwt.PyJWKClient(f"{self.issuer}/.well-known/jwks.json", cache_keys=True)

    def user_from_token(self, token: str | None) -> dict:
        """{"id", "email"} for a valid token. Raises AuthError otherwise."""
        if self.settings.auth_mode == "dev":
            if not token:
                return {"id": "dev-user", "email": "dev-user@alphaforge.dev"}
            tag = hashlib.sha256(token.encode()).hexdigest()[:10]
            return {"id": f"dev-{tag}", "email": f"dev-{tag}@alphaforge.dev"}
        if not token:
            raise AuthError("missing Bearer token")
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=self.settings.cognito_client_id,
                                issuer=self.issuer, options={"require": ["exp", "iss", "sub", "aud"]})
        except Exception as e:  # expired, bad signature, wrong audience/issuer, JWKS unreachable
            raise AuthError(f"invalid token: {e}") from e
        if claims.get("token_use") != "id":
            raise AuthError("expected a Cognito ID token (token_use=id)")
        return {"id": claims["sub"], "email": claims.get("email") or f"{claims['sub']}@users.cognito"}


class TicketStore:
    """Single-use WebSocket tickets, valid for `ttl` seconds."""

    def __init__(self, ttl: int = 30, clock=time.monotonic):
        self.ttl, self.clock = ttl, clock
        self._tickets: dict[str, tuple[dict, float]] = {}
        self._lock = threading.Lock()

    def issue(self, user: dict) -> dict:
        ticket = secrets.token_urlsafe(24)
        with self._lock:
            now = self.clock()
            self._tickets = {t: v for t, v in self._tickets.items() if v[1] > now}  # drop expired ones
            self._tickets[ticket] = (user, now + self.ttl)
        expires = datetime.fromtimestamp(time.time() + self.ttl, tz=timezone.utc)
        return {"ticket": ticket, "expiresAt": expires.isoformat(timespec="seconds").replace("+00:00", "Z")}

    def redeem(self, ticket: str | None) -> dict:
        """The ticket's user; the ticket is consumed. Raises AuthError if unknown, used or expired."""
        with self._lock:
            entry = self._tickets.pop(ticket or "", None)
        if entry is None:
            raise AuthError("unknown or already used ticket")
        user, expires = entry
        if self.clock() > expires:
            raise AuthError("ticket expired")
        return user
