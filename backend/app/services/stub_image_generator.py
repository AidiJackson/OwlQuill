"""Stub image generator — creates simple placeholder PNGs for MVP.

Produces solid-colour images with text overlays. No external AI services.

A BYTE GENERATOR, NOT AN ASSET OWNER (Phase 4D2)
------------------------------------------------
:func:`render_placeholder_png` returns bytes and knows nothing about storage,
ownership, characters or the database. That is deliberate. Its callers were
spread across five modules and they did not agree on who owns the result, what
kind it is, or which transaction it joins — a character's identity anchor, a
scene fallback, a library image, a canon slot. Teaching a low-level renderer to
answer those questions would put ownership semantics in the one place with no
information to decide them.

So the split is: this module makes pixels; the caller persists them through
``asset_persistence.persist_image_asset`` with the ownership it actually knows.

Phase 4D3-3 retired ``generate_placeholder_png``, the legacy wrapper that
rendered AND stored in one call and returned a bare ``file_path``. Its last
caller — the scene-from-canon fallback in ``canon_api`` — now renders bytes here
and persists them through ``asset_persistence.persist_image_asset`` like every
other durable write, so a placeholder ends up owned and reviewable instead of
being bytes with no row behind them. This module no longer imports storage at
all, which is the clearest statement of what it is: a renderer.
"""
import io

from PIL import Image, ImageDraw, ImageFont

# Colour palette per pack role
_ROLE_COLOURS: dict[str, tuple[int, int, int]] = {
    "anchor_front": (45, 125, 126),          # teal
    "anchor_three_quarter": (58, 155, 156),   # lighter teal
    "anchor_torso": (15, 61, 62),             # dark teal
    "generated": (90, 90, 120),               # muted purple-grey
}


def render_placeholder_png(
    *,
    label: str,
    sublabel: str = "",
    role: str = "generated",
    width: int = 512,
    height: int = 768,
) -> bytes:
    """Render a placeholder PNG and return its BYTES.

    The whole of what this module knows how to do. Persisting the result — and
    deciding who owns it — belongs to the caller.
    """
    bg = _ROLE_COLOURS.get(role, (80, 80, 80))
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except (OSError, IOError):
        font_large = ImageFont.load_default()
        font_small = font_large

    text_colour = (255, 255, 255)
    bbox = draw.textbbox((0, 0), label, font=font_large)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) / 2, (height - th) / 2 - 20), label, fill=text_colour, font=font_large)

    if sublabel:
        bbox2 = draw.textbbox((0, 0), sublabel, font=font_small)
        tw2 = bbox2[2] - bbox2[0]
        draw.text(((width - tw2) / 2, (height + th) / 2 + 10), sublabel, fill=(200, 200, 200), font=font_small)

    draw.rectangle([10, 10, width - 11, height - 11], outline=(255, 255, 255, 128), width=2)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
