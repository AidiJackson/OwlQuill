# Changelog

All notable changes to the Ficshon project will be documented in this file.

## [Mark routing] - 2026-08-11 - Permanent mark truth survives unresolved clothing

Found by real browser QA, not by tests. Three generations of **"Summer wearing a
yellow summer dress"** came back with completely clean arms, while **"Summer in
her office wearing a white shirt with the sleeves rolled up"** reproduced both of
her tattoos correctly — same character, same canon, same model, minutes apart.

Forensics on the persisted generation records (2050–2052 vs 2047–2049) found the
difference was one phrase. "sleeves rolled up" is in the scene vocabulary;
"summer dress" is not. The yellow-dress scene matched exactly one word of
anything — "dress", a torso-cover signal — so both arm regions resolved
`covered_default`, no mark was judged exposed, no crop routed, no anatomy was
stated, and **every tattoo sentence in the compiled prompt was a negative one**
("hidden markings remain hidden", "clean-skin truth: no ink on the hands…"). The
provider read the same sentence, correctly rendered a sleeveless dress, and
painted the bare arms it had invented with clean skin. It complied with what it
was sent.

The lesson: **the engine's uncertainty is not the provider's uncertainty.**
Withholding mark truth on an unresolved region is not conservative — it
guarantees the marks vanish whenever the garment vocabulary has a gap, and
garment words are unbounded while a character's marks are finite and structured.

### Fixed
- **One gate removed** (`scene_router._mark_crop_visibility`,
  `canon_compiler._mark_binding_clause`). A region that is NOT `covered_explicit`
  and NOT `ambiguous` — i.e. unresolved — now gets its conditional anatomical
  binding emitted and its scoped mark crop routed, **whatever the scene text
  says**. Neither is gated on `scene_requests_marks` any more: permanent canon
  exists whether or not the user says the word "tattoo". The wording is unchanged
  and still conditional — it states where the mark belongs and that it is
  rendered "only where this scene's own clothing leaves that skin bare", never
  that any skin IS bare. Crops carry `visibility="unresolved"` so nothing
  downstream can read them as a bare-skin claim.
  Explicit coverage still wins (no crop, no anatomy named, occlusion only), and
  contradictory garment evidence still resolves to `ambiguous` and forces nothing.
- **Naming a sleeve is explicit coverage of the upper arm** (`arm_exposure_states`).
  Short/rolled-sleeve vocabulary previously left the upper arm merely unresolved,
  which — once unresolved regions became eligible — would have offered an
  upper-arm-only design to the provider on a rolled-sleeve scene. That is the
  original label-driven-anatomy failure, where the design was then painted onto
  the only bare arm skin in frame. "t-shirt" and "sleeves rolled up" both state
  that a garment covers the shoulder, so they now say so.
- **Exposed marks outrank unresolved ones for the capped crop slots**
  (`_collect_exposed_mark_crops`). Caught on Davies' real canon during
  implementation: his genuinely visible hand marks lost both crop slots to an
  unresolved chest and forearm, purely because those come first in the canon
  list. Skin the scene actually bares must never be displaced by skin whose
  coverage is merely unknown. Canon order still decides between equals.
- **An exclusion is agreement, not contradiction** (`_text_contradicts_region`).
  Summer's butterfly description ends "; hand unmarked" — a statement that the
  hand is CLEAN. Reading "hand" as a positive claim disjoint from `left_full_arm`
  discarded the entire description and replaced "Butterflies and wildflowers in
  fine black line work…" with generic wording on every generation, including the
  ones that passed. Anatomy mentions in an exclusionary context ("no", "except",
  "free of", "unmarked", "ending just above…") no longer count as claims.
- **Design-text fallback order** is now description → label → neutral
  (`_safe_design_text`). A contradictory description must not cost the design its
  name when the label is perfectly consistent. Contradictory free text still
  never overrides `body_region`/`side`.

