"""The signed-in user's own notifications and tickets (Fase 16). Any role; never another user's rows."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from src.api.deps import get_current_user
from src.db.models import User
from src.services import notifications as service

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/notifications")
async def my_notifications(current_user: User = Depends(get_current_user)):
    items, unread = await run_in_threadpool(service.list_for_user, current_user.id, current_user.company_id)
    return {"unread": unread, "items": [asdict(n) for n in items]}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, current_user: User = Depends(get_current_user)):
    changed = await run_in_threadpool(service.mark_read, current_user.id, current_user.company_id, notification_id)
    if not changed:
        # Not found, already read, or someone else's — indistinguishable on purpose.
        raise HTTPException(status_code=404, detail="Notification not found.")
    return {"status": "read"}


@router.post("/notifications/read-all")
async def mark_all_read(current_user: User = Depends(get_current_user)):
    changed = await run_in_threadpool(service.mark_read, current_user.id, current_user.company_id, None)
    return {"status": "read", "changed": changed}


@router.get("/tickets")
async def my_tickets(current_user: User = Depends(get_current_user)):
    tickets = await run_in_threadpool(service.tickets_for_user, current_user.id, current_user.company_id)
    return {"items": [asdict(t) for t in tickets]}
