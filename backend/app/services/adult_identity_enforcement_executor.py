"""Adult Studio tattoo-enforcement EXECUTOR — v1 (Phase 3, Sprint 7).

The first executor. It consumes the DB enforcement plan (identity + active LoRA
version + per-mark routes + reference crops), generates ONE base image with the
active LoRA, dispatches each mark route to its handler to compute that route's real
conditioning artifact, composes a final preview, and emits a structured execution
report.

Honest scope of v1 — read this carefully:
  - Base generation is REAL (one image, capped).
  - Each route handler is REAL conditioning preparation:
      ip_adapter      → normalized style-reference image (the IP-Adapter input)
      controlnet_canny→ edge map of the reference crop (the ControlNet control image)
      inpaint_direct  → stub (Summer has no skin-mark route; allowed by spec)
  - The final image is a deterministic labeled PREVIEW (base + route artifacts), NOT a
    diffusion inpaint. The diffusion-quality denoise pass (IP-Adapter / ControlNet
    guidance actually painting the mark into the skin) requires the GPU backend
    (Phase 0 RunPod/ComfyUI) and is marked ``diffusion_pass="deferred"`` here.
  => Every report carries ``manual_review_required=True``.

Guards: Summer ONLY (character_id=60). Hard spend cap (default $0.15) — generation is
the only spend; if a single base generation would breach the cap, the run stops
immediately and never dispatches routes. No Canon Studio access, no UI, no public path,
no provider training. The only generation is the single base image via the injected
generator (the admin script wires the existing Replicate active-LoRA path).

This module performs NO network or storage I/O on its own: base generation, byte
fetching, and artifact persistence are all injected callables (defaults provided by the
admin script / storage helper), which keeps the executor deterministic and unit-testable
with zero spend.
"""
from __future__ import annotations

import io
import time
from typing import TYPE_CHECKING, Any, Callable

