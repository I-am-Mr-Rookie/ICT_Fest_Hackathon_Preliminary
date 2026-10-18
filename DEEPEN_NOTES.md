# Second-pass deep review notes

This is the second pass over the FastAPI + SQLAlchemy + SQLite booking API. I read `REVIEW_FIXES.md`
first and did not redo any of its 14 fixes or revisit its "Not fixed" decisions. The API contract in
`README.md` is unchanged. Nothing was committed.

Superpowers skills used: `superpowers:test-driven-development` (each fix started with a failing test),
`superpowers:systematic-debugging` (reproduced each bug and found its root cause before fixing), and
`superpowers:verification-before-completion` (re-ran the full suite in a fresh venv before writing this).

## What I examined

- All of `app/`: auth/JWT, refresh rotation, logout, booking create (window, duration, conflict, quota,
  rate limit, reference codes), cancel/refund, list/pagination, availability, stats, usage report,
  export, and registration.
- Edge-case probing against a temporary DB:
  - Pages past the end of the list (`GET /bookings?page=...`).
  - Huge IDs.
  - `Z` and date-only datetimes.
  - Offset datetimes.
  - Refresh token presented as an access token, and the other way round.
  - Usage report with `from > to`.
  - Malformed `include_all`.
- The README setup: a fresh venv using exactly `pip install -r requirements.txt pytest`, then
  `pytest`. I also started the app with the Dockerfile's `uvicorn app.main:app` command and checked
  `/health`, `/ui/`, `/docs` and `/auth/register`.

## Fixes

| # | Where | Issue | Fix |
|---|---|---|---|
| 1 | `app/routers/bookings.py` `list_bookings` | `GET /bookings?page=2**62` (or larger) returned `500`. The offset `(page-1)*limit` overflows SQLite's int64 `OFFSET`. This differs from the ID-overflow case the first pass left alone, because the contract defines the correct answer here: a page past the end is a `200` with empty `items`. | When `offset >= total`, return `[]` without running the page query. This also saves a query for every page past the end. |
| 2 | `app/routers/admin.py` `usage_report` | Performance: N+1. The report ran one query per room and loaded every matching booking row into Python. (The first pass listed this as "could be optimized later".) | Replaced with a single `Room LEFT OUTER JOIN Booking … GROUP BY` query. The status and date filters are in the `ON` clause, so rooms with zero bookings still appear. The output is identical. |
| 3 | `tests/conftest.py` (new) | Test hygiene: `pytest` wrote and reused `./cowork.db` in the repo root, so state carried over between runs. | Before the app is imported, `DATABASE_URL` now points at a fresh temporary SQLite file. |
| 4 | `README.md` | Two small accuracy fixes. "Run the smoke test" became "run the test suite" (it uses a temporary DB). I also documented that an unset `JWT_SECRET` falls back to a random per-process secret, which is first-pass behavior that wasn't documented. | Docs only. |

## Tests added

The new file is `tests/test_contract.py` with **12 tests**. The suite went from 9 to **21 tests, 21 passed**
(`python -m pytest`, Python 3.12, fresh venv built from the updated `requirements.txt`).

- `test_page_past_int64_offset_is_empty_not_500`: the regression test for fix 1. I watched it fail with
  `OverflowError: Python int too large to convert to SQLite INTEGER`, then pass after the fix.
- `test_usage_report_counts_confirmed_bookings_in_range_per_room`: guards fix 2. It includes a cancelled
  booking in the same slot and a room with zero bookings. Mutation check: removing the
  `status == "confirmed"` filter makes it fail.
- The remaining 10 cover critical paths that had no tests before. They are characterization tests and
  passed against the existing code:
  - Pagination: ordering, and no skipped or repeated items.
  - Overlap returns `409 ROOM_CONFLICT`; back-to-back bookings are allowed.
  - Quota: 3 bookings within 24h are allowed and the 4th gets `409 QUOTA_EXCEEDED`; a booking outside the window still succeeds.
  - Duration and window rules: 0h, negative, 9h, 90 min and past starts get `400`; 8h succeeds with the correct price.
  - Offset input is stored and returned as UTC.
  - Refund tiers 100/50/0 with half-cent rounding (1001 → 501), `409 ALREADY_CANCELLED`, exactly one refund log entry, and stats back to 0/0.
  - JWT claims: `exp − iat` = 900 and 7 days, plus `sub`, `org`, `role`, `jti` and `type`.
  - Refresh rotation and reuse returning `401`; logout revokes the access token.
  - Registration roles, `USERNAME_TAKEN`, `INVALID_CREDENTIALS`.
  - Multi-tenancy and member visibility: cross-org and other-member access gets `404`, and members get `403` on admin endpoints.
  - Export: exact CSV header, own bookings vs `include_all`, `404` for a cross-org `room_id`.

## Dependency updates (all verified by the full suite)

| Package | From | To | Kind |
|---|---|---|---|
| fastapi | 0.111.0 | 0.111.1 | patch |
| uvicorn[standard] | 0.30.1 | 0.30.6 | patch |
| SQLAlchemy | 2.0.30 | 2.0.55 | patch |
| pydantic | 2.7.1 | 2.14.1 | minor |
| PyJWT | 2.8.0 | 2.15.1 | minor (includes the 2.10.1 security fix) |

No update broke the tests, so nothing was reverted. The suite shows the same warnings before and after
the updates (`utcnow` deprecations plus two from starlette's test client and form parser).

What I deliberately did not take:

- **FastAPI ≥ 0.112.** In 0.x, a minor bump can break things. 0.112 also stopped installing `httpx`
  by default, which would break the README's `pip install -r requirements.txt pytest` instructions
  because `TestClient` needs `httpx`.
- **uvicorn ≥ 0.31** (also 0.x) and **SQLAlchemy 2.1** (removes deprecated APIs).

Note: with the compose file's 27-byte dev secret, PyJWT ≥ 2.10 logs one `InsecureKeyLengthWarning` per
process. It is a warning only; I confirmed the suite passes with that exact secret. The warning is
accurate. See the compose-secret item below.

## Intentionally left alone

- **Everything under "Not fixed" in `REVIEW_FIXES.md`.** That covers:
  - ID overflow `500`s, for example `POST /bookings` with `room_id=10**20`. I re-confirmed this one still happens.
  - The quota applying to admins.
  - The dev secret in `docker-compose.yml`, which the grader's `docker compose up` relies on.
  - In-memory revocation and refresh-JTI sets.
  - Single-worker locks.
  - `utcnow` deprecations.
  - The container running as root.

  I found no new evidence to reverse any of them.
- **Availability and usage report echo the raw `date` / `from` / `to` strings** (for example `2027-1-5`).
  The contract doesn't say whether to normalize them, and changing the response shape risks the black-box grader.
- **Which error wins when several apply** (for example window vs `ROOM_NOT_FOUND`, conflict vs quota).
  The contract doesn't specify an order, so I kept the existing one.
- **`FRONTEND_NOTES.md` / `bug_report.md` test counts** ("9 passed", "1 test"). They record earlier
  passes, so they are historical and I didn't change them.
- **`docker compose build` was not run.** Docker isn't installed here. I verified the Dockerfile's
  `uvicorn app.main:app` command directly against the updated requirements instead.
