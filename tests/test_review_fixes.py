"""Regression tests for fixes from the code review (see REVIEW_FIXES.md)."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services import reference

client = TestClient(app)


def _future(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(
        minute=0, second=0, microsecond=0
    ).isoformat()


def _admin_headers() -> dict:
    org = f"review-{datetime.now().timestamp()}"
    creds = {"org_name": org, "username": "admin", "password": "pw12345"}
    assert client.post("/auth/register", json=creds).status_code == 201
    token = client.post("/auth/login", json=creds).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _room(headers: dict, name: str = "R") -> int:
    resp = client.post(
        "/rooms", json={"name": name, "capacity": 2, "hourly_rate_cents": 500}, headers=headers
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_malformed_datetime_is_400_not_500():
    headers = _admin_headers()
    room_id = _room(headers)
    resp = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": "not-a-date", "end_time": _future(51)},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_BOOKING_WINDOW"


def test_usage_report_includes_room_created_after_previous_report():
    headers = _admin_headers()
    params = {"from": "2030-01-01", "to": "2030-01-02"}
    assert client.get("/admin/usage-report", params=params, headers=headers).json()["rooms"] == []
    room_id = _room(headers)
    rooms = client.get("/admin/usage-report", params=params, headers=headers).json()["rooms"]
    assert [r["room_id"] for r in rooms] == [room_id]


def test_availability_reflects_non_padded_date_after_booking():
    headers = _admin_headers()
    room_id = _room(headers)
    start = datetime(datetime.now(timezone.utc).year + 1, 1, 5, 10, tzinfo=timezone.utc)
    loose_date = f"{start.year}-1-5"  # non-zero-padded form of the same day
    url = f"/rooms/{room_id}/availability"
    assert client.get(url, params={"date": loose_date}, headers=headers).json()["busy"] == []
    booked = client.post(
        "/bookings",
        json={
            "room_id": room_id,
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(hours=1)).isoformat(),
        },
        headers=headers,
    )
    assert booked.status_code == 201
    assert len(client.get(url, params={"date": loose_date}, headers=headers).json()["busy"]) == 1


def test_reference_counter_resumes_after_restart():
    headers = _admin_headers()
    room_id = _room(headers)
    first = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(60), "end_time": _future(61)},
        headers=headers,
    ).json()["reference_code"]
    reference._counter["value"] = None  # simulate a process restart
    second = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(62), "end_time": _future(63)},
        headers=headers,
    ).json()["reference_code"]
    assert int(second[3:]) > int(first[3:])


def test_lowercase_bearer_scheme_accepted():
    token = _admin_headers()["Authorization"].split(" ", 1)[1]
    assert client.get("/rooms", headers={"Authorization": f"bearer {token}"}).status_code == 200
    assert client.get("/rooms", headers={"Authorization": "Bearer "}).status_code == 401


def test_malformed_booking_requests_count_toward_rate_limit():
    headers = _admin_headers()
    for _ in range(20):
        assert client.post("/bookings", json={"room_id": "x"}, headers=headers).status_code == 422
    resp = client.post(
        "/bookings",
        json={"room_id": 1, "start_time": _future(70), "end_time": _future(71)},
        headers=headers,
    )
    assert resp.status_code == 429


def test_out_of_range_dates_are_400_not_500():
    headers = _admin_headers()
    room_id = _room(headers)
    resp = client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": "0001-01-01T00:00:00+05:00", "end_time": _future(51)},
        headers=headers,
    )
    assert resp.status_code == 400
    params = {"from": "9999-12-30", "to": "9999-12-31"}
    assert client.get("/admin/usage-report", params=params, headers=headers).status_code == 400
    url = f"/rooms/{room_id}/availability"
    assert client.get(url, params={"date": "9999-12-31"}, headers=headers).status_code == 400
