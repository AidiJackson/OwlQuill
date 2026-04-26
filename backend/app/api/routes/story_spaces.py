"""Story Spaces API routes — Stages 2-4: spaces, channels, posts, publish."""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.character import Character
from app.models.story_space import (
    PublishedStory,
    PublishedStorySegment,
    StorySpace,
    StorySpaceChannel,
    StorySpaceMember,
    StorySpacePost,
)
from app.models.user import User
from app.schemas.story_space import (
    ChannelRead,
    InviteRequest,
    MemberRead,
    PublishRequest,
    PublishedSegmentRead,
    PublishedStoryRead,
    SpaceCreate,
    SpaceListItem,
    SpaceRead,
    StorySpacePostCreate,
    StorySpacePostRead,
)

router = APIRouter()


# ── membership guard ──────────────────────────────────────────────────────────

def get_space_member(
    space_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StorySpaceMember:
    """Return the caller's membership row.

    Returns 404 — not 403 — so non-members cannot confirm the space exists.
    """
    member = (
        db.query(StorySpaceMember)
        .filter(
            StorySpaceMember.space_id == space_id,
            StorySpaceMember.user_id == current_user.id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return member


# ── response builders ─────────────────────────────────────────────────────────

def _to_channel_read(ch: StorySpaceChannel) -> ChannelRead:
    return ChannelRead(id=ch.id, channel_type=ch.channel_type, name=ch.name, position=ch.position)


def _to_list_item(space: StorySpace, member: StorySpaceMember, member_count: int) -> SpaceListItem:
    return SpaceListItem(
        id=space.id,
        owner_id=space.owner_id,
        name=space.name,
        slug=space.slug,
        description=space.description,
        cover_url=space.cover_url,
        your_role=member.role,
        member_count=member_count,
        created_at=space.created_at,
        updated_at=space.updated_at,
    )


def _to_read(space: StorySpace, member: StorySpaceMember, member_count: int) -> SpaceRead:
    return SpaceRead(
        id=space.id,
        owner_id=space.owner_id,
        name=space.name,
        slug=space.slug,
        description=space.description,
        cover_url=space.cover_url,
        your_role=member.role,
        member_count=member_count,
        channels=[_to_channel_read(ch) for ch in sorted(space.channels, key=lambda c: c.position)],
        created_at=space.created_at,
        updated_at=space.updated_at,
    )


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=SpaceRead, status_code=status.HTTP_201_CREATED)
def create_space(
    data: SpaceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SpaceRead:
    """Create a Story Space. Auto-creates story/chat/planning channels in the same transaction."""
    now = datetime.utcnow()
    space = StorySpace(
        owner_id=current_user.id,
        name=data.name,
        slug=data.slug,
        description=data.description,
        cover_url=data.cover_url,
        created_at=now,
        updated_at=now,
    )
    db.add(space)
    db.flush()  # populate space.id before channel inserts

    for position, (channel_type, display_name) in enumerate(
        [("story", "Story"), ("chat", "Chat"), ("planning", "Planning")]
    ):
        db.add(StorySpaceChannel(
            space_id=space.id,
            channel_type=channel_type,
            name=display_name,
            position=position,
            created_at=now,
        ))

    membership = StorySpaceMember(
        space_id=space.id,
        user_id=current_user.id,
        role="owner",
        joined_at=now,
    )
    db.add(membership)
    db.commit()
    db.refresh(space)

    return _to_read(space, membership, member_count=1)


@router.get("/", response_model=List[SpaceListItem])
def list_my_spaces(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[SpaceListItem]:
    """List all Story Spaces the current user is a member of."""
    memberships = (
        db.query(StorySpaceMember)
        .filter(StorySpaceMember.user_id == current_user.id)
        .all()
    )
    result = []
    for m in memberships:
        space = db.query(StorySpace).filter(StorySpace.id == m.space_id).first()
        if not space:
            continue
        count = db.query(StorySpaceMember).filter(StorySpaceMember.space_id == space.id).count()
        result.append(_to_list_item(space, m, count))
    return result


@router.get("/{space_id}", response_model=SpaceRead)
def get_space(
    space_id: int,
    member: StorySpaceMember = Depends(get_space_member),
    db: Session = Depends(get_db),
) -> SpaceRead:
    """Get Story Space detail. Non-members and unauthenticated callers receive 404 / 403."""
    space = db.query(StorySpace).filter(StorySpace.id == space_id).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    count = db.query(StorySpaceMember).filter(StorySpaceMember.space_id == space_id).count()
    return _to_read(space, member, count)


@router.post("/{space_id}/invites", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
def invite_member(
    space_id: int,
    body: InviteRequest,
    member: StorySpaceMember = Depends(get_space_member),
    db: Session = Depends(get_db),
) -> MemberRead:
    """Invite a user by username. Added directly — no accept flow in v1. Any member can invite."""
    target = db.query(User).filter(User.username == body.username).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    existing = (
        db.query(StorySpaceMember)
        .filter(
            StorySpaceMember.space_id == space_id,
            StorySpaceMember.user_id == target.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a member")

    new_member = StorySpaceMember(
        space_id=space_id,
        user_id=target.id,
        role="member",
        invited_by_id=member.user_id,
        joined_at=datetime.utcnow(),
    )
    db.add(new_member)
    db.commit()
    db.refresh(new_member)

    return MemberRead(
        id=new_member.id,
        space_id=new_member.space_id,
        user_id=new_member.user_id,
        username=target.username,
        role=new_member.role,
        joined_at=new_member.joined_at,
    )


@router.delete("/{space_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    space_id: int,
    user_id: int,
    current_member: StorySpaceMember = Depends(get_space_member),
    db: Session = Depends(get_db),
) -> None:
    """Leave (self) or remove another member (owner only). The owner row cannot be removed."""
    target = (
        db.query(StorySpaceMember)
        .filter(
            StorySpaceMember.space_id == space_id,
            StorySpaceMember.user_id == user_id,
        )
        .first()
    )
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    if target.role == "owner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The owner cannot be removed",
        )

    if user_id != current_member.user_id and current_member.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can remove other members",
        )

    db.delete(target)
    db.commit()


@router.get("/{space_id}/channels", response_model=List[ChannelRead])
def list_channels(
    space_id: int,
    member: StorySpaceMember = Depends(get_space_member),
    db: Session = Depends(get_db),
) -> List[ChannelRead]:
    """List channels for a Story Space. Non-members receive 404."""
    channels = (
        db.query(StorySpaceChannel)
        .filter(StorySpaceChannel.space_id == space_id)
        .order_by(StorySpaceChannel.position)
        .all()
    )
    return [_to_channel_read(ch) for ch in channels]


def _to_post_read(post: StorySpacePost) -> StorySpacePostRead:
    character_name = None
    character_avatar_url = None
    if post.character:
        character_name = post.character.name
        character_avatar_url = post.character.avatar_url
    return StorySpacePostRead(
        id=post.id,
        space_id=post.space_id,
        channel_id=post.channel_id,
        author_user_id=post.author_user_id,
        author_username=post.author.username,
        character_id=post.character_id,
        character_name=character_name,
        character_avatar_url=character_avatar_url,
        content=post.content,
        content_type=post.content_type,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


@router.post(
    "/{space_id}/channels/{channel_id}/posts",
    response_model=StorySpacePostRead,
    status_code=status.HTTP_201_CREATED,
)
def create_post(
    space_id: int,
    channel_id: int,
    body: StorySpacePostCreate,
    member: StorySpaceMember = Depends(get_space_member),
    db: Session = Depends(get_db),
) -> StorySpacePostRead:
    """Post to a channel. Caller must be a space member; channel must belong to this space."""
    channel = db.query(StorySpaceChannel).filter(StorySpaceChannel.id == channel_id).first()
    if not channel or channel.space_id != space_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    if body.character_id is not None:
        character = db.query(Character).filter(Character.id == body.character_id).first()
        if not character or character.owner_id != member.user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Character not owned by you")

    now = datetime.utcnow()
    post = StorySpacePost(
        space_id=space_id,
        channel_id=channel_id,
        author_user_id=member.user_id,
        character_id=body.character_id,
        content=body.content,
        content_type=body.content_type,
        created_at=now,
        updated_at=now,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return _to_post_read(post)


@router.get(
    "/{space_id}/channels/{channel_id}/posts",
    response_model=List[StorySpacePostRead],
)
def list_posts(
    space_id: int,
    channel_id: int,
    member: StorySpaceMember = Depends(get_space_member),
    db: Session = Depends(get_db),
) -> List[StorySpacePostRead]:
    """List posts for a channel in ascending created_at order. Non-members receive 404."""
    channel = db.query(StorySpaceChannel).filter(StorySpaceChannel.id == channel_id).first()
    if not channel or channel.space_id != space_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    posts = (
        db.query(StorySpacePost)
        .filter(StorySpacePost.channel_id == channel_id)
        .order_by(StorySpacePost.created_at.asc())
        .all()
    )
    return [_to_post_read(p) for p in posts]


# ── publish ───────────────────────────────────────────────────────────────────

def _to_published_read(story: PublishedStory) -> PublishedStoryRead:
    segs = sorted(story.segments, key=lambda s: s.position)
    return PublishedStoryRead(
        id=story.id,
        publisher_user_id=story.publisher_user_id,
        title=story.title,
        summary=story.summary,
        cover_url=story.cover_url,
        visibility=story.visibility,
        segment_count=len(segs),
        segments=[
            PublishedSegmentRead(
                id=s.id,
                position=s.position,
                content=s.content,
                content_type=s.content_type,
                character_id=s.character_id,
                character_name_snap=s.character_name_snap,
            )
            for s in segs
        ],
        published_at=story.published_at,
        created_at=story.created_at,
        updated_at=story.updated_at,
    )


@router.post("/{space_id}/publish", response_model=PublishedStoryRead, status_code=status.HTTP_201_CREATED)
def publish_story(
    space_id: int,
    body: PublishRequest,
    member: StorySpaceMember = Depends(get_space_member),
    db: Session = Depends(get_db),
) -> PublishedStoryRead:
    """Publish selected story-channel posts as a snapshot. Only 'story' channel posts allowed."""
    if not body.post_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="post_ids must not be empty")

    if len(body.post_ids) != len(set(body.post_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="post_ids contains duplicates")

    selected: List[StorySpacePost] = []
    for pid in body.post_ids:
        post = db.query(StorySpacePost).filter(StorySpacePost.id == pid).first()
        if not post or post.space_id != space_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Post {pid} not found in this space")
        channel = db.query(StorySpaceChannel).filter(StorySpaceChannel.id == post.channel_id).first()
        if not channel or channel.channel_type != "story":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Post {pid} is not from a story channel")
        selected.append(post)

    now = datetime.utcnow()
    published = PublishedStory(
        publisher_user_id=member.user_id,
        title=body.title,
        summary=body.summary,
        cover_url=body.cover_url,
        visibility="public",
        published_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(published)
    db.flush()

    for position, post in enumerate(selected, start=1):
        char_name_snap = post.character.name if post.character else None
        db.add(PublishedStorySegment(
            published_story_id=published.id,
            source_post_id=post.id,
            position=position,
            content=post.content,
            character_id=post.character_id,
            character_name_snap=char_name_snap,
            content_type=post.content_type,
            created_at=now,
        ))

    db.commit()
    db.refresh(published)
    return _to_published_read(published)


# ── published stories (separate prefix) ──────────────────────────────────────

published_router = APIRouter()


@published_router.get("/{published_story_id}", response_model=PublishedStoryRead)
def get_published_story(
    published_story_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PublishedStoryRead:
    """Fetch a published story by ID. Auth required; space_id and source_post_id never exposed."""
    story = db.query(PublishedStory).filter(PublishedStory.id == published_story_id).first()
    if not story:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _to_published_read(story)
