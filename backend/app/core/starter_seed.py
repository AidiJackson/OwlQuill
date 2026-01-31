"""Seed starter realms and posts for onboarding (idempotent)."""
import logging
import os

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.user import User
from app.models.realm import Realm as RealmModel, RealmMembership as RealmMembershipModel
from app.models.post import Post as PostModel, ContentTypeEnum

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Starter realm definitions
# ---------------------------------------------------------------------------
STARTER_REALMS = [
    {
        "slug": "crimson-academy",
        "name": "Crimson Academy",
        "tagline": "Where dark gifts are sharpened and alliances forged in firelight",
        "description": (
            "A sprawling supernatural boarding school hidden in the mountains. "
            "Students from every bloodline — witches, shifters, revenants — "
            "compete for standing while ancient rivalries simmer beneath the surface."
        ),
        "genre": "Supernatural School",
        "posts": [
            {
                "key": "welcome",
                "title": "Welcome to Crimson Academy",
                "content": (
                    "The iron gates groan open at the start of each semester, "
                    "admitting a fresh cohort of students whose abilities have "
                    "finally surfaced. Whether you wield flame, shadow, or something "
                    "the professors have never catalogued, Crimson Academy will push "
                    "you to your limits.\n\n"
                    "Post your character introductions here, plot thread ideas, "
                    "or just say hello OOC!"
                ),
                "content_type": ContentTypeEnum.OOC,
                "post_kind": "general",
            },
            {
                "key": "open-courtyard",
                "title": "The Courtyard After Curfew",
                "content": (
                    "Moonlight spills across the cobblestones of the inner courtyard. "
                    "The fountain at its center hums with a faint violet glow — residue "
                    "from last week's summoning practical that nobody bothered to clean up.\n\n"
                    "A figure sits on the rim of the fountain, boots scuffing the stone, "
                    "watching the dormitory windows go dark one by one. They weren't "
                    "supposed to be out here. Then again, rules had never stuck."
                ),
                "content_type": ContentTypeEnum.NARRATION,
                "post_kind": "open_starter",
            },
            {
                "key": "finished-letter",
                "title": "Unsent Letter (fragment)",
                "content": (
                    "I keep the letter folded inside my Wards & Bindings textbook, "
                    "page 214, between the chapter on containment circles and the one "
                    "on blood seals. It's addressed to someone who graduated three years "
                    "ago and never wrote back.\n\n"
                    "Maybe this semester I'll send it. Maybe I'll burn it instead.\n\n"
                    "The ink is starting to bleed through the page."
                ),
                "content_type": ContentTypeEnum.NARRATION,
                "post_kind": "finished_piece",
            },
        ],
    },
    {
        "slug": "neon-city-2087",
        "name": "Neon City 2087",
        "tagline": "Chrome bones, neon veins, and debts that never die",
        "description": (
            "A rain-slicked cyberpunk megacity where corporations own the skyline "
            "and everyone below the 40th floor is running a hustle. Augmented mercs, "
            "rogue hackers, and street medics carve out lives in the glow of "
            "holographic billboards."
        ),
        "genre": "Cyberpunk",
        "posts": [
            {
                "key": "welcome",
                "title": "Welcome to Neon City",
                "content": (
                    "Neon City never sleeps and it never forgives. If you're new to "
                    "the district, drop an OOC intro — tell us about your character's "
                    "hustle, their augmentations, and what part of the city they call home.\n\n"
                    "Looking for a crew? Post a plotting thread. "
                    "Looking for trouble? That finds you on its own."
                ),
                "content_type": ContentTypeEnum.OOC,
                "post_kind": "general",
            },
            {
                "key": "open-noodle-bar",
                "title": "Last Call at Mako's Noodle Bar",
                "content": (
                    "The rain hammers the corrugated awning hard enough to drown out "
                    "the lo-fi stream bleeding from the bar's cracked speakers. Mako's "
                    "is the kind of place where nobody asks your name and the broth "
                    "is hot enough to forgive anything.\n\n"
                    "A woman with a chrome-plated left arm slides onto the end stool, "
                    "sets a sealed data chip on the counter, and flags down the cook. "
                    '"Two bowls," she says. "I\'m expecting company."'
                ),
                "content_type": ContentTypeEnum.IC,
                "post_kind": "open_starter",
            },
            {
                "key": "finished-signal",
                "title": "Ghost Signal (excerpt)",
                "content": (
                    "They found the broadcast at 3:17 AM on a frequency that hadn't "
                    "been active since the Collapse. Forty-four seconds of a child's "
                    "voice reciting coordinates, then static, then a tone that made "
                    "every neural implant in a six-block radius flicker.\n\n"
                    "By morning the recording had been scrubbed from every public node. "
                    "But Ren had already copied it to a dead man's drive duct-taped "
                    "under a bridge in Sector 9."
                ),
                "content_type": ContentTypeEnum.NARRATION,
                "post_kind": "finished_piece",
            },
        ],
    },
    {
        "slug": "crossroads-tavern",
        "name": "The Crossroads Tavern",
        "tagline": "Every road leads here eventually",
        "description": (
            "A weathered fantasy tavern that exists at the intersection of every "
            "trade route, ley line, and pilgrim's path. Adventurers, merchants, and "
            "wanderers share tales over strong ale while the hearth fire never "
            "quite goes out."
        ),
        "genre": "Fantasy",
        "posts": [
            {
                "key": "welcome",
                "title": "Welcome to The Crossroads Tavern",
                "content": (
                    "Pull up a chair, order something warm, and introduce yourself. "
                    "The Crossroads Tavern is a freeform fantasy setting — "
                    "any character is welcome as long as they can walk through the door "
                    "(or climb through the window; we don't judge).\n\n"
                    "Use this space for OOC plotting, character introductions, "
                    "and finding writing partners."
                ),
                "content_type": ContentTypeEnum.OOC,
                "post_kind": "general",
            },
            {
                "key": "open-hearthside",
                "title": "A Stranger by the Hearth",
                "content": (
                    "The door swings open and the storm follows for half a heartbeat "
                    "before the wards push it back. A traveller steps inside, cloak "
                    "heavy with rain, a carved staff in one hand and a canvas-wrapped "
                    "bundle in the other.\n\n"
                    "They don't head for the bar. They choose the corner table nearest "
                    "the hearth, set the bundle down with a care that suggests it's "
                    "either very fragile or very dangerous, and wait."
                ),
                "content_type": ContentTypeEnum.NARRATION,
                "post_kind": "open_starter",
            },
            {
                "key": "finished-map",
                "title": "The Cartographer's Last Map (fragment)",
                "content": (
                    "Old Seren had mapped every road between the Thornwall Mountains "
                    "and the Dulcet Sea. Every road except one. The path that appeared "
                    "only on moonless nights, drawn in silver ink that faded by dawn.\n\n"
                    "She spent forty years chasing it. The map she left behind "
                    "shows the first three miles. After that the parchment is blank — "
                    "or burned, depending on the light."
                ),
                "content_type": ContentTypeEnum.NARRATION,
                "post_kind": "finished_piece",
            },
        ],
    },
]


