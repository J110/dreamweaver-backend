# Dream Valley — Funny Shorts Diversity Scheduler
## Fingerprint-Based Generation Targeting

---

## The Problem

Without guidance, the LLM generates the same kind of short repeatedly. Six shorts produced three "Couldn't X" and three "Forgot X" — all solo, mostly physical_escalation. The LLM finds one template that works and rides it.

## The Solution

Don't tell the LLM what to avoid. Tell it exactly what to generate. A scheduler analyzes the existing library, finds the most underrepresented dimensions, and produces a specific generation brief: "Generate a VILLAIN_FAILS DUO with CROC and SWEET for ages 6-8."

The prompt stays short. The diversity comes from the selection logic, not from growing ban lists.

---

## The Fingerprint

Every funny short gets three dimensions. That's enough — funny shorts are simpler than stories.

```json
{
    "id": "crocodile-rock-001",
    "title": "The Crocodile Who Was Definitely a Rock",
    "age_group": "6-8",
    "comedy_type": "villain_fails",
    "format": "duo",
    "voice_combo": ["comedic_villain", "high_pitch_cartoon"],
    "primary_voice": "comedic_villain"
}
```

### Dimension 1: Comedy Type

What kind of funny is this?

| Comedy Type | Description |
|---|---|
| `physical_escalation` | Something physical happens 3 times, getting more absurd |
| `villain_fails` | Character with grand plans fails spectacularly |
| `misunderstanding` | Character misinterprets something obvious |
| `ominous_mundane` | Narrator describes absurd things with complete seriousness |
| `sarcastic_commentary` | Deadpan commentary on absurd situations |
| `sound_effect` | Humor IS the sounds — onomatopoeia, vocal performance |

### Dimension 2: Format

How many characters?

| Format | Description |
|---|---|
| `solo` | One character, one voice |
| `duo` | Two characters in dialogue |
| `trio` | Three characters — usually narrator + two in dialogue |

### Dimension 3: Voice Combo

Which specific characters? This is the combination of voices used, sorted alphabetically for consistent comparison.

Examples:
- `["high_pitch_cartoon"]` — Mouse solo
- `["comedic_villain", "high_pitch_cartoon"]` — Croc + Mouse duo
- `["comedic_villain", "high_pitch_cartoon", "mysterious_witch"]` — trio

---

## Target Distributions

### Comedy Type Targets

```python
COMEDY_TYPE_TARGET = {
    "physical_escalation":  0.20,
    "villain_fails":        0.20,
    "misunderstanding":     0.15,
    "ominous_mundane":      0.15,
    "sarcastic_commentary": 0.15,
    "sound_effect":         0.15,
}
```

### Format Targets

```python
FORMAT_TARGET = {
    "solo": 0.40,
    "duo":  0.40,
    "trio": 0.20,
}
```

### Comedy Type × Age Validity

Not all comedy types work for all ages:

```python
COMEDY_AGE_VALID = {
    "2-5":  ["physical_escalation", "villain_fails", "sound_effect"],
    "6-8":  ["physical_escalation", "villain_fails", "misunderstanding", 
             "ominous_mundane", "sarcastic_commentary", "sound_effect"],
    "9-12": ["villain_fails", "misunderstanding", "ominous_mundane", 
             "sarcastic_commentary"],
}
```

### Voice × Age Validity

```python
VOICE_AGE_VALID = {
    "2-5":  ["high_pitch_cartoon", "comedic_villain", "musical_original"],
    "6-8":  ["high_pitch_cartoon", "comedic_villain", "young_sweet", 
             "mysterious_witch", "musical_original"],
    "9-12": ["comedic_villain", "young_sweet", "mysterious_witch", 
             "musical_original"],
}
```

### Comedy Type × Voice Affinity

Some comedy types have natural voice pairings. Not hard rules — preferences that the scheduler uses when multiple voice combos are equally underrepresented.

