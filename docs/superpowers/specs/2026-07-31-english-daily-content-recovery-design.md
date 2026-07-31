# English Daily Content Recovery Design

## Goal

Prevent the two failure modes observed in the 2026-07-31 English pipeline, regenerate only the missing short story and silly song, and publish them without changing unrelated production content.

## Changes

### Silly-song duration and age

- Accept complete MiniMax renders from 50 through 100 seconds.
- Keep duration validation mandatory and delete rejected audio.
- Restore two bounded audio-generation attempts around prediction, download, and duration validation.
- Pass the before-bed age to `generate_silly_songs_battlecry.py` so the silly song matches the poem and funny short.

### Short-story resilience

- Keep all comprehensibility and diversity rules unchanged.
- Allow up to three independent content-generation rounds in the pipeline: the initial round plus two retries.
- Recalculate missing stories and poems after every round and stop immediately when the requested counts are met.

## Tests

- A 50-second and a 100-second silly song are accepted; values outside the range are rejected.
- A failed first MiniMax render is retried once.
- The before-bed command includes the selected age.
- Partial content generation can run two retries and stops after success.

## Production rollout

1. Implement and verify the focused tests on a clean branch based on `origin/main`.
2. Commit and push the code to `main`.
3. Run `deploy_guard.py snapshot` on production.
4. Pull `main` on production. These are pipeline-script changes, so no backend container rebuild is required.
5. Regenerate one English short story and its audio, QA, enrichment, mood, and cover stages.
6. Regenerate one English 9–12 wired silly song.
7. Sync assets and call the admin reload endpoint.
8. Run `deploy_guard.py verify` and `deploy_guard.py check`.

## Safety

- Do not rerun the full daily pipeline, which would create duplicate lullaby, poem, long-story, and funny-short content.
- Treat exactly one new English short story and one new English 9–12 silly song as intended deploy-guard additions.
- Stop before publishing if either validator, audio generation, QA, cover generation, reload, or deploy guard fails.
