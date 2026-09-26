from sqlalchemy import func, select
import pytest

from app.models import CollectionRun, Opportunity, Source
from app.scrapers.base import ScraperError
from app.scrapers.fixture import FixtureScraper
from app.scrapers.registry import sync_sources
from app.services.collection import CollectionBusy, CollectionService, SourceUnavailable


class GoodScraper(FixtureScraper):
    slug = "good"
    source_name = "Good test source"
    is_demo = False
    default_active = True


class BrokenScraper(GoodScraper):
    slug = "broken"
    source_name = "Broken test source"

    def fetch(self):
        raise ScraperError("Site changed its HTML")


def service(sessions, settings, registry):
    with sessions.begin() as session:
        sync_sources(session, registry)
    return CollectionService(sessions, settings, registry)


def test_demo_explicit_only(sessions, settings):
    collector = CollectionService(sessions, settings)
    with pytest.raises(SourceUnavailable):
        collector.collect("demo-fixture")
    run_id = collector.collect()
    with sessions() as session:
        assert session.get(CollectionRun, run_id).records_discovered == 0
        assert session.scalar(select(func.count()).select_from(Opportunity)) == 0
    run_id = collector.collect("demo-fixture", allow_demo=True)
    repeat_id = collector.collect("demo-fixture", allow_demo=True)
    with sessions() as session:
        assert session.get(CollectionRun, run_id).records_added == 3
        repeat = session.get(CollectionRun, repeat_id)
        assert repeat.records_added == 0
        assert repeat.records_updated == 3
        assert session.scalar(select(func.count()).select_from(Opportunity)) == 3


def test_failure_does_not_stop_other_sources(sessions, settings):
    collector = service(sessions, settings, {"broken": BrokenScraper, "good": GoodScraper})
    run_id = collector.collect()
    with sessions() as session:
        run = session.get(CollectionRun, run_id)
        assert run.outcome == "PARTIAL"
        assert "Site changed" in run.errors
        assert run.records_added == 3
        broken = session.scalar(select(Source).where(Source.slug == "broken"))
        good = session.scalar(select(Source).where(Source.slug == "good"))
        assert broken.last_checked is not None
        assert broken.last_successful is None
        assert good.last_successful is not None


def test_all_failed(sessions, settings):
    collector = service(sessions, settings, {"broken": BrokenScraper})
    run_id = collector.collect()
    with sessions() as session:
        assert session.get(CollectionRun, run_id).outcome == "FAILED"


def test_source_transaction_rolls_back_and_counts_are_honest(sessions, settings, monkeypatch):
    collector = service(sessions, settings, {"good": GoodScraper})
    from app.services import collection
    real_upsert = collection.upsert_opportunity
    count = 0
    def fail_second(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("Simulated database failure")
        return real_upsert(*args)
    monkeypatch.setattr(collection, "upsert_opportunity", fail_second)
    run_id = collector.collect()
    with sessions() as session:
        run = session.get(CollectionRun, run_id)
        assert run.outcome == "FAILED"
        assert run.records_discovered == 3
        assert run.records_added == 0
        assert session.scalar(select(func.count()).select_from(Opportunity)) == 0


def test_overlap_rejected_within_and_between_services(sessions, settings):
    collector = CollectionService(sessions, settings)
    other = CollectionService(sessions, settings)
    run_id = collector.reserve()
    try:
        with pytest.raises(CollectionBusy):
            collector.reserve()
        with pytest.raises(CollectionBusy):
            other.reserve()
        other.recover_interrupted()
        with sessions() as session:
            assert session.get(CollectionRun, run_id).outcome == "RUNNING"
    finally:
        collector.execute(run_id)
    assert other.collect()


def test_interrupted_run_recovered(sessions, settings):
    with sessions.begin() as session:
        session.add(CollectionRun(id="unfinished", source="ALL"))
    collector = CollectionService(sessions, settings)
    collector.recover_interrupted()
    with sessions() as session:
        record = session.get(CollectionRun, "unfinished")
        assert record.outcome == "INTERRUPTED"
        assert record.finished_at is not None


def test_scheduler_excludes_demo_even_if_active(sessions, settings):
    with sessions.begin() as session:
        source = session.scalar(select(Source).where(Source.slug == "demo-fixture"))
        source.active = True
    collector = CollectionService(sessions, settings)
    run_id = collector.collect()
    with sessions() as session:
        assert session.get(CollectionRun, run_id).records_discovered == 0
