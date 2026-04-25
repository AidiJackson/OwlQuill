"""Stub image generator — creates simple placeholder PNGs for MVP.

Produces solid-colour images with text overlays. No external AI services.
"""
import io

from PIL import Image, ImageDraw, ImageFont

from app.core.storage import save_image

# Colour palette per pack role
_ROLE_COLOURS: dict[str, tuple[int, int, int]] = {
    "anchor_front": (45, 125, 126),          # teal
    "anchor_three_quarter": (58, 155, 156),   # lighter teal
    "anchor_torso": (15, 61, 62),             # dark teal
    "generated": (90, 90, 120),               # muted purple-grey
}


def generate_placeholder_png(
    *,
    label: str,
    sublabel: str = "",
    role: str = "generated",
    width: int = 512,
    height: int = 768,
) -> str:
    """Create a placeholder PNG and return a storable file_path string."""
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
    return save_image(buf.getvalue())
