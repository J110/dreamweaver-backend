"""E2E tests for the restore_codes flow — 7 scenarios.

Tests at the service layer (direct calls to request_restore_code +
verify_restore_code), not HTTP. The HTTP layer (app/api/v1/restore.py)
is a thin pass-through; this tests the load-bearing logic.

Discipline:
  - Uses namespaced synthetic emails (e2e-restore-{N}@dreamvalley-test.local)
    that NEVER match real subscribers.
  - Seeds + tears down its own test users in LocalStore.
  - Bypasses real Resend (RESEND_API_KEY is checked; if set, ONE happy-path
    test will actually send; if you don't want that, run with `RESEND_API_KEY=`
    inline).
  - Inspects the restore_codes LocalStore row to recover the plaintext code
    when needed (test-script-only — the row stores HASHED code, but the
    test seeds via its own write path with a known plaintext).

Run from backend root:
  cd /opt/dreamweaver-backend && python3 scripts/test_restore_e2e.py

Exit 0 = all pass, non-zero = at least one failure.
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure we import from this repo, not anything stale.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.local_store import get_local_store  # noqa: E402
from app.services import restore_codes as rc  # noqa: E402


TEST_EMAIL_PREFIX = "e2e-restore"
TEST_EMAIL_DOMAIN = "dreamvalley-test.local"


def _test_email(slot: int) -> str:
    return f"{TEST_EMAIL_PREFIX}-{slot}-{int(time.time())}@{TEST_EMAIL_DOMAIN}"


def _seed_user(uid: str, email: str, family_id: str, recovery_email: str = None) -> dict:
    """Write a synthetic user record into LocalStore."""
    from app.dependencies import _local_users
    user_data = {
        "id": uid,
        "uid": uid,
        "username": f"e2e_{uid[:6]}",
        "username_lowercase": f"e2e_{uid[:6]}",
        "email": email,
        "family_id": family_id,
        "subscription_tier": "premium",
        "recovery_email": recovery_email or email,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "onboarding_complete": True,
    }
    store = get_local_store()
    store.collection("users").document(uid).set(user_data)
    _local_users[uid] = user_data
    return user_data


def _seed_code_directly(email_lc: str, family_id: str, code: str,
                        expires_in_seconds: int = 600,
                        attempts: int = 0,
                        used: bool = False) -> None:
    """Bypass the email step: write a restore_codes row with a KNOWN plaintext code."""
    import hashlib, secrets
    salt = secrets.token_hex(16)
    now = datetime.now(timezone.utc)
    row = {
        "email": email_lc,
        "family_id": family_id,
        "code_hash": hashlib.sha256(f"{salt}:{code}".encode()).hexdigest(),
        "salt": salt,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=expires_in_seconds)).isoformat(),
        "attempts": attempts,
        "used": used,
    }
    store = get_local_store()
    store.collection("restore_codes").document(email_lc).set(row)


def _cleanup_user(uid: str, email_lc: str) -> None:
    """Tombstone synthetic test user + restore_codes row + rate_limit row.

    LocalStore has no .delete() primitive (see magic_link._delete_auth_code).
    We tombstone instead: subscription_tier=free so the synthetic record
    can't ghost-premium, recovery_email cleared so it can't be re-targeted
    via restore, _e2e_deleted_at marker for audit + manual cleanup later.
    """
    from app.dependencies import _local_users
    store = get_local_store()
    try:
        store.collection("users").document(uid).update({
            "subscription_tier": "free",
            "recovery_email": "",
            "_e2e_deleted_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass
    _local_users.pop(uid, None)
    try:
        store.collection("restore_codes").document(email_lc).update({
            "used": True, "_e2e_deleted": True,
        })
    except Exception:
        pass
    try:
        store.collection("rate_limits").document(
            f"restore_send_{email_lc}"
        ).update({"timestamps": []})
    except Exception:
        pass


class TestRunner:
    def __init__(self):
        self.results = []
        self.synthetic = []  # [(uid, email)]

    def report(self, n: int, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((n, name, ok, detail))
        mark = "PASS" if ok else "FAIL"
        msg = f"[{mark}] Test {n}: {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)

    async def test_1_happy_path(self) -> None:
        """Seeded user with known code → verify returns claimed + token."""
        email = _test_email(1).lower()
        uid = f"e2e1-{int(time.time())}-{os.urandom(4).hex()}"
        family_id = f"fam-{uid[:8]}"
        _seed_user(uid, email, family_id, recovery_email=email)
        self.synthetic.append((uid, email))

        _seed_code_directly(email, family_id, "123456")
        result = rc.verify_restore_code(email, "123456")
        ok = (
            result.get("status") == "claimed"
            and bool(result.get("token"))
            and result.get("uid") == uid
            and result.get("family_id") == family_id
        )
        self.report(1, "happy path (claimed + token)", ok,
                    detail=f"status={result.get('status')}")

    async def test_2_wrong_code(self) -> None:
        """Wrong code; attempts < 3 returns invalid_or_expired, attempts increments."""
        email = _test_email(2).lower()
        uid = f"e2e2-{int(time.time())}-{os.urandom(4).hex()}"
        family_id = f"fam-{uid[:8]}"
        _seed_user(uid, email, family_id, recovery_email=email)
        self.synthetic.append((uid, email))

        _seed_code_directly(email, family_id, "111111")
        r1 = rc.verify_restore_code(email, "999999")
        r2 = rc.verify_restore_code(email, "888888")
        # After 3rd wrong attempt, code is killed (used=True). 4th returns invalid_or_expired
        # via the used path, not too_many_attempts.
        r3 = rc.verify_restore_code(email, "777777")
        r4 = rc.verify_restore_code(email, "111111")  # correct code, but code is dead now
        ok = (
            r1.get("status") == "invalid_or_expired"
            and r2.get("status") == "invalid_or_expired"
            and r3.get("status") == "invalid_or_expired"
            and r4.get("status") == "invalid_or_expired"  # correct code rejected — code is used after attempt 3
        )
        self.report(2, "wrong code (3x then correct → all rejected)", ok,
                    detail=f"r1={r1.get('status')} r2={r2.get('status')} r3={r3.get('status')} r4={r4.get('status')}")

    async def test_3_expired_code(self) -> None:
        """Code older than TTL → invalid_or_expired."""
        email = _test_email(3).lower()
        uid = f"e2e3-{int(time.time())}-{os.urandom(4).hex()}"
        family_id = f"fam-{uid[:8]}"
        _seed_user(uid, email, family_id, recovery_email=email)
        self.synthetic.append((uid, email))

        _seed_code_directly(email, family_id, "222222", expires_in_seconds=-60)
        result = rc.verify_restore_code(email, "222222")
        ok = result.get("status") == "invalid_or_expired"
        self.report(3, "expired code", ok, detail=f"status={result.get('status')}")

    async def test_4_rate_limit(self) -> None:
        """6th send-code within window → rate_limited."""
        email = _test_email(4).lower()
        uid = f"e2e4-{int(time.time())}-{os.urandom(4).hex()}"
        family_id = f"fam-{uid[:8]}"
        _seed_user(uid, email, family_id, recovery_email=email)
        self.synthetic.append((uid, email))

        # Clear rate_limit slot.
        try:
            get_local_store().collection("rate_limits").document(
                f"restore_send_{email}"
            ).set({"key": f"restore_send:{email}", "timestamps": []})
        except Exception:
            pass

        # Disable email send for speed.
        prev_resend_key = os.environ.get("RESEND_API_KEY")
        os.environ["RESEND_API_KEY"] = ""

        results = []
        for _ in range(5):
            results.append(await rc.request_restore_code(email))
        sixth = await rc.request_restore_code(email)

        if prev_resend_key is not None:
            os.environ["RESEND_API_KEY"] = prev_resend_key

        all_sent = all(r.get("status") == "sent" for r in results)
        sixth_blocked = sixth.get("status") == "rate_limited" and sixth.get("retry_after_seconds", 0) > 0
        ok = all_sent and sixth_blocked
        self.report(4, "rate limit (5 sent, 6th rate_limited)", ok,
                    detail=f"first_5_all_sent={all_sent} sixth={sixth.get('status')}")

    async def test_5_unknown_email_send(self) -> None:
        """send-code with unknown email → uniform 'sent', NO code generated."""
        email = _test_email(5).lower()  # no user seeded
        prev_resend_key = os.environ.get("RESEND_API_KEY")
        os.environ["RESEND_API_KEY"] = ""
        result = await rc.request_restore_code(email)
        if prev_resend_key is not None:
            os.environ["RESEND_API_KEY"] = prev_resend_key

        # No code row should have been written.
        store = get_local_store()
        doc = store.collection("restore_codes").document(email).get()
        no_code_written = not doc.exists
        uniform = result.get("status") == "sent"
        ok = uniform and no_code_written
        self.report(5, "unknown email (uniform sent, no code written)", ok,
                    detail=f"status={result.get('status')} code_written={not no_code_written}")

    async def test_6_cancelled_mid_flow(self) -> None:
        """Subscription cancelled between send and verify.
        Restore still succeeds (token=identity), backend entitlement remains
        the source of truth (subscription_tier=free). Token presence ≠ premium."""
        email = _test_email(6).lower()
        uid = f"e2e6-{int(time.time())}-{os.urandom(4).hex()}"
        family_id = f"fam-{uid[:8]}"
        # Seed as premium initially.
        _seed_user(uid, email, family_id, recovery_email=email)
        self.synthetic.append((uid, email))

        _seed_code_directly(email, family_id, "666666")

        # Simulate cancellation between send and verify by flipping tier.
        store = get_local_store()
        store.collection("users").document(uid).update({"subscription_tier": "free"})
        from app.dependencies import _local_users
        if uid in _local_users:
            _local_users[uid]["subscription_tier"] = "free"

        result = rc.verify_restore_code(email, "666666")

        # Verify still succeeds (token is identity, entitlement is separate).
        claimed = result.get("status") == "claimed" and bool(result.get("token"))

        # Confirm entitlement state on the user record is correctly 'free'.
        from app.dependencies import _local_users as live_users
        free_state = live_users.get(uid, {}).get("subscription_tier") == "free"

        ok = claimed and free_state
        self.report(6, "cancelled mid-flow (token issued, tier=free preserved)", ok,
                    detail=f"status={result.get('status')} tier={live_users.get(uid, {}).get('subscription_tier')}")

    async def test_7_replay(self) -> None:
        """Reused code → second verify returns invalid_or_expired."""
        email = _test_email(7).lower()
        uid = f"e2e7-{int(time.time())}-{os.urandom(4).hex()}"
        family_id = f"fam-{uid[:8]}"
        _seed_user(uid, email, family_id, recovery_email=email)
        self.synthetic.append((uid, email))

        _seed_code_directly(email, family_id, "777777")
        first = rc.verify_restore_code(email, "777777")
        second = rc.verify_restore_code(email, "777777")
        ok = (
            first.get("status") == "claimed"
            and second.get("status") == "invalid_or_expired"
        )
        self.report(7, "replay (first claimed, second invalid_or_expired)", ok,
                    detail=f"first={first.get('status')} second={second.get('status')}")

    async def test_8_no_subscription_leak(self) -> None:
        """Wrong-email path (no user, no code row) → no_subscription.
        Wrong-CODE path (real user) → invalid_or_expired, NOT no_subscription."""
        unknown = _test_email(8).lower()
        result_unknown = rc.verify_restore_code(unknown, "999999")
        unknown_ok = result_unknown.get("status") == "no_subscription"

        # Now a real user with a wrong code submission.
        email = _test_email(9).lower()
        uid = f"e2e8-{int(time.time())}-{os.urandom(4).hex()}"
        family_id = f"fam-{uid[:8]}"
        _seed_user(uid, email, family_id, recovery_email=email)
        self.synthetic.append((uid, email))
        _seed_code_directly(email, family_id, "555555")
        result_wrong = rc.verify_restore_code(email, "444444")
        wrong_ok = result_wrong.get("status") == "invalid_or_expired"

        ok = unknown_ok and wrong_ok
        self.report(8, "no_subscription leak ONLY on wrong-email (wrong-code stays uniform)", ok,
                    detail=f"unknown={result_unknown.get('status')} wrong_code={result_wrong.get('status')}")

    async def run_all(self) -> int:
        print("=== restore_codes E2E ===")
        try:
            await self.test_1_happy_path()
            await self.test_2_wrong_code()
            await self.test_3_expired_code()
            await self.test_4_rate_limit()
            await self.test_5_unknown_email_send()
            await self.test_6_cancelled_mid_flow()
            await self.test_7_replay()
            await self.test_8_no_subscription_leak()
        finally:
            for uid, email in self.synthetic:
                _cleanup_user(uid, email)
        passed = sum(1 for _, _, ok, _ in self.results if ok)
        total = len(self.results)
        print()
        print(f"=== {passed}/{total} passed ===")
        return 0 if passed == total else 1


if __name__ == "__main__":
    runner = TestRunner()
    sys.exit(asyncio.run(runner.run_all()))
