# Frontend notes

## What existed before

No frontend. The repository was an API-only FastAPI service (`app/`), with no
templates, static files, JS framework or Node tooling. The only built-in UI was
FastAPI's auto-generated `/docs`.

## What was added / changed

Stack: plain static HTML/CSS/JS, served by the existing FastAPI app. It adds
no build step and no new dependencies (Python or npm), and fetches no external
fonts or assets.

| File | Change |
|---|---|
| `frontend/index.html` | **New.** Single-page UI: log in / register tabs; rooms list with live stats; new-booking form (room, local start time, 1–8 h duration); availability lookup by UTC date; paginated "My bookings" table; booking detail dialog with refunds and cancel; admin-only panel (create room, usage report, CSV export). |
| `frontend/styles.css` | **New.** Light mint/green palette, monospace for references, times and money, responsive grid (one column on phones), tables scroll horizontally, visible focus rings, respects `prefers-reduced-motion`. |
| `frontend/app.js` | **New.** Vanilla JS client for the documented API. Stores tokens in `sessionStorage`. On a `401` it rotates tokens once through `/auth/refresh`, then signs out. It reads `role` from the JWT only to show or hide the admin panel (the server still enforces permissions). All server strings are HTML-escaped before rendering. Converts local `datetime-local` input to UTC ISO for `POST /bookings`. |
| `app/main.py` | Mounts `frontend/` at **`/ui`** with `StaticFiles(html=True)`. No existing route, status code or response shape changed. Same origin, so no CORS config was needed. |
| `tests/test_frontend.py` | **New.** Checks that `/ui/`, `/ui/app.js` and `/ui/styles.css` are served and `/health` still works. |
| `README.md` | One line under Setup pointing to `/ui/`. |

Accessibility: a skip link, labelled form controls, ARIA tabs for auth, `aria-live`
regions for toasts, rooms and availability, `scope` on table headers, a native
`<dialog>` for booking details, and 2.5rem minimum control height.

## How to run

```bash
docker compose up --build
# open http://localhost:8000/ui/
```

Or locally:

```bash
pip install -r requirements.txt
JWT_SECRET=dev uvicorn app.main:app --port 8000
# open http://localhost:8000/ui/
```

Register with a new organization name to become its admin, create a room, then book it.

Tests: `pip install pytest httpx && pytest` (9 passed).

## Verification done

- `pytest`: all 9 tests pass, including the new frontend test.
- `node --check frontend/app.js` passes.
- Against a live uvicorn, every request shape the UI sends was exercised with
  curl: register, login, create room, book with `toISOString()` timestamps,
  list, availability, cancel (refund 100%), CSV export, logout (old token → 401).
- **Not done:** a real browser run. Headless Chromium could not start on this
  machine because system libraries such as `libatk` are missing and there is no
  sudo. The visual layout and responsiveness were not checked on screen.
