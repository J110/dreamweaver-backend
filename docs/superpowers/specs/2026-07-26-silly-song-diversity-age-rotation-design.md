# Silly Song Diversity and Age Rotation

## Goal

Prevent lexically or semantically repetitive English silly-song hooks and ensure one-song daily runs rotate consistently across ages 2-5, 6-8, and 9-12.

## Scope

Update `scripts/generate_silly_songs_battlecry.py` only, plus focused tests. The change does not alter lyrics validation, audio generation, cover generation, publishing, Hindi generation, or existing catalog entries.

## Hook Diversity

Build the comparison set from the newest production metadata first. Include both `title` and `anthem`/`battle_cry`, normalize duplicates, and retain the newest unique hooks rather than the oldest entries from a recent window.

Normalize each candidate and existing hook by:

- removing markdown, punctuation, and repeated whitespace;
- lowercasing;
- reducing common inflections where practical;
- removing low-information stop words only for similarity comparison.

Apply checks in this order:

1. Reject an exact normalized match or existing song ID.
2. Reject token Jaccard similarity at or above `0.60` or normalized string similarity at or above `0.82`.
3. Send candidates with token Jaccard similarity from `0.35` through `0.59`, or normalized string similarity from `0.68` through `0.81`, to Mistral with the five closest existing hooks and require a structured `similar` or `not_similar` result.
4. Accept candidates below both borderline ranges without a semantic call.

The Mistral check is a second line of defense, not the sole enforcement mechanism. A malformed or unavailable semantic response is treated conservatively as similar for borderline candidates.

When a candidate is rejected, regenerate it with the conflicting hooks and rejection reason included in the prompt. Allow three invention attempts total. If all attempts fail, exit without generating metadata, audio, cover, or catalog changes.

## Age Rotation

Derive the next age from production metadata on every invocation instead of rebuilding a batch-local cycle at index zero.

For each age group, determine its latest valid `created_at`. Select the age whose latest generation is oldest. An age with no valid generation date is considered oldest and selected first. Break ties using the fixed order:

1. `2-5`
2. `6-8`
3. `9-12`

For multi-song runs, append each successful result to the in-memory history before selecting the next age. This produces balanced coverage for both daily `--count 1` runs and larger batches.

## Data Flow

1. Load and chronologically order existing song metadata.
2. Select the least-recently-generated age.
3. Select the category and mood using existing rules.
4. Invent a hook.
5. Run deterministic similarity checks.
6. Run semantic judgment only for borderline candidates.
7. Retry rejected candidates up to the attempt limit.
8. Generate lyrics, audio, cover, and publish only after the hook passes.
9. Add the successful song to in-memory rotation and diversity history.

## Observability

Log:

- the selected age and latest generation date for every age group;
- the closest deterministic hook match and score;
- whether semantic judgment ran and its structured result;
- each rejection reason and retry number;
- terminal retry exhaustion before a non-zero exit.

Do not log API keys, tokens, full model responses, or unrelated song metadata.

## Tests

Focused tests must cover:

- `Tiny Parade Hooray`, `Tiny Parade Today`, and `Tiny Parade` as rejected near-duplicates;
- punctuation, markdown, casing, and inflection normalization;
- a semantic paraphrase with low lexical overlap rejected by the semantic judge;
- a genuinely distinct hook accepted;
- newest hooks included in the avoid set;
- malformed semantic output handled conservatively;
- three rejected attempts causing a non-zero, no-publish failure;
- missing or malformed `created_at`;
- three separate one-song selections producing `2-5`, `6-8`, `9-12`;
- multi-song selection remaining balanced;

## Production Rollout

Run focused tests and syntax validation, then deploy through the normal Deploy Guard snapshot and verify workflow. Before generating production audio, run a lyrics-only dry run that demonstrates near-duplicate rejection and the next expected age. The first three successful daily runs must cover all three age groups exactly once.

## Acceptance Criteria

- No candidate lexically or semantically equivalent to a recent or existing hook can reach asset generation.
- A rejected hook is never written to metadata or catalog files.
- Three consecutive successful `--fresh --count 1` invocations select all three age groups exactly once.
- Existing category and mood rotation remains functional.
- Deploy Guard reports the generated item fully serving, apart from any explicitly waived unrelated production check.
