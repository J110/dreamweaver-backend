"""HI content-id collision guard — 2026-07-15 Tippy post-mortem.

Slug-only ids (`hi-neeti_katha-2-5-tipp`) were reused on 05-19/06-15/07-15,
each publish silently destroying the previous story. These tests prove:
  1. ids carry an 8-char content-derived hash → repeated "Tippy" stories with
     different content get DIFFERENT ids; identical content gets the SAME id;
  2. the collision guard fails closed BEFORE any paid render when the id,
     per-content JSON, audio, cover, or recovery-store path already exists —
     and never touches the existing item;
  3. long-story and lullaby ids get the same treatment (parity);
  4. served asset and recovery-store copy are written from the same bytes;
  5. existing catalog items are preserved (guard refuses, never overwrites).

recent_names widening (14→30) is diversity protection only — the unique id
remains the guarantee.
"""
import json
import re
import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import _hindi_generators as gen  # noqa: E402
from _hindi_diversity import pick_short_story_axes  # noqa: E402
from test_hi_longstory_deadline import (  # noqa: E402
    FULL_DATA, LS_AXES, FakeSeg, _render_setup,
)


class DummyClock:
    """Real time, no-op advance — reuses the deadline-test fakes without
    wall-clock gating (deadline/render_budget stay None here)."""

    def time(self):
        return time.time()

    def advance(self, s):
        pass


# ── 1. content hash + id formula ──────────────────────────────────────


def test_content_hash_deterministic_and_distinct():
    a = gen._content_hash("ek kahani")
    assert a == gen._content_hash("ek kahani")          # deterministic
    assert re.fullmatch(r"[0-9a-f]{8}", a)              # 8 hex chars
    assert a != gen._content_hash("doosri kahani")      # content-derived


# ── 2. guard: fail closed, preserve existing ──────────────────────────


def test_guard_blocks_existing_paths_and_preserves_them(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path)      # no catalog snapshot
    monkeypatch.setattr(gen, "ON_PROD", False)          # local semantics
    fresh = tmp_path / "new.json"
    gen._guard_new_content_id("hi-x-2-5-abcd-12345678", [fresh])  # passes
    existing = tmp_path / "old.json"
    existing.write_text('{"id": "precious"}')
    with pytest.raises(gen.ContentIdCollision) as ei:
        gen._guard_new_content_id("hi-x-2-5-abcd-12345678", [fresh, existing])
    assert "old.json" in str(ei.value)
    assert existing.read_text() == '{"id": "precious"}'  # untouched
    assert not fresh.exists()                            # nothing created


def test_guard_blocks_catalog_id(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path)
    monkeypatch.setattr(gen, "ON_PROD", False)
    seed = tmp_path / "seed_output"
    seed.mkdir()
    (seed / "content.json").write_text(json.dumps([{"id": "hi-x-2-5-tipp-aaaaaaaa"}]))
    with pytest.raises(gen.ContentIdCollision) as ei:
        gen._guard_new_content_id("hi-x-2-5-tipp-aaaaaaaa", [])
    assert "catalog id already present" in str(ei.value)


# ── short-story harness ───────────────────────────────────────────────


SHORT_AXES = {"story_type": "neeti_katha", "age_group": "2-5", "mood": "calm",
              "characterType": "land_mammal", "recent_titles": [],
              "recent_phrases": [], "recent_names": []}


def _story_data(text):
    return {
        "id": "hi-neeti_katha-2-5-XXXX", "title": "Tippy aur Raat",
        "title_en": "Tippy and the Night", "hook": "Suno na",
        "hook_deva": "सुनो", "description": "d", "description_en": "d",
        "text": text, "text_deva": "कहानी", "repeated_phrase": "so ja",
        "morals": ["rest"], "categories": ["Bedtime"],
        "character": {"name": "Tippy", "identity": "gecko", "special": "s",
                      "personality_tags": ["Gentle"]},
        "characterType": "land_mammal", "story_type": "neeti_katha",
        "age_group": "2-5", "mood": "calm", "cover_context": "c",
        "diversityFingerprint": {},
    }


