"""
Analytics API — event ingestion, daily aggregation, and dashboard endpoints.

Public endpoint for event ingestion (no auth).
Authenticated endpoints (BLOG_SECRET_KEY) for dashboard queries and admin actions.
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Header, Request, Query

from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

DB_PATH = Path("data/analytics.db")


# ── Database helpers ──────────────────────────────────────────────────


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_analytics_db():
    """Create tables and indexes. Call once on startup."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT NOT NULL,
            user_id TEXT NOT NULL,
            session_id TEXT,
            username TEXT,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            payload TEXT,
            device TEXT,
            url TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
        CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
        CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
        CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
        CREATE INDEX IF NOT EXISTS idx_events_content ON events(
            json_extract(payload, '$.contentId')
        );

        CREATE TABLE IF NOT EXISTS daily_metrics (
            date TEXT NOT NULL,
            metric TEXT NOT NULL,
            dimension TEXT DEFAULT '',
            value REAL NOT NULL,
            PRIMARY KEY (date, metric, dimension)
        );
    """)

    # Migration: add username column if missing (for existing DBs)
    cursor = conn.execute("PRAGMA table_info(events)")
    columns = [row[1] for row in cursor.fetchall()]
    if "username" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN username TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_username ON events(username)")
        logger.info("Migrated: added username column to events table")
    else:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_username ON events(username)")

    conn.close()
    logger.info("Analytics SQLite database initialized at %s", DB_PATH)


# ── Auth ──────────────────────────────────────────────────────────────


def verify_analytics_key(authorization: Optional[str] = Header(None)):
    """Verify Bearer token against BLOG_SECRET_KEY env var."""
    key = os.getenv("BLOG_SECRET_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="Analytics secret key not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing or invalid")
    token = authorization.replace("Bearer ", "")
    if token != key:
        raise HTTPException(status_code=401, detail="Invalid key")


# ── Event Ingestion (public) ──────────────────────────────────────────


@router.post("/events")
async def ingest_events(request: Request):
    """Receive batched analytics events. No auth required."""
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "Invalid JSON"}

    events = body.get("events", [])
    if not events:
        return {"status": "ok", "count": 0}

    conn = get_db()
    try:
        for event in events:
            payload = event.get("payload", {})
            timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())
            date = timestamp[:10]

            conn.execute(
                """INSERT INTO events (event, user_id, session_id, username, timestamp, date, payload, device, url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.get("event", "unknown"),
                    event.get("userId", "anonymous"),
                    event.get("sessionId"),
                    event.get("username"),
                    timestamp,
                    date,
                    json.dumps(payload) if isinstance(payload, dict) else str(payload),
                    payload.get("device") if isinstance(payload, dict) else None,
                    payload.get("url") if isinstance(payload, dict) else None,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "count": len(events)}


# ── Aggregation ───────────────────────────────────────────────────────


