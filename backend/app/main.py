import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings, validate_real_mode_config
from app.modules.auth.router import router as auth_router
from app.modules.accounts.router import router as accounts_router
from app.modules.campaigns.router import (
    campaigns_router,
    ad_groups_router,
    targets_router,
    sync_router,
)
from app.modules.search_terms.router import search_terms_router, st_sync_router
from app.modules.suggestions.router import suggestions_router
from app.modules.rules.router import rules_router, templates_router
from app.modules.performance.router import router as performance_router
from app.modules.execution.router import execution_router
from app.modules.sync_jobs.router import router as sync_jobs_router

# Make all app.* loggers visible at INFO level regardless of uvicorn's root config.
logging.getLogger("app").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

app = FastAPI(title="Internal PPC OS API", version="0.6.3-debug")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"] if settings.env == "dev" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(campaigns_router)
app.include_router(ad_groups_router)
app.include_router(targets_router)
app.include_router(sync_router)
app.include_router(search_terms_router)
app.include_router(st_sync_router)
app.include_router(suggestions_router)
app.include_router(rules_router)
app.include_router(templates_router)
app.include_router(performance_router)
app.include_router(execution_router)
app.include_router(sync_jobs_router)

# Dev-only bootstrap — registered unconditionally but the handler returns 404
# when AMAZON_MOCK_MODE=false, so no production risk.
from app.modules.dev.router import dev_router  # noqa: E402
app.include_router(dev_router)


# ---------------------------------------------------------------------------
# Global exception handler — logs full traceback + returns detail in response
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch any unhandled exception that escapes an endpoint.

    - Logs the full Python traceback (visible in `docker compose logs api`)
    - Returns 500 JSON with the error type and message in `detail`
      so the frontend shows a readable message instead of "Internal Server Error"
    """
    tb = traceback.format_exc()
    logger.error(
        "[UNHANDLED] %s %s raised %s: %s\n%s",
        request.method,
        request.url.path,
        type(exc).__name__,
        exc,
        tb,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"{type(exc).__name__}: {exc}",
        },
    )


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

@app.on_event("startup")
def _startup_checks() -> None:
    """Log warnings for any missing real-mode config on startup."""
    mode = "MOCK" if settings.amazon_mock_mode else "REAL"
    logger.warning("[startup] AMAZON_MOCK_MODE=%s (version 0.6.3-debug)", mode)

    missing = validate_real_mode_config()
    if missing:
        logger.warning(
            "[startup] AMAZON_MOCK_MODE=false but the following env vars are not set: %s. "
            "Amazon OAuth and API calls will fail until they are configured.",
            ", ".join(missing),
        )
    else:
        if not settings.amazon_mock_mode:
            logger.warning(
                "[startup] Real mode config looks complete. "
                "Register AMAZON_REDIRECT_URI=%s in your Amazon LWA app.",
                settings.amazon_redirect_uri,
            )

    # Built-in rule templates are reference data, not user data: seeding them
    # here means a fresh deployment has usable starting points without anyone
    # remembering to run a command. Idempotent — matches builtins by name.
    try:
        from app.database import SessionLocal
        from app.modules.rules.templates import seed_builtin_templates

        db = SessionLocal()
        try:
            seed_builtin_templates(db)
        finally:
            db.close()
    except Exception as exc:
        # Never let reference data block the API from serving requests.
        logger.error("[startup] rule template seeding failed: %s", exc)


@app.get("/health/sync")
def health_sync() -> dict:
    """Sync freshness, for uptime monitors and the UI.

    Unauthenticated so a monitor can watch it without credentials. Exposes no
    ad data — only account ids, names and timestamps. Always returns 200;
    read the `healthy` field rather than relying on the status code.
    """
    from app.database import SessionLocal
    from app.worker.health import collect_sync_health

    db = SessionLocal()
    try:
        return collect_sync_health(db, settings.sync_stale_after_hours)
    finally:
        db.close()


@app.get("/health")
def health() -> dict:
    mode = "mock" if settings.amazon_mock_mode else "real"
    missing = validate_real_mode_config()
    return {
        "status": "ok",
        "version": "0.6.3-debug",
        "amazon_mode": mode,
        "real_mode_config_complete": len(missing) == 0,
        "missing_vars": missing if missing else None,
    }
