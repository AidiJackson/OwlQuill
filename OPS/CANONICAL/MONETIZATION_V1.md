# OwlQuill Monetization Model

**Version:** 1.0
**Status:** Scaffold (Payments Not Yet Live)

## Overview

OwlQuill uses a trust-first monetization model with subscription tiers and optional AI credit packs. No advertisements. No attention selling.

## Subscription Tiers

### Free Tier

**Price:** $0/month

**Includes:**
- Full text-first creative platform
- Unlimited Characters
- Unlimited Realms
- Unlimited Scenes
- Unlimited Posts
- 3 AI image credits (lifetime trial)
- Community features

**Ideal for:** Writers who primarily work with text and want to try AI features.

---

### Creator Tier

**Price:** TBD (Coming Soon)

**Includes:**
- Everything in Free
- 50 AI image credits per month
- Priority support
- Early access to new features
- Creator badge on profile

**Ideal for:** Active storytellers who regularly use AI-assisted image generation.

---

### Studio Tier

**Price:** TBD (Coming Soon)

**Includes:**
- Everything in Creator
- 200 AI image credits per month
- Advanced tools (coming later):
  - Video snippet generation
  - Custom templates
  - Batch generation
- Studio badge on profile
- Direct feedback channel to development team

**Ideal for:** Power users, collaborative groups, and professional creators.

---

## AI Credits System

### What Are Credits?

AI credits are used for AI-assisted image generation (character portraits, scene illustrations, etc.).

**Credit Cost:**
- 1 standard image = 1 credit (exact pricing TBD)

### Credit Packs (One-Time Purchase)

For users who need more credits without a subscription upgrade:

| Pack | Credits | Price |
|------|---------|-------|
| Small | 20 credits | TBD |
| Medium | 60 credits | TBD |
| Large | 150 credits | TBD |

*Credit packs never expire.*

---

## Current Status

**Payments:** Not yet live
**Waitlist:** Available for Creator and Studio tiers

Users can join the waitlist to be notified when paid tiers become available.

---

## Technical Notes

- All plans data served via `/api/monetization/plans`
- User credits available via `/api/monetization/credits` (authenticated)
- `payments_enabled: false` until payment integration is complete
- No database migrations required for scaffold phase
