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
FROM_EMAIL = "Dream Valley Pipeline <support@dreamvalley.app>"
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
    covers_flux = state.get("covers_flux", [])
    covers_fallback = state.get("covers_fallback", [])
    disk_info = state.get("disk_info", "")
    cost_this_run = state.get("cost_this_run", "")
    cost_modal = state.get("cost_modal", "")
    cost_gcp_daily = state.get("cost_gcp_daily", "")
    cost_monthly = state.get("cost_monthly", "")

    # Per-type breakdown for email
    stories_n = state.get("generated_stories", 0)
    poems_n = state.get("generated_poems", 0)
    lullabies_n = state.get("generated_lullabies", 0)
    type_parts = []
    if stories_n: type_parts.append(f"{stories_n} {'story' if stories_n == 1 else 'stories'}")
    if poems_n: type_parts.append(f"{poems_n} {'poem' if poems_n == 1 else 'poems'}")
    if lullabies_n: type_parts.append(f"{lullabies_n} {'lullaby' if lullabies_n == 1 else 'lullabies'}")
    type_detail = f" ({', '.join(type_parts)})" if type_parts else ""

    generation_warning = state.get("generation_warning", "")
    is_partial = is_success and bool(generation_warning)

    if is_partial:
        status_color = "#f59e0b"  # amber/yellow
        status_label = "PARTIAL"
    elif is_success:
        status_color = "#22c55e"
        status_label = "SUCCESS"
    else:
        status_color = "#ef4444"
        status_label = "FAILED"

    failed_step = ""
    if not is_success and status.startswith("failed_at_"):
        failed_step = status.replace("failed_at_", "")

    rows = f"""
    <tr><td><b>Generated</b></td><td>{len(generated)} items{type_detail}</td></tr>
    <tr><td><b>Audio QA</b></td><td>{len(qa_passed)} passed, {len(qa_failed)} failed</td></tr>
    <tr><td><b>Covers</b></td><td>{len(covers_ok)} generated ({len(covers_flux)} FLUX, {len(covers_fallback)} Mistral), {len(covers_fail)} failed</td></tr>
    <tr><td><b>Elapsed</b></td><td>{_fmt_duration(elapsed)}</td></tr>
    """
    # Cost section — actual costs, not estimates
    if cost_this_run:
        rows += f'<tr><td colspan="2" style="padding-top:8px"><b>💰 Cost Breakdown</b></td></tr>'
        rows += f'<tr><td>&nbsp;&nbsp;Modal GPU</td><td>{cost_modal}</td></tr>'
        rows += f'<tr><td>&nbsp;&nbsp;GCP VM</td><td>{cost_gcp_daily}/day</td></tr>'
        rows += f'<tr><td>&nbsp;&nbsp;<b>Total this run</b></td><td><b>{cost_this_run}</b></td></tr>'
    if cost_monthly:
        rows += f'<tr><td>&nbsp;&nbsp;Monthly proj.</td><td>{cost_monthly}</td></tr>'
    if disk_info:
        rows += f'<tr><td><b>Disk</b></td><td>{disk_info}</td></tr>'
    if generation_warning:
        rows += f'<tr><td><b>⚠️ Warning</b></td><td style="color:#f59e0b"><b>{generation_warning}</b></td></tr>'
    if failed_step:
        rows += f'<tr><td><b>Failed at</b></td><td style="color:#ef4444"><b>{failed_step}</b></td></tr>'

    # Generated item titles
    titles_html = ""
    titles = state.get("generated_titles", [])
    if titles:
        items = "".join(f"<li>{t}</li>" for t in titles)
        titles_html = f"<h3>New Content</h3><ul>{items}</ul>"

    # Detailed cover status — distinguish FLUX AI vs Mistral fallback
    covers_html = ""
    covers_flux_titles = state.get("covers_flux_titles", [])
    covers_fallback_titles = state.get("covers_fallback_titles", [])
    covers_fail_titles = state.get("covers_failed_titles", [])
    if covers_flux_titles or covers_fallback_titles or covers_fail_titles:
        covers_items = ""
        for t in covers_flux_titles:
            covers_items += f'<li style="color:#22c55e;">✅ {t} <span style="color:#9ca3af;">(FLUX)</span></li>'
        for t in covers_fallback_titles:
            covers_items += f'<li style="color:#f59e0b;">⚠️ {t} <span style="color:#9ca3af;">(Mistral fallback)</span></li>'
        for t in covers_fail_titles:
            covers_items += f'<li style="color:#ef4444;">❌ {t} <span style="color:#9ca3af;">(no cover)</span></li>'
        covers_html = f"<h3>🎨 Cover Status</h3><ul style='list-style:none;padding-left:0;'>{covers_items}</ul>"

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
        {covers_html}
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

    gen_warning = state.get("generation_warning", "")
    is_partial = is_success and bool(gen_warning)

    if is_partial:
        tag = "[PARTIAL]"
    elif is_success:
        tag = "[OK]"
    else:
        tag = "[FAIL]"

    n_items = len(state.get("generated_ids", []))
    subject = f"{tag} Dream Valley Pipeline — {date_str}"
    if is_success and n_items:
        # Per-type breakdown in subject
        stories_n = state.get("generated_stories", 0)
        poems_n = state.get("generated_poems", 0)
        lullabies_n = state.get("generated_lullabies", 0)
        parts = []
        if stories_n: parts.append(f"{stories_n} story" if stories_n == 1 else f"{stories_n} stories")
        if poems_n: parts.append(f"{poems_n} poem" if poems_n == 1 else f"{poems_n} poems")
        if lullabies_n: parts.append(f"{lullabies_n} lullaby" if lullabies_n == 1 else f"{lullabies_n} lullabies")
        subject += f" — {', '.join(parts)}" if parts else f" — {n_items} new items"

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


# ═══════════════════════════════════════════════════════════════════════
# QA DETAIL NOTIFICATION
# ═══════════════════════════════════════════════════════════════════════

QA_REPORT_PATH = BASE_DIR / "seed_output" / "qa_reports" / "qa_audio_latest.json"
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"


def _verdict_badge(verdict: str) -> str:
    """Return an HTML badge for a QA verdict."""
    colors = {
        "PASS": ("#22c55e", "#f0fdf4"),
        "WARN": ("#f59e0b", "#fffbeb"),
        "FAIL": ("#ef4444", "#fef2f2"),
    }
    fg, bg = colors.get(verdict, ("#6b7280", "#f3f4f6"))
    return (f'<span style="background:{bg};color:{fg};padding:2px 8px;'
            f'border-radius:4px;font-weight:600;font-size:12px;">{verdict}</span>')


def _score_color(score: float) -> str:
    """Return color based on score (0-1)."""
    if score >= 0.8:
        return "#22c55e"
    if score >= 0.6:
        return "#f59e0b"
    return "#ef4444"


def _build_qa_html(qa_report: dict, state: dict) -> str:
    """Build detailed QA email with separate sections for stories/poems and lullabies."""
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary = qa_report.get("summary", {})
    stories = qa_report.get("stories", [])

    qa_passed_ids = set(state.get("qa_passed", []))
    qa_failed_ids = set(state.get("qa_failed", []))
    deployed_ids = set()
    deploy_status = state.get("step_deploy_prod", "not run")
    if deploy_status in ("done", "skipped"):
        deployed_ids = qa_passed_ids

    # Load content.json to determine type (story/poem/song)
    content_types = {}
    try:
        content = json.loads(CONTENT_PATH.read_text())
        for item in content:
            content_types[item["id"]] = item.get("type", "story")
    except Exception:
        pass

    # Separate into stories/poems vs lullabies
    story_poem_reports = []
    lullaby_reports = []
    for s in stories:
        sid = s.get("story_id", "")
        ctype = content_types.get(sid, "story")
        if ctype == "song":
            lullaby_reports.append(s)
        else:
            story_poem_reports.append(s)

    # Overall banner color
    total_failed = summary.get("failed", 0)
    total_warned = summary.get("warned", 0)
    if total_failed > 0:
        banner_color = "#ef4444"
        banner_label = "QA ISSUES FOUND"
    elif total_warned > 0:
        banner_color = "#f59e0b"
        banner_label = "QA WARNINGS"
    else:
        banner_color = "#22c55e"
        banner_label = "QA ALL PASSED"

    # Summary row
    summary_html = f"""
    <table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:16px;">
      <tr><td><b>Total variants</b></td><td>{summary.get('total', 0)}</td></tr>
      <tr><td><b>Passed</b></td><td style="color:#22c55e;font-weight:600;">{summary.get('passed', 0)}</td></tr>
      <tr><td><b>Warned</b></td><td style="color:#f59e0b;font-weight:600;">{summary.get('warned', 0)}</td></tr>
      <tr><td><b>Failed</b></td><td style="color:#ef4444;font-weight:600;">{summary.get('failed', 0)}</td></tr>
    </table>
    """

    def _build_story_section(report_list, section_title, is_lullaby=False):
        if not report_list:
            return ""

        items_html = ""
        for s in report_list:
            sid = s.get("story_id", "")
            title = s.get("title", sid)
            median_dur = s.get("median_duration", 0)

            # Determine if this story was published
            is_published = sid in deployed_ids
            is_qa_failed = sid in qa_failed_ids
            if is_published:
                pub_badge = '<span style="background:#f0fdf4;color:#22c55e;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">PUBLISHED</span>'
            elif is_qa_failed:
                pub_badge = '<span style="background:#fef2f2;color:#ef4444;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">NOT PUBLISHED</span>'
            else:
                pub_badge = '<span style="background:#f3f4f6;color:#6b7280;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">PENDING</span>'

            # Build variant rows
            variant_rows = ""
            for v in s.get("variants", []):
                voice = v.get("voice", "?")
                verdict = v.get("verdict", "?")
                dur = v.get("duration_seconds", 0)
                reasons = v.get("reasons", [])

                if is_lullaby:
                    lqa = v.get("lullaby_qa", {})
                    quality_avg = lqa.get("quality_avg", 0)
                    dims = lqa.get("dimensions", {})
                    warnings = lqa.get("warnings", [])

                    # Key dimension scores
                    dim_parts = []
                    for dname, dinfo in dims.items():
                        score = dinfo.get("score", 0)
                        short_name = dname.replace("_", " ").title()
                        color = _score_color(score)
                        dim_parts.append(f'<span style="color:{color};">{short_name}: {score:.2f}</span>')
                    dims_html = " &middot; ".join(dim_parts) if dim_parts else ""

                    reasons_html = ""
                    all_reasons = reasons + warnings
                    if all_reasons:
                        reasons_html = '<br><span style="color:#9ca3af;font-size:11px;">' + ", ".join(all_reasons) + '</span>'

                    variant_rows += f"""
                    <tr style="border-bottom:1px solid #f3f4f6;">
                      <td style="padding:6px 8px;font-size:13px;">{voice}</td>
                      <td style="padding:6px 8px;text-align:center;">{_verdict_badge(verdict)}</td>
                      <td style="padding:6px 8px;text-align:center;font-size:13px;">{dur:.0f}s</td>
                      <td style="padding:6px 8px;text-align:center;font-size:13px;color:{_score_color(quality_avg)};">{quality_avg:.2f}</td>
                      <td style="padding:6px 8px;font-size:11px;">{dims_html}{reasons_html}</td>
                    </tr>
                    """
                else:
                    fidelity = v.get("text_fidelity_combined", 0)
                    quality_avg = v.get("quality_average", 0)
                    is_outlier = v.get("duration_outlier", False)

                    reasons_html = ""
                    if reasons:
                        reasons_html = '<br><span style="color:#9ca3af;font-size:11px;">' + ", ".join(reasons) + '</span>'

                    fid_color = _score_color(fidelity) if fidelity > 0 else "#9ca3af"
                    fid_text = f"{fidelity:.2f}" if fidelity > 0 else "—"

                    variant_rows += f"""
                    <tr style="border-bottom:1px solid #f3f4f6;">
                      <td style="padding:6px 8px;font-size:13px;">{voice}</td>
                      <td style="padding:6px 8px;text-align:center;">{_verdict_badge(verdict)}</td>
                      <td style="padding:6px 8px;text-align:center;font-size:13px;">{dur:.0f}s{'*' if is_outlier else ''}</td>
                      <td style="padding:6px 8px;text-align:center;font-size:13px;color:{fid_color};">{fid_text}</td>
                      <td style="padding:6px 8px;font-size:11px;">{reasons_html.lstrip('<br>')}</td>
                    </tr>
                    """

            # Column headers differ for lullabies vs stories
            if is_lullaby:
                header = """
                <tr style="background:#f9fafb;border-bottom:2px solid #e5e7eb;">
                  <th style="padding:6px 8px;text-align:left;font-size:12px;color:#6b7280;">Voice</th>
                  <th style="padding:6px 8px;text-align:center;font-size:12px;color:#6b7280;">Verdict</th>
                  <th style="padding:6px 8px;text-align:center;font-size:12px;color:#6b7280;">Duration</th>
                  <th style="padding:6px 8px;text-align:center;font-size:12px;color:#6b7280;">Quality</th>
                  <th style="padding:6px 8px;text-align:left;font-size:12px;color:#6b7280;">Dimensions / Warnings</th>
                </tr>
                """
            else:
                header = """
                <tr style="background:#f9fafb;border-bottom:2px solid #e5e7eb;">
                  <th style="padding:6px 8px;text-align:left;font-size:12px;color:#6b7280;">Voice</th>
                  <th style="padding:6px 8px;text-align:center;font-size:12px;color:#6b7280;">Verdict</th>
                  <th style="padding:6px 8px;text-align:center;font-size:12px;color:#6b7280;">Duration</th>
                  <th style="padding:6px 8px;text-align:center;font-size:12px;color:#6b7280;">Fidelity</th>
                  <th style="padding:6px 8px;text-align:left;font-size:12px;color:#6b7280;">Issues</th>
                </tr>
                """

            items_html += f"""
            <div style="margin-bottom:20px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
              <div style="background:#f9fafb;padding:10px 14px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center;">
                <span style="font-weight:600;font-size:14px;">{title}</span>
                {pub_badge}
              </div>
              <div style="padding:4px 6px;font-size:12px;color:#9ca3af;">
                Median: {median_dur:.0f}s &middot; {len(s.get('variants', []))} variants
              </div>
              <table style="width:100%;border-collapse:collapse;">
                {header}
                {variant_rows}
              </table>
            </div>
            """

        return f"<h3 style='margin:20px 0 12px;font-size:16px;'>{section_title}</h3>{items_html}"

    stories_section = _build_story_section(story_poem_reports, "Stories & Poems", is_lullaby=False)
    lullaby_section = _build_story_section(lullaby_reports, "Lullabies", is_lullaby=True)

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
                max-width:700px;margin:0 auto;color:#333;">
      <div style="background:{banner_color};color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;font-size:20px;">Audio QA Report — {banner_label}</h2>
        <p style="margin:4px 0 0;opacity:0.9;font-size:14px;">{date_str}</p>
      </div>
      <div style="background:#fff;padding:20px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;">
        {summary_html}
        {stories_section}
        {lullaby_section}
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0;" />
        <p style="font-size:12px;color:#9ca3af;">
          Dream Valley Audio QA &middot;
          <a href="https://dreamvalley.app" style="color:#6366f1;">dreamvalley.app</a>
        </p>
      </div>
    </div>
    """
    return html


def send_qa_notification(state: dict) -> bool:
    """Send detailed QA report email. Returns True on success."""
    if not RESEND_API_KEY:
        print("  WARNING: RESEND_API_KEY not set — skipping QA email")
        return False

    # Load QA report
    if not QA_REPORT_PATH.exists():
        print("  No QA report found — skipping QA email")
        return False

    try:
        qa_report = json.loads(QA_REPORT_PATH.read_text())
    except Exception as e:
        print(f"  Failed to load QA report: {e}")
        return False

    summary = qa_report.get("summary", {})
    total = summary.get("total", 0)
    if total == 0:
        print("  QA report is empty — skipping QA email")
        return False

    # Build subject line
    date_str = datetime.now().strftime("%Y-%m-%d")
    passed = summary.get("passed", 0)
    warned = summary.get("warned", 0)
    failed = summary.get("failed", 0)

    if failed > 0:
        tag = "[QA FAIL]"
    elif warned > 0:
        tag = "[QA WARN]"
    else:
        tag = "[QA OK]"

    n_stories = len(qa_report.get("stories", []))
    subject = f"{tag} Audio QA — {date_str} — {n_stories} items, {passed}P/{warned}W/{failed}F"

    html = _build_qa_html(qa_report, state)

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
            print(f"  QA email sent: {subject}")
            return True
        else:
            print(f"  WARNING: QA email failed ({resp.status_code}): {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  WARNING: QA email notification failed: {e}")
        return False


# ── Clips notification ────────────────────────────────────────────────


def _build_clips_html(clips_info: list, elapsed: float = 0) -> str:
    """Build HTML email body for clips-ready notification."""
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    count = len(clips_info)
    total_bytes = sum(c.get("fileSize", 0) for c in clips_info)
    total_mb = total_bytes / (1024 * 1024)

    elapsed_str = _fmt_duration(elapsed) if elapsed else ""

    # Build clip rows
    type_labels = {"story": "Story", "long_story": "Story", "poem": "Poem", "song": "Lullaby"}
    voice_labels = {"female_1": "Calm", "asmr": "ASMR", "male_2": "Lullaby", "female_3": "Lullaby"}

    rows_html = ""
    for c in clips_info:
        title = c.get("title", "Untitled")
        ctype = type_labels.get(c.get("contentType", "story"), c.get("contentType", "story"))
        voice = voice_labels.get(c.get("voice", ""), c.get("voice", ""))
        size_mb = c.get("fileSize", 0) / (1024 * 1024)
        rows_html += f"""
        <tr>
          <td style="padding:8px 10px;border-bottom:1px solid #e5e7eb;">{title}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:center;">{ctype}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:center;">{voice}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:right;">{size_mb:.1f} MB</td>
        </tr>"""

    summary_parts = [f"<b>{count} clip{'s' if count != 1 else ''}</b>", f"{total_mb:.1f} MB total"]
    if elapsed_str:
        summary_parts.append(f"generated in {elapsed_str}")
    summary = " &middot; ".join(summary_parts)

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
                max-width:600px;margin:0 auto;color:#333;">
      <div style="background:linear-gradient(135deg,#8b5cf6,#6366f1);color:#fff;
                  padding:16px 20px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;font-size:20px;">🎬 Clips Ready to Download</h2>
        <p style="margin:4px 0 0;opacity:0.9;font-size:14px;">{date_str}</p>
      </div>
      <div style="background:#f9fafb;padding:20px;border:1px solid #e5e7eb;
                  border-top:none;border-radius:0 0 8px 8px;">
        <p style="font-size:15px;color:#374151;margin:0 0 16px;">{summary}</p>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <thead>
            <tr style="background:#f3f4f6;">
              <th style="padding:8px 10px;text-align:left;font-weight:600;color:#6b7280;">Title</th>
              <th style="padding:8px 10px;text-align:center;font-weight:600;color:#6b7280;">Type</th>
              <th style="padding:8px 10px;text-align:center;font-weight:600;color:#6b7280;">Voice</th>
              <th style="padding:8px 10px;text-align:right;font-weight:600;color:#6b7280;">Size</th>
            </tr>
          </thead>
          <tbody>
            {rows_html}
          </tbody>
        </table>
        <div style="margin-top:20px;text-align:center;">
          <a href="https://dreamvalley.app/analytics"
             style="display:inline-block;padding:12px 28px;background:linear-gradient(135deg,#8b5cf6,#6366f1);
                    color:#fff;text-decoration:none;border-radius:8px;font-weight:600;font-size:14px;">
            Open Clips Dashboard &rarr;
          </a>
        </div>
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0 12px;" />
        <p style="font-size:12px;color:#9ca3af;">
          Dream Valley Clips Pipeline &middot;
          <a href="https://dreamvalley.app" style="color:#6366f1;">dreamvalley.app</a>
        </p>
      </div>
    </div>
    """
    return html


