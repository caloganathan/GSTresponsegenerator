"""Authentication and authorisation.

Two credentials are accepted on the same header, which keeps the original
single-token deployment working while the firm moves to named users:

    Bearer <APP_ACCESS_TOKEN>   legacy shared secret, treated as partner
    Bearer <session token>      issued by POST /api/auth/login

When neither APP_ACCESS_TOKEN nor any user account exists, auth is disabled
entirely — localhost development only.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Request

from . import config, users

LEGACY_USER = {
    "id": "legacy-token",
    "email": "shared-token",
    "name": "Shared Access Token",
    "role": "partner",
    "active": True,
    "permissions": users.ROLE_PERMISSIONS["partner"],
}

ANONYMOUS_USER = {
    "id": "anonymous",
    "email": "local",
    "name": "Local User",
    "role": "partner",
    "active": True,
    "permissions": users.ROLE_PERMISSIONS["partner"],
}


def _extract_token(authorization: str) -> str:
    if not authorization:
        return ""
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def _auth_disabled() -> bool:
    """Auth is off only when there is no shared secret AND no user accounts."""
    if config.APP_ACCESS_TOKEN:
        return False
    try:
        return users.user_count() == 0
    except Exception:
        # Unreadable store: fail closed, never open.
        return False


_GUEST_SESSIONS: Dict[str, Dict[str, Any]] = {}

# A guest is anyone on the internet: POST /api/auth/guest asks for no
# credential. So a guest is admitted to the routes below AND NOTHING ELSE.
#
# The first cut of guest mode issued a token that satisfied `require_auth`
# everywhere, and matters are not scoped per user — so an anonymous caller
# could list every stored matter and read each one in full, client name and
# GSTIN included. The list is an ALLOWlist on purpose: a route added later is
# closed to guests until someone decides otherwise, which is the only safe
# direction for a credential nobody had to earn.
#
# Every entry is a route that works on what the caller sends and stores
# nothing. Nothing that reads the firm's stored matters, conversations,
# dashboard, calendar or settings belongs here.
GUEST_ROUTES = frozenset({
    ("GET", "/api/features"),
    ("GET", "/api/auth/check"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/panel/config"),
    ("POST", "/api/panel/extract"),
    ("POST", "/api/panel/reconciliation"),
    ("POST", "/api/panel/estimate"),
    ("POST", "/api/panel/export-inline"),
    ("POST", "/api/panel/run"),
})

# Guest tokens used to live for the life of the process and were never
# counted, so the endpoint was also a way to grow server memory without limit.
GUEST_SESSION_TTL_HOURS = 12
GUEST_SESSION_CAP = 2000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _prune_guest_sessions() -> None:
    now = _now()
    for token in [t for t, g in _GUEST_SESSIONS.items()
                  if g.get("_expires_at") and g["_expires_at"] <= now]:
        _GUEST_SESSIONS.pop(token, None)
    # Oldest first: dicts keep insertion order.
    while len(_GUEST_SESSIONS) >= GUEST_SESSION_CAP:
        _GUEST_SESSIONS.pop(next(iter(_GUEST_SESSIONS)), None)


def _guest_user(token: str) -> Optional[Dict[str, Any]]:
    guest = _GUEST_SESSIONS.get(token)
    if guest is None:
        return None
    if guest.get("_expires_at") and guest["_expires_at"] <= _now():
        _GUEST_SESSIONS.pop(token, None)
        return None
    return {k: v for k, v in guest.items() if not k.startswith("_")}


def guest_may(method: str, path: str) -> bool:
    """Whether a guest session is admitted to this route."""
    return (method.upper(), path.rstrip("/") or "/") in GUEST_ROUTES


def create_guest_session() -> Dict[str, Any]:
    """Create an ephemeral in-memory guest session (no data persisted)."""
    _prune_guest_sessions()
    token = f"guest_{secrets.token_urlsafe(24)}"
    guest_user = {
        "id": f"guest-{secrets.token_hex(6)}",
        "email": "guest@session.local",
        "name": "Guest User",
        "role": "staff",
        "is_guest": True,
        "active": True,
        "permissions": {
            **users.ROLE_PERMISSIONS["staff"],
            "export": True,
            "view_deliberation": True,
        },
    }
    _GUEST_SESSIONS[token] = {
        **guest_user,
        "_expires_at": _now() + timedelta(hours=GUEST_SESSION_TTL_HOURS),
    }
    return {"token": token, "user": guest_user}


def revoke_guest_session(token: str) -> None:
    """Remove an ephemeral guest session."""
    if token:
        _GUEST_SESSIONS.pop(token, None)


def resolve_user(authorization: str = "") -> Optional[Dict[str, Any]]:
    """Return the user for this request, or None if unauthenticated."""
    if _auth_disabled():
        return dict(ANONYMOUS_USER)

    token = _extract_token(authorization)
    if not token:
        return None

    if config.APP_ACCESS_TOKEN and secrets.compare_digest(
        token, config.APP_ACCESS_TOKEN
    ):
        _warn_legacy_token_use()
        return dict(LEGACY_USER)

    guest = _guest_user(token)
    if guest is not None:
        return guest

    return users.resolve_session(token)


_legacy_warned = False


def _warn_legacy_token_use():
    """
    Say, once, that the shared token was used.

    The shared secret grants partner rights to whoever holds it, attributes
    every action to "Shared Access Token", and cannot be revoked for one
    person. It stays supported because deployments depend on it, but a firm
    that has moved to named users should know when something is still using
    it — silence is how a breakglass credential becomes the normal way in.

    Once per process: this runs on every authenticated request, and a line per
    request would bury everything else in the log.
    """
    global _legacy_warned
    if _legacy_warned:
        return
    _legacy_warned = True
    try:
        named_users = users.user_count()
    except Exception:
        named_users = 0
    if named_users:
        print(
            "WARNING: the shared APP_ACCESS_TOKEN was used to authenticate "
            f"while {named_users} named user account(s) exist. Actions taken "
            "with it are attributed to 'Shared Access Token' and cannot be "
            "traced to a person. Prefer named logins and keep the shared "
            "token for recovery only."
        )


def _refuse_guest_outside_allowlist(user: Dict[str, Any], request: Request) -> None:
    if user.get("is_guest") and not guest_may(request.method, request.url.path):
        raise HTTPException(
            status_code=403,
            detail="Guest sessions cannot reach stored matters or settings. "
                   "Sign in with a firm account.",
        )


async def require_auth(request: Request,
                       authorization: str = Header(default="")) -> Dict[str, Any]:
    """
    FastAPI dependency: authenticate, or 401.

    A guest session authenticates only on `GUEST_ROUTES`. This runs as the
    router-level dependency, so the refusal covers every /api route —
    including ones that do not name `require_auth` themselves.
    """
    user = resolve_user(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")
    _refuse_guest_outside_allowlist(user, request)
    return user


def require_permission(permission: str):
    """Dependency factory enforcing a named permission."""

    async def _dependency(request: Request,
                          authorization: str = Header(default="")) -> Dict[str, Any]:
        user = resolve_user(authorization)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or missing credentials")
        _refuse_guest_outside_allowlist(user, request)
        if not users.can(user, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Your role ({user.get('role')}) does not permit this action",
            )
        return user

    return _dependency


def redact_for_role(payload: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strip the raw counsel deliberation for roles that shouldn't see it.

    Staff get the determination and the verification trail — what they need to
    act — but not the firm's internal argument, which is privileged working
    material and easy to quote out of context.

    Run cost goes the same way for any role without `view_costs`. The matter
    LISTING already stripped it, but a single-matter read carried
    `metadata.usage` through untouched, so what the firm pays per run reached
    a staff screen by the other route.
    """
    redacted = dict(payload)

    if not users.can(user, "view_costs"):
        metadata = dict(redacted.get("metadata") or {})
        if metadata:
            metadata.pop("usage", None)
            metadata.pop("cost", None)
            redacted["metadata"] = metadata
        redacted.pop("usage", None)

    if users.can(user, "view_deliberation"):
        return redacted

    result = dict(redacted.get("result") or {})
    if result:
        result["analyses"] = []
        result["cross_exams"] = []
        result["_redacted"] = True
        redacted["result"] = result
    return redacted
