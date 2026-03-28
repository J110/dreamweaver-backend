# Dream Valley — Funny Shorts Episode Structure
## Voice Identity, Show Jingles, Dynamic Host Intro/Outro

---

## Overview

Every funny short is wrapped in a "show" structure that makes Before Bed feel like a real audio show. The child hears a familiar jingle, learns who's in tonight's episode and what they're attempting, then hears the story, then gets a closing callback.

```
[SHOW INTRO JINGLE]     ← 3.5s, static, same every episode
[HOST INTRO]            ← 3-5s, dynamic, Melody reads one-sentence premise
[CHARACTER JINGLES]     ← 2-4.5s, static, one per character in the short
[STORY]                 ← 60-90s, the funny short with base track + stings
[CHARACTER OUTRO]       ← 1-1.5s, static, primary character's sign-off jingle
[HOST OUTRO]            ← 2-4s, dynamic, Melody reads one-sentence callback
[SHOW OUTRO JINGLE]     ← 3.5s, static, same every episode
```

Total bookend time: ~15-20 seconds. Full episode: ~75-110 seconds.

---

## The Five Voices (Renamed)

Voice names describe the **voice quality**, not a character. Boomy can play a crocodile, a bear, a penguin with delusions of grandeur — any character who's dramatic and over-the-top. The voice is a casting choice, not a character identity.

### Voice Profiles

| Voice Name | Voice File | Sounds Like | Casting Range |
|---|---|---|---|
| **Boomy** | comedic_villain | Deep, dramatic, theatrical, over-the-top | Villains, kings, big animals, anyone with an inflated ego, bossy characters, self-important creatures |
| **Pip** | high_pitch_cartoon | Squeaky, high-pitched, Minnie Mouse energy | Small creatures, nervous characters, babies, anything tiny and excitable, the character things happen TO |
| **Shadow** | mysterious_witch | Dark, low-pitched, mysterious, ominous | Narrators, mysterious figures, fortune tellers, old wise characters, anyone who knows more than they're saying |
| **Sunny** | innocent but sarcastic, deadpan | young_sweet | Observers, commentators, bored teenagers, anyone calmly pointing out the obvious, the unbothered voice of reason |
| **Melody** | musical_original | Rhythmic, poetic, warm, measured | Show host (permanent role), poets, fairy-tale narrators, the straight man in ensemble scenes |

### Voice × Age Compatibility

| Voice | Ages 2-5 | Ages 6-8 | Ages 9-12 |
|---|---|---|---|
| Pip | ✅ Primary | ✅ Works | ❌ Too childish |
| Boomy | ✅ Works | ✅ Primary | ✅ Works |
| Sunny | ❌ Sarcasm lost | ✅ Works | ✅ Primary |
| Shadow | ❌ Too dark | ✅ Works | ✅ Primary |
| Melody | ✅ For poems + host | ✅ For host + support | ✅ For host + support |

### Voice Map

```python
FUNNY_VOICE_MAP = {
    "BOOMY":  "comedic_villain",
    "PIP":    "high_pitch_cartoon",
    "SHADOW": "mysterious_witch",
    "SUNNY":  "young_sweet",
    "MELODY": "musical_original",
}
```

### Per-Voice TTS Params

```python
FUNNY_VOICE_PARAMS = {
    "comedic_villain": {         # Boomy
        "exaggeration": 0.85,
        "cfg_weight": 0.55,
        "speed": 0.88,
    },
    "high_pitch_cartoon": {      # Pip
        "exaggeration": 0.80,
        "cfg_weight": 0.60,
        "speed": 0.95,
    },
    "young_sweet": {             # Sunny
        "exaggeration": 0.55,
        "cfg_weight": 0.50,
        "speed": 0.92,
    },
    "mysterious_witch": {        # Shadow
        "exaggeration": 0.65,
        "cfg_weight": 0.45,
        "speed": 0.85,
    },
    "musical_original": {        # Melody
        "exaggeration": 0.70,
        "cfg_weight": 0.55,
        "speed": 0.90,
    },
}
```

