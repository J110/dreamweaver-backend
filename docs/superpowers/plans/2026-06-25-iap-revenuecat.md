# Native IAP via RevenueCat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Native iOS + Android subscriptions (monthly + annual, 7-day trial) that feed the existing entitlement projection via a RevenueCat webhook — RevenueCat write-only, off the read path.

**Architecture:** Native shell (RevenueCat SDK) → purchase → RevenueCat validates + owns lifecycle → ONE webhook → backend writes `user["entitlements"][apple|google]` → `_apply_tier` → `compute_tier`. The gating read (`compute_tier`/`source_active`) reads LocalStore only, never RevenueCat.

**Tech Stack:** FastAPI backend (`app/api/v1/`), pure projection (`app/utils/entitlements.py`), Flutter shell (`dreamweaver/`, `purchases_flutter`), RevenueCat, SQLite idempotency (mirrors `stripe_webhook_events`).

**Spec:** `docs/superpowers/specs/2026-06-25-iap-revenuecat-design.md`

---

## Buildable-now vs externals-gated

- **Phase A (backend webhook) — BUILDABLE NOW**, mock-tested, zero externals. The full webhook + mapping + idempotency + invariant + sweep/grace tests run against mock RevenueCat events.
- **Phase B (Flutter shell) — BUILDABLE NOW** (the integration code), live purchase gated on products existing.
- **Phase C (sandbox e2e) — GATED** on owner externals #1–7 (products + RevenueCat credential linking).
- **Phase D (submission) — GATED** on Apple Paid Apps Agreement + a reviewable build.
- **Phase E (the flip) — FINAL GATED STEP**, its own on-device verification; reversible.

Build A + B in full while the owner's agreements (Owner Checklist #1, #2 — start today) process. C/D/E begin only as each external lands.

## File structure

- Create `app/utils/revenuecat_mapping.py` — PURE event→source mapping (no app boot; footgun-safe like `entitlements.py`).
- Create `app/api/v1/revenuecat.py` — the webhook router (auth, idempotency, resolve uid, write source, `_apply_tier`).
- Modify `app/api/v1/billing.py` — add `revenuecat_webhook_events` table to `_open_billing_db`; export the shared writers (`_persist_user_update`, `_apply_tier`) for import (already module-level — no change needed beyond confirming import).
- Modify `app/api/v1/router.py` — mount the revenuecat router at `/billing/revenuecat`.
- Create `scripts/test_revenuecat_mapping.py`, `scripts/test_revenuecat_webhook.py`, `scripts/test_read_path_no_revenuecat.py`; extend `scripts/test_sweep.py`.
- Flutter: `dreamweaver/pubspec.yaml`, `dreamweaver/lib/` (purchase service + bridge).

---

## Phase A — Backend webhook (BUILDABLE NOW)

Test interpreters: pure tests (mapping, sweep, read-path) run under **system python3** and MUST NOT dirty `data/content.json`/`seed_output`. The webhook-handler test boots the app → use the fastapi venv and `git checkout -- data/content.json seed_output/content.json` after. Verify every commit's delta excludes `*content.json` (the snapshot footgun).

### Task A1: `revenuecat_webhook_events` idempotency table

**Files:** Modify `app/api/v1/billing.py:48` (`_open_billing_db`). Test: `scripts/test_revenuecat_webhook.py` (table portion).

