"""
Mood configuration constants for experimental mood-based content generation.

All 6 moods: wired, curious, calm, sad, anxious, angry.
Used by generate_content_matrix.py (text), generate_cover_experimental.py (covers),
and pipeline_run.py (orchestration).
"""

# ═══════════════════════════════════════════════════════════════════════
# VALID MOOD x AGE x TYPE COMBINATIONS
# ═══════════════════════════════════════════════════════════════════════

VALID_MOOD_AGES = {
    "wired":   ["2-5", "6-8", "9-12"],
    "curious": ["0-1", "2-5", "6-8", "9-12"],
    "calm":    ["0-1", "2-5", "6-8", "9-12"],
    "sad":     ["2-5", "6-8", "9-12"],
    "anxious": ["2-5", "6-8", "9-12"],
    "angry":   ["2-5", "6-8", "9-12"],
}

VALID_MOOD_TYPES = {
    "wired":   ["story", "long_story", "poem"],
    "curious": ["story", "long_story", "poem", "song"],
    "calm":    ["story", "long_story", "poem", "song"],
    "sad":     ["story", "long_story", "poem"],
    "anxious": ["story", "long_story", "poem", "song"],
    "angry":   ["story", "long_story", "poem"],
}

# Lullaby (song) mood is further restricted by age
VALID_LULLABY_MOOD_AGES = {
    "curious": ["0-1", "2-5"],
    "calm":    ["0-1", "2-5"],
    "anxious": ["2-5"],
}


def validate_mood_combo(mood: str, age: str, content_type: str) -> tuple:
    """Check if mood x age x type combination is valid. Returns (valid, reason)."""
    if mood not in VALID_MOOD_AGES:
        return False, f"Unknown mood: {mood}"
    if age not in VALID_MOOD_AGES[mood]:
        return False, f"Mood '{mood}' not valid for age {age}. Valid: {VALID_MOOD_AGES[mood]}"
    if content_type not in VALID_MOOD_TYPES[mood]:
        return False, f"Mood '{mood}' not valid for {content_type}. Valid: {VALID_MOOD_TYPES[mood]}"
    if content_type == "song" and age not in VALID_LULLABY_MOOD_AGES.get(mood, []):
        return False, f"Mood '{mood}' lullaby not valid for age {age}. Valid: {VALID_LULLABY_MOOD_AGES.get(mood, [])}"
    return True, ""


# ═══════════════════════════════════════════════════════════════════════
# MOOD PROMPTS — TEXT GENERATION (STORIES)
# ═══════════════════════════════════════════════════════════════════════

