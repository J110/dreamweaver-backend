# Hindi Content Publishing Guidelines
## Dream Valley — Language Toggle, Content Filtering, Old Content Cleanup

---

## 1. Core Principle: Hindi Behind a Setting, Not Visible by Default

Hindi content ships to production but is **invisible to all users** until they
explicitly switch their language preference to Hindi in their profile. No user
will accidentally see Hindi content. English remains the default for every new
and existing user.

This gives you:
- Real production testing (content served from the same pipeline, same CDN, same player)
- No risk to existing English users
- Ability to share a "switch to Hindi" instruction with testers privately
- Clean rollback — flip the default back and Hindi disappears from the feed

---

## 2. Profile Page: Language Setting

### Add a Language Preference to Profile

Add a single dropdown or toggle in the parent's profile/settings page:

```
┌──────────────────────────────────────┐
│  Profile Settings                    │
│                                      │
│  Child's Name: ___________           │
│  Age Group:    [2-5 ▼]               │
│                                      │
│  ── Content Language ──────────────  │
│                                      │
│  ┌──────────┐  ┌──────────┐         │
│  │● English │  │  हिन्दी   │         │
│  └──────────┘  └──────────┘         │
│                                      │
│  Hindi stories, lullabies, and       │
│  poems in conversational Hindi —     │
│  the way Indian parents talk to      │
│  their children at bedtime.          │
│                                      │
└──────────────────────────────────────┘
```

### Implementation

```typescript
// Profile state
interface UserProfile {
  childName: string;
  ageGroup: string;
  language: "en" | "hi";  // NEW — default "en"
  // ... existing fields
}
```

**Storage:** localStorage for now (no auth system needed). Key: `dreamvalley_language`.
If no key exists → default to `"en"`.

**No onboarding change.** Language is not asked during first use.
Users discover it in settings when they want it.

---

## 3. Content Filtering: How Language Affects the Feed

### Rule: When language is set, show ONLY that language

When `language === "en"` → show only `lang: "en"` content.
When `language === "hi"` → show only `lang: "hi"` content.

**No mixing.** A Hindi user sees a fully Hindi feed. An English user sees a
fully English feed. This is cleaner than interleaving and avoids confusion
for the child.

### All Sections Remain the Same

The app's tab structure and section headers do not change:

| Section | English | Hindi |
|---------|---------|-------|
| Short Stories | Same grid, English stories | Same grid, Hindi stories |
| Lullabies | Same grid, English lullabies | Same grid, Hindi lullabies |
| Funny Shorts | Same grid, English shorts | Same grid, Hindi shorts |
| Silly Songs | Same grid, English songs | Same grid, Hindi songs |
| Long Stories | Same grid, English stories | Same grid, Hindi stories |
| Musical Poems | Same grid, English poems | Same grid, Hindi poems |

If a section has zero Hindi content (e.g., Funny Shorts not yet generated in
Hindi), that section should show an empty state:

```
┌──────────────────────────────────────┐
│  Funny Shorts                        │
│                                      │
│  🎭 Coming soon in Hindi!            │
│  जल्द ही हिंदी में आ रहा है!           │
│                                      │
└──────────────────────────────────────┘
```

This is better than hiding the section entirely — it tells the parent that
the section exists and Hindi content is on the way.

### Filter Implementation

The content grid currently loads from JSON files or an API endpoint.
Add the language filter at the data layer:

```typescript
// Content loading — add language filter
function loadContent(type: string, language: string): Content[] {
  const allContent = loadAllContent(type);  // existing function
  return allContent.filter(item => item.lang === language);
}

// Every content fetch passes the user's language preference
const stories = loadContent("story", userProfile.language);
const lullabies = loadContent("song", userProfile.language);
```

### Filter Pills: Language-Aware

Existing filter pills (mood, language level, story type) work the same
way within each language. When Hindi is selected:

- Mood pills show Hindi labels: शांत, ऊर्जावान, जिज्ञासु, उदास, चिंतित, गुस्सा
- Language level pills: same English labels (Keep Simple / Medium / Challenge)
  — these describe vocabulary complexity, which applies to Hindi too
- Story type pills (if visible): कथा, लोक कथा, नीति कथा, etc.

### Story Card Display

