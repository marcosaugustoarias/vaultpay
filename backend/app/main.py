"""VaultPay API entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.errors import install_error_handlers
from app.logging_config import configure_logging
from app.routers import accounts, audit, auth, mfa, transfers
from app.security.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from app.services import ledger


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as db:
        ledger.ensure_treasury(db)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    docs = settings.docs_enabled
    app = FastAPI(
        title="VaultPay API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,  # SEC-CFG-01: no API explorer in production
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )

    # Order matters: the LAST added middleware is the OUTERMOST.
    # SEC-API-04: explicit CORS allow-list (never "*" with credentials) + Host header validation.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Requested-With"],
        max_age=600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    install_error_handlers(app)
    for r in (auth.router, mfa.router, accounts.router, transfers.router, audit.router):
        app.include_router(r)

    @app.get("/api/meta", tags=["meta"])
    def meta():
        """Public, non-sensitive limits so the UI can warn users *before* they hit a rule."""
        s = get_settings()
        return {
            "step_up_threshold_cents": s.step_up_threshold_cents,
            "max_transfer_cents": s.max_transfer_cents,
            "demo_funding_enabled": s.demo_funding_enabled,
            "demo_funding_max_cents": s.demo_funding_max_cents,
        }

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()
