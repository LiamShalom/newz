"""Phase 8 ASGI middleware — pure-ASGI classes only (see RESEARCH Pitfall 1).

Two classes:
  - XFFStrip: PRIV-01. Strips IP-revealing headers from scope before any
    downstream code (logging middleware, route handlers, Sentry capture)
    sees them. Must be the OUTERMOST middleware (D-12).
  - RequestIDAndContextvarsBind: PRIV-02. Generates server-side request_id
    (D-11 — never trusts upstream X-Request-ID) and binds structlog
    contextvars (request_id, session_hash) for the duration of the request.

CRITICAL — PURE ASGI ONLY. Starlette's stdlib base-middleware silently breaks
contextvars propagation into route handlers (RESEARCH Pitfall 1). All classes
here implement __init__(self, app) + async __call__(self, scope, receive, send)
directly without subclassing any framework helper.
"""

import uuid

from structlog.contextvars import bind_contextvars, clear_contextvars

from .anonymity import session_hash


# Headers to strip — PRIV-01 + defense in depth against alt header names.
# Lowercase bytes because ASGI headers are bytes-tuples in lowercase.
_FORBIDDEN_HEADERS: frozenset[bytes] = frozenset({
    b"x-forwarded-for",
    b"x-real-ip",
    b"forwarded",
    b"true-client-ip",
    b"cf-connecting-ip",         # Cloudflare leak vector if ever fronted
    b"x-client-ip",
})


class XFFStrip:
    """Pure ASGI middleware. Strips IP-revealing headers from scope BEFORE any
    downstream code (logging middleware, route handlers, Sentry capture) sees them.

    Must be the OUTERMOST middleware (added LAST in app.add_middleware order — D-12).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope)  # shallow copy — don't mutate the original
            scope["headers"] = [
                (name, value)
                for name, value in scope.get("headers", [])
                if name.lower() not in _FORBIDDEN_HEADERS
            ]
        await self.app(scope, receive, send)


class RequestIDAndContextvarsBind:
    """Pure ASGI middleware. Generates a server-side request_id and binds
    structlog contextvars (request_id, session_hash) for the duration of the request.

    PRIV-02 whitelist: only request_id, session_hash, clip_id ever bind.
    clip_id is bound later by the route handler (it doesn't exist yet at this layer).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # D-11 — server-side UUID4. Never trust upstream X-Request-ID.
        request_id = uuid.uuid4().hex

        # Extract X-Session-Id header if present (anonymous session UUID from
        # iOS Safari localStorage). Hash it BEFORE binding (PRIV-02).
        session_uuid: str | None = None
        for name, value in scope.get("headers", []):
            if name == b"x-session-id":
                session_uuid = value.decode("latin-1").strip()
                break

        # Defensive clear — single-worker asyncio shouldn't leak across requests
        # but try/finally is the canonical structlog-contextvars pattern.
        clear_contextvars()
        bind_kwargs: dict = {"request_id": request_id}
        if session_uuid:
            bind_kwargs["session_hash"] = session_hash(session_uuid)
        bind_contextvars(**bind_kwargs)

        try:
            await self.app(scope, receive, send)
        finally:
            clear_contextvars()