def _seed_marker(slug: str, post_key: str) -> str:
    """Return the unique marker string embedded at the end of seeded post content."""
    return f"\n\n[seed:starter:{slug}:{post_key}]"


def ensure_starter_realms_and_posts() -> None:
    """Create starter realms and posts if they don't already exist.

    Idempotent: uses realm slug for realm dedup and a seed marker in post
    content for post dedup. Safe to call on every startup.
    """
    db: Session = SessionLocal()
    try:
        # --- Find an author user ---
        admin_email = os.environ.get("ADMIN_EMAIL")
        author: User | None = None
        if admin_email:
            author = db.query(User).filter(User.email == admin_email).first()
        if author is None:
            author = db.query(User).order_by(User.id).first()
        if author is None:
            logger.info("Starter seed: no users exist yet — skipping")
            return

        for realm_def in STARTER_REALMS:
            slug = realm_def["slug"]
            realm = db.query(RealmModel).filter(RealmModel.slug == slug).first()

            if realm is None:
                realm = RealmModel(
                    name=realm_def["name"],
                    slug=slug,
                    tagline=realm_def["tagline"],
                    description=realm_def["description"],
                    genre=realm_def["genre"],
                    is_public=True,
                    is_commons=False,
                    owner_id=author.id,
                )
                db.add(realm)
                db.flush()  # get realm.id
                logger.info("Starter seed: created realm '%s'", realm_def["name"])
            else:
                logger.info("Starter seed: realm '%s' already exists", realm_def["name"])

            # Ensure author membership
            membership = (
                db.query(RealmMembershipModel)
                .filter(
                    RealmMembershipModel.realm_id == realm.id,
                    RealmMembershipModel.user_id == author.id,
                )
                .first()
            )
            if membership is None:
                db.add(
                    RealmMembershipModel(
                        realm_id=realm.id,
                        user_id=author.id,
                        role="owner",
                    )
                )

            # Seed posts
            for post_def in realm_def["posts"]:
                marker = _seed_marker(slug, post_def["key"])

                exists = (
                    db.query(PostModel.id)
                    .filter(
                        PostModel.realm_id == realm.id,
                        PostModel.content.contains(marker),
                    )
                    .first()
                )
                if exists:
                    continue

                post = PostModel(
                    realm_id=realm.id,
                    author_user_id=author.id,
                    character_id=None,
                    title=post_def["title"],
                    content=post_def["content"] + marker,
                    content_type=post_def["content_type"],
                    post_kind=post_def["post_kind"],
                )
                db.add(post)
                logger.info(
                    "Starter seed: created post '%s' in '%s'",
                    post_def["title"],
                    realm_def["name"],
                )

        db.commit()
        logger.info("Starter seed: complete")
    except Exception as e:
        db.rollback()
        logger.error("Starter seed failed: %s", e)
    finally:
        db.close()
