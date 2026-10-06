"""Post routes."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.admin_seed import auto_join_commons
from app.models.user import User
from app.models.post import Post as PostModel
from app.models.realm import Realm as RealmModel, RealmMembership as RealmMembershipModel
from app.models.character import Character as CharacterModel
from app.models.character_image import (
    POST_ATTACHABLE_IMAGE_KINDS,
    CharacterImage,
    ImageStatusEnum,
)
from app.models.user_image import UserImage
from app.models.post_character_tag import PostCharacterTag
from app.models.post_mention import PostMention as PostMentionModel
from app.schemas.post import Post, PostCreate
from app.services.character_tags import validate_tag_targets
from app.services.composition import link_commit
from app.services.mentions import parse_mention_texts, resolve_mentions
from app.services.notifications import delete_post_notifications, notify_character_tagged
from app.services.provenance import decide_provenance
from app.services.safety import blocked_user_ids
from app.services.visibility import user_can_access_realm
from app.models.authorship import AUTHOR_KIND_CHARACTER
from app.services.seeding import serialize_post_for_viewer, serialize_posts_for_viewer

router = APIRouter()


@router.get("/feed", response_model=List[Post])
def get_feed(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Post]:
    """Get feed of posts from realms the user is a member of."""
    # Fallback: ensure user is a member of The Commons
    auto_join_commons(current_user.id, db)

    # Get all realm IDs where user is a member
    memberships = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.user_id == current_user.id
    ).all()

    realm_ids = [m.realm_id for m in memberships]

    if not realm_ids:
        return []

    # Get posts from those realms, eager-load author and character identity
    posts_q = db.query(PostModel).options(
        selectinload(PostModel.author_user),
        selectinload(PostModel.character),
    ).filter(
        PostModel.realm_id.in_(realm_ids)
    )

    # Exclude posts from blocked users (bidirectional)
    blocked = blocked_user_ids(db, current_user.id)
    if blocked:
        posts_q = posts_q.filter(PostModel.author_user_id.notin_(blocked))

    posts = posts_q.order_by(PostModel.created_at.desc()).offset(skip).limit(limit).all()
    return serialize_posts_for_viewer(posts, current_user, db)


@router.post("/realms/{realm_id}/posts", response_model=Post, status_code=status.HTTP_201_CREATED)
def create_post_in_realm(
    realm_id: int,
    post_data: PostCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Post:
    """Create a post in a realm."""
    # Check if user is a member of the realm
    membership = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.realm_id == realm_id,
        RealmMembershipModel.user_id == current_user.id
    ).first()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a member of this realm to post"
        )

    # Character-first identity (Sprint 33): every post is authored BY a
    # character — the account is private infrastructure and never a public
    # author. Requiring the character here also closes the arbitrary-attribution
    # hole (any character_id used to be accepted unchecked).
    if not post_data.character_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Create a character to start posting — posts are authored by characters.",
        )
    author_char = db.query(CharacterModel).filter(
        CharacterModel.id == post_data.character_id,
        CharacterModel.owner_id == current_user.id,
    ).first()
    if not author_char:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only post as your own character.",
        )

    # Enforce image attachment rules. Account ownership alone is not enough: a
    # post is authored by ONE character, so the image must belong to THAT
    # character. Owning Shadow does not entitle a post authored by Pan to
    # Shadow's media, and the client cannot buy its way past this by sending a
    # forged path — the acting character is taken from the verified
    # ``author_char`` above, never from the request.
    #
    # Status and kind are checked here too, so private production material
    # (identity sketches, face/body refs, anchors, accessory sheets) and
    # inactive/temp rows can never be published even if a client asks for them.
    if post_data.image_url:
        file_path = post_data.image_url.lstrip('/')
        owned_char_img = (
            db.query(CharacterImage)
            .filter(
                CharacterImage.file_path == file_path,
                CharacterImage.character_id == author_char.id,
                CharacterImage.status == ImageStatusEnum.ACTIVE,
                CharacterImage.kind.in_(POST_ATTACHABLE_IMAGE_KINDS),
            )
            .first()
        )
        # Account-level images belong to no character, so the character scope
        # above does not apply to them; they remain the poster's own media.
        owned_user_img = (
            db.query(UserImage)
            .filter(
                UserImage.file_path == file_path,
                UserImage.user_id == current_user.id,
            )
            .first()
        ) if not owned_char_img else None

        if not owned_char_img and not owned_user_img:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only attach your own character's images to a post.",
            )

    # W-10A: explicit tags are validated BEFORE anything is written, so a
    # refused target fails the whole request with no post created. The schema
    # has already de-duplicated and capped the ids; this is the authority on
    # whether each one may be tagged.
    tag_targets = validate_tag_targets(db, post_data.tagged_character_ids, author_char)

    # Provenance is decided here, from server-held evidence, and is the only
    # thing that drives the public badge. Nothing in ``post_data`` can influence
    # it — note the explicit field list rather than the ``**model_dump()`` splat
    # that previously let a client name its own ``source_type``.
    decision = decide_provenance(
        db,
        user_id=current_user.id,
        content=post_data.content,
        composition_session_id=post_data.composition_session_id,
    )

    db_post = PostModel(
        realm_id=realm_id,
        author_user_id=current_user.id,
        character_id=post_data.character_id,
        title=post_data.title,
        content=post_data.content,
        content_type=post_data.content_type,
        post_kind=post_data.post_kind,
        image_url=post_data.image_url,
        # Every post on this path is character-authored (enforced above).
        # Recorded durably so it outlives the character — see
        # app.models.authorship.
        author_kind=AUTHOR_KIND_CHARACTER,
    )
    db_post.apply_provenance(decision)
    db.add(db_post)
    db.flush()
    link_commit(db, decision.session, kind="post", obj_id=db_post.id)

    # Everything below is staged in the SAME transaction as the post and
    # committed once at the end: the post, its tags, the tag notifications and
    # the legacy mention rows land together or not at all.

    # W-10A: explicit character tags — the only path that notifies another
    # character's owner. One row and at most one notification per (post,
    # tagged character); the schema de-duplicated the ids.
    realm = None
    # The product's one definition of "in a block relationship", both
    # directions — the same set the feed, comments and messaging consult.
    blocked_with_author = blocked_user_ids(db, current_user.id) if tag_targets else set()
    for target in tag_targets:
        db.add(PostCharacterTag(post_id=db_post.id, character_id=target.id))
        if target.owner_id == current_user.id:
            continue  # the author's own other character: tagged, not notified
        # A block (either direction) leaves the tag stored but inert — see
        # app.services.character_tags. Nothing in the response differs.
        if target.owner_id in blocked_with_author:
            continue
        if realm is None:
            realm = db.query(RealmModel).filter(RealmModel.id == realm_id).first()
        notify_character_tagged(
            db,
            recipient_user_id=target.owner_id,
            post=db_post,
            realm=realm,
            author_character=author_char,
            tagged_character=target,
        )

    # LEGACY typed @mentions: still parsed, resolved (PUBLIC characters only)
    # and stored, so existing prose keeps its links and the Tagged surface keeps
    # its history. They NO LONGER NOTIFY (W-10A): the ASCII prefix parser can
    # address the wrong character ("@Leo Vance" -> "Leo", "@Zoë" -> "Zo").
    for r in resolve_mentions(parse_mention_texts(post_data.content), db):
        db.add(PostMentionModel(
            post_id=db_post.id,
            mention_text=r["mention_text"],
            mentioned_user_id=r.get("mentioned_user_id"),
            mentioned_character_id=r.get("mentioned_character_id"),
        ))

    db.commit()
    db.refresh(db_post)
    # Serialised like every other read so the author receives the same
    # tagged_characters projection they will see on reload.
    return serialize_post_for_viewer(db_post, current_user, db)


@router.get("/realms/{realm_id}/posts", response_model=List[Post])
def list_realm_posts(
    realm_id: int,
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Post]:
    """List posts in a realm.

    S24F: requires authentication and enforces the realm visibility rule (is_public
    OR caller is owner/member). A private realm the caller is not in returns 404, so
    its posts cannot be enumerated by a non-member.
    """
    realm = db.query(RealmModel).filter(RealmModel.id == realm_id).first()
    if realm is None or not user_can_access_realm(db, current_user.id, realm):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Realm not found")

    posts = db.query(PostModel).options(
        selectinload(PostModel.author_user),
        selectinload(PostModel.character),
    ).filter(
        PostModel.realm_id == realm_id
    ).order_by(PostModel.created_at.desc()).offset(skip).limit(limit).all()
    return serialize_posts_for_viewer(posts, current_user, db)


@router.get("/{post_id}", response_model=Post)
def get_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Post:
    """Get a single post.

    S24E FIX A: requires authentication and enforces post visibility via realm
    access, mirroring the realm visibility rule (is_public). A post is returned
    only when its realm is public or the caller is a member/owner of that realm;
    a post in a private realm the caller is not in returns 404.
    """
    post = db.query(PostModel).options(
        selectinload(PostModel.author_user),
        selectinload(PostModel.character),
    ).filter(PostModel.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    realm = db.query(RealmModel).filter(RealmModel.id == post.realm_id).first()
    if realm is not None and not realm.is_public and realm.owner_id != current_user.id:
        is_member = db.query(RealmMembershipModel).filter(
            RealmMembershipModel.realm_id == realm.id,
            RealmMembershipModel.user_id == current_user.id,
        ).first() is not None
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Post not found"
            )
    return serialize_post_for_viewer(post, current_user, db)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """Delete a post."""
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    is_admin = current_user.email.lower() in settings.get_admin_emails()
    if post.author_user_id != current_user.id and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this post"
        )

    # Comments, reactions, post_mentions and post_character_tags cascade with
    # the row. Post notifications (legacy mention, character_tagged) are not
    # FK-linked (their payload is a JSON snapshot that may carry a preview of
    # the post body), so they are removed explicitly, in the same transaction,
    # or the deleted text would outlive the post.
    delete_post_notifications(db, post.id)
    db.delete(post)
    db.commit()


@router.delete("/{post_id}/tags/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_post_tag(
    post_id: int,
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Remove one character's tag from a post (W-10A).

    Allowed for exactly two accounts: the tagged CHARACTER's owner, and the
    post's author (who added it). Everyone else — and every request naming a
    tag that does not exist — receives the same 404, so this route confirms
    neither a post, nor a tag, nor anything about a post the caller cannot
    read. The tagged owner may remove the tag even from a post in a realm they
    cannot open: it is their character's association, and the 404/204 answer
    discloses nothing about the post's content.

    Removes the durable association and the matching ``character_tagged``
    notification if it still exists. The post's prose and any legacy
    ``post_mentions`` row are untouched.
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    tag = (
        db.query(PostCharacterTag)
        .filter(
            PostCharacterTag.post_id == post_id,
            PostCharacterTag.character_id == character_id,
        )
        .first()
    )
    if tag is None:
        raise not_found
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    character = tag.character
    is_tagged_owner = character is not None and character.owner_id == current_user.id
    is_post_author = post is not None and post.author_user_id == current_user.id
    if not (is_tagged_owner or is_post_author):
        raise not_found

    delete_post_notifications(db, post_id, tagged_character_id=character_id)
    db.delete(tag)
    db.commit()
