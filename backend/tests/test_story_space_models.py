"""DB-layer tests for Story Spaces models (Stage 1).

No HTTP, no routes — exercises SQLAlchemy models and constraints directly
against the in-memory test database created by the conftest fixtures.
"""
import pytest
from datetime import datetime
from sqlalchemy.exc import IntegrityError

from app.models.story_space import (
    StorySpace,
    StorySpaceMember,
    StorySpaceChannel,
    StorySpacePost,
    PublishedStory,
    PublishedStorySegment,
    ChannelTypeEnum,
)
from app.models.user import User


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_user(db, suffix: str = "") -> User:
    u = User(
        email=f"user{suffix}@test.com",
        username=f"user{suffix}",
        hashed_password="x",
        display_name=f"User {suffix}",
    )
    db.add(u)
    db.flush()
    return u


def _make_space(db, owner: User, name: str = "Test Space") -> StorySpace:
    s = StorySpace(
        owner_id=owner.id,
        name=name,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(s)
    db.flush()
    return s


def _make_channel(db, space: StorySpace, channel_type: str, position: int = 0) -> StorySpaceChannel:
    c = StorySpaceChannel(
        space_id=space.id,
        channel_type=channel_type,
        name=channel_type.capitalize(),
        position=position,
        created_at=datetime.utcnow(),
    )
    db.add(c)
    db.flush()
    return c


# ── tests ─────────────────────────────────────────────────────────────────────

def test_create_space_and_owner_member(db_session):
    """Creating a space and attaching an owner membership works correctly."""
    owner = _make_user(db_session, "a")
    space = _make_space(db_session, owner)

    member = StorySpaceMember(
        space_id=space.id,
        user_id=owner.id,
        role="owner",
        joined_at=datetime.utcnow(),
    )
    db_session.add(member)
    db_session.commit()

    fetched = db_session.query(StorySpace).filter_by(id=space.id).one()
    assert fetched.owner_id == owner.id
    assert len(fetched.members) == 1
    assert fetched.members[0].role == "owner"
    assert fetched.members[0].user_id == owner.id


def test_space_member_unique_constraint(db_session):
    """Inserting the same user as member twice raises IntegrityError."""
    owner = _make_user(db_session, "b")
    space = _make_space(db_session, owner)

    db_session.add(StorySpaceMember(space_id=space.id, user_id=owner.id, role="owner", joined_at=datetime.utcnow()))
    db_session.commit()

    db_session.add(StorySpaceMember(space_id=space.id, user_id=owner.id, role="member", joined_at=datetime.utcnow()))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_channel_unique_constraint_per_space(db_session):
    """Two channels with the same space_id + channel_type raises IntegrityError."""
    owner = _make_user(db_session, "c")
    space = _make_space(db_session, owner)

    _make_channel(db_session, space, "story", position=0)
    db_session.commit()

    # The constraint fires at flush (inside _make_channel) not at commit
    with pytest.raises(IntegrityError):
        _make_channel(db_session, space, "story", position=1)


def test_channel_types_are_distinct_per_space(db_session):
    """Three different channel types can coexist in a single space."""
    owner = _make_user(db_session, "d")
    space = _make_space(db_session, owner)

    for i, ct in enumerate(["story", "chat", "planning"]):
        _make_channel(db_session, space, ct, position=i)
    db_session.commit()

    channels = (
        db_session.query(StorySpaceChannel)
        .filter_by(space_id=space.id)
        .order_by(StorySpaceChannel.position)
        .all()
    )
    assert [c.channel_type for c in channels] == ["story", "chat", "planning"]


def test_channel_type_uniqueness_is_per_space_not_global(db_session):
    """Two different spaces can each have a 'story' channel (uniqueness is scoped)."""
    owner = _make_user(db_session, "e")
    space1 = _make_space(db_session, owner, name="Space One")
    space2 = _make_space(db_session, owner, name="Space Two")

    _make_channel(db_session, space1, "story", position=0)
    _make_channel(db_session, space2, "story", position=0)
    db_session.commit()  # must not raise


def test_story_space_post_db_layer(db_session):
    """StorySpacePost can be inserted and related back to space + channel."""
    owner = _make_user(db_session, "f")
    space = _make_space(db_session, owner)
    channel = _make_channel(db_session, space, "story", position=0)
    db_session.commit()

    post = StorySpacePost(
        space_id=space.id,
        channel_id=channel.id,
        author_user_id=owner.id,
        content="Once upon a time...",
        content_type="ic",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(post)
    db_session.commit()

    fetched = db_session.query(StorySpacePost).filter_by(id=post.id).one()
    assert fetched.space_id == space.id
    assert fetched.channel_id == channel.id
    assert fetched.content == "Once upon a time..."


def test_published_story_and_segments(db_session):
    """PublishedStory with two ordered segments can be created and read back."""
    publisher = _make_user(db_session, "g")
    db_session.commit()

    story = PublishedStory(
        publisher_user_id=publisher.id,
        title="My First Story",
        visibility="public",
        published_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(story)
    db_session.flush()

    for pos, text in enumerate(["Part one content.", "Part two content."], start=1):
        db_session.add(PublishedStorySegment(
            published_story_id=story.id,
            position=pos,
            content=text,
            content_type="ic",
            created_at=datetime.utcnow(),
        ))
    db_session.commit()

    fetched = db_session.query(PublishedStory).filter_by(id=story.id).one()
    assert len(fetched.segments) == 2
    assert fetched.segments[0].position == 1
    assert fetched.segments[1].position == 2
    assert fetched.segments[0].content == "Part one content."


def test_published_story_segment_unique_position(db_session):
    """Two segments at the same position in the same story raises IntegrityError."""
    publisher = _make_user(db_session, "h")
    db_session.commit()

    story = PublishedStory(
        publisher_user_id=publisher.id,
        title="Collision Story",
        visibility="public",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(story)
    db_session.flush()

    db_session.add(PublishedStorySegment(
        published_story_id=story.id,
        position=1,
        content="First.",
        content_type="ic",
        created_at=datetime.utcnow(),
    ))
    db_session.commit()

    db_session.add(PublishedStorySegment(
        published_story_id=story.id,
        position=1,  # duplicate
        content="Duplicate.",
        content_type="ic",
        created_at=datetime.utcnow(),
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_space_deletion_cascades_to_members_channels_posts(db_session):
    """Deleting a StorySpace cascades to members, channels, and posts."""
    owner = _make_user(db_session, "i")
    space = _make_space(db_session, owner)
    channel = _make_channel(db_session, space, "story", position=0)
    db_session.add(StorySpaceMember(space_id=space.id, user_id=owner.id, role="owner", joined_at=datetime.utcnow()))
    db_session.add(StorySpacePost(
        space_id=space.id, channel_id=channel.id, author_user_id=owner.id,
        content="x", content_type="ic", created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    ))
    db_session.commit()

    space_id = space.id
    db_session.delete(space)
    db_session.commit()

    assert db_session.query(StorySpaceMember).filter_by(space_id=space_id).count() == 0
    assert db_session.query(StorySpaceChannel).filter_by(space_id=space_id).count() == 0
    assert db_session.query(StorySpacePost).filter_by(space_id=space_id).count() == 0


def test_published_story_space_id_is_nullable(db_session):
    """PublishedStory.space_id can be NULL (space deleted, story survives)."""
    publisher = _make_user(db_session, "j")
    db_session.commit()

    story = PublishedStory(
        publisher_user_id=publisher.id,
        title="Orphaned Story",
        space_id=None,
        visibility="public",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(story)
    db_session.commit()

    fetched = db_session.query(PublishedStory).filter_by(id=story.id).one()
    assert fetched.space_id is None


def test_source_post_id_is_nullable_on_segment(db_session):
    """PublishedStorySegment.source_post_id can be NULL (original post deleted)."""
    publisher = _make_user(db_session, "k")
    db_session.commit()

    story = PublishedStory(
        publisher_user_id=publisher.id,
        title="Detached Segments",
        visibility="public",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(story)
    db_session.flush()

    seg = PublishedStorySegment(
        published_story_id=story.id,
        source_post_id=None,
        position=1,
        content="Snapshot content.",
        content_type="ic",
        created_at=datetime.utcnow(),
    )
    db_session.add(seg)
    db_session.commit()

    fetched = db_session.query(PublishedStorySegment).filter_by(id=seg.id).one()
    assert fetched.source_post_id is None
    assert fetched.content == "Snapshot content."


def test_existing_users_table_unaffected(db_session):
    """Users table is intact after all story-space table creation (no regression)."""
    u = _make_user(db_session, "z")
    db_session.commit()
    fetched = db_session.query(User).filter_by(id=u.id).one()
    assert fetched.email == "userz@test.com"


def test_channel_type_enum_values():
    """ChannelTypeEnum has exactly the three expected values."""
    assert ChannelTypeEnum.STORY == "story"
    assert ChannelTypeEnum.CHAT == "chat"
    assert ChannelTypeEnum.PLANNING == "planning"
    assert set(ChannelTypeEnum) == {ChannelTypeEnum.STORY, ChannelTypeEnum.CHAT, ChannelTypeEnum.PLANNING}