```python
COMEDY_VOICE_AFFINITY = {
    "physical_escalation":  {
        "solo": ["high_pitch_cartoon"],
        "duo":  ["high_pitch_cartoon", "comedic_villain"],
    },
    "villain_fails": {
        "solo": ["comedic_villain"],
        "duo":  ["comedic_villain", "high_pitch_cartoon"],
        "trio": ["comedic_villain", "high_pitch_cartoon", "mysterious_witch"],
    },
    "misunderstanding": {
        "solo": ["young_sweet"],
        "duo":  ["young_sweet", "comedic_villain"],
    },
    "ominous_mundane": {
        "solo": ["mysterious_witch"],
        "duo":  ["mysterious_witch", "young_sweet"],
    },
    "sarcastic_commentary": {
        "solo": ["young_sweet"],
        "duo":  ["young_sweet", "comedic_villain"],
    },
    "sound_effect": {
        "solo": ["high_pitch_cartoon"],
        "duo":  ["high_pitch_cartoon", "comedic_villain"],
    },
}
```

---

## The Scheduler

### Core Selection Logic

```python
def select_funny_short_spec(existing_shorts, age_group):
    """
    Analyze existing library and return exactly what to generate next.
    
    Returns:
        {
            "comedy_type": "ominous_mundane",
            "format": "duo",
            "voices": ["mysterious_witch", "young_sweet"],
            "age_group": "6-8",
        }
    """
    # Filter to this age group
    age_shorts = [s for s in existing_shorts if s["age_group"] == age_group]
    total = len(age_shorts) or 1
    
    # 1. Pick most underrepresented comedy type valid for this age
    comedy_type = _select_comedy_type(age_shorts, total, age_group)
    
    # 2. Pick most underrepresented format
    format_type = _select_format(age_shorts, total)
    
    # 3. Pick voice combo
    voices = _select_voices(
        age_shorts, age_group, comedy_type, format_type
    )
    
    return {
        "comedy_type": comedy_type,
        "format": format_type,
        "voices": voices,
        "age_group": age_group,
    }
```

### Step 1: Select Comedy Type

```python
def _select_comedy_type(age_shorts, total, age_group):
    """Pick the comedy type with the largest deficit for this age group."""
    valid_types = COMEDY_AGE_VALID[age_group]
    type_counts = Counter(s["comedy_type"] for s in age_shorts)
    
    # Find largest deficit
    max_deficit = -1
    selected = valid_types[0]
    
    for ctype in valid_types:
        target = COMEDY_TYPE_TARGET.get(ctype, 0.15)
        actual = type_counts.get(ctype, 0) / total
        deficit = target - actual
        if deficit > max_deficit:
            max_deficit = deficit
            selected = ctype
    
    return selected
```

### Step 2: Select Format

```python
def _select_format(age_shorts, total):
    """Pick the format with the largest deficit."""
    format_counts = Counter(s["format"] for s in age_shorts)
    
    max_deficit = -1
    selected = "solo"
    
    for fmt, target in FORMAT_TARGET.items():
        actual = format_counts.get(fmt, 0) / total
        deficit = target - actual
        if deficit > max_deficit:
            max_deficit = deficit
            selected = fmt
    
    return selected
```

### Step 3: Select Voices

