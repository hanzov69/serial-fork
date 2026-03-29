"""
Authenticated user routes: My Requests page and request re-submission.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.models import RequestStatus, SerialRequest
from web.deps import get_db, require_user
from shared.models import User

router = APIRouter(prefix="/my-requests", tags=["user"])


def _templates(request: Request):
    return request.app.state.templates


@router.get("", response_class=HTMLResponse)
async def my_requests(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    result = await db.execute(
        select(SerialRequest)
        .where(SerialRequest.requester_id == current_user.id)
        .options(
            selectinload(SerialRequest.printer_type),
            selectinload(SerialRequest.serial),
        )
        .order_by(SerialRequest.submitted_at.desc())
    )
    requests = list(result.scalars())

    return _templates(request).TemplateResponse(
        request,
        "my_requests.html",
        {
            "my_requests": requests,
            "current_user": current_user,
            "settings": request.app.state.settings,
            "RequestStatus": RequestStatus,
        },
    )


@router.post("/{request_id}/resubmit")
async def resubmit_request(
    request_id: int,
    post_url: str = Form(default=""),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    result = await db.execute(
        select(SerialRequest).where(SerialRequest.id == request_id)
    )
    serial_request = result.scalar_one_or_none()

    if serial_request is None:
        raise HTTPException(status_code=404, detail="Request not found")

    if serial_request.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only re-submit your own requests")

    if serial_request.status != RequestStatus.rejected:
        raise HTTPException(
            status_code=409,
            detail=f"Only rejected requests can be re-submitted (current status: {serial_request.status})",
        )

    clean_url = post_url.strip()
    if clean_url:
        if "discord.com" not in clean_url:
            raise HTTPException(status_code=400, detail="Post URL must be a Discord link (discord.com)")
        serial_request.post_url = clean_url

    serial_request.status = RequestStatus.pending
    serial_request.rejection_reason = None
    serial_request.reviewed_at = None
    serial_request.reviewed_by_id = None
    serial_request.submitted_at = datetime.now(timezone.utc)

    return RedirectResponse("/my-requests", status_code=303)
