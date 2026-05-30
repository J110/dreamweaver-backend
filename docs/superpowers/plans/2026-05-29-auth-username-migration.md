# Device-Anchored Auth Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hybrid magic-link/username auth with device-anchored identity — onboarding always mints a durable device account (uid + family_id + 365d sliding token), username is cosmetic, premium rides on family_id, and `/login` stops being a magic-link wall.

**Architecture:** Two additive backend endpoints (`/auth/device_account`, `/auth/renew`) deploy first, fully backward-compatible. Then a frontend cutover routes onboarding + silent-mint + a 401-renewal interceptor through them and demotes `/login` to a silent router. This is a LIVE behavior change (NOT flag-gated) — deploy order and rollback safety are load-bearing.

**Tech Stack:** Backend FastAPI + LocalStore (JSON files in `data/`, Docker-volumed). Frontend Next.js 14, `localStorage` token (`dreamweaver_token`). Spec: `docs/superpowers/specs/2026-05-29-auth-username-migration-design.md`.

**Testing note:** Backend uses pytest-style `scripts/test_*.py` (precedent exists) — backend tasks are TDD. The **frontend has no test runner** (only `next dev/build/start`) and no existing frontend tests; adding a framework is out of scope (minimal-change norm). Frontend tasks therefore use **explicit runtime verification** (the spec §9 live tests) as their acceptance gate, with exact reproduction steps. Every frontend task lists its verification.

**Execution context:** Run in a dedicated git worktree. Backend and frontend live in separate repos (`dreamweaver-backend`, `dreamweaver-web`); commits go to each repo. Owner pushes (J110 account); see `reference_github_push_credential`.

---

## File Structure

**Backend (`dreamweaver-backend`):**
- `app/services/magic_link.py` — Modify: `SESSION_TTL` (30d→365d); add `_create_device_user()` next to `_create_user_with_email()` (line 205).
- `app/dependencies.py` — Modify: `_SESSION_TTL_SECONDS` (line 365, 30d→365d); add `AUTH_TOKEN_DORMANCY_DAYS`.
- `app/api/v1/auth.py` — Modify: add `POST /device_account`, `POST /renew`; repurpose `POST /login_username` to always-create.
- `scripts/test_auth_device_account.py` — Create (TDD).
- `scripts/test_auth_renew.py` — Create (TDD).

**Frontend (`dreamweaver-web`):**
- `src/utils/api.js` — Modify: add the 401-renewal interceptor + `authApi.deviceAccount()` + `authApi.renew()`.
- `src/utils/auth.js` — Modify: add `getStoredFamilyId()`.
- `src/app/onboarding/page.js` — Modify: always-create via `deviceAccount` (drop 404→anon fallback).
- `src/components/AppShell.js` — Modify: silent device-mint for legacy anon users; retarget `/login` redirects.
- `src/app/login/page.js` — Rewrite: magic-link UI → silent-recovery router.
- `src/components/Header.js`, `src/app/profile/page.js` — Modify: hide "Log in" entry (retarget per §4).

---

## PHASE A — Backend (additive, backward-compatible). Deploy + verify BEFORE Phase B.

### Task A1: Extend token TTL to 365-day sliding

**Files:**
- Modify: `app/services/magic_link.py:57`
- Modify: `app/dependencies.py:363-366`
- Test: `scripts/test_auth_token_ttl.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/test_auth_token_ttl.py`:
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
from app.services import magic_link as ml

def test_session_ttl_is_365_days():
    # SESSION_TTL drives the minted token's expires_at horizon.
    assert ml.SESSION_TTL.days == 365