```python
def _select_voices(age_shorts, age_group, comedy_type, format_type):
    """Pick the least-used valid voice combo for this comedy type + format."""
    valid_voices = VOICE_AGE_VALID[age_group]
    
    # Get the affinity suggestion
    affinity = COMEDY_VOICE_AFFINITY.get(comedy_type, {})
    suggested = affinity.get(format_type)
    
    if format_type == "solo":
        return _select_solo_voice(age_shorts, valid_voices, suggested)
    elif format_type == "duo":
        return _select_duo_voices(age_shorts, valid_voices, suggested)
    else:  # trio
        return _select_trio_voices(age_shorts, valid_voices, suggested)


def _select_solo_voice(age_shorts, valid_voices, suggested):
    """Pick least-used voice for a solo short."""
    voice_counts = Counter()
    for s in age_shorts:
        if s["format"] == "solo" and s.get("primary_voice"):
            voice_counts[s["primary_voice"]] += 1
    
    # Prefer suggested voice if it's the least used
    if suggested and suggested[0] in valid_voices:
        if voice_counts.get(suggested[0], 0) == min(
            voice_counts.get(v, 0) for v in valid_voices
        ):
            return suggested
    
    # Otherwise pick least used
    least_used = min(valid_voices, key=lambda v: voice_counts.get(v, 0))
    return [least_used]


def _select_duo_voices(age_shorts, valid_voices, suggested):
    """Pick least-used voice pair for a duo."""
    combo_counts = Counter()
    for s in age_shorts:
        if s["format"] == "duo":
            combo_key = tuple(sorted(s["voice_combo"]))
            combo_counts[combo_key] += 1
    
    # Generate all valid pairs
    from itertools import combinations
    all_pairs = list(combinations(valid_voices, 2))
    
    # Prefer suggested if it's least used
    if suggested and len(suggested) == 2:
        suggested_key = tuple(sorted(suggested))
        if all(v in valid_voices for v in suggested):
            if combo_counts.get(suggested_key, 0) == min(
                combo_counts.get(tuple(sorted(p)), 0) for p in all_pairs
            ):
                return list(suggested)
    
    # Pick least used pair
    least_used = min(all_pairs, key=lambda p: combo_counts.get(tuple(sorted(p)), 0))
    return list(least_used)


def _select_trio_voices(age_shorts, valid_voices, suggested):
    """Pick least-used voice trio."""
    combo_counts = Counter()
    for s in age_shorts:
        if s["format"] == "trio":
            combo_key = tuple(sorted(s["voice_combo"]))
            combo_counts[combo_key] += 1
    
    from itertools import combinations
    all_trios = list(combinations(valid_voices, 3))
    
    if suggested and len(suggested) == 3:
        suggested_key = tuple(sorted(suggested))
        if all(v in valid_voices for v in suggested):
            if combo_counts.get(suggested_key, 0) == min(
                combo_counts.get(tuple(sorted(t)), 0) for t in all_trios
            ):
                return list(suggested)
    
    least_used = min(all_trios, key=lambda t: combo_counts.get(tuple(sorted(t)), 0))
    return list(least_used)
```

---

## Generation Prompt

The scheduler output becomes a short, specific prompt:

```python
def build_funny_short_prompt(spec):
    """Turn scheduler output into a generation prompt."""
    
    voice_names = [VOICE_DISPLAY_NAMES[v] for v in spec["voices"]]
    voice_descriptions = "\n".join([
        f"- {VOICE_DISPLAY_NAMES[v]}: {VOICE_DESCRIPTIONS[v]}"
        for v in spec["voices"]
    ])
    
    prompt = f"""
Generate a {spec['comedy_type'].upper().replace('_', ' ')} funny short 
for ages {spec['age_group']}.

Format: {spec['format'].upper()} ({len(spec['voices'])} character{'s' if len(spec['voices']) > 1 else ''})

Characters:
{voice_descriptions}

{AGE_COMEDY_INSTRUCTIONS[spec['age_group']]}

{FUNNY_SHORT_STRUCTURE_RULES}
"""
    return prompt

VOICE_DISPLAY_NAMES = {
    "high_pitch_cartoon": "MOUSE",
    "comedic_villain":    "CROC",
    "young_sweet":        "SWEET",
    "mysterious_witch":   "WITCH",
    "musical_original":   "MUSICAL",
}

VOICE_DESCRIPTIONS = {
    "high_pitch_cartoon": "Squeaky Minnie Mouse energy. Reacts with alarm and panic.",
    "comedic_villain":    "Deep dramatic crocodile. Self-important, always failing.",
    "young_sweet":        "Innocent-sounding but sarcastic. Deadpan. Unbothered.",
    "mysterious_witch":   "Dark, low, mysterious. Makes everything a dark prophecy.",
    "musical_original":   "Rhythmic, poetic, almost singing. The straight man.",
}
```

### What the LLM Sees

For the scheduler output `{"comedy_type": "ominous_mundane", "format": "duo", "voices": ["mysterious_witch", "young_sweet"], "age_group": "9-12"}`:

```
Generate an OMINOUS MUNDANE funny short for ages 9-12.

Format: DUO (2 characters)

Characters:
- WITCH: Dark, low, mysterious. Makes everything a dark prophecy.
- SWEET: Innocent-sounding but sarcastic. Deadpan. Unbothered.

Ages 9-12: Deadpan, sarcasm, and understatement...
(age instructions)

STRUCTURE:
- SETUP: 2-3 sentences...
(structure rules)
```

