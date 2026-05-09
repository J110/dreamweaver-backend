"""Resend email sender (transactional).

Thin wrapper around Resend's HTTP API, mirroring the pattern in
app/api/v1/feedback.py. Used by the magic-link auth flow.

Env:
  RESEND_API_KEY   — required for actual send. Missing → no-op log+swallow.
  AUTH_FROM_EMAIL  — defaults to "Dream Valley <support@dreamvalley.app>"
                     (already-verified Resend sender shared with feedback +
                     pipeline notifications). Override to "auth@..." once
                     that subdomain is verified per spec Outstanding §1/§2.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"


def _from_email() -> str:
    return os.getenv(
        "AUTH_FROM_EMAIL",
        "Dream Valley <support@dreamvalley.app>",
    )


async def send_email_via_resend(
    to: str,
    subject: str,
    html: str,
    from_address: Optional[str] = None,
) -> bool:
    """Send a single transactional email via Resend.

    Returns True on 2xx response, False on missing key / network error / 4xx+.
    Never raises — auth flows treat email failures as a soft signal (log
    WARNING, return generic-success to client to avoid enumeration leak).
    """
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        logger.warning("RESEND_API_KEY missing — email send skipped (to=%s)", to)
        return False

    body = {
        "from": from_address or _from_email(),
        "to": [to],
        "subject": subject,
        "html": html,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                RESEND_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        if 200 <= resp.status_code < 300:
            logger.info("Resend OK to=%s subject=%r", to, subject)
            return True
        logger.warning(
            "Resend failed to=%s status=%d body=%s",
            to, resp.status_code, resp.text[:200],
        )
        return False
    except Exception as e:
        logger.warning("Resend error to=%s: %s", to, e)
        return False
