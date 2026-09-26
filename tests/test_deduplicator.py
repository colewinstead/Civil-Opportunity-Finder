from datetime import date

from sqlalchemy import func, select

from app.config import DEFAULT_WEIGHTS
from app.models import Opportunity
from app.services.deduplicator import upsert_opportunity
from app.services.normalizer import normalize_record


def save(sessions, item):
    with sessions.begin() as session:
        record, added = upsert_opportunity(session, item, DEFAULT_WEIGHTS)
        return record.id, added


def test_repeat_updates_preserve_status_and_first_seen(sessions, item):
    record_id, added = save(sessions, item)
    assert added
    with sessions.begin() as session:
        record = session.get(Opportunity, record_id)
        record.status = "INTERESTED"
        first_seen = record.first_seen
        previous_last_seen = record.last_seen
        old_hash = record.content_hash
    assert save(sessions, item.model_copy(update={"description": "Revised bridge inspection design", "due_date": date(2026, 10, 5)})) == (record_id, False)
    with sessions() as session:
        record = session.get(Opportunity, record_id)
        assert record.status == "INTERESTED"
        assert record.first_seen == first_seen
        assert record.last_seen >= previous_last_seen
        assert record.last_seen.tzinfo is not None
        assert record.content_hash != old_hash
        assert record.due_date == date(2026, 10, 5)
        assert session.scalar(select(func.count()).select_from(Opportunity)) == 1


def test_null_values_do_not_erase_existing(sessions, item):
    record_id, _ = save(sessions, item)
    save(sessions, item.model_copy(update={"description": None, "due_date": None}))
    with sessions() as session:
        record = session.get(Opportunity, record_id)
        assert record.description == item.description
        assert record.due_date == item.due_date


def test_cross_source_same_agency_and_number(sessions, item):
    record_id, _ = save(sessions, item)
    incoming = item.model_copy(update={"source_name": "Other", "source_url": "https://other.invalid/", "opportunity_url": "https://other.invalid/42"})
    assert save(sessions, incoming) == (record_id, False)


def test_numbers_scoped_to_agency(sessions, item):
    save(sessions, item)
    assert save(sessions, item.model_copy(update={"agency": "Other agency", "opportunity_url": "https://other.invalid/bid"}))[1]


def test_conflicting_numbers_are_not_merged(sessions, item):
    save(sessions, item)
    assert save(sessions, item.model_copy(update={"solicitation_number": "TEST-002"}))[1]


def test_hash_without_identifiers(sessions):
    item = normalize_record({"title": "Test", "source_name": "Test", "source_url": "https://example.invalid/"})
    record_id, _ = save(sessions, item)
    assert save(sessions, item) == (record_id, False)


def test_conservative_fuzzy_matching(sessions, item):
    original = item.model_copy(update={"title": "Municipal roadway improvement design services", "solicitation_number": None, "opportunity_url": None})
    record_id, _ = save(sessions, original)
    assert save(sessions, original.model_copy(update={"title": "Municipal roadway improvements design services"})) == (record_id, False)
    assert save(sessions, original.model_copy(update={"title": "Municipal roadway improvements design services", "due_date": date(2027, 10, 1)}))[1]
    assert save(sessions, original.model_copy(update={"title": "Municipal roadway improvements design services", "agency": "Other agency"}))[1]