Short, specific, no ban lists. The LLM can't produce a physical_escalation Mouse solo because it wasn't asked for one.

---

## Recency Check

On top of the target distribution, add a simple recency rule: no identical fingerprint in the last 5 shorts.

```python
def check_recency(spec, recent_shorts, lookback=5):
    """Ensure this exact combo hasn't been generated in the last 5 shorts."""
    recent = recent_shorts[-lookback:]
    
    for s in recent:
        if (s["comedy_type"] == spec["comedy_type"] and 
            s["format"] == spec["format"] and
            tuple(sorted(s["voice_combo"])) == tuple(sorted(spec["voices"]))):
            return False  # too similar to recent
    
    return True

def select_with_recency(existing_shorts, age_group, max_attempts=5):
    """Select spec with recency validation."""
    for attempt in range(max_attempts):
        spec = select_funny_short_spec(existing_shorts, age_group)
        
        if check_recency(spec, existing_shorts):
            return spec
        
        # If recency fails, temporarily boost the second-most-underrepresented
        # type/format to get a different combination
        existing_shorts_modified = existing_shorts + [
            {"comedy_type": spec["comedy_type"], 
             "format": spec["format"],
             "voice_combo": spec["voices"],
             "age_group": age_group}
        ]  # pretend this one exists to force a different pick
        existing_shorts = existing_shorts_modified
    
    # After max attempts, just use whatever we got
    return select_funny_short_spec(existing_shorts, age_group)
```

---

## Walkthrough: What Happens After the First 6 Shorts

Current library:
```
1. "Couldn't Sit Still"      → physical_escalation, solo, [mouse]         (2-5)
2. "Couldn't Stop Sneezing"  → physical_escalation, solo, [mouse]         (2-5)
3. "Couldn't Stop Honking"   → physical_escalation, solo, [croc]          (6-8)
4. "Forgot How to Croc"      → misunderstanding,    solo, [croc]          (6-8)
5. "Forgot to Be Scary"      → villain_fails,       solo, [croc]          (9-12)
6. "Forgot His Own Plan"      → villain_fails,       solo, [croc]          (9-12)
```

**Scheduler picks for short #7 (age 6-8):**

```
Comedy type analysis (6-8 shorts only: #3 physical, #4 misunderstanding):
  physical_escalation: 50% (target 20%) → OVER
  misunderstanding:    50% (target 15%) → OVER  
  villain_fails:        0% (target 20%) → deficit 0.20
  ominous_mundane:      0% (target 15%) → deficit 0.15
  sarcastic_commentary: 0% (target 15%) → deficit 0.15
  sound_effect:         0% (target 15%) → deficit 0.15
  
  → Picks: villain_fails (largest deficit)

Format analysis (6-8 shorts only: #3 solo, #4 solo):
  solo: 100% (target 40%) → OVER
  duo:    0% (target 40%) → deficit 0.40
  trio:   0% (target 20%) → deficit 0.20
  
  → Picks: duo (largest deficit)

Voice combo (villain_fails duo, age 6-8):
  Affinity suggests: [croc, mouse]
  croc used 2x, mouse used 0x for 6-8
  → Picks: [comedic_villain, high_pitch_cartoon]
```

**Generation prompt for short #7:**
```
Generate a VILLAIN FAILS funny short for ages 6-8.
Format: DUO (2 characters)
Characters:
- CROC: Deep dramatic crocodile. Self-important, always failing.
- MOUSE: Squeaky Minnie Mouse energy. Reacts with alarm and panic.
```

**Scheduler picks for short #8 (age 2-5):**

```
Comedy type (2-5 shorts: #1 physical, #2 physical):
  physical_escalation: 100% → OVER
  villain_fails:         0% → deficit 0.20
  sound_effect:          0% → deficit 0.15
  
  → Picks: villain_fails

Format (2-5 shorts: #1 solo, #2 solo):
  solo: 100% → OVER
  duo:    0% → deficit 0.40
  
  → Picks: duo

Voice combo (villain_fails duo, age 2-5):
  Valid voices: mouse, croc, musical
  → Picks: [comedic_villain, high_pitch_cartoon]
```

