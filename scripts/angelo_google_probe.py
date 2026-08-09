#!/usr/bin/env python
"""Angelo dev-vs-production isolation probe for the Google (Gemini) image call.

Angelo's canon generates successfully from the dev workspace and fails from the
Replit deployment with blockReason=OTHER / IMAGE_RECITATION, using canon cards
that have been manually confirmed identical. This script fingerprints every
input the two runtimes could differ on, so the differing variable can be named
from evidence instead of inferred.

It is READ-ONLY: no database write, no canon change, no production data touched.

Usage
-----
    # Report only — no network call.
    python scripts/angelo_google_probe.py --character-id 47

    # Report AND make one real Gemini call with the credential in the
    # environment, so a credential can be tested without deploying anything:
    python scripts/angelo_google_probe.py --character-id 47 --call

    # Test a DIFFERENT credential (e.g. the production key) from dev, without
    # persisting it. Set it for this one command only; it is never written to
    # disk and only its fingerprint is printed:
    GOOGLE_AI_API_KEY_PROBE=... python scripts/angelo_google_probe.py --call

The credential is never printed, logged or stored. Only a one-way sha256[:12]
fingerprint is emitted — equal fingerprints mean equal keys, and the key cannot
be recovered from one.

Run the same command against dev and (via an equivalent shell on the deployment,
or the /api/admin/diagnostics `google` block) against production, then diff the
output. The first line that differs is the differentiating variable.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.storage import load_image_bytes, detect_image_format  # noqa: E402
from app.models.character_identity_canon import CharacterIdentityCanon  # noqa: E402
from app.services.canon_compiler import compile_canon_prompt  # noqa: E402
from app.services.image_providers.google_provider import (  # noqa: E402
    google_effective_config,
)
from app.services.scene_router import route_canon_refs, slot_names_for_urls  # noqa: E402

# Fixed probe scene. Deliberately neutral and fully clothed so that any refusal
# cannot be attributed to the scene text, and identical on both sides so the
# compiled-prompt hash is comparable.
PROBE_SCENE = "Standing in a hotel lobby, wearing a dark suit, natural light."


def _sha8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]


def _credential() -> tuple[str, str]:
    """Return (key, source-label) without ever exposing the value."""
    override = os.getenv("GOOGLE_AI_API_KEY_PROBE")
    if override:
        return override, "GOOGLE_AI_API_KEY_PROBE"
    return (os.getenv("GOOGLE_AI_API_KEY") or settings.GOOGLE_AI_API_KEY or ""), "GOOGLE_AI_API_KEY"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--character-id", type=int, default=47)
    ap.add_argument("--call", action="store_true", help="make one real Gemini request")
    args = ap.parse_args()

    key, key_source = _credential()
    cfg = google_effective_config()
    cfg["credential_source"] = key_source
    if key_source == "GOOGLE_AI_API_KEY_PROBE":
        cfg["credential_fingerprint"] = hashlib.sha256(key.encode()).hexdigest()[:12]
        cfg["credential_present"] = bool(key)
        cfg["credential_length"] = len(key)

    print("── effective google config ──")
    for k, v in cfg.items():
        print(f"  {k}: {v}")

    db = SessionLocal()
    try:
        canon = (
            db.query(CharacterIdentityCanon)
            .filter(CharacterIdentityCanon.character_id == args.character_id)
            .first()
        )
        if canon is None:
            print(f"\nNo canon row for character_id={args.character_id}", file=sys.stderr)
            return 2

        compiled = compile_canon_prompt(canon, PROBE_SCENE, include_accessories=True)
        urls, meta = route_canon_refs(PROBE_SCENE, canon)
        slots = list(meta.route_slots) or slot_names_for_urls(canon, urls)
        requested = urls[:6]

        print("\n── compiled prompt ──")
        print(f"  probe_scene_sha: {_sha8(PROBE_SCENE.encode())}")
        print(f"  prompt_len: {len(compiled)}")
        print(f"  prompt_sha: {_sha8(compiled.encode())}")
        print(f"  camera={meta.camera} routed={meta.routed} exposure={meta.exposure}")

        print("\n── reference set (order = payload part order) ──")
        ref_bytes: list[bytes] = []
        for i, url in enumerate(requested):
            slot = slots[i] if i < len(slots) else "unknown"
            url_h = hashlib.sha256(url.split("?", 1)[0].encode()).hexdigest()[:8]
            try:
                raw = load_image_bytes(url)
            except Exception as exc:  # noqa: BLE001
                print(f"  {i} slot={slot} h={url_h} LOAD_FAILED {type(exc).__name__}")
                continue
            ref_bytes.append(raw)
            _, mime = detect_image_format(raw)
            print(
                f"  {i} slot={slot} h={url_h} b={_sha8(raw)} "
                f"bytes={len(raw)} mime={mime}"
            )

        # Payload fingerprint: everything about the request except the image
        # bytes and prompt text themselves, plus their hashes. Two runtimes with
        # the same payload_sha sent structurally identical requests.
        payload_shape = {
            "model": cfg["model"],
            "api_version": cfg["api_version"],
            "parts": [
                {"inlineData": {"mimeType": detect_image_format(b)[1], "sha": _sha8(b)}}
                for b in ref_bytes
            ]
            + [{"text_sha": _sha8(compiled.encode()), "text_len": len(compiled)}],
            "generationConfig": cfg["generation_config"],
            "safetySettings": cfg["safety_settings"],
            "systemInstruction": cfg["system_instruction"],
        }
        payload_sha = _sha8(json.dumps(payload_shape, sort_keys=True).encode())
        print(f"\n  payload_sha: {payload_sha}   (compare this across runtimes)")

        if not args.call:
            print("\n(no request sent — pass --call to hit Gemini)")
            return 0

        if not key:
            print("\nNo credential available; cannot call.", file=sys.stderr)
            return 2
        if not ref_bytes:
            print("\nNo references loaded; refusing to send a ref-less call.", file=sys.stderr)
            return 2

        # Exactly the payload GoogleImageProvider.generate_with_multi_reference
        # builds: inlineData parts first, text last, no generationConfig and no
        # safetySettings.
        parts: list[dict] = []
        for raw in ref_bytes:
            _, mime = detect_image_format(raw)
            parts.append(
                {"inlineData": {"mimeType": mime, "data": base64.b64encode(raw).decode("ascii")}}
            )
        parts.append({"text": compiled})
        body_out = json.dumps({"contents": [{"parts": parts}]}).encode()

        url = (
            f"https://{cfg['api_host']}/{cfg['api_version']}/models/"
            f"{cfg['model']}:generateContent?key={key}"
        )
        req = urllib.request.Request(
            url, data=body_out, headers={"Content-Type": "application/json"}, method="POST"
        )
        print(
            f"\n── calling gemini (cred_fp={cfg['credential_fingerprint']}, "
            f"model={cfg['model']}, refs={len(ref_bytes)}) ──"
        )
        try:
            with urllib.request.urlopen(req, timeout=settings.GOOGLE_IMAGE_TIMEOUT_S) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            print(f"  HTTP {exc.code}")
            # Error bodies carry the project/quota reason and no credential.
            print(f"  body: {exc.read()[:400]!r}")
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"  transport failure: {type(exc).__name__}: {exc}")
            return 1

        feedback = body.get("promptFeedback") or {}
        cands = body.get("candidates") or []
        finish = cands[0].get("finishReason") if cands else None
        got_image = any(
            p.get("inlineData")
            for c in cands
            for p in (c.get("content") or {}).get("parts", [])
        )
        print(f"  blockReason: {feedback.get('blockReason')}")
        print(f"  safetyRatings: {feedback.get('safetyRatings') or []}")
        print(f"  finishReason: {finish}")
        print(f"  image_returned: {got_image}")
        if not got_image and not feedback.get("blockReason"):
            print(f"  raw(300): {json.dumps(body)[:300]}")
        return 0 if got_image else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
