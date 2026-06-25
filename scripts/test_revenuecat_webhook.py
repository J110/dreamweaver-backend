import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_revenuecat_events_table_dedups(monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setattr("app.api.v1.billing.BILLING_DB_PATH", Path(tmp_path) / "billing.db")
    from app.api.v1.billing import _open_billing_db
    conn = _open_billing_db()
    ins = ("INSERT OR IGNORE INTO revenuecat_webhook_events (event_id, event_type, received_at, status) VALUES (?,?,?,?)",
           ("evt_1", "INITIAL_PURCHASE", "2026-06-25T00:00:00Z", "received"))
    conn.execute(*ins); first = conn.total_changes
    conn.execute(*ins); second = conn.total_changes
    assert first == 1 and second == 1   # duplicate event_id ignored (idempotent)
    rows = conn.execute("SELECT COUNT(*) FROM revenuecat_webhook_events").fetchone()[0]
    assert rows == 1   # exactly one row survives the duplicate — A3's webhook relies on this