**Generation prompt for short #8:**
```
Generate a VILLAIN FAILS funny short for ages 2-5.
Format: DUO (2 characters)
Characters:
- CROC: Deep dramatic crocodile. Self-important, always failing.
- MOUSE: Squeaky Minnie Mouse energy. Reacts with alarm and panic.
```

**Scheduler picks for short #9 (age 9-12):**

```
Comedy type (9-12 shorts: #5 villain_fails, #6 villain_fails):
  villain_fails:        100% → OVER
  misunderstanding:       0% → deficit 0.15
  ominous_mundane:        0% → deficit 0.15
  sarcastic_commentary:   0% → deficit 0.15
  
  → Picks: misunderstanding (first alphabetically among tied deficits)

Format (9-12 shorts: #5 solo, #6 solo):
  solo: 100% → OVER
  duo:    0% → deficit 0.40
  
  → Picks: duo

Voice combo (misunderstanding duo, age 9-12):
  Valid voices: croc, sweet, witch, musical
  Affinity suggests: [sweet, croc]
  → Picks: [young_sweet, comedic_villain]
```

**Generation prompt for short #9:**
```
Generate a MISUNDERSTANDING funny short for ages 9-12.
Format: DUO (2 characters)
Characters:
- SWEET: Innocent-sounding but sarcastic. Deadpan. Unbothered.
- CROC: Deep dramatic crocodile. Self-important, always failing.
```

After 9 shorts, the library has: 3 comedy types covered (physical, villain_fails, misunderstanding), mix of solo and duo, multiple voice combos. The scheduler will next push toward ominous_mundane, sarcastic_commentary, sound_effect, and trio format.

---

## CLI Integration

```bash
# Auto-select what's most needed for age 6-8
python3 scripts/generate_funny_short.py --age 6-8 --auto

# Override specific dimensions if needed
python3 scripts/generate_funny_short.py --age 6-8 \
  --comedy-type sarcastic_commentary \
  --format duo \
  --voices young_sweet,comedic_villain

# Generate 3 shorts, each auto-selected
python3 scripts/generate_funny_short.py --age 6-8 --auto --count 3
```

When `--auto` is used, the script runs `select_funny_short_spec()`, prints the selection, and generates accordingly:

```
[AUTO-SELECT] Age 6-8
  Comedy type: ominous_mundane (deficit: 0.15, 0 existing)
  Format: duo (deficit: 0.40, 0 existing)
  Voices: mysterious_witch + young_sweet
  Generating...
```

---

## JSON Schema Update

Every funny short JSON must include the fingerprint fields:

```json
{
    "id": "witch-pancakes-001",
    "title": "The Perfectly Normal Day",
    "age_group": "9-12",
    "comedy_type": "ominous_mundane",
    "format": "duo",
    "voice_combo": ["mysterious_witch", "young_sweet"],
    "primary_voice": "mysterious_witch",
    "premise": "witch narrates a day where absurd things happen as if they're normal",
    "base_track_style": "mysterious",
    "base_track_file": "base_mysterious_02.wav",
    "duration_seconds": 52,
    "audio_file": "witch-pancakes-001.mp3",
    "cover_file": "witch-pancakes-001.webp",
    "created_at": "2026-03-26",
    "play_count": 0,
    "replay_count": 0
}
```

---

## Implementation Checklist

- [ ] Add `COMEDY_TYPE_TARGET`, `FORMAT_TARGET` to config
- [ ] Add `COMEDY_AGE_VALID`, `VOICE_AGE_VALID` validity matrices
- [ ] Add `COMEDY_VOICE_AFFINITY` preference mapping
- [ ] Implement `select_funny_short_spec()` — the core scheduler
- [ ] Implement `check_recency()` — no identical fingerprint in last 5
- [ ] Add `--auto` flag to `generate_funny_short.py`
- [ ] Update funny short JSON schema to include fingerprint fields
- [ ] Ensure `comedy_type`, `format`, `voice_combo` are written at generation time
- [ ] Add `build_funny_short_prompt()` — turns scheduler output into LLM prompt
- [ ] Test: run `--auto` 10 times for age 6-8 — verify no two identical fingerprints and all comedy types eventually represented
