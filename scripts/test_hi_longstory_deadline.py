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
import tempfile
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
    fake_time = types.SimpleNamespace(time=c.time, sleep=lambda s: c.advance(s),
                                      strftime=lambda fmt: "2026-07-15T00:00:00")
    monkeypatch.setattr(gen, "time", fake_time)
    monkeypatch.setattr(prh, "time", fake_time)
    monkeypatch.setenv("HINDI_QA_ENABLED", "false")  # no critic in these tests
    return c


BAD_DATA = {"full_text_roman": "kuch nahin hua", "full_text_deva": ""}


def _fake_generate_json(clock, seconds=70.0, data=None, captured=None):
    calls = {"n": 0}

    def fake(*, system, user, temperature, max_tokens, log_prefix="", deadline=None):
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
    "physiology A1 FAIL: arousal rises in back half (back=1.23 > open=0.00)",
    'only 0 NAME: "..." dialogue lines (need ≥3); do not embed dialogue inside '
    "narration prose",
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
    # A1: back-half arousal constraint
    assert "CALM BACK HALF" in hint and "achanak" in hint
    # dialogue-format constraint
    assert "DIALOGUE FORMAT" in hint and 'NAME: "..."' in hint
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
                      seed_errors=None, render_budget=None):
        seen["calls"] += 1
        seen["seeds"].append(seed_errors)
        seen["kwargs"].append((deadline, max_attempts, render_budget))
        # Mirror _llm_with_retry's internal gate: 72s attempts (2026-07-15
        # pace), 75s floor estimate, no attempt launched past the deadline.
        for _ in range(max_attempts):
            if deadline - clock.t < 75:
                raise gen.GenerationDeadlineExceeded(
                    "attempt not launched: est=75s > remaining")
            clock.advance(72)
        raise gen.ValidationRetriesExhausted(
            "validator failed after 2 attempts",
            errors=["only 1 onomatopoeia (need ≥2)"])

    _patch_repick(monkeypatch, clock, always_reject)
    with pytest.raises(TimeoutError) as ei:
        prh._generate_with_repick("long_story", catalog=[])
    msg = str(ei.value)
    assert "exit=deadline" in msg
    # Full 720s text budget: 5 fresh combos explored (was 2 on 2026-07-15)
    assert seen["calls"] == 5
    assert clock.t - t0 <= prh.STORY_WALL_CLOCK  # text loop never exceeds 720s
    # every pick got the capped attempt count, the FULL text budget as its
    # deadline, and the render budget
    for deadline, max_attempts, render_budget in seen["kwargs"]:
        assert max_attempts == prh.ATTEMPTS_PER_PICK == 2
        assert deadline == pytest.approx(t0 + prh.STORY_WALL_CLOCK)
        assert render_budget == prh.RENDER_BUDGET
    # failures carried into every later pick
    assert seen["seeds"][0] is None
    for s in seen["seeds"][1:]:
        assert s == ["only 1 onomatopoeia (need ≥2)"]


def test_accepts_valid_story_on_a_later_pick(clock, monkeypatch):
    calls = {"n": 0}

    def reject_then_accept(axes, log_prefix="", deadline=None, max_attempts=None,
                           seed_errors=None, render_budget=None):
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
                        seed_errors=None, render_budget=None):
        calls["n"] += 1
        clock.advance(400)
        raise gen.GenerationDeadlineExceeded(
            "attempt=2/2 not launched: est=380s > remaining=80s")

    _patch_repick(monkeypatch, clock, deadline_inside)
    with pytest.raises(TimeoutError) as ei:
        prh._generate_with_repick("long_story", catalog=[])
    assert "exit=deadline" in str(ei.value)
    assert calls["n"] == 1  # no re-pick after a deadline signal


# ── Item 1 (review): pick 2's FIRST attempt gets the surgical FORWARD
# CONSTRAINTS from the seeded (cumulative) errors, not just the generic block


def test_seeded_first_attempt_gets_forward_constraints(clock, monkeypatch):
    captured: list[str] = []
    fake, _ = _fake_generate_json(clock, captured=captured)
    monkeypatch.setattr(gen, "generate_json", fake)
    with pytest.raises(gen.ValidationRetriesExhausted):
        gen._llm_with_retry(system="s", user="u", validator_key="long_story",
                            max_retries=1, deadline=clock.t + 480, log_prefix="",
                            repair_hint=gen._long_story_repair_hint,
                            seed_errors=list(TODAYS_FAILURES))
    first_prompt = captured[0]
    assert "FORWARD CONSTRAINTS" in first_prompt        # surgical hint present
    assert "ONOMATOPOEIA" in first_prompt and "tip tip" in first_prompt
    assert "≥600 words" in first_prompt                 # word-floor constraint
    assert "[BREATHE]" in first_prompt                  # A3 constraint
    assert "neend" in first_prompt                      # A4 constraint
    assert "MOST 2" in first_prompt                     # settling-gesture cap
    assert "CALM BACK HALF" in first_prompt             # A1 constraint
    assert "DIALOGUE FORMAT" in first_prompt            # NAME: "..." constraint


