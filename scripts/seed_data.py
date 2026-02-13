"""
Seed script to populate Firestore with sample content for development.
Run: python scripts/seed_data.py
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta
import random

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ── Sample Stories ──────────────────────────────────────────────────

SAMPLE_STORIES = [
    {
        "title": "The Sleepy Cloud",
        "description": "A fluffy cloud drifts across the moonlit sky, collecting dreams for sleepy children.",
        "text": (
            "High above the rooftops, a fluffy little cloud named Nimbus floated gently "
            "through the night sky. Nimbus had the most important job in all the world — "
            "collecting sweet dreams from the stars and sprinkling them over sleeping children.\n\n"
            "Tonight, the stars were especially sparkly. Nimbus reached out with soft, "
            "cottony arms and caught a dream about flying horses, another about a garden "
            "made entirely of candy, and one more about a friendly dragon who loved to "
            "share warm hugs.\n\n"
            "As Nimbus drifted over your house, it gently shook its fluffy body, and the "
            "dreams floated down like tiny snowflakes. They landed softly on your pillow, "
            "waiting for you to close your eyes.\n\n"
            "\"Sweet dreams, little one,\" whispered Nimbus, as it continued its journey "
            "across the peaceful night sky, leaving a trail of starlight behind."
        ),
        "theme": "dreamy",
        "categories": ["Fantasy", "Lullabies", "Magical"],
        "target_age": 4,
        "morals": ["Even the smallest things can have the most important jobs"],
    },
    {
        "title": "The Brave Little Firefly",
        "description": "A tiny firefly discovers its light can guide lost animals home through the dark forest.",
        "text": (
            "In the heart of Whispering Woods lived a tiny firefly named Flicker. Unlike "
            "the other fireflies who shone brilliant gold, Flicker's light was small and "
            "soft — more like a gentle candle than a blazing star.\n\n"
            "\"My light is too small to matter,\" sighed Flicker one evening, watching the "
            "other fireflies dance and sparkle above the meadow.\n\n"
            "But that very night, a baby rabbit named Clover got lost in the darkest part "
            "of the forest. The tall trees blocked out all the moonlight, and Clover "
            "couldn't find the path home.\n\n"
            "\"Hello? Can anyone help me?\" whimpered Clover.\n\n"
            "Flicker heard the tiny voice and zipped through the branches. \"Follow my light!\" "
            "said Flicker. And though the glow was small, it was just enough for Clover "
            "to see each step of the way.\n\n"
            "Together, they walked through the forest, Flicker lighting the path one step "
            "at a time, until they reached Clover's burrow where Mama Rabbit was waiting.\n\n"
            "\"Thank you, little light,\" said Clover with a sleepy yawn. \"You're the "
            "bravest firefly in all the woods.\"\n\n"
            "And from that night on, Flicker never felt small again. Because even the "
            "tiniest light can guide someone home."
        ),
        "theme": "adventure",
        "categories": ["Animals", "Adventure", "Friendship"],
        "target_age": 5,
        "morals": ["Even small acts of kindness matter", "Never underestimate yourself"],
    },
    {
        "title": "The Moon's Lullaby",
        "description": "The Moon sings a gentle song to help all the animals in the meadow fall asleep.",
        "text": (
            "When the sun tucked itself behind the hills and the sky turned a deep, velvety "
            "blue, the Moon rose slowly, casting a soft silver glow over Willow Meadow.\n\n"
            "Every night, the Moon had a special duty. It would sing a lullaby so gentle, "
            "so sweet, that every creature in the meadow would drift off to sleep.\n\n"
            "\"Hush now, little fox,\" the Moon sang softly, and the fox curled up in its "
            "cozy den.\n\n"
            "\"Rest now, little owl,\" the Moon hummed, and the owl tucked its head under "
            "its wing.\n\n"
            "\"Sleep now, little deer,\" the Moon whispered, and the deer lay down in the "
            "soft grass beside its mother.\n\n"
            "One by one, every animal closed its eyes. The crickets played a gentle "
            "accompaniment. The wind rustled the leaves like a soft blanket being pulled up.\n\n"
            "And then the Moon looked down at you and sang the sweetest note of all: "
            "\"Goodnight, my little dreamer. The stars will watch over you until morning comes.\"\n\n"
            "And with that, the whole world fell into a peaceful, happy sleep."
        ),
        "theme": "fairy_tale",
        "categories": ["Lullabies", "Animals", "Nature"],
        "target_age": 3,
        "morals": ["The world is peaceful and safe at night"],
    },
    {
        "title": "Captain Stardust and the Comet Race",
        "description": "An adventurous space explorer races comets across galaxies to deliver a birthday wish.",
        "text": (
            "Captain Stardust adjusted her sparkly helmet and gripped the controls of "
            "her starship, the Silver Dreamer. Tonight's mission was the most important "
            "one yet — she had to deliver a birthday wish to Planet Cakealot before "
            "midnight!\n\n"
            "\"Ready for launch!\" she called to her co-pilot, a fluffy space cat named "
            "Nebula, who meowed approvingly from the passenger seat.\n\n"
            "The Silver Dreamer zoomed past the rings of Saturn, weaved through an "
            "asteroid field like a cosmic obstacle course, and even raced alongside a "
            "brilliant blue comet named Flash.\n\n"
            "\"Bet you can't keep up!\" Flash teased, streaking across the sky.\n\n"
            "\"Watch me!\" laughed Captain Stardust, pushing the engines to full speed. "
            "Stars blurred into streaks of light as they raced neck and neck through "
            "the Milky Way.\n\n"
            "They arrived at Planet Cakealot just in time! The entire planet was shaped "
            "like a magnificent birthday cake, with candle-shaped towers that flickered "
            "with rainbow flames.\n\n"
            "Captain Stardust delivered the wish — a glowing golden star that floated "
            "gently down to the birthday child below.\n\n"
            "\"Mission complete,\" she smiled, as Nebula purred contentedly. \"Now, let's "
            "head home. Even space explorers need their sleep.\"\n\n"
            "And as the Silver Dreamer sailed home through the quiet cosmos, the stars "
            "themselves seemed to dim their lights, whispering goodnight."
        ),
        "theme": "space",
        "categories": ["Space", "Adventure", "Funny"],
        "target_age": 7,
        "morals": ["Determination helps you reach your goals"],
    },
    {
        "title": "The Garden of Whispers",
        "description": "A magical garden where flowers tell stories to anyone who listens carefully.",
        "text": (
            "Behind the old stone wall at the edge of Grandmother's house, there was a "
            "garden that nobody talked about. Not because it was a secret, exactly — but "
            "because it was the kind of place you had to discover for yourself.\n\n"
            "Maya found it on a warm summer evening. She pushed open the ivy-covered gate "
            "and stepped into a world that shimmered with soft golden light. The flowers "
            "here were unlike any she'd ever seen — roses that glowed like lanterns, lilies "
            "that hummed gentle melodies, and sunflowers that slowly turned to face her "
            "as she walked past.\n\n"
            "\"Listen closely,\" whispered a tall purple orchid.\n\n"
            "Maya knelt down and put her ear near a patch of tiny blue forget-me-nots. "
            "And to her amazement, she heard a story — a tale about a girl who befriended "
            "a cloud and traveled across the sky.\n\n"
            "Each flower held a different story. The daisies told tales of brave mice. "
            "The tulips shared legends of ancient kindness. The lavender whispered poems "
            "about starlit nights.\n\n"
            "Maya visited the garden every evening after that, listening to one new story "
            "each night. And every story ended the same way — with a gentle reminder:\n\n"
            "\"Close your eyes now, dear listener. Tomorrow, there will be another story "
            "waiting just for you.\"\n\n"
            "And Maya would smile, walk home through the soft twilight, and drift off "
            "to sleep, dreaming of gardens and stories and magic."
        ),
        "theme": "fantasy",
        "categories": ["Magical", "Fantasy", "Nature"],
        "target_age": 8,
        "morals": ["The best stories are found when you slow down and listen"],
    },
]

# ── Sample Poems ──────────────────────────────────────────────────

SAMPLE_POEMS = [
    {
        "title": "Twinkle Dream",
        "description": "A gentle bedtime poem about stars watching over sleeping children.",
        "text": (
            "The stars above are blinking bright,\n"
            "They guard your dreams throughout the night.\n"
            "The moon is smiling, round and white,\n"
            "And wraps the world in silver light.\n\n"
            "So close your eyes, my little one,\n"
            "The day is done, the night's begun.\n"
            "Tomorrow brings a brand new sun,\n"
            "But now it's time for sleep and fun.\n\n"
            "In dreamland meadows, soft and green,\n"
            "The prettiest sights you've ever seen.\n"
            "With butterflies of gold and blue,\n"
            "All dancing there, just for you."
        ),
        "theme": "dreamy",
        "categories": ["Lullabies", "Magical"],
        "target_age": 3,
        "style": "rhyming",
    },
    {
        "title": "The Owl's Goodnight",
        "description": "A wise owl says goodnight to every creature in the forest.",
        "text": (
            "Hoo-hoo, says the owl from the old oak tree,\n"
            "Goodnight to the fish in the deep blue sea.\n"
            "Goodnight to the rabbits in burrows so snug,\n"
            "Goodnight to the ladybug under the rug.\n\n"
            "Hoo-hoo, says the owl to the fox in its den,\n"
            "To the duck and the drake and the little brown hen.\n"
            "Goodnight to the squirrel with acorns to keep,\n"
            "Hoo-hoo, little darling — it's time now to sleep."
        ),
        "theme": "animals",
        "categories": ["Animals", "Lullabies"],
        "target_age": 2,
        "style": "nursery",
    },
]

# ── Sample Songs ──────────────────────────────────────────────────

SAMPLE_SONGS = [
    {
        "title": "Sailing to Dreamland",
        "description": "A gentle lullaby about sailing on a magical boat to the land of dreams.",
        "text": (
            "[Verse 1]\n"
            "We're sailing on a silver boat,\n"
            "Across the moonlit sea.\n"
            "The stars are singing lullabies,\n"
            "For you and me.\n\n"
            "[Chorus]\n"
            "Dreamland, dreamland, just close your eyes,\n"
            "Sail away under purple skies.\n"
            "Dreamland, dreamland, the night is kind,\n"
            "Leave all your worries far behind.\n\n"
            "[Verse 2]\n"
            "The waves are made of cotton clouds,\n"
            "The wind is warm and sweet.\n"
            "And every star that's shining bright,\n"
            "Will guide our tiny fleet.\n\n"
            "[Chorus]\n"
            "Dreamland, dreamland, just close your eyes,\n"
            "Sail away under purple skies.\n"
            "Dreamland, dreamland, the night is kind,\n"
            "Leave all your worries far behind."
        ),
        "theme": "dreamy",
        "categories": ["Lullabies", "Magical"],
        "target_age": 4,
        "music_genre": "lullaby",
        "instruments": ["piano", "harp", "soft strings"],
    },
]


def build_content_doc(item: dict, content_type: str) -> dict:
    """Build a Firestore-ready content document."""
    content_id = str(uuid.uuid4())
    age = item["target_age"]
    word_count = len(item["text"].split())
    duration = int(word_count / 2.5)  # ~150 wpm spoken = ~2.5 words/sec

    doc = {
        "id": content_id,
        "type": content_type,
        "title": item["title"],
        "description": item["description"],
        "text": item["text"],
        "target_age": age,
        "age_min": max(0, age - 2),
        "age_max": min(14, age + 2),
        "duration_seconds": duration,
        "author_id": "system",
        "created_at": (datetime.utcnow() - timedelta(days=random.randint(1, 30))).isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "audio_url": None,
        "album_art_url": None,
        "view_count": random.randint(50, 500),
        "like_count": random.randint(10, 200),
        "save_count": random.randint(5, 100),
        "categories": item.get("categories", []),
        "theme": item.get("theme", "dreamy"),
        "is_generated": False,
        "generation_quality": "excellent",
        "voice_id": "luna_gentle",
        "music_type": "ambient",
        "word_count": word_count,
    }

    # Add type-specific fields
    if content_type == "story":
        doc["morals"] = item.get("morals", [])
        doc["has_qa"] = False
        doc["has_games"] = False
    elif content_type == "poem":
        doc["style"] = item.get("style", "rhyming")
    elif content_type == "song":
        doc["music_genre"] = item.get("music_genre", "lullaby")
        doc["instruments"] = item.get("instruments", [])

    return doc


def generate_seed_data() -> list[dict]:
    """Generate all seed content documents."""
    documents = []

    for story in SAMPLE_STORIES:
        documents.append(build_content_doc(story, "story"))

    for poem in SAMPLE_POEMS:
        documents.append(build_content_doc(poem, "poem"))

    for song in SAMPLE_SONGS:
        documents.append(build_content_doc(song, "song"))

    return documents


# ── Subscription Tier Definitions ─────────────────────────────────

SUBSCRIPTION_TIERS = [
    {
        "tier": "free",
        "name": "Stargazer",
        "daily_limit": 1,
        "max_favorites": 10,
        "max_saves": 5,
        "features": [
            "1 new story per day",
            "Basic voice selection",
            "Save up to 5 stories",
            "Standard audio quality",
        ],
        "price_usd": 0.0,
        "description": "Perfect for trying DreamWeaver. Get one magical story every night!",
    },
    {
        "tier": "premium",
        "name": "Moonbeam",
        "daily_limit": 5,
        "max_favorites": 50,
        "max_saves": 25,
        "features": [
            "5 new stories per day",
            "All voices unlocked",
            "Background music selection",
            "Save up to 25 stories",
            "Custom story themes",
            "High quality audio",
        ],
        "price_usd": 4.99,
        "description": "Unlock more dreams with 5 stories daily and premium features!",
    },
    {
        "tier": "unlimited",
        "name": "Dream Weaver",
        "daily_limit": 999,
        "max_favorites": 9999,
        "max_saves": 9999,
        "features": [
            "Unlimited stories",
            "All voices unlocked",
            "All background music",
            "Unlimited saves & favorites",
            "Custom story prompts",
            "Interactive Q&A mode",
            "Mini-games during stories",
            "Priority generation",
            "Offline downloads",
            "Premium audio quality",
        ],
        "price_usd": 9.99,
        "description": "The ultimate DreamWeaver experience. Unlimited magic, every night!",
    },
]

# ── Voice Definitions ─────────────────────────────────────────────

VOICES = [
    {
        "id": "luna_gentle",
        "name": "Luna",
        "gender": "female",
        "description": "A warm, gentle voice perfect for soothing bedtime stories.",
        "emotions": ["neutral", "sleepy", "gentle", "happy"],
        "sample_url": None,
        "provider": "chatterbox",
        "age_group": "all",
        "is_active": True,
    },
    {
        "id": "atlas_warm",
        "name": "Atlas",
        "gender": "male",
        "description": "A deep, warm voice great for adventure stories and legends.",
        "emotions": ["neutral", "excited", "mysterious", "calm"],
        "sample_url": None,
        "provider": "chatterbox",
        "age_group": "all",
        "is_active": True,
    },
    {
        "id": "aria_playful",
        "name": "Aria",
        "gender": "female",
        "description": "A bright, playful voice ideal for funny stories and songs.",
        "emotions": ["neutral", "happy", "playful", "surprised"],
        "sample_url": None,
        "provider": "chatterbox",
        "age_group": "young",
        "is_active": True,
    },
    {
        "id": "cosmo_adventure",
        "name": "Cosmo",
        "gender": "male",
        "description": "An energetic voice perfect for space adventures and exciting tales.",
        "emotions": ["neutral", "excited", "brave", "mysterious"],
        "sample_url": None,
        "provider": "chatterbox",
        "age_group": "older",
        "is_active": True,
    },
    {
        "id": "whisper_soothing",
        "name": "Whisper",
        "gender": "neutral",
        "description": "An ethereal, soothing voice that makes every story feel like a dream.",
        "emotions": ["neutral", "sleepy", "peaceful", "gentle"],
        "sample_url": None,
        "provider": "chatterbox",
        "age_group": "all",
        "is_active": True,
    },
    {
        "id": "melody_musical",
        "name": "Melody",
        "gender": "female",
        "description": "A melodic voice with a natural singing quality, perfect for songs and poems.",
        "emotions": ["neutral", "happy", "lyrical", "dreamy"],
        "sample_url": None,
        "provider": "chatterbox",
        "age_group": "all",
        "is_active": True,
    },
]


async def seed_firestore():
    """
    Seed Firestore with sample data.
    Requires Firebase Admin SDK initialized with credentials.
    """
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        # Initialize Firebase if not already done
        if not firebase_admin._apps:
            cred_path = os.environ.get(
                "FIREBASE_CREDENTIALS_PATH", "./firebase-credentials.json"
            )
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
            else:
                print(f"Firebase credentials not found at {cred_path}")
                print("Falling back to JSON output mode...")
                await seed_to_json()
                return

        db = firestore.client()

        # Seed content
        content_docs = generate_seed_data()
        print(f"Seeding {len(content_docs)} content documents...")
        for doc in content_docs:
            db.collection("content").document(doc["id"]).set(doc)
            print(f"  + {doc['type'].upper()}: {doc['title']}")

        # Seed subscription tiers
        print(f"\nSeeding {len(SUBSCRIPTION_TIERS)} subscription tiers...")
        for tier in SUBSCRIPTION_TIERS:
            db.collection("subscriptions").document(tier["tier"]).set(tier)
            print(f"  + {tier['name']} (${tier['price_usd']}/mo)")

        # Seed voices
        print(f"\nSeeding {len(VOICES)} voices...")
        for voice in VOICES:
            db.collection("voices").document(voice["id"]).set(voice)
            print(f"  + {voice['name']} ({voice['gender']})")

        print("\nSeed complete!")

    except ImportError:
        print("firebase-admin not installed. Falling back to JSON output...")
        await seed_to_json()


async def seed_to_json():
    """Fallback: output seed data as JSON files for manual import."""
    import json

    output_dir = os.path.join(os.path.dirname(__file__), "..", "seed_output")
    os.makedirs(output_dir, exist_ok=True)

    content_docs = generate_seed_data()

    with open(os.path.join(output_dir, "content.json"), "w") as f:
        json.dump(content_docs, f, indent=2, default=str)
    print(f"Wrote {len(content_docs)} content docs to seed_output/content.json")

    with open(os.path.join(output_dir, "subscriptions.json"), "w") as f:
        json.dump(SUBSCRIPTION_TIERS, f, indent=2)
    print(f"Wrote {len(SUBSCRIPTION_TIERS)} tiers to seed_output/subscriptions.json")

    with open(os.path.join(output_dir, "voices.json"), "w") as f:
        json.dump(VOICES, f, indent=2)
    print(f"Wrote {len(VOICES)} voices to seed_output/voices.json")

    print(f"\nJSON seed files saved to: {output_dir}/")
    print("Import these into Firestore using the Firebase Console or CLI.")


if __name__ == "__main__":
    print("=" * 50)
    print("DreamWeaver Seed Data")
    print("=" * 50)
    print()
    asyncio.run(seed_firestore())
