"""Periodic health snapshot collector — reads system + request metrics every 5 minutes."""

import os
import json
import time
import asyncio
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Server start time (for uptime calculation)
_server_start_time = time.time()

COLLECTION_INTERVAL = 300  # 5 minutes
RETENTION_DAYS = 7


def get_uptime_seconds():
    """Seconds since server process started."""
    return time.time() - _server_start_time


def read_system_metrics():
    """Read CPU, memory, disk from OS. Works in Docker on Linux + macOS dev."""
    metrics = {}

    # CPU load average
    try:
        load1, load5, _load15 = os.getloadavg()
        metrics["cpu_load_1m"] = round(load1, 2)
        metrics["cpu_load_5m"] = round(load5, 2)
    except OSError:
        metrics["cpu_load_1m"] = None
        metrics["cpu_load_5m"] = None

    # Memory — /proc/meminfo (Linux/Docker)
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            info = {}
            for line in meminfo.read_text().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])  # kB
            total_kb = info.get("MemTotal", 0)
            available_kb = info.get("MemAvailable", 0)
            used_kb = total_kb - available_kb
            metrics["memory_total_mb"] = round(total_kb / 1024, 1)
            metrics["memory_used_mb"] = round(used_kb / 1024, 1)
            metrics["memory_used_pct"] = round(used_kb / total_kb * 100, 1) if total_kb > 0 else 0
        except Exception as e:
            logger.warning("Failed to read /proc/meminfo: %s", e)
            metrics["memory_total_mb"] = None
            metrics["memory_used_mb"] = None
            metrics["memory_used_pct"] = None
    else:
        # macOS dev fallback — no memory data
        metrics["memory_total_mb"] = None
        metrics["memory_used_mb"] = None
        metrics["memory_used_pct"] = None

    # Disk usage
    try:
        stat = os.statvfs("/")
        total_bytes = stat.f_blocks * stat.f_frsize
        free_bytes = stat.f_bavail * stat.f_frsize
        used_bytes = total_bytes - free_bytes
        metrics["disk_total_gb"] = round(total_bytes / (1024 ** 3), 1)
        metrics["disk_used_gb"] = round(used_bytes / (1024 ** 3), 1)
        metrics["disk_used_pct"] = round(used_bytes / total_bytes * 100, 1) if total_bytes > 0 else 0
    except Exception:
        metrics["disk_total_gb"] = None
        metrics["disk_used_gb"] = None
        metrics["disk_used_pct"] = None

    return metrics


def compute_request_stats(buffer, lock, since_timestamp):
    """Compute request statistics from the ring buffer for entries after since_timestamp."""
    with lock:
        recent = [(ts, method, path, status, dur)
                  for ts, method, path, status, dur in buffer
                  if ts >= since_timestamp]

    if not recent:
        return {
            "request_count": 0,
            "error_count": 0,
            "latency_p50": None,
            "latency_p95": None,
            "latency_p99": None,
            "latency_avg": None,
        }

    durations = sorted([r[4] for r in recent])
    error_count = sum(1 for r in recent if r[3] >= 400)
    n = len(durations)

    return {
        "request_count": n,
        "error_count": error_count,
        "latency_p50": round(durations[int(n * 0.50)], 1),
        "latency_p95": round(durations[min(int(n * 0.95), n - 1)], 1),
        "latency_p99": round(durations[min(int(n * 0.99), n - 1)], 1),
        "latency_avg": round(statistics.mean(durations), 1),
    }


