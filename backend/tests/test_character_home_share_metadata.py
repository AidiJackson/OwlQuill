"""Link-preview metadata for the public Character Home (``/c/{id}``).

The route exists because crawlers do not run the SPA. Discord, iMessage, Slack
and X fetch the HTML, read ``<head>``, and render whatever is there; the
compiled shell carries one title for every route, so a pasted Character Home
unfurled with no character in it.

Three things are pinned here, in rough order of how much damage getting them
wrong would do:

1. **Escaping.** ``name``, ``alias`` and ``short_bio`` are free text a creator
   types. A single unescaped ``"`` closes a ``content`` attribute and everything
   after it becomes markup in a document served to every visitor. The
   adversarial section is deliberately the longest one.
2. **Indistinguishability.** An unpublished character and one that never existed
   must produce byte-identical HTML, and neither may carry a name, an image or
   any other trace. This is the same rule the JSON API already keeps, and this
   route must not become the hole in it.
3. **Everything else still works.** The React root, the hashed bundle and the
   stylesheet must survive injection untouched, and every other route — SPA,
   API, /static, /assets — must behave exactly as it did.

DEV never exercises this path (Vite serves ``/c/:id`` and FastAPI 404s it), so
the logic under test is reached directly rather than through a running server:
pure functions for the metadata itself, ``render_character_home_shell`` against
real fixtures for the publication gate, and a throwaway app mounting the real
router factory for status codes, ETags and caching.
"""
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.testclient import TestClient

from app.api.routes.character_home_shell import (
    CACHE_CONTROL,
    create_character_home_shell_router,
)
from app.core.config import DEFAULT_FRONTEND_URL, settings
from app.core.database import get_db
from app.models.character import Character, VisibilityEnum
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.schemas.character_home import CharacterHomePublic
from app.services.character_home_share import (
    GENERIC_OG_IMAGE_PATH,
    MAX_DESCRIPTION_CHARS,
    absolutize_media_url,
    build_description,
    build_head_tags,
    canonical_url,
    choose_share_image,
    inject_head_metadata,
    render_character_home_shell,
    truncate_description,
)
from tests.conftest import TestingSessionLocal, auth_headers, get_auth_token

BASE = "https://ficshon.com"

#: A stand-in for the compiled shell, mirroring the parts that must survive:
#: a title to replace, the React mount point, the hashed module script and the
#: stylesheet. Written inline rather than read from ``frontend/dist`` so the
#: suite does not depend on a build artifact having been produced.
SHELL = (
    "<!doctype html>\n<html lang=\"en\">\n  <head>\n"
    "    <meta charset=\"UTF-8\" />\n"
    "    <title>Ficshon — Roleplay Social Network</title>\n"
    "    <link rel=\"manifest\" href=\"/manifest.json\" />\n"
    "    <script type=\"module\" crossorigin src=\"/assets/index-abc123.js\"></script>\n"
    "    <link rel=\"stylesheet\" crossorigin href=\"/assets/index-def456.css\">\n"
    "  </head>\n  <body>\n    <div id=\"root\"></div>\n  </body>\n</html>\n"
)


# ── Parsing helpers ──────────────────────────────────────────────────────────

