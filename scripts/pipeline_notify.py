#!/usr/bin/env python3
"""Send pipeline status notifications via Resend API.

Sends an HTML email summarising a pipeline run — called by pipeline_run.py
on BOTH success and failure so the operator always gets notified.

Standalone test:
    python3 scripts/pipeline_notify.py --test
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx

# ── Paths & Config ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_ENDPOINT = "https://api.resend.com/emails"
FROM_EMAIL = "Dream Valley Pipeline <onboarding@resend.dev>"
TO_EMAIL = "mohan.anmol@gmail.com"


def _fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def _tail_log(log_file: str, lines: int = 20) -> str:
    """Return the last N lines of a log file."""
    try:
        path = Path(log_file)
        if path.exists():
            all_lines = path.read_text().splitlines()
            return "\n".join(all_lines[-lines:])
    except Exception:
        pass
    return "(log file not available)"


def _build_html(state: dict, log_file: str = "", elapsed: float = 0) -> str:
    """Build a clean HTML email body from pipeline state."""
    status = state.get("status", "unknown")
    is_success = status == "completed"
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    generated = state.get("generated_ids", [])
    qa_passed = state.get("qa_passed", [])
    qa_failed = state.get("qa_failed", [])
    covers_ok = state.get("covers_generated", [])
    covers_fail = state.get("covers_failed", [])
    disk_info = state.get("disk_info", "")
    cost_this_run = state.get("cost_this_run", "")
    cost_monthly = state.get("cost_monthly", "")

    status_color = "#22c55e" if is_success else "#ef4444"
    status_label = "SUCCESS" if is_success else "FAILED"
    failed_step = ""
    if not is_success and status.startswith("failed_at_"):
        failed_step = status.replace("failed_at_", "")

    rows = f"""
    <tr><td><b>Generated</b></td><td>{len(generated)} items</td></tr>
    <tr><td><b>Audio QA</b></td><td>{len(qa_passed)} passed, {len(qa_failed)} failed</td></tr>
    <tr><td><b>Covers</b></td><td>{len(covers_ok)} generated, {len(covers_fail)} fallback</td></tr>
    <tr><td><b>Elapsed</b></td><td>{_fmt_duration(elapsed)}</td></tr>
    """
    if cost_this_run:
        rows += f'<tr><td><b>This Run</b></td><td>{cost_this_run}</td></tr>'
    if cost_monthly:
        rows += f'<tr><td><b>Monthly Est.</b></td><td>{cost_monthly}</td></tr>'
    if disk_info:
        rows += f'<tr><td><b>Disk</b></td><td>{disk_info}</td></tr>'
    if failed_step:
        rows += f'<tr><td><b>Failed at</b></td><td style="color:#ef4444"><b>{failed_step}</b></td></tr>'

    # Generated item titles
    titles_html = ""
    titles = state.get("generated_titles", [])
    if titles:
        items = "".join(f"<li>{t}</li>" for t in titles)
        titles_html = f"<h3>New Content</h3><ul>{items}</ul>"

    # Log tail on failure
    log_html = ""
    if not is_success and log_file:
        log_tail = _tail_log(log_file, 20)
        log_html = f"""
        <h3>Last 20 Log Lines</h3>
        <pre style="background:#1e1e1e;color:#d4d4d4;padding:12px;border-radius:6px;
                    font-size:12px;overflow-x:auto;white-space:pre-wrap;">{log_tail}</pre>
        """

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
                max-width:600px;margin:0 auto;color:#333;">
      <div style="background:{status_color};color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;font-size:20px;">Pipeline {status_label}</h2>
        <p style="margin:4px 0 0;opacity:0.9;font-size:14px;">{date_str}</p>
      </div>
      <div style="background:#f9fafb;padding:20px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          {rows}
        </table>
        {titles_html}
        {log_html}
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0;" />
        <p style="font-size:12px;color:#9ca3af;">
          Dream Valley Automated Pipeline &middot;
          <a href="https://dreamvalley.app" style="color:#6366f1;">dreamvalley.app</a>
        </p>
      </div>
    </div>
    """
    return html


def send_pipeline_notification(
    state: dict, log_file: str = "", elapsed: float = 0
) -> bool:
    """Send pipeline status email. Returns True on success."""
    if not RESEND_API_KEY:
        print("  WARNING: RESEND_API_KEY not set — skipping email notification")
        return False

    status = state.get("status", "unknown")
    is_success = status == "completed"
    date_str = datetime.now().strftime("%Y-%m-%d")

    tag = "[OK]" if is_success else "[FAIL]"
    n_items = len(state.get("generated_ids", []))
    subject = f"{tag} Dream Valley Pipeline — {date_str}"
    if is_success and n_items:
        subject += f" — {n_items} new items"

    html = _build_html(state, log_file, elapsed)

    try:
        resp = httpx.post(
            RESEND_ENDPOINT,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": FROM_EMAIL,
                "to": [TO_EMAIL],
                "subject": subject,
                "html": html,
            },
            timeout=30,
        )
        if resp.status_code in (200, 201):
            print(f"  Email notification sent: {subject}")
            return True
        else:
            print(f"  WARNING: Email failed ({resp.status_code}): {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  WARNING: Email notification failed: {e}")
        return False


# ── Standalone test ───────────────────────────────────────────────────
if __name__ == "__main__":
    if "--test" in sys.argv:
        test_state = {
            "status": "completed",
            "generated_ids": ["test-001", "test-002"],
            "generated_titles": ["Test Story: The Friendly Cloud", "Test Poem: Starlight Whisper"],
            "qa_passed": ["test-001", "test-002"],
            "qa_failed": [],
            "covers_generated": ["test-001"],
            "covers_failed": ["test-002"],
            "cost_this_run": "~$0.97",
            "cost_monthly": "~$29.13/mo (GCP $16.13 + Modal ~$13.00 from $30 free credits)",
            "disk_info": "Audio: 304 files (1.2 GB), Covers: 12 SVGs",
        }
        ok = send_pipeline_notification(test_state, "", 325.7)
        sys.exit(0 if ok else 1)
    else:
        print("Usage: python3 scripts/pipeline_notify.py --test")
