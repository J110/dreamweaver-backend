# Native IAP via RevenueCat — Design Spec

**Date:** 2026-06-25
**Status:** Design approved; ready for task breakdown
**Depends on:** Deploy 2 (entitlement projection cutover) — LIVE on prod `8f15919`. `subscription_tier` is projection-derived; `compute_tier` already honors `user["entitlements"][apple|google|comp]`.

## Goal

Native in-app purchases on iOS + Android (auto-renewing monthly + annual subscriptions, 7-day trial) that feed the existing entitlement projection. The projection stays the single source of entitlement truth; RevenueCat is a **write-only** producer of entitlement sources, off the read/gating path.

## Hard invariant — RevenueCat is write-only, off the read path

The gating read is `compute_tier(user) → source_active(user["entitlements"][apple|google])`, which reads the source straight from the LocalStore user record and **never calls a RevenueCat API**. RevenueCat touches the system in exactly one place: its webhook *writes* the entitlement source.

Consequences (all must hold + be tested):
- A RevenueCat outage leaves every existing entitlement intact (already in our store). Only *new* purchases during the outage wait for the webhook — and RevenueCat retries failed webhooks, so they self-heal.
- No request that reads/serves entitlement (gating, playback, paywall decision) may make a synchronous RevenueCat call. **Test:** assert the read path (`compute_tier`/`gating.is_premium`) has zero RevenueCat dependency (no import of / call into the RevenueCat client on the read path).

## Architecture (the spine)

```
Native shell (StoreKit/Play via RevenueCat SDK)
    → purchase
RevenueCat (validates receipt, owns store lifecycle: ASSN V2 / RTDN point at RevenueCat)
    → ONE webhook event
Backend  POST /api/v1/billing/revenuecat/webhook
    → write user["entitlements"][apple|google] = {status, expires}
    → _apply_tier(uid)            # the existing SOLE subscription_tier writer
    → compute_tier → subscription_tier
Gating read  compute_tier → source_active(...)   # reads LocalStore only, never RevenueCat
```

RevenueCat is "another source-writer feeding `_apply_tier`," exactly analogous to how the Stripe webhook writes top-level fields then calls `_apply_tier`.

## The pieces

### 1. RevenueCat (configuration, not our code)
- One RevenueCat project; iOS app (bundle `com.vervetogether.dreamvalley`) + Android app.
- A `premium` entitlement mapped to both products; an offering with monthly + annual packages.
- Store credentials uploaded TO RevenueCat: Apple **App Store Connect API key (.p8)** (Key ID + Issuer ID) and Google **Play service-account JSON**. RevenueCat uses these to validate purchases and to receive store lifecycle notifications. *This .p8 is the App Store **Connect API** key for IAP — distinct from the APNs push .p8 (push is out of scope).* 
- Outputs we consume: the public SDK API keys (iOS + Android) for the shell, and the webhook **Authorization secret** for the backend.

### 2. Flutter shell (`dreamweaver/`) — greenfield IAP
- Add `purchases_flutter` (RevenueCat SDK).
- `Purchases.configure(apiKey)` on boot.
- **`Purchases.logIn(uid)`** with the backend device-anchored uid so RevenueCat `app_user_id` == our uid. This is the identity link that makes the webhook resolvable. **Invariant:** `logIn(uid)` must complete before any purchase; never purchase as an anonymous RevenueCat user.
- Purchase flow: fetch the offering → present monthly/annual → `purchasePackage(...)`. Triggered from the existing web paywall's "Upgrade" CTA via a JS↔native bridge (the paywall UI stays web; the purchase is native StoreKit/Play through RevenueCat).
- Restore: a "Restore Purchases" action → `Purchases.restorePurchases()` (App-Store-required; separate from the existing email-code `/auth/restore`).
- After purchase success: the backend has already received the webhook → source written → `subscription_tier` premium. The webview re-reads entitlement via the existing boot-read / a triggered refresh and unlocks. (No client-trust of entitlement — the client never asserts premium; it reflects what the projection serves.)

