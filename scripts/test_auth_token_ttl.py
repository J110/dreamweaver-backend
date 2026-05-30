import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
from app.services import magic_link as ml

def test_session_ttl_is_365_days():
    assert ml.SESSION_TTL.days == 365

def test_dependencies_ttl_matches():
    from app import dependencies as deps
    assert deps._SESSION_TTL_SECONDS == 365 * 24 * 3600
    assert deps.AUTH_TOKEN_DORMANCY_DAYS == 365
