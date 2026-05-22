"""Seed initial Style Shop presets for beta."""
import json
import logging

from sqlalchemy.orm import Session

from app.models.style_shop import AttachmentModeEnum, PlacementEnum, ShopTypeEnum, StylePreset

logger = logging.getLogger(__name__)

_PRESETS = [
    # ── Barber ──────────────────────────────────────────────────────────
    {
        "shop_type": ShopTypeEnum.BARBER,
        "name": "Short Spiked Blond",
        "slug": "barber-short-spiked-blond",
        "description": "Short textured blond hair with spiked top and clean sides.",
        "attachment_mode": AttachmentModeEnum.PERMANENT,
        "placement": PlacementEnum.HAIR,
        "prompt_token": "short spiked blond hair, textured top, clean sides, natural blond tone",
        "sort_order": 10,
        "spec_patch_json": json.dumps({
            "hair_color": "blond",
            "hair_length": "short",
            "hair_style": "short_cut",
            "hair_texture": "straight",
        }),
    },
    {
        "shop_type": ShopTypeEnum.BARBER,
        "name": "Long Loose Blond",
        "slug": "barber-long-loose-blond",
        "description": "Long flowing blond hair worn loose, natural and relaxed.",
        "attachment_mode": AttachmentModeEnum.PERMANENT,
        "placement": PlacementEnum.HAIR,
        "prompt_token": "long loose blond hair, flowing natural, relaxed style",
        "sort_order": 20,
        "spec_patch_json": json.dumps({
            "hair_color": "blond",
            "hair_length": "long",
            "hair_style": "loose",
            "hair_texture": "straight",
        }),
    },
    {
        "shop_type": ShopTypeEnum.BARBER,
        "name": "Slicked Back Dark",
        "slug": "barber-slicked-back-dark",
        "description": "Dark hair slicked back with a sleek polished finish.",
        "attachment_mode": AttachmentModeEnum.PERMANENT,
        "placement": PlacementEnum.HAIR,
        "prompt_token": "dark hair slicked back, sleek polished finish, high shine",
        "sort_order": 30,
        "spec_patch_json": json.dumps({
            "hair_color": "dark brown",
            "hair_length": "short",
            "hair_style": "slicked_back",
            "hair_texture": "straight",
        }),
    },
    {
        "shop_type": ShopTypeEnum.BARBER,
        "name": "Messy Wolf Cut",
        "slug": "barber-messy-wolf-cut",
        "description": "Medium-length wolf cut with messy layers and effortless texture.",
        "attachment_mode": AttachmentModeEnum.PERMANENT,
        "placement": PlacementEnum.HAIR,
        "prompt_token": "medium messy wolf cut hair, layered, effortless texture, curtain-style",
        "sort_order": 40,
        "spec_patch_json": json.dumps({
            "hair_length": "medium",
            "hair_style": "layered",
            "hair_texture": "messy",
        }),
    },
    {
        "shop_type": ShopTypeEnum.BARBER,
        "name": "Tied Back Long Hair",
        "slug": "barber-tied-back-long",
        "description": "Long hair tied back in a clean ponytail or low bun.",
        "attachment_mode": AttachmentModeEnum.PERMANENT,
        "placement": PlacementEnum.HAIR,
        "prompt_token": "long hair tied back, clean ponytail, neat and pulled back",
        "sort_order": 50,
        "spec_patch_json": json.dumps({
            "hair_length": "long",
            "hair_style": "tied_back",
        }),
    },
    # ── Tattoo Parlour ───────────────────────────────────────────────────
    {
        "shop_type": ShopTypeEnum.TATTOO,
        "name": "Right Arm Black Serpent Sleeve",
        "slug": "tattoo-right-arm-serpent-sleeve",
        "description": "Black ink serpent sleeve tattoo wrapping from shoulder to wrist on the right arm.",
        "attachment_mode": AttachmentModeEnum.PERMANENT,
        "placement": PlacementEnum.RIGHT_ARM,
        "prompt_token": "right arm black serpent sleeve tattoo, wraps from shoulder to wrist, detailed black ink scales",
        "sort_order": 10,
        "spec_patch_json": None,
    },
    {
        "shop_type": ShopTypeEnum.TATTOO,
        "name": "Left Arm Gothic Script Sleeve",
        "slug": "tattoo-left-arm-gothic-script",
        "description": "Gothic script sleeve tattoo in black ink running down the full left arm.",
        "attachment_mode": AttachmentModeEnum.PERMANENT,
        "placement": PlacementEnum.LEFT_ARM,
        "prompt_token": "left arm gothic script sleeve tattoo, black ink lettering and symbols, full arm coverage",
        "sort_order": 20,
        "spec_patch_json": None,
    },
    {
        "shop_type": ShopTypeEnum.TATTOO,
        "name": "Right Arm Tribal Wolf Mark",
        "slug": "tattoo-right-arm-tribal-wolf",
        "description": "Tribal wolf mark tattoo on the right arm, bold geometric black ink.",
        "attachment_mode": AttachmentModeEnum.PERMANENT,
        "placement": PlacementEnum.RIGHT_ARM,
        "prompt_token": "right arm tribal wolf mark tattoo, bold geometric black ink, wolf head motif on upper arm",
        "sort_order": 30,
        "spec_patch_json": None,
    },
    {
        "shop_type": ShopTypeEnum.TATTOO,
        "name": "Left Arm Thorn Vine Wrap",
        "slug": "tattoo-left-arm-thorn-vine",
        "description": "Thorn vine tattoo wrapping around the left arm in dark ink.",
        "attachment_mode": AttachmentModeEnum.PERMANENT,
        "placement": PlacementEnum.LEFT_ARM,
        "prompt_token": "left arm thorn vine tattoo, dark ink thorns and vines wrapping around arm",
        "sort_order": 40,
        "spec_patch_json": None,
    },
    # ── Mask Shop ────────────────────────────────────────────────────────
    {
        "shop_type": ShopTypeEnum.MASK,
        "name": "Matte Black Demon Wolf Mask",
        "slug": "mask-matte-black-demon-wolf",
        "description": "Matte black lower-face demon wolf mask. Eyes exposed, nose bridge covered.",
        "attachment_mode": AttachmentModeEnum.REMOVABLE,
        "placement": PlacementEnum.LOWER_FACE,
        "prompt_token": "matte black lower-face demon wolf mask, eyes exposed, nose bridge covered, sculpted wolf snout detail",
        "sort_order": 10,
        "spec_patch_json": None,
    },
    {
        "shop_type": ShopTypeEnum.MASK,
        "name": "Tactical Lower-Face Mask",
        "slug": "mask-tactical-lower-face",
        "description": "Tactical balaclava-style lower-face mask in black, military aesthetic.",
        "attachment_mode": AttachmentModeEnum.REMOVABLE,
        "placement": PlacementEnum.LOWER_FACE,
        "prompt_token": "black tactical lower-face mask, balaclava style covering nose and mouth, military aesthetic",
        "sort_order": 20,
        "spec_patch_json": None,
    },
    {
        "shop_type": ShopTypeEnum.MASK,
        "name": "Black Urban Phantom Mask",
        "slug": "mask-black-urban-phantom",
        "description": "Sleek black urban phantom mask covering the full face, eyes visible.",
        "attachment_mode": AttachmentModeEnum.REMOVABLE,
        "placement": PlacementEnum.FACE,
        "prompt_token": "black urban phantom face mask, sleek smooth surface, eyes visible through cutouts",
        "sort_order": 30,
        "spec_patch_json": None,
    },
    # ── Jewellery Store ──────────────────────────────────────────────────
    {
        "shop_type": ShopTypeEnum.JEWELLERY,
        "name": "Silver Chain",
        "slug": "jewellery-silver-chain",
        "description": "Classic silver chain necklace, medium weight and length.",
        "attachment_mode": AttachmentModeEnum.REMOVABLE,
        "placement": PlacementEnum.NECK,
        "prompt_token": "silver chain necklace, medium-weight links, resting on collarbone",
        "sort_order": 10,
        "spec_patch_json": None,
    },
    {
        "shop_type": ShopTypeEnum.JEWELLERY,
        "name": "Black Signet Ring",
        "slug": "jewellery-black-signet-ring",
        "description": "Black signet ring, bold and minimal, worn on the right hand.",
        "attachment_mode": AttachmentModeEnum.REMOVABLE,
        "placement": PlacementEnum.HAND,
        "prompt_token": "black signet ring on right hand, bold minimal design, dark metal",
        "sort_order": 20,
        "spec_patch_json": None,
    },
    {
        "shop_type": ShopTypeEnum.JEWELLERY,
        "name": "Cross Necklace",
        "slug": "jewellery-cross-necklace",
        "description": "Simple silver cross necklace on a thin chain.",
        "attachment_mode": AttachmentModeEnum.REMOVABLE,
        "placement": PlacementEnum.NECK,
        "prompt_token": "silver cross necklace, thin chain, plain cross pendant resting on chest",
        "sort_order": 30,
        "spec_patch_json": None,
    },
    # ── Weapon Store ─────────────────────────────────────────────────────
    {
        "shop_type": ShopTypeEnum.WEAPON,
        "name": "Black Handgun",
        "slug": "weapon-black-handgun",
        "description": "Matte black semi-automatic handgun, modern design.",
        "attachment_mode": AttachmentModeEnum.REMOVABLE,
        "placement": PlacementEnum.HAND,
        "prompt_token": "holding a matte black semi-automatic handgun, modern tactical design",
        "sort_order": 10,
        "spec_patch_json": None,
    },
    {
        "shop_type": ShopTypeEnum.WEAPON,
        "name": "Silver Revolver",
        "slug": "weapon-silver-revolver",
        "description": "Classic silver revolver with polished finish.",
        "attachment_mode": AttachmentModeEnum.REMOVABLE,
        "placement": PlacementEnum.HAND,
        "prompt_token": "holding a silver revolver, polished chrome finish, classic western design",
        "sort_order": 20,
        "spec_patch_json": None,
    },
    {
        "shop_type": ShopTypeEnum.WEAPON,
        "name": "Combat Knife",
        "slug": "weapon-combat-knife",
        "description": "Military-style combat knife with black serrated blade.",
        "attachment_mode": AttachmentModeEnum.REMOVABLE,
        "placement": PlacementEnum.HAND,
        "prompt_token": "holding a combat knife, black serrated blade, military tactical design",
        "sort_order": 30,
        "spec_patch_json": None,
    },
    {
        "shop_type": ShopTypeEnum.WEAPON,
        "name": "Katana",
        "slug": "weapon-katana",
        "description": "Traditional Japanese katana with black wrapped handle.",
        "attachment_mode": AttachmentModeEnum.REMOVABLE,
        "placement": PlacementEnum.HAND,
        "prompt_token": "holding a katana, traditional Japanese sword, black wrapped tsuka handle, long curved blade",
        "sort_order": 40,
        "spec_patch_json": None,
    },
]


def seed_style_presets(db: Session) -> None:
    """Insert style presets if they do not already exist (idempotent by slug)."""
    try:
        existing_slugs = {row[0] for row in db.query(StylePreset.slug).all()}
    except Exception as exc:
        logger.warning("STYLE-SHOPS-DIAG seed_skipped reason=table_missing error=%r", str(exc))
        return
    inserted = 0
    for data in _PRESETS:
        if data["slug"] in existing_slugs:
            continue
        preset = StylePreset(**data)
        db.add(preset)
        inserted += 1
    if inserted:
        db.commit()
        logger.info("STYLE-SHOPS-DIAG seed_complete inserted=%d total=%d", inserted, len(_PRESETS))
    else:
        logger.info("STYLE-SHOPS-DIAG seed_skipped reason=already_seeded total=%d", len(existing_slugs))