# ── Item 2 (review): deadline propagation into _hindi_llm provider calls


import _hindi_llm as llm  # noqa: E402


@pytest.fixture()
def llm_clock(monkeypatch):
    c = Clock()
    sleeps: list[float] = []

    def _sleep(s):
        sleeps.append(s)
        c.advance(s)

    fake_time = types.SimpleNamespace(time=c.time, sleep=_sleep)
    monkeypatch.setattr(llm, "time", fake_time)
    monkeypatch.setattr(llm, "MISTRAL_KEY", "mk")
    monkeypatch.setattr(llm, "GROQ_KEY", "gk")
    c.sleeps = sleeps
    return c


def _fake_hard_timeout(clock, behaviors):
    """behaviors: list of (advance_seconds, result_or_exception) per call."""
    calls: list[dict] = []

    def fake(fn, seconds, **kwargs):
        i = min(len(calls), len(behaviors) - 1)
        advance, result = behaviors[i]
        calls.append({"seconds": seconds, "timeout": kwargs.get("timeout"),
                      "endpoint": kwargs.get("endpoint")})
        clock.advance(advance)
        if isinstance(result, Exception):
            raise result
        return result

    return fake, calls


def test_llm_zero_remaining_launches_nothing(llm_clock, monkeypatch):
    fake, calls = _fake_hard_timeout(llm_clock, [(0, "never")])
    monkeypatch.setattr(llm, "_hard_timeout", fake)
    with pytest.raises(llm.LLMDeadlineExceeded):
        llm.generate_text(system="s", user="u", deadline=llm_clock.t)
    assert calls == []  # no provider call launched


def test_slow_mistral_blocks_groq_fallback_near_deadline(llm_clock, monkeypatch):
    # Mistral eats 200s then errors; only 10s remain — Groq must NOT launch.
    fake, calls = _fake_hard_timeout(llm_clock, [(200, RuntimeError("read timeout"))])
    monkeypatch.setattr(llm, "_hard_timeout", fake)
    with pytest.raises(llm.LLMDeadlineExceeded) as ei:
        llm.generate_text(system="s", user="u", deadline=llm_clock.t + 210)
    assert len(calls) == 1 and "mistral" in calls[0]["endpoint"]
    assert "Groq fallback" in str(ei.value)


def test_provider_timeouts_clamped_to_remaining(llm_clock, monkeypatch):
    # 100s remain: Mistral hard timeout min(330,100)=100, HTTP min(300,90)=90
    fake, calls = _fake_hard_timeout(llm_clock, [(10, "ok")])
    monkeypatch.setattr(llm, "_hard_timeout", fake)
    assert llm.generate_text(system="s", user="u",
                             deadline=llm_clock.t + 100) == "ok"
    assert calls[0]["seconds"] == pytest.approx(100)
    assert calls[0]["timeout"] == pytest.approx(90)
    # Groq-only path (no Mistral key): same clamping against its 180/150 caps
    monkeypatch.setattr(llm, "MISTRAL_KEY", "")
    fake2, calls2 = _fake_hard_timeout(llm_clock, [(10, "ok")])
    monkeypatch.setattr(llm, "_hard_timeout", fake2)
    assert llm.generate_text(system="s", user="u",
                             deadline=llm_clock.t + 100) == "ok"
    assert "groq" in calls2[0]["endpoint"]
    assert calls2[0]["seconds"] == pytest.approx(100)
    assert calls2[0]["timeout"] == pytest.approx(90)
    # No deadline → original caps untouched
    fake3, calls3 = _fake_hard_timeout(llm_clock, [(10, "ok")])
    monkeypatch.setattr(llm, "_hard_timeout", fake3)
    monkeypatch.setattr(llm, "MISTRAL_KEY", "mk")
    assert llm.generate_text(system="s", user="u") == "ok"
    assert calls3[0]["seconds"] == pytest.approx(330)
    assert calls3[0]["timeout"] == pytest.approx(300)


