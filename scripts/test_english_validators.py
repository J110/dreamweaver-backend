"""Tests for scripts/_english_validators.py.

Fixtures locked from Task 1 ground-truth + Phase 2.1 post-deploy review.
Run via: python3 scripts/test_english_validators.py

10 tests:
  Must-fail (7): pre-Phase-2.1 baseline failures the floor catches.
  Must-pass (2): items that meet the post-Phase-2.1 bar uniformly.
  Partial  (1): cleanest 9-12 long_story under Phase 2.1, but with
                residual cap violations the regen loop in 2.3 will catch.

Note: Maris was Task 1's 9-12 gold standard but contains "acceptance"
(now universal-banned). It now sits in must-fail to document the floor
catching pre-Phase-2.1 register. The 9-12 must-pass slot is intentionally
empty — no Phase-2.1 9-12 long_story passes ALL hard checks on first
generation yet (Sylvi is the cleanest, with 2 sentence-cap residues).

Pass-cases tolerate `warning:` lines (soft signals) — only `major`
severities count as a true failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

from _english_validators import (
    validate_structured,
    has_major,
    VALIDATORS,
)

FIXTURES_PATH = Path(__file__).resolve().parent / "test_english_validators_fixtures.json"


def _load() -> dict:
    with open(FIXTURES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _content_type(item: dict) -> str:
    """Map fixture's `type` field to validator dispatch key."""
    t = item.get("type")
    if t == "story":
        return "short_story"
    if t == "long_story":
        return "long_story"
    return t  # unknown — caller will see VALIDATORS dispatch miss


def _err_strings(structured: list[dict]) -> list[str]:
    return [e["detail"] for e in structured]


# ─── must-FAIL fixtures ──────────────────────────────────────────────

def test_flutterby_fails():
    """0-1 short_story: somersaulted, butterflies, dandelion, lullaby +
    18-word sentence."""
    fx = _load()["gen-11c8a5d4ff16"]
    errors = validate_structured(_content_type(fx), fx)
    assert has_major(errors), f"expected major errors; got {errors}"
    msgs = " ".join(_err_strings(errors))
    # Spot-check a few specific banned tokens
    for tok in ("somersaulted", "butterflies", "lullaby"):
        assert f"'{tok}'" in msgs, f"expected banned word '{tok}' to be flagged"
    # Sentence cap should also fire (we know it has 18-word sentence)
    assert "sentence over cap:" in msgs, "expected sentence-cap violation"
    print("✓ test_flutterby_fails")


def test_sola_tides_fails():
    """0-1 long_story: 26-word sentence + rhythmic, melody, twinkled."""
    fx = _load()["gen-d1d9090e87f5"]
    errors = validate_structured(_content_type(fx), fx)
    assert has_major(errors), f"expected major errors; got {errors}"
    msgs = " ".join(_err_strings(errors))
    assert "sentence over cap:" in msgs
    # At least one of rhythmic/melody/twinkled should be banned
    banned_hit = any(
        f"'{tok}'" in msgs for tok in ("rhythmic", "melody", "twinkled", "scattered", "gathering")
    )
    assert banned_hit, f"expected at least one 0-1 banned-token hit in {msgs}"
    print("✓ test_sola_tides_fails")


def test_tuck_clover_fails():
    """2-5 short_story: 19-word sentence, multiple long words stacked."""
    fx = _load()["gen-7b207c25a434"]
    errors = validate_structured(_content_type(fx), fx)
    assert has_major(errors), f"expected major errors; got {errors}"
    msgs = " ".join(_err_strings(errors))
    assert "sentence over cap:" in msgs
    print("✓ test_tuck_clover_fails")


def test_mira_lumi_fails():
    """6-8 long_story: 34-word sentence + 'perhaps' (universal banned)."""
    fx = _load()["gen-2e9b43edbe06"]
    errors = validate_structured(_content_type(fx), fx)
    assert has_major(errors), f"expected major errors; got {errors}"
    msgs = " ".join(_err_strings(errors))
    assert "sentence over cap:" in msgs
    assert "'perhaps'" in msgs, f"expected universal banned 'perhaps' in {msgs}"
    print("✓ test_mira_lumi_fails")


def test_kestrel_fails():
    """9-12 long_story: 33-word sentence + many universal banned (loneliness,
    atmosphere, threatening, realization, possibility, misunderstood)."""
    fx = _load()["gen-bcbc176b01d9"]
    errors = validate_structured(_content_type(fx), fx)
    assert has_major(errors), f"expected major errors; got {errors}"
    msgs = " ".join(_err_strings(errors))
    assert "sentence over cap:" in msgs
    universal_hits = [
        tok for tok in ("loneliness", "atmosphere", "threatening", "realization",
                        "possibility", "misunderstood")
        if f"'{tok}'" in msgs
    ]
    assert len(universal_hits) >= 3, (
        f"expected ≥3 universal banned hits, got {universal_hits} in {msgs}"
    )
    print(f"✓ test_kestrel_fails  (banned hits: {universal_hits})")


def test_jade_lantern_fails():
    """9-12 short_story: 40-word sentence (ridiculous over-cap)."""
    fx = _load()["gen-beb0f3862024"]
    errors = validate_structured(_content_type(fx), fx)
    assert has_major(errors), f"expected major errors; got {errors}"
    msgs = " ".join(_err_strings(errors))
    assert "sentence over cap:" in msgs
    print("✓ test_jade_lantern_fails")