def _short_setup(monkeypatch, tmp_path, text):
    rec = {"render": 0, "flux": 0, "save_audio": [], "save_cover": [],
           "per_content": 0, "upsert": 0}
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path / "backend")
    monkeypatch.setattr(gen, "WEB_ROOT", tmp_path / "web")
    monkeypatch.setattr(gen, "ON_PROD", False)  # pin local semantics on prod boxes
    # Valid empty catalog: ON_PROD guard now fails closed on a MISSING one.
    seed = tmp_path / "backend" / "seed_output"
    seed.mkdir(parents=True, exist_ok=True)
    (seed / "content.json").write_text("[]")
    monkeypatch.setattr(gen, "generate_json",
                        lambda **k: dict(_story_data(text)))
    monkeypatch.setattr(gen, "validate_structured", lambda *a, **k: [])
    monkeypatch.setattr(gen, "_short_story_prompt", lambda axes: ("s", "u"))

    def assemble(**kw):
        rec["render"] += 1
        return FakeSeg(60000)

    monkeypatch.setitem(sys.modules, "fix_hindi_batch_day2",
                        types.SimpleNamespace(assemble_story_audio=assemble,
                                              minimax_lullaby=lambda *a, **k: b"mp3"))
    monkeypatch.setattr(gen, "_flux_cover",
                        lambda *a, **k: (rec.__setitem__("flux", rec["flux"] + 1), b"img")[1])
    monkeypatch.setattr(gen, "_save_audio",
                        lambda seg, *paths: rec["save_audio"].append((seg, paths)))
    monkeypatch.setattr(gen, "_save_cover",
                        lambda img, *paths: rec["save_cover"].append((img, paths)))
    monkeypatch.setattr(gen, "_write_per_content_file",
                        lambda e: rec.__setitem__("per_content", rec["per_content"] + 1))
    monkeypatch.setattr(gen, "_upsert_content",
                        lambda e: rec.__setitem__("upsert", rec["upsert"] + 1))
    return rec


# ── 3. repeated Tippy → different ids; same content → refusal ─────────


def test_repeated_tippy_generations_get_different_ids(monkeypatch, tmp_path):
    _short_setup(monkeypatch, tmp_path, "Tippy raat mein chali.")
    e1 = gen.generate_short_story(dict(SHORT_AXES), log_prefix="")
    _short_setup(monkeypatch, tmp_path, "Tippy subah tak soyi rahi.")
    e2 = gen.generate_short_story(dict(SHORT_AXES), log_prefix="")
    pat = r"hi-neeti_katha-2-5-tipp-[0-9a-f]{8}"
    assert re.fullmatch(pat, e1["id"]) and re.fullmatch(pat, e2["id"])
    assert e1["id"] != e2["id"]                     # different content → different id


def test_exact_content_collision_refused_before_render(monkeypatch, tmp_path):
    text = "Tippy raat mein chali."
    rec = _short_setup(monkeypatch, tmp_path, text)
    # Pre-create the per-content JSON at the DETERMINISTIC id this content maps to
    sid = f"hi-neeti_katha-2-5-tipp-{gen._content_hash(text)}"
    pc = tmp_path / "backend" / "data" / "stories_hi" / f"{sid}.json"
    pc.parent.mkdir(parents=True)
    pc.write_text('{"id": "existing"}')
    with pytest.raises(gen.ContentIdCollision):
        gen.generate_short_story(dict(SHORT_AXES), log_prefix="")
    # Refused BEFORE any paid rendering or write; existing item preserved
    assert rec["render"] == 0 and rec["flux"] == 0
    assert rec["save_audio"] == [] and rec["save_cover"] == []
    assert rec["per_content"] == 0 and rec["upsert"] == 0
    assert pc.read_text() == '{"id": "existing"}'


# ── 4. long-story / lullaby parity ────────────────────────────────────


def test_long_story_id_carries_content_hash(monkeypatch):
    clock = DummyClock()
    _render_setup(monkeypatch, clock, segments=())
    entry = gen.generate_long_story(dict(LS_AXES), log_prefix="", max_attempts=2)
    assert re.fullmatch(r"hi-long-6-8-[a-z0-9]{4}-[0-9a-f]{8}", entry["id"])
    assert entry["id"].endswith(gen._content_hash(FULL_DATA["full_text_roman"]))


LULLABY_AXES = {"lullaby_type": "shield", "age_group": "2-5", "mood": "calm"}

