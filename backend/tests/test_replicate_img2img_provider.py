"""Unit tests for the experimental Replicate img2img provider (Sprint E9).

Fully offline: a fake ``requests.Session``-shaped transport records the request
sequence and returns canned Replicate responses. No live API call is made.
"""
from __future__ import annotations

import pytest

from app.services.providers.replicate_provider import (
    ReplicateImg2ImgError,
    ReplicateImg2ImgProvider,
)


class _Resp:
    def __init__(self, status_code=200, json_body=None, content=b""):
        self.status_code = status_code
        self._json = json_body or {}
        self.content = content
        self.text = ""

    def json(self):
        return self._json


class _FakeSession:
    """Records (method, url) calls and replays a scripted list of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._responses.pop(0)


def _provider(session, **kw):
    return ReplicateImg2ImgProvider(
        api_token="tok",
        model_ref="lucataco/realvisxl-v3-img2img",
        fallback_model_ref="RunDiffusion/Juggernaut-XL-v9",
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


def test_img2img_happy_path_uploads_creates_polls_downloads():
    session = _FakeSession([
        # 1) upload source -> file url
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),
        # 2) create prediction (model endpoint, latest version) -> processing
        _Resp(json_body={"status": "processing", "urls": {"get": "https://pred/1"}}),
        # 3) poll -> succeeded with output list
        _Resp(json_body={"status": "succeeded", "output": ["https://out/result.png"]}),
        # 4) download output bytes
        _Resp(content=b"x" * 2048),
    ])
    p = _provider(session)
    png, model_used = p.img2img(source_image_bytes=b"src", prompt="a beach scene")

    assert png == b"x" * 2048
    assert model_used == "lucataco/realvisxl-v3-img2img"

    methods_urls = [(m, u) for (m, u, _k) in session.calls]
    assert methods_urls[0] == ("POST", "https://api.replicate.com/v1/files")
    # latest-version model endpoint (no ':' in model_ref)
    assert methods_urls[1] == (
        "POST",
        "https://api.replicate.com/v1/models/lucataco/realvisxl-v3-img2img/predictions",
    )
    assert methods_urls[2] == ("GET", "https://pred/1")
    assert methods_urls[3] == ("GET", "https://out/result.png")

    # img2img input carries the uploaded url, prompt, and default strength 0.65
    create_kwargs = session.calls[1][2]
    payload = create_kwargs["json"]["input"]
    assert payload["image"] == "https://files/src.png"
    assert payload["prompt"] == "a beach scene"
    assert payload["prompt_strength"] == 0.65


def test_strength_override():
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),
        _Resp(json_body={"status": "succeeded", "output": "https://out/r.png"}),
        _Resp(content=b"y" * 2048),
    ])
    p = _provider(session)
    p.img2img(source_image_bytes=b"src", prompt="scene", strength=0.4)
    payload = session.calls[1][2]["json"]["input"]
    assert payload["prompt_strength"] == 0.4


def test_pinned_version_uses_predictions_endpoint():
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),
        _Resp(json_body={"status": "succeeded", "output": ["https://out/r.png"]}),
        _Resp(content=b"z" * 2048),
    ])
    p = ReplicateImg2ImgProvider(
        api_token="tok", model_ref="owner/name:abc123", session=session, poll_interval=0,
    )
    p.img2img(source_image_bytes=b"src", prompt="scene")
    assert session.calls[1][1] == "https://api.replicate.com/v1/predictions"
    assert session.calls[1][2]["json"]["version"] == "abc123"


def test_falls_back_to_second_model_on_primary_failure():
    session = _FakeSession([
        # upload
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),
        # primary create -> failed run
        _Resp(json_body={"status": "failed", "error": "boom"}),
        # fallback create -> succeeded
        _Resp(json_body={"status": "succeeded", "output": ["https://out/r.png"]}),
        # download
        _Resp(content=b"q" * 2048),
    ])
    p = _provider(session)
    png, model_used = p.img2img(source_image_bytes=b"src", prompt="scene")
    assert model_used == "RunDiffusion/Juggernaut-XL-v9"
    assert len(png) == 2048


def test_raises_when_all_models_fail():
    session = _FakeSession([
        _Resp(json_body={"urls": {"get": "https://files/src.png"}}),
        _Resp(json_body={"status": "failed", "error": "boom1"}),
        _Resp(json_body={"status": "failed", "error": "boom2"}),
    ])
    p = _provider(session)
    with pytest.raises(ReplicateImg2ImgError):
        p.img2img(source_image_bytes=b"src", prompt="scene")


def test_empty_prompt_rejected():
    p = _provider(_FakeSession([]))
    with pytest.raises(ReplicateImg2ImgError):
        p.img2img(source_image_bytes=b"src", prompt="   ")
