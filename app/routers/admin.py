"""Administrative reporting and export endpoints."""
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..database import get_db
from ..errors import AppError
from ..models import Booking, Room, User
from ..services.export import generate_export

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/usage-report")
def usage_report(
    frm: str = Query(..., alias="from"),
    to: str = Query(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        from_date = datetime.strptime(frm, "%Y-%m-%d").date()
        to_date = datetime.strptime(to, "%Y-%m-%d").date()
        range_end = datetime.combine(to_date + timedelta(days=1), time.min)
    except (ValueError, OverflowError):
        raise AppError(400, "INVALID_BOOKING_WINDOW", "Invalid date range")

    range_start = datetime.combine(from_date, time.min)

    # Outer join with the filters in the ON clause keeps rooms that have zero matching bookings.
    rows = (
        db.query(
            Room.id,
            Room.name,
            func.count(Booking.id),
            func.coalesce(func.sum(Booking.price_cents), 0),
        )
        .outerjoin(
            Booking,
            and_(
                Booking.room_id == Room.id,
                Booking.status == "confirmed",
                Booking.start_time >= range_start,
                Booking.start_time < range_end,
            ),
        )
        .filter(Room.org_id == admin.org_id)
        .group_by(Room.id, Room.name)
        .order_by(Room.id.asc())
        .all()
    )
    room_rows = [
        {"room_id": rid, "room_name": name, "confirmed_bookings": count, "revenue_cents": revenue}
        for rid, name, count, revenue in rows
    ]

    return {"from": frm, "to": to, "rooms": room_rows}


@router.get("/export")
def export(
    room_id: int | None = Query(None),
    include_all: bool = Query(False),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if room_id is not None:
        room = db.query(Room).filter(Room.id == room_id, Room.org_id == admin.org_id).first()
        if room is None:
            raise AppError(404, "ROOM_NOT_FOUND", "Room not found")
    csv_body = generate_export(db, admin.org_id, admin.id, room_id, include_all)
    return Response(content=csv_body, media_type="text/csv")