### Punchline Params Per Voice

```python
FUNNY_PUNCHLINE_PARAMS = {
    "comedic_villain": {         # Boomy: maximum dramatic outrage
        "exaggeration": 0.92,
        "speed_multiplier": 0.85,
    },
    "high_pitch_cartoon": {      # Pip: even squeakier
        "exaggeration": 0.88,
        "speed_multiplier": 0.90,
    },
    "young_sweet": {             # Sunny: MORE understated — peak sarcasm
        "exaggeration": 0.50,
        "speed_multiplier": 0.95,
    },
    "mysterious_witch": {        # Shadow: slower, more ominous
        "exaggeration": 0.70,
        "speed_multiplier": 0.80,
    },
    "musical_original": {        # Melody: measured flourish
        "exaggeration": 0.78,
        "speed_multiplier": 0.88,
    },
}
```

### Host Voice Params (Melody as Show Host)

```python
HOST_VOICE_PARAMS = {
    "voice": "musical_original",
    "exaggeration": 0.65,       # warm and present, not dramatic
    "cfg_weight": 0.50,
    "speed": 0.90,              # clear, measured announcer pace
}
```

---

## Character Interaction Pairings (Updated Names)

| Pairing | Dynamic | Why It's Funny |
|---|---|---|
| Boomy + Pip | Big ego meets tiny innocent | Boomy's dramatic threats vs Pip's squeaky "okay but why?" |
| Shadow + any | Ominous narration of silly events | "And then... the penguin... SLIPPED" in prophecy voice |
| Sunny + Boomy | Sarcasm meets self-importance | Sunny calmly deflating Boomy's ego |
| Pip + Sunny | Panic meets calm | Pip freaking out, Sunny completely unbothered |
| Shadow + Sunny | Dark drama meets sarcasm | Both deadpan from opposite directions |
| Boomy + Shadow | Villain narrated by ominous voice | Shadow treats Boomy's failure as tragic epic |
| Shadow + Pip + Boomy | Full ensemble | Shadow narrates, Boomy schemes, Pip reacts |

---

## Show Jingles (Static — Generated Once)

### Intro Jingle

The child hears this and instantly knows "it's Before Bed time." Same jingle every episode, every age group, every comedy type.

```python
SHOW_INTRO_JINGLE = {
    "file": "beforebed_intro_jingle.wav",
    "duration_ms": 3500,
}
```

**MusicGen prompt:**
```
3.5 second playful jingle for a children's audio show.
Glockenspiel melody, 4-5 notes ascending, ending on a cheeky 
wobble note. Soft pizzicato bass underneath. One triangle hit 
at the very end. Bright, mischievous, instantly recognizable. 
Like a music box that's slightly naughty. Must sound complete 
in 3.5 seconds — not a fade, a proper ending.
```

### Outro Jingle

Same melody as intro but descending. The musical equivalent of "that was fun, goodnight."

```python
SHOW_OUTRO_JINGLE = {
    "file": "beforebed_outro_jingle.wav",
    "duration_ms": 3500,
}
```

**MusicGen prompt:**
```
3.5 second closing jingle for a children's audio show.
SAME melody and instruments as the intro (glockenspiel, pizzicato 
bass) but DESCENDING instead of ascending. Slower tempo. The last 
note rings out and fades gently. Like the intro melody going to 
sleep. Must feel like the intro played backwards and sleepier.
```

**Critical:** Intro and outro must use the SAME melody — ascending for intro, descending for outro. Generate together or use intro as reference for outro.

---

## Character Jingles (Static — Generated Once Per Voice)

### Intro Jingles

Each voice has a 2-2.5 second musical signature. Plays after the host intro to announce who's in tonight's episode. The child learns: tuba = Boomy, xylophone = Pip, celesta = Shadow.

