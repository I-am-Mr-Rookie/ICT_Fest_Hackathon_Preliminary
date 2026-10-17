"""Live per-room booking statistics."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Booking


def get(db: Session, room_id: int) -> dict:
    count, revenue = (
        db.query(
            func.count(Booking.id),
            func.coalesce(func.sum(Booking.price_cents), 0),
        )
        .filter(
            Booking.room_id == room_id,
            Booking.status == "confirmed",
        )
        .one()
    )
    return {"count": count, "revenue": revenue}
