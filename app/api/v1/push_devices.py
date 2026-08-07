from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import get_current_user, get_db_client
from app.services import push_devices
from app.services.push_notifications import PushUnavailable, send


router = APIRouter()


class DeviceBody(BaseModel):
    target: str = Field(min_length=20, max_length=4096)
    platform: str = Field(default="ios", pattern="^(ios|android|web)$")
    permission: str = Field(default="authorized", max_length=32)


class SendBody(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=300)
    route: str = Field(default="/", max_length=512)
    uid: str | None = None


@router.post("/devices")
def register_device(body: DeviceBody, current_user: dict = Depends(get_current_user), db_client=Depends(get_db_client)) -> dict:
    push_devices.register(db_client, current_user["uid"], body.target, body.platform, body.permission)
    return {"registered": True}


@router.delete("/devices")
def unregister_device(body: DeviceBody, current_user: dict = Depends(get_current_user), db_client=Depends(get_db_client)) -> dict:
    push_devices.unregister(db_client, current_user["uid"], body.target)
    return {"registered": False}


@router.get("/devices")
def device_status(current_user: dict = Depends(get_current_user), db_client=Depends(get_db_client)) -> dict:
    rows = push_devices.active_for_user(db_client, current_user["uid"])
    return {"registered": bool(rows), "count": len(rows)}


@router.post("/admin/send")
def send_notification(body: SendBody, x_admin_key: str = Header(..., alias="X-Admin-Key"), db_client=Depends(get_db_client)) -> dict:
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin API key not configured")
    if not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    try:
        return send(db_client, push_devices.active_targets(db_client, body.uid), body.title, body.body, body.route)
    except PushUnavailable:
        raise HTTPException(status_code=503, detail="Push notifications unavailable")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid notification route")
