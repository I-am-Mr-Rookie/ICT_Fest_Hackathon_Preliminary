"""Human-facing booking reference codes.

Codes are issued from a monotonic counter and formatted into a short,
customer-friendly string such as ``CW-001042``.
"""
import threading

from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

from ..models import Booking

_START = 1000
_counter: dict[str, int | None] = {"value": None}
_counter_lock = threading.Lock()


def next_reference_code(db: Session) -> str:
    with _counter_lock:
        if _counter["value"] is None:
            # Resume after the highest stored code so a restart never reissues one.
            highest = db.query(func.max(cast(func.substr(Booking.reference_code, 4), Integer))).scalar()
            _counter["value"] = _START if highest is None else max(_START, highest + 1)
        current = _counter["value"]
        _counter["value"] = current + 1
        return f"CW-{current:06d}"