### 3. Backend — ONE new endpoint
`POST /api/v1/billing/revenuecat/webhook`
- **Auth:** verify the `Authorization` header against the configured RevenueCat webhook secret (constant-time compare). Reject otherwise.
- **Idempotency:** a `revenuecat_webhook_events` SQLite table keyed by RevenueCat event `id` (PRIMARY KEY), mirroring the existing `stripe_webhook_events` pattern in `billing.py`. Duplicate event id → no-op.
- **Resolve user:** `app_user_id` → uid → user record (reuse the `_find_user_by_*` lookup approach; here the lookup is by uid directly).
- **Write source:** `store` → key (`APP_STORE`→`apple`, `PLAY_STORE`→`google`); write `user["entitlements"][key] = {status, expires, product_id, store, environment, updated_at}` via `_persist_user_update`.
- **Recompute:** call the existing `_apply_tier(uid)` (the sole `subscription_tier` writer). The projection (`compute_tier`/`source_active`) does the rest.
- **No reads of entitlement happen here beyond what `_apply_tier` already does.**

### 4. Product configuration (stores)
- `com.vervetogether.dreamvalley.premium.monthly` and `.annual`, auto-renewing, in one subscription group; **7-day free trial** introductory offer on both (mirrors web). India-primary whole-number pricing (see Pricing). EN + Roman-Hindi store localizations.

## Event mapping — RevenueCat event → entitlement source

`source_active` treats `("active","trialing","grace","past_due")` as premium and `("revoked","refunded","expired")` as terminal; `expires=None` is perpetual (comp only), otherwise active iff `now < expires`.

| RevenueCat event | source `status` | source `expires` | Resulting tier |
|---|---|---|---|
| INITIAL_PURCHASE / RENEWAL / UNCANCELLATION / PRODUCT_CHANGE | `active` (or `trialing` if `period_type=TRIAL`) | event `expiration_at_ms` | premium |
| CANCELLATION (auto-renew off, not refund) | `active` (unchanged) | unchanged (keep until period end) | premium until `expires`, then free (sweep/projection) |
| BILLING_ISSUE (grace) | `grace` | `grace_period_expiration_at_ms` | premium during grace, then free |
| EXPIRATION | `expired` | event time | free |
| CANCELLATION w/ refund / REFUND / chargeback | `refunded` | event time | free immediately |
| SUBSCRIPTION_PAUSED (Google) | `expired` (treat paused as not-active) | event time | free (re-activates on resume event) |

This mirrors the Stripe semantics already in the projection (canceled-but-in-period stays premium until expiry; the daily downgrade sweep catches expired sources — no new sweep logic needed).

## The order (build sequence)

External owner setup (see Owner Checklist) runs in **parallel from day 1**. The code/build sequence:

1. **Backend webhook + source-writer + idempotency** — built and unit-tested against **mock RevenueCat events** (the full event-mapping table). No stores, no RevenueCat account needed.
2. **RevenueCat project + product/entitlement/offering + store-credential linking** (owner + me).
3. **Flutter shell**: SDK + `logIn(uid)` + purchase/restore + the JS↔native bridge.
4. **Sandbox end-to-end**: sandbox purchase → RevenueCat → webhook → source → `_apply_tier` → `compute_tier` premium; exercise renewal, cancel, billing-issue/grace, refund, restore.
5. **Submit** the native build (IAP + StoreKit config) for App Store / Play review.
6. **(separate gated step)** flip `PAYWALL_NATIVE_ENABLED` (see below).

The headline: **steps 1 and 3 (the bulk of the code) are built and tested before any external approval lands.** Externals gate only step 4 (live sandbox) and step 5 (submission).

## Owner checklist (external / account setup — ordered by lead time)

These are **owner actions with real lead time**, separate from the code tasks. Kick off #1 and #2 **today** so they finish while the code is built against mocks.

