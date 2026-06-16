#!/usr/bin/env python3
"""S24E — upload the kohya training pack to R2 so the RunPod pod can fetch it.

R2 is the same artifact/result channel the existing RunPod proof harness uses. This
uploads scripts/summer_lora_v3_pack.zip under a per-run key and returns a public URL.

Usage:
  python runpod_kohya_upload.py [--pack PATH] [--run-id RID]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# S24Y: train from the approved-only v4 pack (S24X export).
DEFAULT_PACK = HERE / "summer_lora_v4_approved_pack" / "summer_lora_v4_approved_pack.zip"


def _r2_client():
    import boto3  # lazy

    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def upload_file(local_path: str | Path, key: str, content_type: str = "application/zip") -> str:
    """Upload a local file to R2 under *key*; return its public URL."""
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(local_path)
    client = _r2_client()
    client.put_object(
        Bucket=os.environ["R2_BUCKET_NAME"],
        Key=key,
        Body=local_path.read_bytes(),
        ContentType=content_type,
    )
    return f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/{key}"


def upload_pack(pack: str | Path = DEFAULT_PACK, run_id: str = "manual") -> str:
    key = f"lora_training/{run_id}/summer_lora_v4_approved_pack.zip"
    url = upload_file(pack, key)
    return url


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default=str(DEFAULT_PACK))
    ap.add_argument("--run-id", default="manual")
    args = ap.parse_args()
    pack = Path(args.pack)
    if not pack.exists():
        print(f"FATAL: pack not found: {pack}")
        return 1
    size_mb = pack.stat().st_size / 1e6
    url = upload_pack(pack, args.run_id)
    print(f"uploaded {pack.name} ({size_mb:.1f} MB) -> {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