from app.services.adult_identity_enforcement_plan import (
    EXECUTOR_SUPPORTED_ROUTES,
    build_enforcement_plan,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

EXECUTOR_VERSION = "v1"
SUMMER_CHARACTER_ID = 60
DEFAULT_SPEND_CAP_USD = 0.15

# Summer routing expectations (butterfly/floral sleeve→ip_adapter, ballerina→controlnet).
SUMMER_ROUTE_EXPECTATIONS = {"sleeve": "ip_adapter", "ballerina": "controlnet_canny"}

# Per-route conditioning strengths a downstream diffusion pass would consume.
IP_ADAPTER_SCALE = 0.8
CONTROLNET_CONDITIONING_SCALE = 0.9
_ARTIFACT_MAX_EDGE = 768  # normalize reference crops to a sane working size


class CapBreach(Exception):
    """Raised when a generation would cross the hard spend cap."""


# ── Injected-I/O default implementations (overridable for tests) ───────────────


def _default_fetch_bytes(uri: str) -> bytes:
    """Fetch image bytes for a stored URI (R2 public URL or http)."""
    from app.core.storage import load_image_bytes
    try:
        return load_image_bytes(uri)
    except Exception:
        # Fallback: plain GET with a browser UA (r2.dev blocks default UAs).
        import requests
        resp = requests.get(uri, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        return resp.content


def _default_save_image(png_bytes: bytes) -> str:
    """Persist PNG bytes and return a storable URL/path (R2 or local)."""
    from app.core.storage import save_image
    return save_image(png_bytes)


# ── Executor ───────────────────────────────────────────────────────────────────


class AdultIdentityEnforcementExecutor:
    """Consume the DB enforcement plan and execute it into base + artifacts + final.

    Args:
      db: session (read-only use here).
      generate_base: ``(spend_cap: float) -> dict`` returning a single base-image
        generation: ``{status, image_url, cost_usd, prompt, predict_time_s, error}``.
        This is the ONLY spend. Injected so tests never hit the network.
      fetch_bytes / save_image: injected I/O (defaults talk to R2/storage).
      spend_cap: hard USD cap. A generation reporting cost above the cap fails the run.
    """

    def __init__(
        self,
        db: "Session",
        *,
        generate_base: Callable[[float], dict],
        fetch_bytes: Callable[[str], bytes] = _default_fetch_bytes,
        save_image: Callable[[bytes], str] = _default_save_image,
        spend_cap: float = DEFAULT_SPEND_CAP_USD,
    ) -> None:
        self.db = db
        self.generate_base = generate_base
        self.fetch_bytes = fetch_bytes
        self.save_image = save_image
        self.spend_cap = spend_cap
        self._spent = 0.0

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, character_id: int) -> dict[str, Any]:
        """Execute the enforcement plan for a character. Returns the execution report."""
        t0 = time.time()
        report = self._new_report(character_id)

        # Summer-only guard (before any work or spend).
        if character_id != SUMMER_CHARACTER_ID:
            report["blocking_reasons"].append(
                f"executor is Summer-only (expected character_id={SUMMER_CHARACTER_ID}, "
                f"got {character_id})")
            return self._finalize(report, t0)

        # 1. Consume the DB plan.
        plan = build_enforcement_plan(
            character_id, self.db, route_expectations=SUMMER_ROUTE_EXPECTATIONS)
        report["identity_id"] = plan["identity_id"]
        report["active_version_id"] = plan["active_version_id"]
        report["model_version_id"] = plan["active_version_id"]
        report["model_artifact_uri"] = plan["model_artifact_uri"]
        report["plan_status"] = plan["status"]
        if not plan["ready_for_executor"]:
            report["blocking_reasons"].extend(plan["blocking_reasons"])
            report["blocking_reasons"].insert(0, "enforcement plan not ready_for_executor")
            return self._finalize(report, t0)

        # 2. Generate exactly ONE base image (the only spend). Stop on cap breach.
        try:
            base = self._generate_base_guarded()
        except CapBreach as e:
            report["blocking_reasons"].append(str(e))
            report["base_image"] = {"status": "skipped_spend_cap"}
            return self._finalize(report, t0)
        report["base_image"] = base
        if base.get("status") != "succeeded" or not base.get("image_url"):
            report["blocking_reasons"].append(
                f"base image generation did not succeed (status={base.get('status')})")
            return self._finalize(report, t0)

        # 3. Dispatch each route from the DB plan to its handler.
        artifacts: list[dict[str, Any]] = []
        for mark in plan["marks"]:
            artifacts.append(self._dispatch(mark))
        report["routes_executed"] = artifacts

        failed_routes = [a for a in artifacts if a["status"] not in ("prepared", "stub")]
        if failed_routes:
            report["blocking_reasons"].extend(
                f"route {a['route']} for {a['canon_mark_id']} failed: {a.get('error')}"
                for a in failed_routes)

        # 4. Compose the final preview (base + route artifacts). No spend.
        try:
            report["final_image_url"] = self._compose_final(base["image_url"], artifacts)
        except Exception as e:  # compositing must never crash the run
            report["blocking_reasons"].append(f"final compose failed: {e}")

        # 5. Success = plan consumed + base generated + every route prepared/stub + final made.
        report["success"] = (
            not report["blocking_reasons"]
            and report["final_image_url"] is not None
            and bool(artifacts)
        )
        return self._finalize(report, t0)

    # ── Base generation (single image, capped) ────────────────────────────────

    def _generate_base_guarded(self) -> dict[str, Any]:
        if self._spent >= self.spend_cap:
            raise CapBreach(f"spend cap ${self.spend_cap} already reached; no generation")
        remaining = round(self.spend_cap - self._spent, 5)
        base = self.generate_base(remaining)
        cost = float(base.get("cost_usd") or 0.0)
        self._spent = round(self._spent + cost, 5)
        if self._spent > self.spend_cap:
            # Spend the cost already incurred but stop immediately — do not dispatch.
            raise CapBreach(
                f"SPEND CAP BREACH: base generation cost ${cost} pushed spend to "
                f"${self._spent} over cap ${self.spend_cap}; stopping immediately")
        return base

    # ── Route dispatch ────────────────────────────────────────────────────────

    def _dispatch(self, mark: dict[str, Any]) -> dict[str, Any]:
        route = mark.get("route")
        handlers = {
            "ip_adapter": self._handle_ip_adapter,
            "controlnet_canny": self._handle_controlnet_canny,
            "inpaint_direct": self._handle_inpaint_direct,
        }
        base_descriptor = {
            "canon_mark_id": mark.get("canon_mark_id"),
            "region": mark.get("region"),
            "side": mark.get("side"),
            "route": route,
            "reference_uri": mark.get("reference_uri"),
            "reason": mark.get("reason"),
        }
        handler = handlers.get(route)
        if handler is None:
            return {**base_descriptor, "status": "unsupported", "artifact_url": None,
                    "error": f"no handler for route '{route}' "
                             f"(supported: {sorted(EXECUTOR_SUPPORTED_ROUTES)})"}
        try:
            return handler(base_descriptor)
        except Exception as e:
            return {**base_descriptor, "status": "error", "artifact_url": None,
                    "error": f"{type(e).__name__}: {e}"}

    def _handle_ip_adapter(self, d: dict[str, Any]) -> dict[str, Any]:
        """Prepare the IP-Adapter style reference (normalized crop) for the sleeve."""
        from PIL import Image
        crop = Image.open(io.BytesIO(self.fetch_bytes(d["reference_uri"]))).convert("RGB")
        crop.thumbnail((_ARTIFACT_MAX_EDGE, _ARTIFACT_MAX_EDGE))
        url = self._save_png(crop)
        return {**d, "status": "prepared", "artifact_kind": "ip_adapter_style_reference",
                "artifact_url": url,
                "params": {"ip_adapter_scale": IP_ADAPTER_SCALE,
                           "artifact_size": list(crop.size)}}

    def _handle_controlnet_canny(self, d: dict[str, Any]) -> dict[str, Any]:
        """Prepare the ControlNet control image (edge map) for the ballerina."""
        from PIL import Image, ImageFilter
        crop = Image.open(io.BytesIO(self.fetch_bytes(d["reference_uri"]))).convert("RGB")
        crop.thumbnail((_ARTIFACT_MAX_EDGE, _ARTIFACT_MAX_EDGE))
        # PIL edge map (true cv2 Canny needs numpy/cv2; the GPU backend computes Canny
        # proper — this is the deterministic, dependency-light control artifact for v1).
        edges = crop.convert("L").filter(ImageFilter.FIND_EDGES).convert("RGB")
        url = self._save_png(edges)
        return {**d, "status": "prepared", "artifact_kind": "controlnet_edge_map",
                "artifact_url": url,
                "params": {"controlnet_conditioning_scale": CONTROLNET_CONDITIONING_SCALE,
                           "edge_op": "PIL.FIND_EDGES", "artifact_size": list(edges.size)}}

    def _handle_inpaint_direct(self, d: dict[str, Any]) -> dict[str, Any]:
        """Stub — Summer has no skin-mark (scar/birthmark/mole) route. Allowed by spec."""
        return {**d, "status": "stub", "artifact_kind": "inpaint_direct_stub",
                "artifact_url": None,
                "params": {"note": "inpaint_direct handler is a stub (unused for Summer)"}}

    # ── Final compose (labeled preview; no spend) ─────────────────────────────

    def _compose_final(self, base_url: str, artifacts: list[dict[str, Any]]) -> str:
        """Montage: base image + each route artifact, captioned. Deterministic, no spend."""
        from PIL import Image, ImageDraw
        base = Image.open(io.BytesIO(self.fetch_bytes(base_url))).convert("RGB")
        base.thumbnail((512, 768))
        renderable = [a for a in artifacts if a.get("artifact_url")]

        pad, cap_h, header_h = 16, 22, 30
        thumb_w = base.width
        panels = 1 + len(renderable)
        canvas_w = panels * thumb_w + (panels + 1) * pad
        canvas_h = header_h + base.height + cap_h + 2 * pad
        canvas = Image.new("RGB", (canvas_w, canvas_h), (18, 18, 20))
        draw = ImageDraw.Draw(canvas)
        draw.text((pad, 8),
                  "ADULT STUDIO ENFORCEMENT EXECUTOR v1 — base + route conditioning "
                  "(diffusion pass DEFERRED) — manual review required",
                  fill=(235, 235, 235))

        def place(img, idx, caption):
            x = pad + idx * (thumb_w + pad)
            y = header_h + pad
            cell = img.resize((thumb_w, base.height))
            canvas.paste(cell, (x, y))
            draw.text((x, y + base.height + 4), caption[:48], fill=(200, 200, 200))

        place(base, 0, "base (active LoRA)")
        for i, a in enumerate(renderable, start=1):
            art = Image.open(io.BytesIO(self.fetch_bytes(a["artifact_url"]))).convert("RGB")
            place(art, i, f"{a['route']} | {a.get('region') or ''}")
        return self._save_png(canvas)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _save_png(self, img) -> str:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return self.save_image(buf.getvalue())

    def _new_report(self, character_id: int) -> dict[str, Any]:
        return {
            "executor": "adult_identity_enforcement_executor",
            "version": EXECUTOR_VERSION,
            "character_id": character_id,
            "identity_id": None,
            "active_version_id": None,
            "model_version_id": None,
            "model_artifact_uri": None,
            "plan_status": None,
            "enforcement_mode": "conditioning_preview",
            "diffusion_pass": "deferred",
            "spend_cap_usd": self.spend_cap,
            "base_image": None,
            "routes_executed": [],
            "final_image_url": None,
            "success": False,
            "manual_review_required": True,  # never auto-passed in v1
            "blocking_reasons": [],
        }

    def _finalize(self, report: dict[str, Any], t0: float) -> dict[str, Any]:
        report["spend_usd"] = round(self._spent, 5)
        report["runtime_s"] = round(time.time() - t0, 2)
        base = report.get("base_image") or {}
        report["image_urls"] = {
            "base": base.get("image_url"),
            "final": report.get("final_image_url"),
            "artifacts": [a["artifact_url"] for a in report["routes_executed"]
                          if a.get("artifact_url")],
        }
        return report
