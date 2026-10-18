"""CoWork API application entrypoint."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .errors import AppError, app_error_handler
from .routers import admin, auth, bookings, health, rooms

Base.metadata.create_all(bind=engine)

app = FastAPI(title="CoWork API", version="1.0.0")

app.add_exception_handler(AppError, app_error_handler)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(rooms.router)
app.include_router(bookings.router)
app.include_router(admin.router)

# Browser UI (static files in frontend/), mounted off the API paths.
app.mount(
    "/ui",
    StaticFiles(directory=Path(__file__).resolve().parent.parent / "frontend", html=True),
    name="ui",
)
