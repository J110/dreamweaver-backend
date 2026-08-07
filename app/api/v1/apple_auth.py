from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import get_db_client, get_optional_user
from app.services.apple_identity import AppleIdentityInvalid, AppleIdentityUnavailable, start_session, verify_identity_token
from app.services.magic_link import mint_device_token
from app.services.subscription_accounts import SubscriptionAccountConflict, find_by_apple_subject, link_verified_apple_identity, primary_user_for_account
from app.utils.entitlements import compute_tier


router = APIRouter()


class StartBody(BaseModel):
    purpose: str = Field(default="restore", pattern="^(purchase|restore|link)$")


class VerifyBody(BaseModel):
    session_id: str = Field(alias="sessionId")
    identity_token: str = Field(alias="identityToken")


@router.post("/start")
def start(body: StartBody, db_client=Depends(get_db_client)) -> dict:
    try:
        return start_session(db_client, body.purpose)
    except AppleIdentityUnavailable:
        raise HTTPException(status_code=503, detail="Apple sign-in unavailable")


@router.post("/verify")
def verify(body: VerifyBody, current_user: dict | None = Depends(get_optional_user), db_client=Depends(get_db_client)) -> dict:
    try:
        claims = verify_identity_token(db_client, body.session_id, body.identity_token)
        subject = claims["sub"]
        email = claims.get("email") if claims.get("email_verified") in (True, "true", "1") else None
        if current_user:
            account = link_verified_apple_identity(db_client, current_user["uid"], subject, email)
            if claims.get("_purpose") == "restore":
                user = primary_user_for_account(db_client, account)
                if user and compute_tier(user) == "premium":
                    uid = user["uid"]
                    token = mint_device_token(db_client, uid)
                    return {"status": "claimed", "token": token, "uid": uid, "family_id": user.get("family_id", "")}
            return {"status": "linked", "subscriptionAccountId": account["id"], "email": account.get("recovery_email")}
        account = find_by_apple_subject(db_client, subject)
        user = primary_user_for_account(db_client, account) if account else None
        if not user or compute_tier(user) != "premium":
            raise HTTPException(status_code=404, detail="No subscription account found")
        token = mint_device_token(db_client, user["uid"])
        return {"status": "claimed", "token": token, "uid": user["uid"], "family_id": user.get("family_id", "")}
    except AppleIdentityUnavailable:
        raise HTTPException(status_code=503, detail="Apple sign-in unavailable")
    except AppleIdentityInvalid:
        raise HTTPException(status_code=401, detail="Invalid Apple authorization")
    except SubscriptionAccountConflict:
        raise HTTPException(status_code=409, detail="Subscription identity conflict")