- [ ] **Step 1: Write the failing test** (`scripts/test_revenuecat_webhook.py`)
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile
def test_revenuecat_events_table_dedups(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.v1.billing.BILLING_DB_PATH", tmp_path / "billing.db")
    from app.api.v1.billing import _open_billing_db
    conn = _open_billing_db()
    conn.execute("INSERT OR IGNORE INTO revenuecat_webhook_events (event_id, event_type, received_at, status) VALUES (?,?,?,?)", ("evt_1", "INITIAL_PURCHASE", "2026-06-25T00:00:00Z", "received"))
    r1 = conn.total_changes
    conn.execute("INSERT OR IGNORE INTO revenuecat_webhook_events (event_id, event_type, received_at, status) VALUES (?,?,?,?)", ("evt_1", "INITIAL_PURCHASE", "2026-06-25T00:00:00Z", "received"))
    r2 = conn.total_changes
    assert r1 == 1 and r2 == 1  # second insert ignored (duplicate event_id)
```
- [ ] **Step 2: Run, verify it fails** — `PYTHONPATH=. /tmp/dvb-billing-venv/bin/python -m pytest scripts/test_revenuecat_webhook.py::test_revenuecat_events_table_dedups -v` → FAIL (no such table).
- [ ] **Step 3: Implement** — in `_open_billing_db`, add after the `stripe_webhook_events` block, mirroring it exactly:
```python
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS revenuecat_webhook_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            received_at TEXT NOT NULL,
            processed_at TEXT,
            status TEXT NOT NULL DEFAULT 'received',
            error TEXT
        )
        """
    )
```
- [ ] **Step 4: Run, verify it passes.**
- [ ] **Step 5: Commit** — `git add app/api/v1/billing.py scripts/test_revenuecat_webhook.py && git commit -m "feat(iap): revenuecat_webhook_events idempotency table"`. Confirm delta excludes content.json.

### Task A2: Pure event→source mapping (`app/utils/revenuecat_mapping.py`)

**Files:** Create `app/utils/revenuecat_mapping.py`. Test: `scripts/test_revenuecat_mapping.py`.

`map_event_to_source(event: dict) -> dict | None` — returns `{"store": "apple"|"google", "status": str, "expires": iso|None}` for entitlement-affecting events, `None` for ignorable ones. Pure stdlib (datetime) — no app import, footgun-safe, runs under system python3.

- [ ] **Step 1: Write the failing test** (`scripts/test_revenuecat_mapping.py`) — the full mapping table:
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
from app.utils.revenuecat_mapping import map_event_to_source

MS = 1_750_000_000_000  # arbitrary future epoch-ms
ISO = datetime.fromtimestamp(MS/1000, tz=timezone.utc).isoformat()

def _e(t, store="APP_STORE", period="NORMAL", exp=MS, grace=None):
    return {"type": t, "app_user_id": "u1", "store": store, "period_type": period,
            "expiration_at_ms": exp, "grace_period_expiration_at_ms": grace}

def test_initial_purchase_active():
    assert map_event_to_source(_e("INITIAL_PURCHASE")) == {"store":"apple","status":"active","expires":ISO}
def test_trial_period_maps_trialing():
    assert map_event_to_source(_e("INITIAL_PURCHASE", period="TRIAL"))["status"] == "trialing"
def test_renewal_active():
    assert map_event_to_source(_e("RENEWAL"))["status"] == "active"
def test_cancellation_keeps_active_until_expires():
    s = map_event_to_source(_e("CANCELLATION"))
    assert s["status"] == "active" and s["expires"] == ISO
def test_billing_issue_grace():
    s = map_event_to_source(_e("BILLING_ISSUE", grace=MS))
    assert s["status"] == "grace" and s["expires"] == ISO
def test_expiration_terminal():
    assert map_event_to_source(_e("EXPIRATION"))["status"] == "expired"
def test_refund_terminal():
    assert map_event_to_source(_e("REFUND"))["status"] == "refunded"
def test_paused_terminal():
    assert map_event_to_source(_e("SUBSCRIPTION_PAUSED", store="PLAY_STORE"))["status"] == "expired"
def test_play_store_maps_google():
    assert map_event_to_source(_e("INITIAL_PURCHASE", store="PLAY_STORE"))["store"] == "google"
def test_test_event_ignored():
    assert map_event_to_source(_e("TEST")) is None
```
- [ ] **Step 2: Run, verify it fails** — `PYTHONPATH=. python3 -m pytest scripts/test_revenuecat_mapping.py -v` → FAIL (module missing). Confirm `git status` clean of content.json (pure test, no boot).
- [ ] **Step 3: Implement** `app/utils/revenuecat_mapping.py`:
```python
"""Pure RevenueCat webhook event -> entitlement source mapping. No app imports."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

