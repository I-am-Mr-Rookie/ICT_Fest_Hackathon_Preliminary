"""Business-rule coverage for the critical paths in README.md (second review pass)."""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _future(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(
        minute=0, second=0, microsecond=0
    ).isoformat()


def _user(org: str, username: str) -> dict:
    creds = {"org_name": org, "username": username, "password": "pw12345"}
    reg = client.post("/auth/register", json=creds)
    assert reg.status_code == 201
    tokens = client.post("/auth/login", json=creds).json()
    return {**reg.json(), **tokens, "h": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _org() -> str:
    return f"org-{uuid.uuid4().hex}"


def _room(admin: dict, rate: int = 1000) -> int:
    resp = client.post(
        "/rooms", json={"name": "R", "capacity": 2, "hourly_rate_cents": rate}, headers=admin["h"]
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _book(user: dict, room_id: int, start: int, end: int):
    return client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": _future(start), "end_time": _future(end)},
        headers=user["h"],
    )


def test_page_past_int64_offset_is_empty_not_500():
    admin = _user(_org(), "a")
    resp = client.get("/bookings", params={"page": 2**62}, headers=admin["h"])
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_pagination_orders_by_start_and_never_skips_or_repeats():
    admin = _user(_org(), "a")
    room_id = _room(admin)
    for start in (60, 50, 80, 70, 90):
        assert _book(admin, room_id, start, start + 1).status_code == 201
    seen = []
    for page in (1, 2, 3):
        body = client.get("/bookings", params={"page": page, "limit": 2}, headers=admin["h"]).json()
        assert body["total"] == 5
        seen += body["items"]
    starts = [b["start_time"] for b in seen]
    assert len({b["id"] for b in seen}) == 5
    assert starts == sorted(starts)


def test_overlap_conflicts_but_back_to_back_is_allowed():
    admin = _user(_org(), "a")
    room_id = _room(admin)
    assert _book(admin, room_id, 50, 52).status_code == 201
    clash = _book(admin, room_id, 51, 53)
    assert clash.status_code == 409 and clash.json()["code"] == "ROOM_CONFLICT"
    assert _book(admin, room_id, 52, 53).status_code == 201
    assert _book(admin, room_id, 49, 50).status_code == 201


def test_quota_caps_confirmed_bookings_in_next_24h():
    admin = _user(_org(), "a")
    room_id = _room(admin)
    for start in (2, 4, 6):
        assert _book(admin, room_id, start, start + 1).status_code == 201
    over = _book(admin, room_id, 8, 9)
    assert over.status_code == 409 and over.json()["code"] == "QUOTA_EXCEEDED"
    assert _book(admin, room_id, 30, 31).status_code == 201  # outside the window


def test_duration_and_window_rules():
    admin = _user(_org(), "a")
    room_id = _room(admin, rate=750)
    for start, end in ((50, 50), (50, 49), (50, 59), (-2, -1)):
        resp = _book(admin, room_id, start, end)
        assert resp.status_code == 400 and resp.json()["code"] == "INVALID_BOOKING_WINDOW"
    half_hour = client.post(
        "/bookings",
        json={
            "room_id": room_id,
            "start_time": _future(50),
            "end_time": _future(51).replace(":00:00", ":30:00"),
        },
        headers=admin["h"],
    )
    assert half_hour.status_code == 400
    eight = _book(admin, room_id, 50, 58)
    assert eight.status_code == 201 and eight.json()["price_cents"] == 750 * 8


def test_offset_input_is_stored_as_utc():
    admin = _user(_org(), "a")
    room_id = _room(admin)
    start = (datetime.now(timezone.utc) + timedelta(days=3)).replace(minute=0, second=0, microsecond=0)
    local = start.astimezone(timezone(timedelta(hours=5, minutes=30)))
    resp = client.post(
        "/bookings",
        json={
            "room_id": room_id,
            "start_time": local.isoformat(),
            "end_time": (local + timedelta(hours=1)).isoformat(),
        },
        headers=admin["h"],
    )
    assert resp.status_code == 201
    assert datetime.fromisoformat(resp.json()["start_time"].replace("Z", "+00:00")) == start
    assert resp.json()["start_time"].endswith(("Z", "+00:00"))


def test_cancel_refund_tiers_single_refund_log_and_stats():
    admin = _user(_org(), "a")
    room_id = _room(admin, rate=1001)
    expected = {50: (100, 1001), 30: (50, 501), 2: (0, 0)}
    for start, (percent, amount) in expected.items():
        booking_id = _book(admin, room_id, start, start + 1).json()["id"]
        cancel = client.post(f"/bookings/{booking_id}/cancel", headers=admin["h"])
        assert cancel.status_code == 200
        assert cancel.json() == {
            "id": booking_id,
            "status": "cancelled",
            "refund_percent": percent,
            "refund_amount_cents": amount,
        }
        again = client.post(f"/bookings/{booking_id}/cancel", headers=admin["h"])
        assert again.status_code == 409 and again.json()["code"] == "ALREADY_CANCELLED"
        refunds = client.get(f"/bookings/{booking_id}", headers=admin["h"]).json()["refunds"]
        assert [r["amount_cents"] for r in refunds] == [amount]
    stats = client.get(f"/rooms/{room_id}/stats", headers=admin["h"]).json()
    assert stats == {"room_id": room_id, "total_confirmed_bookings": 0, "total_revenue_cents": 0}


def test_token_claims_refresh_rotation_and_logout():
    admin = _user(_org(), "a")
    claims = jwt.decode(admin["access_token"], options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 900
    assert claims["sub"] == str(admin["user_id"]) and claims["type"] == "access"
    assert claims["org"] == admin["org_id"] and claims["role"] == "admin" and claims["jti"]
    refresh_claims = jwt.decode(admin["refresh_token"], options={"verify_signature": False})
    assert refresh_claims["exp"] - refresh_claims["iat"] == 7 * 24 * 3600

    rotated = client.post("/auth/refresh", json={"refresh_token": admin["refresh_token"]})
    assert rotated.status_code == 200
    assert set(rotated.json()) == {"access_token", "refresh_token", "token_type"}
    reuse = client.post("/auth/refresh", json={"refresh_token": admin["refresh_token"]})
    assert reuse.status_code == 401

    assert client.post("/auth/logout", headers=admin["h"]).status_code == 200
    assert client.get("/rooms", headers=admin["h"]).status_code == 401
    new_h = {"Authorization": f"Bearer {rotated.json()['access_token']}"}
    assert client.get("/rooms", headers=new_h).status_code == 200


def test_registration_roles_and_bad_credentials():
    org = _org()
    assert _user(org, "a")["role"] == "admin"
    assert _user(org, "m")["role"] == "member"
    dup = client.post("/auth/register", json={"org_name": org, "username": "m", "password": "x"})
    assert dup.status_code == 409 and dup.json()["code"] == "USERNAME_TAKEN"
    bad = client.post("/auth/login", json={"org_name": org, "username": "m", "password": "nope"})
    assert bad.status_code == 401 and bad.json()["code"] == "INVALID_CREDENTIALS"


def test_multitenancy_and_member_visibility():
    org = _org()
    admin, alice, bob = _user(org, "a"), _user(org, "alice"), _user(org, "bob")
    outsider = _user(_org(), "x")
    room_id = _room(admin)
    booking_id = _book(alice, room_id, 50, 51).json()["id"]

    assert client.post("/rooms", json={"name": "N", "capacity": 1, "hourly_rate_cents": 1},
                       headers=alice["h"]).status_code == 403
    assert client.get("/admin/usage-report", params={"from": "2030-01-01", "to": "2030-01-01"},
                      headers=alice["h"]).status_code == 403
    assert client.get(f"/bookings/{booking_id}", headers=admin["h"]).status_code == 200
    for user in (bob, outsider):
        for resp in (
            client.get(f"/bookings/{booking_id}", headers=user["h"]),
            client.post(f"/bookings/{booking_id}/cancel", headers=user["h"]),
        ):
            assert resp.status_code == 404 and resp.json()["code"] == "BOOKING_NOT_FOUND"
    for path in (f"/rooms/{room_id}/stats", f"/rooms/{room_id}/availability?date=2030-01-01"):
        resp = client.get(path, headers=outsider["h"])
        assert resp.status_code == 404 and resp.json()["code"] == "ROOM_NOT_FOUND"
    assert _book(outsider, room_id, 60, 61).status_code == 404
    assert client.get("/admin/export", params={"room_id": room_id},
                      headers=outsider["h"]).status_code == 404
    assert client.get("/rooms", headers=outsider["h"]).json() == []
    assert client.post(f"/bookings/{booking_id}/cancel", headers=admin["h"]).status_code == 200


def test_usage_report_counts_confirmed_bookings_in_range_per_room():
    admin = _user(_org(), "a")
    busy, idle = _room(admin, rate=300), _room(admin, rate=999)
    dropped = _book(admin, busy, 50, 51).json()
    client.post(f"/bookings/{dropped['id']}/cancel", headers=admin["h"])
    kept = _book(admin, busy, 50, 52).json()  # same slot: cancelling freed it, same UTC day
    _book(admin, busy, 60, 61)
    day = kept["start_time"][:10]
    report = client.get("/admin/usage-report", params={"from": day, "to": day},
                        headers=admin["h"]).json()
    rows = {r["room_id"]: r for r in report["rooms"]}
    assert report["from"] == day and set(rows) == {busy, idle}
    on_day = [b["price_cents"] for b in client.get("/bookings", params={"limit": 100},
              headers=admin["h"]).json()["items"]
              if b["status"] == "confirmed" and b["start_time"][:10] == day]
    assert rows[busy]["confirmed_bookings"] == len(on_day) >= 1
    assert rows[busy]["revenue_cents"] == sum(on_day) >= 600
    assert rows[idle] == {"room_id": idle, "room_name": "R", "confirmed_bookings": 0, "revenue_cents": 0}


def test_export_header_and_scope():
    org = _org()
    admin, member = _user(org, "a"), _user(org, "m")
    room_id = _room(admin)
    mine = _book(admin, room_id, 50, 51).json()["id"]
    theirs = _book(member, room_id, 60, 61).json()["id"]

    def ids(**params):
        resp = client.get("/admin/export", params=params, headers=admin["h"])
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
        rows = list(csv.reader(io.StringIO(resp.text)))
        assert rows[0] == "id,reference_code,room_id,user_id,start_time,end_time,status,price_cents".split(",")
        return [int(r[0]) for r in rows[1:]]

    assert ids() == [mine]
    assert ids(include_all="true") == [mine, theirs]
    assert client.get("/admin/export", headers=member["h"]).status_code == 403