```python
CHARACTER_INTRO_JINGLES = {
    "comedic_villain": {
        "file": "char_jingle_boomy_intro.wav",
        "duration_ms": 2500,
        "musicgen_prompt": "2.5 second comedic villain entrance. Low tuba "
                           "playing 3 notes — dun, dun, DUNNN. Sneaky, "
                           "dramatic, played for laughs. Cartoon villain "
                           "stepping onto stage.",
    },
    "high_pitch_cartoon": {
        "file": "char_jingle_pip_intro.wav",
        "duration_ms": 2000,
        "musicgen_prompt": "2 second cartoon character entrance. Quick high "
                           "xylophone run going up — biddly-biddly-BING. "
                           "Small, fast, cute. Something tiny scurrying in.",
    },
    "mysterious_witch": {
        "file": "char_jingle_shadow_intro.wav",
        "duration_ms": 2500,
        "musicgen_prompt": "2.5 second mysterious entrance. Low celesta "
                           "trill with a single deep gong at the end. "
                           "Spooky but playful — dark fairy tale, not "
                           "actually scary. Curtain slowly opening.",
    },
    "young_sweet": {
        "file": "char_jingle_sunny_intro.wav",
        "duration_ms": 2000,
        "musicgen_prompt": "2 second innocent entrance. Simple toy piano "
                           "playing 3 sweet notes, almost too cute, "
                           "followed by a tiny pause. The innocence is "
                           "slightly suspicious.",
    },
    "musical_original": {
        "file": "char_jingle_melody_intro.wav",
        "duration_ms": 2500,
        "musicgen_prompt": "2.5 second elegant entrance. Quick harp "
                           "arpeggio flourish going up. Fairy-tale-like, "
                           "whimsical, warm. The musical 'once upon a time.'",
    },
}
```

### Outro Jingles

Shorter callbacks — 1-1.5 second fragment of the voice's signature sound. Only the primary character's outro plays.

```python
CHARACTER_OUTRO_JINGLES = {
    "comedic_villain": {
        "file": "char_jingle_boomy_outro.wav",
        "duration_ms": 1500,
        "musicgen_prompt": "1.5 second comedy defeat. Single tuba note "
                           "deflating — wahhh. The villain lost again.",
    },
    "high_pitch_cartoon": {
        "file": "char_jingle_pip_outro.wav",
        "duration_ms": 1000,
        "musicgen_prompt": "1 second cheerful ending. Single high "
                           "xylophone 'bing!' — bright, quick, happy.",
    },
    "mysterious_witch": {
        "file": "char_jingle_shadow_outro.wav",
        "duration_ms": 1500,
        "musicgen_prompt": "1.5 second mysterious ending. Low celesta "
                           "single note fading into silence. Unresolved.",
    },
    "young_sweet": {
        "file": "char_jingle_sunny_outro.wav",
        "duration_ms": 1000,
        "musicgen_prompt": "1 second deadpan ending. One toy piano note, "
                           "completely flat. The musical 'cool.'",
    },
    "musical_original": {
        "file": "char_jingle_melody_outro.wav",
        "duration_ms": 1500,
        "musicgen_prompt": "1.5 second fairy tale closing. Harp glissando "
                           "descending gently. Warm, resolved, settling.",
    },
}
```

### Character Jingle Playback Rules

**Intro jingles:** All characters in the short get their jingle, played in order. Primary character first:

```
Solo:  [boomy intro jingle]
Duo:   [boomy intro jingle] → 150ms gap → [pip intro jingle]
Trio:  [shadow intro jingle] → 150ms gap → [boomy intro jingle] → 150ms gap → [pip intro jingle]
```

**Outro jingles:** Only the primary character's outro plays:

```
Solo:  [boomy outro jingle]
Duo:   [boomy outro jingle]     (primary only)
Trio:  [shadow outro jingle]    (primary only)
```

---

## Dynamic Host Intro and Outro

### Host Intro

