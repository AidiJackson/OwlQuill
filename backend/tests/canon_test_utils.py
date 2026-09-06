"""Shared test utilities for the CharacterIdentityCanon generation contract.

Not a test module (no test_ prefix) — imported by the route-level test files
that were migrated from the legacy identity_anchor_json contract to canon.
"""


def stub_png_bytes() -> bytes:
    """Raw PNG bytes for mock provider returns.

    Phase 4D3-3: rendered directly. This used to render, store, and load the
    bytes back through ``generate_placeholder_png`` — a round trip through
    storage for something that was only ever wanted as bytes, and the reason
    this helper needed local storage mode at all.
    """
    from app.services.stub_image_generator import render_placeholder_png
    return render_placeholder_png(label="test", sublabel="stub")


def stub_image_url(label: str = "ref") -> str:
    """Create a real local stub PNG and return a loadable /static URL.

    Still stores, because the point of this one is a url a route can load. Uses
    the low-level object writer directly: it is a test fixture standing in for
    material some earlier flow produced, not a durable asset the application is
    creating, so it deliberately does not go through the canonical primitive.
    """
    from app.core.storage import mint_object_key, put_object
    from app.services.stub_image_generator import render_placeholder_png

    content = render_placeholder_png(label=label, role="anchor_front")
    stored = put_object(content, key=mint_object_key(content))
    return f"/{stored.file_path}"


def setup_canon(
    db_session,
    cid: int,
    *,
    marks: list[dict] | None = None,
    accessories: list[dict] | None = None,
    lock: bool = True,
    with_images: bool = True,
):
    """Build a populated CharacterIdentityCanon (the only identity-truth source).

    No identity_anchor_json / body_identity_json / style elements. Commits so the
    generation route (a separate DB session) sees the data.
    """
    from app.services import canon_service as cs
    from app.schemas.canon import (
        FaceCanonData, BodyCanonData, AddPermanentMarkRequest, AddAccessoryRequest,
    )

    canon = cs.get_or_create_canon(cid, db_session)
    face = cs.load_face_canon(canon) or FaceCanonData()
    body = cs.load_body_canon(canon) or BodyCanonData()

    face.face_description = "sharp angular jaw, dark brown eyes, olive skin"
    body.body_description = "athletic build, medium height"
    body.build = "athletic"
    if with_images:
        face.face_front_image_url = stub_image_url("face_front")
        body.body_front_image_url = stub_image_url("body_front")
    if lock:
        face.locked = True
        body.locked = True

    cs._save_face(canon, face)
    cs._save_body(canon, body)

    for m in (marks or []):
        cs.add_permanent_mark(canon, AddPermanentMarkRequest(**m))
    for a in (accessories or []):
        cs.add_accessory(canon, AddAccessoryRequest(**a))

    if lock and with_images:
        canon.face_locked = True
        canon.body_locked = True

    db_session.commit()
    return canon
