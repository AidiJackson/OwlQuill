#!/usr/bin/env python3
"""S24AB diagnostics — dry-run canon prompt compilation + ref routing for the
controlled Pan + Summer tattoo-exposure scenarios. NO generation (no provider
calls); read-only against the canon DB.

Run from backend/:
    cd backend && python3 ../scripts/s24ab_tattoo_exposure_diagnostics.py
"""
from __future__ import annotations

import sys

from app.core.database import SessionLocal
from app.models.character import Character
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services.canon_compiler import (
    _MANDATORY_EXPOSED_DIRECTIVE,
    compile_canon_prompt,
)
from app.services.scene_router import (
    _is_sleeve_mark,
    _mark_region_exposed,
    _partition_marks,
    route_canon_refs,
)
from app.services.canon_service import load_body_canon

CASES = {
    "Pan": [
        "Pan standing on a beach at sunset, shirtless, cinematic fantasy realism",
        "Pan in a black shirt with sleeves rolled to the elbows, standing in a dark forest",
        "Pan wearing a fitted long-sleeve sweater in a castle hall",
    ],
    "Summer": [
        "Summer standing on a beach at sunset in a white bikini",
        "Summer wearing a beige long-sleeve sweater in a coffee shop",
    ],
}


def _find_canon(db, name):
    char = (db.query(Character).filter(Character.name.ilike(f"%{name}%"))
            .order_by(Character.id).first())
    if not char:
        return None, None
    canon = (db.query(CharacterIdentityCanon)
             .filter(CharacterIdentityCanon.character_id == char.id).first())
    return char, canon


def main() -> int:
    db = SessionLocal()
    failures = []
    try:
        for name, prompts in CASES.items():
            char, canon = _find_canon(db, name)
            if not canon:
                print(f"!! no canon for {name}; skipping")
                failures.append(f"{name}: no canon")
                continue
            body = load_body_canon(canon)
            marks = getattr(body, "permanent_body_marks", None) or []
            print(f"\n{'='*78}\n{name} (char {char.id}) — {len(marks)} permanent marks")
            for m in marks:
                print(f"   · {m.label!r} region={m.body_region!r} side={m.side!r} "
                      f"sleeve={_is_sleeve_mark(m)}")

            for p in prompts:
                urls, meta = route_canon_refs(p, canon)
                exposed, hidden = _partition_marks(canon, p.lower(), meta.camera)
                prompt = compile_canon_prompt(canon, p)
                mandatory = _MANDATORY_EXPOSED_DIRECTIVE in prompt
                print(f"\n  PROMPT: {p}")
                print(f"    camera={meta.camera} exposure={meta.exposure}")
                print(f"    exposed_regions   = {[m.body_region for m in exposed]}")
                print(f"    required_mark_refs= {[m.label for m in exposed]}")
                print(f"    hidden_mark_refs  = {[m.label for m in hidden]}")
                print(f"    final_anchor_order= {meta.route_slots} (refs={len(urls)} "
                      f"crops={meta.mark_crops})")
                print(f"    MANDATORY_LINE_PRESENT = {mandatory}")
                # acceptance asserts
                if exposed and not mandatory:
                    failures.append(f"{name} :: {p!r} → exposed marks but NO mandatory line")
                if not exposed and mandatory:
                    failures.append(f"{name} :: {p!r} → no exposed marks but mandatory line present")

        print(f"\n{'='*78}\nRESULT:", "PASS — all assertions held" if not failures
              else f"FAIL\n  - " + "\n  - ".join(failures))
        return 1 if failures else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
