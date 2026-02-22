# Handover: UX Onboarding & Discovery Sprint — 2026-02-22

**Product:** Ficshon (runtime still branded OwlQuill — no rebrand executed yet)
**Note:** The rebrand checklist lives at `docs/rebrand/FICSHON_REBRAND_CHECKLIST.md`; the name swap has not been applied to any runtime code.

---

## Branch Context

| Branch | Status |
|---|---|
| `chore/ficshon-rebrand` | **Active working branch.** All commits from today land here. |
| `feature/profile-redesign` | Earlier identity/UX work. This branch is the divergence point; today's branch is ahead of it by all commits listed below. |
| `main` | Behind both feature branches. |

`chore/ficshon-rebrand` branched from `feature/profile-redesign` at commit `3d5dcab` (rebrand checklist doc).

---

## UX Improvements Made Today

### Onboarding / Empty States
- **Welcome banner (Home)** — shown when user has zero characters; dismissible via `localStorage` key `ficshon.home_banner_dismissed`.
- **Characters empty-state CTA** — replaces blank list with a directed prompt to create a first character.
- **Images empty-state CTA** — replaces blank gallery with a directed prompt to generate a first image.
- **"Get started" card (Home)** — adaptive card shown when user has a character but no posts; guides toward first post action.

### Discovery & Engagement Nudges
- **Realms nudge in Home composer** — subtle prompt to post in a Realm instead of (or in addition to) Commons.
- **Post-success "Share in a Realm" nudge** — after a successful Commons post, surfaces a one-time nudge to cross-post to a Realm.
- **Realms page: join feedback states** — button switches to "Joined ✓" on success with in-place feedback.
- **Realms page: genre filter pills** — client-side filter bar; no network round-trip.
- **Realms page: post-join "Open realm" nudge** — after joining, inline prompt to navigate into the realm immediately.

### Readability & Navigation
- **Post readability** — `leading-relaxed` applied to post content `<p>` across Home, RealmDetail, SceneDetail; followed by `mt-1` top-margin for breathing room between metadata row and content.
- **Messages sidebar link** — added "Messages" nav item linking to `/messages`.
- **First-visit dot indicator** — emerald `w-2 h-2` dot on the Messages sidebar link until the user visits `/messages` once; cleared via `localStorage` key `ficshon.messages_seen`.

---

## Docs Created Today

| File | Purpose |
|---|---|
| `docs/rebrand/FICSHON_REBRAND_CHECKLIST.md` | Step-by-step checklist for executing the OwlQuill → Ficshon rename when ready |
| `docs/product/identity.md` | Product identity, positioning, and tone |
| `docs/product/beta_scope.md` | Beta feature scope and out-of-scope items |
| `docs/product/user_journey.md` | Core user journey map |
| `docs/product/current_focus.md` | Current sprint focus areas |
| `docs/safety/platform_rules.md` | Platform content rules |
| `docs/safety/age_and_content.md` | Age-gating and content policy |
| `docs/handover/2026-02-22-ux-onboarding-and-discovery.md` | This file |

---

## Key Tags Created Today

Tags follow the pattern `fic-checkpoint-<feature>-2026-02-22`. Milestone tags in chronological order:

| Tag | Commit | Description |
|---|---|---|
| `fic-checkpoint-rebrand-plan-doc-2026-02-22` | `3d5dcab` | Rebrand checklist doc (branch point from `feature/profile-redesign`) |
| `fic-checkpoint-onboarding-banner-done-2026-02-22` | `81ff434` | Welcome banner complete |
| `fic-checkpoint-onboarding-empty-characters-cta-2026-02-22` | `c45aca1` | Characters empty-state CTA |
| `fic-checkpoint-onboarding-empty-images-cta-2026-02-22` | `49cde33` | Images empty-state CTA |
| `fic-checkpoint-onboarding-home-get-started-2026-02-22` | `b9b4892` | Adaptive get-started card |
| `fic-checkpoint-ux-realms-join-feedback-2026-02-22` | `5b24ff9` | Realms join feedback states |
| `fic-checkpoint-ux-realms-genre-filter-2026-02-22` | `b88478c` | Genre filter pills |
| `fic-checkpoint-ux-realms-post-join-nudge-2026-02-22` | `e6d9592` | Post-join "Open realm" nudge |
| `fic-checkpoint-ux-post-leading-relaxed-2026-02-22` | `70ac7a0` | Post readability (leading-relaxed) |
| `fic-checkpoint-ux-sidebar-messages-link-2026-02-22` | `edaca54` | Messages sidebar link |
| `fic-checkpoint-ux-messages-dot-2026-02-22` | `2c9cfb8` | First-visit dot indicator |
| `fic-checkpoint-ux-post-mt-1-2026-02-22` | `912b83c` | Post content top margin (HEAD) |

---

## Next Steps

### Merge Plan Options

Two reasonable paths — do **not** merge without review:

1. **PR: `chore/ficshon-rebrand` → `feature/profile-redesign`**
   Keeps all UX/onboarding work consolidated on the profile-redesign branch before hitting main. Good if profile-redesign still has in-flight work to finish.

2. **PR: `chore/ficshon-rebrand` → `main`**
   Direct promotion if `feature/profile-redesign` is considered stable and already reviewed. Cleaner history, skips an intermediate merge.

Either way: squash-merge or rebase to keep history readable; the per-feature tags already provide fine-grained rollback points.

### Recommended Next UX Lane

**Messaging polish** — the infrastructure is in place (`/messages`, `ConversationsList`, `ConversationThread`) but the experience is bare. Suggested specifics:
- Unread count badge on the sidebar Messages link (backend already tracks `updated_at`; can approximate unread client-side)
- Empty state in `ConversationThread` for brand-new conversations
- "New message" affordance visible from the Characters detail page (start a convo from a character profile)

This lane is self-contained, high-visibility, and directly rewards the discoverability work done today.
