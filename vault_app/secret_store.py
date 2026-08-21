from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from threading import Lock


_TTL_SECONDS = 300
_store: dict[str, dict[str, datetime | str]] = {}
_lock = Lock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _prune_expired() -> None:
    now = _utcnow()
    expired_tokens = [
        token
        for token, payload in _store.items()
        if payload["expires_at"] <= now
    ]
    for token in expired_tokens:
        _store.pop(token, None)


def stash_secret(secret: str, ttl_seconds: int = _TTL_SECONDS) -> str:
    token = token_urlsafe(32)
    expires_at = _utcnow() + timedelta(seconds=ttl_seconds)

    with _lock:
        _prune_expired()
        _store[token] = {
            "secret": secret,
            "expires_at": expires_at,
        }

    return token


def get_secret(token: str) -> str | None:
    with _lock:
        _prune_expired()
        payload = _store.get(token)
        if not payload:
            return None
        return str(payload["secret"])


def delete_secret(token: str) -> None:
    with _lock:
        _store.pop(token, None)


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 10:
        return "*****"
    return f"{value[:5]}*****{value[-5:]}"