Hindi story cards show:
- Hindi title in Devanagari (from `title` field)
- Hindi description (from `description` field)
- Same cover art (covers are language-independent)
- Age + mood label in Hindi (from `HINDI_MOOD_LABELS`)

```
┌──────────────┐  ┌──────────────┐
│   🐰 🌙      │  │   🌳 ⭐      │
│              │  │              │
│ चाँद का सफ़र  │  │ जंगल की कहानी │
│ 2-5 • शांत   │  │ 6-8 • जिज्ञासु│
└──────────────┘  └──────────────┘
```

---

## 4. Player: Language-Aware Behavior

### Story Player

When playing Hindi content:
- Title displayed in Devanagari
- "Now Playing" text can stay English (or switch to "अभी चल रहा है")
- Cover art: same pipeline, no change
- Audio: plays the Hindi TTS audio file (same player, different file)
- Background music beds: same as English (language-independent)

### No Translation Toggle

Do NOT add a "translate" button or show English alongside Hindi.
The parent chose Hindi — respect the choice. If they want English,
they switch back in settings. Keep the UI clean.

---

## 5. Old Hindi Content: Remove from Backend

### The Problem

Existing Hindi content in the backend was generated with शुद्ध (Shudh/Pure)
Hindi — literary, formal, Sanskrit-heavy vocabulary that kids can't understand.
This content must be removed before any user sees the Hindi feed.

### Identification

Old Hindi content can be identified by:
- `lang: "hi"` in the content metadata
- Generated before the conversational Hindi spec was implemented
- Fails the `conversational_score` check (score < 0.70)
- Contains literary Hindi markers from `LITERARY_HINDI_REJECT` list

### Removal Steps

```bash
# 1. Identify all existing Hindi content
# Look in all content directories and JSON indices

# Stories
grep -l '"lang": "hi"' seed_output/stories/*.json
grep -l '"lang": "hi"' public/audio/stories/*.json

# Lullabies
grep -l '"lang": "hi"' seed_output/lullabies/*.json

# All content types
find seed_output/ public/audio/ -name "*.json" -exec grep -l '"lang": "hi"' {} \;
```

```bash
# 2. Archive (don't delete — move to a dated archive folder)
mkdir -p /opt/audio-store/_archive_old_hindi/$(date +%Y%m%d)

# Move old Hindi audio files
# Move old Hindi JSON metadata
# Move old Hindi covers
```

```bash
# 3. Remove from indices
# Edit lullabies.json, stories index, etc.
# Remove all entries where lang === "hi"

# Python one-liner for each index file:
python3 -c "
import json, sys
with open(sys.argv[1]) as f: data = json.load(f)
filtered = [item for item in data if item.get('lang') != 'hi']
with open(sys.argv[1], 'w') as f: json.dump(filtered, f, indent=2)
print(f'Removed {len(data) - len(filtered)} Hindi items')
" seed_output/lullabies/lullabies.json
```

```bash
# 4. Verify removal
# No Hindi content should appear in any index
grep '"lang": "hi"' seed_output/lullabies/lullabies.json
# Should return nothing
```

```bash
# 5. Clear CDN/public cache if applicable
# If content is served via nginx or a CDN, purge Hindi audio URLs
```

### What NOT to Remove

- Hindi voice reference files (WAV files for TTS voices) — these are inputs, not content
- Hindi generation scripts and guidelines — these are code, not content
- Hindi test outputs in local development directories — only remove from production paths

### Verification Checklist

After cleanup:

- [ ] Zero Hindi entries in `lullabies.json`
- [ ] Zero Hindi entries in stories index
- [ ] Zero Hindi entries in any content index
- [ ] Zero Hindi audio files in `public/audio/`
- [ ] Old files archived in `/opt/audio-store/_archive_old_hindi/`
- [ ] App with `language: "hi"` shows empty states for all sections
- [ ] App with `language: "en"` is completely unaffected

---

## 6. New Hindi Content: Publishing Flow

After old content is removed, new conversational Hindi content goes through
this flow:

```
Generate (scripts/generate_*.py --lang hi)
  → Validate (conversational_score ≥ 0.70, no literary Hindi)
  → QA (listen test — pronunciation, warmth, register)
  → Publish to seed_output/ with lang: "hi"
  → Copy to public/audio/ (same structure as English)
  → Update index JSON (lullabies.json, stories index, etc.)
  → Content appears in Hindi feed for users who switched language
```

