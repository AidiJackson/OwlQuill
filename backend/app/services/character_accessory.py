"""Character accessory helpers for identity-pack accessory slot (v1)."""
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
