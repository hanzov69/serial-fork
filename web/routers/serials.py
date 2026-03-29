"""
Public serial number routes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.models import PrinterType, Serial, SerialRequest
from web.deps import get_current_user, get_db

router = APIRouter(tags=["serials"])


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    total_active = await db.scalar(
        select(func.count(Serial.id)).where(Serial.rescinded_at.is_(None))
    )

    # Per-type counts for the homepage summary
    type_counts_rows = await db.execute(
        select(PrinterType, func.count(Serial.id).label("count"))
        .outerjoin(Serial, (Serial.printer_type_id == PrinterType.id) & Serial.rescinded_at.is_(None))
        .where(PrinterType.is_active == True)
        .group_by(PrinterType.id)
        .order_by(PrinterType.identifier)
    )
    type_counts = type_counts_rows.all()

    recent_result = await db.execute(
        select(Serial)
        .where(Serial.rescinded_at.is_(None))
        .options(
            selectinload(Serial.holder),
            selectinload(Serial.printer_type),
        )
        .order_by(Serial.issued_at.desc())
        .limit(10)
    )
    recent = list(recent_result.scalars())

    return _templates(request).TemplateResponse(
        request,
        "index.html",
        {
            "total_active": total_active,
            "type_counts": type_counts,
            "recent_serials": recent,
            "current_user": current_user,
            "settings": request.app.state.settings,
        },
    )


@router.get("/serial/{identifier}/{serial_number}", response_class=HTMLResponse)
async def serial_detail(
    identifier: str,
    serial_number: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(Serial)
        .join(PrinterType, Serial.printer_type_id == PrinterType.id)
        .where(PrinterType.identifier == identifier.upper())
        .where(Serial.serial_number == serial_number)
        .options(
            selectinload(Serial.printer_type),
            selectinload(Serial.holder),
            selectinload(Serial.issued_by),
            selectinload(Serial.rescinded_by),
            selectinload(Serial.request).selectinload(SerialRequest.requester),
        )
    )
    serial = result.scalar_one_or_none()
    if serial is None:
        raise HTTPException(status_code=404, detail="Serial not found")

    return _templates(request).TemplateResponse(
        request,
        "serial_detail.html",
        {
            "serial": serial,
            "current_user": current_user,
            "settings": request.app.state.settings,
        },
    )


@router.get("/info", response_class=HTMLResponse)
async def info_page(
    request: Request,
    current_user=Depends(get_current_user),
):
    return _templates(request).TemplateResponse(
        request,
        "info.html",
        {"current_user": current_user},
    )


@router.get("/serials", response_class=HTMLResponse)
async def serials_list(
    request: Request,
    page: int = 1,
    type_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    per_page = 25
    offset = (page - 1) * per_page

    query = select(Serial).options(
        selectinload(Serial.holder),
        selectinload(Serial.printer_type),
    )
    count_query = select(func.count(Serial.id))

    if type_filter:
        query = query.join(PrinterType).where(PrinterType.identifier == type_filter.upper())
        count_query = count_query.join(PrinterType).where(PrinterType.identifier == type_filter.upper())

    total = await db.scalar(count_query)
    result = await db.execute(
        query.order_by(Serial.printer_type_id, Serial.serial_number.desc())
        .limit(per_page)
        .offset(offset)
    )
    serials = list(result.scalars())
    total_pages = max(1, (total + per_page - 1) // per_page)

    # All active printer types for the filter dropdown
    types_result = await db.execute(
        select(PrinterType).where(PrinterType.is_active == True).order_by(PrinterType.identifier)
    )
    printer_types = list(types_result.scalars())

    return _templates(request).TemplateResponse(
        request,
        "serials_list.html",
        {
            "serials": serials,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "type_filter": type_filter,
            "printer_types": printer_types,
            "current_user": current_user,
            "settings": request.app.state.settings,
        },
    )