def aggregate_daily_metrics(date: str):
    """Compute and store daily metrics for a given date (YYYY-MM-DD)."""
    conn = get_db()
    c = conn.cursor()
    metrics = []

    # --- USER METRICS ---
    c.execute("SELECT COUNT(DISTINCT user_id) FROM events WHERE date = ?", (date,))
    metrics.append((date, "dau", "", c.fetchone()[0]))

    c.execute("SELECT COUNT(DISTINCT user_id) FROM events WHERE event = 'signup' AND date = ?", (date,))
    metrics.append((date, "new_users", "", c.fetchone()[0]))

    c.execute("SELECT COUNT(DISTINCT session_id) FROM events WHERE date = ?", (date,))
    metrics.append((date, "sessions", "", c.fetchone()[0]))

    c.execute(
        "SELECT AVG(json_extract(payload, '$.durationMs')) FROM events WHERE event = 'session_end' AND date = ?",
        (date,),
    )
    avg_dur = c.fetchone()[0]
    metrics.append((date, "avg_session_duration_ms", "", avg_dur or 0))

    # Device breakdown
    c.execute(
        "SELECT device, COUNT(DISTINCT user_id) FROM events WHERE date = ? AND device IS NOT NULL GROUP BY device",
        (date,),
    )
    for device, count in c.fetchall():
        metrics.append((date, "users_by_device", device or "unknown", count))

    # Referrer breakdown
    c.execute(
        """SELECT json_extract(payload, '$.referrer'), COUNT(*)
           FROM events WHERE event = 'app_open' AND date = ?
           GROUP BY json_extract(payload, '$.referrer')""",
        (date,),
    )
    for referrer, count in c.fetchall():
        metrics.append((date, "opens_by_referrer", referrer or "direct", count))

    # --- CONTENT METRICS ---
    c.execute("SELECT COUNT(*) FROM events WHERE event = 'play_start' AND date = ?", (date,))
    starts = c.fetchone()[0]
    metrics.append((date, "plays_started", "", starts))

    c.execute("SELECT COUNT(*) FROM events WHERE event = 'play_complete' AND date = ?", (date,))
    completes = c.fetchone()[0]
    metrics.append((date, "plays_completed", "", completes))

    rate = (completes / starts * 100) if starts > 0 else 0
    metrics.append((date, "completion_rate", "", round(rate, 1)))

    # Plays by content type
    c.execute(
        """SELECT json_extract(payload, '$.contentType'), COUNT(*)
           FROM events WHERE event = 'play_start' AND date = ?
           GROUP BY json_extract(payload, '$.contentType')""",
        (date,),
    )
    for ctype, count in c.fetchall():
        metrics.append((date, "plays_by_type", ctype or "unknown", count))

    # Plays by age group
    c.execute(
        """SELECT json_extract(payload, '$.ageGroup'), COUNT(*)
           FROM events WHERE event = 'play_start' AND date = ?
           GROUP BY json_extract(payload, '$.ageGroup')""",
        (date,),
    )
    for age, count in c.fetchall():
        metrics.append((date, "plays_by_age", age or "unknown", count))

    # Top stories
    c.execute(
        """SELECT json_extract(payload, '$.contentId'), COUNT(*) as plays
           FROM events WHERE event = 'play_start' AND date = ?
           GROUP BY json_extract(payload, '$.contentId')
           ORDER BY plays DESC LIMIT 20""",
        (date,),
    )
    for content_id, count in c.fetchall():
        metrics.append((date, "top_content", content_id or "unknown", count))

    # Plays by voice
    c.execute(
        """SELECT json_extract(payload, '$.voice'), COUNT(*)
           FROM events WHERE event = 'play_start' AND date = ?
           GROUP BY json_extract(payload, '$.voice')""",
        (date,),
    )
    for voice, count in c.fetchall():
        metrics.append((date, "plays_by_voice", voice or "unknown", count))

    # Avg abandon position
    c.execute(
        "SELECT AVG(json_extract(payload, '$.percentComplete')) FROM events WHERE event = 'play_abandon' AND date = ?",
        (date,),
    )
    avg_abandon = c.fetchone()[0]
    metrics.append((date, "avg_abandon_percent", "", avg_abandon or 0))

    # Abandons by phase
    c.execute(
        """SELECT json_extract(payload, '$.phase'), COUNT(*) as abandons
           FROM events WHERE event = 'play_abandon' AND date = ?
           AND json_extract(payload, '$.phase') IS NOT NULL
           GROUP BY json_extract(payload, '$.phase')
           ORDER BY abandons DESC""",
        (date,),
    )
    for phase, count in c.fetchall():
        metrics.append((date, "abandons_by_phase", str(phase), count))

    # --- ENGAGEMENT ---
    c.execute("SELECT COUNT(*) FROM events WHERE event = 'like' AND date = ?", (date,))
    metrics.append((date, "likes", "", c.fetchone()[0]))

    c.execute("SELECT COUNT(*) FROM events WHERE event = 'share' AND date = ?", (date,))
    metrics.append((date, "shares", "", c.fetchone()[0]))

    c.execute("SELECT COUNT(*) FROM events WHERE event = 'blog_view' AND date = ?", (date,))
    metrics.append((date, "blog_views", "", c.fetchone()[0]))

    # --- SLEEP SUCCESS RATE ---
    total = starts
    c.execute(
        """SELECT COUNT(*) FROM events
           WHERE event = 'play_abandon' AND date = ?
           AND json_extract(payload, '$.phase') = 3""",
        (date,),
    )
    phase3_abandons = c.fetchone()[0]

    c.execute(
        """SELECT COUNT(*) FROM events
           WHERE event = 'play_abandon' AND date = ?
           AND json_extract(payload, '$.percentComplete') >= 80""",
        (date,),
    )
    late_abandons = c.fetchone()[0]

    success = completes + max(phase3_abandons, late_abandons)
    sleep_rate = (success / total * 100) if total > 0 else 0
    metrics.append((date, "sleep_success_rate", "", round(sleep_rate, 1)))

    # --- WRITE ALL METRICS ---
    conn.executemany(
        """INSERT OR REPLACE INTO daily_metrics (date, metric, dimension, value)
           VALUES (?, ?, ?, ?)""",
        metrics,
    )
    conn.commit()
    conn.close()
    return len(metrics)


# ── Retention ─────────────────────────────────────────────────────────


def compute_retention(cohort_date: str, period_days: int) -> float:
    conn = get_db()
    c = conn.cursor()

    target_date = (datetime.strptime(cohort_date, "%Y-%m-%d") + timedelta(days=period_days)).strftime("%Y-%m-%d")

    c.execute("SELECT DISTINCT user_id FROM events WHERE date = ?", (cohort_date,))
    cohort_users = [row[0] for row in c.fetchall()]

    if not cohort_users:
        conn.close()
        return 0.0

    placeholders = ",".join("?" * len(cohort_users))
    c.execute(
        f"SELECT COUNT(DISTINCT user_id) FROM events WHERE date = ? AND user_id IN ({placeholders})",
        (target_date, *cohort_users),
    )
    retained = c.fetchone()[0]
    conn.close()
    return round(retained / len(cohort_users) * 100, 1)


def compute_retention_table(start_date: str, num_cohorts: int = 8, periods=None):
    if periods is None:
        periods = [1, 3, 7, 14, 30]
    table = []
    for i in range(num_cohorts):
        cohort_date = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=i * 7)).strftime("%Y-%m-%d")
        row = {"cohort": cohort_date}
        for period in periods:
            row[f"day_{period}"] = compute_retention(cohort_date, period)
        table.append(row)
    return table


# ── Aggregation endpoint ──────────────────────────────────────────────