LULLABY_DATA = {
    "title": "Lori Ki Raat", "title_en": "Night Lullaby", "card_label": "Lori",
    "card_subtitle": "soft", "lyrics": "so ja\nso ja\nchup chup\nso ja\nso ja\nchanda",
    "lyrics_deva": "सो जा", "instruments": "harmonium", "tempo": 60,
    "cover_context": "c",
}


def test_lullaby_id_carries_content_hash(monkeypatch, tmp_path):
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path / "backend")
    monkeypatch.setattr(gen, "ON_PROD", False)
    monkeypatch.setattr(gen, "WEB_ROOT", tmp_path / "web")
    monkeypatch.setattr(gen, "generate_json", lambda **k: dict(LULLABY_DATA))
    monkeypatch.setattr(gen, "validate_structured", lambda *a, **k: [])
    monkeypatch.setattr(gen, "_lullaby_prompt", lambda axes: ("s", "u"))
    monkeypatch.setitem(sys.modules, "fix_hindi_batch_day2",
                        types.SimpleNamespace(minimax_lullaby=lambda *a, **k: b"mp3"))
    monkeypatch.setattr(gen, "AudioSegment", types.SimpleNamespace(
        from_file=lambda *a, **k: FakeSeg(45000)))
    monkeypatch.setattr(gen, "_flux_cover", lambda *a, **k: b"img")
    saves = {"audio": [], "cover": []}
    monkeypatch.setattr(gen, "_save_audio",
                        lambda seg, *paths: saves["audio"].append(paths))
    monkeypatch.setattr(gen, "_save_cover",
                        lambda img, *paths: saves["cover"].append(paths))
    monkeypatch.setattr(gen, "_write_per_content_file", lambda e: None)
    monkeypatch.setattr(gen, "_upsert_content", lambda e: None)
    entry = gen.generate_lullaby(dict(LULLABY_AXES), log_prefix="")
    assert re.fullmatch(r"hi-shield-2-5-[a-z0-9]{1,4}-[0-9a-f]{8}", entry["id"])
    assert entry["id"].endswith(gen._content_hash(LULLABY_DATA["lyrics"]))


# ── 5. served asset and recovery store from the same bytes ────────────


def test_store_and_served_copies_written_from_same_bytes(monkeypatch, tmp_path):
    rec = _short_setup(monkeypatch, tmp_path, "Tippy store parity kahani.")
    monkeypatch.setattr(gen, "ON_PROD", True)
    monkeypatch.setattr(gen, "PROD_AUDIO_STORE", tmp_path / "audio-store")
    monkeypatch.setattr(gen, "PROD_COVER_STORE", tmp_path / "cover-store")
    entry = gen.generate_short_story(dict(SHORT_AXES), log_prefix="")
    sid = entry["id"]
    (seg, audio_paths), = rec["save_audio"]     # ONE _save_audio call...
    audio_paths = [str(p) for p in audio_paths]
    assert str(tmp_path / "audio-store" / "pre-gen" / f"{sid}_tripti.mp3") in audio_paths
    assert any("web" in p and p.endswith(f"{sid}_tripti.mp3") for p in audio_paths)
    # ...one seg object exported to every path → served + store byte-identical
    (img, cover_paths), = rec["save_cover"]
    cover_paths = [str(p) for p in cover_paths]
    assert str(tmp_path / "cover-store" / f"{sid}.webp") in cover_paths
    assert any("web" in p and p.endswith(f"{sid}.webp") for p in cover_paths)


# ── 6. diversity widening (protection only) ───────────────────────────


def test_recent_names_covers_all_30_recent_stories():
    stories = [{"type": "story", "age_group": "2-5", "mood": "calm",
                "characterType": "bird", "story_type": "katha",
                "title": f"T{i}", "repeated_phrase": "p",
                "created_at": f"2026-06-{i + 1:02d}T00:00:00",
                "character": {"name": f"Naam{i}"}} for i in range(40)]
    axes = pick_short_story_axes(stories)
    assert len(axes["recent_names"]) == 30          # was 14
    assert "Naam39" in axes["recent_names"]         # newest included
    assert "Naam15" in axes["recent_names"]         # would have been cut at 14


# ── 7. fail-closed guard: corrupt / invalid catalog (review round 2) ──


