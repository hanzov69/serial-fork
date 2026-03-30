"""
Moderator and admin routes: review queue, user management, reservations, printer types.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.database import is_serial_number_free, next_serial_number
from shared.models import (
    AuditLog,
    PrinterType,
    RequestStatus,
    Serial,
    SerialRequest,
    SerialReservation,
    User,
    UserRole,
)
from web.deps import get_db, require_admin, require_backup_access, require_moderator, require_owner
from web.discord_notify import assign_role, notify_approved, notify_rejected

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9]{1,3}$")


def _templates(request: Request):
    return request.app.state.templates


def _pad(request: Request) -> int:
    return request.app.state.settings.serial_pad_width


# ------------------------------------------------------------------
# Queue (moderator)
# ------------------------------------------------------------------

@router.get("/queue", response_class=HTMLResponse)
async def queue(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_moderator),
):
    pending_result = await db.execute(
        select(SerialRequest)
        .where(SerialRequest.status == RequestStatus.pending)
        .options(
            selectinload(SerialRequest.requester),
            selectinload(SerialRequest.printer_type),
        )
        .order_by(SerialRequest.submitted_at)
    )
    pending_requests = list(pending_result.scalars())

    # Admins also see rejected requests so they can delete them immediately
    rejected_requests = []
    if current_user.is_admin:
        rejected_result = await db.execute(
            select(SerialRequest)
            .where(SerialRequest.status == RequestStatus.rejected)
            .options(
                selectinload(SerialRequest.requester),
                selectinload(SerialRequest.printer_type),
            )
            .order_by(SerialRequest.reviewed_at.desc())
            .limit(50)
        )
        rejected_requests = list(rejected_result.scalars())

    return _templates(request).TemplateResponse(
        request,
        "queue.html",
        {
            "pending_requests": pending_requests,
            "rejected_requests": rejected_requests,
            "current_user": current_user,
            "settings": request.app.state.settings,
        },
    )


@router.post("/approve/{request_id}")
async def approve_request(
    request_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_moderator),
):
    result = await db.execute(
        select(SerialRequest)
        .where(SerialRequest.id == request_id)
        .options(
            selectinload(SerialRequest.printer_type),
            selectinload(SerialRequest.requester),
        )
    )
    serial_request = result.scalar_one_or_none()

    if serial_request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if serial_request.status != RequestStatus.pending:
        raise HTTPException(status_code=409, detail=f"Request is already {serial_request.status}")

    serial_num = await next_serial_number(db, serial_request.printer_type_id)

    serial_request.status = RequestStatus.approved
    serial_request.reviewed_at = datetime.now(timezone.utc)
    serial_request.reviewed_by_id = current_user.id

    db.add(Serial(
        printer_type_id=serial_request.printer_type_id,
        serial_number=serial_num,
        request_id=serial_request.id,
        holder_id=serial_request.requester_id,
        issued_by_id=current_user.id,
    ))
    db.add(AuditLog(
        actor_id=current_user.id,
        action="approve",
        target_user_id=serial_request.requester_id,
        details=f"request_id={request_id}, type={serial_request.printer_type.identifier}, serial={serial_num}",
    ))
    await db.flush()

    settings = request.app.state.settings
    pad = settings.serial_pad_width
    serial_display = serial_request.printer_type.format_serial(serial_num, pad)
    await notify_approved(
        settings,
        serial_request.discord_message_id,
        request_id,
        serial_request.printer_type.name,
        serial_request.printer_type.identifier,
        serial_display,
        serial_request.requester.discord_id,
        current_user.username,
    )
    if serial_request.printer_type.discord_role_id:
        await assign_role(settings, serial_request.requester.discord_id, serial_request.printer_type.discord_role_id)

    return RedirectResponse("/admin/queue", status_code=303)


@router.post("/assign/{request_id}")
async def assign_serial(
    request_id: int,
    serial_number: int = Form(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(
        select(SerialRequest)
        .where(SerialRequest.id == request_id)
        .options(
            selectinload(SerialRequest.printer_type),
            selectinload(SerialRequest.requester),
        )
    )
    serial_request = result.scalar_one_or_none()

    if serial_request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if serial_request.status != RequestStatus.pending:
        raise HTTPException(status_code=409, detail=f"Request is already {serial_request.status}")

    if not await is_serial_number_free(db, serial_request.printer_type_id, serial_number):
        raise HTTPException(
            status_code=409,
            detail=f"Serial {serial_request.printer_type.identifier}-{serial_number} is already issued",
        )

    # Consume reservation if one exists
    existing_res = await db.scalar(
        select(SerialReservation)
        .where(SerialReservation.printer_type_id == serial_request.printer_type_id)
        .where(SerialReservation.serial_number == serial_number)
    )
    if existing_res:
        await db.delete(existing_res)

    serial_request.status = RequestStatus.approved
    serial_request.reviewed_at = datetime.now(timezone.utc)
    serial_request.reviewed_by_id = current_user.id

    db.add(Serial(
        printer_type_id=serial_request.printer_type_id,
        serial_number=serial_number,
        request_id=serial_request.id,
        holder_id=serial_request.requester_id,
        issued_by_id=current_user.id,
    ))
    db.add(AuditLog(
        actor_id=current_user.id,
        action="approve",
        target_user_id=serial_request.requester_id,
        details=f"request_id={request_id}, assigned={serial_request.printer_type.identifier}-{serial_number}",
    ))
    await db.flush()

    settings = request.app.state.settings
    serial_display = serial_request.printer_type.format_serial(serial_number, settings.serial_pad_width)
    await notify_approved(
        settings,
        serial_request.discord_message_id,
        request_id,
        serial_request.printer_type.name,
        serial_request.printer_type.identifier,
        serial_display,
        serial_request.requester.discord_id,
        current_user.username,
    )
    if serial_request.printer_type.discord_role_id:
        await assign_role(settings, serial_request.requester.discord_id, serial_request.printer_type.discord_role_id)

    return RedirectResponse("/admin/queue", status_code=303)


@router.post("/reject/{request_id}")
async def reject_request(
    request_id: int,
    reason: str = Form(default=""),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_moderator),
):
    result = await db.execute(
        select(SerialRequest)
        .where(SerialRequest.id == request_id)
        .options(
            selectinload(SerialRequest.printer_type),
            selectinload(SerialRequest.requester),
        )
    )
    serial_request = result.scalar_one_or_none()

    if serial_request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if serial_request.status != RequestStatus.pending:
        raise HTTPException(status_code=409, detail=f"Request is already {serial_request.status}")

    clean_reason = reason.strip() or None
    serial_request.status = RequestStatus.rejected
    serial_request.reviewed_at = datetime.now(timezone.utc)
    serial_request.reviewed_by_id = current_user.id
    serial_request.rejection_reason = clean_reason

    db.add(AuditLog(
        actor_id=current_user.id,
        action="reject",
        target_user_id=serial_request.requester_id,
        details=f"request_id={request_id}, reason={reason}",
    ))

    await notify_rejected(
        request.app.state.settings,
        serial_request.discord_message_id,
        request_id,
        serial_request.printer_type.name,
        serial_request.printer_type.identifier,
        serial_request.requester.discord_id,
        clean_reason,
        current_user.username,
    )

    return RedirectResponse("/admin/queue", status_code=303)


@router.post("/requests/{request_id}/delete")
async def delete_rejected_request(
    request_id: int,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Immediately delete a rejected request."""
    result = await db.execute(
        select(SerialRequest).where(SerialRequest.id == request_id)
    )
    serial_request = result.scalar_one_or_none()

    if serial_request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if serial_request.status != RequestStatus.rejected:
        raise HTTPException(status_code=409, detail="Only rejected requests can be deleted")

    await db.delete(serial_request)
    return RedirectResponse("/admin/queue", status_code=303)


# ------------------------------------------------------------------
# User management (admin)
# ------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def users_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = list(result.scalars())
    return _templates(request).TemplateResponse(
        request,
        "admin_users.html",
        {"users": users, "current_user": current_user, "UserRole": UserRole},
    )


@router.post("/users/{user_id}/role")
async def set_user_role(
    user_id: int,
    role: str = Form(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if role not in (UserRole.user, UserRole.moderator, UserRole.admin):
        raise HTTPException(status_code=400, detail="Invalid role")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if target.role == UserRole.owner:
        raise HTTPException(status_code=403, detail="The Owner's role cannot be changed")

    old_role = target.role
    target.role = role
    db.add(AuditLog(
        actor_id=current_user.id,
        action="promote" if role > old_role else "demote",
        target_user_id=target.id,
        details=f"old_role={old_role}, new_role={role}",
    ))
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/transfer-ownership")
async def transfer_ownership(
    user_id: int,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Transfer the Owner role to another admin, reducing the current owner to admin."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not target.is_admin:
        raise HTTPException(status_code=409, detail="Target user must already be an admin")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="You are already the Owner")

    # Fetch current owner's own row within the same session
    owner_result = await db.execute(select(User).where(User.id == current_user.id))
    owner_row = owner_result.scalar_one()

    owner_row.role = UserRole.admin
    target.role = UserRole.owner

    db.add(AuditLog(
        actor_id=current_user.id,
        action="promote",
        target_user_id=target.id,
        details=f"ownership_transfer: {current_user.username} → {target.username}",
    ))
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/serials/{serial_id}/rescind")
async def rescind_serial(
    serial_id: int,
    reason: str = Form(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(
        select(Serial)
        .where(Serial.id == serial_id)
        .options(selectinload(Serial.printer_type))
    )
    serial = result.scalar_one_or_none()

    if serial is None:
        raise HTTPException(status_code=404, detail="Serial not found")
    if not serial.is_active:
        raise HTTPException(status_code=409, detail="Serial is already rescinded")

    serial.rescinded_at = datetime.now(timezone.utc)
    serial.rescinded_by_id = current_user.id
    serial.rescind_reason = reason

    db.add(AuditLog(actor_id=current_user.id, action="rescind", serial_id=serial.id, details=f"reason={reason}"))

    identifier = serial.printer_type.identifier
    snum = serial.serial_number
    return RedirectResponse(f"/serial/{identifier}/{snum}", status_code=303)


# ------------------------------------------------------------------
# Printer type management (admin)
# ------------------------------------------------------------------

@router.get("/printers", response_class=HTMLResponse)
async def printers_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(
        select(PrinterType).order_by(PrinterType.identifier)
    )
    printer_types = list(result.scalars())
    return _templates(request).TemplateResponse(
        request,
        "admin_printers.html",
        {"printer_types": printer_types, "current_user": current_user},
    )


_ROLE_ID_RE = re.compile(r"^\d{17,20}$")


@router.post("/printers")
async def create_printer_type(
    identifier: str = Form(...),
    name: str = Form(...),
    description: str = Form(default=""),
    discord_role_id: str = Form(default=""),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    identifier = identifier.upper().strip()

    if not _IDENTIFIER_RE.match(identifier):
        raise HTTPException(status_code=400, detail="Identifier must be 1–3 alphanumeric characters")

    existing_id = await db.scalar(select(PrinterType).where(PrinterType.identifier == identifier))
    if existing_id:
        raise HTTPException(status_code=409, detail=f"Identifier '{identifier}' is already in use")

    existing_name = await db.scalar(select(PrinterType).where(PrinterType.name == name.strip()))
    if existing_name:
        raise HTTPException(status_code=409, detail=f"Name '{name}' is already in use")

    clean_role_id = discord_role_id.strip() or None
    if clean_role_id and not _ROLE_ID_RE.match(clean_role_id):
        raise HTTPException(status_code=400, detail="Discord Role ID must be a numeric snowflake (17–20 digits)")

    db.add(PrinterType(
        identifier=identifier,
        name=name.strip(),
        description=description.strip() or None,
        discord_role_id=clean_role_id,
        is_active=True,
        created_by_id=current_user.id,
    ))
    return RedirectResponse("/admin/printers", status_code=303)


@router.post("/printers/{printer_id}/role")
async def set_printer_role(
    printer_id: int,
    discord_role_id: str = Form(default=""),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(PrinterType).where(PrinterType.id == printer_id))
    pt = result.scalar_one_or_none()
    if pt is None:
        raise HTTPException(status_code=404, detail="Printer type not found")

    clean_role_id = discord_role_id.strip() or None
    if clean_role_id and not _ROLE_ID_RE.match(clean_role_id):
        raise HTTPException(status_code=400, detail="Discord Role ID must be a numeric snowflake (17–20 digits)")

    pt.discord_role_id = clean_role_id
    return RedirectResponse("/admin/printers", status_code=303)


@router.post("/printers/{printer_id}/toggle")
async def toggle_printer_type(
    printer_id: int,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(PrinterType).where(PrinterType.id == printer_id))
    pt = result.scalar_one_or_none()
    if pt is None:
        raise HTTPException(status_code=404, detail="Printer type not found")
    pt.is_active = not pt.is_active
    return RedirectResponse("/admin/printers", status_code=303)


# ------------------------------------------------------------------
# Serial reservations (admin)
# ------------------------------------------------------------------

@router.get("/reservations", response_class=HTMLResponse)
async def reservations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    reservations_result = await db.execute(
        select(SerialReservation)
        .options(
            selectinload(SerialReservation.printer_type),
            selectinload(SerialReservation.reserved_by),
        )
        .order_by(SerialReservation.printer_type_id, SerialReservation.serial_number)
    )
    reservations_list = list(reservations_result.scalars())

    printer_types_result = await db.execute(
        select(PrinterType).where(PrinterType.is_active == True).order_by(PrinterType.identifier)
    )
    printer_types = list(printer_types_result.scalars())

    return _templates(request).TemplateResponse(
        request,
        "admin_reservations.html",
        {
            "reservations": reservations_list,
            "printer_types": printer_types,
            "current_user": current_user,
            "settings": request.app.state.settings,
        },
    )


@router.post("/reservations")
async def create_reservation(
    printer_type_id: int = Form(...),
    serial_number: int = Form(...),
    reason: str = Form(default=""),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    pt = await db.scalar(select(PrinterType).where(PrinterType.id == printer_type_id))
    if pt is None:
        raise HTTPException(status_code=404, detail="Printer type not found")

    if not await is_serial_number_free(db, printer_type_id, serial_number):
        raise HTTPException(status_code=409, detail=f"{pt.identifier}-{serial_number} is already issued")

    existing = await db.scalar(
        select(SerialReservation)
        .where(SerialReservation.printer_type_id == printer_type_id)
        .where(SerialReservation.serial_number == serial_number)
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"{pt.identifier}-{serial_number} is already reserved")

    db.add(SerialReservation(
        printer_type_id=printer_type_id,
        serial_number=serial_number,
        reason=reason.strip() or None,
        reserved_by_id=current_user.id,
    ))
    return RedirectResponse("/admin/reservations", status_code=303)


@router.post("/reservations/{reservation_id}/delete")
async def delete_reservation(
    reservation_id: int,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(SerialReservation).where(SerialReservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    await db.delete(reservation)
    return RedirectResponse("/admin/reservations", status_code=303)


# ------------------------------------------------------------------
# Database backup (owner always; admin if backup_allow_admin enabled)
# ------------------------------------------------------------------

def _hot_backup_zip(db_path: str, db_filename: str) -> bytes:
    """
    Use SQLite's built-in online backup API to create a consistent snapshot,
    then wrap it in a zip archive. Safe to run while other connections are
    active (WAL mode). Returns zip file bytes.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)
    try:
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(tmp_path)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_path, arcname=db_filename)
        return buf.getvalue()
    finally:
        os.unlink(tmp_path)


@router.get("/backup")
async def download_backup(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_backup_access),
):
    """Download a hot backup of the SQLite database as a zip archive."""
    db_path = request.app.state.settings.db_path
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    db_filename = f"bb_serial_backup_{timestamp}.db"
    zip_filename = f"bb_serial_backup_{timestamp}.zip"

    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _hot_backup_zip, db_path, db_filename)

    db.add(AuditLog(
        actor_id=current_user.id,
        action="backup",
        details=f"database backup downloaded by {current_user.username}",
    ))

    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )
