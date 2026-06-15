#!/usr/bin/env python3
"""S24R — cache the RealVisXL V4.0 SDXL base checkpoint into R2 once.

Why: S24Q's training pod spent its entire 9000s wallclock stuck in `download_base`
pulling the ~6.94GB RealVisXL checkpoint from Hugging Face and never reached `train`.
Caching the base in R2 lets every future pod fetch it from the authenticated R2 cache
via boto3 (fast, same-provider network) instead of the slow HF resolve.

Behaviour:
  * If the R2 key already exists at ~6.94GB -> report cached=true and stop (idempotent).
  * Otherwise stream the checkpoint from HF to a local temp file, upload it to R2 via
    boto3 multipart (upload_file with a TransferConfig), then verify the final R2 size.

This script performs NO training and launches NO pod. It only moves bytes HF -> local -> R2.

  python scripts/cache_realvisxl_to_r2.py            # cache (no-op if already cached)
  python scripts/cache_realvisxl_to_r2.py --check    # report cache state only, do nothing
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

import boto3
import requests
from boto3.s3.transfer import TransferConfig

HF_URL = "https://huggingface.co/SG161222/RealVisXL_V4.0/resolve/main/RealVisXL_V4.0.safetensors"
R2_KEY = "lora_training/base_models/RealVisXL_V4.0.safetensors"
# RealVisXL_V4.0.safetensors is ~6.94GB. Accept anything in a generous band around that so a
# transient/partial upload (much smaller) or a wrong object is not mistaken for a good cache.
EXPECTED_MIN = 6_500_000_000   # 6.5 GB
EXPECTED_MAX = 7_400_000_000   # 7.4 GB


def r2():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def head_size(cli, bucket):
    """Return the R2 object size in bytes, or None if the key does not exist."""
    try:
        return cli.head_object(Bucket=bucket, Key=R2_KEY)["ContentLength"]
    except Exception:
        return None


def gb(n):
    return f"{n / 1e9:.3f}GB" if n else "0"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report cache state only; do not download/upload")
    args = ap.parse_args()

    bucket = os.environ["R2_BUCKET_NAME"]
    cli = r2()

    existing = head_size(cli, bucket)
    if existing is not None and EXPECTED_MIN <= existing <= EXPECTED_MAX:
        print(f"cached=true key={R2_KEY} size={gb(existing)} ({existing} bytes) — nothing to do.")
        return 0
    if existing is not None:
        print(f"cached=partial/bad key={R2_KEY} size={gb(existing)} ({existing} bytes) "
              f"outside [{gb(EXPECTED_MIN)},{gb(EXPECTED_MAX)}] — will re-cache.")

    if args.check:
        print(f"cached=false key={R2_KEY} (--check: no action taken).")
        return 0

    # 1) stream HF -> local temp file (workspace has ample disk; /tmp may be small).
    tmp_dir = os.path.dirname(os.path.abspath(__file__))
    fd, tmp = tempfile.mkstemp(prefix="realvisxl_", suffix=".safetensors", dir=tmp_dir)
    os.close(fd)
    try:
        print(f"downloading base from HF -> {tmp}")
        t0 = time.time()
        with requests.get(HF_URL, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            got = 0
            next_mark = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8 << 20):  # 8 MiB
                    if not chunk:
                        continue
                    fh.write(chunk)
                    got += len(chunk)
                    if got >= next_mark:
                        pct = f"{100 * got / total:.0f}%" if total else "?"
                        print(f"  downloaded {gb(got)} / {gb(total)} ({pct})", flush=True)
                        next_mark = got + (512 << 20)  # log every ~512 MiB
        local = os.path.getsize(tmp)
        print(f"download complete: {gb(local)} ({local} bytes) in {time.time() - t0:.0f}s")
        if not (EXPECTED_MIN <= local <= EXPECTED_MAX):
            print(f"FAIL: local download size {gb(local)} outside expected band "
                  f"[{gb(EXPECTED_MIN)},{gb(EXPECTED_MAX)}] — aborting, NOT uploading.")
            return 1

        # 2) upload local -> R2 via multipart (TransferConfig drives parallel parts).
        cfg = TransferConfig(multipart_threshold=64 << 20, multipart_chunksize=64 << 20,
                             max_concurrency=4, use_threads=True)
        print(f"uploading -> r2://{bucket}/{R2_KEY} (multipart)")
        t1 = time.time()
        cli.upload_file(tmp, bucket, R2_KEY, Config=cfg,
                        ExtraArgs={"ContentType": "application/octet-stream"})
        print(f"upload complete in {time.time() - t1:.0f}s")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
            print(f"removed temp {tmp}")

    # 3) verify final R2 size.
    final = head_size(cli, bucket)
    if final is not None and EXPECTED_MIN <= final <= EXPECTED_MAX:
        print(f"cached=true key={R2_KEY} size={gb(final)} ({final} bytes) — verified.")
        return 0
    print(f"FAIL: post-upload R2 size {gb(final)} ({final}) outside expected band.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