import os          # noqa: E402
import subprocess  # noqa: E402
import threading   # noqa: E402


def test_corrupt_catalog_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path)
    monkeypatch.setattr(gen, "ON_PROD", False)
    (tmp_path / "seed_output").mkdir()
    (tmp_path / "seed_output" / "content.json").write_text("{ not json !!")
    with pytest.raises(gen.ContentIdGuardError):
        gen._guard_new_content_id("hi-x-2-5-abcd-12345678", [])


def test_invalid_catalog_shape_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path)
    monkeypatch.setattr(gen, "ON_PROD", False)
    (tmp_path / "seed_output").mkdir()
    for bad in ('{"items": 5}', "[1, 2, 3]", '"just a string"'):
        (tmp_path / "seed_output" / "content.json").write_text(bad)
        with pytest.raises(gen.ContentIdGuardError):
            gen._guard_new_content_id("hi-x-2-5-abcd-12345678", [])


def test_corrupt_catalog_blocks_generator_before_render(monkeypatch, tmp_path):
    rec = _short_setup(monkeypatch, tmp_path, "Tippy corrupt catalog kahani.")
    (tmp_path / "backend" / "seed_output" / "content.json").write_text(
        "{ definitely not json")
    with pytest.raises(gen.ContentIdGuardError):
        gen.generate_short_story(dict(SHORT_AXES), log_prefix="")
    assert rec["render"] == 0 and rec["flux"] == 0     # nothing paid happened
    assert rec["save_audio"] == [] and rec["per_content"] == 0


# ── 8. JSON recovery-store collision (prod /opt/json-store analogue) ──


def test_json_recovery_store_collision_refused(monkeypatch, tmp_path):
    text = "Tippy json-store kahani."
    rec = _short_setup(monkeypatch, tmp_path, text)
    monkeypatch.setattr(gen, "ON_PROD", True)
    monkeypatch.setattr(gen, "PROD_AUDIO_STORE", tmp_path / "audio-store")
    monkeypatch.setattr(gen, "PROD_COVER_STORE", tmp_path / "cover-store")
    monkeypatch.setattr(gen, "PROD_JSON_STORE", tmp_path / "json-store")
    sid = f"hi-neeti_katha-2-5-tipp-{gen._content_hash(text)}"
    stale = tmp_path / "json-store" / "stories_hi" / f"{sid}.json"
    stale.parent.mkdir(parents=True)
    stale.write_text('{"id": "recovery copy"}')
    with pytest.raises(gen.ContentIdCollision) as ei:
        gen.generate_short_story(dict(SHORT_AXES), log_prefix="")
    assert "json-store" in str(ei.value)
    assert rec["render"] == 0 and rec["flux"] == 0
    assert stale.read_text() == '{"id": "recovery copy"}'  # preserved


# ── 9. exclusive reservations: race, staleness, release ───────────────


def test_concurrent_reservations_only_one_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path)
    monkeypatch.setattr(gen, "_pid_alive", lambda pid: True)
    pids = {}
    monkeypatch.setattr(gen.os, "getpid",
                        lambda: pids.setdefault(threading.get_ident(), 10000 + len(pids)))
    barrier = threading.Barrier(2)
    results = []

    def attempt():
        barrier.wait()
        try:
            gen._reserve_content_id("hi-race-2-5-abcd-12345678")
            results.append("ok")
        except gen.ContentIdCollision:
            results.append("blocked")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["blocked", "ok"]  # exactly one reservation


def test_stale_reservation_dead_pid_taken_over(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path)
    sid = "hi-stale-2-5-abcd-12345678"
    path = gen._reservation_path(sid)
    path.parent.mkdir(parents=True)
    proc = subprocess.Popen(["true"])
    proc.wait()  # reaped → pid is dead
    path.write_text(json.dumps({"sid": sid, "pid": proc.pid, "ts": time.time()}))
    gen._reserve_content_id(sid)                       # safe takeover
    assert json.loads(path.read_text())["pid"] == os.getpid()


def test_stale_reservation_ttl_taken_over(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path)
    monkeypatch.setattr(gen, "_pid_alive", lambda pid: True)  # holder "alive" but wedged
    sid = "hi-ttl-2-5-abcd-12345678"
    path = gen._reservation_path(sid)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(
        {"sid": sid, "pid": 99999, "ts": time.time() - gen.RESERVATION_TTL_S - 10}))
    gen._reserve_content_id(sid)                       # TTL takeover
    assert json.loads(path.read_text())["pid"] == os.getpid()


