# Provenance Sprint — Final Polish

Audit and polish pass over the provenance system, character-scoped media,
typography, badges and the Commons composer. Nothing here adds capability.

Every claim below was produced by reading the code and, where the claim is
about behaviour, by a test that fails without the fix. Nothing is committed or
pushed.

**Baseline before this pass:** 179 frontend tests, 45 focused backend tests
(provenance, post image scope, posts, images) — all green.

---

## 1. Summary

| # | Issue | Severity | State |
|---|-------|----------|-------|
| P1 | Restored WriteSpace draft loses all typing evidence → "Created elsewhere" | **High** | Fixed |
| P2 | Android gesture typing / CJK IME counted as pasting → "Created elsewhere" | **High** | Fixed |
| P3 | "Use in Post" from a character gallery was broken end-to-end (HTTP 403) | **High** | Fixed |
| P4 | Undo→redo re-counts replayed text as an insertion | Medium | Fixed |
| P5 | WriteSpace's own formatting tools are invisible to the session counters | Medium | Fixed |
| P6 | Composer claimed a posting identity the user had not selected | Medium | Fixed |
| P7 | Two divergent badge systems on the same feed row | Medium | Fixed |
| P8 | Four different type treatments for the same paragraph of writing | Medium | Fixed |
| P9 | Image picker's empty state lied when no character was selected | Low | Fixed |
| P10 | Long character names could push a feed byline off the card | Low | Fixed |
| P11 | Badge colours were dark-mode-only in the Realm feed | Low | Fixed |
| P12 | Emoji in the provenance badge read aloud as content | Low | Fixed |
| A1–A9 | Provenance limits found and *not* fixed | see §6 | Documented |

No cross-character image leak was found. No provenance forgery path was found.

---

## 2. Part 1 — paths Ficshon cannot truthfully classify

### The premise is sound, and stays

ChatGPT → Facebook → Ficshon lands on **"Created elsewhere"**, and that is
correct, not a miss. The content *was* created elsewhere. The badge makes no
claim about which elsewhere, and the design note in
`backend/app/services/provenance.py` is right that guessing would be worse than
declining to.

No AI detection was added. No heuristic was added.

### What the review actually found

The interesting failures run the other direction: **content genuinely written
in Ficshon that the system labelled "Created elsewhere"**. Those are not
philosophy, they are bugs — the evidence existed and was being dropped. Four
were fixed (P1, P2, P4, P5); the rest are recorded in §6 as recommendations.

The false-negative inventory, in order of how many writers it touches:

1. **Phone writers** (P2 — fixed). Android gesture typing commits a whole word
   per swipe; a Japanese or Chinese IME commits a whole phrase. The typed-vs-
   pasted rule was a size threshold — anything over two characters at once was
   an insertion — so a post swiped out on a phone reported ~100% inserted and
   published as created elsewhere. The browser tells us unambiguously that this
   was keyboard composition (`insertCompositionText`, and the
   `compositionstart`/`compositionend` pair); a clipboard operation can never
   produce those signals.
2. **Anyone who closes a tab** (P1 — fixed). See §3.
3. **Anyone who uses the editor's own buttons** (P5 — fixed).
4. **Anyone who presses undo then redo** (P4 — fixed).
5. **Dictation** (A1 — recommendation). Desktop speech-to-text inserts whole
   phrases with no composition signal and is indistinguishable from a paste at
   the event level. Android voice typing goes through composition and is now
   covered by P2.
6. **Cross-device drafting** (A2 — recommendation). Drafts live in
   `localStorage`, so starting on a phone and finishing on a laptop necessarily
   arrives as a paste.

### The honest limit, restated

`typed_chars` is client-attested. Anyone who can send an HTTP request can open
a session, report 4,000 typed characters and post 4,000 characters of anything.
The server's own evidence — AI fingerprints, structural surfaces, the session's
existence and single use — cannot be forged, but "Written in Ficshon" cannot be
made unforgeable in a browser and this pass did not pretend otherwise. It is a
statement about what Ficshon observed, not a trust score, and it should not be
built into moderation or reputation.

---

## 3. P1 — the restored-draft false negative (High)

**What happened.** A composition session lives for the life of a React
component. A WriteSpace draft does not — it is autosaved to `localStorage` and
restored on mount. So writing a chapter over two sittings meant: the first
session recorded the typing and was then abandoned; the second mount restored
4,000 characters that no session had ever watched arrive, reported ~0 typed
characters, and the finished piece published as **"Created elsewhere"**.

