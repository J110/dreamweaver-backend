"""PostHog server-side emitter.

Thin wrapper around the posthog Python SDK. Lazy init on first call.

Configuration via env vars:
  POSTHOG_PROJECT_API_KEY: project API key (same phc_* value as the web
                           client — public-by-design, server-side
                           placement is for env hygiene, not secret
                           protection).
  POSTHOG_HOST:            defaults to https://us.i.posthog.com
  POSTHOG_DISABLED:        set to '1' / 'true' to disable emission
                           (tests / CI / local dev escape hatch).

All public functions log + swallow on error — analytics failures must
never break user-facing paths.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_client: Optional[Any] = None
_initialized: bool = False
_disabled: bool = False


def _get_client() -> Optional[Any]:
    global _client, _initialized, _disabled
    if _initialized:
        return None if _disabled else _client

    _initialized = True

    if os.getenv("POSTHOG_DISABLED", "").lower() in ("1", "true", "yes"):
        logger.info("POSTHOG_DISABLED set — server-side PostHog emission disabled")
        _disabled = True
        return None

    api_key = os.getenv("POSTHOG_PROJECT_API_KEY", "").strip()
    if not api_key:
        logger.warning(
            "POSTHOG_PROJECT_API_KEY missing — server-side PostHog emission disabled"
        )
        _disabled = True
        return None

    try:
        from posthog import Posthog
    except ImportError:
        logger.warning("posthog Python SDK not installed — emission disabled")
        _disabled = True
        return None

    host = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")
    try:
        _client = Posthog(api_key, host=host)
        logger.info("PostHog server emitter initialized (host=%s)", host)
    except Exception as e:
        logger.warning("PostHog client init failed: %s", e)
        _disabled = True
        return None

    return _client


def emit_event(
    distinct_id: str,
    event_name: str,
    properties: Optional[Dict[str, Any]] = None,
) -> None:
    client = _get_client()
    if client is None or not distinct_id:
        return
    try:
        client.capture(
            distinct_id=distinct_id,
            event=event_name,
            properties=properties or {},
        )
    except Exception as e:
        logger.warning("PostHog emit_event(%s) failed: %s", event_name, e)


def identify(
    distinct_id: str,
    properties: Optional[Dict[str, Any]] = None,
) -> None:
    """Set Person properties on a distinct_id.

    properties may include $set and $set_once keys for the standard
    PostHog Person property semantics.
    """
    client = _get_client()
    if client is None or not distinct_id:
        return
    try:
        client.identify(distinct_id=distinct_id, properties=properties or {})
    except Exception as e:
        logger.warning("PostHog identify(%s) failed: %s", distinct_id, e)


def alias(previous_id: str, distinct_id: str) -> None:
    client = _get_client()
    if client is None or not previous_id or not distinct_id:
        return
    try:
        client.alias(previous_id=previous_id, distinct_id=distinct_id)
    except Exception as e:
        logger.warning(
            "PostHog alias(%s -> %s) failed: %s", previous_id, distinct_id, e
        )


def flush() -> None:
    """Flush queued events. Call before process exit (e.g. cron scripts)."""
    client = _get_client()
    if client is None:
        return
    try:
        if hasattr(client, "flush"):
            client.flush()
    except Exception as e:
        logger.warning("PostHog flush failed: %s", e)