One sentence generated per short. Tells the listener who's in tonight's episode and what they're attempting — with a hint it won't go well. Read by Melody (the permanent show host).

**Script tag:** `[HOST_INTRO: sentence]`

**LLM prompt addition:**

```
HOST INTRO AND OUTRO:
Write a one-sentence show introduction and a one-sentence closing 
callback. Both are read by a show host (Melody), NOT by any character 
in the story.

[HOST_INTRO: sentence] — Who's in this episode + what they're doing + 
a hint it goes wrong. Under 20 words. Makes the child smile before 
the story starts.

[HOST_OUTRO: sentence] — Winking callback to what happened. Under 
15 words. One final laugh.

Examples:

HOST_INTRO:
- "Tonight, Boomy has built the perfect trap for Pip. It is not perfect."
- "Tonight, Pip finds something in the park that is definitely a bench."
- "Tonight, Shadow tells you about a perfectly normal Tuesday. It was not normal."
- "Tonight, Sunny explains what happened at the pond. She is not impressed."
- "Tonight, Boomy tries to be a rock. Rocks don't usually have teeth."

HOST_OUTRO:
- "Boomy is still stuck in his own net. He says he meant to do that."
- "The bench has been seen swimming in the lake. It was a very fast bench."
- "Wednesday was, in fact, worse."
- "Pip would like everyone to know she is fine."
- "Boomy has learned nothing. See you next time."

RULES:
- The host is warm, slightly amused, not a character in the story.
- Never explain the joke. Hint at it (intro) or callback to it (outro).
- Refer to characters by their voice names: Boomy, Pip, Shadow, Sunny.
- Under 20 words for intro. Under 15 words for outro. Shorter is better.
```

### Host Outro

**Script tag:** `[HOST_OUTRO: sentence]`

Same voice (Melody), same params, generated alongside the script.

---

## Updated Script Format

```
[TITLE: The Great Trap Flop]
[HOST_INTRO: Tonight, Boomy has built the perfect trap for Pip. It is not perfect.]
[HOST_OUTRO: Boomy is still stuck in his own net. He says he meant to do that.]
[AGE: 2-5]
[VOICES: comedic_villain, high_pitch_cartoon]
[COMEDY_TYPE: villain_fails]
[COVER: A large dramatic animal tangled in a spaghetti net while a tiny creature watches]

[SETUP]
[BOOMY] [DELIVERY: confident] I have built the greatest trap this park has ever seen!
[BOOMY] [DELIVERY: bluster] When that tiny squeaky creature walks past, SNAP! Trapped!
[PIP] [DELIVERY: curious] What's this big sticky thing across the path?
[/SETUP]

[BEAT_1]
[PIP] [DELIVERY: tentative] I'm stepping on it... why is it wobbling?
[BOOMY] [DELIVERY: confident] Step further! It's perfectly safe!
[PIP] [DELIVERY: alarmed] I'm sinking into it! It's like pudding!
[BOOMY] [DELIVERY: caught off guard] Wait — why am I sinking too?! [STING: villain_fail]
[/BEAT_1]

[BEAT_2]
[BOOMY] [DELIVERY: bluster] Forget that trap! I built something BETTER — a trampoline!
[PIP] [DELIVERY: suspicious] Why does a trampoline have teeth marks on it?
[BOOMY] [DELIVERY: dismissive] Decorative teeth marks! Now jump!
[PIP] [DELIVERY: alarmed] We're bouncing higher and higher! I can see my house!
[BOOMY] [DELIVERY: desperate] I can see SPACE! HOW DO I STOP?! [STING: big_crash]
[/BEAT_2]

[BEAT_3]
[BOOMY] [DELIVERY: confident] Third time is the charm. A net. A beautiful, perfect net.
[PIP] [DELIVERY: matter of fact] Boomy, I can see through it. It's full of holes.
[BOOMY] [DELIVERY: defensive] Those are ventilation holes!
[PIP] [DELIVERY: calm gotcha] And why is it made of spaghetti?
[BOOMY] [DELIVERY: scrambling] It's... Italian engineering! Very advanced! [STING: deflation]
[/BEAT_3]

[BUTTON]
[PIP] [DELIVERY: devastating] Boomy, you trapped yourself in your own spaghetti net. [STING: villain_fail]
[BOOMY] [DELIVERY: stunned] [PUNCHLINE]I am... I am the mistake.[/PUNCHLINE]
[/BUTTON]
```

