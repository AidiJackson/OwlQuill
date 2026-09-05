"""The HTML shell for ``/c/{id}``, with share metadata in its head.

Registered only when the compiled frontend is being served (production), and
registered BEFORE the SPA catch-all so it wins the match. In development Vite
serves ``/c/:id`` itself and never reaches FastAPI, so nothing here is exercised
there — which is why the logic it delegates to lives in
``services.character_home_share`` as plain functions, testable without a
production server, and why this module is kept to wiring alone.

Built as a FACTORY rather than a module-level router so a test can mount it on
a throwaway app with a temporary dist directory. The alternative — importing the
real app with ``SERVE_FRONTEND_DIST=true`` — would mean re-importing the app
module the whole test suite already shares.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.services.character_home_share import render_character_home_shell

logger = logging.getLogger(__name__)

#: Conservative on purpose. The body reflects a character's current name, bio
#: and imagery, so a cached copy outlives an edit, an image takedown, or the
#: founder revoking publication. ``max-age=0, must-revalidate`` keeps the ETag
#: useful — a repeat visitor still gets a 304 and no body — while guaranteeing
#: every request checks first. V1 favours correctness after a change over
#: shaving a round trip on a route that carries very little traffic.
#:
#: ``private`` keeps shared caches out of it entirely: the response is the same
#: for everyone today, but a CDN holding a character page for hours is exactly
#: how an unpublished Home stays visible after it is withdrawn.
CACHE_CONTROL = "private, max-age=0, must-revalidate"


def _parse_character_id(raw: str) -> Optional[int]:
    """The id as an int, or None when the path segment is not one.

    The route accepts ``str`` rather than declaring ``int`` deliberately: an
    ``int`` path parameter makes FastAPI answer ``/c/abc`` with a 422 JSON body,
    where today it returns the SPA shell and the page renders its own "no public
    home" state. Changing that would be a regression in a path this task is not
    meant to touch.
    """
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def create_character_home_shell_router(dist_dir: Path) -> APIRouter:
    """Router serving ``/c/{character_id}`` from *dist_dir*'s ``index.html``."""
    router = APIRouter()
    index_path = dist_dir / "index.html"

    @router.get("/c/{character_id}", include_in_schema=False)
    def character_home_shell(
        character_id: str,
        request: Request,
        db: Session = Depends(get_db),
    ) -> Response:
        """The SPA shell, head-injected for a published Home and plain otherwise.

        Read from disk per request rather than cached in memory, matching what
        ``FileResponse`` already does for every other SPA route: the file is
        under a kilobyte, and a deployment that rebuilds the frontend must not
        keep serving the previous bundle's script tag.

        The ETag is derived from the BODY that is actually returned, not from
        the file. The static file's ETag is identical for every route by
        definition, so reusing it here would tell caches that Pan's Home and a
        stranger's unpublished one are the same resource.
        """
        shell = index_path.read_text(encoding="utf-8")
        body = render_character_home_shell(
            db,
            _parse_character_id(character_id),
            shell,
            settings.get_public_base_url(),
        )

        etag = '"%s"' % hashlib.sha256(body.encode("utf-8")).hexdigest()
        headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}

        # A content ETag with nothing checking it is decoration. This is the
        # half that turns "revalidate every time" into "revalidate cheaply".
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)

        return Response(content=body, media_type="text/html; charset=utf-8", headers=headers)

    return router