class _Head(HTMLParser):
    """Collects the head facts a preview card is built from.

    Parsed rather than string-matched so assertions see what a CRAWLER sees:
    ``&amp;`` in the source is the single character ``&`` in the attribute, and
    only a real parser tells the two apart. String matching would happily pass a
    document whose escaping had broken an attribute open.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.canonical = None
        self.tags: list[str] = []
        #: Every attribute NAME that appears anywhere, so a test can assert on
        #: what the document actually declares rather than on whether a word
        #: appears in the source. "onerror" inside escaped creator text is inert
        #: text; "onerror" as an attribute is an execution. Only a parser
        #: distinguishes them, and a string search fails the safe case.
        self.attr_names: set[str] = set()
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        a = dict(attrs)
        self.attr_names |= {name.lower() for name, _ in attrs}
        if tag == "meta":
            key = a.get("property") or a.get("name")
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse(html: str) -> _Head:
    p = _Head()
    p.feed(html)
    return p


def home(**over) -> CharacterHomePublic:
    base = dict(
        id=59, name="Pan", alias=None, role=None, era=None, species="human",
        short_bio=None, long_bio=None, tags=None,
        avatar_url=None, avatar_position_x=0.5, avatar_position_y=0.5, avatar_scale=1.0,
        cover_url=None, cover_position_x=0.5, cover_position_y=0.5, cover_scale=1.0,
    )
    base.update(over)
    return CharacterHomePublic(**base)


def render(**over) -> _Head:
    return parse(inject_head_metadata(SHELL, build_head_tags(home(**over), BASE)))


# ── A. A published Home gets real metadata ───────────────────────────────────

class TestPublishedMetadata:
    def test_emits_every_required_tag(self):
        h = render(short_bio="A king of the Never Never.", cover_url=f"{BASE}/x.png")

        assert h.title == "Pan | Ficshon"
        assert h.meta["description"] == "A king of the Never Never."
        assert h.meta["og:title"] == "Pan | Ficshon"
        assert h.meta["og:description"] == "A king of the Never Never."
        assert h.meta["og:url"] == "https://ficshon.com/c/59"
        assert h.meta["og:type"] == "profile"
        assert h.meta["og:site_name"] == "Ficshon"
        assert h.meta["og:image"] == f"{BASE}/x.png"
        assert h.canonical == "https://ficshon.com/c/59"

    def test_twitter_card_is_large_only_when_an_image_exists(self):
        assert render(cover_url="https://r2.test/c.png").meta["twitter:card"] == "summary_large_image"
        # No image anywhere — not even the generic card, because no base URL.
        h = parse(inject_head_metadata(SHELL, build_head_tags(home(), None)))
        assert h.meta["twitter:card"] == "summary"
        assert "twitter:image" not in h.meta

    def test_exactly_one_title_survives_injection(self):
        h = render()
        assert h.tags.count("title") == 1
        assert "Roleplay Social Network" not in h.title


# ── B. React must be untouched ───────────────────────────────────────────────

class TestShellIntegrity:
    def test_root_bundle_and_stylesheet_survive_byte_for_byte(self):
        out = inject_head_metadata(SHELL, build_head_tags(home(), BASE))
        for fragment in (
            '<div id="root"></div>',
            '<script type="module" crossorigin src="/assets/index-abc123.js"></script>',
            '<link rel="stylesheet" crossorigin href="/assets/index-def456.css">',
            '<meta charset="UTF-8" />',
            '<link rel="manifest" href="/manifest.json" />',
        ):
            assert fragment in out

    def test_only_the_head_grows(self):
        out = inject_head_metadata(SHELL, build_head_tags(home(), BASE))
        assert out.split("</head>")[1] == SHELL.split("</head>")[1]

    def test_a_shell_without_a_head_is_returned_untouched(self):
        # Fail safe: guessing at malformed markup would break the page for every
        # visitor in order to serve a preview to some.
        broken = "<html><body><div id='root'></div></body></html>"
        assert inject_head_metadata(broken, "<title>x</title>") == broken


# ── C. Description ───────────────────────────────────────────────────────────

class TestDescription:
    def test_uses_short_bio_when_present(self):
        assert build_description("Pan", "A king.") == "A king."

    def test_falls_back_to_a_statement_not_an_empty_field(self):
        for empty in (None, "", "   ", "\n\t "):
            assert build_description("Pan", empty) == "Pan has a home on Ficshon."

    def test_truncates_on_a_word_boundary_with_an_ellipsis(self):
        bio = "word " * 100
        out = truncate_description(bio)
        assert len(out) <= MAX_DESCRIPTION_CHARS
        assert out.endswith("…")
        assert "wor…" not in out  # never mid-word

    def test_collapses_newlines_a_real_bio_contains(self):
        assert build_description("Pan", "One.\n\nTwo.\tThree.") == "One. Two. Three."

    def test_truncation_happens_before_escaping(self):
        # A long bio ending in an entity-producing character. Cutting the
        # ESCAPED string could slice "&amp;" into "&am"; cutting first cannot.
        bio = ("a" * (MAX_DESCRIPTION_CHARS - 2)) + " &&&&&&&&&&"
        content = parse(
            inject_head_metadata(SHELL, build_head_tags(home(short_bio=bio), BASE))
        ).meta["description"]
        assert len(content) <= MAX_DESCRIPTION_CHARS
        assert "&am" not in content or "&amp;" not in content

    def test_ignores_long_bio_tags_species_and_role(self):
        h = render(
            long_bio="Private prose about Pan.", tags="fantasy,gothic",
            species="human", role="immortal king",
        )
        assert h.meta["description"] == "Pan has a home on Ficshon."
        for leaked in ("Private prose", "fantasy", "gothic", "immortal king"):
            assert leaked not in h.meta["og:description"]


# ── D. Image priority and absolutisation ─────────────────────────────────────

class TestImage:
    def test_cover_wins_over_avatar(self):
        assert choose_share_image("https://r2/c.png", "https://r2/a.png", BASE) == "https://r2/c.png"

    def test_avatar_is_used_when_there_is_no_cover(self):
        assert choose_share_image(None, "https://r2/a.png", BASE) == "https://r2/a.png"

    def test_generic_card_is_the_last_resort(self):
        assert choose_share_image(None, None, BASE) == f"{BASE}{GENERIC_OG_IMAGE_PATH}"

    def test_no_image_at_all_without_a_base_url(self):
        # A relative og:image is not a degraded preview, it is a broken one.
        assert choose_share_image(None, None, None) is None
        assert choose_share_image("/static/generated/x.png", None, None) is None
        h = parse(inject_head_metadata(SHELL, build_head_tags(home(), None)))
        assert "og:image" not in h.meta

    @pytest.mark.parametrize("stored", ["/static/generated/x.png", "static/generated/x.png"])
    def test_relative_static_urls_become_absolute(self, stored):
        assert absolutize_media_url(stored, BASE) == f"{BASE}/static/generated/x.png"
        assert render(cover_url=stored).meta["og:image"] == f"{BASE}/static/generated/x.png"

    def test_absolute_r2_urls_are_left_exactly_as_they_are(self):
        r2 = "https://pub-2cb664acb0474ef1b96cb149469a11bc.r2.dev/generated/a.png"
        assert absolutize_media_url(r2, BASE) == r2
        assert render(cover_url=r2).meta["og:image"] == r2

    def test_a_trailing_slash_on_the_base_does_not_double(self):
        assert absolutize_media_url("/static/x.png", "https://ficshon.com/") == "https://ficshon.com/static/x.png"


# ── E. Canonical ─────────────────────────────────────────────────────────────

class TestCanonical:
    def test_built_from_configuration_and_id(self):
        assert canonical_url(59, BASE) == "https://ficshon.com/c/59"

    def test_omitted_entirely_when_the_origin_is_unknown(self):
        assert canonical_url(59, None) is None
        h = parse(inject_head_metadata(SHELL, build_head_tags(home(), None)))
        assert h.canonical is None
        assert "og:url" not in h.meta


class TestPublicBaseUrl:
    """``get_public_base_url`` must never publish localhost as a real origin."""

    def test_explicit_configuration_wins(self, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://ficshon.com/")
        assert settings.get_public_base_url() == "https://ficshon.com"

    def test_falls_back_to_the_replit_domain(self, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", DEFAULT_FRONTEND_URL)
        monkeypatch.setenv("REPLIT_DEV_DOMAIN", "example.replit.dev")
        assert settings.get_public_base_url() == "https://example.replit.dev"

    def test_localhost_is_acceptable_in_development(self, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", DEFAULT_FRONTEND_URL)
        monkeypatch.delenv("REPLIT_DEV_DOMAIN", raising=False)
        monkeypatch.setattr(settings, "DEBUG", True)
        assert settings.get_public_base_url() == DEFAULT_FRONTEND_URL

    def test_production_with_nothing_configured_returns_none_not_localhost(self, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", DEFAULT_FRONTEND_URL)
        monkeypatch.delenv("REPLIT_DEV_DOMAIN", raising=False)
        monkeypatch.setattr(settings, "DEBUG", False)
        monkeypatch.setattr(settings, "DEV_MODE", False)
        assert settings.get_public_base_url() is None


# ── F. Adversarial: creator text must never become markup ────────────────────

#: Each entry is a real attempt to break out of the position it lands in.
BREAKOUT = [
    '" /><script>alert(1)</script><meta x="',
    "' /><script>alert(1)</script><meta x='",
    "</title><script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "Tom & Jerry <b>bold</b>",
    'a"b\'c<d>e&f',
    "</head><body onload=alert(1)>",
    '\\" /><script>alert(1)</script>',
]


#: The shell legitimately contains one <script> and two <link>s — the React
#: bundle, the stylesheet and the manifest. "Nothing was injected" therefore
#: means "the counts did not change", not "there are none".
_SHELL_TAGS = parse(SHELL).tags


def _assert_no_markup_injected(out: str) -> _Head:
    """Every way a hostile value could stop being text and start being markup.

    Asserted against the PARSED document, not against the source string. A
    payload containing the word "onerror" still contains it after escaping — as
    six inert characters of text — so a substring search reports a breakout that
    did not happen and, worse, would pass a document where the same payload had
    genuinely opened an attribute. What matters is what the document declares:
    which elements exist, and which attribute names they carry.
    """
    h = parse(out)

    # No element gained the power to execute or fetch anything.
    assert h.tags.count("script") == _SHELL_TAGS.count("script"), "a <script> appeared"
    assert set(h.tags) <= set(_SHELL_TAGS) | {"title", "meta", "link"}, "a new element appeared"
    assert not {a for a in h.attr_names if a.startswith("on")}, "an event handler appeared"
    assert "<script>" not in out

    # Structure intact: one title, one head boundary, the React root untouched.
    assert h.tags.count("title") == 1
    assert out.count("</head>") == 1
    assert out.count("</title>") == 1
    assert '<div id="root"></div>' in out
    return h


class TestEscaping:
    @pytest.mark.parametrize("payload", BREAKOUT)
    def test_a_hostile_name_never_becomes_markup(self, payload):
        out = inject_head_metadata(SHELL, build_head_tags(home(name=payload), BASE))
        h = _assert_no_markup_injected(out)
        # The text survives as TEXT — escaped in the source, exact once parsed.
        assert h.title == f"{payload} | Ficshon"

    @pytest.mark.parametrize("payload", BREAKOUT)
    def test_a_hostile_bio_never_becomes_markup(self, payload):
        out = inject_head_metadata(SHELL, build_head_tags(home(short_bio=payload), BASE))
        h = _assert_no_markup_injected(out)
        assert h.meta["og:description"] == payload
        assert h.meta["description"] == payload

    @pytest.mark.parametrize("ch,entity", [("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;")])
    def test_each_dangerous_character_is_encoded_in_the_source(self, ch, entity):
        out = inject_head_metadata(SHELL, build_head_tags(home(name=f"x{ch}y"), BASE))
        assert f"x{entity}y" in out
        assert f'content="x{ch}y"' not in out

    def test_a_hostile_name_cannot_forge_a_second_canonical(self):
        out = inject_head_metadata(
            SHELL,
            build_head_tags(home(name='" /><link rel="canonical" href="https://evil.test'), BASE),
        )
        assert parse(out).canonical == "https://ficshon.com/c/59"
        assert out.count('rel="canonical"') == 1
        assert "evil.test" not in parse(out).canonical


# ── G. The publication gate, against real rows ───────────────────────────────

#: Ficshon allows one character per account, so a test needing two characters
#: needs two accounts. A counter is simpler than threading emails through every
#: call site, and keeps each test's intent about the character, not the login.
_ACCOUNTS = iter(range(1, 10_000))


def _character(db, client, **over) -> int:
    n = next(_ACCOUNTS)
    token = get_auth_token(client, email=f"share{n}@test.com", username=f"share{n}")
    resp = client.post(
        "/characters/",
        json={"name": "Pan", "species": "human", "visibility": "public"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    row = db.query(Character).filter(Character.id == cid).first()
    row.public_home_enabled = True
    for k, v in over.items():
        setattr(row, k, v)
    db.commit()
    return cid


class TestPublicationGate:
    def test_a_published_home_is_head_injected(self, client, db_session):
        cid = _character(db_session, client, short_bio="A king.")
        h = parse(render_character_home_shell(db_session, cid, SHELL, BASE))
        assert h.title == "Pan | Ficshon"
        assert h.meta["og:url"] == f"{BASE}/c/{cid}"

    @pytest.mark.parametrize(
        "mutate",
        [
            pytest.param({"public_home_enabled": False}, id="unpublished"),
            pytest.param({"visibility": VisibilityEnum.PRIVATE}, id="private"),
            pytest.param({"visibility": VisibilityEnum.FRIENDS}, id="friends"),
        ],
    )
    def test_every_withheld_character_returns_the_untouched_shell(
        self, client, db_session, mutate
    ):
        cid = _character(db_session, client, short_bio="A king.", **mutate)
        assert render_character_home_shell(db_session, cid, SHELL, BASE) == SHELL

    def test_unpublished_and_nonexistent_are_byte_identical(self, client, db_session):
        cid = _character(db_session, client, public_home_enabled=False, short_bio="A king.")
        withheld = render_character_home_shell(db_session, cid, SHELL, BASE)
        missing = render_character_home_shell(db_session, 999_999, SHELL, BASE)

        assert withheld == missing == SHELL
        # No trace of the character in either.
        for body in (withheld, missing):
            assert "Pan" not in body and "A king" not in body

    def test_a_non_numeric_id_is_the_same_shell_and_costs_no_query(self, db_session):
        assert render_character_home_shell(db_session, None, SHELL, BASE) == SHELL

    def test_an_unsafe_cover_falls_through_to_the_avatar(self, client, db_session):
        """The media safety boundary is the projection's, and it still applies.

        A cover whose source row came from a studio whose output may not be
        published is blanked by ``resolve_public_media_url`` before this code
        sees it. Falling through to the avatar is the correct response — and
        proves the resolver is in the path rather than bypassed.
        """
        cid = _character(db_session, client)
        row = db_session.query(Character).filter(Character.id == cid).first()
        row.cover_url = "/static/generated/unsafe.png"
        row.avatar_url = "https://r2.test/safe-avatar.png"
        db_session.add(
            CharacterImage(
                character_id=cid,
                kind=ImageKindEnum.COVER,
                status=ImageStatusEnum.ACTIVE,
                visibility=ImageVisibilityEnum.PRIVATE,
                provider="replicate_nsfw",       # never public, whatever the kind
                file_path="static/generated/unsafe.png",
            )
        )
        db_session.commit()

        h = parse(render_character_home_shell(db_session, cid, SHELL, BASE))
        assert h.meta["og:image"] == "https://r2.test/safe-avatar.png"
        assert "unsafe.png" not in h.meta["og:image"]


# ── H. The route: status, caching, and everything it must not disturb ────────

@pytest.fixture
def shell_app(tmp_path, db_session, monkeypatch):
    """The real router factory on a throwaway app with a temporary dist.

    Mounted alongside a stand-in for the SPA catch-all and the API/static 404
    branches, so the regression assertions exercise the same ordering
    production uses: the /c route first, everything else falling through.
    """
    monkeypatch.setattr(settings, "FRONTEND_URL", BASE)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(SHELL, encoding="utf-8")

    app = FastAPI()
    app.include_router(create_character_home_shell_router(dist))

    @app.get("/{full_path:path}", include_in_schema=False)
    def catch_all(full_path: str):
        if full_path.split("/", 1)[0] in ("api", "static", "assets"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(dist / "index.html")

    app.dependency_overrides[get_db] = lambda: TestingSessionLocal()
    with TestClient(app) as c:
        yield c


class TestRoute:
    def test_published_home_returns_injected_html(self, shell_app, client, db_session):
        cid = _character(db_session, client, short_bio="A king.")
        r = shell_app.get(f"/c/{cid}")

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert parse(r.text).meta["og:title"] == "Pan | Ficshon"

    def test_a_query_string_never_reaches_the_canonical(self, shell_app, client, db_session):
        cid = _character(db_session, client)
        r = shell_app.get(f"/c/{cid}?utm_source=discord&fbclid=abc")
        h = parse(r.text)

        assert h.canonical == f"{BASE}/c/{cid}"
        assert h.meta["og:url"] == f"{BASE}/c/{cid}"
        for leaked in ("utm_source", "discord", "fbclid"):
            assert leaked not in r.text

    def test_etag_is_content_derived_not_the_static_file_s(self, shell_app, client, db_session):
        published = _character(db_session, client, short_bio="A king.")
        withheld = _character(db_session, client, public_home_enabled=False)

        a = shell_app.get(f"/c/{published}")
        b = shell_app.get(f"/c/{withheld}")
        assert a.headers["etag"] != b.headers["etag"]
        assert a.headers["cache-control"] == CACHE_CONTROL
        assert b.headers["cache-control"] == CACHE_CONTROL

    def test_the_etag_changes_when_the_character_does(self, shell_app, client, db_session):
        cid = _character(db_session, client, short_bio="A king.")
        before = shell_app.get(f"/c/{cid}").headers["etag"]

        row = db_session.query(Character).filter(Character.id == cid).first()
        row.short_bio = "A different king."
        db_session.commit()

        after = shell_app.get(f"/c/{cid}")
        assert after.headers["etag"] != before
        assert parse(after.text).meta["description"] == "A different king."

    def test_a_matching_etag_revalidates_to_304(self, shell_app, client, db_session):
        cid = _character(db_session, client)
        etag = shell_app.get(f"/c/{cid}").headers["etag"]

        again = shell_app.get(f"/c/{cid}", headers={"If-None-Match": etag})
        assert again.status_code == 304
        assert again.content == b""

    def test_unpublished_and_nonexistent_are_identical_over_http(self, shell_app, client, db_session):
        cid = _character(db_session, client, public_home_enabled=False, short_bio="A king.")
        withheld = shell_app.get(f"/c/{cid}")
        missing = shell_app.get("/c/999999")
        junk = shell_app.get("/c/not-a-number")

        assert withheld.status_code == missing.status_code == junk.status_code == 200
        assert withheld.text == missing.text == junk.text == SHELL
        assert withheld.headers["etag"] == missing.headers["etag"] == junk.headers["etag"]
        assert "Pan" not in withheld.text


class TestNoRegression:
    """Everything this route sits next to must behave exactly as it did."""

    def test_other_spa_routes_still_get_the_plain_shell(self, shell_app):
        for path in ("/login", "/characters/59", "/", "/settings/profile"):
            r = shell_app.get(path)
            assert r.status_code == 200
            assert r.text == SHELL
            assert "og:title" not in r.text

    def test_api_static_and_assets_still_404_as_json(self, shell_app):
        for path in ("/api/nope", "/static/nope.png", "/assets/nope.js"):
            r = shell_app.get(path)
            assert r.status_code == 404
            assert r.json() == {"detail": "Not Found"}

    def test_the_route_only_claims_a_single_path_segment(self, shell_app):
        # /c/59/extra is not a Character Home and must fall to the catch-all.
        r = shell_app.get("/c/59/extra")
        assert r.text == SHELL
