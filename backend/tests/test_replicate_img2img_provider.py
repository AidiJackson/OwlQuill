"""Unit tests for the experimental Replicate img2img provider (Sprint E9/E9.2).

Fully offline: a fake ``requests.Session``-shaped transport records the request
sequence and returns canned Replicate responses. No live API call is made.

Flow under test (non-pinned model_ref): upload source → GET model (resolve latest
version) → POST /v1/predictions → poll → download. A pinned ``owner/name:version``
skips the GET. 429 on prediction creation is retried exactly once.
"""
from __future__ import annotations

import pytest

from app.services.providers.replicate_provider import (
    ReplicateImg2ImgError,
    ReplicateImg2ImgProvider,
)


class _Resp:
    def __init__(self, status_code=200, json_body=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_body or {}
        self.content = content
        self.text = ""
        self.headers = headers or {}

    def json(self):
        return self._json


class _FakeSession:
    """Records (method, url, kwargs) calls and replays a scripted list of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._responses.pop(0)


def _model_info(version="ver123"):
    return _Resp(json_body={"latest_version": {"id": version}})


def _provider(session, **kw):
    return ReplicateImg2ImgProvider(
        api_token="tok",
        model_ref="lucataco/realvisxl-v2.0",
        fallback_model_ref="stability-ai/sdxl",
        session=session,
        poll_interval=0,
        **kw,
    )


def test_requires_token():
    with pytest.raises(ValueError):
        ReplicateImg2ImgProvider(api_token="", model_ref="a/b")


def test_requires_model_ref():
    with pytest.raises(ValueError):
        ReplicateImg2ImgProvider(api_token="tok", model_ref="")


def test_img2img_happy_path_resolves_version_creates_polls_downloads():
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),     # 1 upload
        _model_info("ver123"),                                            # 2 resolve version
        _Resp(json_body={"status": "processing", "urls": {"get": "https://pred/1"}}),  # 3 create
        _Resp(json_body={"status": "succeeded", "output": ["https://out/result.png"]}),  # 4 poll
        _Resp(content=b"x" * 2048),                                       # 5 download
    ])
    p = _provider(session)
    png, model_used = p.img2img(source_image_bytes=b"src", prompt="a beach scene")

    assert png == b"x" * 2048
    assert model_used == "lucataco/realvisxl-v2.0"

    methods_urls = [(m, u) for (m, u, _k) in session.calls]
    assert methods_urls[0] == ("POST", "https://api.replicate.com/v1/files")
    assert methods_urls[1] == ("GET", "https://api.replicate.com/v1/models/lucataco/realvisxl-v2.0")
    assert methods_urls[2] == ("POST", "https://api.replicate.com/v1/predictions")
    assert methods_urls[3] == ("GET", "https://pred/1")
    assert methods_urls[4] == ("GET", "https://out/result.png")

    create_body = session.calls[2][2]["json"]
    assert create_body["version"] == "ver123"
    payload = create_body["input"]
    assert payload["image"] == "https://files/src.png"
    assert payload["prompt"] == "a beach scene"
    # Non-asiryan model → prompt_strength, and NOT strength.
    assert payload["prompt_strength"] == 0.65  # default unless overridden
    assert "strength" not in payload


def test_asiryan_uses_strength_field_not_prompt_strength():
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),
        _model_info("verA"),
        _Resp(json_body={"status": "succeeded", "output": ["https://out/r.png"]}),
        _Resp(content=b"a" * 2048),
    ])
    p = ReplicateImg2ImgProvider(
        api_token="tok", model_ref="asiryan/realistic-vision-v6.0-b1",
        strength=0.58, session=session, poll_interval=0,
    )
    p.img2img(source_image_bytes=b"src", prompt="scene")
    payload = session.calls[2][2]["json"]["input"]
    assert payload["strength"] == 0.58
    assert "prompt_strength" not in payload


def test_strength_override():
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),
        _model_info(),
        _Resp(json_body={"status": "succeeded", "output": "https://out/r.png"}),
        _Resp(content=b"y" * 2048),
    ])
    p = _provider(session)
    p.img2img(source_image_bytes=b"src", prompt="scene", strength=0.4)
    payload = session.calls[2][2]["json"]["input"]
    assert payload["prompt_strength"] == 0.4


def test_pinned_version_skips_model_lookup():
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),
        _Resp(json_body={"status": "succeeded", "output": ["https://out/r.png"]}),
        _Resp(content=b"z" * 2048),
    ])
    p = ReplicateImg2ImgProvider(
        api_token="tok", model_ref="owner/name:abc123", session=session, poll_interval=0,
    )
    p.img2img(source_image_bytes=b"src", prompt="scene")
    # No GET model lookup; create posts straight to /v1/predictions with the pinned version.
    assert session.calls[1][0] == "POST"
    assert session.calls[1][1] == "https://api.replicate.com/v1/predictions"
    assert session.calls[1][2]["json"]["version"] == "abc123"


def test_missing_latest_version_raises():
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),
        _Resp(json_body={"latest_version": None}),  # no version
        # fallback also has no version
        _Resp(json_body={"latest_version": None}),
    ])
    p = _provider(session)
    with pytest.raises(ReplicateImg2ImgError):
        p.img2img(source_image_bytes=b"src", prompt="scene")


def test_falls_back_to_second_model_on_primary_failure():
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),     # upload
        _model_info("verP"),                                             # primary version
        _Resp(json_body={"status": "failed", "error": "boom"}),          # primary create -> failed run
        _model_info("verF"),                                             # fallback version
        _Resp(json_body={"status": "succeeded", "output": ["https://out/r.png"]}),  # fallback create
        _Resp(content=b"q" * 2048),                                      # download
    ])
    p = _provider(session)
    png, model_used = p.img2img(source_image_bytes=b"src", prompt="scene")
    assert model_used == "stability-ai/sdxl"
    assert len(png) == 2048


def test_raises_when_all_models_fail():
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),
        _model_info("verP"),
        _Resp(json_body={"status": "failed", "error": "boom1"}),
        _model_info("verF"),
        _Resp(json_body={"status": "failed", "error": "boom2"}),
    ])
    p = _provider(session)
    with pytest.raises(ReplicateImg2ImgError):
        p.img2img(source_image_bytes=b"src", prompt="scene")


def test_429_retries_once_honoring_retry_after(monkeypatch):
    slept = []
    monkeypatch.setattr(
        "app.services.providers.replicate_provider.time.sleep", lambda s: slept.append(s)
    )
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),     # upload
        _model_info(),                                                   # resolve version
        _Resp(status_code=429, headers={"Retry-After": "3"}),            # create -> 429
        _Resp(json_body={"status": "processing", "urls": {"get": "https://pred/1"}}),  # retry create
        _Resp(json_body={"status": "succeeded", "output": ["https://out/r.png"]}),     # poll
        _Resp(content=b"w" * 2048),                                      # download
    ])
    p = _provider(session)
    png, model_used = p.img2img(source_image_bytes=b"src", prompt="scene")
    assert len(png) == 2048
    assert model_used == "lucataco/realvisxl-v2.0"
    # slept retry_after (3) + 1 = 4 on the throttle (poll_interval is 0).
    assert 4 in slept
    # two POSTs to the create endpoint (original + one retry).
    create_posts = [c for c in session.calls if c[0] == "POST" and c[1].endswith("/predictions")]
    assert len(create_posts) == 2


def test_429_retried_only_once_then_fails(monkeypatch):
    monkeypatch.setattr(
        "app.services.providers.replicate_provider.time.sleep", lambda s: None
    )
    # Primary 429 twice (original + retry) → primary fails; no fallback configured.
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),
        _model_info(),
        _Resp(status_code=429, headers={"Retry-After": "1"}),
        _Resp(status_code=429, headers={"Retry-After": "1"}),
    ])
    p = ReplicateImg2ImgProvider(
        api_token="tok", model_ref="lucataco/realvisxl-v2.0", session=session, poll_interval=0,
    )
    with pytest.raises(ReplicateImg2ImgError):
        p.img2img(source_image_bytes=b"src", prompt="scene")


def test_empty_prompt_rejected():
    p = _provider(_FakeSession([]))
    with pytest.raises(ReplicateImg2ImgError):
        p.img2img(source_image_bytes=b"src", prompt="   ")