@router.post("/aggregate")
async def trigger_aggregation(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    verify_analytics_key(authorization)

    try:
        body = await request.json()
    except Exception:
        body = {}

    date = body.get("date")
    if not date:
        date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    count = aggregate_daily_metrics(date)
    return {"status": "ok", "date": date, "metrics_computed": count}


@router.post("/cleanup")
async def trigger_cleanup(authorization: Optional[str] = Header(None)):
    verify_analytics_key(authorization)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM events WHERE date < ?", (cutoff,))
    deleted_count = c.fetchone()[0]
    conn.execute("DELETE FROM events WHERE date < ?", (cutoff,))
    conn.execute("VACUUM")
    conn.commit()
    conn.close()
    return {"status": "ok", "cutoff": cutoff, "events_deleted": deleted_count}


# ── Dashboard API endpoints ──────────────────────────────────────────


def _date_range_params(from_date: Optional[str], to_date: Optional[str]):
    if not to_date:
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not from_date:
        from_date = (datetime.strptime(to_date, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
    return from_date, to_date


def _query_metrics(conn, from_date: str, to_date: str, metric_names: list) -> dict:
    """Query daily_metrics for a list of metric names in a date range."""
    placeholders = ",".join("?" * len(metric_names))
    rows = conn.execute(
        f"""SELECT date, metric, dimension, value FROM daily_metrics
            WHERE date >= ? AND date <= ? AND metric IN ({placeholders})
            ORDER BY date""",
        (from_date, to_date, *metric_names),
    ).fetchall()

    result = {}
    for row in rows:
        date, metric, dimension, value = row["date"], row["metric"], row["dimension"], row["value"]
        if date not in result:
            result[date] = {}
        if dimension:
            if metric not in result[date]:
                result[date][metric] = {}
            result[date][metric][dimension] = value
        else:
            result[date][metric] = value
    return result


@router.get("/overview")
async def dashboard_overview(
    authorization: Optional[str] = Header(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    verify_analytics_key(authorization)
    fr, to = _date_range_params(from_date, to_date)

    conn = get_db()
    data = _query_metrics(conn, fr, to, [
        "dau", "new_users", "sessions", "avg_session_duration_ms",
        "plays_started", "plays_completed", "completion_rate",
        "likes", "shares", "sleep_success_rate",
    ])

    daily = []
    for date in sorted(data.keys()):
        d = data[date]
        daily.append({
            "date": date,
            "dau": d.get("dau", 0),
            "newUsers": d.get("new_users", 0),
            "sessions": d.get("sessions", 0),
            "avgSessionDurationMin": round((d.get("avg_session_duration_ms", 0) or 0) / 60000, 1),
            "playsStarted": d.get("plays_started", 0),
            "playsCompleted": d.get("plays_completed", 0),
            "completionRate": d.get("completion_rate", 0),
            "likes": d.get("likes", 0),
            "shares": d.get("shares", 0),
            "sleepSuccessRate": d.get("sleep_success_rate", 0),
        })

    totals = {}
    if daily:
        totals = {
            "totalUsers": sum(d["dau"] for d in daily),
            "totalNewUsers": sum(d["newUsers"] for d in daily),
            "totalSessions": sum(d["sessions"] for d in daily),
            "totalPlays": sum(d["playsStarted"] for d in daily),
            "avgCompletionRate": round(sum(d["completionRate"] for d in daily) / len(daily), 1),
            "avgDau": round(sum(d["dau"] for d in daily) / len(daily), 1),
            "avgSleepSuccessRate": round(sum(d["sleepSuccessRate"] for d in daily) / len(daily), 1),
        }

    conn.close()
    return {"dateRange": {"from": fr, "to": to}, "daily": daily, "totals": totals}


@router.get("/users")
async def dashboard_users(
    authorization: Optional[str] = Header(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    verify_analytics_key(authorization)
    fr, to = _date_range_params(from_date, to_date)

    conn = get_db()
    data = _query_metrics(conn, fr, to, ["dau", "new_users", "users_by_device"])

    daily = []
    for date in sorted(data.keys()):
        d = data[date]
        daily.append({
            "date": date,
            "dau": d.get("dau", 0),
            "newUsers": d.get("new_users", 0),
        })

    # Aggregate device breakdown
    devices = {}
    for date in data:
        dev = data[date].get("users_by_device", {})
        if isinstance(dev, dict):
            for d, v in dev.items():
                devices[d] = devices.get(d, 0) + v

    # Total unique users ever
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT user_id) FROM events")
    total_unique = c.fetchone()[0]

    conn.close()
    return {
        "dateRange": {"from": fr, "to": to},
        "daily": daily,
        "devices": devices,
        "totalUniqueUsers": total_unique,
    }


@router.get("/acquisition")
async def dashboard_acquisition(
    authorization: Optional[str] = Header(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    verify_analytics_key(authorization)
    fr, to = _date_range_params(from_date, to_date)

    conn = get_db()
    data = _query_metrics(conn, fr, to, ["opens_by_referrer"])

    # Aggregate referrers across dates
    referrers = {}
    for date in data:
        ref = data[date].get("opens_by_referrer", {})
        if isinstance(ref, dict):
            for source, count in ref.items():
                referrers[source] = referrers.get(source, 0) + count

    conn.close()
    return {"dateRange": {"from": fr, "to": to}, "referrers": referrers}


@router.get("/content")
async def dashboard_content(
    authorization: Optional[str] = Header(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    verify_analytics_key(authorization)
    fr, to = _date_range_params(from_date, to_date)

    conn = get_db()
    data = _query_metrics(conn, fr, to, [
        "plays_by_type", "plays_by_age", "top_content", "plays_by_voice",
        "avg_abandon_percent", "abandons_by_phase", "sleep_success_rate",
        "plays_started", "plays_completed", "completion_rate",
    ])

    # Aggregate dimensional metrics
    by_type = {}
    by_age = {}
    top_content = {}
    by_voice = {}
    by_phase = {}

    for date in data:
        d = data[date]
        for key, agg in [("plays_by_type", by_type), ("plays_by_age", by_age),
                         ("top_content", top_content), ("plays_by_voice", by_voice),
                         ("abandons_by_phase", by_phase)]:
            vals = d.get(key, {})
            if isinstance(vals, dict):
                for k, v in vals.items():
                    agg[k] = agg.get(k, 0) + v

    # Sort top content
    top_sorted = sorted(top_content.items(), key=lambda x: x[1], reverse=True)[:20]

    # Resolve content titles
    top_with_titles = []
    try:
        from app.services.local_store import get_local_store
        store = get_local_store()
        content_col = store.collection("content")
        for content_id, plays in top_sorted:
            doc = content_col.document(content_id).get()
            title = doc.to_dict().get("title", content_id) if doc.exists else content_id
            top_with_titles.append({"id": content_id, "title": title, "plays": plays})
    except Exception:
        top_with_titles = [{"id": cid, "title": cid, "plays": p} for cid, p in top_sorted]

    # Average abandon percent across period
    abandon_values = [d.get("avg_abandon_percent", 0) for d in data.values() if isinstance(d.get("avg_abandon_percent"), (int, float)) and d.get("avg_abandon_percent", 0) > 0]
    avg_abandon = round(sum(abandon_values) / len(abandon_values), 1) if abandon_values else 0

    # Average sleep success rate
    sleep_values = [d.get("sleep_success_rate", 0) for d in data.values() if isinstance(d.get("sleep_success_rate"), (int, float))]
    avg_sleep = round(sum(sleep_values) / len(sleep_values), 1) if sleep_values else 0

    conn.close()
    return {
        "dateRange": {"from": fr, "to": to},
        "playsByType": by_type,
        "playsByAge": by_age,
        "topContent": top_with_titles,
        "playsByVoice": by_voice,
        "abandonsByPhase": by_phase,
        "avgAbandonPercent": avg_abandon,
        "sleepSuccessRate": avg_sleep,
    }


@router.get("/retention")
async def dashboard_retention(
    authorization: Optional[str] = Header(None),
    start_date: Optional[str] = Query(None),
):
    verify_analytics_key(authorization)
    if not start_date:
        start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    table = compute_retention_table(start_date)
    return {"startDate": start_date, "cohorts": table}


@router.get("/engagement")
async def dashboard_engagement(
    authorization: Optional[str] = Header(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    verify_analytics_key(authorization)
    fr, to = _date_range_params(from_date, to_date)

    conn = get_db()
    data = _query_metrics(conn, fr, to, ["likes", "shares", "blog_views"])

    daily = []
    for date in sorted(data.keys()):
        d = data[date]
        daily.append({
            "date": date,
            "likes": d.get("likes", 0),
            "shares": d.get("shares", 0),
            "blogViews": d.get("blog_views", 0),
        })

    conn.close()
    return {"dateRange": {"from": fr, "to": to}, "daily": daily}


@router.get("/realtime")
async def dashboard_realtime(authorization: Optional[str] = Header(None)):
    verify_analytics_key(authorization)

    five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT user_id) FROM events WHERE timestamp > ?", (five_min_ago,))
    active = c.fetchone()[0]
    conn.close()

    return {"activeUsers": active, "windowMinutes": 5}


@router.get("/funnel")
async def dashboard_funnel(
    authorization: Optional[str] = Header(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """Conversion funnel: visit → onboarding → play → 1-min listen."""
    verify_analytics_key(authorization)
    fr, to = _date_range_params(from_date, to_date)

    conn = get_db()
    c = conn.cursor()

    # Step 1: Website visits (unique users with app_open)
    c.execute(
        "SELECT COUNT(DISTINCT user_id) FROM events WHERE event = 'app_open' AND date >= ? AND date <= ?",
        (fr, to),
    )
    visits = c.fetchone()[0]

    # Step 2: Onboarding complete
    c.execute(
        "SELECT COUNT(DISTINCT user_id) FROM events WHERE event = 'onboarding_complete' AND date >= ? AND date <= ?",
        (fr, to),
    )
    onboarded = c.fetchone()[0]

    # Step 3: Audio listen (play_start)
    c.execute(
        "SELECT COUNT(DISTINCT user_id) FROM events WHERE event = 'play_start' AND date >= ? AND date <= ?",
        (fr, to),
    )
    listeners = c.fetchone()[0]

    # Step 4: Listened >= 1 min
    c.execute(
        "SELECT COUNT(DISTINCT user_id) FROM events WHERE event = 'play_1min' AND date >= ? AND date <= ?",
        (fr, to),
    )
    listened_1min = c.fetchone()[0]

    conn.close()

    steps = [
        {"label": "Website Visit", "count": visits},
        {"label": "Onboarding Complete", "count": onboarded},
        {"label": "Audio Listen", "count": listeners},
        {"label": "Listened 1+ min", "count": listened_1min},
    ]

    return {"dateRange": {"from": fr, "to": to}, "steps": steps}


@router.get("/users-activity")
async def dashboard_users_activity(
    authorization: Optional[str] = Header(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """Per-user activity breakdown: sessions, plays, time spent, last seen."""
    verify_analytics_key(authorization)
    fr, to = _date_range_params(from_date, to_date)

    conn = get_db()
    rows = conn.execute(
        """
        SELECT
            user_id,
            MAX(username) AS username,
            COUNT(DISTINCT session_id) AS sessions,
            COUNT(CASE WHEN event = 'play_start' THEN 1 END) AS plays,
            COUNT(CASE WHEN event = 'play_complete' THEN 1 END) AS completions,
            COUNT(*) AS total_events,
            MIN(timestamp) AS first_seen,
            MAX(timestamp) AS last_seen,
            MAX(device) AS device
        FROM events
        WHERE date >= ? AND date <= ?
        GROUP BY user_id
        ORDER BY last_seen DESC
        """,
        (fr, to),
    ).fetchall()

    users = []
    for r in rows:
        users.append({
            "userId": r["user_id"],
            "username": r["username"],
            "sessions": r["sessions"],
            "plays": r["plays"],
            "completions": r["completions"],
            "totalEvents": r["total_events"],
            "firstSeen": r["first_seen"],
            "lastSeen": r["last_seen"],
            "device": r["device"],
        })

    conn.close()
    return {"dateRange": {"from": fr, "to": to}, "users": users}
