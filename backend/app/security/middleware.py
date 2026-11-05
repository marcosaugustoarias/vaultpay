"""HTTP hardening middleware.

SEC-API-03  security headers (+ HSTS outside development)
SEC-API-05  request body size limit (Content-Length *and* streamed bytes)
SEC-AUDIT-02 request id + access log without bodies / query strings
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings

access_log = logging.getLogger("vaultpay.access")

_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


class SecurityHeadersMiddleware:
    """Adds security headers and a request id to every response (pure ASGI)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        path = scope["path"]
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                h = MutableHeaders(scope=message)
                h["X-Request-ID"] = request_id
                h["X-Content-Type-Options"] = "nosniff"
                h["X-Frame-Options"] = "DENY"
                h["Referrer-Policy"] = "no-referrer"
                h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
                h["Cross-Origin-Opener-Policy"] = "same-origin"
                h["Cross-Origin-Resource-Policy"] = "same-origin"
                h["Cache-Control"] = "no-store"  # never cache balances / tokens
                h["Pragma"] = "no-cache"
                if not (settings.docs_enabled and path.startswith(("/docs", "/redoc"))):
                    h["Content-Security-Policy"] = _API_CSP  # Swagger UI needs inline JS
                if settings.env != "development":
                    h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # Only metadata. Never bodies, query strings, cookies or Authorization.
            access_log.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": scope["method"],
                        "path": path,
                        "status": status_code,
                        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    }
                )
            )


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = get_settings().max_body_bytes
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            await self._reject(send)
            return

        received = 0
        started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Answer 413 right now. FastAPI wraps body-read errors into a 400,
                    # so we must not leave the status code to the framework.
                    if not started and not rejected:
                        rejected = True
                        await self._reject(send)
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return  # 413 already sent; drop whatever the app tries to say afterwards
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        with contextlib.suppress(_BodyTooLarge):
            await self.app(scope, limited_receive, tracking_send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = b'{"detail":"Request body too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
