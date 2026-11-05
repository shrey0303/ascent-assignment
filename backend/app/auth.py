"""Test logins and signed session tokens (stdlib HMAC, no extra dependency).

The token carries only the username and expiry. Role and account are looked up from users.json on
every request, so a client cannot raise its own privileges by editing the token.
"""
import base64
import hashlib
import hmac
import json
import time
from functools import lru_cache

from . import config
from .access import ROLES, Principal


class AuthError(Exception):
    pass


@lru_cache(maxsize=1)
def users() -> dict[str, dict]:
    entries = json.loads((config.DATA_DIR / "users.json").read_text(encoding="utf-8"))
    for user in entries:
        if user["role"] not in ROLES:
            raise ValueError(f"Unknown role {user['role']!r} for {user['username']}")
    return {u["username"]: u for u in entries}


def _sign(body: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()


def login(username: str, password: str) -> str:
    if username not in users() or not hmac.compare_digest(password.encode(), config.DEMO_PASSWORD.encode()):
        raise AuthError("Invalid username or password.")
    claims = {"sub": username, "exp": int(time.time()) + config.SESSION_TTL_MINUTES * 60}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
    return f"{body}.{_sign(body)}"


def principal_from_token(token: str) -> Principal:
    try:
        body, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _sign(body)):
            raise AuthError("Invalid session.")
        claims = json.loads(base64.urlsafe_b64decode(body.encode()))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthError("Invalid session.") from exc
    if claims.get("exp", 0) < time.time():
        raise AuthError("Session expired. Please sign in again.")
    user = users().get(claims.get("sub"))
    if user is None:
        raise AuthError("Unknown user.")
    return Principal(user_id=user["username"], name=user["name"], role=user["role"], account_id=user["account_id"])
