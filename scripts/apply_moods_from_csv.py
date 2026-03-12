#!/usr/bin/env python3
"""Apply moods from the dry-run CSV log to content.json."""
import csv
import json
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CSV_PATH = BASE_DIR / "seed_output" / "mood_classification_log.csv"
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"

# Load mood mapping from CSV
mood_map = {}
with open(CSV_PATH) as f:
    for row in csv.DictReader(f):
        if row["mood"] != "error":
            mood_map[row["id"]] = row["mood"]

print(f"Loaded {len(mood_map)} mood classifications from CSV")

# Load content.json
with open(CONTENT_PATH) as f:
    content = json.load(f)

# Apply moods
applied = 0
missing = 0
for item in content:
    sid = item.get("id", "")
    if sid in mood_map:
        item["mood"] = mood_map[sid]
        applied += 1
    else:
        title = item.get("title", "?")[:40]
        print(f"  WARNING: No mood for {sid} ({title})")
        missing += 1

# Save
with open(CONTENT_PATH, "w") as f:
    json.dump(content, f, indent=2, ensure_ascii=False)

print(f"\nApplied {applied} moods, {missing} missing")
print(f"Saved to {CONTENT_PATH}")

# Verify
moods = Counter(item.get("mood") for item in content if item.get("mood"))
print(f"\nDistribution:")
for mood in ["calm", "curious", "wired", "sad", "anxious", "angry"]:
    c = moods.get(mood, 0)
    pct = (c / sum(moods.values()) * 100) if moods else 0
    print(f"  {mood:10s}  {c:3d}  ({pct:4.1f}%)")
