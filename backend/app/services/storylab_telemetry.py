"""StoryLab generation telemetry sink (S24AZ — survival hardening).

A thread-local accumulator that records per-call token usage and estimated cost
for every OpenRouter generation in a StoryLab request. The generator service
layer has no DB session, so it records into this sink; the route layer (which
owns the session) drains the sink at the end of the request and persists the
rows into the ``generation_telemetry`` table.

Design notes
------------
  * Thread-local: FastAPI runs sync endpoints in a threadpool. The whole
    endpoint — route + generator sub-calls — executes on a single thread, so a
    thread-local list is safe and isolated per request. ``reset()`` is called at
    the start of every instrumented endpoint to clear any residue from a reused
    worker thread.
  * Token counts are ACTUAL (read from the OpenRouter ``usage`` object). Only
    the per-token RATE used to derive ``cost_usd`` is approximate — see
    ``_MODEL_PRICING``. When a model's rate is unknown, ``cost_usd`` is left
    None rather than guessed.
  * Recording is best-effort and must never break generation: ``record()``
    swallows all exceptions.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Cost model (approximate — verify against current OpenRouter pricing) ───────
# USD per 1,000 tokens, as (input_rate, output_rate). These are conservative
# public list prices for the OpenRouter slugs StoryLab routes to; token COUNTS
# are exact, only these rates are approximate. Update when pricing changes.
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "qwen/qwen-2.5-72b-instruct":          (0.00090, 0.00090),
    "mistralai/mixtral-8x22b-instruct":    (0.00090, 0.00090),
    "mistralai/mixtral-8x7b-instruct":     (0.00024, 0.00024),
    "meta-llama/llama-3.1-70b-instruct":   (0.00040, 0.00040),
}


def estimate_cost_usd(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
    """Return estimated USD cost from actual token counts, or None if unknown.

    Cost = (prompt_tokens × input_rate + completion_tokens × output_rate) / 1000.
    Returns None when the model has no known rate (so callers can store NULL
    rather than a fabricated number).
    """
    rate = _MODEL_PRICING.get((model or "").strip())
    if rate is None:
        return None
    p = prompt_tokens or 0
    c = completion_tokens or 0
    return round((p * rate[0] + c * rate[1]) / 1000.0, 8)


@dataclass
class _UsageRecord:
    kind: str                 # continuation | chapter | summary | rp_reply | canon_extract
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


@dataclass
class _Sink:
    records: list[_UsageRecord] = field(default_factory=list)


_local = threading.local()


def _sink() -> _Sink:
    s = getattr(_local, "sink", None)
    if s is None:
        s = _Sink()
        _local.sink = s
    return s


def reset() -> None:
    """Clear the thread-local sink. Call at the start of each instrumented request."""
    _local.sink = _Sink()


def record(kind: str, provider: str, model: str, usage: dict[str, Any] | None) -> None:
    """Record one OpenRouter call's usage into the thread-local sink.

    ``usage`` is the OpenRouter response ``usage`` object (may be None/partial).
    Best-effort: never raises.
    """
    try:
        usage = usage or {}
        pt = usage.get("prompt_tokens")
        ct = usage.get("completion_tokens")
        tt = usage.get("total_tokens")
        if tt is None and (pt is not None or ct is not None):
            tt = (pt or 0) + (ct or 0)
        pt_i = int(pt) if pt is not None else None
        ct_i = int(ct) if ct is not None else None
        tt_i = int(tt) if tt is not None else None
        cost = estimate_cost_usd(model, pt_i, ct_i)
        _sink().records.append(
            _UsageRecord(
                kind=kind,
                provider=provider,
                model=model,
                prompt_tokens=pt_i,
                completion_tokens=ct_i,
                total_tokens=tt_i,
                cost_usd=cost,
            )
        )
    except Exception as exc:  # noqa: BLE001 — telemetry must never break generation
        logger.warning("[SL-TELEMETRY] record failed kind=%s: %s", kind, exc)


def drain() -> list[_UsageRecord]:
    """Return and clear all records accumulated on this thread."""
    s = _sink()
    out = list(s.records)
    s.records.clear()
    return out


def aggregate_by_kind(records: list[_UsageRecord]) -> dict[str, dict[str, Any]]:
    """Collapse per-call records into one summed entry per kind.

    Returns ``{kind: {provider, model, calls, prompt_tokens, completion_tokens,
    total_tokens, cost_usd}}``. Token/cost sums are None only when no call in
    that kind reported a value (keeps stub rows honest with NULLs).
    """
    out: dict[str, dict[str, Any]] = {}
    for r in records:
        agg = out.get(r.kind)
        if agg is None:
            agg = {
                "provider": r.provider,
                "model": r.model,
                "calls": 0,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "cost_usd": None,
            }
            out[r.kind] = agg
        agg["calls"] += 1
        # last non-empty model/provider wins (they are identical within a kind)
        if r.model:
            agg["model"] = r.model
        if r.provider:
            agg["provider"] = r.provider
        for f in ("prompt_tokens", "completion_tokens", "total_tokens", "cost_usd"):
            val = getattr(r, f)
            if val is not None:
                agg[f] = (agg[f] or 0) + val
    return out
