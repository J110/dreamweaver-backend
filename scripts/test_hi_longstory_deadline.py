"""Deadline-aware HI long-story retry loop — 2026-07-15 timeout post-mortem.

Proves, without any network call:
  1. repeated validator rejection stays within the 720s wall-clock budget
     and ADVANCES across fresh picks (no 5-attempt grind on one combo);
  2. attempts that cannot finish before the deadline are never launched;
  3. validator failures feed the next generation/repair prompt with explicit
     Hindi constraints (word floor, onomatopoeia, A3/A4 physiology, settling
     gestures) and carry across picks;
  4. a valid story is accepted and returned;
  5. existing validation rules are NOT relaxed (real validate_long_story
     still rejects each 2026-07-15 failure class).

Fake clock is injected by patching the `time` module attribute on the two
modules under test; the LLM is faked by patching `generate_json`.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import _hindi_generators as gen  # noqa: E402
import pipeline_run_hi as prh  # noqa: E402
from _hindi_validators import ONOMATOPOEIA, validate_long_story  # noqa: E402


class Clock:
    def __init__(self, t: float = 1_000.0):
        self.t = t

    def time(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


@pytest.fixture()
def clock(monkeypatch):
    c = Clock()
    fake_time = types.SimpleNamespace(time=c.time, sleep=lambda s: c.advance(s))
    monkeypatch.setattr(gen, "time", fake_time)
    monkeypatch.setattr(prh, "time", fake_time)
    monkeypatch.setenv("HINDI_QA_ENABLED", "false")  # no critic in these tests
    return c


BAD_DATA = {"full_text_roman": "kuch nahin hua", "full_text_deva": ""}


def _fake_generate_json(clock, seconds=70.0, data=None, captured=None):
    calls = {"n": 0}

    def fake(*, system, user, temperature, max_tokens, log_prefix=""):
        calls["n"] += 1
        if captured is not None:
            captured.append(user)
        clock.advance(seconds)
        return dict(data or BAD_DATA)

    return fake, calls


# ── 1+2. _llm_with_retry: attempt cap, real-validator rejection, deadline gate


def test_llm_retry_caps_attempts_and_carries_real_validator_errors(clock, monkeypatch):
    fake, calls = _fake_generate_json(clock)
    monkeypatch.setattr(gen, "generate_json", fake)
    with pytest.raises(gen.ValidationRetriesExhausted) as ei:
        gen._llm_with_retry(system="s", user="u", validator_key="long_story",
                            max_retries=2, deadline=clock.t + 480, log_prefix="")
    assert calls["n"] == 2  # capped at two attempts per pick
    # Real validate_long_story ran and rejected — rules not relaxed
    assert any("missing [PHASE_1]" in e for e in ei.value.errors)
    assert any("onomatopoeia" in e for e in ei.value.errors)


def test_llm_retry_never_launches_unfinishable_attempt(clock, monkeypatch):
    fake, calls = _fake_generate_json(clock, seconds=70)
    monkeypatch.setattr(gen, "generate_json", fake)
    # remaining 100s: attempt 1 launches (est 75 ≤ 100), eats 70s → remaining
    # 30s < observed 70s → attempt 2 must NOT launch.
    with pytest.raises(gen.GenerationDeadlineExceeded):
        gen._llm_with_retry(system="s", user="u", validator_key="long_story",
                            max_retries=5, deadline=clock.t + 100, log_prefix="")
    assert calls["n"] == 1
    # remaining below the floor estimate → zero attempts launched
    fake2, calls2 = _fake_generate_json(clock)
    monkeypatch.setattr(gen, "generate_json", fake2)
    with pytest.raises(gen.GenerationDeadlineExceeded):
        gen._llm_with_retry(system="s", user="u", validator_key="long_story",
                            max_retries=5, deadline=clock.t + 50, log_prefix="")
    assert calls2["n"] == 0


# ── 3. Validator failures feed the next prompt with Hindi constraints


TODAYS_FAILURES = [
    "only 1 onomatopoeia (need ≥2)",
    "physiology A3 FAIL: the long exhale is never rendered — no out-breath cue "
    "is described as long/slow (bare [BREATHE] swells are not enough)",
    "physiology A4 FAIL: no stillness/sleep terminal in the ending",
    "word count 594 below floor 600 for age 6-8 — write the full length, not a fragment",
    "settling-gesture tic: eyes close 3x — max 2 eye-closes per story; the same "
    "settling beat repeating 3+ times blurs it. Vary the gesture instead",
]


def test_repair_hint_states_explicit_hindi_constraints():
    hint = gen._long_story_repair_hint(TODAYS_FAILURES, {})
    assert hint is not None
    # word floor, with the age band's number
    assert "≥600 words" in hint and "age 6-8" in hint
    # onomatopoeia examples must come from the exact counted list
    assert "tip tip" in hint and "sarr" in hint
    for word in ("sarr", "tap tap", "tip tip", "jhoom", "thak thak"):
        assert word in ONOMATOPOEIA and word in hint
    # A3: long exhale rendered next to a [BREATHE] tag
    assert "[BREATHE]" in hint and "lambi" in hint and "dheere" in hint
    # A4: stillness terminals the validator counts
    assert "neend" in hint and "so gaya" in hint
    # settling-gesture cap + variation
    assert "aankhen band" in hint and "MOST 2" in hint
    # unknown-only errors → no hint (falls back to generic block)
    assert gen._long_story_repair_hint(["something unmapped"], {}) is None


def test_retry_prompt_carries_failures_and_seed_errors(clock, monkeypatch):
    captured: list[str] = []
    fake, calls = _fake_generate_json(clock, captured=captured)
    monkeypatch.setattr(gen, "generate_json", fake)
    with pytest.raises(gen.ValidationRetriesExhausted):
        gen._llm_with_retry(system="s", user="u", validator_key="long_story",
                            max_retries=2, deadline=clock.t + 480, log_prefix="",
                            repair_hint=gen._long_story_repair_hint)
    assert "PREVIOUS ATTEMPTS FAILED VALIDATION" not in captured[0]
    assert "PREVIOUS ATTEMPTS FAILED VALIDATION" in captured[1]
    assert "missing [PHASE_1]" in captured[1]          # cumulative failures
    assert "ONOMATOPOEIA" in captured[1] and "sarr" in captured[1]  # Hindi hint
    # seeded errors reach attempt 1 of a FRESH pick
    captured2: list[str] = []
    fake2, _ = _fake_generate_json(clock, captured=captured2)
    monkeypatch.setattr(gen, "generate_json", fake2)
    with pytest.raises(gen.ValidationRetriesExhausted):
        gen._llm_with_retry(system="s", user="u", validator_key="long_story",
                            max_retries=1, deadline=clock.t + 480, log_prefix="",
                            repair_hint=gen._long_story_repair_hint,
                            seed_errors=list(TODAYS_FAILURES))
    assert "PREVIOUS ATTEMPTS FAILED VALIDATION" in captured2[0]
    assert "only 1 onomatopoeia (need ≥2)" in captured2[0]


# ── 1+4. _generate_with_repick: budget, pick advancement, accept, terminal


def _patch_repick(monkeypatch, clock, generator):
    picks = {"n": 0}

    def fake_picker(catalog):
        picks["n"] += 1
        return {"age_group": "6-8", "mood": f"mood{picks['n']}",
                "world": f"W{picks['n']}", "world_name": f"W{picks['n']}",
                "characterType": "bird"}

    monkeypatch.setitem(prh.PICKERS, "long_story", fake_picker)
    monkeypatch.setitem(prh.GENERATORS, "long_story", generator)
    monkeypatch.setattr(prh, "load_hindi_catalog", lambda: [])
    return picks


def test_repeated_rejection_stays_within_budget_and_advances_picks(clock, monkeypatch):
    t0 = clock.t
    seen = {"calls": 0, "seeds": [], "kwargs": []}

    def always_reject(axes, log_prefix="", deadline=None, max_attempts=None,
                      seed_errors=None):
        seen["calls"] += 1
        seen["seeds"].append(seed_errors)
        seen["kwargs"].append((deadline, max_attempts))
        clock.advance(144)  # 2 attempts × 72s, mirrors 2026-07-15 pace
        raise gen.ValidationRetriesExhausted(
            "validator failed after 2 attempts",
            errors=["only 1 onomatopoeia (need ≥2)"])

    _patch_repick(monkeypatch, clock, always_reject)
    with pytest.raises(TimeoutError) as ei:
        prh._generate_with_repick("long_story", catalog=[])
    msg = str(ei.value)
    assert "exit=deadline" in msg and "picks_tried=3" in msg
    assert seen["calls"] == 3                    # 3 fresh combos, was 2 before
    assert clock.t - t0 <= prh.STORY_WALL_CLOCK  # never exceeds 720s
    # every pick got the capped attempt count and the text deadline
    for deadline, max_attempts in seen["kwargs"]:
        assert max_attempts == prh.ATTEMPTS_PER_PICK == 2
        assert deadline == pytest.approx(
            t0 + prh.STORY_WALL_CLOCK - prh.RENDER_RESERVE)
    # failures carried into picks 2 and 3
    assert seen["seeds"][0] is None
    assert seen["seeds"][1] == ["only 1 onomatopoeia (need ≥2)"]
    assert seen["seeds"][2] == ["only 1 onomatopoeia (need ≥2)"]


def test_accepts_valid_story_on_a_later_pick(clock, monkeypatch):
    calls = {"n": 0}

    def reject_then_accept(axes, log_prefix="", deadline=None, max_attempts=None,
                           seed_errors=None):
        calls["n"] += 1
        clock.advance(144)
        if calls["n"] == 1:
            raise gen.ValidationRetriesExhausted(
                "validator failed after 2 attempts",
                errors=["physiology A4 FAIL: no stillness/sleep terminal in the ending"])
        assert seed_errors and "physiology A4" in seed_errors[0]
        return {"id": "hi-long-test", "type": "long_story"}

    picks = _patch_repick(monkeypatch, clock, reject_then_accept)
    entry, axes = prh._generate_with_repick("long_story", catalog=[])
    assert entry["id"] == "hi-long-test"
    assert calls["n"] == 2 and picks["n"] >= 2   # advanced to a fresh combo


def test_generation_deadline_is_terminal_no_futile_repick(clock, monkeypatch):
    calls = {"n": 0}

    def deadline_inside(axes, log_prefix="", deadline=None, max_attempts=None,
                        seed_errors=None):
        calls["n"] += 1
        clock.advance(400)
        raise gen.GenerationDeadlineExceeded(
            "attempt=2/2 not launched: est=380s > remaining=80s")

    _patch_repick(monkeypatch, clock, deadline_inside)
    with pytest.raises(TimeoutError) as ei:
        prh._generate_with_repick("long_story", catalog=[])
    assert "exit=deadline" in str(ei.value)
    assert calls["n"] == 1  # no re-pick after a deadline signal


# ── 5. Existing validation rules are not relaxed (real validator, real rules)


def _long_story_dict(full: str, age: str = "6-8") -> dict:
    d = {
        "full_text_roman": full, "full_text_deva": "नींद",
        "age_group": age, "narrative_shape": "", "cast_structure": "",
        "title": "Test", "world_name": "W", "world_description": "",
        "mystery": "", "resolution": "", "repeated_phrase": "so ja",
        "characters": [],
    }
    for i, ph in enumerate(("PHASE_1", "PHASE_2", "PHASE_3"), 1):
        d[f"phase_{i}_text_roman"] = full  # validator joins these for lexicon checks
    return d


def test_validators_still_reject_todays_failure_classes():
    short = "[PHASE_1] kuch hua. [PHASE_2] aur hua. [PHASE_3] so gaya."
    errs = validate_long_story(_long_story_dict(short))
    assert any("below floor 600 for age 6-8" in e for e in errs)
    assert any("only 0 onomatopoeia (need ≥2)" in e for e in errs)
    assert any(e.startswith("physiology A3 FAIL") for e in errs)  # 0 [BREATHE]
    # A4: ending without any stillness terminal still fails
    no_still = short.replace("so gaya.", "phir subah aayi aur din shuru hua.")
    errs = validate_long_story(_long_story_dict(no_still))
    assert any("physiology A4 FAIL: no stillness/sleep terminal" in e for e in errs)
    # settling-gesture tic: 3× aankhen band still fails
    tic = short + " Usne aankhen band ki. Phir aankhen band ki. Fir se aankhen band ki."
    errs = validate_long_story(_long_story_dict(tic))
    assert any("settling-gesture tic: eyes close 3x" in e for e in errs)
