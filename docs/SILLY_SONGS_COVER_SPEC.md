# Dream Valley — Silly Songs Cover Generation
## FLUX Schnell + Comedy Animation (Same Pipeline as Funny Shorts)

---

## Overview

Every silly song gets an animated cover. Same pipeline as funny short covers: FLUX Schnell generates the base image, then `generate_funny_cover.py` applies comedy-energy SMIL SVG animation on top. NOT the sleep cover pipeline (which enforces drowsiness guardrails).

---

## Cover Style — Songs vs Shorts

Song covers should feel slightly different from funny short covers while staying in the same visual family:

| | Funny Short Covers | Silly Song Covers |
|---|---|---|
| **Composition** | Character in the punchline moment | Character performing / singing / in the song's world |
| **Energy** | Frozen comic moment (mid-action) | Musical energy (movement, rhythm, performance) |
| **Visual cues** | Slapstick scene | Musical notes, instruments, stage-like framing |
| **Aspect ratio** | 1:1 square | 1:1 square (same card format) |
| **Style** | Bold cartoon, bright colors | Bold cartoon, bright colors + subtle musical elements |
| **Animation** | Wobble, bounce, blink | Bounce, pulse, sway (rhythmic, not chaotic) |

The child should be able to tell from the cover whether they're looking at a funny short or a silly song — the musical visual cues (notes, instruments, performance poses) signal "this one has music."

---

## FLUX Prompt Template

```python
SILLY_SONG_COVER_PROMPT = """
Children's book illustration, bold cartoon style, bright saturated colors,
simple background, exaggerated funny expressions, playful and energetic,
square format, thick outlines, expressive eyes, slightly exaggerated 
proportions, Pixar-meets-picture-book aesthetic.

Musical scene: {scene_description}

Include subtle musical elements: small floating music notes, or the 
character holding/near an instrument, or a stage-like spotlight feel.
NOT a realistic concert — cartoon musical energy.

DO NOT make it dreamy, muted, watercolor, or soft. 
This is comedy + music, not bedtime.
"""
```

---

## Scene Descriptions for the 6 Test Songs

The LLM generates a `[COVER:]` tag with each song's lyrics. For the test set, here are the scene descriptions:

### Song 1: "Not a Rock" (Ages 2-5)

```python
cover_prompt = SILLY_SONG_COVER_PROMPT.format(
    scene_description="A big green crocodile lying completely flat on the ground "
                      "trying to look like a grey rock, with a tiny confused bird "
                      "sitting on his head. The crocodile's eyes are wide open, "
                      "trying not to blink. Small music notes floating around. "
                      "Pond setting, simple green and blue background."
)
```

### Song 2: "The Sneezy Bear" (Ages 2-5)

```python
cover_prompt = SILLY_SONG_COVER_PROMPT.format(
    scene_description="A big brown bear mid-sneeze with his mouth wide open and "
                      "eyes squeezed shut. Trees bending sideways from the sneeze "
                      "wind. Leaves and a small rabbit flying through the air. "
                      "The bear looks apologetic. Small music notes scattered "
                      "among the flying leaves. Forest setting."
)
```

### Song 3: "Perfectly Normal" (Ages 6-8)

```python
cover_prompt = SILLY_SONG_COVER_PROMPT.format(
    scene_description="A cat standing at a kitchen counter flipping pancakes with "
                      "a spatula, wearing a tiny chef hat. Behind the cat, through "
                      "the window, the house is floating six feet off the ground. "
                      "The cat looks completely unbothered. A small guitar leans "
                      "against the counter. Warm kitchen colors."
)
```

### Song 4: "The Plan" (Ages 6-8)

```python
cover_prompt = SILLY_SONG_COVER_PROMPT.format(
    scene_description="A dramatic-looking animal (like a fox or raccoon) standing "
                      "on a rock, holding up a rolled-out blueprint of a ridiculous "
                      "trap. The trap in the background is already falling apart. "
                      "The animal looks triumphantly confident despite the chaos. "
                      "Spotlight effect, theatrical stage energy. Music notes and "
                      "a tuba visible in the corner."
)
```

### Song 5: "I'm Fine" (Ages 9-12)

```python
cover_prompt = SILLY_SONG_COVER_PROMPT.format(
    scene_description="A young hedgehog sitting at a desk looking directly at the "
                      "viewer with a completely calm, slightly deadpan expression. "
                      "Behind them, everything is chaos: the desk is floating, the "
                      "lamp is upside down, a sandwich is waving, the window shows "
                      "a purple sky. The hedgehog holds a small ukulele and looks "
                      "totally unbothered. Pastel and bright colors."
)
```

