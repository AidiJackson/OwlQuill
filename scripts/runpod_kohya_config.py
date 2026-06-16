#!/usr/bin/env python3
"""S24E — kohya sd-scripts SDXL LoRA training config builder (pure, no network).

Produces the exact CLI args + dataset TOML for `sdxl_train_network.py`. This module
performs NO training and NO I/O beyond optionally writing a JSON snapshot — it is the
single source of truth for the v3 training settings and is unit-verifiable locally.

Defaults (S24E spec): RealVisXL SDXL base, resolution 1024, aspect buckets ENABLED,
no forced square crop, network rank 16 / alpha 16, conservative LR, 1800 steps.
"""
from __future__ import annotations

import json
from pathlib import Path

# Trigger/identity for the Summer v4 dataset (matches the approved kohya pack).
TRIGGER_TOKEN = "smmr_v4"

# In-pod canonical paths (the RunPod harness lays the dataset/base out here).
POD_DATASET_DIR = "/workspace/dataset/img"          # contains the .png + .txt pairs
POD_BASE_MODEL = "/workspace/base/realvisxl.safetensors"
POD_OUTPUT_DIR = "/workspace/output"
OUTPUT_NAME = "summer_lora_v4"

# ── Default training hyperparameters (S24E) ──────────────────────────────────
DEFAULTS = {
    # data / buckets — preserve aspect ratio, NO forced square crop
    "resolution": "1024,1024",
    "enable_bucket": True,
    "min_bucket_reso": 512,
    "max_bucket_reso": 2048,
    "bucket_reso_steps": 64,
    "bucket_no_upscale": True,
    "caption_extension": ".txt",
    "num_repeats": 10,                 # 18 imgs * 10 = 180 imgs/epoch
    # network
    "network_module": "networks.lora",
    "network_dim": 32,                 # rank (S24Y v4: 32)
    "network_alpha": 32,               # alpha == rank (S24Y v4: 32)
    # optimisation — conservative
    "train_batch_size": 2,
    "max_train_steps": 2600,           # S24Y v4
    "learning_rate": 1e-4,
    "unet_lr": 1e-4,
    "text_encoder_lr": 5e-5,
    "optimizer_type": "AdamW",         # S24Q: standard AdamW (no bitsandbytes); LoRA optimizer states are tiny
    "lr_scheduler": "cosine",
    "lr_warmup_steps": 150,            # S24Y v4
    # precision / perf
    "mixed_precision": "bf16",
    "save_precision": "bf16",
    "gradient_checkpointing": True,
    "sdpa": True,                      # memory-efficient attention (no xformers dep)
    "cache_latents": True,
    "max_data_loader_n_workers": 2,
    # io
    "save_model_as": "safetensors",
    "save_every_n_steps": 600,
    "seed": 42,
}


def build_dataset_toml(
    *, dataset_dir: str = POD_DATASET_DIR, num_repeats: int | None = None,
    resolution: str | None = None, params: dict | None = None,
) -> str:
    """Return a kohya dataset_config TOML string (buckets on, aspect preserved)."""
    p = {**DEFAULTS, **(params or {})}
    repeats = num_repeats if num_repeats is not None else p["num_repeats"]
    reso = resolution or p["resolution"]
    return (
        "[general]\n"
        f"enable_bucket = {str(p['enable_bucket']).lower()}\n"
        f"caption_extension = \"{p['caption_extension']}\"\n"
        "keep_tokens = 1\n"
        "shuffle_caption = false\n"
        "\n"
        "[[datasets]]\n"
        f"resolution = [{reso}]\n"
        f"min_bucket_reso = {p['min_bucket_reso']}\n"
        f"max_bucket_reso = {p['max_bucket_reso']}\n"
        f"bucket_reso_steps = {p['bucket_reso_steps']}\n"
        f"bucket_no_upscale = {str(p['bucket_no_upscale']).lower()}\n"
        "\n"
        "  [[datasets.subsets]]\n"
        f"  image_dir = \"{dataset_dir}\"\n"
        f"  num_repeats = {repeats}\n"
        f"  class_tokens = \"{TRIGGER_TOKEN}\"\n"
    )


def build_train_args(
    *, base_model: str = POD_BASE_MODEL, output_dir: str = POD_OUTPUT_DIR,
    output_name: str = OUTPUT_NAME, dataset_config: str = "/workspace/dataset.toml",
    params: dict | None = None,
) -> list[str]:
    """Return the sdxl_train_network.py CLI args list."""
    p = {**DEFAULTS, **(params or {})}
    args = [
        f"--pretrained_model_name_or_path={base_model}",
        f"--dataset_config={dataset_config}",
        f"--output_dir={output_dir}",
        f"--output_name={output_name}",
        f"--save_model_as={p['save_model_as']}",
        f"--network_module={p['network_module']}",
        f"--network_dim={p['network_dim']}",
        f"--network_alpha={p['network_alpha']}",
        f"--train_batch_size={p['train_batch_size']}",
        f"--max_train_steps={p['max_train_steps']}",
        f"--learning_rate={p['learning_rate']}",
        f"--unet_lr={p['unet_lr']}",
        f"--text_encoder_lr={p['text_encoder_lr']}",
        f"--optimizer_type={p['optimizer_type']}",
        f"--lr_scheduler={p['lr_scheduler']}",
        f"--lr_warmup_steps={p['lr_warmup_steps']}",
        f"--mixed_precision={p['mixed_precision']}",
        f"--save_precision={p['save_precision']}",
        f"--save_every_n_steps={p['save_every_n_steps']}",
        f"--max_data_loader_n_workers={p['max_data_loader_n_workers']}",
        f"--seed={p['seed']}",
        "--network_train_unet_only",
    ]
    if p["gradient_checkpointing"]:
        args.append("--gradient_checkpointing")
    if p["sdpa"]:
        args.append("--sdpa")
    if p["cache_latents"]:
        args.append("--cache_latents")
    return args


def build_config(params: dict | None = None) -> dict:
    """Full config snapshot: resolved params + dataset TOML + CLI args."""
    p = {**DEFAULTS, **(params or {})}
    return {
        "trigger_token": TRIGGER_TOKEN,
        "base_model": "RealVisXL_V4.0 (SDXL photoreal)",
        "params": p,
        "dataset_toml": build_dataset_toml(params=p),
        "train_args": build_train_args(params=p),
        "train_script": "sdxl_train_network.py",
        "launcher": "accelerate launch --num_processes=1 --mixed_precision=bf16",
    }


def write_config(path: str | Path, params: dict | None = None) -> dict:
    cfg = build_config(params)
    Path(path).write_text(json.dumps(cfg, indent=2))
    return cfg


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "summer_lora_v3_kohya_config.json"
    cfg = write_config(out)
    print(f"config built OK -> {out}")
    print(f"  base={cfg['base_model']} rank={cfg['params']['network_dim']} "
          f"alpha={cfg['params']['network_alpha']} steps={cfg['params']['max_train_steps']} "
          f"res={cfg['params']['resolution']} buckets={cfg['params']['enable_bucket']} "
          f"bucket_no_upscale={cfg['params']['bucket_no_upscale']}")
    print("\n--- dataset.toml ---")
    print(cfg["dataset_toml"])
    print("--- accelerate launch sdxl_train_network.py \\")
    print("      " + " \\\n      ".join(cfg["train_args"]))
