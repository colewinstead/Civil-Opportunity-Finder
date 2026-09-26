"""Add source classes here; each real source keeps its own parsing module."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.source import Source
from app.scrapers.base import BaseScraper
from app.scrapers.fixture import FixtureScraper
from app.scrapers.mississippi_procurement import MississippiProcurementScraper

SCRAPERS: dict[str, type[BaseScraper]] = {
    FixtureScraper.slug: FixtureScraper,
    MississippiProcurementScraper.slug: MississippiProcurementScraper,
}


def sync_sources(session: Session, registry: dict[str, type[BaseScraper]] = SCRAPERS) -> None:
    """Insert metadata without overwriting an operator's activation choice."""
    for slug, scraper in registry.items():
        source = session.scalar(select(Source).where(Source.slug == slug))
        if source is None:
            session.add(Source(slug=slug, name=scraper.source_name, base_url=scraper.source_url,
                               source_type=scraper.source_type, active=scraper.default_active and not scraper.is_demo,
                               notes=scraper.notes))