### Added — diagnostics (no behaviour change)
- `SceneMeta.mark_decisions` — one record per registered mark: id, region, side,
  visibility (`exposed` / `unresolved` / `None`), whether a crop image existed,
  whether it routed, and the reason if not.
- `scene_router.routing_diagnostics(meta)` — flattens routing into persistable
  fields (camera, routed, slot order, per-region coverage states, suppressed
  slots, conflict anchor, body_map suppression, crop count, mark decisions).
  Contains no URLs, no secrets, no image bytes.
- `compile_canon_prompt(..., diagnostics={})` — write-only dict reporting which
  clauses were emitted (`marks_clause`, `geometry_lines`, `binding_clause`,
  `clean_skin_clause`), `scene_mentions_marks`, whether detail compression or
  prompt fitting ran, prompt/scene length, and whether the scene survived. Filled
  on the compile pass that already happens; the returned prompt is byte-identical
  with and without it.
- Both generation routes persist the above, plus **`compiled_prompt` bounded at
  4000 chars instead of 400** (above the 2400 prompt cap, so the stored value is
  the whole prompt in every non-pathological case) with `compiled_prompt_len` and
  a short hash. The 400-char cut is why this investigation had to replay the
  compiler against live canon to discover what had actually been sent.
- `tests/test_unresolved_clothing_marks.py` — 108 tests on invented characters:
  unknown garments (yellow summer dress, bandeau, tube top, dashiki, thawb,
  qipao, no garment at all), explicit coverage, contradictory layers, markless,
  mirrored pairs, exclusionary descriptions, genuine contradictions, reference
  cap, crop priority, and emphasis-under-cover.

### Invariant corrections
Every one of these asserted that an unresolved scene must stay silent. Real
visual QA established that silence is the failure, so they now assert the
conditional behaviour instead. None were weakened: each keeps its original
guarantees (no bare-skin assertion, occlusion stated, scene preserved, no
essays) and adds the anatomy assertion.
- `test_mark_routing_gaps`: `test_scene_without_mark_language_is_unchanged`,
  `test_scene_that_never_mentions_marks_routes_no_unresolved_crops`,
  `test_ordinary_ink_language_routes_nothing`
- `test_generic_mark_architecture`: `test_L_a_vague_prompt_routes_nothing…`,
  `test_N_unrelated_or_negated_language_is_not_a_request`
- `test_scene_router`: `test_truly_ambiguous_scene_still_falls_back` (crop count
  only; the fallback behaviour it tests is unchanged)
- `test_mark_completion`: `test_covered_mark_does_not_route_on_vague_prompt`
- `test_canon_rebuild`: `test_prompt_is_small` (bound 700 → 1400 for a
  mark-bearing canon; a new sibling test pins markless canons under 700),
  `test_beach_no_mask_prompt`, `test_beach_with_mask_prompt`

`scene_requests_marks` survives as **diagnostics only** — it is recorded on the
generation record so an operator can see whether the user asked, and it is kept
narrow so that signal stays meaningful, but it gates nothing.

### Known limitations
- **Torso print-through is the trade to watch.** A torso mark on a vague prompt
  now routes its scoped crop, and that is the region where the provider is most
  likely to render clothing — the Davies failure. Two explicit clauses accompany
  it (the general "never printed, traced or echoed onto the garment" and the
  region-named "wherever clothing covers the chest and torso…"), and the crop is
  region-scoped rather than a bare whole-body card. If print-through reappears on
  torso marks, revisit this first; the fix would be a per-region visibility prior,
  not a return to silence. Recorded in
  `test_mark_completion.test_unresolved_mark_routes_on_vague_prompt_with_occlusion_stated`.
- **Prompts are larger for mark-bearing canons** (~600 chars for the binding
  clause). Markless canons are unchanged.
- **Negated garments still read as present** — "no jacket" matches the jacket
  cover signal. Conservative direction; unchanged.
- Nothing here is visually confirmed. The next step is a real browser retest,
  starting with the exact yellow-dress prompt.

## [Mark routing] - 2026-08-11 - Generic architecture: the blockers below, closed

