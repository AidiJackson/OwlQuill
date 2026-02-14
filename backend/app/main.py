"""Ficshon FastAPI application."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.admin_seed import ensure_admin_user, ensure_commons_realm
from app.core.starter_seed import ensure_starter_realms_and_posts
from app.api.routes import auth, users, characters, realms, posts, comments, reactions, ai, scenes, character_visual, messages, images


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    if settings.SMTP_HOST:
        logger.info("Email: SMTP enabled (host=%s)", settings.SMTP_HOST)
    else:
        logger.info("Email: DEV console mode")
    ensure_admin_user()
    ensure_commons_realm()
    try:
        ensure_starter_realms_and_posts()
    except Exception:
        pass  # logged inside; never crash startup
    yield
    # Shutdown (nothing to do)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan
)

# Add rate limiter state and exception handler
app.state.limiter = auth.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
app.include_router(messages.router, prefix="/messages", tags=["messages"])
app.include_router(images.router, prefix="/images", tags=["images"])

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
api_router.include_router(messages.router, prefix="/messages", tags=["messages"])
api_router.include_router(images.router, prefix="/images", tags=["images"])
app.include_router(api_router)


# Serve stub/generated images from backend/static
_static_dir = Path(__file__).resolve().parent.parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
(_static_dir / "generated").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "service": "ficshon-backend"}


@app.get("/")
def root() -> dict:
    """Root endpoint."""
    return {
        "service": "Ficshon API",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }
