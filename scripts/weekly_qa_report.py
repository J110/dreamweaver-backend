#!/usr/bin/env python3
"""Weekly Hindi QA aggregation report.

Reads `qa_changes` from every Hindi item created in the last 7 days and
emits an HTML email summarising:

  - Total items generated (per type)
  - % that needed Groq critic intervention (vs went straight from
    Mistral → audio render)
  - Top fix categories (the rules Groq is most often patching)
  - Pass-overrides (validator-vs-critic disagreements flagged for review)

The fix histogram is the highest-leverage signal: rules Groq fixes most
often = rules the Mistral prompt isn't steering hard enough on.

Schedule: Monday 09:00 UTC (after Sunday's daily run).

Cron entry on prod:
    0 9 * * 1  cd /opt/dreamweaver-backend && python3 scripts/weekly_qa_report.py >> logs/weekly_qa.log 2>&1
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass


def load_recent_hi_items(days: int = 7) -> list[dict]:
    """All Hindi content items created in the last N days (from seed)."""
    cj = BASE_DIR / "seed_output" / "content.json"
    if not cj.exists():
        return []
    data = json.loads(cj.read_text())
    items = data["items"] if isinstance(data, dict) else data
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    return [
        i for i in items
        if i.get("lang") == "hi"
        and (i.get("created_at") or "") >= cutoff
    ]


def _bucket_fix_summary(s: str) -> str:
    """Map a free-form 'summary_of_changes' string to a coarse category
    so we can count similar fixes together."""
    sl = s.lower()
    if "onomatopoeia" in sl or any(x in sl for x in ("sarr", "tap tap", "chhap", "gunghun", "khat khat")):
        return "Added onomatopoeia"
    if "dialogue" in sl and ("reformat" in sl or "name:" in sl or "uppercase" in sl):
        return "Reformatted embedded dialogue → NAME: form"
    if "[breathe]" in sl or "breathe tag" in sl:
        return "Added [BREATHE] tag(s)"
    if "[music]" in sl or "music swell" in sl:
        return "Added [MUSIC] swell(s)"
    if "[phrase]" in sl:
        return "Added/wrapped [PHRASE] tag(s)"
    if "[pause" in sl:
        return "Added [PAUSE] tag(s)"
    if "morals" in sl:
        return "Filled missing morals"
    if "categories" in sl:
        return "Filled missing categories"
    if "conversational" in sl or any(m in sl for m in (" na ", " toh ", "pata hai")):
        return "Added conversational marker(s)"
    if "diversityfingerprint" in sl or "fingerprint" in sl:
        return "Filled diversityFingerprint key(s)"
    return f"Other: {s[:60]}"


def build_report(items: list[dict], days: int) -> dict:
    by_type = Counter(i.get("type", "?") for i in items)
    fixed_items = [i for i in items if i.get("qa_changes", {}).get("action") == "fix"]
    overrides = [i for i in items if i.get("qa_changes", {}).get("action") == "pass_override"]

    fix_buckets: Counter = Counter()
    for it in fixed_items:
        for change in (it.get("qa_changes", {}).get("summary_of_changes") or []):
            fix_buckets[_bucket_fix_summary(change)] += 1

    total = len(items)
    return {
        "window_days": days,
        "total_items": total,
        "by_type": dict(by_type),
        "fixed_count": len(fixed_items),
        "fixed_pct": round(100 * len(fixed_items) / total, 1) if total else 0,
        "override_count": len(overrides),
        "override_details": [
            {
                "id": o.get("id"),
                "type": o.get("type"),
                "validator_errors": o.get("qa_changes", {}).get("validator_errors", [])[:5],
                "justification": o.get("qa_changes", {}).get("justification"),
            }
            for o in overrides
        ],
        "top_fixes": fix_buckets.most_common(8),
    }


def render_html(report: dict) -> str:
    rows_type = "".join(
        f"<tr><td>{t}</td><td>{n}</td></tr>"
        for t, n in sorted(report["by_type"].items())
    )
    rows_fixes = "".join(
        f"<tr><td>{cat}</td><td>{n}</td></tr>"
        for cat, n in report["top_fixes"]
    ) or "<tr><td colspan='2'>(no fixes — Groq didn't run or wasn't needed)</td></tr>"
    overrides_html = ""
    for o in report["override_details"]:
        overrides_html += (
            f"<li><strong>{o['id']}</strong> ({o['type']})<br>"
            f"<em>justification:</em> {o['justification']}<br>"
            f"<em>validator flagged:</em> {', '.join(e[:80] for e in o['validator_errors'])}</li>"
        )
    if not overrides_html:
        overrides_html = "<li>(none — no validator-vs-critic disagreements)</li>"

    return f"""\
<html><body style="font-family:system-ui,Arial,sans-serif;max-width:720px;margin:24px auto;color:#222;">
<h2 style="margin:0 0 8px">Hindi Pipeline — Weekly QA Report</h2>
<p style="color:#666;margin:0 0 24px">Last {report['window_days']} days · {report['total_items']} items generated</p>

<h3>Items by type</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
<tr><th align=left>Type</th><th align=left>Count</th></tr>
{rows_type}
</table>

<h3 style="margin-top:24px">Critic fix rate</h3>
<p><strong>{report['fixed_count']} / {report['total_items']}</strong> items needed a Groq fix
({report['fixed_pct']}%). Lower is better — high fix rates mean the Mistral prompt
isn't steering hard enough on those rules.</p>

<h3>Top fix categories</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
<tr><th align=left>Fix category</th><th align=left>Count</th></tr>
{rows_fixes}
</table>
<p style="color:#666;font-size:12px">Rules appearing repeatedly here are candidates
for prompt strengthening in the next iteration. Fixes Groq makes consistently
should be moved upstream into Mistral's prompt.</p>

<h3 style="margin-top:24px">Pass-overrides ({report['override_count']})</h3>
<p style="color:#666;font-size:12px">Cases where Groq disagreed with the regex validator
and shipped anyway. Audit each to confirm the validator was wrong (false positive)
vs Groq rationalizing a real failure.</p>
<ul>{overrides_html}</ul>

<hr style="margin:32px 0;border:none;border-top:1px solid #ddd;">
<p style="color:#999;font-size:12px">Generated {datetime.now().strftime('%Y-%m-%d %H:%M UTC')} ·
Dream Valley Hindi Daily Pipeline</p>
</body></html>"""


def send_email(html: str, subject: str) -> None:
    api_key = os.getenv("RESEND_API_KEY", "")
    if not api_key:
        print("RESEND_API_KEY missing — printing HTML to stdout instead")
        print(html)
        return
    import httpx
    r = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "from": "Dream Valley Pipeline <support@dreamvalley.app>",
            "to": "mohan.anmol@gmail.com",
            "subject": subject,
            "html": html,
        },
        timeout=30,
    )
    if r.status_code in (200, 202):
        print(f"sent: {r.json().get('id', '(no id)')}")
    else:
        print(f"send failed {r.status_code}: {r.text[:300]}")


def main():
    items = load_recent_hi_items(days=7)
    report = build_report(items, days=7)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    html = render_html(report)
    subject = (
        f"[Hindi QA] Weekly · {report['total_items']} items · "
        f"{report['fixed_pct']}% fix rate · {report['override_count']} overrides"
    )
    send_email(html, subject)


if __name__ == "__main__":
    main()