def test_backoff_skipped_when_no_time_remains(llm_clock, monkeypatch):
    # Both providers fail fast twice-over; backoff (5s) + MIN_LAUNCH (20s)
    # don't fit in the 15s remaining → raise instead of sleeping.
    fake, calls = _fake_hard_timeout(llm_clock, [(5, RuntimeError("boom"))])
    monkeypatch.setattr(llm, "_hard_timeout", fake)
    with pytest.raises(llm.LLMDeadlineExceeded) as ei:
        llm.generate_text(system="s", user="u", max_retries=2,
                          deadline=llm_clock.t + 25)
    assert len(calls) == 2               # Mistral + Groq, attempt 1 only
    assert llm_clock.sleeps == []        # backoff never slept
    assert "backoff" in str(ei.value)


def test_llm_deadline_is_terminal_in_retry_loop(clock, monkeypatch):
    # LLMDeadlineExceeded from the provider layer must abort _llm_with_retry
    # as GenerationDeadlineExceeded, not be retried like an LLMError.
    calls = {"n": 0}

    def fake_gen(**kwargs):
        calls["n"] += 1
        raise gen.LLMDeadlineExceeded("Groq fallback not launched")

    monkeypatch.setattr(gen, "generate_json", fake_gen)
    with pytest.raises(gen.GenerationDeadlineExceeded):
        gen._llm_with_retry(system="s", user="u", validator_key="long_story",
                            max_retries=5, deadline=clock.t + 480, log_prefix="")
    assert calls["n"] == 1


# ── Item 3 (review): render/publish envelope — over-budget runs cannot
# start external render phases or mutate production content


def test_wall_gate_blocks_expired_and_passes_future(clock):
    gen._wall_gate(None, "publish")                    # no deadline → no-op
    gen._wall_gate(clock.t + 60, "publish")            # future → passes
    with pytest.raises(gen.GenerationDeadlineExceeded) as ei:
        gen._wall_gate(clock.t - 1, "publish")
    assert "phase=publish" in str(ei.value)


class FakeSeg:
    """Minimal pydub stand-in supporting the assembly operators used by
    generate_long_story. export() records instead of writing."""
    exports: list = []
    fail_export: bool = False

    def __init__(self, ms=1000):
        self.ms = ms

    def __len__(self):
        return self.ms

    def __add__(self, o):
        return FakeSeg(self.ms + (len(o) if o is not None else 0))

    def __sub__(self, db):
        return self

    def __getitem__(self, sl):
        return FakeSeg(self.ms)

    def overlay(self, o):
        return self

    def fade_in(self, ms):
        return self

    def fade_out(self, ms):
        return self

    def export(self, path, **kw):
        if FakeSeg.fail_export:
            raise RuntimeError("mp3 encoder unavailable")
        FakeSeg.exports.append(str(path))


LS_AXES = {"age_group": "6-8", "mood": "calm", "world_name": "W",
           "world": "W", "characterType": "bird", "narrative_shape": "",
           "cast_structure": "", "recent_titles": [], "recent_phrases": [],
           "recent_names": []}

FULL_DATA = {
    "full_text_roman": "[PHASE_1] a [PHASE_2] b [PHASE_3] c",
    "full_text_deva": "कहानी", "song_lyrics_deva": "लोरी",
    "repeated_phrase": "so ja", "characters": [],
    "title": "T", "title_en": "T", "world_description": "w",
    "world_description_en": "w", "world_name": "W", "world_name_en": "W",
    "mystery": "m", "resolution": "r", "breathing_mechanic": "b",
    "song_seed": "s", "cover_context": "c",
}

_TTS_PRESET = {"stability": 0.5, "style": 0.0, "speed": 1.0}


def _render_setup(monkeypatch, clock, *, segments=(), song_advance=0.0,
                  tts_advance=0.0, flux_advance=0.0, text_seconds=100.0,
                  hard_fail_on=None):
    """Wire generate_long_story for an offline render run: fake LLM (validator
    stubbed to pass), fake render-stack modules, fake pydub, passthrough
    _hard_timeout (records bounded seconds; raises like the real one when
    `hard_fail_on` names the wrapped fn), and write recorders. Returns the
    recorder dict."""
    # Isolate repo paths: the collision guard + id reservation write under
    # BASE_DIR; tests must never touch the real worktree's data/seed dirs.
    _tmp = Path(tempfile.mkdtemp(prefix="hi_ls_test_"))
    monkeypatch.setattr(gen, "BASE_DIR", _tmp / "backend")
    monkeypatch.setattr(gen, "WEB_ROOT", _tmp / "web")
    # Pin local semantics: on the prod box ON_PROD is genuinely True and the
    # guard fails closed on a missing catalog; tests wanting prod behavior
    # override this explicitly after setup.
    monkeypatch.setattr(gen, "ON_PROD", False)
    rec = {"minimax": 0, "tts": 0, "flux": 0, "save_audio": 0,
           "save_cover": 0, "per_content": 0, "upsert": 0,
           "song_write": 0, "song_path": "", "hard": []}
    FakeSeg.exports = []
    FakeSeg.fail_export = False

    fake, _ = _fake_generate_json(clock, seconds=text_seconds, data=dict(FULL_DATA))
    monkeypatch.setattr(gen, "generate_json", fake)
    monkeypatch.setattr(gen, "validate_structured", lambda *a, **k: [])
    monkeypatch.setattr(gen, "_long_story_prompt", lambda axes: ("s", "u"))

    def hard(fn, seconds, **kwargs):
        rec["hard"].append((fn.__name__, seconds))
        if hard_fail_on and fn.__name__ == hard_fail_on:
            raise TimeoutError(
                f"hard wall-clock timeout after {seconds}s (inner read-timeout did not fire)")
        return fn(**kwargs)

    monkeypatch.setattr(gen, "_hard_timeout", hard)
    monkeypatch.setattr(gen, "AudioSegment", types.SimpleNamespace(
        silent=lambda duration=0: FakeSeg(duration),
        from_file=lambda *a, **k: FakeSeg(30000),
        from_wav=lambda *a, **k: FakeSeg(2000)))

    def minimax_lullaby(style, lyrics_deva):
        rec["minimax"] += 1
        clock.advance(song_advance)
        return b"mp3"

    def elevenlabs_tts(text, voice_id, **kw):
        rec["tts"] += 1
        clock.advance(tts_advance)
        return FakeSeg(5000)

    def flux(prompt, w=1024, h=1024, deadline=None):
        rec["flux"] += 1
        clock.advance(flux_advance)
        return b"img"

    def write_bytes(path, data):
        rec["song_write"] += 1
        rec["song_path"] = str(path)

    monkeypatch.setattr(gen, "_flux_cover", flux)
    monkeypatch.setattr(gen, "_write_bytes", write_bytes)
    monkeypatch.setattr(gen, "_save_audio",
                        lambda *a, **k: rec.__setitem__("save_audio", rec["save_audio"] + 1))
    monkeypatch.setattr(gen, "_save_cover",
                        lambda *a, **k: rec.__setitem__("save_cover", rec["save_cover"] + 1))
    monkeypatch.setattr(gen, "_write_per_content_file",
                        lambda *a, **k: rec.__setitem__("per_content", rec["per_content"] + 1))
    monkeypatch.setattr(gen, "_upsert_content",
                        lambda *a, **k: rec.__setitem__("upsert", rec["upsert"] + 1))

    pub = types.SimpleNamespace(
        elevenlabs_tts=elevenlabs_tts, ELEVENLABS_VOICES={"tripti": "v1", "roohi": "v2"},
        PHASE_TTS={1: _TTS_PRESET, 2: _TTS_PRESET, 3: _TTS_PRESET},
        PHRASE_TTS=_TTS_PRESET, WHISPER_TTS=_TTS_PRESET, INTRO_TTS=_TTS_PRESET,
        _trim_or_loop=lambda *a, **k: FakeSeg(1000),
        _apply_breathe_swells=lambda *a, **k: FakeSeg(1000),
        parse_long_segments=lambda t: list(segments),
        _ensure_terminal=lambda s: s, strip_long_story_tags=lambda s: s,
    )
    monkeypatch.setitem(sys.modules, "publish_hindi_long_day1", pub)
    monkeypatch.setitem(sys.modules, "audio_assembly", types.SimpleNamespace(
        normalize_for_tts=lambda s: s, MUSIC_DIR=Path(".")))
    monkeypatch.setitem(sys.modules, "fix_hindi_batch_day2", types.SimpleNamespace(
        minimax_lullaby=minimax_lullaby))
    return rec


def _writes(rec):
    return (rec["save_audio"], rec["save_cover"], rec["per_content"],
            rec["upsert"], rec["song_write"])