An audit of the entry below asked one question of it: would this work for a
character the code has never seen, from structured canon alone? Three of its
changes would not have. They were generic defects, not character-specific ones,
and they are corrected here. Read this section as superseding the one that
follows it.

### Fixed
- **Contradictory garment evidence no longer resolves as bare skin**
  (`scene_router.arm_exposure_states`). A definitionally sleeveless garment used
  to outrank any arm-covering garment, on a layering argument ("jacket over a
  tank top") with no notion of layer order. The inverse phrasing therefore read
  identically: "a sports bra under a heavy winter parka" resolved to bare arms,
  routed a mark crop, asserted bare skin in the prompt, and invited ink onto a
  coat sleeve — every failure mode this work exists to prevent, on a sentence a
  real user would write.
  Arm exposure is now a STATE, not a boolean: `exposed` / `covered_explicit` /
  `covered_default` / `ambiguous`. Credible evidence both ways yields
  `ambiguous`, which routes no crop, asserts no bare skin, and asserts no
  explicit coverage either — so a genuinely sleeveless scene keeps its bare
  cards. Short/rolled-sleeve vocabulary is deliberately exempt from the
  contradiction rule: "a long-sleeved shirt with the sleeves rolled up" is not a
  contradiction, it is how a forearm becomes bare. No clothing parser, no
  layer-order inference; conservative ambiguity is the whole design.
  The arm-COVER vocabulary moved to `scene_router` beside the exposure sets it is
  weighed against, and gained the long-sleeved outerwear the rule needs to be
  worth anything (parka, anorak, cardigan, overcoat, raincoat, windbreaker,
  sweatshirt, pullover, peacoat, cloak, poncho, kimono, bathrobe, dressing gown).
  Deliberately arm-only: claiming torso coverage for these would change card
  suppression for existing canons, which is outside this correction.
- **Prompt fitting is by priority, and can no longer evict identity or safety**
  (`canon_compiler`). The previous repair preserved the user's scene but added a
  worse branch: when the scene ALONE approached the cap it emitted the scene and
  nothing else — no safety directive, no identity grounding, no invariants.
  Measured on a 2.7 kB scene. That branch was mark-independent, so it was a
  general image-system regression affecting markless and fully clothed
  characters too.
  Parts are now ranked. Safety and identity grounding are never shed; structural
  invariants (anatomy bindings, occlusion, clean-skin truth) are shed only as a
  last resort and from the end; descriptive prose goes first. Before anything is
  shed at all, design DETAIL is compressed — mark descriptions clipped, binding
  lines collapsed toward their general rule. The scene is always represented: it
  is trimmed to fit rather than dropped, and not trimmed below a floor while any
  sheddable part remains.
- **Structured anatomy is the only anatomy the provider reads** (`canon_compiler`).
  Two independent leaks, both putting a second, contradicting anatomy in the
  prompt beside the structured one:
  * `side` is stored independently of `body_region` and nothing validates them
    against each other. `region="right_forearm"` with `side="left"` produced
    "belongs on the right forearm … never the right arm"; `side="centre"` on a
    side-named region silently dropped the side exclusion entirely — the exact
    protection the clause exists for. Side is now DERIVED from `body_region`
    whenever it encodes one, the `side` field may only supplement a region that
    carries none, and a disagreement is logged as the canon data defect it is.
  * `label` and `description` are free text — the schema's own example label is
    'Left arm gothic script sleeve'. A mark labelled "Right shoulder eagle" with
    region `left_forearm` was emitted verbatim beside "belongs on the left
    forearm". Free text that makes an anatomical claim the structured region
    denies is now replaced with neutral wording ("the canonical left forearm
    tattoo") and logged. Whole-arm extent claims ("sleeve", "shoulder to wrist")
    are checked against the region's exact extent, which closes the original
    label-driven-anatomy bug at the prose layer as well as the routing layer.
    Consistent labels are still used — two designs must stay distinguishable.
- **The mark-request trigger is narrow, and no longer selects references**
  (`canon_compiler.scene_requests_marks`). It matched bare "ink" ("an ink pen"),
  bare singular "marking" ("marking papers") and bare "scar" ("the scars of the
  old city wall"). Those now require a possessive form ("show her ink"). Compound
  nouns naming a place, object or profession are excluded ("a tattoo parlour"),
  and a clause-bounded negation guard rejects "no tattoos visible" without
  cancelling a request that merely sits near an unrelated negation ("no jacket,
  show his tattoos" — found by adversarial probing after the first fix).
- **Unmappable mark regions no longer bypass the hidden-design rule**
  (`canon_compiler`). The "never name a covered design" guard only protected
  regions the coverage vocabulary could map, so a mark on an invented region
  (`tailbone`) was named in a fully dressed scene. Unknown anatomy now fails
  conservatively in every direction: it is never named under an explicitly
  covered scene, and never routes a crop.
- **"halter" is no longer a bare noun** (`scene_router`). A horse is led by its
  halter. Reachable only as "halter top" / "halter neck" / "halterneck" /
  "halter dress".

### Changed
- **The bare placement-sheet exception was DELETED** (`scene_router`), replaced
  by anatomically-scoped crops on the same path. The exception kept the bare
  `body_map` against the S24I gate whenever a scene mentioned markings, which
  reintroduced whole-body bare evidence — torso, back and legs included — into
  scenes whose wardrobe was never stated. That is the reference contamination the
  card-coverage engine exists to prevent.
  Measured A/B on a synthetic opposite-side canon (left full-arm design + right
  forearm design) across five scenarios. On the decisive one — vague scene,
  explicit tattoo request — the sheet gave 3 references, a bare whole-body card
  and ZERO per-mark side-bound evidence; scoped crops gave 4 references, no bare
  card, and both designs bound to their own region and side. Scoped crops
  dominate on every scenario; the exception is gone. (The sampled arm-swap that
  motivated it was also measured before any anatomy binding existed in the
  prompt at all, so it never established that the sheet was needed.)
  Crops on unresolved regions carry `visibility="unresolved"`, never "exposed",
  so nothing downstream can read them as a claim that the skin is bare. Every
  existing guarantee holds: explicitly covered marks route nothing, ambiguous
  regions route nothing, crops never lead, a body anchor is always required, the
  six-reference cap is unchanged, and portraits route no body crops.
- Mark-crop audit metadata now reports the authoritative (region-derived) side,
  so diagnostics cannot disagree with the anatomy the prompt states.

### Added
- `tests/test_generic_mark_architecture.py` — the decisive suite, on INVENTED
  characters only. Fourteen cases (forearm-only, full arm, upper-arm-only, hand
  + gloves, chest + shirt, markless, opposite limbs, contradictory layers,
  hostile labels, oversized scenes, unmappable regions, vague prompts, emphasis
  prompts, unrelated ink language) plus a many-mark character for the reference
  cap. Mirrored-anatomy pairs are asserted in both directions: a rule that
  passes for one and fails for its mirror is character-specific.

### Invariant corrections
- `test_layering_still_bares_the_arms` asserted that "jacket over a tank top"
  bares the arms. That requirement is what forced exposure to outrank cover
  unconditionally, and it has been demonstrated unsafe. Replaced with
  `test_contradictory_layers_resolve_to_ambiguous`. The cost is under-rendering a
  genuinely bare arm in a contradictory sentence; the alternative is printing a
  tattoo on a coat.
- The mark-request vocabulary tests asserted bare "ink" and bare "scars" count
  as requests. They no longer do, and the predicate now also gates a reference
  slot, so the bar is "this sentence is about the character's own markings".

### Known limitations
- **Garment vocabulary is finite.** An unknown garment (bandeau, tube top,
  dashiki, thawb) leaves marks unrouted and unnamed. Verified to fail closed —
  under-render, never ink on fabric — but it is the standing cost of
  deterministic keyword matching, and the vocabulary will keep needing entries.
- **Negated garments read as present.** "no jacket" matches the jacket cover
  signal, so the arms read covered. Conservative direction (hides marks, never
  prints them); not fixed, because a general clothing-negation parser is out of
  scope.
- **Segment-blind crops** — unchanged, see the entry below.
- Nothing in this section has been visually confirmed on generated images. The
  automated mark verifier remains unreliable and gates nothing; manual visual
  inspection is still ground truth, and is the next step.

## [Mark routing] - 2026-08-10 - Three routing gaps closed

> Superseded in part by the section above: the placement-sheet exception was
> deleted, the arm-exposure precedence corrected, and the prompt-fitting policy
> replaced. The `card_coverage` data work and the diagnostics alignment stand.

### Fixed
- **Sleeveless garment vocabulary** (`scene_router`): "sports bra", "bralette",
  "vest top", "strappy top", "spaghetti strap", "halter"/"halterneck" and "singlet"
  now bare the arms, as "tank top" always has. A second, weaker tier ("crop top",
  "sundress") bares the arms only when the scene names no arm-covering garment — a
  crop top is a statement about length, not sleeves, so "long-sleeved sundress"
  stays covered. Phrases, not bare nouns, wherever the noun would collide: "vest
  top" (never "vest" — the three-piece-suit false positive), "sports bra" (never
  "bra" — "bracelet"), "strappy top" (never "strappy" — sandals). Arms only: none
  of this vocabulary claims torso, back, legs or neck.
- **One arm-exposure decision** (`scene_router.arm_exposure`): the router's per-mark
  gate and `card_coverage.scene_region_states` now call the same resolver instead of
  each reading the frozensets themselves, so the two engines cannot drift.
- **Explicit mark requests under unspecified clothing** (`canon_compiler`): a scene
  that asks for markings but names no garment used to emit NO per-mark anatomy at
  all — every region resolved `covered_default`, so the exposed-mark block stayed
  empty while the user's own sentence pushed the provider to render ink. It swapped
  Summer's two designs across arms. Two questions were being answered by one gate;
  they are now separate: WHERE a mark belongs is canon truth and is stated
  unconditionally, WHETHER that skin is bare is scene truth and stays conditional
  ("render only where this scene's clothing leaves that skin bare"). Trigger is
  generic scene language (word-boundary matched, so "scarf" is not "scar"); every
  binding line is built from structured canon. Silent on scenes that do not mention
  markings, and silent for a mark whose regions the scene EXPLICITLY covers —
  asking for tattoos must not uncover them.
- **The placement sheet survives an explicit request** (`scene_router`): body_map is
  the only reference that shows which design sits on which side, and the S24I gate
  dropped it precisely when a user asked for tattoos without naming clothes. With it
  suppressed, 2 of 3 samples put the forearm design on the wrong arm despite the
  prompt naming both sides in words. Kept only when the scene asks for marks AND no
  region is explicitly covered; a named covering garment still suppresses it.
- **Prompt fitting no longer deletes the scene** (`canon_compiler`): the cap was a
  tail cut, and the scene is assembled last, so on a nine-mark character the new
  bindings pushed the prompt over and the cut discarded the occlusion clause, the
  clean-skin clause and the user's own sentence. Binding lines are now short (label
  over full description), budgeted, and compressed toward their general rule before
  anything else is sacrificed; overflow is summarised, never silently dropped; the
  scene is preserved whole.
  (Correction, 2026-08-11: "the scene is preserved whole" was not true in the
  `head_room <= 0` branch, which emitted the scene ALONE — no safety directive,
  no identity grounding, no invariants. Replaced by priority-based fitting; see
  the section above.)

### Added
- Summer's body cards declare `card_coverage = swimwear`
  (`scripts/declare_summer_card_coverage.py`). Every one of them is a bikini shot,
  which was previously `unknown` metadata, so a long-sleeved scene routed bare-skin
  evidence that contradicted its own wardrobe. Covered scenes now suppress them and
  retain `body_front` as the conflict anchor; exposed scenes are unchanged.
- `tests/test_mark_routing_gaps.py` — invariants for all three gaps, plus the
  prompt-budget and placement-evidence behaviours found while fixing them.

### Known limitation
- **Segment-blind crops (gap C, not fixed).** A `*_full_arm` mark carries one crop
  and nothing records which segment it depicts. Summer's butterfly piece spans
  shoulder to wrist but both of its stored images frame the upper arm, so a short
  sleeve routes a crop of the covered half. No wrong image has been produced by it —
  the whole-body cards lead and the design vocabulary is continuous along the arm —
  but the schema cannot express the distinction. Proposed minimal extension in the
  handover; deliberately not implemented, since populating it needs new canon
  imagery.

## [Canon fact] - 2026-08-10 - Summer's left-arm mark is a full arm, not an upper arm

### Fixed
- **Summer (character 60) left-arm mark region** (`scripts/fix_summer_left_arm_region.py`):
  `pbm_8cff990d` ("Butterfly floral sleeve") was stored as `left_upper_arm` with a
  "shoulder cap down to the elbow" description. That anatomy was copied from the TEXT
  LEGEND on her body-map card; the renders on that same card — and body_front,
  body_left, body_right, body_back, the final character card and its wardrobe strip —
  all show the work running shoulder → elbow → forearm, ending just above the wrist.
  Now `left_full_arm` with a description matching the cards. Two fields on one mark;
  side, label, images, the ballerina mark, `marked_regions` and both identity locks
  unchanged. No schema change was needed — `left_full_arm` is existing vocabulary in
  the router, `card_coverage.mark_region_groups` and the CanonManager dropdown.
- Effect: short-sleeve and rolled-sleeve scenes now route the left-arm crop and name
  the left arm in the prompt (previously the left forearm generated as bare skin,
  because an upper-arm mark is correctly treated as covered by a short sleeve).
- Stale comments corrected in `scene_router` (the deleted `_is_sleeve_mark` rationale
  cited the wrong region as fact) and `adult_studio._marks_body_phrase` (docstring
  example had Summer's sides swapped).

### Added
- `backend/scripts/summer_exposure_soak.py` — Summer-only exposure-class supplement to
  `mark_soak.py` (bare arms / short sleeve / rolled / long sleeve), reusing its
  scoring and retention primitives. Measurement only; the shared roster matrix is
  untouched so recorded passes stay comparable.

## [Permanent-Mark Canon] - 2026-08-09 - Mark location authority + provider modernisation

### Added
- **Mark-location authority** (`BodyCanonData.marked_regions` + `card_coverage.mark_location_authority`):
  separates SKIN VISIBILITY from PERMANENT-MARK LOCATION AUTHORITY. A canon can now
  declare where marks exist; every other region is authoritatively clean skin.
  `[]` = explicitly unmarked; structured marks union in (under-declaration can never
  suppress a registered mark); unmappable mark regions veto clean-skin claims.
- **Clean-skin authority clause** (`canon_compiler._clean_region_clause`): scene-relevant
  negative truth — stops reference-pack tattoos migrating onto neck/hands/face
  (the Davies office collar/knuckle inventions). Character-agnostic, region-level.
- **Legacy mark presence clause**: enriched legacy canons (declaration, no structured
  marks) get a positive "markings exactly as shown in references" line in exposed scenes.
- **Mark placement verifier** (`services/mark_verifier.py`, `CANON_MARK_VERIFY`):
  flag-only post-generation check for marks outside authority and marks printed on
  clothing. Never rejects/regenerates — writes metadata warnings.
- **Model profiles** (`services/model_profiles.py`): per-model capability facts
  (gpt-image-2 rejects `input_fidelity`; images.edit hard cap 16 refs). Editor
  strength control now gates on the profile instead of assuming the parameter.
- **Reference dedup**: byte-identical duplicate references dropped before the provider
  call (first occurrence kept); `refs_deduped` in logs and image metadata.
- **Creator UX** (CanonManager): "Skin & Marking Truth" section — marked-regions
  checkboxes + per-card coverage presets; mark body-region is now a canonical
  dropdown (free text was how unmappable regions entered canon).
- Admin diagnostics now report the effective Google model and OpenAI
  input-fidelity support alongside the OpenAI model.

### Changed
- `IMAGE_MODEL` default `gpt-image-1.5` → `gpt-image-2` (OpenAI's current recommended
  model, verified against official docs 2026-08). Env var still overrides.

### Not changed
- `GOOGLE_IMAGE_MODEL` stays `gemini-3.1-flash-image` (benchmarked vs flash-lite on
  4 canon cases: comparable scores, but n is too small to prove the cheaper model
  holds identity on hard tattoo cases — see sprint report for the larger-benchmark plan).
- No Alembic migration: `marked_regions` is JSON-additive inside `body_canon_json`.

## [Phase 2] - 2025-11-16 - Playable Social MVP

### Added

#### Backend
- **Character Enhancements**
  - Added `role` field to Character model for character roles (e.g., "assassin", "healer")
  - Added `era` field to Character model for time periods (e.g., "modern", "medieval")
  - Added `portrait_url` field to Character model for character portrait images

- **Realm Enhancements**
  - Added `tagline` field to Realm model for short catchy descriptions
  - Added `banner_url` field to Realm model for header/banner images

- **Feed System**
  - New `/posts/feed` endpoint that returns posts from realms the user is a member of
  - Feed is sorted by creation date (newest first)
  - Supports pagination with `skip` and `limit` parameters

- **AI Service Enhancement**
  - Enhanced AI stub to generate richer character bios using role and era fields
  - Bio generation now incorporates character's role and era for more contextual descriptions

- **Database Migration**
  - Created Alembic migration `8b18cfce864f` to add Phase 2 fields to database
  - Migration safely adds nullable columns to existing tables

#### Frontend
- **Profile Page**
  - User avatar display with circular avatar component
  - Avatar preview in edit mode
  - Fallback to user initials when no avatar is set
  - Improved profile layout with avatar header section

- **Character Creation**
  - Added Role and Era input fields in creation form
  - Added Portrait URL input field
  - Enhanced AI bio generation to include role and era
  - Updated character display cards to show portraits
  - Character cards now display "species • role • era" subtitle
  - Image error handling with fallback display

- **Realms**
  - Added Tagline and Banner URL fields to realm creation form
  - Realm cards now display banner images with gradient fallback
  - Tagline displayed in italic with accent color
  - Realm detail page with full realm information
  - Ability to create posts directly from realm detail page
  - Post type selection (IC/OOC/Narration) in post composer

- **Home Feed**
  - Replaced manual post loading with `/feed` endpoint
  - Added post type badges (IC/OOC/NARRATION) with color coding
  - Display character name and realm name for each post
  - Improved post metadata display

- **Routing**
  - Added `/realms/:realmId` route for realm detail pages
  - Realm cards in listing page now link to detail pages

- **TypeScript**
  - Created `vite-env.d.ts` for proper Vite environment types
  - Fixed TypeScript compilation errors in API client

### Changed
- Updated Character schema to include role, era, and portrait_url
- Updated Realm schema to include tagline and banner_url
- Enhanced AI character bio request schema to accept role and era
- Updated frontend types to match new backend schemas
- Improved error handling for image loading across all components

### Technical Details
- All new fields are nullable/optional to maintain backward compatibility
- Database migration can be run on existing data without issues
- Frontend build process now properly handles Vite environment variables
- API client uses proper TypeScript types for headers

## [Phase 1] - Initial MVP Scaffold

### Added
- User authentication system with JWT
- Character creation and management
- Realm creation and joining
- Post creation with IC/OOC/Narration types
- Comment and reaction systems
- AI stub service for bio generation
- Full-stack setup with FastAPI backend and React frontend
- Database models and migrations with Alembic
- RESTful API with Swagger documentation
- React Router navigation
- Tailwind CSS styling
- Zustand state management
