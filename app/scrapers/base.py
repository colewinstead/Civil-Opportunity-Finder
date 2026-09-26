"""Reusable, polite HTTP transport and source-specific parsing contract."""
import logging
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import Settings
from app.schemas.opportunity import OpportunityInput
from app.services.normalizer import canonical_url, normalize_record

logger = logging.getLogger("opportunity_finder.http")


class ScraperError(RuntimeError):
    """Visible source failure; collection continues with other sources."""


class SourceAccessError(ScraperError):
    """Access rejection or exhausted throttling: stop requesting this source."""


class PoliteHTTPClient:
    """Checks robots before each target/redirect, rate limits hosts, and retries."""
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.client = httpx.Client(timeout=settings.scraper_timeout, headers={"User-Agent": settings.scraper_user_agent}, transport=transport)
        self.robots: dict[str, RobotFileParser] = {}
        self.last_request: dict[str, float] = {}
        self.lock = threading.Lock()

    def close(self) -> None:
        self.client.close()

    def _delay(self, url: str, minimum: float = 0) -> None:
        host = urlsplit(url).netloc
        with self.lock:
            wait = max(self.settings.scraper_delay, minimum) - (time.monotonic() - self.last_request.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            self.last_request[host] = time.monotonic()

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        delay = float(2 ** attempt)
        if response is not None and (header := response.headers.get("Retry-After")):
            try:
                delay = max(delay, float(header))
            except ValueError:
                try:
                    delay = max(delay, (parsedate_to_datetime(header).astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    pass
        if delay > 120:
            raise ScraperError("Server requested a long retry delay; defer this source to a later run")
        return delay

    def _request(self, url: str, minimum: float = 0, method: str = "GET", data: dict[str, str] | None = None) -> httpx.Response:
        for attempt in range(self.settings.scraper_retries + 1):
            self._delay(url, minimum)
            response = None
            try:
                response = self.client.request(method, url, data=data, follow_redirects=False)
                if response.status_code != 429 and response.status_code < 500:
                    return response
                error = f"HTTP {response.status_code}"
            except httpx.TransportError as exc:
                error = str(exc)
            if attempt == self.settings.scraper_retries:
                if response is not None and response.status_code == 429:
                    raise SourceAccessError(f"HTTP 429 fetching {url}; defer collection")
                raise ScraperError(f"Request failed for {url}: {error}")
            delay = self._retry_delay(response, attempt)
            logger.warning("Retrying source request", extra={"fields": {"url": url, "attempt": attempt + 1, "delay": delay, "error": error}})
            time.sleep(delay)
        raise ScraperError("Retry attempts exhausted")

    def _robots(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            robots_url = origin + "/robots.txt"
            for _ in range(6):
                response = self._request(robots_url)
                if response.is_redirect:
                    target = canonical_url(response.headers.get("location"), robots_url)
                    if not target or urlsplit(target).netloc != parts.netloc or urlsplit(target).scheme != parts.scheme:
                        raise ScraperError("Cannot verify robots policy across origins")
                    robots_url = target
                    continue
                if response.status_code != 200:
                    raise ScraperError(f"Cannot verify robots.txt: HTTP {response.status_code}")
                if "text/html" in response.headers.get("content-type", "") or response.text.lstrip().lower().startswith(("<!doctype html", "<html")):
                    raise ScraperError("robots.txt returned an HTML page rather than a policy")
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
                self.robots[origin] = parser
                break
            else:
                raise ScraperError("Too many robots.txt redirects")
        return self.robots[origin]

    def get(self, url: str) -> str:
        return self._fetch(url)

    def post_form(self, url: str, data: dict[str, str]) -> str:
        """Read a public form-backed listing with the same access protections as GET."""
        return self._fetch(url, "POST", data)

    def _fetch(self, url: str, method: str = "GET", data: dict[str, str] | None = None) -> str:
        url = canonical_url(url)
        for _ in range(6):
            policy = self._robots(url)
            agent = self.settings.scraper_user_agent
            if not policy.can_fetch(agent, url):
                raise ScraperError(f"robots.txt disallows {url}")
            delay = policy.crawl_delay(agent) or policy.crawl_delay("*") or 0
            rate = policy.request_rate(agent) or policy.request_rate("*")
            if rate and rate.requests:
                delay = max(delay, rate.seconds / rate.requests)
            response = self._request(url, delay, method, data)
            if response.is_redirect:
                target = canonical_url(response.headers.get("location"), url)
                if not target:
                    raise ScraperError("Redirect has no destination")
                if method == "POST":
                    if urlsplit(target)[:2] != urlsplit(url)[:2]:
                        raise ScraperError("Refusing to forward a form across origins")
                    if response.status_code == 303:
                        method, data = "GET", None
                    elif response.status_code not in (307, 308):
                        raise ScraperError("Ambiguous redirect for a form request")
                url = target
                continue
            try:
                if response.status_code in (401, 403):
                    raise SourceAccessError(f"HTTP {response.status_code} fetching {url}; access denied")
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ScraperError(f"HTTP {response.status_code} fetching {url}") from exc
            return response.text
        raise ScraperError("Too many source redirects")


class BaseScraper(ABC):
    source_name: str
    source_url: str
    slug: str
    source_type: str = "public_procurement"
    default_active: bool = False
    notes: str = ""
    is_demo: bool = False

    def __init__(self, settings: Settings, http: PoliteHTTPClient | None = None):
        self.settings = settings
        self.http = http
        self.metrics: dict[str, int] = {}
        self.record_errors: list[str] = []

    def fetch(self) -> str:
        if self.http is None:
            raise ScraperError("HTTP client was not configured")
        return self.http.get(self.source_url)

    @abstractmethod
    def parse(self, content: str) -> list[dict]:
        """Extract raw records; raise on unexpected page structure."""

    def normalize(self, records: list[dict]) -> list[OpportunityInput]:
        return [normalize_record(record | {"source_name": self.source_name, "source_url": self.source_url}) for record in records]

    def run(self) -> list[OpportunityInput]:
        return self.normalize(self.parse(self.fetch()))
