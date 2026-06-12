"""Self-hosted Editor Studio provider (E4) — RunPod SDXL inpaint transform.

The premium unrestricted transformation path proven in Sprint E3: the source
image is structural truth; a throwaway RunPod instance runs SegFormer masking
+ RealVisXL inpaint (outfit pass, remnant cleanup, scene pass) and streams
results to R2. This module is the production supervisor: it uploads the
source, launches the pod, polls status under hard spend/time caps, downloads
the final image, and GUARANTEES termination (finally-terminate + orphan
verify).

Synchronous by design — the editor route runs providers in a worker thread.
A call takes ~2-10 minutes depending on host cache warmth.

Env (not in Settings — same direct-os.environ convention as core/storage.py):
  RUNPOD_API_KEY, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
  R2_BUCKET_NAME, R2_PUBLIC_URL
Optional:
  EDITOR_SELF_HOSTED_LORA_URL (defaults to the active Summer LoRA lookup),
  EDITOR_SELF_HOSTED_BASE_MODEL (default RealVisXL_V4.0)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
import uuid
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_GQL = "https://api.runpod.io/graphql"
_REST = "https://rest.runpod.io/v1/pods"

GPU_CANDIDATES = ["NVIDIA RTX A5000", "NVIDIA RTX A4500", "NVIDIA GeForce RTX 3090"]
SPEND_CAP_USD = 0.05        # hard per-edit cap
TERMINATE_AT_USD = 0.045
WATCHDOG_S = 720            # in-pod self-kill backstop
SUPERVISE_WALLCLOCK_S = 720
POLL_S = 15
MAX_SAFE_RATE = round(SPEND_CAP_USD / (WATCHDOG_S / 3600.0) * 0.95, 4)

_POD_SCRIPT = Path(__file__).resolve().parent / "editor_self_hosted_pod.py"


class SelfHostedEditorError(RuntimeError):
    """Raised when the self-hosted transform fails or breaches a cap."""


def _gql(key: str, query: str, variables: dict | None = None) -> dict:
    r = requests.post(f"{_GQL}?api_key={key}",
                      json={"query": query, "variables": variables or {}}, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise SelfHostedEditorError(json.dumps(j["errors"])[:400])
    return j["data"]


def _list_pods(key: str) -> dict:
    return _gql(key, "query { myself { pods { id desiredStatus costPerHr "
                     "runtime { uptimeInSeconds } } } }")["myself"]


def _terminate(key: str, pod_id: str | None) -> None:
    if not pod_id:
        return
    try:
        _gql(key, "mutation($id:String!){ podTerminate(input:{podId:$id}) }",
             {"id": pod_id})
        logger.info("SELF_HOSTED_EDITOR terminate sent pod=%s", pod_id)
    except Exception as exc:  # noqa: BLE001 — watchdog backs this up
        # Pod already gone (in-pod self-kill won the race) — the desired end
        # state, not an error.
        if "pod_not_found" in str(exc).lower().replace(" ", "_"):
            logger.info(
                "SELF_HOSTED_EDITOR pod=%s already terminated — benign double-terminate",
                pod_id)
        else:
            logger.warning("SELF_HOSTED_EDITOR terminate error pod=%s: %s", pod_id, exc)


def _r2_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def _r2_status(run_id: str) -> dict:
    """Authenticated status read — public R2 URLs 403 for server-side GETs."""
    try:
        body = _r2_client().get_object(
            Bucket=os.environ["R2_BUCKET_NAME"],
            Key=f"proof/{run_id}/status.json")["Body"].read()
        return json.loads(body)
    except Exception:  # noqa: BLE001 — absent until the pod's first push
        return {}


def _default_lora_url() -> str:
    """Active Summer LoRA artifact (read-only plan lookup), overridable by env."""
    override = os.environ.get("EDITOR_SELF_HOSTED_LORA_URL")
    if override:
        return override
    from app.core.database import SessionLocal
    from app.services.adult_identity_enforcement_plan import build_enforcement_plan
    db = SessionLocal()
    try:
        plan = build_enforcement_plan(
            60, db, route_expectations={"sleeve": "ip_adapter",
                                        "ballerina": "controlnet_canny"})
        if not plan["ready_for_executor"]:
            logger.warning("SELF_HOSTED_EDITOR lora plan not ready — running without LoRA")
            return ""
        return plan["model_artifact_uri"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("SELF_HOSTED_EDITOR lora lookup failed (%s) — running without", exc)
        return ""
    finally:
        db.close()


def _launch(key: str, env: dict, wrapper_b64: str) -> tuple[dict | None, str | None]:
    body = {
        "name": "editor-self-hosted",
        "imageName": "runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04",
        "gpuCount": 1,
        "cloudType": "COMMUNITY",
        "containerDiskInGb": 40,
        "volumeInGb": 0,
        "ports": ["8888/http"],
        "env": env,
        "dockerStartCmd": ["bash", "-c", f"echo {wrapper_b64} | base64 -d | bash"],
    }
    for gpu in GPU_CANDIDATES:
        body["gpuTypeIds"] = [gpu]
        rr = requests.post(_REST, headers={"Authorization": f"Bearer {key}",
                                           "Content-Type": "application/json"},
                           json=body, timeout=90)
        if rr.status_code in (200, 201):
            pod = rr.json()
            logger.info("SELF_HOSTED_EDITOR launched gpu=%s pod=%s rate=$%s",
                        gpu, pod.get("id"), pod.get("costPerHr"))
            return pod, gpu
        logger.info("SELF_HOSTED_EDITOR launch failed gpu=%s status=%s body=%s",
                    gpu, rr.status_code, rr.text[:200])
    return None, None


def _build_wrapper() -> str:
    wrapper = (
        '#!/bin/bash\n'
        'KEY="$RUNPOD_API_KEY"; PODID="$RUNPOD_POD_ID"\n'
        'command -v curl >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq curl)\n'
        'selfkill(){ curl -s -X POST "https://api.runpod.io/graphql?api_key=$KEY" '
        '-H "Content-Type: application/json" '
        '-d "{\\"query\\":\\"mutation { podTerminate(input:{podId:\\\\\\"$PODID\\\\\\"}) }\\"}"; }\n'
        f'( sleep {WATCHDOG_S}; echo WATCHDOG_FIRED; selfkill ) &\n'
        'mkdir -p /workspace\n'
        'echo "$PROOF_PY_B64" | base64 -d > /workspace/proof.py\n'
        'pip install -q --no-cache-dir "diffusers==0.31.0" "transformers==4.46.3" accelerate '
        'safetensors peft boto3 2>&1 | tail -3\n'
        'pip install -q --no-cache-dir "numpy==1.26.4" 2>&1 | tail -2\n'
        'python /workspace/proof.py\n'
        'echo "MAIN_DONE rc=$?"\n'
        'selfkill\n'
    )
    return base64.b64encode(wrapper.encode()).decode()


class SelfHostedImageEditor:
    """RunPod source-truth transform editor — the E4 premium path."""

    provider_name = "self_hosted"
    editor_version = "e4"

    def __init__(self) -> None:
        if not os.environ.get("RUNPOD_API_KEY"):
            raise RuntimeError(
                "RUNPOD_API_KEY is not configured — required for the self_hosted editor."
            )
        for var in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                    "R2_BUCKET_NAME", "R2_PUBLIC_URL"):
            if not os.environ.get(var):
                raise RuntimeError(f"{var} is not configured — required for the self_hosted editor.")

    def edit(
        self,
        *,
        prompt: str,
        source_images: list[bytes],
        strength: float,  # accepted for interface parity; pod runs fixed passes
        size: str = "1024x1024",
    ) -> bytes:
        """Transform ONE source image per the prompt on owned compute.

        Raises:
            ValueError: invalid inputs (only one source image is supported).
            SelfHostedEditorError: pod failure, cap breach, or timeout.
        """
        if not source_images:
            raise ValueError("At least one source image is required.")
        if len(source_images) != 1:
            raise ValueError(
                "self_hosted editor supports exactly 1 source image (got "
                f"{len(source_images)})."
            )
        return self.transform(prompt=prompt, source_png=source_images[0])["png"]

    def transform(
        self,
        *,
        prompt: str,
        source_png: bytes,
        run_id: str | None = None,
        on_launch=None,  # callable(pod_id: str) — fires once the pod exists
    ) -> dict:
        """Run the full transform; return the final PNG plus run telemetry.

        Returns a dict: ``png`` (bytes), ``run_id``, ``pod_id``, ``gpu``,
        ``rate_usd_hr``, ``spend_usd``, ``status`` (the pod's final status.json
        with stage images and quality metrics).

        Raises:
            ValueError: empty prompt.
            SelfHostedEditorError: pod failure, cap breach, or timeout.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")

        key = os.environ["RUNPOD_API_KEY"]
        run_id = run_id or f"editor_sh_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        # Source travels via R2 — pods read it authenticated, never via public URL.
        s3 = _r2_client()
        bucket = os.environ["R2_BUCKET_NAME"]
        src_key = f"proof/{run_id}/input_source.png"
        s3.put_object(Bucket=bucket, Key=src_key, Body=source_png,
                      ContentType="image/png")

        env = {
            "RUNPOD_API_KEY": key,
            "R2_ACCOUNT_ID": os.environ["R2_ACCOUNT_ID"],
            "R2_ACCESS_KEY_ID": os.environ["R2_ACCESS_KEY_ID"],
            "R2_SECRET_ACCESS_KEY": os.environ["R2_SECRET_ACCESS_KEY"],
            "R2_BUCKET_NAME": bucket,
            "R2_PUBLIC_URL": os.environ["R2_PUBLIC_URL"],
            "PROOF_RUN_ID": run_id,
            "PROOF_PY_B64": base64.b64encode(_POD_SCRIPT.read_bytes()).decode(),
            "SOURCE_URL": src_key,
            "LORA_URL": _default_lora_url(),
            "USER_PROMPT": prompt.strip(),
            "BASE_MODEL_ID": os.environ.get(
                "EDITOR_SELF_HOSTED_BASE_MODEL", "SG161222/RealVisXL_V4.0"),
        }

        pod, gpu = _launch(key, env, _build_wrapper())
        if pod is None:
            raise SelfHostedEditorError(
                "No community GPU available — no pod launched, no spend.")
        pod_id = pod["id"]
        if on_launch is not None:
            try:
                on_launch(pod_id)
            except Exception:  # noqa: BLE001 — a callback bug must not strand the pod
                logger.warning("SELF_HOSTED_EDITOR on_launch callback failed", exc_info=True)

        rate = float(pod.get("costPerHr") or 0.0)
        if rate <= 0 or rate > MAX_SAFE_RATE:
            _terminate(key, pod_id)
            raise SelfHostedEditorError(
                f"Rate guard: ${rate}/hr exceeds max safe ${MAX_SAFE_RATE}/hr — terminated.")

        logger.info("SELF_HOSTED_EDITOR run=%s pod=%s gpu=%s rate=$%s prompt=%r",
                    run_id, pod_id, gpu, rate, prompt[:60])

        t0 = time.time()
        st: dict = {}
        spend = 0.0
        try:
            while True:
                time.sleep(POLL_S)
                pods = {p["id"]: p for p in _list_pods(key)["pods"]}
                st = _r2_status(run_id)
                up = (pods.get(pod_id, {}).get("runtime") or {}).get("uptimeInSeconds") or 0
                rate = pods.get(pod_id, {}).get("costPerHr") or rate
                spend = round(up / 3600.0 * rate, 4)
                logger.info("SELF_HOSTED_EDITOR poll run=%s up=%ss spend=$%s stage=%s",
                            run_id, up, spend, st.get("stage", "?"))
                if st.get("done"):
                    break
                if pod_id not in pods:
                    break  # self-terminated; status may still show done below
                fatal = any("fatal" in str(e).lower() for e in (st.get("errors") or []))
                if spend >= TERMINATE_AT_USD or up >= SUPERVISE_WALLCLOCK_S or fatal:
                    _terminate(key, pod_id)
                    reason = ("spend cap" if spend >= TERMINATE_AT_USD
                              else "wallclock" if up >= SUPERVISE_WALLCLOCK_S
                              else "fatal pod error")
                    raise SelfHostedEditorError(
                        f"self_hosted edit aborted ({reason}); spend=${spend}, "
                        f"stage={st.get('stage')}, errors={st.get('errors')}")
                if time.time() - t0 > SUPERVISE_WALLCLOCK_S + 120:
                    _terminate(key, pod_id)
                    raise SelfHostedEditorError("self_hosted edit supervision timeout.")
        finally:
            _terminate(key, pod_id)  # idempotent — guarantee no orphan
            try:
                time.sleep(5)
                still = {p["id"]: p for p in _list_pods(key)["pods"]}
                orphaned = pod_id in still and still[pod_id].get("desiredStatus") not in (
                    "TERMINATED", "EXITED")
                if orphaned:
                    logger.error("SELF_HOSTED_EDITOR ORPHAN pod=%s — retrying terminate", pod_id)
                    _terminate(key, pod_id)
            except Exception:  # noqa: BLE001
                pass

        st = _r2_status(run_id) or st
        final_key = f"proof/{run_id}/99_final.png"
        if not (st.get("done") and st.get("images", {}).get("99_final")):
            raise SelfHostedEditorError(
                f"self_hosted edit did not complete: stage={st.get('stage')}, "
                f"errors={st.get('errors')}")
        png = s3.get_object(Bucket=bucket, Key=final_key)["Body"].read()
        logger.info("SELF_HOSTED_EDITOR done run=%s bytes=%d quality=%s",
                    run_id, len(png), st.get("quality"))
        return {
            "png": png,
            "run_id": run_id,
            "pod_id": pod_id,
            "gpu": gpu,
            "rate_usd_hr": rate,
            "spend_usd": spend,
            "runtime_s": round(time.time() - t0, 1),
            "status": st,
        }
