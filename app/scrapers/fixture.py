"""Explicit synthetic fixture source. Never scheduled and never fetched online."""
from pathlib import Path

from bs4 import BeautifulSoup

from app.config import ROOT
from app.scrapers.base import BaseScraper, ScraperError


class FixtureScraper(BaseScraper):
    slug = "demo-fixture"
    source_name = "DEMO — Offline fixture"
    source_url = "https://example.invalid/demo/"
    source_type = "offline_fixture"
    is_demo = True
    notes = "Synthetic opportunities for testing only. No live Mississippi procurement coverage."

    def fetch(self) -> str:
        return (ROOT / "app" / "scrapers" / "fixtures" / "demo.html").read_text(encoding="utf-8")

    def parse(self, content: str) -> list[dict]:
        soup = BeautifulSoup(content, "html.parser")
        container = soup.select_one("#opportunities")
        if container is None:
            raise ScraperError("Expected #opportunities container is missing")
        records = []
        for node in container.select("article.opportunity"):
            heading = node.select_one("h2")
            if not heading or not heading.get_text(strip=True):
                raise ScraperError("Opportunity has no title")
            record = {"title": heading.get_text(" ", strip=True), "raw_text": node.get_text(" ", strip=True)}
            link = node.select_one("a.solicitation")
            record["opportunity_url"] = link.get("href") if link else None
            for key in ("agency", "description", "county", "city", "state", "posted_date", "due_date", "solicitation_number", "procurement_type", "contact_name", "contact_email", "contact_phone"):
                element = node.select_one(f"[data-field='{key}']")
                record[key] = element.get_text(" ", strip=True) if element else None
            records.append(record)
        return records