---

## Episode Assembly Pipeline

```python
def build_episode(narration_chunks, script, base_track):
    """Build a complete Before Bed episode with all layers."""
    episode = AudioStream()
    
    # === OPENING ===
    
    # 1. Show intro jingle
    episode.add_audio(load_audio(SHOW_INTRO_JINGLE["file"]))
    episode.add_silence(200)
    
    # 2. Host intro (dynamic — Melody reads the premise)
    host_intro_audio = generate_tts(
        script.host_intro,
        voice="musical_original",
        **HOST_VOICE_PARAMS,
    )
    episode.add_audio(host_intro_audio)
    episode.add_silence(300)
    
    # 3. Character intro jingles (primary first, then others)
    voices = script.voices  # ordered, primary first
    for voice in voices:
        jingle = CHARACTER_INTRO_JINGLES[voice]
        episode.add_audio(load_audio(jingle["file"]))
        episode.add_silence(150)
    
    episode.add_silence(300)  # breath before story starts
    
    # === STORY ===
    
    # 4. The story itself (narration + base track + stings, pre-mixed)
    story_audio = mix_funny_short(narration_chunks, script, base_track)
    episode.add_audio(story_audio)
    
    episode.add_silence(500)  # breath after story ends
    
    # === CLOSING ===
    
    # 5. Primary character outro jingle
    primary_voice = voices[0]
    outro_jingle = CHARACTER_OUTRO_JINGLES[primary_voice]
    episode.add_audio(load_audio(outro_jingle["file"]))
    episode.add_silence(200)
    
    # 6. Host outro (dynamic — Melody reads the callback)
    host_outro_audio = generate_tts(
        script.host_outro,
        voice="musical_original",
        **HOST_VOICE_PARAMS,
    )
    episode.add_audio(host_outro_audio)
    episode.add_silence(200)
    
    # 7. Show outro jingle
    episode.add_audio(load_audio(SHOW_OUTRO_JINGLE["file"]))
    
    return episode
```

---

## What the Child Hears — Full Episode Example

```
"The Great Trap Flop" — Boomy + Pip, ages 2-5

0.0s  *[glockenspiel ascending — biddly biddly boing!]*

3.7s  "Tonight, Boomy has built the perfect trap for Pip.
       It is not perfect."

8.0s  *[tuba: dun, dun, DUNNN]*
10.5s *[xylophone: biddly-biddly-BING!]*

12.7s *[sneaky base track fades in]*
13.0s "I have built the greatest trap this park has ever seen!"
      ...
      (60-90 seconds of story with stings)
      ...
      "I am... I am the mistake."
      *[tuba: wahhh]*

~78s  *[base track fades out]*

~79s  *[tuba deflating: wahhh]* (Boomy outro jingle)

~80s  "Boomy is still stuck in his own net.
       He says he meant to do that."

~84s  *[glockenspiel descending — settling, gentle]*

~87s  [silence]
```

**Night 2:**

```
0.0s  *[same glockenspiel jingle — child recognizes it!]*

3.7s  "Tonight, Shadow tells you about a perfectly normal Tuesday.
       It was not normal."

8.0s  *[celesta + gong — child knows: it's Shadow!]*

10.5s *[mysterious base track fades in]*
      ...story...
      *[celesta fading]* (Shadow outro jingle)
      
      "Wednesday was, in fact, worse."
      
      *[same glockenspiel descending]*
```

