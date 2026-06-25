import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app.utils.gating as gating


class _Settings:
    paywall_enabled = True
    paywall_native_enabled = True   # irrelevant once enabled; keep native gate off-path
    paywall_test_family_ids = set() # empty -> no family restriction -> reaches the tier read


def _gate_on(monkeypatch):
    monkeypatch.setattr(gating, "get_settings", lambda: _Settings())
    gating.set_native_app_flag(False)   # ensure native short-circuit doesn't fire


def test_is_premium_reads_tier_premium_true(monkeypatch):
    _gate_on(monkeypatch)
    assert gating.is_premium({"subscription_tier": "premium"}) is True


def test_is_premium_reads_tier_free_false(monkeypatch):
    _gate_on(monkeypatch)
    assert gating.is_premium({"subscription_tier": "free"}) is False


def test_is_premium_missing_tier_false(monkeypatch):
    _gate_on(monkeypatch)
    assert gating.is_premium({}) is False


def test_is_premium_none_tier_false(monkeypatch):
    _gate_on(monkeypatch)
    assert gating.is_premium({"subscription_tier": None}) is False


def test_is_premium_none_user_false(monkeypatch):
    _gate_on(monkeypatch)
    assert gating.is_premium(None) is False


def test_paywall_off_everyone_premium(monkeypatch):
    class _Off(_Settings):
        paywall_enabled = False
    monkeypatch.setattr(gating, "get_settings", lambda: _Off())
    gating.set_native_app_flag(False)
    assert gating.is_premium({"subscription_tier": "free"}) is True
