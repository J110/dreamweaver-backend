# Auth Migration: Device-Anchored Identity (Username-Only, Magic-Link → Restore)

**Date:** 2026-05-29
**Status:** Design — awaiting owner review
**Spans:** `dreamweaver-web` (frontend) + `dreamweaver-backend` (backend)
**Relationship to paywall:** PREREQUISITE for Step 5 (restore/recovery). NOT flag-gated — this is a **live behavior change** for all users regardless of `PAYWALL_ENABLED`.

---

## 1. Problem

The live auth model is hybrid and inconsistent:
- `/login` still renders the **magic-link (email)** flow, which was conceptually scrapped.
- Onboarding does **username-only** login via `loginByUsername`, but on an unknown username it **404s and drops the user into token-less anon localStorage** — no `family_id`-bearing account.
- Saves/premium require `isLoggedIn()` = a token. Anon users have no token, so the heart bounces them to the stale magic-link `/login`.
- There is **no username path that creates a durable account** — the only token-minting path for a brand-new identity is magic-link, which we're removing from login.

This blocks the paywall: a paying user needs a durable account their subscription can attach to, and the restore design assumed username-only.

## 2. Decided model — device-anchored identity

Resolved with the owner (brainstorm Q1–Q3 + design Sections 1–2):

- **The durable identity is the device account:** server-minted `uid` + `family_id` (both UUIDs) + a session token, created at onboarding.
- **Username is a cosmetic label** on the record. Collisions allowed. Never queried for auth. Never gates premium.
- **Onboarding always creates a fresh device account** (create-only; the old find-existing-by-username login is removed — it was the impersonation vector). Each device gets a unique `family_id` regardless of username.
- **Premium attaches to `family_id`.** On the paying device it "just works" — no login.
- **Cross-device premium moves ONLY via email-verify restore** (Step 5): prove the Stripe billing email → re-anchor premium to the calling device's `family_id`. **Transfer model (one active premium device at a time)** — on restore the old account drops to free. Not multi-device.
- **The heart never sees a logged-out state** — every onboarded device holds a token.

## 3. Token lifecycle — sliding renewal + robust failure handling

### Sliding renewal
- Token rows carry `expires_at`. Each authenticated request slides `expires_at = now + 365d`.
- An active device effectively never expires. A device falls to cold restore only after **365 days of zero use** (`AUTH_TOKEN_DORMANCY_DAYS = 365`, single config constant). Stripe keeps billing through dormancy, so nothing is lost — a year-dormant premium device does one email-verify to re-anchor.
- Expired token rows are **retained until the 365d horizon** (so renewal can recognize them), then purged.

> **iOS caveat (load-bearing).** The 365d server-side TTL does NOT hold on iOS *web*: Safari/WKWebView ITP clears script-writable localStorage (where the token lives) after ~7 days inactivity / under storage pressure. So iOS web devices — including premium — lose the token and re-auth (→ email-restore for premium) far more often than 365d implies. **Web launch: accepted iOS-web limitation** (smaller segment; re-auth smoother post-migration). **Native iOS build: a named must-have** — store the token in the iOS Keychain and inject it into the webview so it survives ITP clearing (see native-build requirements). This migration does not solve iOS localStorage clearing; it only makes the re-auth graceful (silent re-mint / restore, no magic-link wall).

### Failure taxonomy (item 1 — the riskiest retarget)
Every authenticated-request failure is classified; **only an explicit backend "unrenewable" verdict bounces the user.** A transient blip must never send a paying device to restore.

| Failure | Classification | Action |
|---|---|---|
| Network error / timeout / **5xx** | TRANSIENT | Retry with backoff (≤2). Do NOT renew, do NOT fall through. Session intact. |
| **403 `premium_required`** | Paywall gate, not auth | Handle as gating (upgrade UX). Never triggers renewal. |
| **401 unauthorized** | Token rejected | Enter renewal flow ↓ |

### Renewal flow (on 401)
1. **Dedupe:** if a renewal is already in-flight, await it — N concurrent 401s trigger ONE renewal.
2. Call `POST /auth/renew` with the stored (possibly-expired) **token + family_id**. The stored *token* is required (proof of a prior real session) — `family_id` alone can never mint a token (closes the "leaked UUID → premium theft" hole). A fresh device with no token cannot renew.
3. Renew responses:
   - **200 `{token}`** — token row exists within the 365d window → store new token, **retry the original request once**. (A transient 401 with a still-valid token self-heals here.) Premium preserved (same `family_id`).
   - **410 `dormant_reauth_required`** — token row purged (>365d) or unrecognized → **the only fall-through trigger.** Premium device → `/restore`; free → silent fresh mint.
   - **5xx / network on `/auth/renew` itself** — TRANSIENT → back off, do NOT fall through; retry on next cycle.
4. **Loop guard:** at most one renew+retry per request cycle. If the original request still 401s after a *successful* renew (fresh token also rejected) → surface a generic error, do NOT loop, do NOT auto-bounce.

## 4. `/login` disposition + redirect retargeting

`/login` magic-link UI is **removed**; the route becomes a thin **silent-recovery router** (no email field):
- localStorage has `family_id` + token → attempt renewal → bounce home.
- No renewable token → `/onboarding` (fresh free) or `/restore` (premium recovery; Step 5).

Every current `/login` caller retargeted:

