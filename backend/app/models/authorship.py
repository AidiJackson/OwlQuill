"""Durable authorship provenance for posts and comments (``author_kind``).

WHY A COLUMN AND NOT ``character_id``. "Was this written as a character?" used
to be answered by ``character_id IS NOT NULL``. That stops being true the
moment a character is deleted: ``posts.character_id`` and
``comments.character_id`` are ``ON DELETE SET NULL``, so a Writer's character
content became indistinguishable from the two kinds of row that legitimately
carry the account username — a legacy account-authored post, and a Wanderer's
comment — and the serializers published the Writer's private username.

``author_kind`` is written ONCE, at creation, and nothing ever clears it, so it
survives the character. It is the authoritative answer; ``character_id`` only
says whether the character still exists.

VALUES

* ``character``       — posts and comments: written as a character.
* ``account_legacy``  — posts only: account-attributed compatibility content.
  No user-facing path writes it; the starter seed's editorial posts do, and
  historical rows may be classified to it deliberately — never inferred.
* ``wanderer``        — comments only: a characterless Wanderer comment, whose
  public identity IS the Wanderer username.
* ``NULL``            — UNKNOWN. Historical characterless rows the migration
  (``ak01_author_kind``) could not classify without guessing. Treated exactly
  like ``character`` for privacy: account identity is never shown to another
  viewer.

The rule the serializers apply (``app.services.seeding``): a non-author sees
account identity ONLY for ``account_legacy`` posts and ``wanderer`` comments.
Anything else — including NULL — withholds it.
"""

AUTHOR_KIND_CHARACTER = "character"
POST_AUTHOR_KIND_ACCOUNT_LEGACY = "account_legacy"
COMMENT_AUTHOR_KIND_WANDERER = "wanderer"

#: Post kinds whose account identity a non-author may see.
POST_ACCOUNT_ATTRIBUTED_KINDS = frozenset({POST_AUTHOR_KIND_ACCOUNT_LEGACY})
#: Comment kinds whose account identity a non-author may see.
COMMENT_ACCOUNT_ATTRIBUTED_KINDS = frozenset({COMMENT_AUTHOR_KIND_WANDERER})
