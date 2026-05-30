import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from fastapi import HTTPException
from app.services.local_store import get_local_store
from app.services import magic_link as ml
from app.api.v1.auth import _renew_logic

def test_renew_valid_token_mints_new():
    store = get_local_store()
    user = ml._create_device_user(store, "renew_ok", child_age=6, lang="en")
    old = ml.mint_device_token(store, user["uid"])
    result = _renew_logic(old, user["family_id"])
    assert result["token"] and result["token"] != old
    from app.dependencies import local_verify_token
    assert local_verify_token(result["token"])["uid"] == user["uid"]

def test_renew_unknown_token_410():
    with pytest.raises(HTTPException) as exc:
        _renew_logic("deadbeef-not-a-real-token", "any-family-id")
    assert exc.value.status_code == 410
    assert exc.value.detail == "dormant_reauth_required"

def test_renew_family_id_mismatch_410():
    store = get_local_store()
    user = ml._create_device_user(store, "renew_mismatch", child_age=6, lang="en")
    tok = ml.mint_device_token(store, user["uid"])
    with pytest.raises(HTTPException) as exc:
        _renew_logic(tok, "wrong-family-id")
    assert exc.value.status_code == 410
