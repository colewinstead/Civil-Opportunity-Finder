from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.services.normalizer import canonical_url, content_hash, normalize_record, normalized_key, parse_date


def test_normalization_preserves_raw_and_unknown_fields():
    item = normalize_record({"title": "  Roadway \n design ", "source_name": "Test", "source_url": "https://EXAMPLE.invalid/", "opportunity_url": "/bid?id=7&utm_source=email#files", "state": "Mississippi", "contact_email": "mailto:Engineer@EXAMPLE.invalid", "contact_phone": "tel:601-555-0100", "due_date": "ambiguous", "raw_text": "original\n spacing"})
    assert item.title == "Roadway design"
    assert item.state == "MS"
    assert item.opportunity_url == "https://example.invalid/bid?id=7"
    assert item.contact_email == "engineer@example.invalid"
    assert item.contact_phone == "601-555-0100"
    assert item.due_date is None
    assert item.professional_services is None
    assert item.raw_text == "original\n spacing"


@pytest.mark.parametrize("value", ["2026-10-01", "10/01/2026", "October 1, 2026", "Oct 1, 2026"])
def test_date_formats(value):
    assert parse_date(value) == date(2026, 10, 1)


def test_date_objects_and_unknown_dates():
    assert parse_date(datetime(2026, 10, 1, tzinfo=timezone.utc)) == date(2026, 10, 1)
    assert parse_date("10/01") is None


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "https://user:password@example.invalid/", "data:text/html,test"])
def test_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):
        canonical_url(url)


def test_title_required():
    with pytest.raises(ValidationError):
        normalize_record({"title": " ", "source_name": "Test", "source_url": "https://example.invalid/"})


def test_hash_deterministic_and_content_sensitive():
    assert content_hash({"title": "Test", "agency": "A"}) == content_hash({"agency": "A", "title": "Test", "last_seen": "today", "status": "INTERESTED"})
    assert content_hash({"title": "Test"}) != content_hash({"title": "New title"})
    assert normalized_key("Water-main DESIGN") == "water main design"