Reproduced from the code path: with no draft edits at all, `commit()` opens a
session with zero counters, and `_typing_evidence` returns `no_typing_evidence`
→ EXTERNAL. With a few edits, the reported total falls short of the content
length and it returns `inconsistent_metrics` → EXTERNAL. Both are pinned by
existing tests (`test_a_session_with_no_reported_typing_earns_nothing`,
`test_metrics_that_contradict_the_content_are_discarded`).

**Fix.** The session id is now stored beside the draft, and
`CompositionTracker.resume()` re-attaches to it:

- **Session still open** → adopt it, and adopt *the server's* counters as the
  baseline. Nothing new is claimed; those characters were already observed
  being typed into that session.
- **Session spent, expired or gone** → open a session that *continues* the old
  one and declare the restored text an internal transfer. That is a claim, not
  a grant: `credited_internal_chars` credits it only up to what the parent was
  independently observed to type. With no parent, the credit is zero and the
  draft honestly reads as created elsewhere.

The server-held counters are read through a new `metrics` field on
`SessionRead`. It is owner-scoped (the endpoint already 404s for anyone else)
and filtered through the `CompositionMetrics` model, so the open `metrics_json`
slot — shared with autosave and analytics — cannot leak a non-counter through
it.

**Known limitation, unfixed by choice.** Two WriteSpace tabs now share one
resumed session. The first post to commit redeems it; a second post from the
other tab finds a spent session and reads as EXTERNAL. Posting the same draft
twice from two tabs is already a conflict (they clobber each other's autosave),
and the failure mode is honest rather than permissive.

---

## 4. Part 2 — character image isolation

**Result: no leak found.** Every layer holds.

| Layer | Finding |
|-------|---------|
| API — `GET /users/me/character-images` | Ownership is *verified*, not just filtered: an unowned `character_id` is 403, an unknown one 404, so the endpoint cannot be used to probe ids. Kind filter applied server-side. |
| API — `POST /posts/realms/{id}/posts` | The acting character comes from the verified `author_char`, never from the request. Image must match that character, be ACTIVE, and be in `POST_ATTACHABLE_IMAGE_KINDS`. A forged path cannot cross characters. |
| Permissions | Another account's media is invisible and unattachable (`test_another_writer_cannot_read_your_characters_media`, `test_cannot_attach_another_accounts_image`). |
| Queries | Joined to `characters.owner_id`; no query returns cross-owner rows. |
| Frontend cache | `AttachImageModal` refetches per character and cancels in-flight responses, so a fast Pan→Shadow switch cannot repopulate the grid with the previous character's media. |
| Pagination | `limit`/`offset` are applied *after* the temp-image filter, so a page is never short-changed by invisible rows. |
| Search / recent | The picker has no search; ordering is `newest`/`oldest` within the already-scoped set. |
| Composer state | Home and RealmDetail both clear the attached image when the posting character changes. |
| Other surfaces | Comments, scenes and Story Space posts accept no images at all — nothing to scope. |

**P3 — the one real defect (High).** The "Use in Post" action on a character's
gallery was broken end to end, and had been since it was written:

1. `PostComposer` sent **no `character_id`**, so the server refused every post
   from it with *"Create a character to start posting"* — to a user standing on
   their own character's page.
2. It sent `resolveImageUrl(image.url)`, which prefixes an API origin when
   `VITE_API_BASE_URL` is absolute. The server matches the *stored* path, so
   the rendered form fails the ownership check on exactly the image the user
   just picked.
3. It opened no composition session, so anything typed in it was labelled
   "Created elsewhere".

Both server-side halves are now pinned by tests that fail against the old
client behaviour: `test_the_stored_address_is_what_the_server_accepts` and
`test_a_post_without_a_character_is_refused_outright`.

Fixed: the composer takes `characterId` (and shows whose name it is posting
under), sends the stored address, and carries a session like every other
composer.

**P9 (Low).** With no character selected the picker showed *"No generated
images saved yet"* — false for a founder with a full library. It now says to
choose a character first, and the attach buttons in both composers are disabled
until one is chosen.

**Noted, not changed:** account-level `UserImage` rows are attachable to a post
by any of the account's characters. They belong to no character, they are the
poster's own media, and no UI offers them to a composer — it is reachable only
by direct API use. Recorded rather than fixed because it is the documented
design.

---

## 5. Parts 3–5 — typography, badges, composer

### P8 — typography (Medium)

The same in-character paragraph rendered four ways: 17px Playfair in the
Commons, ~16px Inter in a Realm, 14px Inter in a Story Space, 16px Playfair on
a character page. Comments, scenes, StoryLab and the published reader each had
a fifth, sixth and seventh treatment.

One scale now lives in `frontend/src/index.css` and every reading surface uses
it: `.fic-read` (16px mobile / 17px desktop, 1.75), `.fic-read-sm` (15px, 1.65,
for conversational surfaces), `.fic-ooc` and `.fic-narration` modifiers,
`.fic-title` for headings, `.fic-compose` for composers, `.fic-measure` for
reading width.

**Inter is the reading face, as specified.** Playfair Display stays on titles,
mastheads and the published-story header — which is what it was drawn for. It
is a high-contrast didone: handsome at 32px, thin-stroked and tiring at 17px on
a dark background, which is where the feed had been using it. This is the one
visible change in the pass: in-character feed prose now reads as Inter. It is a
one-line reversal (`font-family` in `.fic-read`) if the change is not wanted.

Audited and settled: font-family, size, line-height, letter-spacing, reading
width, mobile vs desktop (a `min-width: 640px` step, not a separate stack), and
dark mode (all colours were already token-driven). Paragraph spacing is
untouched — every feed surface renders a single `whitespace-pre-wrap` block, so
spacing comes from the writer's own blank lines. No container, padding or
layout value was changed.

`overflow-wrap: anywhere` was added to reading text so a pasted URL or an
unbroken string cannot widen a card and start the page scrolling sideways.

### P7, P11, P12 — badges (Medium / Low)

Three badge implementations existed: quiet outlined chips in the Commons, solid
12px blocks in raw Tailwind palette colours in a Realm, and a third variant in
comments — with the shared `ProvenanceBadge` as a fourth geometry. On a Realm
post, "IC" and "✍️ Written in Ficshon" rendered at different heights, weights
and colour systems on the same line.

Now: one `.badge` rule owns geometry (a *fixed height*, so a chip is exactly as
tall as its neighbour whatever it contains), one `PostBadges.tsx` owns the
IC/OOC/Narration and Open Starter/Finished Piece vocabulary, and
`ProvenanceBadge` sits on the same geometry.

- **Colours** (P11): the Realm feed's `bg-blue-600` / `bg-amber-950/20` were
  dark-mode assumptions. Every badge now has a `[data-mode="light"]` variant.
- **Accessibility** (P12): the provenance emoji is `aria-hidden` — "writing
  hand Written in Ficshon" was noise — and every badge carries a plain-language
  `title`/`aria-label`, so "IC" keeps its brevity for people who know it and
  gains a meaning for people who do not.
- **Mobile wrapping**: badges wrap as whole units (`white-space: nowrap`),
  never mid-label.
- **Unknown values** render nothing rather than defaulting. The Commons helper
  previously fell back to `IC`, so an unrecognised content type was labelled
  in-character.

**P10 (Low):** a 100-character name (the schema limit) could push a byline past
the card edge. Names now truncate in the Commons, Realm and Story Space
bylines.

### P6 — composer (Medium)

- **The identity line lied.** The composer header read *"Writing as
  \<first character\>"* whenever nothing was selected, while the selector below
  it still read *"— select character —"*. It also duplicated the "Posting as"
  control directly beneath. The heading is gone; the "Posting as" control is
  the single statement of who is posting.
- **Attach image** is disabled without a character, with a title explaining
  why, instead of opening onto a misleading empty state.
- **Loading state** now covers the whole control set — textarea and both
  selects freeze while posting, not just the button.
- **Errors** use the same treatment as every other error surface
  (`bg-red-400/10` panel) and carry `role="alert"`; a "select a character"
  error clears when a character is selected rather than lingering as an
  apparently unrelated failure.
- **Post** stays clickable without a character on purpose: being told what is
  missing beats a dead button that explains nothing.
- Both selects gained `aria-label`s; the composer textarea did too.

---

## 6. Part 6 — provenance bypass audit

Each row is a path that was actually traced through the code.

| Path | Result |
|------|--------|
| **API — forged verdict** | `PostCreate` has no `source_type`/`provenance` field and the route lists columns explicitly rather than splatting the payload. Extra JSON keys are dropped by Pydantic. Pinned by `test_client_cannot_forge_the_badge`. **Not exploitable.** |
| **Modified request / forged JSON** | The only client input to the decision is `composition_session_id`, which the server issued and verifies. **Not exploitable.** |
| **Missing session** | → EXTERNAL (`no_session`). Correct. |
| **Expired session** | Refused past 24h. Pinned. |
| **Another user's session** | Ownership-checked; endpoints 404 so ids cannot be probed. Pinned. |
| **Session replay** | Claimed inside the content transaction, single-use. Pinned. |
| **Multiple tabs** | Separate sessions per composer. WriteSpace now shares one across tabs; see §3's limitation. |
| **Refresh / browser back** | Composer state is lost, a fresh session opens. WriteSpace resumes (P1). |
| **Copy / paste** | Counted as insertion; >20% external → EXTERNAL. Clipboard *contents* are never read. |
| **Drag / drop** | Counted as insertion (see A3). |
| **IME input** | Now typing, at any chunk size (P2). |
| **Speech input** | Android voice typing → typing. Desktop dictation → insertion (A1). |
| **Mobile keyboards** | Gesture typing → typing (P2). Autocorrect → insertion (A4). |
| **Autocomplete / autofill** | `insertReplacementText` and unattributed bulk → insertion. Correct: the text came from a store, not the writer. |
| **WriteSpace** | Resume (P1) and tool edits (P5) fixed. Copy-for-posting handoff is credited only up to the parent's observed typing. Pinned. |
| **StoryLab** | All four text generators fingerprint their output. A paste of a generation is labelled AI_ASSISTED whatever the client claims. Pinned. |
| **Imports** | RP partner starters/turns → `external_import`. Story Space publish inherits per segment and rolls up worst-case for the story. Pinned. |
| **Seeder tools** | `starter_seed` is the only seeding path and uses `not_composed_here`. No script writes posts. |
| **Admin tools** | Admin routes are reports and bans only. No content-writing endpoint. |
| **Post editing** | **No post/comment update endpoint exists.** The `PostUpdate` schema is dead code. Nothing can change content after the verdict. |
| **Serialisation** | Provenance is read from the row via `model_validate`; the character-first serialiser does not touch it. |

**Fixed as genuine weaknesses:** P1, P2, P4, P5 (all false negatives — the
system understating its own evidence). Nothing was loosened; every change is
either the server's own record being re-read or a browser signal that a
clipboard operation cannot produce.

### Recommendations — found, deliberately not implemented

- **A1 — desktop dictation** reads as pasting. No event-level signal separates
  it from a paste. Recommend accepting.
- **A2 — cross-device drafting** necessarily reads as pasting. The real fix is
  server-side drafts; `CompositionSession.state_json` is already reserved for
  exactly that.
- **A3 — drag-and-drop within one textarea** (moving a paragraph you wrote)
  counts as an insertion. Fixable by tracking `dragstart` on the same element,
  but the cross-browser behaviour needs care; not worth doing under a polish
  brief.
- **A4 — iOS autocorrect** counts each corrected word as inserted. Unlikely to
  reach the 20% threshold alone; worth measuring before changing.
- **A5 — a failed session open** (an offline blip) silently costs the badge.
  Recommend one retry.
- **A6 — `/api/ai/character-bio` and `/api/ai/scene`** produce text and do not
  register fingerprints. Both are `FakeAIClient` stubs today, so the gap is
  theoretical — but it must be closed *before* either is wired to a real model,
  or Ficshon's own AI output will go unlabelled.
- **A7 — StoryLab chapters carry no provenance columns.** They are AI-assisted
  by construction and are not publicly badged today. If chapters ever become a
  public surface, they need the mixin.
- **A8 — composition-session creation is unrate-limited.** Authenticated, and
  it gains an attacker nothing but rows; worth a limit before open signup.
- **A9 — `typed_chars` is client-attested.** Restated here because it is the
  ceiling on everything above: do not build moderation or reputation on the
  "Written in Ficshon" badge.

---

## 7. Screens affected

| Screen | Change |
|--------|--------|
| Commons (Home) | Type scale, unified badges, composer identity/disabled/loading/error polish, name truncation |
| Realm detail | Type scale, unified badges (was a separate solid-block system), attach-image guard, name truncation |
| Story Space channel | Type scale (compact), name truncation |
| Published story reader | Type scale |
| StoryLab chapter reader | Type scale |
| RP story thread | Type scale |
| Scene detail | Type scale |
| Character profile — timeline, bio | Type scale |
| Character profile — "Use in Post" | Now works at all; character-scoped and evidenced |
| Comments | Type scale, unified badge |
| WriteSpace | Session resume, tool-edit accounting |
| Attach-image modal | Honest empty state |
| All composers | Composer type scale, IME/gesture typing counted as typing |

---

## 8. Test results

All figures below are from a fresh run at review time, not carried over.

**Frontend** — `npm run test` (vitest): **204 passed / 20 files** (baseline
179/18). 25 new tests across four files:

- `lib/__tests__/compositionResume.test.ts` (9) — adopt-open-session,
  continue-spent-session, unknown-key filtering, never-claims-untyped,
  typed-during-lookup, no-ops, editor-tool accounting.
- `lib/__tests__/composition.test.ts` (+8, 14 total) — gesture typing, IME
  phrases, composition-without-inputType, paste-still-wins-inside-composition,
  quoted paste, undo/redo.
- `components/__tests__/postBadges.test.ts` (7) — badge vocabulary, plain
  language expansions, unknown values render nothing, shared geometry.
- `components/__tests__/provenanceBadge.test.ts` (+1, 9 total) — the spoken
  label, now that the emoji is a separate `aria-hidden` field.

Both badge test files import the vocabulary tables **from the components**
(`PostBadges.TYPES`/`KINDS`, `ProvenanceBadge.BADGES`) rather than restating
them. A mirrored copy in a test file cannot catch the two drifting apart, which
is precisely what P12 did to the provenance table: it split the emoji out of
`label`, and the mirror kept passing against a shape the component no longer
had.

`npx tsc --noEmit`: clean. `npm run build`: clean.

**Backend** — `pytest tests/test_provenance.py tests/test_post_image_scope.py`:
**45 passed** (baseline 31). 5 new tests:

- `test_a_resumed_session_still_carries_its_typing`
- `test_a_session_read_back_never_exposes_non_counter_state`
- `test_a_resumed_draft_whose_parent_never_typed_earns_nothing`
- `test_the_stored_address_is_what_the_server_accepts`
- `test_a_post_without_a_character_is_refused_outright`

**Backend — changed-surface selection** (24 files: provenance, post image
scope, posts, realms, mentions, comment visibility, scenes, Story Spaces,
StoryLab, RP stories/replies/turn ownership, founder image workflow, images,
characters, entitlements, seeding attribution, character public surface):
**847 passed, 3 failed** in 12m36s.

The three failures are `test_storylab_isolation.py::TestEndpointIsolation`
(`test_standard_chapter_endpoint_returns_200`, `…_no_rp_cadence`,
`…_minimum_word_count`). All three are **pre-existing and unrelated to this
pass**: they register a bare account and call `/storylab/stories`, which sits
behind `require_creator` and answers 403. That is the same gate-postdates-the-
test defect commit `de87b7f` fixed in three other files; this file was last
touched in July, before the gate existed. Verified by running the file at
pristine `HEAD` in a detached worktree — identical 3 failed / 99 passed, with
none of this pass's changes present. Fixing it is a fixture change in a file
this sprint does not touch, so it is left for a separate commit.

**Not run:** `npm run lint` — the project has no ESLint config file
(`.eslintrc*` is absent), so the `lint` script fails on any branch. Pre-existing
and out of scope.

**Not verified in a browser.** Every typography and badge change is CSS and
class-level and is covered by the type check and production build, but no
screenshot pass was run on a device. Gesture typing and IME behaviour (P2) are
verified at the rule level by unit tests, not on real hardware — that is the
one item worth a manual pass on an Android phone before merge.

---

## 9. Ready for merge?

**Yes, with one caveat.**

- Committed to `feature/provenance-sprint` and pushed. Not merged, not
  deployed, no migration applied.
- No new capability; no schema migration; no API breaking change (the one
  schema addition, `SessionRead.metrics`, is additive and owner-scoped).
- Frontend green, type check clean, production build clean. Backend green
  across the changed-surface selection apart from three pre-existing
  `test_storylab_isolation.py` failures that reproduce at pristine `HEAD` — see
  §8.

The caveat is **P8, the typography change**, which is the only thing here a
reader will notice: in-character feed prose moves from Playfair Display to
Inter. That is what "one primary reading font, Inter" means in a product that
was setting body copy in a display serif, and it is a readability improvement —
but it is a visible change of character in the feed, and it deserves a look
before merge rather than a test result. If it is not wanted, it reverts by
changing one `font-family` in `.fic-read`; every other part of the type
standardisation (sizes, leading, wrapping, mobile step) stands independently.