def test_render_budget_zero_blocks_immediately(clock, monkeypatch):
    # render_budget=0 is authoritative: the very first render gate fires;
    # no external call, no write.
    rec = _render_setup(monkeypatch, clock)
    with pytest.raises(gen.GenerationDeadlineExceeded) as ei:
        gen.generate_long_story(LS_AXES, log_prefix="", deadline=clock.t + 720,
                                max_attempts=2, render_budget=0)
    assert "phase=song_render" in str(ei.value)
    assert rec["minimax"] == 0 and rec["tts"] == 0 and rec["flux"] == 0
    assert _writes(rec) == (0, 0, 0, 0, 0)


def test_slow_tts_blocks_further_tts_cover_and_all_writes(clock, monkeypatch):
    # First ElevenLabs call eats the render budget → the NEXT per-call gate
    # fires: exactly one TTS request, no cover request, zero writes.
    segs = [{"kind": "narration", "content": "one", "section": "intro", "phase": 1},
            {"kind": "narration", "content": "two", "section": "intro", "phase": 1}]
    rec = _render_setup(monkeypatch, clock, segments=segs, tts_advance=200)
    with pytest.raises(gen.GenerationDeadlineExceeded) as ei:
        gen.generate_long_story(LS_AXES, log_prefix="", deadline=clock.t + 720,
                                max_attempts=2, render_budget=90)
    assert "phase=tts_call" in str(ei.value)
    assert rec["tts"] == 1 and rec["flux"] == 0
    assert _writes(rec) == (0, 0, 0, 0, 0)
    # the one launched TTS request had its timeout clamped to remaining render
    tts_hard = [s for name, s in rec["hard"] if name == "elevenlabs_tts"]
    assert tts_hard and tts_hard[0] <= 90


def test_expired_post_cover_gate_produces_zero_writes(clock, monkeypatch):
    # Cover render overruns the budget → the publish gate blocks: assets were
    # generated (paid) but NOTHING is written to production.
    rec = _render_setup(monkeypatch, clock, flux_advance=200)
    with pytest.raises(gen.GenerationDeadlineExceeded) as ei:
        gen.generate_long_story(LS_AXES, log_prefix="", deadline=clock.t + 720,
                                max_attempts=2, render_budget=90)
    assert "phase=publish" in str(ei.value)
    assert rec["flux"] == 1                       # cover attempt happened
    assert _writes(rec) == (0, 0, 0, 0, 0)        # zero production mutation


def test_successful_path_publishes_every_asset_once(clock, monkeypatch):
    segs = [{"kind": "narration", "content": "one", "section": "intro", "phase": 1}]
    rec = _render_setup(monkeypatch, clock, segments=segs)
    entry = gen.generate_long_story(LS_AXES, log_prefix="", deadline=clock.t + 720,
                                    max_attempts=2, render_budget=900)
    assert entry["id"].startswith("hi-long-6-8-")
    assert entry["cover"] == f"/covers/{entry['id']}.webp"
    assert rec["minimax"] == 1 and rec["tts"] == 1 and rec["flux"] == 1
    # every asset written exactly once: audio, cover, catalog entry (x2 paths),
    # standalone song bytes (pre-encoded, then written post-gate)
    assert _writes(rec) == (1, 1, 1, 1, 1)
    assert len(FakeSeg.exports) == 1              # song encoded exactly once
    assert rec["song_path"].endswith(f"{entry['id']}_song.mp3")
    # request waits bounded to the natural caps within the 900s envelope
    hard = dict((name, s) for name, s in rec["hard"])
    assert hard["minimax_lullaby"] == pytest.approx(600.0)
    assert hard["elevenlabs_tts"] == pytest.approx(240.0)


# ── Items 1+2 (review): repick is validation-only; render failures terminal


def _patch_picker_only(monkeypatch):
    """Patch the picker + catalog loader but keep the REAL generator wired in
    GENERATORS, so repick-level tests exercise generate_long_story itself."""
    picks = {"n": 0}

    def fake_picker(catalog):
        picks["n"] += 1
        return dict(LS_AXES)

    monkeypatch.setitem(prh.PICKERS, "long_story", fake_picker)
    monkeypatch.setattr(prh, "load_hindi_catalog", lambda: [])
    return picks


def test_hard_timeout_during_song_is_terminal_one_pick_zero_writes(clock, monkeypatch):
    # _hard_timeout itself raises while waiting on MiniMax → RenderFailed:
    # the generator runs ONCE, no fresh pick starts, nothing is written.
    rec = _render_setup(monkeypatch, clock, hard_fail_on="minimax_lullaby")
    picks = _patch_picker_only(monkeypatch)
    with pytest.raises(gen.RenderFailed) as ei:
        prh._generate_with_repick("long_story", catalog=[])
    assert "song render hard-timeout" in str(ei.value)
    assert picks["n"] == 1                        # no re-pick after paid render
    assert rec["minimax"] == 0 and rec["tts"] == 0 and rec["flux"] == 0
    assert _writes(rec) == (0, 0, 0, 0, 0)


