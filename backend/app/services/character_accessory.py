"""Character accessory helpers for identity-pack accessory slot (v1/v2)."""
import json as _json
import re
from typing import Any


def get_accessories(identity_anchor_json: str | None) -> list[dict]:
    """Parse accessories list from identity_anchor_json. Returns [] on any failure."""
    if not identity_anchor_json:
        return []
    try:
        data = _json.loads(identity_anchor_json)
        accessories = data.get("accessories")
        if not isinstance(accessories, list):
            return []
        return accessories
    except (ValueError, TypeError, AttributeError):
        return []


def build_accessory_prompt_block(character: Any, prompt: str) -> str:
    """Return a SIGNATURE ACCESSORY prompt block if the prompt triggers a locked accessory.

    Returns empty string when:
    - character has no accessories
    - no accessory is triggered by the prompt

    Trigger logic: case-insensitive match of accessory.type or its past-tense (+d)
    anywhere in the prompt. E.g. type="mask" triggers on "mask", "masked",
    "wearing his mask".

    Output format:
    SIGNATURE ACCESSORY — PRESERVE IF INCLUDED:
    {accessory.name}: {accessory.description}
    {visual_rules, one per line}
    Do not redesign the {accessory.type}. Preserve shape, material, and colour.
    """
    accessories = get_accessories(getattr(character, "identity_anchor_json", None))
    if not accessories:
        return ""

    prompt_lower = prompt.lower()
    triggered = None
    for acc in accessories:
        acc_type = acc.get("type", "")
        if not acc_type:
            continue
        acc_type_lower = acc_type.lower()
        past_tense = acc_type_lower + "d"
        # Check if type or past-tense variant appears as a word (or word-start) in prompt.
        # We use word-boundary on the left side so "mask" matches "mask", "masked",
        # "masking", "maskd" etc. but not a suffix like "unmask" only if "mask" is embedded.
        # Simple approach: check if type appears as substring of prompt (catches "masked").
        if acc_type_lower in prompt_lower or past_tense in prompt_lower:
            triggered = acc
            break

    if triggered is None:
        return ""

    acc_type = triggered.get("type", "")
    acc_name = triggered.get("name", "")
    acc_desc = triggered.get("description", "")
    visual_rules = triggered.get("visual_rules") or []

    lines = [
        "SIGNATURE ACCESSORY — PRESERVE IF INCLUDED:",
        f"{acc_name}: {acc_desc}",
    ]
    for rule in visual_rules:
        if rule:
            lines.append(rule)
    lines.append(f"Do not redesign the {acc_type}. Preserve shape, material, and colour.")

    block = "\n".join(lines)
    # Hard-cap at 400 chars
    return block[:400]


def build_anchor_prompt(accessory: dict) -> str:
    """Build a standalone product-style image prompt for the accessory anchor image.

    The generated image shows the object alone — no wearer, neutral background,
    front product view. Visual rules are appended as descriptive qualifiers.
    """
    name = accessory.get("name", "accessory")
    description = accessory.get("description", "")
    visual_rules = accessory.get("visual_rules") or []

    base = description if description else name
    parts = [f"Standalone product-style image of {base}"]
    for rule in visual_rules:
        if rule:
            parts.append(rule.rstrip(", "))
    parts += [
        "object only",
        "no person wearing it",
        "clean neutral background",
        "front product view",
        "highly detailed",
        "no logos",
        "no bright colors",
        "no monstrous exaggeration",
    ]
    return ", ".join(parts)[:800]


def build_fit_anchor_prompt(accessory: dict, character_name: str = "") -> str:
    """Build a worn-portrait prompt for the accessory fit anchor image.

    The generated image shows the character wearing the accessory correctly —
    fitted to the appropriate area only, head/skull/hair remain visible.
    Character face identity is the primary subject; accessory is secondary.
    """
    name = accessory.get("name", "accessory")
    description = accessory.get("description", "")
    visual_rules = accessory.get("visual_rules") or []
    acc_type = accessory.get("type", "accessory")

    base = description if description else name
    subject = f"Portrait of {character_name}" if character_name else "Neutral portrait headshot"

    parts = [subject, f"wearing {base}"]
    for rule in visual_rules:
        if rule:
            parts.append(rule.rstrip(", "))
    parts += [
        f"The {acc_type} is worn by the character, fitted to the lower face only",
        f"It must not replace the head, skull, hair, or full face",
        "Eyes, forehead, hair, and head shape remain visible",
        "Character face identity preserved",
        "Neutral plain background",
        "Front-facing portrait",
        "photorealistic",
        "no redesign of the accessory",
    ]
    return ", ".join(parts)[:800]


def get_identity_anchor_urls(identity_anchor_json: str | None) -> list[str]:
    """Return identity anchor image URLs in preferred load order (front first)."""
    if not identity_anchor_json:
        return []
    try:
        data = _json.loads(identity_anchor_json)
        anchors = data.get("anchors") or {}
        urls: list[str] = []
        for key in ("front", "three_quarter", "torso", "full_body"):
            entry = anchors.get(key)
            if entry and entry.get("url"):
                urls.append(entry["url"])
        return urls
    except (ValueError, TypeError):
        return []


def get_triggered_accessory(identity_anchor_json: str | None, prompt: str) -> dict | None:
    """Return the first accessory triggered by the prompt, or None.

    Mirrors the trigger logic in build_accessory_prompt_block without building
    the full text block — useful when only the accessory dict is needed.
    """
    accessories = get_accessories(identity_anchor_json)
    if not accessories:
        return None
    prompt_lower = prompt.lower()
    for acc in accessories:
        acc_type = acc.get("type", "")
        if not acc_type:
            continue
        acc_type_lower = acc_type.lower()
        if acc_type_lower in prompt_lower or (acc_type_lower + "d") in prompt_lower:
            return acc
    return None


def update_accessory_in_json(
    identity_anchor_json: str | None,
    accessory_id: str,
    updates: dict,
) -> "tuple[str, dict | None]":
    """Apply field updates to the accessory with the given id in-place.

    Returns (updated_json_str, updated_accessory_dict).
    Returns (original_json, None) when the accessory_id is not found.
    """
    if identity_anchor_json:
        try:
            data = _json.loads(identity_anchor_json)
        except (ValueError, TypeError):
            data = {}
    else:
        data = {}

    accessories: list[dict] = data.get("accessories") or []
    if not isinstance(accessories, list):
        return identity_anchor_json or "{}", None

    updated_acc: dict | None = None
    for i, acc in enumerate(accessories):
        if acc.get("id") == accessory_id:
            accessories[i] = {**acc, **updates}
            updated_acc = accessories[i]
            break

    if updated_acc is None:
        return identity_anchor_json or "{}", None

    data["accessories"] = accessories
    return _json.dumps(data), updated_acc


def append_accessory(identity_anchor_json: str | None, accessory: dict) -> str:
    """Return updated identity_anchor_json string with the accessory appended/replaced.

    If an accessory with the same type already exists, replace it.
    Returns a JSON string.
    """
    if identity_anchor_json:
        try:
            data = _json.loads(identity_anchor_json)
        except (ValueError, TypeError):
            data = {}
    else:
        data = {}

    accessories: list[dict] = data.get("accessories") or []
    if not isinstance(accessories, list):
        accessories = []

    # Replace existing accessory of same type, or append
    new_type = accessory.get("type", "")
    replaced = False
    for i, existing in enumerate(accessories):
        if existing.get("type", "") == new_type:
            accessories[i] = accessory
            replaced = True
            break

    if not replaced:
        accessories.append(accessory)

    data["accessories"] = accessories
    return _json.dumps(data)