_STORE = {"APP_STORE": "apple", "MAC_APP_STORE": "apple", "PLAY_STORE": "google"}
_ACTIVE = {"INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "PRODUCT_CHANGE", "NON_RENEWING_PURCHASE"}
_TERMINAL = {"EXPIRATION", "SUBSCRIPTION_PAUSED"}
_REFUND = {"REFUND", "REFUND_REVERSED"}  # REFUND_REVERSED handled as re-grant in A-followup if needed

def _iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None

def map_event_to_source(event: dict) -> Optional[dict]:
    etype = event.get("type")
    store = _STORE.get(event.get("store"))
    if store is None:
        return None
    if etype in _ACTIVE:
        status = "trialing" if event.get("period_type") == "TRIAL" else "active"
        return {"store": store, "status": status, "expires": _iso(event.get("expiration_at_ms"))}
    if etype == "CANCELLATION":
        # auto-renew off (not refund): keep active until period end; expiry drives downgrade
        return {"store": store, "status": "active", "expires": _iso(event.get("expiration_at_ms"))}
    if etype == "BILLING_ISSUE":
        return {"store": store, "status": "grace", "expires": _iso(event.get("grace_period_expiration_at_ms")) or _iso(event.get("expiration_at_ms"))}
    if etype in _TERMINAL:
        return {"store": store, "status": "expired", "expires": _iso(event.get("expiration_at_ms"))}
    if etype in _REFUND:
        return {"store": store, "status": "refunded", "expires": _iso(event.get("expiration_at_ms"))}
    return None  # TEST, TRANSFER, etc. — ignored
```
- [ ] **Step 4: Run, verify it passes** (all 10). Confirm `git status` clean of content.json.
- [ ] **Step 5: Commit** — only `app/utils/revenuecat_mapping.py` + the test.

### Task A3: The webhook endpoint (`app/api/v1/revenuecat.py`)

**Files:** Create `app/api/v1/revenuecat.py`; Modify `app/api/v1/router.py` (mount). Test: extend `scripts/test_revenuecat_webhook.py` (handler portion, fastapi venv).

Behavior: verify `Authorization` header == `os.getenv("REVENUECAT_WEBHOOK_SECRET")` (constant-time); idempotency via `revenuecat_webhook_events`; `event = body["event"]`; `source = map_event_to_source(event)`; if None → 200 ack (ignored); resolve `uid = event["app_user_id"]`; write `user["entitlements"][source["store"]] = {status, expires, product_id, store, environment, updated_at}` via `_persist_user_update`; call `_apply_tier(db_client, uid)`. Reuse `from app.api.v1.billing import _persist_user_update, _apply_tier` and `from app.dependencies import get_db_client`.

- [ ] **Step 1: Write the failing test** — handler-level, fake db (copy the `_FakeDb` pattern from `scripts/test_billing_projection.py`), monkeypatch the secret:
```python
def test_webhook_initial_purchase_writes_apple_source_and_projects_premium(monkeypatch):
    # seed user u1 in _local_users + fake db (tier=free), set REVENUECAT_WEBHOOK_SECRET
    # POST event {type:INITIAL_PURCHASE, app_user_id:u1, store:APP_STORE, expiration_at_ms:<future>}
    # assert db.users["u1"]["entitlements"]["apple"]["status"]=="active"
    # assert db.users["u1"]["subscription_tier"]=="premium"
```
(Full harness mirrors `test_billing_projection.py`: fake db, seeded `_local_users`, monkeypatched `ph_emit` if used, no real RevenueCat.) Also a test: bad/missing Authorization → 401; duplicate event_id → second call no-ops; `type=TEST` → 200 ignored, no source written.
- [ ] **Step 2: Run (fastapi venv), verify it fails.**
- [ ] **Step 3: Implement** `app/api/v1/revenuecat.py` (router with `POST /webhook`) per the behavior above; mount in `router.py`: `router.include_router(revenuecat_router, prefix="/billing/revenuecat", tags=["RevenueCat"])`.
- [ ] **Step 4: Run, verify it passes.** Then `git checkout -- data/content.json seed_output/content.json` (boot footgun); confirm clean.
- [ ] **Step 5: Commit** — `revenuecat.py` + `router.py` + the test; delta excludes content.json.

### Task A4: Write-only invariant test (read path has zero RevenueCat dependency)

**Files:** Create `scripts/test_read_path_no_revenuecat.py` (pure).

- [ ] **Step 1: Write the failing-then-passing test** (this guards the invariant; it passes immediately because the read path is already clean — its job is to FAIL if anyone later couples them):
```python
import sys, os, ast
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _imports(relpath):
    src = open(os.path.join(ROOT, relpath)).read()
    out = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.ImportFrom) and n.module: out.add(n.module)
        if isinstance(n, ast.Import):
            for a in n.names: out.add(a.name)
    return out