def send_clips_notification(clips_info: list, elapsed: float = 0) -> bool:
    """Send clips-ready email notification. Returns True on success."""
    if not RESEND_API_KEY:
        print("  WARNING: RESEND_API_KEY not set — skipping clips email")
        return False

    if not clips_info:
        print("  No clips to notify about — skipping email")
        return False

    date_str = datetime.now().strftime("%Y-%m-%d")
    count = len(clips_info)
    subject = f"[CLIPS] {count} new clip{'s' if count != 1 else ''} ready — {date_str}"

    html = _build_clips_html(clips_info, elapsed)

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
            print(f"  Clips email sent: {subject}")
            return True
        else:
            print(f"  WARNING: Clips email failed ({resp.status_code}): {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  WARNING: Clips email notification failed: {e}")
        return False


# ── Standalone test ───────────────────────────────────────────────────
if __name__ == "__main__":
    if "--test" in sys.argv:
        test_state = {
            "status": "completed",
            "generated_ids": ["test-001", "test-002", "test-003"],
            "generated_titles": ["Test Story: The Friendly Cloud", "Test Poem: Starlight Whisper", "Test Lullaby: Moonlight Dreams"],
            "generated_stories": 1,
            "generated_poems": 1,
            "generated_lullabies": 1,
            "qa_passed": ["test-001", "test-002"],
            "qa_failed": [],
            "covers_generated": ["test-001"],
            "covers_failed": ["test-002"],
            "covers_generated_titles": ["Test Story: The Friendly Cloud"],
            "covers_failed_titles": ["Test Poem: Starlight Whisper"],
            "cost_this_run": "$1.07",
            "cost_modal": "$0.53 (40.2 GPU-min)",
            "cost_gcp_daily": "$0.54",
            "cost_monthly": "~$32.03/mo est. (GCP $16.13 + Modal ~$15.90)",
            "disk_info": "Audio: 304 files (1.2 GB), Covers: 12 SVGs",
        }
        ok = send_pipeline_notification(test_state, "", 325.7)
        sys.exit(0 if ok else 1)
    elif "--test-qa" in sys.argv:
        # Send QA email using the latest QA report on disk
        test_state = {
            "qa_passed": ["gen-5232e740399d"],
            "qa_failed": [],
            "step_deploy_prod": "done",
        }
        ok = send_qa_notification(test_state)
        sys.exit(0 if ok else 1)
    elif "--test-clips" in sys.argv:
        test_clips = [
            {"title": "Luna and the Lanterns of Whispering Hollow", "voice": "female_1", "contentType": "story", "fileSize": 3800000, "filename": "gen-1234_female_1_clip.mp4"},
            {"title": "Twinkle Dream", "voice": "asmr", "contentType": "poem", "fileSize": 2900000, "filename": "gen-5678_asmr_clip.mp4"},
            {"title": "Bella and the Starlight Window", "voice": "male_2", "contentType": "song", "fileSize": 3500000, "filename": "gen-3683_male_2_clip.mp4"},
            {"title": "The Sleepy Cloud", "voice": "female_1", "contentType": "story", "fileSize": 4100000, "filename": "gen-9abc_female_1_clip.mp4"},
            {"title": "Sailing to Dreamland", "voice": "female_1", "contentType": "song", "fileSize": 3200000, "filename": "gen-def0_female_1_clip.mp4"},
        ]
        ok = send_clips_notification(test_clips, elapsed=2052.3)
        sys.exit(0 if ok else 1)
    else:
        print("Usage: python3 scripts/pipeline_notify.py --test | --test-qa | --test-clips")
