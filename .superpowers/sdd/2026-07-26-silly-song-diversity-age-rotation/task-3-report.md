# Task 3: Persistent Age Rotation

## RED evidence

Command:

```sh
PYTHONPATH=. pytest -q scripts/test_silly_song_diversity_rotation.py
```

Result: 3 failed, 10 passed. Each new age-rotation test failed with `AttributeError` because `select_next_age` did not exist.

## GREEN evidence

Command:

```sh
PYTHONPATH=. pytest -q scripts/test_silly_song_diversity_rotation.py
```

Result: 13 passed, 1 existing `replicate`/Pydantic Python 3.14 compatibility warning.

## Files

- `scripts/generate_silly_songs_battlecry.py`
- `scripts/test_silly_song_diversity_rotation.py`

## Self-review

- Age selection reads successful production history, treats invalid or missing dates as oldest, and uses `AGE_GROUPS` order for deterministic ties.
- Fresh-mode selection occurs immediately before hook invention and successful generated results remain appended to `existing_songs`.
- Existing hook-comparison interfaces remain unchanged.

## Concerns

- Focused pytest emits the pre-existing Python 3.14 `replicate` Pydantic V1 compatibility warning.