def test_dependencies_ttl_matches():
    from app import dependencies as deps
    assert deps._SESSION_TTL_SECONDS == 365 * 24 * 3600
    assert deps.AUTH_TOKEN_DORMANCY_DAYS == 365
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dreamweaver-backend && python3 -m pytest scripts/test_auth_token_ttl.py -v`
Expected: FAIL — `SESSION_TTL.days == 30`, and `AttributeError: AUTH_TOKEN_DORMANCY_DAYS`.

- [ ] **Step 3: Make the change**

In `app/services/magic_link.py`, line 57:
```python
SESSION_TTL = timedelta(days=365)
```
In `app/dependencies.py`, replace lines 365-366:
```python
AUTH_TOKEN_DORMANCY_DAYS = 365
_SESSION_TTL_SECONDS = AUTH_TOKEN_DORMANCY_DAYS * 24 * 3600
_SESSION_REFRESH_GATE_SECONDS = 24 * 3600
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/test_auth_token_ttl.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/magic_link.py app/dependencies.py scripts/test_auth_token_ttl.py
git commit -m "feat(auth): 365-day sliding token TTL (device-anchored migration)"
```

---

### Task A2: `_create_device_user()` + `POST /auth/device_account`

**Files:**
- Modify: `app/services/magic_link.py` (add helper after `_create_user_with_email`, line ~248)
- Modify: `app/api/v1/auth.py` (add endpoint)
- Test: `scripts/test_auth_device_account.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/test_auth_device_account.py`:
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.local_store import get_local_store
from app.services import magic_link as ml
from app.dependencies import local_verify_token

def test_device_user_unique_uid_on_collision():
    store = get_local_store()
    a = ml._create_device_user(store, "spiderman", child_age=6, lang="en")
    b = ml._create_device_user(store, "spiderman", child_age=6, lang="en")
    # Same cosmetic username, but two SEPARATE accounts (no find-by-username).
    assert a["uid"] != b["uid"]
    assert a["family_id"] != b["family_id"]
    assert a["username"] == b["username"] == "spiderman"
    assert a["subscription_tier"] == "free"
    assert a["onboarding_complete"] is True
    assert "email" not in a

def test_device_account_token_validates():
    store = get_local_store()
    user = ml._create_device_user(store, "batman", child_age=8, lang="en")
    token = ml.mint_device_token(store, user["uid"])
    verified = local_verify_token(token)
    assert verified is not None
    assert verified["uid"] == user["uid"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/test_auth_device_account.py -v`
Expected: FAIL — `AttributeError: _create_device_user` / `mint_device_token`.

- [ ] **Step 3: Implement the helpers**

In `app/services/magic_link.py`, after `_create_user_with_email` (line 248), add:
```python
def _create_device_user(store, username: str, child_age=None, lang: str = "en") -> dict:
    """Mint a fresh device account. Username is a COSMETIC label — never
    queried for auth, collisions allowed. Each call creates a distinct
    account (uid + family_id). onboarding_complete=True (the device account
    IS onboarding). No email (email is captured only at Stripe checkout for
    restore). Mirrors _create_user_with_email; secrets.token_hex keeps the
    uid unique even when the username repeats.
    """
    uname = (username or "").strip()
    uid = hashlib.sha256(f"{uname}:{secrets.token_hex(8)}".encode()).hexdigest()[:28]
    family_id = str(uuid.uuid4())
    user_data = {
        "id": uid,
        "uid": uid,
        "username": uname,
        "username_lowercase": uname.lower(),
        "child_age": child_age,
        "preferred_lang": lang or "en",
        "subscription_tier": "free",
        "created_at": _now_iso(),
        "preferences": {},
        "family_id": family_id,
        "onboarding_complete": True,
    }
    store.collection("users").document(uid).set(user_data)
    try:
        from app.dependencies import _local_users
        _local_users[uid] = user_data
    except Exception:
        pass
    logger.info("Device account created: uid=%s family_id=%s username=%s", uid, family_id, uname)
    return user_data


def mint_device_token(store, uid: str) -> str:
    """Issue a fresh 365d sliding token for a uid and persist it."""
    import uuid as _uuid
    token = _uuid.uuid4().hex
    session_id = f"device-{_uuid.uuid4().hex[:8]}"
    _persist_token_row(store, token, uid, session_id)
    return token
```