### Song 6: "The Explanation" (Ages 9-12)

```python
cover_prompt = SILLY_SONG_COVER_PROMPT.format(
    scene_description="A dark kitchen at night, fridge door slightly open with an "
                      "ominous green glow coming from inside. A small pair of eyes "
                      "peek out from behind a jar. On the counter, a trail of "
                      "crumbs leads away from the fridge. A guitar leans against "
                      "the fridge. Mysterious but clearly funny, not scary. "
                      "Dark blues and greens with warm highlights."
)
```

---

## Cover Specs

| Property | Value |
|---|---|
| Model | FLUX Schnell (Together AI) |
| Size | 1024×1024 (square) |
| Output format | WebP |
| Output filename | `{song_id}_cover.webp` |
| Animation | Comedy SMIL SVG via `generate_funny_cover.py` |
| Cost per cover | ~$0.01 |

---

## Animation — Comedy Energy, Not Sleep Energy

Use `generate_funny_cover.py` (the funny shorts animation script), NOT the sleep story cover animation. The sleep system enforces drowsiness guardrails (warm/muted colors only, max opacity 0.80, min animation duration 3s, breathing pacer, no upward motion). Song covers need the opposite.

### Animation Presets for Songs

Songs should feel rhythmic — not chaotic like shorts, but pulsing and alive. The animation should feel like the cover is moving to a beat.

```python
SONG_ANIMATION_PRESETS = {
    "bounce_rhythmic": {
        # Gentle rhythmic bounce — the whole scene pulses with the beat
        "type": "translateY",
        "values": "0; -8; 0",
        "duration": "1.5s",       # matches ~80 BPM feel
        "repeatCount": "indefinite",
    },
    "sway": {
        # Side to side sway — like swaying to music
        "type": "rotate",
        "values": "-2; 2; -2",
        "duration": "2s",
        "repeatCount": "indefinite",
    },
    "pulse": {
        # Subtle scale pulse — breathing but faster, musical
        "type": "scale",
        "values": "1.0; 1.03; 1.0",
        "duration": "1.2s",
        "repeatCount": "indefinite",
    },
    "notes_float": {
        # Music notes floating upward (if notes are in the image)
        "type": "translateY",
        "values": "0; -30",
        "duration": "3s",
        "repeatCount": "indefinite",
        "opacity_values": "1; 0",
    },
}
```

### Song-Specific Animation Selection

| Song | Primary Animation | Why |
|---|---|---|
| Not a Rock | `bounce_rhythmic` + `sway` | The croc is trying to stay still — the bounce is ironic |
| The Sneezy Bear | `pulse` (building) | Pulses that get bigger match the escalating sneezes |
| Perfectly Normal | `sway` | Gentle sway — everything's normal, the floating house just sways |
| The Plan | `bounce_rhythmic` | Theatrical energy — the villain marches to a beat |
| I'm Fine | `pulse` (very subtle) | Deadpan — barely moving, like Sunny's delivery |
| The Explanation | `sway` (slow) | Mysterious — the fridge light sways ominously |

### Implementation

`generate_funny_cover.py` already handles comedy-energy animation. For songs, pass an `animation_style="song"` parameter that selects the rhythmic presets above instead of the slapstick presets (wobble, jiggle, blink) used for funny shorts:

```python
def generate_song_cover(song_data):
    """Generate cover for a silly song."""
    # 1. Generate FLUX image
    cover_prompt = SILLY_SONG_COVER_PROMPT.format(
        scene_description=song_data["cover_description"]
    )
    base_image = generate_flux_image(cover_prompt, size="1024x1024")
    
    # 2. Apply comedy animation (song style — rhythmic, not slapstick)
    animated_svg = apply_funny_animation(
        base_image,
        animation_style="song",
        preset=song_data.get("animation_preset", "bounce_rhythmic"),
    )
    
    # 3. Save
    save_webp(base_image, f"{song_data['id']}_cover.webp")
    save_svg(animated_svg, f"{song_data['id']}_cover.svg")
    
    return {
        "cover_file": f"{song_data['id']}_cover.webp",
        "cover_svg": f"{song_data['id']}_cover.svg",
    }
```

---

## Script Tag for Songs

Add a `[COVER:]` tag to the song generation prompt so the LLM generates a scene description alongside the lyrics:

