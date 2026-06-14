# S24E Handover — Adult LoRA Training Status

**Date:** 2026-06-13
**Branch:** `experiment/s23c-tattoo-safe-hires`
**Status:** Paused. No active work. No spend.

---

## Where things stand

- **Summer v3 pack is ready.** The training dataset (`scripts/summer_lora_v3_pack.zip`, config in `scripts/summer_lora_v3_kohya_config.json`) is built and uploads cleanly to R2.
- **Replicate trainer is unsuitable.** The Replicate-based path was evaluated and does not meet the needs for proper SDXL LoRA training — not the right tool for this job.
- **Proper kohya training requires a new RunPod harness.** Real kohya `sd-scripts` SDXL LoRA training needs a dedicated, hardened RunPod harness (template + launch + poll + teardown). That harness does not yet exist in a reliable form.
- **S24E scripts exist but the dry-run pod launch failed before pod creation.** The S24E driver (`scripts/runpod_kohya_train.py` + helpers) was written and a dry-run was attempted. It got as far as uploading the dataset to R2, then **failed before any pod was created** — no `pod_id` was ever recorded and the in-pod status file (R2 `status.json`) returned 404, confirming the pod never booted. The exact launch error was not persisted to disk, so it cannot be quoted; most likely GPU supply exhaustion or an interrupted launch call.
- **No spend occurred.** RunPod shows zero active pods and `currentSpendPerHr: 0`; balance is intact (~$8.99). The only real action that ran was a cheap R2 dataset upload — no GPU billing.

## Files (all uncommitted, intentionally kept)

```
scripts/runpod_kohya_config.py     pure config builder (no network)
scripts/runpod_kohya_train.py      pod-launch driver — the only file that can start a pod
scripts/runpod_kohya_upload.py     R2 pack upload
scripts/runpod_kohya_download.py   artifact download
scripts/runpod_kohya_poll.py       status polling
scripts/runpod_kohya_state.json    dry-run run record (no pod_id — launch never completed)
scripts/summer_lora_v3_pack.zip    training dataset
```

None of these are committed and none execute on their own.

## Next safest paths (pick one when resuming)

- **A) Manual RunPod / kohya template setup outside the app.** Stand up a known-good kohya template on RunPod by hand, train once manually, and validate the pipeline end-to-end before re-automating. Lowest engineering risk, highest manual effort.
- **B) Harden the S24E harness in a dedicated sprint.** Take the existing S24E scripts and make the launch path robust (error persistence, GPU fallback, watchdog/spend caps, teardown verification) as focused sprint work before any further live attempts.
- **C) Pause Adult LoRA training and return to beta polish.** Shelve training entirely for now and redirect effort to beta polish work.

## Guardrails (in effect)

- Do **not** launch RunPod pods.
- Do **not** continue S24E.
- Keep all S24E files uncommitted.
- Read-only RunPod API queries (balance, pod list) are acceptable; pod launches are not.
