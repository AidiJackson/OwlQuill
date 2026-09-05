"""Ficshon FastAPI application."""
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.admin_seed import (
    ensure_admin_user,
    ensure_commons_realm,
    ensure_identity_schema,
    ensure_seeder_flags,
)
from app.core.starter_seed import ensure_starter_realms_and_posts
from app.core.invite_seed import seed_invite_codes
from app.core.style_shop_seed import seed_style_presets
from app.api.routes import auth, users, characters, realms, posts, comments, composition, reactions, ai, scenes, character_visual, messages, images, scene_images, image_generator, grammar, storylab, reports, admin, blocks, admin_diagnostics, story_spaces, character_accessory, identity_evolution, candidate_slot, notifications, style_shops, body_canon, body_identity, canon_api, adult_studio, adult_studio_admin, editor_studio
from app.api.routes.story_spaces import published_router
from app.api.routes import rp_stories
from app.api.routes import character_home


logger = logging.getLogger(__name__)


def _db_identity() -> dict:
    """TEMP DIAG (remove after prod DB is confirmed): redacted DB host + name.

    Exposes only the database hostname and database name parsed from
    DATABASE_URL — never the user, password, port, or query string. Used to
    identify which database the running process is connected to without needing
    authentication.
    """
    from urllib.parse import urlparse
    try:
        p = urlparse(settings.DATABASE_URL)
        return {"host": p.hostname, "name": (p.path or "").lstrip("/")}
    except Exception:
        return {"host": None, "name": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    # TEMP DIAG (remove after prod DB is confirmed): emit a single consolidated
    # line identifying the connected database + counts. Uses print(flush=True)
    # (PYTHONUNBUFFERED=1 in start-prod.sh) so it reaches the deployment logs
    # regardless of logging configuration. Never raises — startup must not break.
    try:
        _ident = _db_identity()
        from app.core.database import SessionLocal as _diag_sl
        from sqlalchemy import text as _diag_text
        _diag_db = _diag_sl()
        try:
            _u = _diag_db.execute(_diag_text("SELECT count(*) FROM users")).scalar()
            _c = _diag_db.execute(_diag_text("SELECT count(*) FROM characters")).scalar()
        finally:
            _diag_db.close()
        print(
            f"TEMP DIAG host={_ident.get('host')} db={_ident.get('name')} "
            f"users={_u} characters={_c}",
            flush=True,
        )
    except Exception as _diag_e:  # pragma: no cover - diagnostic only
        print(f"TEMP DIAG host=? db=? counts_error={type(_diag_e).__name__}", flush=True)
    if settings.SMTP_HOST:
        logger.info("Email: SMTP enabled (host=%s)", settings.SMTP_HOST)
    else:
        logger.info("Email: DEV console mode")
    if settings.is_dev_mode():
        logger.info(
            "image_provider_config "
            "IMAGE_PROVIDER=%s IMAGE_MODEL=%s "
            "IDENTITY_IMAGE_PROVIDER=%r IDENTITY_SEED_PROVIDER=%s "
            "IDENTITY_ANGLES_PROVIDER=%s openai_key_present=%s",
            settings.IMAGE_PROVIDER,
            settings.IMAGE_MODEL,
            settings.IDENTITY_IMAGE_PROVIDER or "(not set)",
            settings.IDENTITY_SEED_PROVIDER,
            settings.IDENTITY_ANGLES_PROVIDER,
            bool(settings.OPENAI_API_KEY),
        )
    ensure_identity_schema()
    ensure_admin_user()
    ensure_seeder_flags()
    ensure_commons_realm()
    try:
        ensure_starter_realms_and_posts()
    except Exception:
        pass  # logged inside; never crash startup
    try:
        seed_invite_codes()
    except Exception:
        pass  # logged inside; never crash startup
    try:
        from app.core.database import SessionLocal as _SL
        _db = _SL()
        try:
            seed_style_presets(_db)
        finally:
            _db.close()
    except Exception:
        pass  # logged inside; never crash startup
    yield
    # Shutdown (nothing to do)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    # Disable interactive API docs in production (DEBUG=False).
    # They are re-enabled automatically when DEBUG=True (dev mode).
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# Add rate limiter state and exception handler.
# The handler is ours rather than slowapi's default: same 429, same limits, but
# a `detail` the UI can display and a Retry-After header (see auth module).
app.state.limiter = auth.limiter
app.add_exception_handler(RateLimitExceeded, auth.rate_limit_exceeded_handler)


PUBLIC_ERROR_MESSAGE = "Something went wrong on our end. Please try again."


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return JSON — never plain text — for exceptions no route handled.

    Without this, Starlette answers an unhandled exception with a plain-text
    ``Internal Server Error`` body. Every frontend client parses error bodies as
    JSON, so that body fails to parse and the real fault is flattened into a
    generic "Something went wrong" with no way to tell a storage failure from a
    timeout. That is exactly what stalled the Canon image-generation incident.

    The public payload stays deliberately generic: no exception type, message,
    or traceback, since those can carry file paths, connection strings, and
    provider detail. The correlation id is the bridge — it is returned to the
    caller and logged alongside the full traceback, so a user-reported id can be
    matched to its server-side stack without exposing anything.
    """
    request_id = uuid.uuid4().hex[:12]
    # logger.exception attaches the traceback; keep every detail server-side.
    logger.exception(
        "UNHANDLED_EXCEPTION request_id=%s method=%s path=%s exc_type=%s",
        request_id,
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": PUBLIC_ERROR_MESSAGE, "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


# Registered for bare Exception, so FastAPI's own HTTPException and validation
# handlers still own their responses; only genuinely unhandled faults land here.
#
# Note: Starlette's ServerErrorMiddleware prefers its HTML debug page when
# app.debug is True, so this handler is what production (DEBUG=False) returns
# while local dev keeps the interactive traceback.
app.add_exception_handler(Exception, unhandled_exception_handler)

# Configure CORS - uses parsed origins from settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(characters.router, prefix="/characters", tags=["characters"])
app.include_router(realms.router, prefix="/realms", tags=["realms"])
app.include_router(posts.router, prefix="/posts", tags=["posts"])
app.include_router(comments.router, prefix="/comments", tags=["comments"])
app.include_router(reactions.router, prefix="/reactions", tags=["reactions"])
app.include_router(ai.router, prefix="/ai", tags=["ai"])
app.include_router(scenes.router, prefix="/scenes", tags=["scenes"])
app.include_router(character_visual.router, prefix="/characters", tags=["character-visual"])
app.include_router(scene_images.router, prefix="/characters", tags=["scene-images"])
app.include_router(image_generator.router, prefix="/characters", tags=["image-generator"])
app.include_router(character_accessory.router, prefix="/characters", tags=["character-accessory"])
app.include_router(identity_evolution.router, prefix="/characters", tags=["identity-evolution"])
app.include_router(candidate_slot.router, prefix="/characters", tags=["identity-evolution"])
app.include_router(messages.router, prefix="/messages", tags=["messages"])
app.include_router(images.router, prefix="/images", tags=["images"])
app.include_router(grammar.router, prefix="/grammar", tags=["grammar"])
app.include_router(storylab.router, prefix="/storylab", tags=["storylab"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(blocks.router, prefix="/blocks", tags=["blocks"])
app.include_router(story_spaces.router, prefix="/story-spaces", tags=["story-spaces"])
app.include_router(published_router, prefix="/published-stories", tags=["published-stories"])
app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
app.include_router(style_shops.router, tags=["style-shops"])
app.include_router(body_canon.router, prefix="/characters", tags=["body-canon"])
app.include_router(body_identity.router, prefix="/characters", tags=["body-identity"])
app.include_router(canon_api.router, prefix="/characters", tags=["identity-canon"])
app.include_router(character_home.router, prefix="/characters", tags=["character-home"])
app.include_router(rp_stories.router, prefix="/rp-stories", tags=["rp-stories"])
app.include_router(adult_studio.router, prefix="/adult-studio", tags=["adult-studio"])
app.include_router(adult_studio_admin.router, prefix="/admin/adult-studio", tags=["adult-studio-admin"])
app.include_router(editor_studio.router, prefix="/editor", tags=["editor-studio"])
app.include_router(composition.router, prefix="/composition", tags=["composition"])

# Mirror all routes under /api/* prefix
api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(characters.router, prefix="/characters", tags=["characters"])
api_router.include_router(realms.router, prefix="/realms", tags=["realms"])
api_router.include_router(posts.router, prefix="/posts", tags=["posts"])
api_router.include_router(comments.router, prefix="/comments", tags=["comments"])
api_router.include_router(reactions.router, prefix="/reactions", tags=["reactions"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(scenes.router, prefix="/scenes", tags=["scenes"])
api_router.include_router(character_visual.router, prefix="/characters", tags=["character-visual"])
api_router.include_router(scene_images.router, prefix="/characters", tags=["scene-images"])
api_router.include_router(image_generator.router, prefix="/characters", tags=["image-generator"])
api_router.include_router(character_accessory.router, prefix="/characters", tags=["character-accessory"])
api_router.include_router(identity_evolution.router, prefix="/characters", tags=["identity-evolution"])
api_router.include_router(candidate_slot.router, prefix="/characters", tags=["identity-evolution"])
api_router.include_router(messages.router, prefix="/messages", tags=["messages"])
api_router.include_router(images.router, prefix="/images", tags=["images"])
api_router.include_router(grammar.router, prefix="/grammar", tags=["grammar"])
api_router.include_router(storylab.router, prefix="/storylab", tags=["storylab"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(blocks.router, prefix="/blocks", tags=["blocks"])
api_router.include_router(admin_diagnostics.router, prefix="/admin", tags=["admin-diagnostics"])
api_router.include_router(story_spaces.router, prefix="/story-spaces", tags=["story-spaces"])
api_router.include_router(published_router, prefix="/published-stories", tags=["published-stories"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(style_shops.router, tags=["style-shops"])
api_router.include_router(body_canon.router, prefix="/characters", tags=["body-canon"])
api_router.include_router(body_identity.router, prefix="/characters", tags=["body-identity"])
api_router.include_router(canon_api.router, prefix="/characters", tags=["identity-canon"])
api_router.include_router(character_home.router, prefix="/characters", tags=["character-home"])
api_router.include_router(rp_stories.router, prefix="/rp-stories", tags=["rp-stories"])
api_router.include_router(adult_studio.router, prefix="/adult-studio", tags=["adult-studio"])
api_router.include_router(adult_studio_admin.router, prefix="/admin/adult-studio", tags=["adult-studio-admin"])
api_router.include_router(editor_studio.router, prefix="/editor", tags=["editor-studio"])
api_router.include_router(composition.router, prefix="/composition", tags=["composition"])
app.include_router(api_router)


# Serve stub/generated images from backend/static
_static_dir = Path(__file__).resolve().parent.parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
(_static_dir / "generated").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    resp: dict = {"status": "ok", "service": "ficshon-backend"}
    # TEMP DIAG (remove after prod DB is confirmed): unauthenticated database
    # identity + aggregate counts, so the deployment's database can be identified
    # without login. Exposes only redacted host/db name and row counts — no
    # credentials, no PII. Wrapped so /health never fails (start-prod.sh readiness
    # depends on it): any DB error degrades to an error tag, status stays "ok".
    diag: dict = {"db": _db_identity()}
    try:
        from app.core.database import SessionLocal
        from sqlalchemy import text
        _db = SessionLocal()
        try:
            diag["users"] = _db.execute(text("SELECT count(*) FROM users")).scalar()
            diag["characters"] = _db.execute(text("SELECT count(*) FROM characters")).scalar()
        finally:
            _db.close()
    except Exception as e:  # pragma: no cover - diagnostic only
        diag["counts_error"] = type(e).__name__
    resp["_diag"] = diag
    return resp


@app.get("/")
def root():
    """Root endpoint — SPA index in production, API info otherwise."""
    if _SERVE_SPA:
        return FileResponse(_FRONTEND_DIST / "index.html")
    resp: dict = {"service": "Ficshon API", "version": settings.APP_VERSION}
    if settings.DEBUG:
        resp["docs"] = "/docs"
    return resp


# --- Production SPA serving (Sprint 34) -------------------------------------
# In production (start-prod.sh sets SERVE_FRONTEND_DIST=true) uvicorn serves
# the compiled frontend from frontend/dist directly, replacing the Vite dev
# server that previously fronted the app in deployments. Vite dev mode keeps
# an HMR WebSocket open to the browser; when the connection drops (as it does
# periodically behind the deployment proxy) the Vite client force-reloads the
# page — the observed five-minute production reload. Serving static compiled
# assets removes that WebSocket entirely.
#
# Development is unaffected: the env var is unset, so this whole block is
# inert and start-dev.sh keeps using Vite exactly as before.
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
_SERVE_SPA = (
    os.environ.get("SERVE_FRONTEND_DIST", "").lower() == "true"
    and (_FRONTEND_DIST / "index.html").is_file()
)
if os.environ.get("SERVE_FRONTEND_DIST", "").lower() == "true" and not _SERVE_SPA:
    # Fail loudly at import so a deployment without a built frontend surfaces
    # immediately instead of serving JSON at every page URL.
    raise RuntimeError(
        f"SERVE_FRONTEND_DIST=true but {_FRONTEND_DIST / 'index.html'} does not "
        "exist — run 'npm run build' in frontend/ (deployment build step)."
    )

if _SERVE_SPA:
    # Compiled hashed assets (JS/CSS) live under dist/assets.
    app.mount(
        "/assets",
        StaticFiles(directory=str(_FRONTEND_DIST / "assets")),
        name="spa-assets",
    )

    # The public Character Home is the one SPA route that is pasted into other
    # apps, so it is the one route whose HTML must carry per-character metadata:
    # link-preview crawlers read <head> and never execute the bundle. Registered
    # BEFORE the catch-all below, which would otherwise answer /c/{id} with the
    # static index and its one-title-for-every-route head.
    #
    # Only the head differs. An unpublished or nonexistent character gets the
    # catch-all's exact bytes, so the two stay indistinguishable.
    from app.api.routes.character_home_shell import (
        create_character_home_shell_router,
    )

    app.include_router(create_character_home_shell_router(_FRONTEND_DIST))

    # Registered last, so every real API route, /static and /assets mount, and
    # /health match first. Only unmatched GETs land here.
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """Serve dist files by exact path, else the SPA index (client routing).

        Unmatched paths under the API namespaces keep returning JSON 404 —
        the SPA index must never mask a missing API endpoint.
        """
        first_segment = full_path.split("/", 1)[0]
        if first_segment in ("api", "static", "assets"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (_FRONTEND_DIST / full_path).resolve()
        if candidate.is_relative_to(_FRONTEND_DIST) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")
