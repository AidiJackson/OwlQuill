Summer Fielding — Adult LoRA v4 APPROVED training pack (S24X)
=============================================================

trigger token : smmr_v4
identity      : blonde hair, blue eyes; build: slim
approved      : 18   rejected: 1   failed: 0
exported      : 18 images
exported_at   : 2026-06-16T18:40:29.437041+00:00

Contents
--------
  images/        approved candidate images (<role>.png)
  captions/      one kohya-style .txt caption per image (basename matches)
  captions.json  filename -> caption map
  manifest.json  full approved-pack manifest (roles, captions, counts)
  training_notes.json  trigger/base-model/caption guidance for training

Excluded (rejected): standing_casual

Boundaries
----------
  - Adult-safe only (swimwear/underwear/reference-body). No explicit NSFW.
  - This pack is NOT trained. It is offline LoRA v4 training material only.
  - Built from reviewed manifest statuses; rejected candidates are excluded.
