"""Post-generation physiology validators A1-A4 -- the enforced sleep guarantee.

Each check returns (ok: bool, reason: str). A story is accepted only if all
four pass; a failure rejects it (regenerate). Designed to BITE: see
test_physiology_validators.py for the crafted violations each must reject.

A1  arousal only falls after the opening (activation, not length)
A2  prosody slows (sentence length shrinks)
A3  exhale >= inhale on every breath beat (emergent, world-metaphor aware)
A4  ending dissolves, never resolves-to-alertness (conjunction, final-section only)

See docs/superpowers/specs/2026-07-02-long-story-generation-redesign.md
"""
import re
from _story_axes import BREATH_EXPRESSIONS

# ─────────────────────────── shared helpers ───────────────────────────

_TAG = re.compile(r"\[[^\]]*\]")
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+|।+")  # . ! ? … newline danda


def _strip_tags(text):
    return _TAG.sub(" ", text)


def _sentences(text):
    t = _strip_tags(text)
    return [p.strip() for p in _SENT_SPLIT.split(t) if p.strip()]


def _words(s):
    return re.findall(r"[A-Za-zऀ-ॿ']+", s)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _slope(ys):
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx, my = _mean(xs), _mean(ys)
    denom = sum((x - mx) ** 2 for x in xs) or 1.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


# ═══════════════════════════════ A1 ═══════════════════════════════════
# Arousal = ACTIVATION (stakes / excitement), measured separately from length.

AROUSAL_WORDS = {
    # EN
    "rushed", "raced", "dashed", "shouted", "screamed", "yelled", "burst",
    "danger", "dangerous", "scared", "afraid", "terrified", "panic", "panicked",
    "urgent", "hurry", "hurried", "faster", "quicker", "louder", "chase", "chased",
    "jumped", "leapt", "sprang", "crash", "crashed", "bang", "alarm", "frantic",
    "roared", "shriek", "shrieked", "thundered",
    # HI (roman)
    "bhaaga", "bhaagi", "dauda", "daudi", "chillaya", "chillayi", "ghabraya",
    "ghabrayi", "dara", "dari", "darr", "khatra", "halla", "kooda", "koodi",
    "shor", "ghabrahat", "bhaagam", "tez",
}

# Stakes/threat -- often UNPUNCTUATED, no arousal word. Weight 3. Hard-banned
# in the back half. (Answers "the whole garden was about to vanish".)
STAKES_PATTERNS = [
    re.compile(r"\babout to (vanish|disappear|break|shatter|end|fall|go out|stop|crumble|melt away|be lost|be gone)\b", re.I),
    re.compile(r"\brunning out of time\b", re.I),
    re.compile(r"\bbefore it('?s| is| was)?\s+too late\b", re.I),
    re.compile(r"\b(last|only) chance\b", re.I),
    re.compile(r"\bnever (again|come back|return)\b", re.I),
    re.compile(r"\bwould be (lost|gone) forever\b", re.I),
    re.compile(r"\bno time (to|left)\b", re.I),
    re.compile(r"\bif [^,.]{0,30}\b(did ?n['o]?t|could ?n['o]?t|failed|wo ?n['o]?t)\b", re.I),
    re.compile(r"\bwas about to\b", re.I),
    # HI stakes
    re.compile(r"\bkhatam hone wal[ai]\b", re.I),
    re.compile(r"\bgayab hone wal[ai]\b", re.I),
    re.compile(r"\bwaqt nikal raha\b", re.I),
    re.compile(r"\baakhri mauka\b", re.I),
    re.compile(r"\bder ho rah[ii]\b", re.I),
]

CLIFFHANGER_PATTERNS = [
    # "but then"/"all at once"/"tabhi" removed: all over-match calm narrative.
    # "tabhi" is Hindi narrative sequencing ("tabhi X ne kaha" = "then X said"),
    # not a cliffhanger — it fired on a plain dialogue lead-in in the batch, and
    # since A1 GATES generation a false-positive costs a re-pick. suddenly/just
    # then/out of nowhere/achanak/ekdam se are unambiguous surge markers;
    # "achanak"/"ekdam se" keep the genuine Hindi cliffhangers caught.
    re.compile(r"\bsuddenly\b", re.I),
    re.compile(r"\bjust then\b", re.I),
    re.compile(r"\bout of nowhere\b", re.I),
    re.compile(r"\bachanak\b", re.I),
    re.compile(r"\bekdam se\b", re.I),
]


# A negated arousal word is CALM, not aroused ("koi darr nahin" = no fear;
# "wasn't afraid"). This handles negation GENERALLY for every arousal word,
# not one word at a time — the 3rd arousal false-positive after "all at once"
# and "but then", both already removed.
_NEGATIONS = {"no", "not", "never", "without", "nahin", "nahi", "bina", "mat"}


def _negated(ws, i):
    # negation within 2 words either side: EN "no fear"/"wasn't afraid" (before),
    # HI "darr nahin" (after).
    for j in range(max(0, i - 2), min(len(ws), i + 3)):
        w = ws[j]
        if w in _NEGATIONS or w.endswith("n't"):
            return True
    return False


