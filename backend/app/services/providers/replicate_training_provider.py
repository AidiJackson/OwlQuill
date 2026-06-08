"""ReplicateTrainingProvider — the first real Adult Studio TrainingProvider (Phase 3, S1).

Implements the ``TrainingProvider`` protocol from ``app.services.adult_identity_provider``
by driving Replicate's hosted SDXL LoRA trainer. The flow mirrors the PROVEN Summer LoRA
training path (scripts/validate_summer_lora_v2.py): build a training ZIP from the locked
canon manifest → upload it → ensure a private destination model → start an SDXL LoRA
training → poll → cancel. No new architecture is introduced; only the orchestration seam
is implemented against the real API.

SCOPE: training lifecycle ONLY. This provider trains a per-character LoRA and reports the
trained artifact + cost back through ``ProviderJob``. It performs NO image generation, NO
inference, and never touches Canon Studio or the normal image generators.

Construction is feature-gated (see ``get_training_provider``): it requires
``ADULT_STUDIO_PROVIDER=replicate``, ``ADULT_STUDIO_TRAINING_ENABLED=true``, a
``REPLICATE_API_TOKEN`` and a configured owner. With the defaults (provider disabled) this
class is never instantiated and no network call is possible.

The HTTP layer is injected as a ``session`` (a ``requests.Session``-shaped object) so tests
can supply a fake transport and assert the exact request sequence WITHOUT any live API call.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.adult_identity_provider import ProviderJob, ProviderStatus

logger = logging.getLogger(__name__)

# ── Replicate constants (mirror the proven Summer LoRA v2 flow) ────────────────
API_BASE = "https://api.replicate.com/v1"
# stability-ai/sdxl trainer pin — same version validated for Summer's LoRA.
SDXL_TRAINER = "stability-ai/sdxl"
SDXL_TRAINER_VERSION = "7762fd07cf82c948538e41f63f77d685e02b063e37e496e96eefd46c929f9bdc"

# Per-second hardware rates used for a cost ESTIMATE from predict_time (USD/s).
HARDWARE_RATES = {"gpu-a100-large": 0.001400, "gpu-l40s": 0.000975, "gpu-t4": 0.000225}
TRAIN_HARDWARE = "gpu-a100-large"

# Training defaults — the settings that produced Summer's kept v1/v2 LoRAs.
DEFAULT_TRAIN_CONFIG = {
    "max_train_steps": 1000,
    "resolution": 1024,
    "lora_rank": 32,
    "use_face_detection_instead": True,
    "seed": 42,
}

# Replicate training status → our normalized ProviderStatus.
_STATUS_MAP = {
    "starting": ProviderStatus.SUBMITTED,
    "processing": ProviderStatus.RUNNING,
    "succeeded": ProviderStatus.COMPLETED,
    "failed": ProviderStatus.FAILED,
    "canceled": ProviderStatus.CANCELED,
}


class ReplicateTrainingError(Exception):
    """Raised when Replicate returns an unexpected/non-2xx response."""


class ReplicateTrainingProvider:
    """Trains a per-character SDXL LoRA on Replicate. Training lifecycle only."""

    name = "replicate"

    def __init__(
        self,
        *,
        api_token: str,
        owner: str,
        session: Any = None,
        trainer: str = SDXL_TRAINER,
        trainer_version: str = SDXL_TRAINER_VERSION,
        base_model: str = "sdxl",
        train_hardware: str = TRAIN_HARDWARE,
        timeout: float = 120.0,
    ) -> None:
        if not api_token:
            raise ValueError("ReplicateTrainingProvider requires an api_token")
        if not owner:
            raise ValueError("ReplicateTrainingProvider requires a destination owner")
        self._token = api_token
        self._owner = owner
        self._trainer = trainer
        self._trainer_version = trainer_version
        self.base_model = base_model  # read by the orchestration layer on completion
        self._train_hardware = train_hardware
        self._timeout = timeout
        if session is None:  # pragma: no cover - exercised only with real creds
            import requests  # local import keeps requests off the gated path

            session = requests.Session()
        self._session = session

    # ── HTTP seam ──────────────────────────────────────────────────────────────
    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _request(self, method: str, url: str, **kwargs) -> dict:
        resp = self._session.request(
            method, url, headers={**self._headers, **kwargs.pop("headers", {})},
            timeout=self._timeout, **kwargs,
        )
        status_code = getattr(resp, "status_code", None)
        if status_code is None or status_code >= 400:
            body = getattr(resp, "text", "")
            raise ReplicateTrainingError(f"{method} {url} -> {status_code}: {body}")
        return resp.json()

    # ── helpers ─────────────────────────────────────────────────────────────────
    def _destination(self, identity_id: int) -> tuple[str, str]:
        """Stable private destination model name for an identity, e.g. owner/ficshon-adult-7."""
        name = f"ficshon-adult-{identity_id}"
        return name, f"{self._owner}/{name}"

    def _build_training_zip(self, identity_id: int, source_manifest: Optional[dict]) -> bytes:
        """Package the locked-canon manifest into an SDXL LoRA training ZIP.

        Reuses the PROVEN ``build_training_pack`` packaging (canon-read-only). No new
        packaging logic is introduced here.
        """
        from app.services.adult_studio import build_training_pack

        manifest = source_manifest or {}
        if not manifest.get("refs"):
            raise ReplicateTrainingError(
                f"identity {identity_id} manifest has no refs to train on"
            )
        zip_bytes, summary = build_training_pack(
            manifest, character_id=identity_id,
            character_name=manifest.get("character_name", ""),
        )
        if summary["image_count"] == 0:
            raise ReplicateTrainingError(
                f"identity {identity_id} produced 0 trainable images"
            )
        logger.info(
            "replicate_training: built zip identity=%s images=%d",
            identity_id, summary["image_count"],
        )
        return zip_bytes

    def _upload_zip(self, zip_bytes: bytes) -> str:
        out = self._request(
            "POST", f"{API_BASE}/files",
            files={"content": ("training.zip", zip_bytes, "application/zip")},
        )
        return out["urls"]["get"]

    def _ensure_destination(self, identity_id: int) -> str:
        name, full = self._destination(identity_id)
        resp = self._session.request(
            "GET", f"{API_BASE}/models/{full}", headers=self._headers, timeout=self._timeout,
        )
        if getattr(resp, "status_code", None) == 200:
            return full
        self._request(
            "POST", f"{API_BASE}/models",
            json={
                "owner": self._owner, "name": name, "visibility": "private",
                "hardware": "gpu-l40s",
                "description": f"Ficshon Adult Studio identity LoRA ({name}).",
            },
        )
        logger.info("replicate_training: created destination %s", full)
        return full

    @staticmethod
    def _cost_from(training: dict) -> Optional[float]:
        predict_time = (training.get("metrics") or {}).get("predict_time")
        if predict_time is None:
            return None
        return round(predict_time * HARDWARE_RATES[TRAIN_HARDWARE], 4)

    # ── TrainingProvider protocol ────────────────────────────────────────────────
    def create_training_job(
        self,
        *,
        identity_id: int,
        trigger_token: Optional[str],
        base_model: Optional[str],
        training_config: Optional[dict],
        source_manifest: Optional[dict],
    ) -> ProviderJob:
        """Build → upload → ensure destination → start an SDXL LoRA training."""
        zip_bytes = self._build_training_zip(identity_id, source_manifest)
        images_url = self._upload_zip(zip_bytes)
        destination = self._ensure_destination(identity_id)

        cfg = {**DEFAULT_TRAIN_CONFIG, **(training_config or {})}
        token = trigger_token or "TOK"
        body = {
            "destination": destination,
            "input": {
                "input_images": images_url,
                "input_images_filetype": "zip",
                "token_string": token,
                "caption_prefix": f"a photo of {token}, ",
                "is_lora": True,
                **cfg,
            },
        }
        training = self._request(
            "POST",
            f"{API_BASE}/models/{self._trainer}/versions/{self._trainer_version}/trainings",
            json=body, headers={"Content-Type": "application/json"},
        )
        status = _STATUS_MAP.get(training.get("status", ""), ProviderStatus.SUBMITTED)
        logger.info(
            "replicate_training: started identity=%s job=%s status=%s",
            identity_id, training.get("id"), status,
        )
        return ProviderJob(
            provider_job_id=training["id"],
            status=status,
            cost_estimate=self._cost_from(training),
        )

    def poll_training_job(self, provider_job_id: str) -> ProviderJob:
        """Fetch the training and normalize status/artifact/cost."""
        training = self._request("GET", f"{API_BASE}/trainings/{provider_job_id}")
        status = _STATUS_MAP.get(training.get("status", ""), ProviderStatus.RUNNING)
        artifact_uri = None
        if status == ProviderStatus.COMPLETED:
            output = training.get("output") or {}
            # SDXL trainer returns {"version": "owner/name:hash", "weights": "<url>"}.
            artifact_uri = output.get("weights") or output.get("version")
        return ProviderJob(
            provider_job_id=provider_job_id,
            status=status,
            model_artifact_uri=artifact_uri,
            cost_estimate=self._cost_from(training),
            error=training.get("error"),
        )

    def cancel_training_job(self, provider_job_id: str) -> ProviderJob:
        """Cancel an in-flight training on Replicate."""
        self._request("POST", f"{API_BASE}/trainings/{provider_job_id}/cancel")
        return ProviderJob(
            provider_job_id=provider_job_id, status=ProviderStatus.CANCELED,
        )
