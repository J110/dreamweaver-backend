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

        CREATE TABLE IF NOT EXISTS health_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            hour TEXT NOT NULL,
            cpu_load_1m REAL,
            cpu_load_5m REAL,
            memory_used_pct REAL,
            memory_used_mb REAL,
            memory_total_mb REAL,
            disk_used_pct REAL,
            disk_used_gb REAL,
            disk_total_gb REAL,
            request_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            latency_p50 REAL,
            latency_p95 REAL,
            latency_p99 REAL,
            latency_avg REAL,
            health_score INTEGER,
            health_components TEXT,
            db_size_mb REAL
        );
        CREATE INDEX IF NOT EXISTS idx_health_ts ON health_snapshots(timestamp);
        CREATE INDEX IF NOT EXISTS idx_health_hour ON health_snapshots(hour);
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

    # Step 2: App download click
    c.execute(
        "SELECT COUNT(DISTINCT user_id) FROM events WHERE event = 'app_download_click' AND date >= ? AND date <= ?",
        (fr, to),
    )
    download_clicks = c.fetchone()[0]

    # Step 3: Onboarding complete
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
        {"label": "App Download Click", "count": download_clicks},
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
          AND user_id IN (
              SELECT DISTINCT user_id FROM events
              WHERE username IS NOT NULL AND username != ''
          )
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


def _format_uptime(seconds):
    """Format seconds into human-readable uptime string."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _describe_error(method, path, status):
    """Return a human-readable description for an API error."""
    # Specific path + status combos
    p = path.lower()
    if "auth/signup" in p and status == 400:
        return "Signup attempt with invalid or already-registered email"
    if "auth/signup" in p and status == 422:
        return "Signup form submitted with missing fields"
    if "auth" in p and status == 401:
        return "Login attempt with wrong credentials"
    if "/content" in p and status == 422:
        return "Content page loaded without required filters (normal on refresh)"
    if "/content" in p and status == 404:
        return "Requested story or content not found"
    if "/blog" in p and status == 404:
        return "Blog post not found"
    if "/analytics" in p and status == 401:
        return "Dashboard access attempt with invalid key"

    # Generic by status code
    descriptions = {
        400: "Bad request — invalid or missing input data",
        401: "Unauthorized — missing or invalid credentials",
        403: "Access denied",
        404: "Page or resource not found",
        405: "HTTP method not allowed for this endpoint",
        422: "Validation failed — request had missing or invalid fields",
        429: "Rate limited — too many requests from one user",
        500: "Server error — something crashed while processing",
        502: "Bad gateway — server temporarily unreachable",
        503: "Server overloaded or restarting",
        504: "Gateway timeout — request took too long",
    }
    return descriptions.get(status, f"HTTP {status} error")


@router.get("/server-health")
async def dashboard_server_health(
    authorization: Optional[str] = Header(None),
    hours: int = Query(24, description="Hours of history to return"),
):
    """Server health: system stats, latency, errors, health score, trends."""
    verify_analytics_key(authorization)

    import time as _time
    from app.services.health_collector import (
        get_uptime_seconds, read_system_metrics, get_db_size_mb,
        compute_request_stats, compute_health_score,
    )
    from app.middleware.timing import get_request_buffer

    # --- Current snapshot (live) ---
    sys_metrics = read_system_metrics()
    uptime_seconds = get_uptime_seconds()
    db_size = get_db_size_mb()

    # Live latency from ring buffer (last 5 minutes)
    buffer, lock = get_request_buffer()
    recent_stats = compute_request_stats(buffer, lock, _time.time() - 300)

    # Live health score
    live_health = compute_health_score(sys_metrics, recent_stats)

    current = {
        "uptimeSeconds": int(uptime_seconds),
        "uptimeHuman": _format_uptime(uptime_seconds),
        "cpuLoad1m": sys_metrics.get("cpu_load_1m"),
        "cpuLoad5m": sys_metrics.get("cpu_load_5m"),
        "memoryUsedPct": sys_metrics.get("memory_used_pct"),
        "memoryUsedMb": sys_metrics.get("memory_used_mb"),
        "memoryTotalMb": sys_metrics.get("memory_total_mb"),
        "diskUsedPct": sys_metrics.get("disk_used_pct"),
        "diskUsedGb": sys_metrics.get("disk_used_gb"),
        "diskTotalGb": sys_metrics.get("disk_total_gb"),
        "dbSizeMb": db_size,
        "latency": recent_stats,
        "healthScore": live_health,
    }

    # --- Peak traffic health (worst score in last 6 hours) ---
    conn = get_db()
    six_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    peak_row = conn.execute("""
        SELECT health_score, health_components, timestamp,
               request_count, latency_p95, cpu_load_1m, memory_used_pct, disk_used_pct
        FROM health_snapshots
        WHERE timestamp >= ?
        ORDER BY health_score ASC
        LIMIT 1
    """, (six_hours_ago,)).fetchone()

    if peak_row and peak_row["health_score"] is not None:
        peak_health = {
            "score": peak_row["health_score"],
            "components": json.loads(peak_row["health_components"]) if peak_row["health_components"] else [],
            "timestamp": peak_row["timestamp"],
            "requestCount": peak_row["request_count"],
        }
        ps = peak_health["score"]
        peak_health["status"] = "green" if ps >= 80 else "yellow" if ps >= 50 else "red"
    else:
        # No snapshots yet — use live score
        peak_health = {
            "score": live_health["score"],
            "status": live_health["status"],
            "components": live_health["components"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "requestCount": recent_stats["request_count"],
        }

    # --- Historical data (5-min snapshots for charts) ---
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = conn.execute("""
        SELECT timestamp, cpu_load_1m, memory_used_pct, disk_used_pct,
               request_count, error_count,
               latency_p50, latency_p95, latency_p99, latency_avg,
               health_score, db_size_mb
        FROM health_snapshots
        WHERE timestamp >= ?
        ORDER BY timestamp
    """, (cutoff,)).fetchall()

    history = []
    for row in rows:
        error_rate = 0
        if row["request_count"] and row["request_count"] > 0:
            error_rate = round(row["error_count"] / row["request_count"] * 100, 1)
        history.append({
            "timestamp": row["timestamp"],
            "cpuLoad": row["cpu_load_1m"],
            "memoryPct": row["memory_used_pct"],
            "diskPct": row["disk_used_pct"],
            "requestCount": row["request_count"],
            "errorCount": row["error_count"],
            "errorRate": error_rate,
            "p50": row["latency_p50"],
            "p95": row["latency_p95"],
            "p99": row["latency_p99"],
            "avgLatency": row["latency_avg"],
            "healthScore": row["health_score"],
            "dbSizeMb": row["db_size_mb"],
        })

    # --- Recent slow requests (from ring buffer, last hour, >500ms) ---
    one_hour_ago = _time.time() - 3600
    with lock:
        recent_slow = sorted(
            [(ts, method, path, status, dur) for ts, method, path, status, dur in buffer
             if ts >= one_hour_ago and dur > 500],
            key=lambda x: -x[4],
        )[:20]

    slow_requests = [{
        "timestamp": datetime.fromtimestamp(r[0], tz=timezone.utc).isoformat(),
        "method": r[1],
        "path": r[2],
        "status": r[3],
        "durationMs": r[4],
    } for r in recent_slow]

    # --- Recent errors (from ring buffer, last hour, 4xx/5xx) ---
    with lock:
        recent_errors = sorted(
            [(ts, method, path, status, dur) for ts, method, path, status, dur in buffer
             if ts >= one_hour_ago and status >= 400],
            key=lambda x: -x[0],
        )[:20]

    error_requests = [{
        "timestamp": datetime.fromtimestamp(r[0], tz=timezone.utc).isoformat(),
        "method": r[1],
        "path": r[2],
        "status": r[3],
        "durationMs": r[4],
        "description": _describe_error(r[1], r[2], r[3]),
        "severity": "error" if r[3] >= 500 else "warning",
    } for r in recent_errors]

    conn.close()

    return {
        "current": current,
        "peakHealth": peak_health,
        "history": history,
        "slowRequests": slow_requests,
        "recentErrors": error_requests,
    }


# ── Diversity Dashboard ──────────────────────────────────────────────

DIVERSITY_SNAPSHOT_PATH = Path("data/diversity_snapshot.json")
CONTENT_JSON_PATH = Path("data/content.json")
AXES_HISTORY_PATH = Path("seed_output/covers_experimental/_axes_history.json")

# Inline dimension configs (mirrored from scripts/diversity.py)
_DIVERSITY_DIMS = {
    "characterType": {"weight": 10, "tier": 1, "hard_rule": True, "values": [
        "land_mammal","bird","sea_creature","insect","reptile_amphibian","human_child",
        "mythical_creature","object_alive","plant_tree","celestial_weather","robot_mechanical"]},
    "setting": {"weight": 10, "tier": 1, "hard_rule": True, "values": [
        "forest_woodland","ocean_water","sky_space","mountain_highland","meadow_field",
        "desert_arid","arctic_polar","cozy_indoor","village_town","city_urban",
        "underground_cave","garden_farm","island_tropical","imaginary_surreal","miniature_world"]},
    "plotShape": {"weight": 3, "tier": 1, "hard_rule": True, "values": [
        "journey_destination","discovery_reveal","lost_and_found","helping_someone",
        "building_growing","transformation","gathering_reunion","pure_observation",
        "routine_ritual","cyclical_seasonal"]},
    "scale": {"weight": 5, "tier": 2, "values": ["tiny_intimate","personal","local_adventure","journey","epic_vast"]},
    "companion": {"weight": 4, "tier": 2, "values": ["solo","duo","group_community","meets_stranger","character_and_environment"]},
    "movement": {"weight": 4, "tier": 2, "values": ["sleeping_resting","sitting_watching","floating_drifting","walking_wandering","flying_swimming","building_making"]},
    "timeOfDay": {"weight": 4, "tier": 2, "values": ["sunset_golden_hour","twilight_blue_hour","deep_night_starlight","late_afternoon","timeless"]},
    "weather": {"weight": 4, "tier": 2, "values": ["clear_calm","gentle_rain","misty_foggy","snowy","warm_breeze","overcast_grey","stormy_distant","magical_atmospheric"]},
    "theme": {"weight": 3, "tier": 3, "values": ["curiosity_wonder","courage","kindness","friendship","patience","creativity","belonging","gratitude","letting_go","self_acceptance","gentleness","rest_stillness"]},
    "characterTrait": {"weight": 3, "tier": 3, "values": ["shy_quiet","bold_adventurous","dreamy_imaginative","kind_nurturing","clumsy_silly","wise_old_soul","anxious_worried","stubborn_determined","lonely_seeking","playful_mischievous"]},
    "magicType": {"weight": 3, "tier": 3, "values": ["glowing_bioluminescent","talking_sentient_world","transformation_metamorphosis","miniaturization","music_sound_magic","weather_magic","dream_imagination_bleed","time_magic","color_magic","no_magic_realistic"]},
    "season": {"weight": 2, "tier": 3, "values": ["spring","summer","autumn","winter","seasonal_transition","seasonless_timeless"]},
    "senseEmphasis": {"weight": 2, "tier": 3, "values": ["visual","auditory","tactile","olfactory","kinesthetic"]},
}

_CHAR_TYPE_MAP = {
    "human": "human_child", "animal": "land_mammal", "bird": "bird",
    "sea_creature": "sea_creature", "insect": "insect", "plant": "plant_tree",
    "celestial": "celestial_weather", "atmospheric": "celestial_weather",
    "mythical": "mythical_creature", "object": "object_alive",
    "alien": "mythical_creature", "robot": "robot_mechanical",
}
_PLOT_MAP = {
    "quest_journey": "journey_destination", "discovery": "discovery_reveal",
    "friendship_bonding": "helping_someone", "transformation": "transformation",
    "problem_solving": "discovery_reveal", "celebration": "gathering_reunion",
}
_THEME_MAP = {
    "dreamy": "rest_stillness", "adventure": "courage", "nature": "curiosity_wonder",
    "ocean": "curiosity_wonder", "animals": "friendship", "fantasy": "curiosity_wonder",
    "space": "curiosity_wonder", "bedtime": "rest_stillness", "friendship": "friendship",
    "mystery": "curiosity_wonder", "science": "curiosity_wonder", "family": "kindness",
    "fairy_tale": "curiosity_wonder",
}

_COVER_AXES = {
    "world_setting": ["deep_ocean","cloud_kingdom","enchanted_forest","snow_landscape","desert_night","cozy_interior","mountain_meadow","space_cosmos","tropical_lagoon","underground_cave","ancient_library","floating_islands"],
    "palette": ["ember_warm","twilight_cool","forest_deep","golden_hour","moonstone","berry_dusk"],
    "composition": ["vast_landscape","intimate_closeup","overhead_canopy","winding_path","circular_nest"],
    "character": ["human_child","small_mammal","aquatic_creature","bird","insect","plant","celestial","atmospheric","mythical_gentle","object","robot_mech","nature_spirit","no_character"],
    "light": ["above","backlit","below","ambient"],
    "texture": ["watercolor_soft","soft_pastel","digital_painterly","paper_cutout"],
    "time": ["early_night","deep_night","eternal_dusk","timeless_indoor"],
}

_ALL_MOODS = ["wired","curious","calm","sad","anxious","angry"]
_MOOD_LABELS = {"wired":"Silly","curious":"Adventure","calm":"Gentle","sad":"Comfort","anxious":"Brave","angry":"Let It Out"}
_AGE_GROUPS = ["0-1","2-5","6-8","9-12"]


def _age_to_group(target_age) -> str:
    if target_age is None: return "unknown"
    try: age = int(target_age)
    except (ValueError, TypeError): return str(target_age)
    if age <= 1: return "0-1"
    elif age <= 5: return "2-5"
    elif age <= 8: return "6-8"
    return "9-12"


def _compute_diversity_report() -> dict:
    """Compute live diversity report from data files."""
    from collections import Counter

    items = []
    if CONTENT_JSON_PATH.exists():
        try: items = json.loads(CONTENT_JSON_PATH.read_text())
        except Exception: pass

    axes_history = []
    if AXES_HISTORY_PATH.exists():
        try: axes_history = json.loads(AXES_HISTORY_PATH.read_text())
        except Exception: pass

    total = len(items) or 1
    type_ctr = Counter(i.get("type", "story") for i in items)
    age_ctr = Counter(_age_to_group(i.get("target_age")) for i in items)

    # Mood
    mood_ctr = Counter()
    mood_by_type, mood_by_age = {}, {}
    for item in items:
        m = item.get("mood") or "none"
        mood_ctr[m] += 1
        ct = item.get("type", "story")
        mood_by_type.setdefault(ct, Counter())[m] += 1
        ag = _age_to_group(item.get("target_age"))
        mood_by_age.setdefault(ag, Counter())[m] += 1

    mood_dist = {}
    for m in _ALL_MOODS + ["none"]:
        c = mood_ctr.get(m, 0)
        mood_dist[m] = {"count": c, "pct": round(c * 100 / total, 1)}

    # Content fingerprints
    fingerprints = []
    for item in items:
        fp = item.get("diversityFingerprint")
        if fp:
            fingerprints.append(fp)
        else:
            legacy = {}
            ct = item.get("lead_character_type")
            if ct and ct in _CHAR_TYPE_MAP: legacy["characterType"] = _CHAR_TYPE_MAP[ct]
            pa = item.get("plot_archetype")
            if pa and pa in _PLOT_MAP: legacy["plotShape"] = _PLOT_MAP[pa]
            th = item.get("theme")
            if th and th in _THEME_MAP: legacy["theme"] = _THEME_MAP[th]
            if legacy: fingerprints.append(legacy)

    dimensions = {}
    for dname, dcfg in _DIVERSITY_DIMS.items():
        vals = dcfg["values"]
        vctr = Counter()
        tagged = 0
        for fp in fingerprints:
            v = fp.get(dname)
            if v: vctr[v] += 1; tagged += 1
        dist = {v: vctr.get(v, 0) for v in vals}
        used = sum(1 for v in vals if vctr.get(v, 0) > 0)
        dimensions[dname] = {
            "weight": dcfg["weight"], "tier": dcfg.get("tier", 3),
            "hardRule": dcfg.get("hard_rule", False), "values": vals,
            "distribution": dist, "coverage": round(used / len(vals), 2) if vals else 0,
            "tagged": tagged,
        }

    gaps = {}
    for dname, dd in dimensions.items():
        missing = [v for v in dd["values"] if dd["distribution"].get(v, 0) == 0]
        if missing: gaps[dname] = missing

    # Covers
    cover_axes = {}
    for axis, vals in _COVER_AXES.items():
        vctr = Counter()
        for entry in axes_history:
            ax = entry.get("axes", {})
            v = ax.get(axis)
            if v: vctr[v] += 1
        dist = {v: vctr.get(v, 0) for v in vals}
        used = sum(1 for v in vals if vctr.get(v, 0) > 0)
        cover_axes[axis] = {"values": vals, "distribution": dist, "coverage": round(used / len(vals), 2) if vals else 0}

    char_ctr = Counter()
    for i in items:
        ct = i.get("lead_character_type")
        if ct: char_ctr[ct] += 1

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "catalog": {
            "total": len(items), "byType": dict(sorted(type_ctr.items())),
            "byAge": {ag: age_ctr.get(ag, 0) for ag in _AGE_GROUPS},
            "withFingerprint": sum(1 for i in items if i.get("diversityFingerprint")),
            "withMood": sum(1 for i in items if i.get("mood")),
            "withCover": sum(1 for i in items if i.get("cover") and i["cover"] != "/covers/default.svg"),
            "withAudio": sum(1 for i in items if i.get("audio_url")),
        },
        "mood": {
            "config": {"moods": _ALL_MOODS, "labels": _MOOD_LABELS},
            "distribution": mood_dist,
            "byType": {t: dict(c) for t, c in sorted(mood_by_type.items())},
            "byAge": {ag: dict(mood_by_age.get(ag, {})) for ag in _AGE_GROUPS},
        },
        "content": {"totalFingerprinted": len(fingerprints), "dimensions": dimensions, "gaps": gaps},
        "covers": {"historyCount": len(axes_history), "axes": cover_axes, "leadCharacterType": dict(char_ctr.most_common())},
    }


@router.get("/diversity")
async def dashboard_diversity(
    authorization: Optional[str] = Header(None),
    view: str = Query("current", description="'current' for live stats, 'previous' for last pipeline snapshot"),
):
    """Content, cover, and mood diversity distributions."""
    verify_analytics_key(authorization)

    if view == "previous":
        if not DIVERSITY_SNAPSHOT_PATH.exists():
            return {"error": "No previous snapshot available", "generatedAt": None}
        try:
            return json.loads(DIVERSITY_SNAPSHOT_PATH.read_text())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read snapshot: {e}")

    try:
        return _compute_diversity_report()
    except Exception as e:
        logger.error("Diversity report error: %s", e)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")