- [ ] **Step 4: Add the endpoint**

In `app/api/v1/auth.py`, add (near `login_username`, after the body models):
```python
class DeviceAccountBody(BaseModel):
    username: str
    child_age: int | None = None
    lang: str = "en"


@router.post("/device_account")
async def device_account(body: DeviceAccountBody) -> dict:
    """Always-create a fresh device account + 365d token. Username is a
    cosmetic label (collisions fine). This is the ONLY mint path for new
    devices; there is no find-existing-by-username login (impersonation
    vector removed — see /login_username, now also always-create).
    """
    from app.services.local_store import get_local_store
    from app.services import magic_link as ml
    store = get_local_store()
    user = ml._create_device_user(store, body.username, child_age=body.child_age, lang=body.lang)
    token = ml.mint_device_token(store, user["uid"])
    return {
        "token": token,
        "user": {
            "uid": user["uid"],
            "username": user["username"],
            "family_id": user["family_id"],
            "child_age": user.get("child_age"),
            "preferred_lang": user.get("preferred_lang"),
            "subscription_tier": user.get("subscription_tier") or "free",
            "onboarding_complete": True,
        },
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest scripts/test_auth_device_account.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add app/services/magic_link.py app/api/v1/auth.py scripts/test_auth_device_account.py
git commit -m "feat(auth): POST /auth/device_account — always-create device account"
```

---

### Task A3: `POST /auth/renew` (sliding renewal + 410 dormant)

**Files:**
- Modify: `app/api/v1/auth.py`
- Test: `scripts/test_auth_renew.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/test_auth_renew.py`:
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from fastapi import HTTPException
from app.services.local_store import get_local_store
from app.services import magic_link as ml
from app.api.v1.auth import _renew_logic  # pure function under test

def test_renew_valid_token_mints_new():
    store = get_local_store()
    user = ml._create_device_user(store, "renew_ok", child_age=6, lang="en")
    old = ml.mint_device_token(store, user["uid"])
    result = _renew_logic(old, user["family_id"])
    assert result["token"] and result["token"] != old
    # New token validates for the same uid.
    from app.dependencies import local_verify_token
    assert local_verify_token(result["token"])["uid"] == user["uid"]

def test_renew_unknown_token_410():
    with pytest.raises(HTTPException) as exc:
        _renew_logic("deadbeef-not-a-real-token", "any-family-id")
    assert exc.value.status_code == 410
    assert exc.value.detail == "dormant_reauth_required"

def test_renew_family_id_mismatch_410():
    store = get_local_store()
    user = ml._create_device_user(store, "renew_mismatch", child_age=6, lang="en")
    tok = ml.mint_device_token(store, user["uid"])
    with pytest.raises(HTTPException) as exc:
        _renew_logic(tok, "wrong-family-id")
    assert exc.value.status_code == 410
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/test_auth_renew.py -v`
Expected: FAIL — `ImportError: cannot import name '_renew_logic'`.

- [ ] **Step 3: Implement renew logic + endpoint**

In `app/api/v1/auth.py`, add:
```python
class RenewBody(BaseModel):
    token: str
    family_id: str


def _renew_logic(token: str, family_id: str) -> dict:
    """Renew a session: the stored token (proof of a prior real session) +
    family_id are required. family_id alone can never mint — closes the
    leaked-UUID hole. Returns {token} on success; raises 410
    'dormant_reauth_required' when the token row is gone/unrecognized or the
    family_id doesn't match (the ONLY fall-through trigger per spec §3).
    """
    from datetime import datetime, timezone
    from app.services.local_store import get_local_store
    from app.services import magic_link as ml
    store = get_local_store()
    doc = store.collection("tokens").document(token).get()
    row = doc.to_dict() if doc.exists else None
    if not row or row.get("revoked_at"):
        raise HTTPException(status_code=410, detail="dormant_reauth_required")
    uid = row.get("uid")
    user_doc = store.collection("users").document(uid).get() if uid else None
    user = user_doc.to_dict() if (user_doc and user_doc.exists) else None
    if not user or (user.get("family_id") or "") != family_id:
        raise HTTPException(status_code=410, detail="dormant_reauth_required")
    # Expiry: legacy rows (no expires_at) are tolerated; expired rows fall through.
    exp = row.get("expires_at")
    if exp:
        try:
            if datetime.fromisoformat(exp) < datetime.now(timezone.utc):
                raise HTTPException(status_code=410, detail="dormant_reauth_required")
        except HTTPException:
            raise
        except Exception:
            pass
    new_token = ml.mint_device_token(store, uid)
    return {"token": new_token}


