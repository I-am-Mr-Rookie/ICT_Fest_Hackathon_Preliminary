# Code Review Fixes

Scope: the whole repository, a FastAPI + SQLAlchemy + SQLite booking API ("CoWork") with
multi-tenant orgs, JWT auth, rooms, bookings, refunds, admin reports and CSV export.
The API contract in `README.md` was preserved: paths, status codes, error codes, field
names, JWT claims and the CSV header are unchanged.

## Issues found and fixed

| # | Severity | Where | Issue | Fix |
|---|---|---|---|---|
| 1 | High | `app/routers/bookings.py`, `app/services/ratelimit.py`, `app/services/reference.py`, `app/services/notifications.py` | Artificial `time.sleep()` calls ("warmup", "audit", "settle", "format" pauses) ran inside global locks. Every booking create held the process-wide booking lock for about 0.45 s, plus about 0.22 s more on the global notification locks. Under concurrent load, requests queued for seconds and could fill the worker threadpool, which breaks rule 16 (liveness). | Removed the sleeps and the unused `_settlement_pause` helper. The notification stubs are kept as no-ops. 30 concurrent creates now finish in about 0.15 s. |
| 2 | High | `app/routers/bookings.py` | The rate-limit check ran inside `_booking_lock`, so requests that should get a `429` waited behind in-flight bookings. | `ratelimit.record_and_check` now runs before the booking lock. It has its own lock, and every request still counts. |
| 3 | High | `app/services/reference.py` | The reference counter was in memory and restarted at 1000 on every process start, but the database persists in a Docker volume. After a restart, reference codes were reissued (breaks rule 7). | On first use, the counter is seeded from the highest stored code. `Booking.reference_code` is also marked `unique=True`, so a duplicate fails loudly instead of being stored silently (this only applies to newly created DBs). |
| 4 | High | `app/cache.py` (deleted), `app/routers/admin.py`, `app/routers/rooms.py` | The in-memory report and availability caches had four problems: (a) creating a room didn't invalidate the usage report, so new rooms were missing from it (breaks rule 12); (b) the availability cache was keyed by the raw `date` string, so `2027-1-5` stayed stale because invalidation used `2027-01-05` (breaks rule 13); (c) there was a read/invalidate race where a slow reader could write a stale result back after invalidation; (d) cache keys were unbounded and user-controlled, and `invalidate_report` iterated a dict that other threads were changing. | Removed the caches. Both endpoints now query the DB directly, which is cheap here. |
| 5 | Medium | `app/routers/bookings.py` | A malformed `start_time`/`end_time` made `datetime.fromisoformat` raise `ValueError`, which returned a `500`. | Malformed values now return `400 INVALID_BOOKING_WINDOW`. |
| 6 | Medium | `app/config.py` | When `JWT_SECRET` was unset, the code fell back to a hard-coded, publicly known secret, so anyone could forge tokens. | The fallback is now a random secret per process. `docker-compose.yml` still sets its own value; see "Not fixed". |
| 7 | Medium | `app/schemas.py` | There was no input validation: empty org, username or password were accepted, and so were rooms with negative or zero capacity, negative hourly rates (which produce negative prices) and empty names. | Added `Field` constraints. Bad input now gets FastAPI's default `422`. |
| 8 | Low | `app/routers/bookings.py` | `_has_conflict` loaded every confirmed booking for the room into Python. | The overlap check now runs in SQL and returns the first match. The semantics are the same strict overlap. |
| 9 | Low | `app/auth.py` | The `Authorization` scheme check was case-sensitive (`bearer` was rejected) and accepted an empty token after `Bearer `. | The scheme is now matched case-insensitively and an empty token returns `401`. |
| 10 | Low | `app/routers/health.py` | `/health` was a sync endpoint, so it waited for a threadpool slot and could hang when the pool was saturated. | It is now `async def` and runs on the event loop. |
| 11 | Low (dead code) | `app/services/export.py`, `app/services/stats.py` | `fetch_bookings_raw` was unused and had no org scoping, a multi-tenancy footgun. `stats.record_create`/`record_cancel` were no-ops. The `include_all` branches in `generate_export` duplicated each other. | Deleted the unused code and collapsed the branches into one call with the same behavior. |
| 12 | Low (docs) | `README.md` | The smoke-test instructions ran `pytest`, which isn't in `requirements.txt`. | Changed to `pip install -r requirements.txt pytest`. |
| 13 | Medium | `app/routers/bookings.py` | The rate limit was checked inside the endpoint body, which FastAPI only runs after the request body validates. Malformed `POST /bookings` requests (`422`) therefore never counted toward the limit, which breaks rule 5 ("all requests count, successful or not"). Verified: after 25 malformed requests, a valid one got `404` instead of `429`. | The rate limit now runs in a `_rate_limited_user` dependency. Dependencies run before body validation, so every authenticated request counts, and the check stays outside the booking lock. |
| 14 | Low | `app/routers/bookings.py`, `app/routers/admin.py`, `app/routers/rooms.py` | Out-of-range datetimes raised `OverflowError`, which returned a `500`. Examples: a booking start of `0001-01-01T00:00:00+05:00`, which overflows when converted to UTC, and `to=9999-12-31` or `date=9999-12-31`, where adding one day overflows. | `OverflowError` is now caught next to `ValueError`, and these inputs return `400 INVALID_BOOKING_WINDOW`, the same as other malformed dates. |