By night 3, the child recognizes the show jingle, anticipates the character jingles, and listens for the host intro to find out what tonight's episode is about. They're listening to a show, not playing a random audio file.

---

## LLM Prompt — Voices Section (Updated)

Replace the old character descriptions in the generation prompt:

```
VOICES AVAILABLE:
- BOOMY: Deep, dramatic, theatrical. Over-the-top self-importance.
  Cast as: villains, kings, big animals, bossy characters, anyone 
  with an inflated ego. The voice of spectacular failure.
  
- PIP: Squeaky, high-pitched, energetic. Reacts with alarm and panic.
  Cast as: small creatures, nervous characters, babies, anyone tiny 
  and excitable. The character things happen to.
  
- SHADOW: Dark, low, mysterious. Makes everything sound ominous.
  Cast as: narrators, mysterious figures, old wise characters, anyone 
  who knows more than they're saying. The dramatic commentator.
  
- SUNNY: Innocent-sounding but sarcastic. Deadpan, unbothered.
  Cast as: observers, bored teenagers, anyone calmly pointing out the 
  obvious. The voice of reason that nobody listens to.
  
- MELODY: Rhythmic, poetic, warm. The permanent show host.
  Cast as: show host (intro/outro), poets, fairy-tale narrators, 
  the straight man in ensemble scenes.

Tag every sentence with the voice name: [BOOMY], [PIP], [SHADOW], 
[SUNNY], or [MELODY].

These are VOICE TYPES, not fixed characters. Boomy might play a 
crocodile tonight and a penguin tomorrow. Pip might be a mouse or 
a cricket or a baby cloud. The voice stays the same; the character 
changes with each short.
```

---

## Audio File Inventory

### Static Files (Generated Once)

| Category | File | Duration |
|---|---|---|
| Show intro jingle | `beforebed_intro_jingle.wav` | 3.5s |
| Show outro jingle | `beforebed_outro_jingle.wav` | 3.5s |
| Boomy intro jingle | `char_jingle_boomy_intro.wav` | 2.5s |
| Boomy outro jingle | `char_jingle_boomy_outro.wav` | 1.5s |
| Pip intro jingle | `char_jingle_pip_intro.wav` | 2.0s |
| Pip outro jingle | `char_jingle_pip_outro.wav` | 1.0s |
| Shadow intro jingle | `char_jingle_shadow_intro.wav` | 2.5s |
| Shadow outro jingle | `char_jingle_shadow_outro.wav` | 1.5s |
| Sunny intro jingle | `char_jingle_sunny_intro.wav` | 2.0s |
| Sunny outro jingle | `char_jingle_sunny_outro.wav` | 1.0s |
| Melody intro jingle | `char_jingle_melody_intro.wav` | 2.5s |
| Melody outro jingle | `char_jingle_melody_outro.wav` | 1.5s |
| **Total static** | **12 files** | **~25s total** |

### Per-Short Dynamic Files

| File | Duration | Cost |
|---|---|---|
| Host intro audio (Melody TTS) | 3-5s | ~$0.002 |
| Host outro audio (Melody TTS) | 2-4s | ~$0.002 |
| **Total per short** | **5-9s extra** | **~$0.004** |

### Total Per-Short Cost Impact

```
Before episode structure: ~$0.025-0.035 per short
After episode structure:  ~$0.029-0.039 per short (+$0.004)
One-time jingle generation: ~$0.50 (12 files via MusicGen)
```

Negligible cost increase.

---

## Updated Funny Short JSON Schema

```json
{
    "id": "trap-flop-001",
    "title": "The Great Trap Flop",
    "age_group": "2-5",
    "comedy_type": "villain_fails",
    "format": "duo",
    "voice_combo": ["comedic_villain", "high_pitch_cartoon"],
    "primary_voice": "comedic_villain",
    "premise": "Boomy builds traps for Pip that all backfire spectacularly",
    "host_intro": "Tonight, Boomy has built the perfect trap for Pip. It is not perfect.",
    "host_outro": "Boomy is still stuck in his own net. He says he meant to do that.",
    "base_track_style": "sneaky",
    "base_track_file": "base_sneaky_02.wav",
    "cover_file": "trap-flop-001.webp",
    "audio_chunks_dir": "trap-flop-001/chunks/",
    "episode_file": "trap-flop-001_episode.mp3",
    "duration_seconds": 87,
    "created_at": "2026-03-26",
    "play_count": 0,
    "replay_count": 0
}
```

