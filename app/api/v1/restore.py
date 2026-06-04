"""Restore endpoints — native email-CODE sign-in (Step 5 of paywall rollout).

Distinct from magic-link auth: user TYPES a 6-digit code into the native
app so the resulting session token lands in the WebView session (then
forwarded to native Keychain via the bridge in #35), NOT in a browser
tab they clicked a URL from.

See app/services/restore_codes.py for the matching logic, anti-enumeration
contract, rate limits, and token issuance.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field

from app.services.restore_codes import (
    request_restore_code,
    verify_restore_code,
)

router = APIRouter()


class SendCodeBody(BaseModel):
    email: EmailStr


class VerifyCodeBody(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


@router.post("/send-code")
async def send_code(body: SendCodeBody) -> dict:
    return await request_restore_code(body.email)


@router.post("/verify-code")
async def verify_code(body: VerifyCodeBody) -> dict:
    return verify_restore_code(body.email, body.code)
