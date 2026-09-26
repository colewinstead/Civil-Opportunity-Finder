from datetime import date, timedelta

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.config import DEFAULT_WEIGHTS
from app.main import create_app
from app.models import Opportunity
from app.services.deduplicator import upsert_opportunity


def seed(sessions, item, **updates):
    with sessions.begin() as session:
        record, _ = upsert_opportunity(session, item.model_copy(update=updates), DEFAULT_WEIGHTS)
        return record.id


def test_startup_health_and_empty_pages(client, application):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert response.json()["scheduler_enabled"] is False
    assert application.state.scheduler is None
    assert client.get("/api/opportunities").json()["total"] == 0
    assert "Your workspace is ready." in client.get("/").text
    assert client.get("/sources").status_code == 200
    assert "offline_fixture" in client.get("/api/sources").text
    assert client.get("/static/vendor/bootstrap.min.css").status_code == 200


def test_filtering_and_detail(client, sessions, item):
    record_id = seed(sessions, item, county="Hinds", city="Jackson")
    result = client.get("/api/opportunities", params={"q": "stormwater", "category": "DRAINAGE", "agency": "Test City", "county": "Hinds", "city": "Jackson", "source": "Test source", "min_score": 70, "due_from": "2026-09-30", "due_to": "2026-10-02", "status": "NEW"})
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["id"] == record_id
    assert client.get("/api/opportunities?min_score=100").json()["total"] == 1
    assert client.get("/api/opportunities?county=Other").json()["total"] == 0
    assert client.get(f"/api/opportunities/{record_id}").json()["first_seen"].endswith("Z")
    assert "Project description" in client.get(f"/opportunities/{record_id}").text
    assert client.get("/?category=DRAINAGE&q=stormwater").status_code == 200


@pytest.mark.parametrize("query", ["category=BAD", "status=BAD", "min_score=101", "page=0", "page_size=101", "sort=BAD", "due_from=invalid", "due_from=2027-01-01&due_to=2026-01-01"])
def test_invalid_filters(client, query):
    assert client.get("/api/opportunities?" + query).status_code == 422
    assert client.get("/?" + query).status_code == 422


def test_nulls_last_and_pagination(client, sessions, item):
    known = seed(sessions, item)
    unknown = seed(sessions, item, title="Water main design", solicitation_number="TEST-002", opportunity_url="https://example.invalid/2", due_date=None, posted_date=None)
    for sort in ("due_date", "posted_date"):
        result = client.get(f"/api/opportunities?sort={sort}&page_size=1").json()
        assert result["items"][0]["id"] == known
        assert result["total"] == 2
        assert client.get(f"/api/opportunities?sort={sort}&page_size=1&page=2").json()["items"][0]["id"] == unknown
    assert client.get("/api/opportunities?sort=newest").json()["items"][0]["id"] == unknown


def test_literal_search_wildcards(client, sessions, item):
    seed(sessions, item)
    assert client.get("/api/opportunities", params={"q": "%"}).json()["total"] == 0


@pytest.mark.parametrize("status", ["NEW", "REVIEWING", "INTERESTED", "NOT_INTERESTED", "SUBMITTED", "ARCHIVED"])
def test_status_patch(client, sessions, item, csrf, status):
    record_id = seed(sessions, item)
    response = client.patch(f"/api/opportunities/{record_id}", json={"status": status}, headers=csrf)
    assert response.status_code == 200
    assert response.json()["status"] == status


def test_status_only_contract(client, sessions, item, csrf):
    record_id = seed(sessions, item)
    assert client.patch(f"/api/opportunities/{record_id}", json={"status": "INVALID"}, headers=csrf).status_code == 422
    assert client.patch(f"/api/opportunities/{record_id}", json={"status": "NEW", "title": "Altered"}, headers=csrf).status_code == 422


def test_browser_status_forms(client, sessions, item, csrf):
    record_id = seed(sessions, item)
    html = BeautifulSoup(client.get(f"/opportunities/{record_id}").text, "html.parser")
    forms = html.select("form")
    assert len(forms) == 2
    assert forms[0].select_one("select") is None
    assert client.get(f"/opportunities/{record_id}").headers["referrer-policy"] == "same-origin"
    result = client.post(f"/opportunities/{record_id}/status", data={"status": "INTERESTED", "csrf_token": csrf["X-CSRF-Token"]}, headers={"Origin": "http://127.0.0.1"}, follow_redirects=False)
    assert result.status_code == 303
    assert client.get(f"/api/opportunities/{record_id}").json()["status"] == "INTERESTED"


def test_csrf_and_origin_protection(client, sessions, item, csrf):
    record_id = seed(sessions, item)
    url = f"/api/opportunities/{record_id}"
    assert client.patch(url, json={"status": "INTERESTED"}).status_code == 403
    assert client.patch(url, json={"status": "INTERESTED"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.patch(url, json={"status": "INTERESTED"}, headers=csrf | {"Origin": "https://attacker.invalid"}).status_code == 403
    assert client.patch(url, json={"status": "INTERESTED"}, headers=csrf | {"Origin": "null"}).status_code == 403
    assert client.patch(url, json={"status": "INTERESTED"}, headers=csrf | {"Origin": "http://[malformed"}).status_code == 403
    assert client.patch(url, json={"status": "INTERESTED"}, headers=csrf | {"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/", headers={"Host": "attacker.invalid"}).status_code == 400


def test_scrape_api_runs_and_overlap(client, application, csrf):
    response = client.post("/api/scrape", headers=csrf)
    assert response.status_code == 202
    run = client.get(response.json()["status_url"]).json()
    assert run["run"]["outcome"] == "SUCCEEDED"
    assert run["run"]["records_discovered"] == 0
    assert client.post("/api/scrape/missing", headers=csrf).status_code == 404
    assert client.post("/api/scrape/demo-fixture", headers=csrf).status_code == 404
    run_id = application.state.collection.reserve()
    try:
        assert client.post("/api/scrape", headers=csrf).status_code == 409
    finally:
        application.state.collection.execute(run_id)


def test_missing_records(client, csrf):
    assert client.get("/api/opportunities/999").status_code == 404
    assert client.get("/opportunities/999").status_code == 404
    assert client.get("/api/scrape-runs/missing").status_code == 404
    assert client.patch("/api/opportunities/999", json={"status": "NEW"}, headers=csrf).status_code == 404


def test_rendering_escapes_content_and_labels_deadlines(client, sessions, item):
    record_id = seed(sessions, item, title='<script>alert("x")</script>', description='<img src=x onerror="alert(1)">', due_date=date.today() - timedelta(days=1))
    result = client.get(f"/opportunities/{record_id}")
    assert '<script>alert("x")</script>' not in result.text
    assert "&lt;script&gt;" in result.text
    assert "Deadline passed" in result.text
    assert client.get("/").headers["content-security-policy"].startswith("default-src 'self'")
    with sessions.begin() as session:
        session.get(Opportunity, record_id).due_date = date.today() + timedelta(days=1)
    assert "Due soon" in client.get("/").text


def test_scheduler_lifecycle(settings):
    settings = settings.model_copy(update={"enable_scheduler": True, "scrape_hour": 7})
    application = create_app(settings)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").json()["scheduler_enabled"] is True
        job = application.state.scheduler.get_job("daily_collection")
        assert job is not None
        assert str(job.trigger.timezone) == "America/Chicago"
        assert job.max_instances == 1
    assert not application.state.scheduler.running
