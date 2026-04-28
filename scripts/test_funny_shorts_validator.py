"""Tests for the funny shorts validator.

Run: cd dreamweaver-backend && .venv-test/bin/python -m pytest scripts/test_funny_shorts_validator.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _funny_shorts_common import validate_funny_short

# ────────────────────────────────────────────────────────────────────────
#  Task 1 — structural + tag whitelist
# ────────────────────────────────────────────────────────────────────────

GOOD_EN = {
    "title": "Cloud Catch",
    "lang": "en",
    "comedic_device": "earnest_vs_skeptical",
    "setting": "couch fort",
    "inputs": [
        {"voice": "A", "text": "[curious] Wait, do clouds taste like cotton?"},
        {"voice": "B", "text": "[matter-of-fact] No way. They're just water."},
        {"voice": "A", "text": "[earnest] But they LOOK like cotton candy."},
        {"voice": "B", "text": "[laughs]"},
        {"voice": "A", "text": "[serious] I'm saying clouds are POSSIBLE snacks."},
        {"voice": "B", "text": "[laughs together]"},
    ],
}


def test_good_short_has_no_errors():
    errors = validate_funny_short(GOOD_EN, recent_shorts=[], lang="en")
    assert errors == [], f"Expected no errors, got: {errors}"


def test_rejects_single_voice():
    bad = dict(GOOD_EN)
    bad["inputs"] = [{"voice": "A", "text": "[curious] Hi."}] * 6
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("voices A and B" in e for e in errors)


def test_rejects_too_few_lines():
    bad = dict(GOOD_EN)
    bad["inputs"] = GOOD_EN["inputs"][:5]
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("Line count" in e for e in errors)


def test_rejects_too_many_lines():
    bad = dict(GOOD_EN)
    bad["inputs"] = [
        {"voice": "A" if i % 2 == 0 else "B", "text": "[grinning] hi."}
        for i in range(21)
    ]
    bad["inputs"][-1] = {"voice": "B", "text": "[laughs together] yeah."}
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("Line count" in e for e in errors)


def test_rejects_line_over_12_words():
    bad = dict(GOOD_EN)
    bad["inputs"] = list(GOOD_EN["inputs"])
    bad["inputs"][0] = {"voice": "A", "text": "[curious] " + " ".join(["word"] * 13)}
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("too many words" in e for e in errors)


def test_rejects_total_chars_over_500():
    bad = dict(GOOD_EN)
    long_line = "a" * 100
    bad["inputs"] = [
        {"voice": "A" if i % 2 == 0 else "B", "text": long_line} for i in range(6)
    ]
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("Too long" in e for e in errors)


def test_rejects_unapproved_tag():
    bad = dict(GOOD_EN)
    bad["inputs"] = list(GOOD_EN["inputs"])
    bad["inputs"][0] = {"voice": "A", "text": "[crying] No no no!"}
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("unapproved tag" in e for e in errors)


# ────────────────────────────────────────────────────────────────────────
#  Task 2 — anti-template diversity + content rules
# ────────────────────────────────────────────────────────────────────────

def _make_short(opening_tag, device, setting, age_dyn="siblings", closing_lines=None):
    return {
        "title": "Stub",
        "lang": "en",
        "comedic_device": device,
        "setting": setting,
        "opening_tag": opening_tag,
        "closing_pattern": "thoughtful_pause",
        "character_age_dynamic": age_dyn,
        "inputs": closing_lines or [
            {"voice": "A", "text": f"{opening_tag} test."},
            {"voice": "B", "text": "[grinning] yeah."},
            {"voice": "A", "text": "[curious] one."},
            {"voice": "B", "text": "[grinning] two."},
            {"voice": "A", "text": "[grinning] three."},
            {"voice": "B", "text": "[thoughtful] hmm."},
        ],
    }


def test_rejects_opening_tag_repeated_in_2_of_last_3():
    recent = [
        _make_short("[curious]", "device_a", "kitchen"),
        _make_short("[curious]", "device_b", "bedroom"),
        _make_short("[grinning]", "device_c", "park"),
    ]
    candidate = _make_short("[curious]", "device_x", "treehouse")
    candidate["inputs"][0]["text"] = "[curious] hi."
    errors = validate_funny_short(candidate, recent_shorts=recent, lang="en")
    assert any("Opening tag" in e for e in errors)


def test_rejects_comedic_device_repeated_in_last_5():
    recent = [
        _make_short("[grinning]", "earnest_vs_skeptical", "kitchen"),
        _make_short("[curious]", "earnest_vs_skeptical", "bedroom"),
    ]
    candidate = _make_short("[grinning]", "earnest_vs_skeptical", "park")
    errors = validate_funny_short(candidate, recent_shorts=recent, lang="en")
    assert any("Comedic device" in e or "Device" in e for e in errors)


def test_rejects_setting_repeated_in_2_of_last_3():
    recent = [
        _make_short("[curious]", "device_a", "kitchen"),
        _make_short("[grinning]", "device_b", "kitchen"),
        _make_short("[serious]", "device_c", "park"),
    ]
    candidate = _make_short("[playful]", "device_x", "kitchen")
    errors = validate_funny_short(candidate, recent_shorts=recent, lang="en")
    assert any("Setting" in e or "setting" in e for e in errors)


def test_rejects_age_dynamic_repeated_in_2_of_last_3():
    recent = [
        _make_short("[curious]", "device_a", "kitchen", age_dyn="cousins"),
        _make_short("[grinning]", "device_b", "bedroom", age_dyn="cousins"),
        _make_short("[serious]", "device_c", "park", age_dyn="siblings"),
    ]
    candidate = _make_short("[playful]", "device_x", "treehouse", age_dyn="cousins")
    errors = validate_funny_short(candidate, recent_shorts=recent, lang="en")
    assert any("Character age dynamic" in e for e in errors)


def test_required_opening_tag_must_match_actual():
    bad = _make_short("[curious]", "device_x", "park")
    bad["inputs"][0]["text"] = "[grinning] hi."  # used grinning, not curious
    bad["required_opening_tag"] = "[curious]"
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("Required opening tag" in e for e in errors)


def test_required_opening_tag_match_passes():
    good = _make_short("[curious]", "device_x", "park")
    good["inputs"][0]["text"] = "[curious] hi there."
    good["required_opening_tag"] = "[curious]"
    errors = validate_funny_short(good, recent_shorts=[], lang="en")
    assert not any("Required opening tag" in e for e in errors)


def test_rejects_forbidden_word_brand():
    bad = _make_short("[curious]", "device_x", "park")
    bad["inputs"][0]["text"] = "[curious] I have a Hershey bar."
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("Forbidden" in e or "forbidden" in e for e in errors)


def test_rejects_forbidden_word_insult():
    bad = _make_short("[curious]", "device_x", "park")
    bad["inputs"][0]["text"] = "[curious] Don't be a dummy."
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("Forbidden" in e or "forbidden" in e for e in errors)


def test_rejects_unsettled_ending():
    bad = _make_short("[curious]", "device_x", "park")
    bad["inputs"][-1] = {"voice": "B", "text": "[shouts] AAAARGH"}
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("Final line must be standalone" in e for e in errors)


def test_accepts_settled_ending_via_soft_word():
    good = _make_short("[curious]", "device_x", "park")
    good["inputs"][-1] = {"voice": "B", "text": "okay yeah whatever"}
    errors = validate_funny_short(good, recent_shorts=[], lang="en")
    assert not any("not bedtime-settled" in e for e in errors)


def test_rejects_overlong_title():
    bad = _make_short("[curious]", "device_x", "park")
    bad["title"] = "x" * 31
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("Title too long" in e for e in errors)


# ────────────────────────────────────────────────────────────────────────
#  Task 3 — Hindi-specific
# ────────────────────────────────────────────────────────────────────────

GOOD_HI = {
    "title": "Chai Ki Cheez",
    "title_en": "The Chai Thing",
    "lang": "hi",
    "comedic_device": "earnest_vs_skeptical",
    "setting": "during a power cut",
    "opening_tag": "[matter-of-fact]",
    "closing_pattern": "thoughtful_pause",
    "character_age_dynamic": "siblings",
    "inputs": [
        {"voice": "A", "text": "[matter-of-fact] Bijli phir gayi yaar."},
        {"voice": "B", "text": "[grinning] Pakka mosquito ne fuse uda diya."},
        {"voice": "A", "text": "[serious] Mosquito ke paas pliers nahin hai."},
        {"voice": "B", "text": "[laughs]"},
        {"voice": "A", "text": "Tumhara dimaag bhi power cut hai yaar."},
        {"voice": "B", "text": "[laughs together]"},
    ],
}


def test_good_hindi_short_validates():
    errors = validate_funny_short(GOOD_HI, recent_shorts=[], lang="hi")
    assert errors == [], f"Expected none, got: {errors}"


def test_rejects_devanagari_in_dialogue():
    bad = {**GOOD_HI, "inputs": list(GOOD_HI["inputs"])}
    bad["inputs"][0] = {"voice": "A", "text": "मुझे चाय चाहिए"}
    errors = validate_funny_short(bad, recent_shorts=[], lang="hi")
    assert any("Devanagari" in e for e in errors)


def test_rejects_devanagari_in_title():
    bad = {**GOOD_HI, "title": "चाय की कहानी"}
    errors = validate_funny_short(bad, recent_shorts=[], lang="hi")
    assert any("Devanagari" in e for e in errors)


def test_rejects_missing_title_en_on_hindi():
    bad = {**GOOD_HI}
    bad.pop("title_en")
    errors = validate_funny_short(bad, recent_shorts=[], lang="hi")
    assert any("title_en" in e for e in errors)


def test_rejects_literary_hindi():
    bad = {**GOOD_HI, "inputs": list(GOOD_HI["inputs"])}
    bad["inputs"][0] = {"voice": "A", "text": "[curious] Mujhe nidra aa rahi hai."}
    errors = validate_funny_short(bad, recent_shorts=[], lang="hi")
    assert any("Literary" in e for e in errors)


def test_rejects_religious_content_hindi():
    bad = {**GOOD_HI, "inputs": list(GOOD_HI["inputs"])}
    bad["inputs"][0] = {"voice": "A", "text": "[curious] Aaj puja karni hai."}
    errors = validate_funny_short(bad, recent_shorts=[], lang="hi")
    assert any("Religious" in e for e in errors)


def test_rejects_caste_word_hindi():
    bad = {**GOOD_HI, "inputs": list(GOOD_HI["inputs"])}
    bad["inputs"][0] = {"voice": "A", "text": "[curious] Tum motu ho yaar."}
    errors = validate_funny_short(bad, recent_shorts=[], lang="hi")
    assert any("Forbidden word" in e for e in errors)


def test_rejects_indian_brand_hindi():
    bad = {**GOOD_HI, "inputs": list(GOOD_HI["inputs"])}
    bad["inputs"][0] = {"voice": "A", "text": "[curious] Parle-G de do."}
    errors = validate_funny_short(bad, recent_shorts=[], lang="hi")
    assert any("brand" in e.lower() or "forbidden" in e.lower() for e in errors)


# ────────────────────────────────────────────────────────────────────────
#  Real-laughter rules (added after user feedback that v3 needs
#  standalone tag-only lines to produce actual non-verbal audio)
# ────────────────────────────────────────────────────────────────────────

def test_rejects_no_standalone_laughter_line():
    bad = dict(GOOD_EN)
    bad["inputs"] = [
        {"voice": "A", "text": "[curious] Hi there friend."},
        {"voice": "B", "text": "[grinning] Hi back."},
        {"voice": "A", "text": "[thoughtful] How are you."},
        {"voice": "B", "text": "[matter-of-fact] Doing well."},
        {"voice": "A", "text": "[grinning] Cool cool."},
        {"voice": "B", "text": "yeah okay fine."},
    ]
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("standalone laughter" in e for e in errors), errors


def test_accepts_standalone_laughs_anywhere():
    good = dict(GOOD_EN)
    good["inputs"] = [
        {"voice": "A", "text": "[curious] Hi."},
        {"voice": "B", "text": "[laughs]"},
        {"voice": "A", "text": "[thoughtful] What."},
        {"voice": "B", "text": "[grinning] Funny face."},
        {"voice": "A", "text": "[serious] Stop."},
        {"voice": "B", "text": "[laughs together]"},
    ]
    errors = validate_funny_short(good, recent_shorts=[], lang="en")
    assert not any("standalone laughter" in e for e in errors)


def test_rejects_grinning_alone_as_final_line():
    bad = dict(GOOD_EN)
    bad["inputs"] = [
        {"voice": "A", "text": "[curious] Hi."},
        {"voice": "B", "text": "[laughs]"},  # standalone laughter elsewhere
        {"voice": "A", "text": "[thoughtful] What."},
        {"voice": "B", "text": "[grinning] Funny face."},
        {"voice": "A", "text": "[serious] Stop."},
        {"voice": "B", "text": "[grinning]"},  # standalone grinning — not allowed as final
    ]
    errors = validate_funny_short(bad, recent_shorts=[], lang="en")
    assert any("Final line must be standalone" in e for e in errors)


def test_accepts_soft_prose_final_line():
    good = dict(GOOD_EN)
    good["inputs"] = [
        {"voice": "A", "text": "[curious] Hi."},
        {"voice": "B", "text": "[laughs]"},
        {"voice": "A", "text": "[thoughtful] What."},
        {"voice": "B", "text": "[grinning] Funny."},
        {"voice": "A", "text": "[serious] Stop."},
        {"voice": "B", "text": "Yeah okay fine I guess."},  # soft prose — accepted
    ]
    errors = validate_funny_short(good, recent_shorts=[], lang="en")
    assert not any("Final line must be standalone" in e for e in errors)