def compute_health_score(sys_metrics, req_stats):
    """Compute overall health score (0-100) with per-component breakdown.

    Components:
      CPU (25 pts)     — green <1.5, yellow 1.5-3.0, red >3.0
      Memory (25 pts)  — green <70%, yellow 70-85%, red >85%
      Disk (20 pts)    — green <75%, yellow 75-90%, red >90%
      Latency (20 pts) — green <500ms, yellow 500-2000ms, red >2000ms
      Errors (10 pts)  — green <2%, yellow 2-10%, red >10%
    """
    components = []

    # CPU
    cpu = sys_metrics.get("cpu_load_1m")
    if cpu is not None:
        if cpu < 1.5:
            score, status = 25, "green"
        elif cpu < 3.0:
            score, status = 12, "yellow"
        else:
            score, status = 0, "red"
        components.append({"name": "CPU", "score": score, "max": 25, "status": status,
                           "value": f"{cpu} load", "detail": f"1-min load avg: {cpu}"})
    else:
        components.append({"name": "CPU", "score": 25, "max": 25, "status": "green",
                           "value": "N/A", "detail": "Not available"})

    # Memory
    mem = sys_metrics.get("memory_used_pct")
    if mem is not None:
        if mem < 70:
            score, status = 25, "green"
        elif mem < 85:
            score, status = 12, "yellow"
        else:
            score, status = 0, "red"
        used_mb = sys_metrics.get("memory_used_mb", 0)
        total_mb = sys_metrics.get("memory_total_mb", 0)
        components.append({"name": "Memory", "score": score, "max": 25, "status": status,
                           "value": f"{mem}%", "detail": f"{used_mb}MB / {total_mb}MB"})
    else:
        components.append({"name": "Memory", "score": 25, "max": 25, "status": "green",
                           "value": "N/A", "detail": "Not available"})

    # Disk
    disk = sys_metrics.get("disk_used_pct")
    if disk is not None:
        if disk < 75:
            score, status = 20, "green"
        elif disk < 90:
            score, status = 10, "yellow"
        else:
            score, status = 0, "red"
        used_gb = sys_metrics.get("disk_used_gb", 0)
        total_gb = sys_metrics.get("disk_total_gb", 0)
        components.append({"name": "Disk", "score": score, "max": 20, "status": status,
                           "value": f"{disk}%", "detail": f"{used_gb}GB / {total_gb}GB"})
    else:
        components.append({"name": "Disk", "score": 20, "max": 20, "status": "green",
                           "value": "N/A", "detail": "Not available"})

    # Latency (p95)
    p95 = req_stats.get("latency_p95")
    if p95 is not None:
        if p95 < 500:
            score, status = 20, "green"
        elif p95 < 2000:
            score, status = 10, "yellow"
        else:
            score, status = 0, "red"
        components.append({"name": "Latency", "score": score, "max": 20, "status": status,
                           "value": f"{p95}ms p95", "detail": f"p50={req_stats.get('latency_p50')}ms, p95={p95}ms, p99={req_stats.get('latency_p99')}ms"})
    else:
        components.append({"name": "Latency", "score": 20, "max": 20, "status": "green",
                           "value": "No traffic", "detail": "No recent requests"})

    # Error rate
    req_count = req_stats.get("request_count", 0)
    err_count = req_stats.get("error_count", 0)
    if req_count > 0:
        err_rate = err_count / req_count * 100
        if err_rate < 2:
            score, status = 10, "green"
        elif err_rate < 10:
            score, status = 5, "yellow"
        else:
            score, status = 0, "red"
        components.append({"name": "Errors", "score": score, "max": 10, "status": status,
                           "value": f"{round(err_rate, 1)}%", "detail": f"{err_count} errors / {req_count} requests"})
    else:
        components.append({"name": "Errors", "score": 10, "max": 10, "status": "green",
                           "value": "0%", "detail": "No recent requests"})

    total_score = sum(c["score"] for c in components)
    if total_score >= 80:
        overall_status = "green"
    elif total_score >= 50:
        overall_status = "yellow"
    else:
        overall_status = "red"

    # Sort: problems first when not green
    if overall_status != "green":
        components.sort(key=lambda c: 0 if c["status"] == "red" else 1 if c["status"] == "yellow" else 2)

    return {
        "score": total_score,
        "status": overall_status,
        "components": components,
    }


def get_db_size_mb():
    """Get analytics DB file size in MB."""
    db_path = Path("data/analytics.db")
    if db_path.exists():
        return round(db_path.stat().st_size / (1024 * 1024), 2)
    return 0


async def health_collection_loop():
    """Main loop: collect a snapshot every 5 minutes and write to SQLite."""
    from app.api.v1.analytics import get_db
    from app.middleware.timing import get_request_buffer

    logger.info("Health collector started (interval=%ds, retention=%dd)",
                COLLECTION_INTERVAL, RETENTION_DAYS)

    # Wait for server to fully start
    await asyncio.sleep(10)

    last_collection_time = time.time()

    while True:
        try:
            now = time.time()
            now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
            timestamp_iso = now_dt.isoformat()
            hour = now_dt.strftime("%Y-%m-%d %H")

            # System metrics
            sys_metrics = read_system_metrics()

            # Request metrics since last collection
            buffer, lock = get_request_buffer()
            req_stats = compute_request_stats(buffer, lock, last_collection_time)

            # Health score
            health = compute_health_score(sys_metrics, req_stats)

            # DB size
            db_size = get_db_size_mb()

            # Write to SQLite
            conn = get_db()
            conn.execute("""
                INSERT INTO health_snapshots
                    (timestamp, hour, cpu_load_1m, cpu_load_5m,
                     memory_used_pct, memory_used_mb, memory_total_mb,
                     disk_used_pct, disk_used_gb, disk_total_gb,
                     request_count, error_count,
                     latency_p50, latency_p95, latency_p99, latency_avg,
                     health_score, health_components, db_size_mb)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp_iso, hour,
                sys_metrics.get("cpu_load_1m"),
                sys_metrics.get("cpu_load_5m"),
                sys_metrics.get("memory_used_pct"),
                sys_metrics.get("memory_used_mb"),
                sys_metrics.get("memory_total_mb"),
                sys_metrics.get("disk_used_pct"),
                sys_metrics.get("disk_used_gb"),
                sys_metrics.get("disk_total_gb"),
                req_stats["request_count"],
                req_stats["error_count"],
                req_stats["latency_p50"],
                req_stats["latency_p95"],
                req_stats["latency_p99"],
                req_stats["latency_avg"],
                health["score"],
                json.dumps(health["components"]),
                db_size,
            ))

            # Prune old snapshots
            cutoff = (now_dt - timedelta(days=RETENTION_DAYS)).isoformat()
            conn.execute("DELETE FROM health_snapshots WHERE timestamp < ?", (cutoff,))

            conn.commit()
            conn.close()

            last_collection_time = now
            logger.debug("Health snapshot: score=%d, %d reqs, p95=%s ms",
                         health["score"], req_stats["request_count"],
                         req_stats.get("latency_p95") or 0)

        except Exception as e:
            logger.warning("Health collection error: %s", e)

        await asyncio.sleep(COLLECTION_INTERVAL)
