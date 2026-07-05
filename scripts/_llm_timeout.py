"""Language-neutral hard wall-clock backstop for LLM calls.

Home for _hard_timeout so BOTH language paths import it from a neutral source:
the HI wrapper (_hindi_llm.py) and the EN generator (generate_long_story_episode.py).
Previously EN imported it from _hindi_llm, a misleading coupling (why would the
English generator depend on the Hindi LLM module?). Same shared-source / anti-
drift principle as _story_axes.

A degraded outbound connection once wedged a Mistral call for 22min with the
provider SDK / httpx read-timeout never firing; in a gated pipeline (~15 calls
per story) that is a cron-stall risk. This runs the call on a worker thread and
abandons it if it blows the hard limit — the caller regains control
(retry / re-pick); the wedged thread lingers harmlessly until the process exits.
"""
from __future__ import annotations

import concurrent.futures

_CALL_EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _hard_timeout(fn, seconds, **kwargs):
    fut = _CALL_EXEC.submit(fn, **kwargs)
    try:
        return fut.result(timeout=seconds)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(
            f"hard wall-clock timeout after {seconds}s (inner read-timeout did not fire)")