| Site | Today | After |
|---|---|---|
| `HeartButton.js:52` | → `/login` (magic-link) | Unreachable post-onboarding; defensively no-token → silent renew/mint, never a login wall |
| `AppShell.js:168` (`session_expired`) | → `/login` | Silent renewal first; only 410-dormant falls through |
| `api.js:65` (401) | → `/login` | Same renewal flow (§3) |
| `Header.js:79` "Log in" button | → `/login` | **Hidden** in this migration (no login concept). "Restore subscription" entry point ships with Step 5 (see §5) |
| `profile/page.js:78` | → `/login` | Silent renew, else onboarding |
| `auth/verify` page | magic-link code consumer | **Repurposed** as the email-code verify step for restore (Step 5) |

## 5. Magic-link → restore engine (boundary with Step 5)

The magic-link backend (`request_link` / `verify_link` / `poll`) **stays live**, repurposed as the **email-verify engine for restore only** — never login. `signup` / `login` remain 410.

**Restore (Step 5, not this migration):** email code → `recovery_email` stored from Stripe at checkout → on verify, premium re-anchors to the **calling device's** `family_id` (transfer; old account → free).

**Discoverability carry-forward (item 2):** a returning premium user on a fresh device is silently minted a free account (correct — fresh devices are free until restore). "Restore subscription" must be discoverable from that state. Since `/restore` is built in Step 5, this migration **hides** the login entry point; Step 5 ships the "Restore subscription" entry points (Header, Settings, upgrade screen) **together with** the `/restore` page so no link ever 404s. **Step 5 acceptance criterion:** restore is discoverable from Header + Settings + upgrade screen.

## 6. Existing-user migration

- **Magic-link users** (token + email + family_id): unchanged on their device; restore via email on new devices. Their verified email already powers restore.
- **Anon-localStorage users** (username, no token): on next load, silently mint a device account (stored username → cosmetic label). One-time, no user action. **No saves to migrate** — anon users could never save (saving requires a token; the heart bounced them), and there is no localStorage save mechanism (only prefs/lang/voice). Server-side saves simply begin once the account exists.
- **Premium re-anchoring: none needed.** Prod has 65 users — 64 free, 1 premium, and that one is the owner's own test account (`mohan.anmol@gmail.com`, `cus_UanwU8279Im0`), which **already has a `family_id`** (`7f361eb2…`). Zero real third-party premium users. Premium migration is a no-op.

## 7. Scope

**IN (this migration):**
- Backend: `POST /auth/device_account` (always-create: mint uid + family_id + token from a cosmetic username + child_age/lang). Remove find-existing-by-username login behavior.
- Backend: `POST /auth/renew` (token + family_id → fresh token or 410 dormant). Sliding `expires_at` on auth; retain expired rows to 365d.
- Frontend: onboarding always creates a device account (drop the 404→anon fallback).
- Frontend: silent device-account mint for legacy anon users on load.
- Frontend: `/login` → silent-recovery router (email UI removed); retarget all redirects (§4); robust 401 renewal (§3); hide the login entry point.

**OUT (→ Step 5):** `/restore` page, Stripe `recovery_email` capture (`billing.py`), email-verify→transfer logic, "Restore subscription" entry points. This migration only frees magic-link for restore and removes it from login.

**OUT (→ hygiene queue):** single-voice fallback, deploy-guard variant check, orphan re-link.

## 8. Scope-split safety (item 3)

Safe to ship **before** Step 5 exists. The only premium account (owner's test) is on its original device with a valid token, so it needs no `/restore`. New/anon users get free device accounts (no premium to restore). No user requires restore in the interim window between this migration and Step 5.

## 9. Verification — LIVE change, full test plan (item 4)

This is the **one deliberate live-behavior change** in the build — not a dark deploy. Verify all paths post-deploy (backend Docker rebuild + frontend build/PM2):

1. **New onboarding:** fresh browser → pick username → device account minted (token + family_id present) → lands home → heart saves successfully (server-side).
2. **Existing token-holder:** user with a current token → unaffected; normal use slides the token; no re-auth prompt.
3. **Anon upgrade:** user with `dreamvalley_anon_username` in localStorage but no token → on load, silent mint → token appears → can now save. No visible disruption.
4. **401 renewal — transient:** simulate a transient 401/5xx (e.g., backend blip) → device silently renews/retries → user continues, **not** bounced to restore, no loop.
5. **401 renewal — genuine dormancy:** token row purged (>365d / removed) → `/auth/renew` returns 410 → free device silently re-mints; premium device routed to `/restore` (Step 5; pre-Step-5 it lands on the silent-router fallback, acceptable since no real premium user is in this state).
6. **No bounce/loop anywhere:** confirm no redirect loop between `/login`, `/onboarding`, and authed pages under any of the above.
7. **deploy_guard:** snapshot before, verify after (YouTube-radio flag pre-existing/exempt).

## 10. Risks & rollback

- **Risk:** misclassifying a transient 401 as dormancy → §3 makes only an explicit 410 bounce; everything else retries.
- **Risk:** redirect loop → loop guard (one renew+retry per cycle) + silent-router idempotency.
- **Rollback:** frontend is a code deploy (revert commit + rebuild/PM2); backend endpoints are additive (revert + Docker rebuild). No data migration is destructive — anon upgrade only adds accounts; no existing record is mutated except sliding `expires_at`.
