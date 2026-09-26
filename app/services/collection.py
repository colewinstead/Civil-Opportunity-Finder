"""Collection orchestration with per-source transactions and durable run results."""
import logging
import threading
from uuid import uuid4

from sqlalchemy import select, update

from app.config import Settings
from app.database import utcnow
from app.models import CollectionRun, Source
from app.scrapers.base import PoliteHTTPClient
from app.scrapers.registry import SCRAPERS
from app.services.deduplicator import upsert_opportunity
from app.services.lock import CollectionFileLock

logger = logging.getLogger("opportunity_finder.collection")


class CollectionBusy(RuntimeError):
    pass


class SourceUnavailable(ValueError):
    pass


class CollectionService:
    def __init__(self, sessions, settings: Settings, registry=None):
        self.sessions = sessions
        self.settings = settings
        self.registry = SCRAPERS if registry is None else registry
        self.lock = threading.Lock()
        self.file_lock = CollectionFileLock(str(sessions.kw["bind"].url))

    def recover_interrupted(self) -> None:
        """Called only on startup of the documented single-process application."""
        if self.file_lock.acquire():
            try:
                with self.sessions.begin() as session:
                    session.execute(update(CollectionRun).where(CollectionRun.outcome == "RUNNING").values(
                        outcome="INTERRUPTED", finished_at=utcnow(), errors="Application stopped before this run finished; run collection again."))
            finally:
                self.file_lock.release()

    def reserve(self, source: str | None = None, allow_demo: bool = False) -> str:
        if source is not None:
            if source not in self.registry:
                raise SourceUnavailable(f"Unknown source: {source}")
            if self.registry[source].is_demo and not allow_demo:
                raise SourceUnavailable("Demo collection is available only through the explicit demo-loading command")
        if not self.lock.acquire(blocking=False):
            raise CollectionBusy("A collection run is already in progress")
        try:
            if not self.file_lock.acquire():
                raise CollectionBusy("Another process is collecting for this database")
            run_id = str(uuid4())
            with self.sessions.begin() as session:
                session.add(CollectionRun(id=run_id, source=source or "ALL"))
            return run_id
        except Exception:
            self.file_lock.release()
            self.lock.release()
            raise

    def collect(self, source: str | None = None, allow_demo: bool = False) -> str:
        run_id = self.reserve(source, allow_demo)
        self.execute(run_id)
        return run_id

    def scheduled_collect(self) -> None:
        try:
            self.collect()
        except CollectionBusy:
            logger.warning("Scheduled collection skipped: another run is active")

    def execute(self, run_id: str) -> None:
        try:
            with self.sessions() as session:
                batch = session.get(CollectionRun, run_id)
                if batch.source == "ALL":
                    slugs = [source.slug for source in session.scalars(select(Source).where(Source.active.is_(True)))
                             if source.slug in self.registry and not self.registry[source.slug].is_demo]
                else:
                    slugs = [batch.source]
            with_http = PoliteHTTPClient(self.settings)
            try:
                for slug in slugs:
                    self._collect_source(run_id, slug, with_http)
            finally:
                with_http.close()
            with self.sessions.begin() as session:
                batch = session.get(CollectionRun, run_id)
                children = session.scalars(select(CollectionRun).where(CollectionRun.parent_id == run_id)).all()
                for field in ("records_discovered", "records_added", "records_updated"):
                    setattr(batch, field, sum(getattr(child, field) for child in children))
                failures = [child for child in children if child.outcome != "SUCCEEDED"]
                batch.outcome = "PARTIAL" if failures and len(failures) < len(children) else "FAILED" if failures else "SUCCEEDED"
                batch.errors = "\n".join(f"{child.source}: {child.errors}" for child in failures) or None
                batch.finished_at = utcnow()
                self._log_run(batch)
        except Exception as exc:
            logger.exception("Collection batch failed", extra={"fields": {"run_id": run_id}})
            with self.sessions.begin() as session:
                batch = session.get(CollectionRun, run_id)
                batch.outcome = "FAILED"
                batch.finished_at = utcnow()
                batch.errors = str(exc)
        finally:
            self.file_lock.release()
            self.lock.release()

    def _collect_source(self, parent_id: str, slug: str, http: PoliteHTTPClient) -> None:
        child_id = str(uuid4())
        started = utcnow()
        with self.sessions.begin() as session:
            source = session.scalar(select(Source).where(Source.slug == slug))
            if source is None:
                raise SourceUnavailable(f"Source metadata missing for {slug}")
            source.last_checked = started
            session.add(CollectionRun(id=child_id, parent_id=parent_id, source=slug, started_at=started))
        logger.info("Scraper started", extra={"fields": {"source": slug, "run_id": child_id, "start_time": started}})
        discovered = 0
        try:
            records = self.registry[slug](self.settings, http).run()
            discovered = len(records)
            # Data and successful counts commit atomically for this source.
            with self.sessions.begin() as session:
                run = session.get(CollectionRun, child_id)
                run.records_discovered = discovered
                for record in records:
                    _, added = upsert_opportunity(session, record, self.settings.scoring_weights)
                    if added:
                        run.records_added += 1
                    else:
                        run.records_updated += 1
                run.outcome = "SUCCEEDED"
                run.finished_at = utcnow()
                source = session.scalar(select(Source).where(Source.slug == slug))
                source.last_successful = run.finished_at
            self._log_run(run)
        except Exception as exc:
            logger.exception("Scraper failed", extra={"fields": {"source": slug, "run_id": child_id}})
            with self.sessions.begin() as session:
                run = session.get(CollectionRun, child_id)
                run.outcome = "FAILED"
                run.records_discovered = discovered
                run.records_added = 0
                run.records_updated = 0
                run.finished_at = utcnow()
                run.errors = f"{type(exc).__name__}: {exc}"
            self._log_run(run)

    @staticmethod
    def _log_run(run: CollectionRun) -> None:
        logger.info("Collection finished", extra={"fields": {
            "source": run.source, "run_id": run.id, "start_time": run.started_at, "finish_time": run.finished_at,
            "outcome": run.outcome, "records_discovered": run.records_discovered,
            "records_added": run.records_added, "records_updated": run.records_updated, "errors": run.errors,
        }})
