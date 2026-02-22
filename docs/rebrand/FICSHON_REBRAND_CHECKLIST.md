# Ficshon Rebrand Checklist

**Purpose:** Track the incremental rename from OwlQuill → Ficshon.
**Rule: Plan only. Do not execute any phase until the current release is stable and smoke-tested.**

---

## Phase 0 — Pre-flight

Do this before touching a single string.

**Steps**
1. Cut a git tag: `git tag pre-rebrand-snapshot`
2. Branch: `git checkout -b rebrand/ficshon`
3. Run the inventory grep and save output to `docs/rebrand/inventory.txt`:
   ```
   grep -rn "OwlQuill\|owlquill\|OWLQUILL\|owl-quill\|owl_quill\|owq" \
     --include="*.tsx" --include="*.ts" --include="*.css" \
     --include="*.html" --include="*.json" --include="*.md" \
     --include="*.env*" --include="*.yaml" --include="*.yml" .
   ```
4. Count occurrences per phase (UI text / meta / emails / ops) so each phase has a finite list.
5. Agree on QA smoke list before starting (see Completion Criteria).

**Don't**
- Don't rename env vars, DB labels, or the repo itself in this phase.
- Don't ship partial renames (OwlQuill and Ficshon coexisting in visible UI).

---

## Phase 1 — In-app UI Text

**Search targets**
```
OwlQuill    owlquill    owl-quill    owl_quill
text-owl-   bg-owl-     border-owl-   (Tailwind colour aliases — visual only, not text)
```
> Note: `owl-*` Tailwind classes are colour tokens, not brand text — leave them for a separate design-token pass after Phase 1 is stable.

**Files to touch**
- `frontend/src/**/*.tsx` — navbar logo text, page `<title>` strings rendered in JSX, empty-state copy, toast messages, banner copy
- `frontend/src/**/*.ts` — any hardcoded display strings

**Do**
- Replace visible display strings: `"OwlQuill"` → `"Ficshon"`
- Update `<title>` tags set via JSX/React Helmet (not the static `index.html` — that's Phase 2)
- Update `alt` text on logo images

**Don't**
- Don't change CSS class names (`owl-400`, `owl-600`, etc.) — that's a token rename, not a rebrand string
- Don't change API route paths or field names
- Don't touch email templates (Phase 3)

**Verification**
- [ ] Load home, character detail, profile, creation flow — no "OwlQuill" visible in UI
- [ ] Check browser tab titles on each major page
- [ ] Search rendered HTML in devtools for "OwlQuill"

---

## Phase 2 — Document Metadata

**Search targets**
```
OwlQuill    owlquill    og:site_name    twitter:site
```

**Files to touch**
- `frontend/index.html` — `<title>`, `<meta name="description">`, Open Graph tags, Twitter card tags
- `frontend/public/` — `manifest.json` (`name`, `short_name`), `robots.txt` if it references the old domain
- Favicon / logo assets — replace files, update `<link rel="icon">` href if filename changes

**Do**
- Update all `<meta>` brand references in one commit
- Replace or re-export logo/favicon assets under new filename if needed

**Don't**
- Don't change the domain itself here — that's an ops/DNS operation outside this repo
- Don't delete old favicon files until new ones are confirmed in production

**Verification**
- [ ] Unfurl link in Slack/Discord/iMessage — shows "Ficshon" name and correct image
- [ ] `<title>` in `view-source:` matches new name
- [ ] PWA install prompt shows "Ficshon"

---

## Phase 3 — Emails & Transactional Copy

**Search targets**
```
OwlQuill    owlquill    support@owlquill    noreply@owlquill
```

**Files to touch**
- Email template files (HTML/text) in `backend/` or external provider dashboard
- Sender name / reply-to configuration
- Any hardcoded support links inside templates

**Do**
- Update sender display name and reply-to in the provider dashboard (Postmark / SendGrid / etc.) in sync with template deploy
- Update unsubscribe footer copy

**Don't**
- Don't change email domains until DNS/SPF/DKIM records are updated for the new domain — deliverability risk
- Don't edit backend runtime logic, only copy strings

**Verification**
- [ ] Trigger a test transactional email — "From" field shows new name
- [ ] No "OwlQuill" in email subject, body, or footer
- [ ] Unsubscribe link resolves correctly

---

## Phase 4 — Ops, Labels & Repo

**Search targets**
```
OWLQUILL    OWL_QUILL    owlquill    OwlQuill
```

**Files to touch**
- `.env.example` / `env.template` — rename any `OWLQUILL_*` vars (coordinate with infra before deploy)
- `docker-compose.yml`, `*.yaml` — service labels, container names
- CI pipeline names (GitHub Actions workflow `name:` fields)
- `README.md` and other `docs/` references
- Repo name — GitHub repo rename is a separate org-level step; update any hardcoded clone URLs after

**Do**
- Rename env vars in lockstep: update `.env.example`, deployment secrets, and consuming code in one PR
- Update monitoring dashboard / alert names to match

**Don't**
- Don't rename a live env var without updating the deployment secret simultaneously — will break the running service
- Don't rename the GitHub repo until external links / CI badge URLs are updated

**Verification**
- [ ] `CI` pipeline passes with new env var names
- [ ] No `OWLQUILL` in `printenv` output on staging
- [ ] README renders correctly with new repo name / links

---

## Rollback Plan

| Trigger | Action |
|---|---|
| Visible regression in production | `git revert <rebrand-commit-sha>` + deploy |
| Partial deploy (old+new coexist) | Revert to `pre-rebrand-snapshot` tag: `git checkout pre-rebrand-snapshot` |
| Email deliverability drop | Revert provider sender config; DNS changes may need 24–48 h TTL to settle |
| Env var breakage | Restore previous secret values in deployment platform; redeploy last known-good image |

Keep the `pre-rebrand-snapshot` tag intact until all four phases are verified in production.

---

## Completion Criteria

- [ ] `grep -r "OwlQuill\|owlquill\|OWLQUILL" frontend/src` returns zero results in UI-visible strings
- [ ] All page `<title>` and Open Graph tags show "Ficshon"
- [ ] At least one full transactional email flow tested end-to-end
- [ ] CI green on rebrand branch; no TypeScript or lint errors
- [ ] QA sign-off: home, auth, character creation, profile, image generation flows smoke-tested
- [ ] `pre-rebrand-snapshot` tag retained in remote for 30 days post-launch
