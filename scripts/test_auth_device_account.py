import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.local_store import get_local_store
from app.services import magic_link as ml
from app.dependencies import local_verify_token

def test_device_user_unique_uid_on_collision():
    store = get_local_store()
    a = ml._create_device_user(store, "spiderman", child_age=6, lang="en")
    b = ml._create_device_user(store, "spiderman", child_age=6, lang="en")
    assert a["uid"] != b["uid"]
    assert a["family_id"] != b["family_id"]
    assert a["username"] == b["username"] == "spiderman"
    assert a["subscription_tier"] == "free"
    assert a["onboarding_complete"] is True
    assert "email" not in a

def test_device_account_token_validates():
    store = get_local_store()
    user = ml._create_device_user(store, "batman", child_age=8, lang="en")
    token = ml.mint_device_token(store, user["uid"])
    verified = local_verify_token(token)
    assert verified is not None
    assert verified["uid"] == user["uid"]