@router.post("/renew")
async def renew(body: RenewBody) -> dict:
    return _renew_logic(body.token, body.family_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest scripts/test_auth_renew.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/auth.py scripts/test_auth_renew.py
git commit -m "feat(auth): POST /auth/renew — 365d renewal, 410 on dormancy"
```

---

### Task A4: `login_username` → always-create (remove find-existing, mid-deploy compat)

**Files:**
- Modify: `app/api/v1/auth.py:156-229` (the `login_username` handler)
- Test: `scripts/test_auth_login_username_compat.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/test_auth_login_username_compat.py`:
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from app.api.v1.auth import login_username, LoginUsernameBody
from app.dependencies import local_verify_token

def test_login_username_always_creates_no_find_existing():
    # Two calls with the same username must yield DISTINCT accounts —
    # find-existing-by-username login is removed (impersonation vector).
    r1 = asyncio.get_event_loop().run_until_complete(
        login_username(LoginUsernameBody(username="compat_user", child_age=6, lang="en")))
    r2 = asyncio.get_event_loop().run_until_complete(
        login_username(LoginUsernameBody(username="compat_user", child_age=6, lang="en")))
    assert r1["token"] != r2["token"]
    assert r1["user"]["uid"] != r2["user"]["uid"]
    assert local_verify_token(r1["token"])["uid"] == r1["user"]["uid"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/test_auth_login_username_compat.py -v`
Expected: FAIL — current `login_username` 404s on an unknown username (raises HTTPException) and finds-existing on a known one.

- [ ] **Step 3: Replace the `login_username` body**

In `app/api/v1/auth.py`, replace the entire `login_username` function body (lines 156-229) with a delegation to always-create. Keep the route + `LoginUsernameBody` model so the cached old frontend keeps working during the deploy window:
```python
@router.post("/login_username")
async def login_username(body: LoginUsernameBody) -> dict:
    """DEPRECATED COMPAT SHIM. Find-existing-by-username login is removed
    (impersonation vector). Now always-creates a device account, identical
    to /auth/device_account, so a mid-deploy old-frontend session keeps
    working. Remove this route in a follow-up once no old frontend remains.
    """
    from app.services.local_store import get_local_store
    from app.services import magic_link as ml
    store = get_local_store()
    user = ml._create_device_user(store, body.username, child_age=body.child_age, lang=body.lang)
    token = ml.mint_device_token(store, user["uid"])
    return {
        "token": token,
        "user": {
            "uid": user["uid"],
            "username": user["username"],
            "family_id": user["family_id"],
            "child_age": user.get("child_age"),
            "preferred_lang": user.get("preferred_lang"),
            "subscription_tier": "free",
            "onboarding_complete": True,
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest scripts/test_auth_login_username_compat.py scripts/test_auth_device_account.py scripts/test_auth_renew.py scripts/test_auth_token_ttl.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/auth.py scripts/test_auth_login_username_compat.py
git commit -m "refactor(auth): login_username → always-create compat shim (no find-existing)"
```

---

### Task A5: Deploy + verify Phase A (backend, backward-compatible)

- [ ] **Step 1: Snapshot, push, rebuild** (owner pushes as J110)

```bash
# local: owner pushes commits
git push origin main
# on VM:
gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-c
cd /opt/dreamweaver-backend && python3 scripts/deploy_guard.py snapshot
git pull origin main
sudo docker-compose down && sudo docker-compose up -d --build
```

- [ ] **Step 2: Verify new endpoints live + old still works**

```bash
# device_account mints a token:
curl -s -X POST https://api.dreamvalley.app/api/v1/auth/device_account \
  -H 'Content-Type: application/json' -d '{"username":"verify_test","child_age":6,"lang":"en"}'
# Expect: {"token":"...","user":{"uid":...,"family_id":...}}

# renew with that token+family_id returns a new token:
curl -s -X POST https://api.dreamvalley.app/api/v1/auth/renew \
  -H 'Content-Type: application/json' -d '{"token":"<TOKEN>","family_id":"<FAMILY_ID>"}'
# Expect: {"token":"..."}  (different token)

# renew with junk token returns 410:
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://api.dreamvalley.app/api/v1/auth/renew \
  -H 'Content-Type: application/json' -d '{"token":"junk","family_id":"x"}'
# Expect: 410

# old login_username still responds (compat):
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://api.dreamvalley.app/api/v1/auth/login_username \
  -H 'Content-Type: application/json' -d '{"username":"compat","child_age":6,"lang":"en"}'
# Expect: 200
```

- [ ] **Step 3: deploy_guard verify**

Run on VM: `python3 scripts/deploy_guard.py verify`
Expected: invariants pass; only the pre-existing YouTube-radio flag.

Phase A is additive and backward-compatible — the existing frontend is unaffected (it doesn't call the new endpoints; `login_username` still 200s). Safe to leave live before Phase B.

---

## PHASE B — Frontend cutover. Deploy AFTER Phase A is verified live.

### Task B1: `authApi.deviceAccount` / `authApi.renew` + 401-renewal interceptor

**Files:**
- Modify: `src/utils/api.js`
- Modify: `src/utils/auth.js` (add `getStoredFamilyId`)

- [ ] **Step 1: Add `getStoredFamilyId` to auth.js**

In `src/utils/auth.js`, add:
```javascript
export const getStoredFamilyId = () => {
  if (typeof window === 'undefined') return null;
  try { return (JSON.parse(localStorage.getItem('dreamweaver_user') || 'null') || {}).family_id || null; }
  catch { return null; }
};
```

- [ ] **Step 2: Add the auth API methods (api.js, in `authApi`)**

```javascript
  deviceAccount: async (username, opts = {}) => {
    const res = await fetchApi('/api/v1/auth/device_account', {
      method: 'POST',
      body: JSON.stringify({ username, child_age: opts.child_age ?? null, lang: opts.lang || 'en' }),
    });
    return res; // { token, user }
  },
  renew: async (token, familyId) => {
    // silentRenew so a failing renew never recurses into the 401 interceptor.
    const res = await fetchApi('/api/v1/auth/renew', {
      method: 'POST',
      silentRenew: true,
      body: JSON.stringify({ token, family_id: familyId }),
    });
    return res; // { token }
  },
```

- [ ] **Step 3: Replace fetchApi's 401 branch with the renewal flow (§3)**

In `src/utils/api.js`, replace the `if (response.status === 401 && token) { ... }` block. Keep `silent401` (heart) and add `silentRenew` (the renew call itself) short-circuits, plus the dedup'd renewal:
```javascript
    if (response.status === 401 && token) {
      // Heart actions: never logout/redirect (shipped fix).
      if (options.silent401) { const e = new Error('unauthorized'); e.status = 401; throw e; }
      // The renew call itself must not recurse.
      if (options.silentRenew) { const e = new Error('renew_unauthorized'); e.status = 401; throw e; }

      // Try one dedup'd renewal before doing anything drastic.
      const { getStoredFamilyId } = await import('./auth');
      const familyId = getStoredFamilyId();
      if (familyId) {
        try {
          if (!fetchApi._renewPromise) {
            fetchApi._renewPromise = (async () => {
              const r = await authApi.renew(getAuthToken(), familyId); // throws on 410
              if (r && r.token) { setStoredToken(r.token); return r.token; }
              throw new Error('renew_no_token');
            })().finally(() => { setTimeout(() => { fetchApi._renewPromise = null; }, 0); });
          }
          await fetchApi._renewPromise;
          // Retry the original request ONCE with the fresh token (loop guard).
          if (!options._retried) {
            return fetchApi(endpoint, { ...options, _retried: true });
          }
        } catch (renewErr) {
          // 410 dormant (or no family_id path) → fall through to re-auth below.
        }
      }

      // Unrenewable / dormant: clear and route to the silent recovery router.
      // NOTE: /login is the SILENT ROUTER after Task B4 — NOT a magic-link wall.
      try { authLogout(); } catch { /* ignore */ }
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')
          && !window.location.pathname.startsWith('/auth/')) {
        window.location.href = '/login';
      }
      throw new Error('Session expired');
    }
```
Add a token-setter import at the top of api.js (or inline): `import { setToken as setStoredToken } from './auth';` (auth.js already exports `setToken`).

- [ ] **Step 4: Runtime verification (spec §9 steps 4 & 5)**

Cannot unit-test (no frontend runner). After Phase B deploy, verify on prod:
- **Transient self-heal:** with a valid session, a one-off 401 (or restart blip) → app continues, no bounce. (Observe: no redirect to `/login`, request succeeds on retry.)
- **Dormant fall-through:** with a token whose row was removed server-side, a required-auth call → `/auth/renew` 410 → routed to `/login` (silent router, Task B4), NOT a magic-link page.
- **No loop:** confirm at most one renew+retry; no redirect loop.

- [ ] **Step 5: Commit**

```bash
git add src/utils/api.js src/utils/auth.js
git commit -m "feat(auth): 401-renewal interceptor + device_account/renew API"
```

---

### Task B2: Onboarding always-creates a device account

**Files:**
- Modify: `src/app/onboarding/page.js:81-123` (the anon-submit branch)

- [ ] **Step 1: Replace the loginByUsername→404→anon branch**

Replace the `if (!authed) { ... }` block (the `loginByUsername` try + anon fallthrough) with an always-create:
```javascript
    if (!authed) {
      try {
        const res = await authApi.deviceAccount(trimmed, { child_age: numericAge, lang: selectedLang });
        if (res && res.token) {
          setToken(res.token);
          setUser({ ...(res.user || {}), onboarding_complete: true });
          try {
            localStorage.setItem('dreamvalley_anon_username', trimmed);
            localStorage.setItem('dreamvalley_child_age', childAge);
          } catch {}
          setLang(selectedLang);
          dvAnalytics.track('onboarding_complete', { childAge, username: trimmed, lang: selectedLang, logged_in: true });
          setLoading(false);
          router.replace('/');
          return;
        }
      } catch (err) {
        // Network error only — keep the user moving with a local username so
        // the app is usable offline; a device account mints on next load (B3).
      }
      try {
        localStorage.setItem('dreamvalley_anon_username', trimmed);
        localStorage.setItem('dreamvalley_child_age', childAge);
      } catch {}
      setLang(selectedLang);
      dvAnalytics.track('onboarding_complete', { childAge, username: trimmed, lang: selectedLang, anon: true });
      setLoading(false);
      router.replace('/');
      return;
    }
```

- [ ] **Step 2: Runtime verification (spec §9 step 1)**

After deploy: fresh browser (clear localStorage) → onboard with a username → confirm `localStorage.dreamweaver_token` and `dreamweaver_user.family_id` are set → land home → tap heart → saves successfully (no "Sign in to save").

- [ ] **Step 3: Commit**

```bash
git add src/app/onboarding/page.js
git commit -m "feat(auth): onboarding always-creates a device account"
```

---

### Task B3: Silent device-mint for legacy anon users on load

**Files:**
- Modify: `src/components/AppShell.js` (add a one-time effect)

- [ ] **Step 1: Add the silent-mint effect**

In `AppShell.js`, add an effect (runs once on mount, client-only):
```javascript
  const anonMintTried = useRef(false);
  useEffect(() => {
    if (anonMintTried.current) return;
    anonMintTried.current = true;
    if (typeof window === 'undefined') return;
    if (isLoggedIn()) return; // already has a token
    let username = '';
    try { username = localStorage.getItem('dreamvalley_anon_username') || ''; } catch {}
    if (!username) return; // not an onboarded anon user
    let age = null;
    try { age = parseInt(localStorage.getItem('dreamvalley_child_age') || '', 10) || null; } catch {}
    import('@/utils/api').then(({ authApi }) =>
      authApi.deviceAccount(username, { child_age: age, lang: undefined })
        .then((res) => {
          if (res && res.token) {
            setToken(res.token);
            setUser({ ...(res.user || {}), onboarding_complete: true });
          }
        })
        .catch(() => { /* offline — retry next load */ })
    );
  }, []);
```
Add imports at top of AppShell.js: `import { isLoggedIn, getToken, logout, setToken, setUser } from '@/utils/auth';` (extend the existing auth import).

- [ ] **Step 2: Runtime verification (spec §9 step 3)**

After deploy: in a browser that has `dreamvalley_anon_username` set but no `dreamweaver_token` (simulate a legacy anon user) → reload → confirm `dreamweaver_token` now appears, no visible disruption, heart saves work.

- [ ] **Step 3: Commit**

```bash
git add src/components/AppShell.js
git commit -m "feat(auth): silent device-account mint for legacy anon users on load"
```

---

### Task B4: `/login` → silent recovery router (remove magic-link UI)

**Files:**
- Rewrite: `src/app/login/page.js`

- [ ] **Step 1: Replace the page with a silent router**

Replace `src/app/login/page.js` entirely:
```javascript
'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { isLoggedIn, getToken, getStoredFamilyId, setToken } from '@/utils/auth';
import { authApi } from '@/utils/api';

export default function LoginRouter() {
  const router = useRouter();
  useEffect(() => {
    (async () => {
      if (isLoggedIn()) { router.replace('/'); return; }
      const familyId = getStoredFamilyId();
      const token = getToken();
      if (familyId && token) {
        try {
          const r = await authApi.renew(token, familyId);
          if (r && r.token) { setToken(r.token); router.replace('/'); return; }
        } catch { /* 410 dormant → fall through */ }
      }
      // No renewable session: send to onboarding (fresh free account).
      // Premium recovery lands here too until Step 5 ships /restore.
      router.replace('/onboarding');
    })();
  }, [router]);
  return null; // no UI — pure router
}
```

- [ ] **Step 2: Runtime verification**

After deploy: navigate to `/login` directly → must NOT show the email/"we sent a login link" UI; instead silently routes to `/` (if renewable) or `/onboarding`. Confirm the magic-link form is gone.

- [ ] **Step 3: Commit**

```bash
git add src/app/login/page.js
git commit -m "feat(auth): /login → silent recovery router (magic-link UI removed)"
```

---

### Task B5: Retarget remaining `/login` callers + hide the login entry

**Files:**
- Modify: `src/components/Header.js:79` (the "Log in" button)
- Modify: `src/app/profile/page.js:78`

- [ ] **Step 1: Hide the Header "Log in" entry**

In `src/components/Header.js`, remove/guard the "Log in" `<Link href="/login">` button — there is no login concept; the device auto-holds a token. (Step 5 adds a "Restore subscription" entry here.) Replace the button with nothing when `!isLoggedIn()` is the only case it showed for, or render nothing:
```javascript
// Removed the "Log in" button — device accounts are auto-held; no login.
```

- [ ] **Step 2: profile redirect**

In `src/app/profile/page.js:78`, the `router.push('/login')` now lands on the silent router (Task B4) — acceptable as-is (it will renew or send to onboarding). No change required beyond confirming it doesn't reference magic-link copy. Leave the redirect; the router handles it.

- [ ] **Step 3: Runtime verification (spec §9 steps 2 & 6)**

After deploy: existing token-holder uses the app normally — no re-auth prompt, no "Log in" button visible; navigate through Header/profile → no magic-link page, no redirect loop between `/login`, `/onboarding`, authed pages.

- [ ] **Step 4: Commit**

```bash
git add src/components/Header.js src/app/profile/page.js
git commit -m "feat(auth): retarget /login callers + hide login entry"
```

---

### Task B6: Heart silent401 regression check (spec §9 step 8)

**Files:** none (verification only — the shipped silent401 fix must still hold).

- [ ] **Step 1: Runtime verification**

After Phase B deploy: with a deliberately stale/cleared token, tap the heart → inline **"Sign in to save"**, **no logout, no `/login` bounce**. Confirm the B1 interceptor + B4 router did not reintroduce a heart→magic-link bounce (the `silent401` path short-circuits before any renewal/redirect).

- [ ] **Step 2: No commit** (assertion only). If it regresses, fix in `api.js`/`HeartButton.js` before proceeding.

---

## PHASE C — Deploy, verify, rollback

### Task C1: Deploy Phase B + full §9 verification

- [ ] **Step 1: Push + frontend build/PM2** (owner pushes J110)

```bash
git push origin main   # dreamweaver-web
# VM:
cd /opt/dreamweaver-web && git pull origin main
sudo npm run build
sudo cp -r public .next/standalone/public && sudo cp -r .next/static .next/standalone/.next/static
sudo pm2 restart dreamweaver-web
cd /opt/dreamweaver-backend && python3 scripts/deploy_guard.py verify
```

- [ ] **Step 2: Run the spec §9 test plan** — all 8 steps (new onboarding, existing token-holder, anon upgrade, transient 401, dormant 410, no bounce/loop, deploy_guard, heart silent401). Record pass/fail per step.

### Task C2: Rollback readiness (spec §9 "Rollback path & safety")

- [ ] **Step 1: Confirm rollback is a clean both-repos revert**

If §9 verification fails: `git revert` the Phase A + Phase B commits in BOTH repos, redeploy backend (Docker rebuild) + frontend (build/PM2). Device accounts minted during the live window SURVIVE — they're normal user/token rows in volumed `data/`; the reverted `local_verify_token` validates them (token row has uid + future `expires_at`; reverts to 30d TTL on next use). No account loss. Never partial-revert (new frontend calling `/auth/renew` against an old backend 404s) — revert both together.

---

## Self-Review

- **Spec coverage:** §2 device model → A2/B2; §3 sliding TTL → A1, 401 taxonomy/renewal → A3/B1, iOS caveat → noted (native-build, out of scope here); §4 `/login` + redirects → B4/B5; §5 magic-link-as-restore → magic-link backend left intact (untouched), only `/login` UI removed (B4); §6 existing-user migration → B3 (anon) + A1 (existing tokens slide to 365d), no premium re-anchor needed; §7 scope incl. remove find-by-username → A4; §8 scope-split safety → Phase A additive; §9 test plan → C1 + per-task runtime checks incl. step 8 → B6; rollback → C2; mid-deploy → A4 compat shim + Phase A-before-B ordering.
- **Out of scope (Step 5):** `/restore` page, Stripe `recovery_email`, transfer logic — referenced, not built here.
- **Placeholder scan:** none — every code step has complete code; runtime-verification steps have exact repro.
- **Type consistency:** `_create_device_user` / `mint_device_token` / `_renew_logic` signatures and the `{token, user:{uid,username,family_id,...}}` response shape are consistent across A2/A3/A4/B1/B2.
