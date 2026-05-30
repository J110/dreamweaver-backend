import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from app.api.v1.auth import login_username, LoginUsernameBody
from app.dependencies import local_verify_token

def test_login_username_always_creates_no_find_existing():
    # Two calls, same username → DISTINCT accounts (find-existing removed).
    r1 = asyncio.new_event_loop().run_until_complete(
        login_username(LoginUsernameBody(username="compat_user", child_age=6, lang="en")))
    r2 = asyncio.new_event_loop().run_until_complete(
        login_username(LoginUsernameBody(username="compat_user", child_age=6, lang="en")))
    assert r1["token"] != r2["token"]
    assert r1["user"]["uid"] != r2["user"]["uid"]
    assert local_verify_token(r1["token"])["uid"] == r1["user"]["uid"]