def _arousal_score(sentence):
    s = sentence.lower()
    ws = _words(s)
    score = sum(1 for i, w in enumerate(ws) if w in AROUSAL_WORDS and not _negated(ws, i))
    score += 2 * s.count("!")
    for p in CLIFFHANGER_PATTERNS:
        score += 2 * len(p.findall(s))
    for p in STAKES_PATTERNS:
        score += 3 * len(p.findall(s))
    return 100.0 * score / max(1, len(ws))  # per-100-words


def _deciles(items):
    n = len(items)
    return [items[int(i * n / 10):int((i + 1) * n / 10)] for i in range(10)]


def check_a1(text):
    sents = _sentences(text)
    n = len(sents)
    if n < 6:
        return True, "A1 n/a (too short to trend)"
    # Hard bans anywhere in the back half (from midpoint on).
    back = sents[n // 2:]
    back_join = " ".join(back)
    if "!" in back_join:
        return False, "A1 FAIL: exclamation mark in back half"
    for p in CLIFFHANGER_PATTERNS:
        if p.search(back_join):
            return False, f"A1 FAIL: cliffhanger connective in back half ({p.pattern})"
    for p in STAKES_PATTERNS:
        if p.search(back_join):
            return False, f"A1 FAIL: stakes/threat phrase in back half ({p.pattern})"
    # Density trend: back-half arousal must not exceed the opening peak.
    dec = _deciles(sents)
    scores = [_mean([_arousal_score(s) for s in d]) if d else 0.0 for d in dec]
    opening_peak = max(scores[0:2]) if scores else 0.0
    back_max = max(scores[5:10]) if scores else 0.0
    if back_max > opening_peak and back_max > 1.0:
        return False, f"A1 FAIL: arousal rises in back half (back={back_max:.2f} > open={opening_peak:.2f})"
    return True, "A1 ok"


# ═══════════════════════════════ A2 ═══════════════════════════════════

def check_a2(text):
    sents = _sentences(text)
    n = len(sents)
    if n < 10:
        return True, "A2 n/a (too short)"
    lengths = [len(_words(s)) for s in sents]
    dec = max(1, n // 10)
    last_decile = _mean(lengths[-dec:])
    sl = _slope(lengths)
    # A short dissolving ending (last-decile <= 6 words) plus a downward
    # overall trend (negative slope) is the guarantee. The old first/last-
    # third *ratio* check was dropped: it false-rejected stories that slow
    # gradually into a genuinely short tail (24% vs an arbitrary 30% bar).
    if last_decile > 7:
        return False, f"A2 FAIL: final lines not short (last-decile mean {last_decile:.1f} > 7)"
    if sl >= 0:
        return False, f"A2 FAIL: sentence-length slope not negative ({sl:.2f})"
    return True, "A2 ok"


# ═══════════════════════════════ A3 ═══════════════════════════════════
# Breath beat located via [BREATHE] anchor + world-metaphor cue lexicon.
# out-clause words >= in-clause words (the long exhale), on every paired line.

def _dir_regex(cue_key, extra):
    """Compile a direction regex from the shared BREATH_EXPRESSIONS cues.

    Each cue allows an inflection suffix (\\w{0,3}) so 'swell' matches
    'swells'/'swelled', and the literal-breath extras use 'breath\\w*' so
    'breathe/breathes/breathed out' all match. This is what keeps emergent
    world-metaphor breath (and real model inflections) validatable."""
    cues = set()
    for be in BREATH_EXPRESSIONS.values():
        cues.update(c.lower() for c in be[cue_key])
    parts = []
    for c in sorted(cues, key=len, reverse=True):
        parts.append(re.escape(c).replace(r"\ ", r"\s+") + r"\w{0,3}")
    parts += extra
    return re.compile("|".join(parts), re.I)


_IN_RE = _dir_regex("in_cues", [r"breath\w*\s+in", r"in[-\s]breath", r"draw\w*\s+in"])
_OUT_RE = _dir_regex("out_cues", [r"breath\w*\s+out", r"out[-\s]breath",
                                   r"let\w*\s+(?:it\s+|the\s+\w+\s+)?go", r"exhal\w*"])


# Order-independent A3: the out-breath cue must carry an elongation marker
# in its window (the exhale is rendered long/slow), and no breath beat may
# render the exhale short/fast. Stems match inflections (slow->slowly,
# lamb->lambi/lamba, dheer->dheere) across EN + HI.
_ELONG_STEMS = ["long", "slow", "stretch", "wide", "unhurried", "linger",
                "lamb", "dheem", "dheer", "phail", "khich", "faila"]
_SHORT_STEMS = ["fast", "quick", "sharp", "short", "brief", "sudden",
                "jaldi", "tez", "turant", "jhatk"]


def _win_words(text_lower, char_start, before=3, after=8):
    wi = len(text_lower[:char_start].split())
    words = re.sub(r"[.,;:—\-]", " ", text_lower).split()
    return words[max(0, wi - before): wi + after + 1]


def _breath_texts(text):
    """Breath beats = prose adjacent to a [BREATHE] tag, plus any sentence
    naming breath/saans. Tag-adjacency is what makes pure world-metaphor
    breath (no literal 'breathe in/out') locatable, and restricting to these
    avoids false pairings on unrelated 'open'/'rise' prose."""
    out = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if re.search(r"\[BREATHE\]", ln, re.I):
            rest = _strip_tags(ln).strip()
            if rest:
                out.append(rest)
            # The woven breath sentence may sit just BEFORE the tag (the
            # prompt puts it before) or just after — capture both sides.
            for j in range(i - 1, -1, -1):
                if lines[j].strip():
                    out.append(_strip_tags(lines[j]).strip())
                    break
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    out.append(_strip_tags(lines[j]).strip())
                    break
    for s in _sentences(text):
        if re.search(r"\b(breath|saans|exhal|inhal)", s, re.I):
            out.append(s)
    return out


def check_a3(text):
    breathe_tags = [m.start() for m in re.finditer(r"\[BREATHE\]", text, re.I)]
    if len(breathe_tags) < 3:
        return False, f"A3 FAIL: only {len(breathe_tags)} [BREATHE] tags (need >= 3)"
    # >= 1 [BREATHE] in the back half
    if not any(pos > len(text) // 2 for pos in breathe_tags):
        return False, "A3 FAIL: no [BREATHE] beat in the back half"
    long_shown = 0
    for t in _breath_texts(text):
        tl = t.lower()
        # Only an explicit breath line (breath/saans) can trip the "short
        # exhale" rejection — otherwise a non-breath metaphor verb near a
        # [BREATHE] tag (e.g. "the petals open fast") would false-positive.
        breath_line = bool(re.search(r"\b(breath|saans)", tl))
        for m in _OUT_RE.finditer(tl):
            # near = right at the exhale (short word here = short exhale, even
            # if an unrelated "slow" floats downstream). wide = elongation may
            # legitimately trail a few words ("breathed out, the glow spread
            # wide and slow"). This two-window rule keeps the widened reach for
            # real long exhales without passing a genuinely-short one that
            # happens to have a far-off elong word.
            near = _win_words(tl, m.start(), before=1, after=4)
            wide = _win_words(tl, m.start(), before=3, after=8)
            short_near = any(stem in w for w in near for stem in _SHORT_STEMS)
            elong_near = any(stem in w for w in near for stem in _ELONG_STEMS)
            elong_wide = any(stem in w for w in wide for stem in _ELONG_STEMS)
            if short_near and not elong_near and breath_line:
                return False, (f"A3 FAIL: exhale rendered short/fast, not long "
                               f"(near out-breath): '{t[:70]}'")
            if elong_wide:
                long_shown += 1
    if long_shown == 0:
        return False, ("A3 FAIL: the long exhale is never rendered — no out-breath cue "
                       "is described as long/slow (bare [BREATHE] swells are not enough)")
    return True, f"A3 ok ({len(breathe_tags)} beats, {long_shown} long-exhale renderings)"


# ═══════════════════════════════ A4 ═══════════════════════════════════

ALERT_WORDS = [
    "woke", "awake", "awoke", "wide-eyed", "wide awake", "sprang", "jumped up",
    "leapt up", "energized", "excited", "hurray", "cheered", "victory", "won",
    "ready to go", "ready to play", "brand-new day", "brand new day", "wake up",
    # HI
    "jaag gaya", "jaag gayi", "jaag uthi", "jaag utha", "uth gaya", "uth gayi",
    "kal phir", "khush ho kar chillay",
]
STILL_TERMINALS = [
    "asleep", "sleeping", "sleep", "still", "quiet", "silent", "dark", "dream",
    "drifted off", "drifting", "slumber",
    # HI
    "so raha", "so rahi", "so gaya", "so gayi", "so rahe", "so gaye", "so jao",
    "neend", "shaant", "chup", "andhera", "sapne", "sapna",
    "tham gaya", "tham gayi", "tham gaye", "thami", "tham",  # "stilled" — a valid dissolution close
]

_WHISPER = re.compile(r"\[WHISPER\](.*?)\[/WHISPER\]", re.I | re.S)


def check_a4(text):
    # Final section = ALL [WHISPER] blocks (a dissolving ending often has
    # several) plus the last ~10% of sentences — not just the last block.
    m = _WHISPER.findall(text)
    sents = _sentences(text)
    dec = max(1, len(sents) // 10)
    tail = " ".join(sents[-dec:])
    final = (" ".join(m) + " " + tail) if m else tail
    f = _strip_tags(final).lower()
    if "!" in f:
        return False, "A4 FAIL: exclamation in the ending"
    for w in ALERT_WORDS:
        if w in f:
            return False, f"A4 FAIL: alertness/waking word in ending ('{w}')"
    if not any(t in f for t in STILL_TERMINALS):
        return False, "A4 FAIL: no stillness/sleep terminal in the ending"
    return True, "A4 ok"


VALIDATORS = [("A1", check_a1), ("A2", check_a2), ("A3", check_a3), ("A4", check_a4)]


def validate_all(text):
    """Return (all_ok, [(name, ok, reason), ...])."""
    results = [(name, *fn(text)) for name, fn in VALIDATORS]
    return all(r[1] for r in results), results
