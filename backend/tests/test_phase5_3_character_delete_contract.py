"""Phase 5.3 — the deletion consequences the confirmation dialog now states.

The owner-facing delete copy (PD-8) promises four things about what survives
a character. Three of them were already pinned elsewhere:

  * images are KEPT, association dropped   → test_optional_character_association
  * active character selection is cleared  → test_identity_first
  * the cooldown, and who is exempt        → test_characters

The fourth — every conversation the character was in is removed, messages
included, for the OTHER character too — was enforced only by ``ON DELETE
CASCADE`` on ``conversations`` / ``messages`` with no ORM relationship and no
test, so nothing would have noticed if the cascade were dropped. This file
pins it, plus the "posts and comments stay up without the name" line, on an
engine that actually enforces foreign keys (the shared fixture does not).

No routes, no providers: this is the database contract the copy describes.
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.character import Character
from app.models.comment import Comment
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.post import Post
from app.models.user import User


@pytest.fixture()
def fk_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'delete_contract.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def two_characters_talking(fk_session):
    """Two owners, one character each, one conversation with a message from each side."""
    db = fk_session
    owner_a = User(email="a@test.local", username="owner_a", hashed_password="x")
    owner_b = User(email="b@test.local", username="owner_b", hashed_password="x")
    db.add_all([owner_a, owner_b])
    db.flush()
    char_a = Character(owner_id=owner_a.id, name="Doomed")
    char_b = Character(owner_id=owner_b.id, name="Bystander")
    db.add_all([char_a, char_b])
    db.flush()
    convo = Conversation(character_a_id=char_a.id, character_b_id=char_b.id)
    db.add(convo)
    db.flush()
    db.add_all([
        Message(conversation_id=convo.id, sender_character_id=char_a.id, body="hello"),
        Message(conversation_id=convo.id, sender_character_id=char_b.id, body="hi back"),
    ])
    db.commit()
    return db, owner_a, owner_b, char_a, char_b, convo


def test_deleting_a_character_removes_the_shared_conversation_and_every_message(
    two_characters_talking,
):
    db, _a, _b, char_a, char_b, convo = two_characters_talking
    convo_id, b_id = convo.id, char_b.id

    # Exactly what the route does: ORM delete, then commit.
    db.delete(db.get(Character, char_a.id))
    db.commit()
    db.expire_all()

    # The conversation is gone — and so it is gone for the OTHER character.
    assert db.get(Conversation, convo_id) is None
    assert db.query(Conversation).filter(
        (Conversation.character_a_id == b_id) | (Conversation.character_b_id == b_id)
    ).count() == 0
    # Both sides' messages went with it, not only the deleted character's own.
    assert db.query(Message).filter(Message.conversation_id == convo_id).count() == 0
    # The other character is untouched.
    assert db.get(Character, b_id) is not None


def test_deleting_a_character_keeps_posts_and_comments_but_detaches_the_name(fk_session):
    db = fk_session
    owner = User(email="p@test.local", username="poster", hashed_password="x")
    db.add(owner)
    db.flush()
    char = Character(owner_id=owner.id, name="Doomed")
    db.add(char)
    db.flush()
    post = Post(author_user_id=owner.id, character_id=char.id, content="as the character")
    db.add(post)
    db.flush()
    comment = Comment(post_id=post.id, author_user_id=owner.id, character_id=char.id, content="also")
    db.add(comment)
    db.commit()
    post_id, comment_id = post.id, comment.id

    db.delete(db.get(Character, char.id))
    db.commit()
    db.expire_all()

    kept_post = db.get(Post, post_id)
    kept_comment = db.get(Comment, comment_id)
    # "stay up" — the rows survive, still authored by the account…
    assert kept_post is not None and kept_post.author_user_id == owner.id
    assert kept_comment is not None and kept_comment.author_user_id == owner.id
    # …"but no longer carry their name" — the character link is cleared.
    assert kept_post.character_id is None
    assert kept_comment.character_id is None
