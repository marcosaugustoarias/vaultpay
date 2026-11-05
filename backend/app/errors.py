"""Error handling (SEC-API-06).

* Domain errors become stable `{detail, code}` payloads.
* Validation errors are re-written WITHOUT echoing the submitted value: FastAPI's
  default 422 includes `input`, which would reflect passwords/OTPs into responses,
  proxies and logs.
* Unhandled exceptions return a generic 500 with only a request id.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.errors import DomainError

log = logging.getLogger("vaultpay.errors")


def domain_to_http(err: DomainError, headers: dict[str, str] | None = None) -> HTTPException:
    return HTTPException(err.status_code, {"message": err.message, "code": err.code}, headers=headers)


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException):
        detail = exc.detail
        body = detail if isinstance(detail, dict) else {"message": str(detail), "code": "error"}
        return JSONResponse(
            {"detail": body, "request_id": _rid(request)}, status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exc(request: Request, exc: RequestValidationError):
        safe = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
            for e in exc.errors()  # `input` and `ctx` deliberately dropped
        ]
        return JSONResponse(
            {"detail": {"message": "Validation failed", "code": "validation_error", "errors": safe},
             "request_id": _rid(request)},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.error("unhandled exception request_id=%s", _rid(request), exc_info=exc)
        return JSONResponse(
            {"detail": {"message": "Internal server error", "code": "internal_error"},
             "request_id": _rid(request)},
            status_code=500,
        )