```
[COVER: description of the funniest or most iconic visual moment from the song]
```

The LLM prompt addition:

```
COVER DESCRIPTION:
Write a one-sentence scene description for the song's cover art.
Tag it as [COVER: description].

The cover should show the song's ICONIC MOMENT — the single image 
that captures what the song is about. Include a subtle musical 
element (music notes, instrument, performance pose).

Examples:
- [COVER: A crocodile lying flat trying to look like a rock while a bird sits on his head, small music notes floating around]
- [COVER: A bear mid-sneeze with trees bending sideways and leaves flying, music notes scattered among the leaves]
- [COVER: A hedgehog with a ukulele looking calm at a desk while everything behind them floats and glows]
```

---

## Song JSON Schema (Cover Fields)

```json
{
    "id": "not-a-rock",
    "title": "Not a Rock",
    "age_group": "2-5",
    "cover_description": "A crocodile lying flat trying to look like a grey rock...",
    "cover_file": "not-a-rock_cover.webp",
    "cover_svg": "not-a-rock_cover.svg",
    "animation_preset": "bounce_rhythmic",
    "audio_file": "not-a-rock.mp3",
    "duration_seconds": 75,
    "lyrics": "...",
    "style_prompt": "...",
    "created_at": "2026-03-28"
}
```

---

## Before Bed Tab — Song Cards with Covers

```
🌙 Before Bed

😂 Funny Shorts
┌──────────────┐ ┌──────────────┐
│ ┌──────────┐ │ │ ┌──────────┐ │
│ │ [animated │ │ │ │ [animated │ │
│ │  cover]   │ │ │ │  cover]   │ │
│ └──────────┘ │ │ └──────────┘ │
│ 🐊🐭         │ │ 🐊           │
│ The Great    │ │ The Croc Who │
│ Trap Flop    │ │ Was a Rock   │
│       [▶]    │ │       [▶]    │
└──────────────┘ └──────────────┘

🎵 Silly Songs
┌──────────────┐ ┌──────────────┐
│ ┌──────────┐ │ │ ┌──────────┐ │
│ │ [animated │ │ │ │ [animated │ │
│ │  cover]   │ │ │ │  cover]   │ │
│ └──────────┘ │ │ └──────────┘ │
│ 🎵           │ │ 🎵           │
│ Not a Rock   │ │ The Sneezy   │
│              │ │ Bear         │
│       [▶]    │ │       [▶]    │
└──────────────┘ └──────────────┘
```

Song cards use 🎵 emoji instead of character emojis. The animated cover with its rhythmic pulse/sway visually distinguishes songs from shorts (which have slapstick wobble/jiggle animation).

---

## Generation Pipeline for Test Set

```bash
# Step 1: Generate 6 covers
for song in not_a_rock sneezy_bear perfectly_normal the_plan im_fine the_explanation; do
  python3 scripts/generate_song_cover.py \
    --prompt-file "prompts/${song}_cover.txt" \
    --animation-preset "$(cat prompts/${song}_animation.txt)" \
    --output "output/songs/${song}_cover"
done

# Step 2: Generate 6 songs via ACE-Step (from the test plan spec)
for song in not_a_rock sneezy_bear perfectly_normal the_plan im_fine the_explanation; do
  python3 scripts/generate_song.py \
    --style-prompt "prompts/${song}_style.txt" \
    --lyrics "prompts/${song}_lyrics.txt" \
    --duration 80 \
    --variants 2 \
    --output "output/songs/${song}"
done

# Step 3: Pick best variant per song, pair with cover
# (manual step — listen to both variants, pick the better one)
```

### Cost for Test Set

```
6 FLUX Schnell covers:  ~$0.06
6 ACE-Step songs (×2):  ~$0.18
Total test set:         ~$0.24
```

---

## Implementation Checklist (Test Only)

- [ ] Write 6 cover prompt files (scene descriptions above)
- [ ] Write 6 animation preset assignments
- [ ] Generate 6 FLUX covers at 1024×1024
- [ ] Apply comedy animation via `generate_funny_cover.py` with song presets
- [ ] Verify animation feels rhythmic (pulse/sway), not slapstick (wobble/jiggle)
- [ ] Generate 12 song variants via ACE-Step (2 per song)
- [ ] Listen and pick best variant per song
- [ ] Pair covers with songs
- [ ] Review: do the covers match the songs? Does the animation style feel "musical"?
- [ ] Test: show a cover to a child — can they tell it's a song vs a funny short?
