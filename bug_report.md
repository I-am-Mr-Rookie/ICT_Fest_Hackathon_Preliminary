# Bug Report

This report summarizes the bugs fixed for the CoWork multi-tenant booking API preliminary challenge. The fixes preserve the frozen API contract: paths, status codes, error codes, response field names, JWT claims, and CSV header.

| # | File(s) | Rule | Wrong behavior observed | Root cause | Fix summary | Difficulty |
|---|---|---:|---|---|---|---|
| 1 | `app/timeutils.py` | 1 | Datetimes submitted with timezone offsets were stored as the same wall-clock time instead of UTC. | `parse_input_datetime()` stripped `tzinfo` without converting. | Convert aware datetimes to UTC first, then store as naive UTC. | Easy |
| 2 | `app/routers/auth.py` | 8 | Access tokens lasted about 15 hours instead of 15 minutes. | Expiry used `15 * 60` minutes. | Issue access tokens with exactly 900 seconds between `iat` and `exp`. | Easy |
| 3 | `app/auth.py` | 8 | Logged-out access tokens could still be used. | Blacklist stored `jti` but checked `sub`. | Check the token `jti` against the blacklist. | Easy |
| 4 | `app/routers/bookings.py` | 2 | Bookings slightly in the past were accepted. | A 5-minute grace window was allowed. | Reject any `start_time <= now` with `INVALID_BOOKING_WINDOW`. | Easy |
| 5 | `app/routers/bookings.py` | 3 | Adjacent bookings such as 10-11 and 11-12 conflicted. | Overlap check used inclusive boundary logic. | Use strict interval overlap: `existing.start < new.end` and `new.start < existing.end`. | Easy |
| 6 | `app/routers/bookings.py` | 6 | Refund tiers were wrong near 48h/24h and short-notice cancels. | Tier comparisons used the wrong branch thresholds. | Apply 100% for at least 48h, 50% for 24-48h, and 0% below 24h. | Easy |
| 7 | `app/routers/auth.py` | 15 | Registering an existing username returned or created invalid state instead of `409 USERNAME_TAKEN`. | Duplicate user handling did not reject an existing `(org_id, username)`. | Check for existing username and map duplicate insert races to `USERNAME_TAKEN`. | Easy |
| 8 | `app/routers/bookings.py` | 11 | Booking list order was newest-first. | Query ordered by descending start time. | Sort by `start_time ASC, id ASC`. | Easy |
| 9 | `app/routers/bookings.py` | 11 | Page 1 skipped the first page of results. | Offset used `page * limit`. | Use `(page - 1) * limit`. | Easy |
| 10 | `app/routers/bookings.py` | 11 | `limit` query parameter was ignored. | Query used a hardcoded limit of 10. | Apply the requested `limit`. | Easy |
| 11 | `app/routers/bookings.py` | 10 | A member could fetch another member's booking inside the same org. | Detail endpoint lacked member-owner filtering. | Return `404 BOOKING_NOT_FOUND` for non-owner members. | Easy |
| 12 | `app/routers/bookings.py` | 1 | Booking detail returned `created_at` in the `start_time` field. | Response code overwrote serialized `start_time`. | Remove the clobbering assignment. | Easy |
| 13 | `app/routers/auth.py` | 8 | Refresh tokens were reusable. | Refresh token `jti` values were never consumed. | Track used refresh `jti`s behind a lock and reject reuse with 401. | Medium |
| 14 | `app/routers/bookings.py` | 2 | Zero-length or negative bookings could pass validation. | Minimum duration constant existed but was not enforced. | Require whole-hour duration from 1 to 8 hours. | Medium |
| 15 | `app/services/refunds.py`, `app/routers/bookings.py` | 6 | Cancel response and refund ledger could disagree, e.g. 50% of 1001 cents. | Response used `round()` while ledger recomputed with float truncation. | Compute refund once with integer half-up math: `(price_cents * pct + 50) // 100`. | Medium |
| 16 | `app/routers/admin.py`, `app/services/export.py` | 9 | `include_all=true&room_id=X` could export a foreign org room. | Export path bypassed org-scoped room validation. | Validate `room_id` belongs to admin org and use org-scoped export query. | Medium |
| 17 | `app/routers/bookings.py` | 12 | Usage reports stayed stale after booking creation. | Create path invalidated availability but not report cache. | Invalidate the org usage-report cache after create. | Medium |
| 18 | `app/routers/bookings.py` | 13 | Availability stayed busy after cancellation. | Cancel path invalidated reports but not availability cache. | Invalidate the room/date availability cache after cancel. | Medium |
| 19 | `app/services/notifications.py` | 16 | Concurrent create/cancel notifications could deadlock. | Created/cancelled paths acquired email/audit locks in opposite nested orders. | Remove nested lock acquisition and avoid holding one notification lock while waiting on the other. | Hard |
| 20 | `app/services/ratelimit.py` | 5 | Concurrent booking requests could undercount the per-minute bucket. | Bucket trim/append/check was a read-modify-write without a lock. | Guard bucket update and limit check with a module-level lock. | Hard |
| 21 | `app/services/reference.py` | 7 | Concurrent bookings could receive duplicate reference codes. | Counter read/sleep/write was unsynchronized. | Guard reference allocation with a module-level lock. | Hard |
| 22 | `app/services/stats.py`, `app/routers/rooms.py` | 14 | Room stats could drift under create/cancel bursts or process restarts. | Stats endpoint trusted in-memory counters. | Compute count and revenue live from confirmed booking rows. | Hard |
| 23 | `app/routers/bookings.py` | 3 | Concurrent same-slot booking requests could both be confirmed. | Conflict check and insert were not atomic. | Serialize booking creation from rate-limit check through DB commit with a booking lock. | Hard |
| 24 | `app/routers/bookings.py` | 4 | Concurrent requests could exceed the 3-booking quota window. | Quota count and insert were not atomic. | Use the same booking creation critical section around quota count and commit. | Hard |
| 25 | `app/routers/bookings.py`, `app/services/refunds.py` | 6 | Concurrent cancellation could create multiple refund logs or double-update stats. | Status check, refund insert, and status update were separate operations; refund helper committed internally. | Gate cancellation with a conditional `status='confirmed'` update, write one refund only for the winner, and commit refund plus status together. | Hard |

## Verification

- `python -m pytest` passed: 1 test, 1 warning.
- Focused probes were run after individual fixes for auth, booking validation, overlap, pagination, owner visibility, refund math, export scoping, cache invalidation, and concurrency.
- Final consolidated HTTP-level probe passed across auth, booking windows, timezone conversion, pagination, export scoping, cache invalidation, rate limiting, double-booking, quota, cancel atomicity, and live stats.