| # | Item | What the owner does | Gates | Rough lead time |
|---|---|---|---|---|
| 1 | **Apple Paid Apps Agreement + banking/tax** | App Store Connect → Agreements/Tax/Banking: accept the Paid Applications agreement, add bank account + tax forms | ANY IAP product, app-with-IAP submission | **Longest — START FIRST.** Hours to several days (bank/tax verification) |
| 2 | **Google Play merchant account** | Play Console → Payments profile: business + bank + tax | Play subscription products, Play Billing | Hours–days (merchant verification) |
| 3 | **Apple App Store Connect API key (.p8)** | App Store Connect → Users & Access → Integrations → generate key (in-app-purchase capable role); save Key ID, Issuer ID, the one-time .p8 download | RevenueCat validating Apple + ASSN | Minutes (after #1 account exists) |
| 4 | **Apple subscription products** | Create 2 auto-renew subs in one group, 7-day intro trial, price tiers, EN + Roman-Hindi localizations; get to "Ready to Submit" | RevenueCat offering, sandbox test | Minutes–hours (prices need #1 active) |
| 5 | **Google service-account JSON + products** | Link GCP project in Play Console; create service account + role; download JSON. Create 2 subscription products (monthly/annual base plans + 7-day free-trial offer), prices, EN + Roman-Hindi | RevenueCat validating Google + products | Minutes–hours |
| 6 | **Google RTDN** | Play Console → Monetization setup → paste the Pub/Sub topic RevenueCat provides | Live Google lifecycle events to RevenueCat | Minutes (after #7 project exists) |
| 7 | **RevenueCat project + linking** | Create project; add iOS (`com.vervetogether.dreamvalley`) + Android apps; upload the .p8 (Key/Issuer IDs) + the Play service JSON; configure `premium` entitlement + products + offering; copy out the SDK API keys + webhook secret | The whole live purchase + webhook flow | ~1 hour (after creds/products #3–5 exist) |
| 8 | **Store metadata + screenshots** | EN + Roman-Hindi descriptions, subscription localizations, screenshots at required sizes (iPhone 6.7″ = 1284×2778, iPad 13″ = 2048×2732) | Submission | Own prep time — start anytime, parallel |

## Pricing — INR-primary (DECIDED)

**Live web charge (Stripe `sk_live_`, fetched 2026-06-25 — source of truth for the WEB product):** Monthly `price_1Tbafu…` = $6.00/mo USD; Annual `price_1Tbc1c…` = $40.00/yr USD.

**IAP pricing — DECIDED: INR-primary, clean whole-number tiers.** Set the India price to a clean ₹ whole number (placeholders **~₹499/mo, ~₹3,499/yr**); other regions auto-convert from the INR base. Honors the no-`.99` rule and the India-primary intent.
- **Exact tier TBD at product-creation:** ₹499 / ₹3,499 snap to the nearest available App Store Connect / Play Console **INR** tier — confirm against the real Apple/Google INR ladders when creating the products (those tables aren't fetchable from here).
- **Sanity-check the auto-conversion:** confirm the INR base auto-converts to a sensible USD near $6/$40. If ~₹499 lands far off $6, add per-region tier overrides — but INR-primary-clean is the call.

**Web paywall display verified showing $6/$40 correctly** (the earlier `$9/$12` were Next.js RSC artifacts, not prices) — no web fix needed (see Out of scope).

## The `PAYWALL_NATIVE_ENABLED` flip — its own final gated step

The single biggest risk; **not bundled with the build.** It turns native from forced-premium (current: all native-UA forced premium for App Store compliance) into a real paywall: the `/upgrade` redirect goes live on native and native gating becomes real. It gets the same full verification the web paywall got, on a **real device**:
- Native renders the paywall + gates correctly, with no leak (the native equivalent of the web leak-checks).
- Premium content plays for entitled users; free content is gated.
- Full purchase round-trip on device: tap Upgrade → native RevenueCat purchase → webhook → source written → `_apply_tier` → `compute_tier` premium → content unlocks.
- Restore round-trip; renewal/expiry behavior over time.
- Only then flip the flag. **Reversible** — flag back to forced-premium if anything is wrong (the same dark-default safety the web paywall has).

## Out of scope (explicit)

- **Push notifications** — separate workstream, additive, NOT on the IAP critical path. The APNs `.p8` and any Firebase-config refresh stay there. **The IAP build ships with zero push dependency.**
- **Capacitor migration** — parked; the shell stays Flutter WebView for this build.
- New entitlement *semantics* — none. The projection already models everything (`source_active` by status + expiry). This build only *populates* the apple/google buckets.
- **Web paywall price display** — *verified correct during spec-writing.* The deployed web paywall (`PricingClient.js` on `b74a62e`) renders **$6/$40** matching Stripe live; `priceCurrency: USD`. The earlier `$9`/`$12` flag was a **false positive** — those are Next.js RSC serialization references (`$N` chunk refs in the Flight HTML payload, e.g. `{"__html":"$9"}`, `globalErrorComponent":"$12"`), not displayed prices. **No web price-fix needed.**

## Open items / risks

- **Pricing finalization** (owner) — see Pricing.
- **Identity edge cases** — anonymous→identified RevenueCat alias if `logIn(uid)` races a purchase; mitigated by enforcing `logIn` before purchase.
- **Sandbox fidelity** — sandbox renewal cadence is accelerated; validate grace/billing-issue paths explicitly.
- **App Review** — IAP apps draw extra review scrutiny (restore present, prices clear, no external-purchase steering). The flip step covers the on-device pass.