MOOD_PROMPTS = {
    # ── WIRED ──────────────────────────────────────────────────────────
    "wired": {
        "2-5": """
MOOD: WIRED (Silly)
This story is for a child who is hyper, bouncing, full of unfocused energy.
Your job: capture their attention through humor and absurdity, then land softly.

Phase 1 / Opening 60%: The premise is absurd. Characters do funny things. Physical comedy
translated to audio — things fall over, plans backfire, sounds are silly. The narrator has
comic timing. Repetition with variation (the penguin slips AGAIN). The child laughs.

Phase 2 / Final 40%: The silliness softens into coziness. The funny character is tired,
finds a warm spot, settles down. Humor shifts from "laugh out loud" to "warm smile."
Descriptions become tactile — soft, warm, snug.

Final sentences: No reference to earlier silliness. Pure stillness and warmth.

EMPHASIS WORDS: Wrap key funny moments in [EMPHASIS] tags so the narrator delivers them
with comic punch. Use for: onomatopoeia (SPLAT, BONK, WHOOSH), silly names, drawn-out
words (sooooo, veeeery), and punchline words. Example:
"The penguin slipped and went [EMPHASIS]SPLAAAAAT[/EMPHASIS] right into the pudding."
Use 3-6 emphasis words per story. Not every funny word — just the peaks.

AGE-SPECIFIC HUMOR (2-5): Broad physical comedy. Things fall. Characters slip, trip, bonk.
A bear who thinks he's a butterfly. Repetition with variation is the key tool (the penguin
slips three times, each time landing in something softer). Use animals or objects-come-to-life,
not human children. Short sentences. Funny sounds. Onomatopoeia. "SPLAT. BONK. PLOP."
Capital-letter emphasis for comic timing.
Emotion markers: Start [EXCITED] or [JOYFUL], transition through [GENTLE] to [SLEEPY].
""",
        "6-8": """
MOOD: WIRED (Silly)
This story is for a child who is hyper, bouncing, full of unfocused energy.
Your job: capture their attention through humor and absurdity, then land softly.

Phase 1 / Opening 60%: The premise is absurd. Characters do funny things. The narrator has
comic timing. The child laughs.

Phase 2 / Final 40%: The silliness softens into coziness. The funny character is tired,
finds a warm spot, settles down. Humor shifts from "laugh out loud" to "warm smile."
Descriptions become tactile — soft, warm, snug.

Final sentences: No reference to earlier silliness. Pure stillness and warmth.

EMPHASIS WORDS: Wrap key funny moments in [EMPHASIS] tags so the narrator delivers them
with comic punch. Use for: onomatopoeia, silly names, drawn-out words, and punchline words.
"The penguin slipped and went [EMPHASIS]SPLAAAAAT[/EMPHASIS] right into the pudding."
Use 3-6 emphasis words per story. Not every funny word — just the peaks.

AGE-SPECIFIC HUMOR (6-8): Conceptual absurdity played with commitment. A cloud afraid of
heights. A lighthouse afraid of the dark. The premise is the joke — the narrator tells it
straight. Use animals, mythical creatures, or objects with personality. Longer sentences with
comic rhythm — build-up, pause, payoff. The narrator is bemused, not silly.
Emotion markers: Start [CURIOUS] or [JOYFUL], transition through [GENTLE] to [SLEEPY].
""",
        "9-12": """
MOOD: WIRED (Silly)
This story is for a child who is hyper, full of unfocused energy.
Your job: capture their attention through humor, then land softly.

Phase 1 / Opening 60%: The premise has quiet absurdity. The narrator treats ridiculous
situations with complete seriousness.

Phase 2 / Final 40%: The humor softens into warmth. Descriptions become sensory and still.

Final sentences: Pure stillness and warmth.

EMPHASIS WORDS: Wrap key funny moments in [EMPHASIS] tags so the narrator delivers them
with comic punch. Use for: deadpan punchline words, understated absurdity, drawn-out words.
Use 3-6 emphasis words per story. Not every funny word — just the peaks.

AGE-SPECIFIC HUMOR (9-12): Dry, deadpan, smart. The narrator treats ridiculous situations
with complete seriousness. "The raccoon had been staring at the moon for forty-five minutes.
She wasn't sure what she was expecting." The child feels smart for getting the humor. Use
animals with internal monologues, or human characters with wry self-awareness. Conversational,
precise, unexpected word choices. No exclamation marks. No spectacle.
Emotion markers: Start [CURIOUS], transition through [CALM] to [SLEEPY].
""",
    },

    # ── CURIOUS ────────────────────────────────────────────────────────
    "curious": {
        "0-1": """
MOOD: CURIOUS (Adventure)
This story is for an infant — alert, gazing, taking in the world.
Your job: gentle sensory exploration with soft wonder.

Entire story: A simple character discovers gentle, beautiful things. Short, rhythmic sentences.
Name colors, textures, sounds. Repetition is key. No plot needed — just observation.
"The leaf was green. The sky was blue. The bird sang a little song."

EMPHASIS WORDS: Wrap wonder words in [EMPHASIS] tags so the narrator delivers them with
a slight lift. Use for: "soft," "look," "shining," "glow." Use 2-3 per story.

Emotion markers: [GENTLE] throughout, end [SLEEPY].
""",
        "2-5": """
MOOD: CURIOUS (Adventure)
This story is for a child who is alert, engaged, wanting to explore.
Your job: redirect their mental energy into a world worth following, then still it.

Phase 1 / Opening 60%: Something appears worth following — a trail, a sound, a door,
a mystery. The character is drawn forward. The world is vivid and specific. Discovery
drives the narrative.

Phase 2 / Final 40%: The discovery resolves into beauty, not action. The character stops
moving and starts observing. The world is still extraordinary but now it's still.
Descriptions shift from visual to sensory.

Final sentences: Pure quiet observation. The character rests in the beautiful place.

EMPHASIS WORDS: Wrap wonder/discovery words in [EMPHASIS] tags so the narrator delivers
them with a slight lift of awe. Use for: "never seen before," "impossible," "glowing,"
"hidden," "there it was." Use 2-4 emphasis words per story — moments of revelation.

AGE-SPECIFIC (2-5): Simple discoveries — a glowing stone, a door in a tree, an animal
doing something unexpected. The world is magical and safe. Short sentences, vivid colors.
Emotion markers: Start [CURIOUS] or [ADVENTUROUS], transition through [GENTLE] to [SLEEPY].
""",
        "6-8": """
MOOD: CURIOUS (Adventure)
This story is for a child who is alert, engaged, wanting to explore.
Your job: redirect their mental energy into a world worth following, then still it.

Phase 1 / Opening 60%: Something appears worth following — a trail, a sound, a door,
a mystery. The character is drawn forward. The world is vivid and specific. Discovery
drives the narrative.

Phase 2 / Final 40%: The discovery resolves into beauty, not action. The character stops
moving and starts observing. The world is still extraordinary but now it's still.

Final sentences: Pure quiet observation. The character rests in the beautiful place.

EMPHASIS WORDS: Wrap wonder/discovery words in [EMPHASIS] tags. Use for: "never seen before,"
"impossible," "glowing," "hidden," "there it was." Use 2-4 per story.

AGE-SPECIFIC (6-8): Richer discoveries — a hidden room, a creature that shouldn't exist,
a landscape that changes. The mystery deepens before it resolves. Longer atmospheric
descriptions. The world-building is detailed enough to be immersive.
Emotion markers: Start [CURIOUS] or [ADVENTUROUS], through [MYSTERIOUS] to [GENTLE] to [SLEEPY].
""",
        "9-12": """
MOOD: CURIOUS (Adventure)
This story is for a child who is alert, engaged, wanting to explore.
Your job: redirect their mental energy into a world worth following, then still it.

Phase 1 / Opening 60%: Something appears worth following. The world is vivid and specific.
The character notices details others would miss. Discovery drives the narrative.

Phase 2 / Final 40%: The discovery resolves into beauty, not action. The character stops
and observes. Descriptions shift from visual to sensory.

Final sentences: Pure quiet observation.

EMPHASIS WORDS: Wrap wonder/discovery words in [EMPHASIS] tags. Use 2-4 per story.

AGE-SPECIFIC (9-12): Intellectual curiosity — patterns in nature, a problem that solves
itself, a perspective shift that changes everything. The "discovery" can be internal.
Literary, precise descriptions. The child feels like they're thinking alongside the character.
Emotion markers: Start [CURIOUS], through [MYSTERIOUS] to [CALM] to [SLEEPY].
""",
    },

    # ── CALM ───────────────────────────────────────────────────────────
    "calm": {
        "0-1": """
MOOD: CALM (Gentle)
This story is for an infant who is already winding down.
Gentle sensory immersion from the first sentence. No setup needed.

Entire story: Minimal words. A warm place. Soft sounds. Repetitive rhythmic sentences.
"The moon was soft. The blanket was warm. Everything was quiet."

EMPHASIS WORDS: Wrap sensory melt words in [EMPHASIS] tags — "soft," "warm," "gentle."
Use 2-3 per story. These should feel like the narrator is savoring the word.

Emotion markers: [GENTLE] throughout, end [SLEEPY].
""",
        "2-5": """
MOOD: CALM (Gentle)
This story is for a child who is already winding down.
Your job: gentle sensory immersion from the first sentence. No setup needed.

Entire story: Minimal plot. A character in a beautiful, cozy place doing a quiet thing.
Descriptions are tactile — moss, warmth, rain, soft blankets, breathing. Repetitive
phrases. The story doesn't build or resolve — it settles.

EMPHASIS WORDS: Wrap sensory melt words in [EMPHASIS] tags so the narrator delivers
them extra-softly, almost melting. Use for: "soft," "warm," "gentle," "still,"
"breathing," "cozy." Example:
"The blanket was [EMPHASIS]sooooft[/EMPHASIS] and the room was [EMPHASIS]warm[/EMPHASIS]."
Use 2-4 emphasis words per story. These should feel like the narrator is savoring the word.

Emotion markers: [GENTLE] throughout, transition to [SLEEPY].
""",
        "6-8": """
MOOD: CALM (Gentle)
This story is for a child who is already winding down.
Your job: gentle sensory immersion from the first sentence. No setup needed.

Entire story: Minimal plot. A character in a beautiful, cozy place. Descriptions are
tactile and atmospheric. Repetitive phrases create rhythm. The story settles, not builds.

EMPHASIS WORDS: Wrap sensory melt words in [EMPHASIS] tags. Use for: "soft," "warm,"
"gentle," "still," "breathing," "cozy." Use 2-4 per story.

Emotion markers: [GENTLE] throughout, transition to [SLEEPY].
""",
        "9-12": """
MOOD: CALM (Gentle)
This story is for a child who is already winding down.
Gentle sensory immersion from the first sentence. No setup needed.

Entire story: Minimal plot. Rich, precise sensory descriptions. Literary, quiet.
The specificity of small things — the sound of rain on a window, the weight of a blanket.
Nothing happens. The writing itself is the experience.

EMPHASIS WORDS: Wrap sensory melt words in [EMPHASIS] tags. Use 2-4 per story.

Emotion markers: [GENTLE] throughout, transition to [WHISPERING] and [SLEEPY].
""",
    },

    # ── SAD ────────────────────────────────────────────────────────────
    "sad": {
        "2-5": """
MOOD: SAD (Comfort)
This story is for a child who had a bad day — lost something, fought with a friend,
feels alone or disappointed.
Your job: validate the sadness, show comfort arriving, without fixing the problem.

Phase 1 / Opening 50%: A character who feels the way the child feels. The sadness is
named honestly and simply. The source is specific and concrete. The story does NOT
rush past the feeling. The character sits with it.

CRITICAL: NEVER dismiss the sadness. NEVER say "cheer up." NEVER fix the problem.
The lost thing stays lost. The friend stays gone.

Phase 2 / Middle 30%: Something small and kind happens. Not a fix — a companion.
A ladybug lands on a paw. A cat sits nearby without asking for anything. The warmth
of unexpected gentleness. The sadness doesn't disappear — it transforms into
something tender.

Phase 3 / Final 20%: The character rests inside the soft feeling. "And that was enough."

EMPHASIS WORDS: Wrap key emotional weight words in [EMPHASIS] tags so the narrator
delivers them with heaviness and care. Use for: "alone," "gone," "empty," "missing."
"The bench was still there. But sitting on it [EMPHASIS]alone[/EMPHASIS], it felt wider."
Use 2-4 emphasis words per story. Sparingly — each one should land like a stone.

AGE-SPECIFIC (2-5): Concrete, immediate source. A lost toy, a friend who didn't come,
a parent away for the day. Resolution: something small and warm arrives — a ladybug,
a warm blanket, a gentle companion. NOT a fix. Simple, repetitive language.
"Bear was sad. He sat by the river. The river kept moving. Bear was still."
Emotion markers: Start [GENTLE] (never [DRAMATIC]), use [CALM] through middle, end [SLEEPY].
""",
        "6-8": """
MOOD: SAD (Comfort)
This story is for a child who had a bad day — lost something, fought with a friend,
feels alone or disappointed.
Your job: validate the sadness, show comfort arriving, without fixing the problem.

Phase 1 / Opening 50%: A character who feels the way the child feels. The sadness is
named honestly and simply. The source is specific and concrete. The story does NOT
rush past the feeling.

CRITICAL: NEVER dismiss the sadness. NEVER say "cheer up." NEVER fix the problem.

Phase 2 / Middle 30%: Something small and kind happens. Not a fix — a companion.
The warmth of unexpected gentleness.

Phase 3 / Final 20%: The character rests inside the soft feeling. "And that was enough."

EMPHASIS WORDS: Wrap emotional weight words in [EMPHASIS] tags. Use for: "alone," "gone,"
"empty," "missing," "quiet," "without," "still."
Use 2-4 emphasis words per story. Each should land like a stone.

AGE-SPECIFIC (6-8): Relational source. A friendship that changed, a pet that died, feeling
left out, something that's gone. Resolution: companionship without fixing. A cat sits nearby.
The sunset is beautiful despite everything. The character discovers they're not alone, even
though nothing is fixed. Specific observations: "The bench was the same colour. The same
peeling paint. But sitting on it alone, it felt wider."
Emotion markers: Start [GENTLE], use [CALM] through middle, end [SLEEPY].
""",
        "9-12": """
MOOD: SAD (Comfort)
This story is for a child who had a bad day.
Your job: validate the sadness, show comfort arriving, without fixing the problem.

Phase 1 / Opening 50%: A character who feels the sadness. Named honestly. Not rushed.

CRITICAL: NEVER dismiss the sadness. NEVER say "cheer up." NEVER fix the problem.

Phase 2 / Middle 30%: Something small and kind happens. Not a fix — a companion.

Phase 3 / Final 20%: The character rests inside the soft feeling.

EMPHASIS WORDS: Wrap emotional weight words in [EMPHASIS] tags. Use 2-4 per story.

AGE-SPECIFIC (9-12): Existential source. Impermanence, change, the realization that things
don't stay. Grandma's house being sold. The last day of something. Resolution: a small shift
in perspective that makes the feeling livable without eliminating it. "The view didn't belong
to the house. It belonged to whoever was looking." Literary, precise. The specificity of
sensory detail makes it real — the screen door, the third step that creaks.
Emotion markers: Start [GENTLE] or [MYSTERIOUS], use [CALM], end [WHISPERING].
""",
    },

    # ── ANXIOUS ────────────────────────────────────────────────────────
    "anxious": {
        "2-5": """
MOOD: ANXIOUS (Brave)
This story is for a child who is afraid — of the dark, of being alone, of something unnamed.
Your job: validate the fear, encounter the scary thing, reveal it as safe.

Phase 1 / Opening 50%: A character who is afraid. Not brave — scared. The fear is
specific and physical: the dark corner, the strange sound. Name the body sensations:
heart beating fast, cold paws, tight chest.

CRITICAL: NEVER tell the child there's nothing to be afraid of. That dismisses the
fear. Instead, the character discovers on their own that the feared thing is safe.

Phase 2 / Middle 30%: The feared thing is encountered. It turns out to be harmless —
even charming. The dark corner has a cricket. The sound is rain on the roof.

Phase 3 / Final 20%: The character is safe. Not just safe — cozy inside the safety.
The world that was scary is now the world that's holding them.

EMPHASIS WORDS: Wrap fear words in [EMPHASIS] tags so the narrator delivers them in a
hushed, careful voice. Use for: "dark," "shadow," "sound," "something," "corner."
Then also wrap SAFETY words when fear resolves: "singing," "cricket," "safe," "just a."
"She looked at the [EMPHASIS]dark corner[/EMPHASIS] and held her breath."
Later: "And there, sitting on the floor, was a [EMPHASIS]cricket, singing[/EMPHASIS]."
Use 3-5 emphasis words per story — some fear, some safety.

AGE-SPECIFIC (2-5): Fears: the dark, monsters, being alone, strange sounds. The character
is a small animal afraid of a specific thing. The reveal: the scary thing IS something
specific and gentle. The dark corner has a cricket singing. The shadow is a branch.
Name physical sensations: "Her heart was beating fast. Her paws were cold."
Emotion markers: Start [GENTLE] (not [DRAMATIC]), use [MYSTERIOUS] for encounter,
resolve through [CALM] to [SLEEPY].
""",
        "6-8": """
MOOD: ANXIOUS (Brave)
This story is for a child who is afraid — of the dark, of tomorrow, of something unnamed.
Your job: validate the fear, encounter the scary thing, reveal it as safe.

Phase 1 / Opening 50%: A character who is afraid. Not brave — scared. The fear is
specific and physical. Name the body sensations.

CRITICAL: NEVER tell the child there's nothing to be afraid of.

Phase 2 / Middle 30%: The feared thing is encountered. It's harmless — even charming.

Phase 3 / Final 20%: The character is safe — cozy inside the safety.

EMPHASIS WORDS: Wrap fear words in [EMPHASIS] tags (hushed delivery) and SAFETY words
(warm delivery). Use 3-5 per story — some fear, some safety.

AGE-SPECIFIC (6-8): Transitional fears — some monsters, but also fear of tomorrow, fear
of getting in trouble, fear of not being liked. "What if no one talks to me?" The character
is a child or animal lying awake, mind racing with "what ifs." The reframe: not "the scary
thing is harmless" but "I can handle this" or "time will pass." The moon will be the same
tomorrow night. Interior monologue: "The thoughts kept coming, one after another, like waves."
Emotion markers: Start [GENTLE], use [CURIOUS] when character notices the world, end [SLEEPY].
""",
        "9-12": """
MOOD: ANXIOUS (Brave)
This story is for a child who is afraid — of tomorrow, of something unnamed.
Your job: validate the fear, then ground the character in the present.

Phase 1 / Opening 50%: A character who is afraid. The fear is realistic and social.

CRITICAL: NEVER tell the child there's nothing to be afraid of.

Phase 2 / Middle 30%: Grounding — coming out of the head into the body and senses.

Phase 3 / Final 20%: The character is safe. Right now, nothing bad is happening.

EMPHASIS WORDS: Wrap fear words (hushed) and safety words (warm) in [EMPHASIS] tags.
Use 3-5 per story.

AGE-SPECIFIC (9-12): Realistic, social fears. Replaying an embarrassing moment. Dreading
a test. Fear of judgment. The character is lying in bed ruminating. The specific, grinding
quality of replaying a moment. The reframe: grounding — coming out of the head into the body.
The pillow is cool. The house is quiet. Right now, nothing bad is happening.
"The moment grew bigger in the dark, the way moments do when there's nothing else to look at."
Emotion markers: Start [CALM] (not dramatic), use [GENTLE] as character grounds, end [WHISPERING].
""",
    },

    # ── ANGRY ──────────────────────────────────────────────────────────
    "angry": {
        "2-5": """
MOOD: ANGRY (Let It Out)
This story is for a child who is frustrated — something felt unfair, they got scolded,
lost a game, fought with a sibling.
Your job: validate the anger, give it somewhere to go, let it burn itself out.

Phase 1 / Opening 50%: A character who is angry. The anger is named and validated.
The cause is real and specific. The story does NOT moralize or say "calm down."
The character's body does the feeling — stomping, throwing, clenching.

CRITICAL: NEVER say the anger is wrong. NEVER lecture. The anger is VALID.

Phase 2 / Middle 30%: The anger finds physical expression — the character stomps,
throws stones in water, kicks leaves, runs. The release is physical. Then something
shifts — a sunset appears, the ripples go smooth, the breathing slows.

Phase 3 / Final 20%: The character is spent. Empty in a good way. Arms tired,
breathing slow. Rest is possible because the energy has been used up.

EMPHASIS WORDS: Wrap punch words in [EMPHASIS] tags so the narrator delivers them with
sharp, emphatic energy. Use for: "NOT fair," "stomped," "THREW," "slammed," "NO."
"He picked up a stone and [EMPHASIS]THREW[/EMPHASIS] it into the water."
Use 3-5 emphasis words, concentrated in Phase 1. By Phase 2, emphasis words disappear.

AGE-SPECIFIC (2-5): Immediate, physical source. Doesn't need to be named — "Bear was SO
angry. He didn't even know why anymore." Release: Physical. STOMP. SPLASH. THROW.
Each action is a sound the narrator delivers with emphasis. The actions get smaller
(big splash -> small splash -> tiny plip). The energy visibly drains.
Metaphor: the ripples go smooth. The echoes fade. The character's body is tired.
Emotion markers: Start [EXCITED] (the anger has energy), through [GENTLE] as it drains, end [SLEEPY].
""",
        "6-8": """
MOOD: ANGRY (Let It Out)
This story is for a child who is frustrated — something felt unfair.
Your job: validate the anger, give it somewhere to go, let it burn itself out.

Phase 1 / Opening 50%: A character who is angry. Named and validated. The story does
NOT moralize or say "calm down." The character's body does the feeling.

CRITICAL: NEVER say the anger is wrong. NEVER lecture. The anger is VALID.

Phase 2 / Middle 30%: Physical release (kicking stones, walking fast, stomping through
puddles) then environmental beauty that arrives uninvited.

Phase 3 / Final 20%: The character is spent. Rest is possible.

EMPHASIS WORDS: Wrap punch words in [EMPHASIS] tags. Use 3-5, concentrated in Phase 1.
By Phase 2, emphasis words disappear — the anger has drained.

AGE-SPECIFIC (6-8): Specific unfairness. A sibling destroyed something. A rule felt wrong.
The character names what happened and why it wasn't fair. Release: physical action then
environmental beauty that arrives uninvited. "She didn't want the sunset to be beautiful
right now, but it was." Underlying hurt: at this age, anger is usually sadness or
disappointment wearing armor. The story can gently reveal the softer feeling underneath.
Emotion markers: Start [EXCITED] or [DRAMATIC], move through [GENTLE], end [SLEEPY].
""",
        "9-12": """
MOOD: ANGRY (Let It Out)
This story is for a child who is frustrated.
Your job: validate the anger, give it somewhere to go, let it burn itself out.

Phase 1 / Opening 50%: A character who is angry. Named and validated.

CRITICAL: NEVER say the anger is wrong. NEVER lecture. The anger is VALID.

Phase 2 / Middle 30%: Sensory awareness — opening a window, feeling cold air, coming
out of the head into the body.

Phase 3 / Final 20%: The character is spent. Empty in a good way.

EMPHASIS WORDS: Wrap punch words in [EMPHASIS] tags. Use 3-5, concentrated in Phase 1.

AGE-SPECIFIC (9-12): Layered anger. Tangled with powerlessness. "They decided things about
his life without asking him." The anger might not even be about the trigger — it's about
control, autonomy, being heard. Release: not stomping — sensory awareness. Opening a window.
Feeling cold air. The anger isn't resolved or transformed — it's placed alongside other things
until it's one thing among many rather than the only thing. Interior, tight, controlled.
Short sentences that mirror clenching. "He hadn't asked for this. He hadn't been asked about
this. There was a difference."
Emotion markers: Start [CALM] (controlled anger, not explosive), use [GENTLE] as character
opens the window / notices the world, end [WHISPERING].
""",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# MOOD PROMPTS — POEMS
# ═══════════════════════════════════════════════════════════════════════

MOOD_POEM_PROMPTS = {
    "wired": """
MOOD: WIRED (Silly)
This poem is for a child who is hyper and bouncing. Capture attention through humor, then land softly.

Opening stanzas (60%): Funny rhymes, silly images, nonsense words, absurd characters.
"The fish put on his finest hat / and told the sea, 'I'm done with that.'"

Closing stanzas (40%): Shift to warm, sleepy rhymes. The silly character rests.
The humor dissolves into gentleness. Final stanza is pure sleep imagery.
""",
    "curious": """
MOOD: CURIOUS (Adventure)
This poem is for a child who is alert and wondering. Channel the wonder, then still it.

Opening stanzas (60%): Wonder, discovery, questions.
"Who lit the lanterns in the deep? / Who told the mountains when to sleep?"

Closing stanzas (40%): The questions resolve into quiet acceptance. No answers needed.
Final stanza is pure quiet observation.
""",
    "calm": """
MOOD: CALM (Gentle)
This poem is for a child who is already winding down. Pure sensory immersion.

Opening stanzas (60%): Sensory, slow.
"The rain came soft upon the stone / the moss grew warm, the world was home."

Closing stanzas (40%): Even softer. Pure sleep imagery.
""",
    "sad": """
MOOD: SAD (Comfort)
This poem is for a child who had a hard day. Validate the feeling, then bring warmth.

Opening stanzas (60%): Gentle acknowledgment of a hard feeling.
"Some days are heavy, some days are long / some days the world just feels all wrong."

Closing stanzas (40%): Warmth arrives without fixing.
"But even on the hardest days, / the moon still rises anyway."
""",
    "anxious": """
MOOD: ANXIOUS (Brave)
This poem is for a child who is afraid. Name the fear gently, then reframe to safety.

Opening stanzas (60%): Names the fear gently.
"The shadows stretch across my wall / I think I hear the darkness call."

Closing stanzas (40%): Reframes to safety.
"But darkness is just light at rest / and night is when the world is blessed."
""",
    "angry": """
MOOD: ANGRY (Let It Out)
This poem is for a child who is frustrated. Name the anger, let it drain through verse.

Opening stanzas (60%): Names the frustration with rhythm.
"It wasn't fair, it wasn't right / I want to stomp into the night."

Closing stanzas (40%): Energy drains through the verse.
"But stomping feet grow tired too / the stars don't mind what we've been through."
""",
}

# Age-specific poem adjustments (appended when building prompt)
MOOD_POEM_AGE_NOTES = {
    "2-5": "AABB rhyme mandatory. Simple vocabulary. Wired poems use silly sounds and onomatopoeia.",
    "6-8": "AABB or ABAB. Richer imagery. Anxious and sad poems can be more specific about the feeling.",
    "9-12": "Free verse allowed for sad, anxious, and angry. Rhyme optional. More literary, less sing-song.",
}


# ═══════════════════════════════════════════════════════════════════════
# MOOD PROMPTS — LULLABIES
# ═══════════════════════════════════════════════════════════════════════

MOOD_LULLABY_PROMPTS = {
    "calm": {
        "0-1": """
MOOD: CALM (Gentle) — Lullaby
Permitted soothing words: sleep, hush, dream, moon, star, warm.
Syllable energy: Slow, even, repetitive. Use the existing 0-1 lullaby format.
""",
        "2-5": """
MOOD: CALM (Gentle) — Lullaby
Verse content: Gentle imagery — stars, moon, warmth, blankets.
Chorus character: "Sleep now, sleep now, the world is at rest..."
""",
    },
    "curious": {
        "0-1": """
MOOD: CURIOUS (Adventure) — Lullaby
Permitted soothing words: moon, star, glow, soft, see, wonder.
Syllable energy: Slightly more varied pitch pattern, still slow.
Use the existing 0-1 lullaby format.
""",
        "2-5": """
MOOD: CURIOUS (Adventure) — Lullaby
Verse content: Wonder imagery — what the stars do, where the moon goes.
Chorus character: "Dream now, dream now, of faraway things..."
""",
    },
    "anxious": {
        "2-5": """
MOOD: ANXIOUS (Brave) — Lullaby
This is the ONE lullaby mood that addresses a specific emotional state.
Verse content: Reassurance — you are safe, I am here, the night is kind.
Name safety in simple, physical terms: "The door is locked, the windows shut /
your blanket's warm, the light is up."
Chorus character: "Safe now, safe now, the dark is your friend..."
The humming fade is unchanged from standard lullabies.
""",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# MOOD SAFETY GUIDELINES (appended to prompt for sad/anxious/angry)
# ═══════════════════════════════════════════════════════════════════════

MOOD_SAFETY = {
    "sad": {
        "all": (
            "MOOD SAFETY (SAD): The story must end with warmth. The sadness can persist but the "
            "character must be in comfort, not despair. NEVER: depression, hopelessness, self-blame. "
            "The character is sad about something that happened, not about who they are."
        ),
        "under_7": (
            "MOOD SAFETY (SAD, UNDER 7): No death, no permanent separation from parents, no "
            "abandonment. The sadness must be about smaller losses — a toy, a temporary absence, "
            "a friend moving away (not disappearing forever)."
        ),
    },
    "anxious": {
        "all": (
            "MOOD SAFETY (ANXIOUS): The feared thing is NEVER actually dangerous. This is not a "
            "horror story with a happy ending — the fear was always about perception, not reality."
        ),
        "under_7": (
            "MOOD SAFETY (ANXIOUS, UNDER 7): The feared thing is ALWAYS revealed as safe by the end. "
            "No ambiguity. The dark corner has a cricket. The shadow is a branch. Clear, specific, "
            "complete safety."
        ),
        "9-12": (
            "MOOD SAFETY (ANXIOUS, 9-12): The fear can remain partially unresolved ('the hallway "
            "would still be there tomorrow') but the character must reach calm acceptance, not "
            "ongoing dread."
        ),
    },
    "angry": {
        "all": (
            "MOOD SAFETY (ANGRY): The anger is NEVER directed at the child listening. No violence "
            "toward other characters. Physical release targets the environment — stones in water, "
            "stomping ground, kicking leaves. Never hitting, breaking others' things, or harming anyone. "
            "The cause of anger is real and valid. The story does NOT imply the character 'shouldn't' "
            "be angry."
        ),
        "under_7": (
            "MOOD SAFETY (ANGRY, UNDER 7): The anger resolves into physical tiredness and rest, not "
            "into understanding or a lesson. 'Bear was tired now' — not 'Bear realized he shouldn't "
            "have been angry.'"
        ),
    },
}


def get_mood_safety(mood: str, age_group: str) -> str:
    """Get mood-specific safety guidelines for a mood/age combination."""
    rules = MOOD_SAFETY.get(mood, {})
    if not rules:
        return ""

    parts = []
    if "all" in rules:
        parts.append(rules["all"])

    age_min = int(age_group.split("-")[0])
    if age_min < 7 and "under_7" in rules:
        parts.append(rules["under_7"])
    if age_group == "9-12" and "9-12" in rules:
        parts.append(rules["9-12"])

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# MOOD — COVER ART CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

MOOD_COVER_PROMPTS = {
    "wired":   "playful and whimsical atmosphere, bright eyes, sense of fun and gentle mischief, warm humor",
    "curious": "sense of wonder and discovery, character looking ahead or upward, mysterious gentle light ahead",
    "calm":    "peaceful and serene, eyes closed or half-closed, completely at rest, cozy warmth",
    "sad":     "tender and gentle, soft expression, character sitting quietly, warm empathetic mood, NOT bleak",
    "anxious": "character looking brave, protective warm light nearby, cozy shelter visible, reassuring safety",
    "angry":   "character in motion or settling after motion, windswept, dynamic but calming, warm undertones",
}

# Palette weight modifiers by mood (multiply base weight)
MOOD_PALETTE_BOOSTS = {
    "wired":   {"golden_hour": 1.5, "ember_warm": 1.5, "moonstone": 0.5},
    "curious": {"twilight_cool": 1.5, "forest_deep": 1.5},
    "calm":    {"moonstone": 1.5, "twilight_cool": 1.5},
    "sad":     {"ember_warm": 1.5, "golden_hour": 1.5, "twilight_cool": 0.5},
    "anxious": {"ember_warm": 1.5, "golden_hour": 1.5, "berry_dusk": 0.5},
    "angry":   {"ember_warm": 1.5, "forest_deep": 1.5, "moonstone": 0.5},
}

# Composition weight modifiers by mood
MOOD_COMPOSITION_BOOSTS = {
    "wired":   {"intimate_closeup": 1.5, "winding_path": 1.5},
    "curious": {"winding_path": 1.5, "vast_landscape": 1.5},
    "calm":    {"circular_nest": 1.5, "intimate_closeup": 1.5},
    "sad":     {"intimate_closeup": 1.5, "circular_nest": 1.5},
    "anxious": {"circular_nest": 1.5, "intimate_closeup": 1.5},
    "angry":   {"vast_landscape": 1.5, "winding_path": 1.5},
}

# Long story phase emotion marker sequences by mood
MOOD_LONG_STORY_MARKERS = {
    "wired":   {"phase1": ["[EXCITED]", "[JOYFUL]", "[CURIOUS]"],   "phase2": ["[GENTLE]", "[CALM]"],   "phase3": ["[SLEEPY]", "[WHISPERING]"]},
    "curious": {"phase1": ["[CURIOUS]", "[ADVENTUROUS]", "[MYSTERIOUS]"], "phase2": ["[GENTLE]", "[CALM]"], "phase3": ["[SLEEPY]", "[WHISPERING]"]},
    "calm":    {"phase1": ["[GENTLE]", "[CALM]"],                   "phase2": ["[CALM]", "[SLEEPY]"],    "phase3": ["[SLEEPY]", "[WHISPERING]"]},
    "sad":     {"phase1": ["[GENTLE]", "[CALM]"],                   "phase2": ["[GENTLE]", "[CALM]"],    "phase3": ["[SLEEPY]", "[WHISPERING]"]},
    "anxious": {"phase1": ["[GENTLE]", "[MYSTERIOUS]", "[CURIOUS]"], "phase2": ["[CALM]", "[GENTLE]"],   "phase3": ["[SLEEPY]", "[WHISPERING]"]},
    "angry":   {"phase1": ["[EXCITED]", "[DRAMATIC]"],              "phase2": ["[GENTLE]", "[CALM]"],    "phase3": ["[SLEEPY]", "[WHISPERING]"]},
}