def test_hard_timeout_during_tts_is_terminal_one_pick_zero_writes(clock, monkeypatch):
    segs = [{"kind": "narration", "content": "one", "section": "intro", "phase": 1}]
    rec = _render_setup(monkeypatch, clock, segments=segs,
                        hard_fail_on="elevenlabs_tts")
    picks = _patch_picker_only(monkeypatch)
    with pytest.raises(gen.RenderFailed) as ei:
        prh._generate_with_repick("long_story", catalog=[])
    assert "tts render hard-timeout" in str(ei.value)
    assert picks["n"] == 1                        # no fresh pick
    assert rec["minimax"] == 1                    # song already paid for
    assert rec["tts"] == 0                        # hard timeout, not the fn
    assert _writes(rec) == (0, 0, 0, 0, 0)


def test_repick_reraises_unexpected_errors_immediately(clock, monkeypatch):
    # Filesystem/assembly/unexpected errors are NOT a repick path.
    calls = {"n": 0}

    def blows_up(axes, log_prefix="", deadline=None, max_attempts=None,
                 seed_errors=None, render_budget=None):
        calls["n"] += 1
        raise OSError("disk full")

    _patch_repick(monkeypatch, clock, blows_up)
    with pytest.raises(OSError):
        prh._generate_with_repick("long_story", catalog=[])
    assert calls["n"] == 1


def test_song_encode_failure_is_terminal_zero_writes(clock, monkeypatch):
    # The pre-gate standalone-song encode fails → RenderFailed, zero writes
    # (no more silently-skipped marketing song after the audio already shipped).
    rec = _render_setup(monkeypatch, clock)
    FakeSeg.fail_export = True
    with pytest.raises(gen.RenderFailed) as ei:
        gen.generate_long_story(LS_AXES, log_prefix="", deadline=clock.t + 720,
                                max_attempts=2, render_budget=900)
    assert "standalone song encode failed" in str(ei.value)
    assert _writes(rec) == (0, 0, 0, 0, 0)


# ── Item 3 (review): Pollinations 429 retry recomputes its timeout post-wait


def test_flux_429_retry_timeout_recomputed_after_wait(clock, monkeypatch):
    monkeypatch.setattr(gen, "POLLINATIONS_KEY", "pk")
    timeouts: list[float] = []

    class Resp:
        def __init__(self, status):
            self.status_code = status
            self.content = b"x" * 2000
            self.headers = {"content-type": "image/jpeg"}
            self.text = ""

    responses = [Resp(429), Resp(200)]

    def fake_get(url, headers=None, timeout=None, follow_redirects=False):
        timeouts.append(timeout)
        return responses[len(timeouts) - 1]

    monkeypatch.setattr(gen, "httpx", types.SimpleNamespace(get=fake_get))
    deadline = clock.t + 100
    out = gen._flux_cover("prompt", deadline=deadline)
    assert out == b"x" * 2000
    # first request: min(180, 100) = 100. The 20s wait elapses before the
    # retry, so its timeout is the POST-wait remainder (~80), not the stale
    # pre-wait value.
    assert timeouts[0] == pytest.approx(100)
    assert timeouts[1] == pytest.approx(80)


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
    # A1: arousal/exclamation in the back half still fails
    a1 = ("[PHASE_1] Ek chota ghar tha. Sab shaant tha. Hawa dheeri thi. "
          "Chidiya chup thi. [PHASE_2] Raat aayi. Taare chamke. "
          "[PHASE_3] Achanak billi bhaagi! Sab jaag gaye. Phir neend aayi.")
    errs = validate_long_story(_long_story_dict(a1))
    assert any(e.startswith("physiology A1 FAIL") for e in errs)
    # dialogue-format failures still fire: zero NAME: "..." lines on a
    # dialogue-driven shape, and a declared character who never speaks
    decl = short + ' [CHARACTER: Suhani] Suhani ne kaha ki so jao.'
    errs = validate_long_story(_long_story_dict(decl))
    assert any('only 0 NAME: "..." dialogue lines' in e for e in errs)
    assert any("declared character 'Suhani' has no dialogue line" in e for e in errs)
