"""User feedback and report endpoints."""

import os
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel

from app.dependencies import get_optional_user, get_db_client
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

RESEND_ENDPOINT = "https://api.resend.com/emails"
FROM_EMAIL = "Dream Valley <support@dreamvalley.app>"
TO_EMAIL = "mohan.anmol@gmail.com"


def _get_resend_key() -> str:
    """Get Resend API key at call time (env may be loaded lazily)."""
    return os.getenv("RESEND_API_KEY", "")


# ── Request / Response Models ────────────────────────────────────────

class ReportRequest(BaseModel):
    """Request model for submitting a report."""
    content_id: str
    content_title: str
    voice: Optional[str] = None
    issue_type: str  # audio_quality | story_content | background_music | voice_mismatch | other
    description: Optional[str] = None


class ReportResponse(BaseModel):
    """Response model for reports."""
    success: bool
    message: str


# ── Email Builder ────────────────────────────────────────────────────

ISSUE_LABELS = {
    "audio_quality": "🔊 Audio quality issue",
    "story_content": "📖 Story content issue",
    "background_music": "🎵 Background music issue",
    "voice_mismatch": "🗣️ Voice doesn't match story",
    "other": "🐛 Other issue",
}


def _build_report_html(report: ReportRequest, user_id: Optional[str]) -> str:
    """Build HTML email body for a user report."""
    issue_label = ISSUE_LABELS.get(report.issue_type, report.issue_type)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    desc_html = ""
    if report.description:
        desc_html = f"""
        <tr>
          <td style="padding:8px 0;color:#6b7280;font-size:14px;vertical-align:top;">Description</td>
          <td style="padding:8px 0 8px 12px;font-size:14px;">{report.description}</td>
        </tr>
        """

    user_html = ""
    if user_id:
        user_html = f"""
        <tr>
          <td style="padding:8px 0;color:#6b7280;font-size:14px;">User ID</td>
          <td style="padding:8px 0 8px 12px;font-size:14px;font-family:monospace;">{user_id}</td>
        </tr>
        """

    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
                max-width:600px;margin:0 auto;color:#333;">
      <div style="background:#6B4CE6;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;font-size:18px;">⚠️ User Report</h2>
        <p style="margin:4px 0 0;opacity:0.9;font-size:13px;">{timestamp}</p>
      </div>
      <div style="background:#f9fafb;padding:20px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;">
        <table style="width:100%;border-collapse:collapse;">
          <tr>
            <td style="padding:8px 0;color:#6b7280;font-size:14px;">Story</td>
            <td style="padding:8px 0 8px 12px;font-size:14px;font-weight:600;">{report.content_title}</td>
          </tr>
          <tr>
            <td style="padding:8px 0;color:#6b7280;font-size:14px;">Content ID</td>
            <td style="padding:8px 0 8px 12px;font-size:14px;font-family:monospace;">{report.content_id}</td>
          </tr>
          <tr>
            <td style="padding:8px 0;color:#6b7280;font-size:14px;">Voice</td>
            <td style="padding:8px 0 8px 12px;font-size:14px;">{report.voice or 'Not specified'}</td>
          </tr>
          <tr>
            <td style="padding:8px 0;color:#6b7280;font-size:14px;">Issue Type</td>
            <td style="padding:8px 0 8px 12px;font-size:14px;font-weight:600;color:#ef4444;">{issue_label}</td>
          </tr>
          {desc_html}
          {user_html}
        </table>
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0;" />
        <p style="font-size:12px;color:#9ca3af;">
          Sent via Dream Valley app &middot;
          <a href="https://dreamvalley.app/player/{report.content_id}" style="color:#6366f1;">View story</a>
        </p>
      </div>
    </div>
    """


# ── Endpoint ─────────────────────────────────────────────────────────

@router.post("/report", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def submit_report(
    report: ReportRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
    db_client=Depends(get_db_client),
) -> ReportResponse:
    """
    Submit a user report about a story.

    Does not require authentication — includes user ID if logged in.
    Sends an email notification and stores the report in Firestore.
    """
    user_id = current_user["uid"] if current_user else None

    # Store in Firestore
    try:
        report_data = {
            "content_id": report.content_id,
            "content_title": report.content_title,
            "voice": report.voice,
            "issue_type": report.issue_type,
            "description": report.description,
            "user_id": user_id,
            "created_at": datetime.utcnow(),
        }
        db_client.collection("reports").add(report_data)
    except Exception as e:
        logger.warning(f"Failed to store report in Firestore: {e}")

    # Send email via Resend
    resend_key = _get_resend_key()
    if not resend_key:
        logger.warning("RESEND_API_KEY not set — skipping report email")
        return ReportResponse(success=True, message="Report submitted (email skipped)")

    issue_label = ISSUE_LABELS.get(report.issue_type, report.issue_type)
    subject = f"[Report] {report.content_title} — {issue_label}"
    html = _build_report_html(report, user_id)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                RESEND_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": FROM_EMAIL,
                    "to": [TO_EMAIL],
                    "subject": subject,
                    "html": html,
                },
            )

        if resp.status_code in (200, 201):
            logger.info(f"Report email sent: {subject}")
        else:
            logger.warning(f"Report email failed ({resp.status_code}): {resp.text[:200]}")

    except Exception as e:
        logger.warning(f"Report email failed: {e}")

    return ReportResponse(success=True, message="Report submitted successfully")
