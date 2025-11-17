"""OwlQuill FastAPI application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import auth, users, characters, realms, posts, comments, reactions, ai, scenes, blocks, reports

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
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
app.include_router(blocks.router, prefix="/blocks", tags=["blocks"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "service": "owlquill-backend"}


@app.get("/")
def root() -> dict:
    """Root endpoint."""
    return {
        "service": "OwlQuill API",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }
