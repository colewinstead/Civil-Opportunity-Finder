from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.scrapers.base import PoliteHTTPClient, ScraperError
from app.scrapers.fixture import FixtureScraper

FIXTURES = Path(__file__).parent / "fixtures"


def test_saved_demo_fixture(settings):
    records = FixtureScraper(settings).run()
    assert len(records) == 3
    assert records[0].state == "MS"
    assert records[0].opportunity_url == "https://example.invalid/demo/roadway-design"
    assert records[1].posted_date is None


def test_optional_fields(settings):
    scraper = FixtureScraper(settings)
    records = scraper.normalize(scraper.parse((FIXTURES / "minimal.html").read_text()))
    assert records[0].due_date is None
    assert records[0].opportunity_url is None


@pytest.mark.parametrize("content", ["<html>Site changed</html>", (FIXTURES / "malformed.html").read_text()])
def test_structural_errors_visible(settings, content):
    with pytest.raises(ScraperError):
        FixtureScraper(settings).parse(content)


def test_robots_disallow(settings):
    requests = []
    def handle(request):
        requests.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /private", headers={"content-type": "text/plain"})
    http = PoliteHTTPClient(settings, httpx.MockTransport(handle))
    try:
        with pytest.raises(ScraperError, match="disallows"):
            http.get("https://example.invalid/private")
        assert requests == ["/robots.txt"]
    finally:
        http.close()


@pytest.mark.parametrize("status,text", [(403, "denied"), (404, "missing"), (200, "<html>error</html>")])
def test_unverifiable_robots_fails(settings, status, text):
    http = PoliteHTTPClient(settings, httpx.MockTransport(lambda request: httpx.Response(status, text=text)))
    try:
        with pytest.raises(ScraperError, match="robots"):
            http.get("https://example.invalid/bids")
    finally:
        http.close()


def test_redirect_target_checked(settings):
    requested = []
    def handle(request):
        requested.append((request.url.host, request.url.path))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /" if request.url.host == "blocked.invalid" else "User-agent: *\nAllow: /")
        return httpx.Response(302, headers={"location": "https://blocked.invalid/bids"})
    http = PoliteHTTPClient(settings, httpx.MockTransport(handle))
    try:
        with pytest.raises(ScraperError, match="disallows"):
            http.get("https://example.invalid/bids")
        assert ("blocked.invalid", "/bids") not in requested
    finally:
        http.close()


def test_retry_after_and_backoff(settings, monkeypatch):
    settings = settings.model_copy(update={"scraper_retries": 2})
    sleeps = []
    monkeypatch.setattr("app.scrapers.base.time.sleep", sleeps.append)
    calls = 0
    def handle(request):
        nonlocal calls
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        if calls == 2:
            return httpx.Response(503)
        return httpx.Response(200, text="Success")
    http = PoliteHTTPClient(settings, httpx.MockTransport(handle))
    try:
        assert http.get("https://example.invalid/bids") == "Success"
        assert sleeps == [3, 2]
    finally:
        http.close()


def test_timeout_failure_is_meaningful(settings):
    def handle(request):
        raise httpx.ReadTimeout("Timed out", request=request)
    http = PoliteHTTPClient(settings, httpx.MockTransport(handle))
    try:
        with pytest.raises(ScraperError, match="Timed out"):
            http.get("https://example.invalid/bids")
    finally:
        http.close()