def test_maris_fails():
    """9-12 long_story Maris and the Moonlit Molt — Task 1 gold standard
    that fails Phase 2.1's higher bar. Body literally contains the phrase
    "a quiet song of acceptance" — `acceptance` is universal-banned per
    the Phase 2.1 floor. Documents the floor catching pre-Phase-2.1
    abstract-noun register."""
    fx = _load()["gen-64fdd62201b4"]
    errors = validate_structured(_content_type(fx), fx)
    assert has_major(errors), f"expected major errors; got {errors}"
    msgs = " ".join(_err_strings(errors))
    assert "'acceptance'" in msgs, (
        f"expected universal banned 'acceptance' to be flagged; got: {msgs}"
    )
    print("✓ test_maris_fails  (universal banned: 'acceptance' caught)")


# ─── must-PASS fixtures (gold standards) ─────────────────────────────


def test_bibo_passes():
    """0-1 long_story Bibo and the Gentle Rain Song — clean 0-1 sample.
    Longest sentence 7 words (under cap 8). No banned vocab in Task 1
    sample."""
    fx = _load()["gen-69a79bb17da1"]
    errors = validate_structured(_content_type(fx), fx)
    if has_major(errors):
        major_msgs = [e["detail"] for e in errors if e["severity"] == "major"]
        raise AssertionError(
            f"Bibo must not produce major errors; got: {major_msgs}"
        )
    print("✓ test_bibo_passes")


def test_glim_passes():
    """6-8 short_story Glim and the First Firefly — clean 6-8 sample.
    Longest sentence 9 words (under cap 16), no flagged vocab."""
    fx = _load()["gen-30999f1d21bc"]
    errors = validate_structured(_content_type(fx), fx)
    if has_major(errors):
        major_msgs = [e["detail"] for e in errors if e["severity"] == "major"]
        raise AssertionError(
            f"Glim must not produce major errors; got: {major_msgs}"
        )
    print("✓ test_glim_passes")


# ─── partial fixture (cap-only failures) ─────────────────────────────

def test_sylvi_partial():
    """9-12 long_story Sylvi and Orin and the Lighthouse — generated under
    Phase 2.1 prompts (2026-05-04). Cleanest 9-12 long_story we have, but
    has 2 sentences slightly over the 22-word cap (23 and 24 words). No
    other violations: clean banned-word check, no -ing stacking, no title
    override, no abstract-noun stacking.

    Documents:
    1. Sylvi's only failures are cap-related residue
    2. No vocabulary regression — validator confirms yesterday's
       qualitative review (PLAIN+RICH register, no banned vocab)
    3. The Phase 2.3 regen loop will catch these and produce a clean
       version on retry — exactly what the validator-driven retry
       pattern is for

    No 9-12 must-pass fixture is added; the slot stays empty until a
    future cron generates a 9-12 long_story that passes ALL hard checks
    on first attempt.
    """
    fx = _load()["gen-a0029af498f6"]
    errors = validate_structured(_content_type(fx), fx)
    major = [e for e in errors if e["severity"] == "major"]

    # 1. There must be major errors (otherwise this should be a must-pass)
    assert major, f"Sylvi expected to have at least one major cap violation; got none"

    # 2. EVERY major error must be a sentence-cap violation
    non_cap_major = [e for e in major if not e["detail"].startswith("sentence over cap:")]
    assert not non_cap_major, (
        f"Sylvi expected only cap violations; got non-cap major errors: "
        f"{[e['detail'] for e in non_cap_major]}"
    )

    # 3. Exactly 2 cap violations expected (23 + 24 word sentences)
    cap_violations = [e for e in major if e["detail"].startswith("sentence over cap:")]
    assert len(cap_violations) == 2, (
        f"Sylvi expected exactly 2 cap violations; got {len(cap_violations)}: "
        f"{[e['detail'] for e in cap_violations]}"
    )

    # 4. Both violations should be small overshoots (≤25 words at cap 22)
    import re as _re
    for e in cap_violations:
        m = _re.match(r"sentence over cap: (\d+) words", e["detail"])
        if m:
            n = int(m.group(1))
            assert 22 < n <= 25, (
                f"Sylvi cap violation should be small overshoot (23-25 words); "
                f"got {n}-word sentence: {e['detail']}"
            )

    print(f"✓ test_sylvi_partial  ({len(cap_violations)} cap violations, "
          f"all small overshoots, no other classes)")


# ─── Runner ──────────────────────────────────────────────────────────

ALL_TESTS = [
    test_flutterby_fails,
    test_sola_tides_fails,
    test_tuck_clover_fails,
    test_mira_lumi_fails,
    test_kestrel_fails,
    test_jade_lantern_fails,
    test_maris_fails,
    test_bibo_passes,
    test_glim_passes,
    test_sylvi_partial,
]


def main() -> int:
    print(f"Loading fixtures from {FIXTURES_PATH}")
    fx = _load()
    print(f"  {len(fx)} fixtures loaded\n")
    print(f"Running {len(ALL_TESTS)} tests...\n")
    failed = []
    for t in ALL_TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"✗ {t.__name__} FAILED: {e}")
            failed.append(t.__name__)
        except Exception as e:
            print(f"✗ {t.__name__} ERROR: {type(e).__name__}: {e}")
            failed.append(t.__name__)
    print()
    if failed:
        print(f"FAILED {len(failed)}/{len(ALL_TESTS)}: {failed}")
        return 1
    print(f"PASSED all {len(ALL_TESTS)} tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
