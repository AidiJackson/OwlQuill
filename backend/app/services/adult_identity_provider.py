"""Training-provider abstraction for Adult Studio (Phase 1, Sprint 5).

Defines the seam between the orchestration lifecycle (Sprint 4) and whatever actually
trains a per-character LoRA (Replicate / RunPod / Modal). This module contains ONLY the
protocol + result model + an in-memory FakeTrainingProvider for tests. It makes NO
external API calls, launches NO GPU, and spends NOTHING.

Real provider implementations (Replicate, etc.) are deliberately NOT added here — that
is a later sprint and would require live API access. The orchestration layer is fully
exercisable through the fake.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


class ProviderStatus:
    """Provider-side job statuses (distinct from our internal job/identity states)."""
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

    TERMINAL = frozenset({COMPLETED, FAILED, CANCELED})


@dataclass
class ProviderJob:
    """Normalized result returned by every TrainingProvider method."""
    provider_job_id: str
    status: str
    model_artifact_uri: Optional[str] = None
    cost_estimate: Optional[float] = None
    error: Optional[str] = None


@runtime_checkable
class TrainingProvider(Protocol):
    """A pluggable trainer. Implementations own all external interaction."""
    name: str

    def create_training_job(
        self,
        *,
        identity_id: int,
        trigger_token: Optional[str],
        base_model: Optional[str],
        training_config: Optional[dict],
        source_manifest: Optional[dict],
    ) -> ProviderJob: ...

    def poll_training_job(self, provider_job_id: str) -> ProviderJob: ...

    def cancel_training_job(self, provider_job_id: str) -> ProviderJob: ...


class FakeTrainingProvider:
    """In-memory fake provider for tests/dev. No network, no GPU, no spend.

    Configurable terminal outcome:
      - default: poll() reports COMPLETED with `artifact_uri`.
      - fail=True: poll() reports FAILED with `fail_reason`.
    Every call is recorded in `.calls` so tests can assert the seam was used (and that
    no real provider was reached).
    """
    name = "fake"

    def __init__(
        self,
        *,
        artifact_uri: str = "r2://fake/adult/lora.safetensors",
        cost_estimate: float = 0.34,
        fail: bool = False,
        fail_reason: str = "fake provider failure",
    ) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._jobs: dict[str, ProviderJob] = {}
        self._counter = 0
        self._artifact_uri = artifact_uri
        self._cost = cost_estimate
        self._fail = fail
        self._fail_reason = fail_reason

    def create_training_job(self, *, identity_id, trigger_token, base_model,
                            training_config, source_manifest) -> ProviderJob:
        self._counter += 1
        pjid = f"fake-job-{self._counter}"
        job = ProviderJob(provider_job_id=pjid, status=ProviderStatus.RUNNING,
                          cost_estimate=self._cost)
        self._jobs[pjid] = job
        self.calls.append(("create", pjid))
        return job

    def poll_training_job(self, provider_job_id: str) -> ProviderJob:
        self.calls.append(("poll", provider_job_id))
        if self._fail:
            return ProviderJob(provider_job_id=provider_job_id, status=ProviderStatus.FAILED,
                               error=self._fail_reason, cost_estimate=self._cost)
        return ProviderJob(provider_job_id=provider_job_id, status=ProviderStatus.COMPLETED,
                           model_artifact_uri=self._artifact_uri, cost_estimate=self._cost)

    def cancel_training_job(self, provider_job_id: str) -> ProviderJob:
        self.calls.append(("cancel", provider_job_id))
        return ProviderJob(provider_job_id=provider_job_id, status=ProviderStatus.CANCELED,
                           cost_estimate=self._cost)