**Note:** `episode_file` is the final mixed file that includes all bookends. This is what the client plays. The `audio_chunks_dir` contains the raw per-sentence WAV files for re-mixing without re-generating TTS.

---

## Names Update — Global Search and Replace

All references across all specs and code must update:

| Old Reference | New Reference |
|---|---|
| `CROC` (in scripts) | `BOOMY` |
| `MOUSE` (in scripts) | `PIP` |
| `WITCH` (in scripts) | `SHADOW` |
| `SWEET` (in scripts) | `SUNNY` |
| `MUSICAL` (in scripts) | `MELODY` |
| `char_jingle_croc_*` | `char_jingle_boomy_*` |
| `char_jingle_mouse_*` | `char_jingle_pip_*` |
| `char_jingle_witch_*` | `char_jingle_shadow_*` |
| `char_jingle_sweet_*` | `char_jingle_sunny_*` |
| `char_jingle_musical_*` | `char_jingle_melody_*` |

**The underlying voice file references DO NOT change.** `comedic_villain`, `high_pitch_cartoon`, `mysterious_witch`, `young_sweet`, `musical_original` — these stay the same in `voice_service.py`. The new names are script-level aliases only.

---

## Implementation Checklist

### Jingle Generation (One-Time)
- [ ] Generate show intro jingle (glockenspiel ascending, 3.5s)
- [ ] Generate show outro jingle (same melody descending, 3.5s)
- [ ] Verify intro and outro use the same melody in opposite directions
- [ ] Generate 5 character intro jingles (2-2.5s each)
- [ ] Generate 5 character outro jingles (1-1.5s each)
- [ ] QA: play each jingle in isolation — is it instantly identifiable?
- [ ] QA: play intro jingle → character jingle → sample dialogue — does it flow?
- [ ] Store all 12 files in `audio/jingles/`

### Script Format Update
- [ ] Add `[HOST_INTRO:]` tag to script format and parser
- [ ] Add `[HOST_OUTRO:]` tag to script format and parser
- [ ] Update script validation: both tags required, both under 20 words
- [ ] Rename all voice tags in prompts: CROC→BOOMY, MOUSE→PIP, WITCH→SHADOW, SWEET→SUNNY, MUSICAL→MELODY
- [ ] Update `FUNNY_VOICE_MAP` with new tag names
- [ ] Update LLM prompt with new voice descriptions and casting ranges

### Audio Pipeline
- [ ] Add `generate_host_audio()` — generates intro and outro TTS with Melody voice
- [ ] Add `build_episode()` — assembles: show jingle → host intro → character jingles → story → character outro → host outro → show outro
- [ ] Save episode file as `{id}_episode.mp3` (the deliverable the client plays)
- [ ] Add `host_intro` and `host_outro` text fields to JSON schema
- [ ] Add `episode_file` path to JSON schema

### Existing Shorts
- [ ] Regenerate scripts for existing 6 shorts with new voice names
- [ ] Generate host intro and outro for each existing short
- [ ] Re-assemble all 6 as full episodes with bookends
- [ ] QA: listen to all 6 as episodes — does the show structure work?

### Testing
- [ ] Play 3 episodes back to back — does the show jingle become recognizable?
- [ ] Verify character jingles match their voice — tuba = Boomy, xylophone = Pip
- [ ] Verify host intro creates anticipation — child should smile before story starts
- [ ] Verify host outro gets one more laugh — callback should land
- [ ] Time check: full episodes should be under 110 seconds total