def test_live_foreign_reservation_refused_and_reentrant_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path)
    monkeypatch.setattr(gen, "_pid_alive", lambda pid: True)
    sid = "hi-held-2-5-abcd-12345678"
    path = gen._reservation_path(sid)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"sid": sid, "pid": 99999, "ts": time.time()}))
    with pytest.raises(gen.ContentIdCollision):
        gen._reserve_content_id(sid)                   # live peer → refuse
    path.write_text(json.dumps({"sid": sid, "pid": os.getpid(), "ts": time.time()}))
    gen._reserve_content_id(sid)                       # own pid → re-entrant


def test_reservation_released_after_successful_publish(monkeypatch, tmp_path):
    _short_setup(monkeypatch, tmp_path, "Tippy release kahani.")
    entry = gen.generate_short_story(dict(SHORT_AXES), log_prefix="")
    assert not gen._reservation_path(entry["id"]).exists()


# ── 10. real single-encode byte parity (served / seed / recovery store) ──


def test_save_audio_single_encode_byte_identical_real_files(tmp_path):
    from pydub import AudioSegment as RealSeg
    seg = RealSeg.silent(duration=300)
    served = tmp_path / "web" / "audio" / "pre-gen" / "x_anika.mp3"
    seed = tmp_path / "backend" / "seed_output" / "stories_hi" / "x.mp3"
    store = tmp_path / "audio-store" / "pre-gen" / "x_anika.mp3"
    gen._save_audio(seg, served, seed, store)
    hashes = {__import__("hashlib").sha256(p.read_bytes()).hexdigest()
              for p in (served, seed, store)}
    assert len(hashes) == 1                    # byte-identical SHA-256
    assert served.stat().st_size > 500         # a real encoded mp3, not a stub


# ── 11. review round 3: unreadable reservations + missing prod catalog ──


def test_fresh_zero_byte_reservation_refused_and_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path)
    sid = "hi-zb-2-5-abcd-12345678"
    path = gen._reservation_path(sid)
    path.parent.mkdir(parents=True)
    path.write_text("")                      # zero-byte, mtime = now
    with pytest.raises(gen.ContentIdCollision) as ei:
        gen._reserve_content_id(sid)
    assert "unreadable reservation" in str(ei.value)
    assert path.exists() and path.read_text() == ""   # NOT unlinked


def test_unreadable_reservation_past_ttl_reclaimed(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "BASE_DIR", tmp_path)
    sid = "hi-zbold-2-5-abcd-12345678"
    path = gen._reservation_path(sid)
    path.parent.mkdir(parents=True)
    path.write_text("garbage not json")
    old = time.time() - gen.RESERVATION_TTL_S - 60
    os.utime(path, (old, old))               # fs age beyond the TTL
    gen._reserve_content_id(sid)             # reclaimed
    assert json.loads(path.read_text())["pid"] == os.getpid()


def test_missing_prod_catalog_blocks_before_render(monkeypatch, tmp_path):
    rec = _short_setup(monkeypatch, tmp_path, "Tippy missing catalog kahani.")
    monkeypatch.setattr(gen, "ON_PROD", True)
    monkeypatch.setattr(gen, "PROD_AUDIO_STORE", tmp_path / "audio-store")
    monkeypatch.setattr(gen, "PROD_COVER_STORE", tmp_path / "cover-store")
    monkeypatch.setattr(gen, "PROD_JSON_STORE", tmp_path / "json-store")
    (tmp_path / "backend" / "seed_output" / "content.json").unlink()
    with pytest.raises(gen.ContentIdGuardError) as ei:
        gen.generate_short_story(dict(SHORT_AXES), log_prefix="")
    assert "MISSING on production" in str(ei.value)
    assert rec["render"] == 0 and rec["flux"] == 0     # nothing paid happened
    # Local/manual behavior unchanged: same missing catalog, ON_PROD False
    monkeypatch.setattr(gen, "ON_PROD", False)
    gen._guard_new_content_id("hi-local-2-5-abcd-12345678", [])