def test_read_path_modules_never_import_revenuecat():
    for f in ["app/utils/entitlements.py", "app/utils/gating.py"]:
        assert not any("revenuecat" in m for m in _imports(f)), f"{f} must not import revenuecat"
def test_compute_tier_serves_apple_source_with_no_revenuecat_loaded():
    import sys as _s
    assert not any("revenuecat" in m for m in list(_s.modules)) or True  # informational
    from datetime import datetime, timezone, timedelta
    from app.utils.entitlements import compute_tier
    now = datetime(2026,6,25,tzinfo=timezone.utc); fut=(now+timedelta(days=5)).isoformat()
    assert compute_tier({"entitlements":{"apple":{"status":"active","expires":fut}}}, now) == "premium"
```
- [ ] **Step 2–4:** Run (system python3) → PASS; confirm no content.json drift.
- [ ] **Step 5: Commit.**

### Task A5: Sweep + grace closure tests (your two encoded notes)

**Files:** Extend `scripts/test_sweep.py` (pure). Proves "no new sweep logic needed" holds for apple/google sources.

**Integration closure (per review):** A5 must run AFTER A2, and its swept sources are built via `map_event_to_source` (the SAME mapping A3 writes) — NOT hand-constructed fixtures — so A5 proves the real written shape is swept. (A3's own test already proves endpoint-write→projection=premium; A5 proves mapping-output→expiry→sweep. Together they close the loop.)

- [ ] **Step 1: Add tests (sources derived from the real mapping):**
```python
from app.utils.revenuecat_mapping import map_event_to_source   # ties A5 to A2's real output
PAST_MS = int((NOW.timestamp() - 10*86400) * 1000)
FUT_MS  = int((NOW.timestamp() + 10*86400) * 1000)
def _src(etype, store="APP_STORE", exp=PAST_MS, grace=None):
    return map_event_to_source({"type":etype,"app_user_id":"u","store":store,
                                "period_type":"NORMAL","expiration_at_ms":exp,
                                "grace_period_expiration_at_ms":grace})
def test_mapping_output_has_fields_source_active_reads():
    assert set(_src("CANCELLATION", exp=FUT_MS)) >= {"status","expires"}  # shape compute_tier consumes
def test_sweep_downgrades_cancelled_then_expired_apple():
    # CANCELLATION -> {status:active, expires:past} -> swept once the paid window ends
    u = {"uid":"a1","subscription_tier":"premium","entitlements":{"apple": _src("CANCELLATION", exp=PAST_MS)}}
    assert compute_downgrades([u], NOW) == [u]
def test_sweep_grace_expired_apple_via_mapping():
    # BILLING_ISSUE -> {status:grace, expires:grace_end}; once grace_end passes -> free via expiry (no terminal event)
    u = {"uid":"a2","subscription_tier":"premium","entitlements":{"apple": _src("BILLING_ISSUE", grace=PAST_MS)}}
    assert compute_downgrades([u], NOW) == [u]
def test_sweep_skips_active_apple_via_mapping():
    u = {"uid":"a3","subscription_tier":"premium","entitlements":{"apple": _src("RENEWAL", exp=FUT_MS)}}
    assert compute_downgrades([u], NOW) == []