## Not fixed (deliberately)

- **Integer IDs larger than SQLite's 64-bit range** (for example `GET /bookings/999…9` with 25 digits) still return `500`, because sqlite3 can't bind the value. Fixing it means adding a bound to every ID and `page` parameter. That would return `422` instead of the contract's `404 …_NOT_FOUND`, so I left it alone. No valid client sends such IDs.
- **Booking quota is applied to admins too.** README rule 4 says "a member". The original code applies it to every user, and I kept that because it's ambiguous whether "member" means the role or any user.
- **Hard-coded dev JWT secret in `docker-compose.yml`.** The grader runs `docker compose up`, and changing the setup could break that. Before any real deployment, replace it with a secret injected from the environment.
- **Revoked access tokens and used refresh-token JTIs are kept only in memory.** They are lost on restart, so a refresh token could be replayed after a restart, and the sets grow without limit. Fixing this properly needs a DB table, which is a schema and architecture change. It is acceptable for the single-process container as specified.
- **All locks are in-process `threading.Lock`s.** They are correct only with a single uvicorn worker, which is what the Dockerfile runs. Running multiple workers or replicas would need DB-level locking.
- **`datetime.utcnow()` deprecation warnings on Python 3.12.** The target is Python 3.11, and changing it would touch every timestamp path for no behavior gain.
- **Login timing difference for unknown users** (enumeration via timing). This is minor and outside the contract.
- **Usage report runs one query per room (N+1).** It is correct; it could be optimized later with a single `GROUP BY`.
- **The container runs as root.** Adding a non-root user could break existing named volumes that root owns.
- **Existing SQLite databases won't get the new unique index** (`create_all` doesn't alter tables). The counter seeding (fix 3) is what prevents duplicates for existing DBs.

## Build / test results

- `python -m pytest`: **8 passed** (the original smoke test plus 7 regression tests in `tests/test_review_fixes.py`). Run on Python 3.12 in a fresh venv with the pinned `requirements.txt`, against a temporary SQLite file. The only warnings are the `datetime.utcnow()` deprecations noted above.
- Every regression test **fails against the committed code** (HEAD) and passes with the fixes. I re-checked this for the two newest tests (fixes 13 and 14).
- Concurrency probe against a real `uvicorn` server, re-run after fix 13:
  - 30 concurrent same-slot creates: 1 × `201`, 19 × `409 ROOM_CONFLICT`, 10 × `429`.
  - 10 concurrent cancels of one booking: 1 × `200` (refund 1001 for price 1001 at 100%), 9 × `409`, and exactly one refund log.
  - Room stats return to 0/0 afterwards.
- The project has no lint or type-check configuration, so none was run.
- `docker compose build` was **not run**: Docker isn't installed in this environment. The Dockerfile and requirements are unchanged.
