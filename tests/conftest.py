from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.normalizer import normalize_record


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'test.db'}", scraper_delay=0, scraper_retries=0, enable_scheduler=False)


@pytest.fixture
def application(settings):
    return create_app(settings)


@pytest.fixture
def client(application):
    with TestClient(application, base_url="http://127.0.0.1") as client:
        yield client


@pytest.fixture
def sessions(client, application):
    return application.state.sessions


@pytest.fixture
def item():
    return normalize_record({"title": "Roadway and stormwater design RFQ", "agency": "Test City", "source_name": "Test source", "source_url": "https://example.invalid/", "opportunity_url": "https://example.invalid/bids/1", "description": "Professional civil engineering consulting services for roadway and drainage design.", "state": "Mississippi", "due_date": date(2026, 10, 1), "posted_date": date(2026, 9, 20), "solicitation_number": "TEST-001"})


@pytest.fixture
def csrf(client):
    return {"X-CSRF-Token": client.get("/api/health").json()["csrf_token"]}