### Content JSON: Required Fields for Hindi

Every Hindi content item must have:

```json
{
  "lang": "hi",
  "title": "चाँद का सफ़र",
  "title_en": "The Moon's Journey",
  "description": "एक छोटा खरगोश चाँद से मिलने निकला...",
  "description_en": "A little rabbit sets off to meet the moon...",
  "cover_description_en": "A small rabbit looking up at a silver moon, watercolor...",
  "story_type": "lok_katha",
  "conversational_score": 0.85,
  "repeated_phrase": "सुनो ना...",
  // ... all other standard fields (id, type, age, mood, audio_file, etc.)
}
```

The `_en` fields are for internal tooling (search, FLUX covers, analytics).
They are never shown to the user.

---

## 7. Testing Protocol

### Phase 1: Internal Testing (you + Neha + friends)

1. Generate 15-20 Hindi short stories across moods and age groups
2. Generate 6 Hindi lullabies (Phase 1 batch from lullaby spec)
3. Publish all to production with `lang: "hi"`
4. Switch your own profile to Hindi
5. Test every story and lullaby on the actual app
6. Share "switch to Hindi in settings" instruction with 3-5 Indian parent friends
7. Collect feedback on: comprehension, register (does it sound natural?),
   voice quality, music, covers, overall bedtime experience

### Phase 2: Soft Launch

Once internal testing passes:
1. Add a small banner on the profile page: "🇮🇳 Hindi stories now available!"
2. Still behind the language setting — users must opt in
3. Monitor: do Hindi users return? Do their kids fall asleep?

### Phase 3: Full Launch

Once Hindi engagement is validated:
1. Add language selection to onboarding (for new users only)
2. Auto-detect device language and suggest Hindi for Hindi-locale devices
3. Consider bilingual mode (English + Hindi mixed feed) — but only if users ask for it

---

## 8. Technical Checklist for the Agent

### Backend Changes

- [ ] Add `lang` field to content Pydantic model (if not already present)
- [ ] Add `title_en`, `description_en`, `cover_description_en` fields
- [ ] Add `story_type`, `conversational_score`, `repeated_phrase` fields
- [ ] Content API: accept `?lang=en` or `?lang=hi` query parameter
- [ ] Content API: default to `lang=en` if no parameter provided
- [ ] Remove all existing Hindi content from indices and public directories
- [ ] Archive removed content to `/opt/audio-store/_archive_old_hindi/`

### Frontend Changes

- [ ] Add `language` field to user profile state (localStorage)
- [ ] Default `language` to `"en"` for all users
- [ ] Add language toggle to profile/settings page
- [ ] Pass `language` to all content loading functions
- [ ] Filter content grid by `lang` field
- [ ] Show Hindi mood labels when `language === "hi"`
- [ ] Show "Coming soon in Hindi" empty state for sections with zero Hindi content
- [ ] Story card: display `title` (Devanagari) and Hindi mood label for Hindi content
- [ ] Player: display Hindi title when playing Hindi content

### What Does NOT Change

- [ ] Tab structure (same sections for both languages)
- [ ] Cover art pipeline (FLUX reads English description regardless of content language)
- [ ] Music beds (language-independent, shared)
- [ ] Age group logic
- [ ] Mood system
- [ ] Audio player component
- [ ] Landing page (stays English)
- [ ] SEO pages (stay English for now)

---

## 9. Future Considerations (Not for Phase 1)

- **Bilingual feed:** Some parents might want both English and Hindi mixed.
  Add a "Both" option to the language toggle later if requested.
- **Auto-detection:** Use `navigator.language` to suggest Hindi for `hi-IN` locale
  devices during onboarding. Not for Phase 1.
- **Per-child language:** If a family has multiple children with different
  language preferences, the profile needs per-child language settings.
  Not for Phase 1 — current profile is single-child.
- **Hindi landing page / SEO:** A Hindi version of dreamvalley.app for
  organic search from India. Separate effort, not part of content publishing.
- **Hindi UI strings:** Translate button labels, section headers, player controls
  to Hindi when language is set. Nice-to-have, not blocking.
