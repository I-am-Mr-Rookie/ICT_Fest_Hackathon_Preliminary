"""The static browser UI is served at /ui/ without shadowing API routes."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_ui_served():
    page = client.get("/ui/")
    assert page.status_code == 200
    assert "CoWork" in page.text
    assert client.get("/ui/app.js").status_code == 200
    assert client.get("/ui/styles.css").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}