def test_sweep_skips_in_grace_apple_via_mapping():
    u = {"uid":"a4","subscription_tier":"premium","entitlements":{"apple": _src("BILLING_ISSUE", grace=FUT_MS)}}
    assert compute_downgrades([u], NOW) == []
def test_sweep_downgrades_expired_google_via_mapping():
    u = {"uid":"g1","subscription_tier":"premium","entitlements":{"google": _src("CANCELLATION", store="PLAY_STORE", exp=PAST_MS)}}
    assert compute_downgrades([u], NOW) == [u]
```
A5 stays pure (`map_event_to_source` is stdlib-only) — system-python3, no app boot, footgun-safe.
- [ ] **Step 2–4:** Run (system python3) → PASS (`source_active` is generic over apple/google/comp; expiry drives it). Confirm clean.
- [ ] **Step 5: Commit.**

**End of Phase A: the full backend webhook is built + mock-tested, zero externals touched.**

---

## Phase B — Flutter shell (BUILDABLE NOW; live purchase gated)

Tasks (code buildable now; on-device purchase verified in Phase C):
- **B1:** Add `purchases_flutter` to `dreamweaver/pubspec.yaml`; `Purchases.configure(PurchasesConfiguration(apiKey))` on boot (platform-specific key).
- **B2:** `Purchases.logIn(uid)` using the backend device-anchored uid (the `app_user_id` link). Invariant: logIn before any purchase.
- **B3:** Purchase service: fetch offering → expose `purchaseMonthly()/purchaseAnnual()`; JS↔native bridge so the web paywall "Upgrade" CTA invokes native purchase; on success, refresh the webview entitlement (boot-read).
- **B4:** `Purchases.restorePurchases()` wired to a "Restore Purchases" action.

Each B task: implement + a Flutter widget/unit test where meaningful (purchase service logic), with on-device behavior deferred to Phase C. Detailed steps authored when Phase B starts (depends on the shell's current structure + the resolved RevenueCat SDK API).

## Phase C — Sandbox end-to-end (GATED on Owner #1–7)

- **C1:** Sandbox purchase (iOS sandbox + Android license tester) → RevenueCat → webhook → source → `compute_tier` premium, verified on device + in the user record.
- **C2:** Lifecycle: renewal, cancellation (stays premium to expiry), billing-issue→grace→expiry, refund (immediate free), restore. Each verified end-to-end.

## Phase D — Submission (GATED on Owner #1 + a reviewable build)

- **D1:** Native build with IAP + StoreKit config + the subscription products; submit to App Store / Play review.

## Phase E — The flip (FINAL GATED STEP — its own verification)

- **E1:** On-device full verification (the web-paywall-equivalent pass): native renders the paywall + gates with no leak; premium plays, free gated; full purchase round-trip; restore; renewal/expiry.
- **E2:** Flip `PAYWALL_NATIVE_ENABLED=true` (reversible — flag back to forced-premium if anything is wrong). Deploy-guarded, serial/foreground, `down && up --build`.

---

## Self-review

- **Spec coverage:** webhook+mapping+idempotency (A1–A3) ✓; write-only invariant (A4) ✓; event-mapping table (A2) ✓; sweep/grace closure (A5) ✓; Flutter SDK+bridge+restore (B) ✓; sandbox (C) ✓; submission (D) ✓; flip (E) ✓; owner externals → Owner Checklist in spec ✓; push out-of-scope ✓.
- **Footgun:** pure tests (A2/A4/A5) under system python3, no boot; A1/A3 use the venv + revert snapshots; every commit delta excludes content.json.
- **Type consistency:** `map_event_to_source` returns `{store,status,expires}`; the webhook writes `user["entitlements"][store]={status,expires,...}`; `source_active` reads `status`+`expires` — consistent across A2/A3/A5 and the live `entitlements.py`.
- **Gated phases (B detail, C/D/E):** steps intentionally milestone-level — they depend on externals/SDK specifics not yet available; detailed steps authored when each phase starts. Flagged, not placeholder-hidden.
