"""Conservative identity matching and source-field updates within a transaction."""
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models.opportunity import Category, Opportunity
from app.schemas.opportunity import OpportunityInput
from app.services.classifier import classify
from app.services.normalizer import canonical_url, content_hash, normalized_key
from app.services.scoring import score_match


def find_duplicate(session: Session, values: dict) -> Opportunity | None:
    # Phase 1 favors transparent conservative comparisons. Add indexed identity
    # keys when real-source volume justifies it; do not use DB-specific functions.
    incoming_agency = normalized_key(values.get("agency"))
    title = normalized_key(values["title"])
    for record in session.scalars(select(Opportunity).order_by(Opportunity.id)):
        same_agency = bool(incoming_agency) and normalized_key(record.agency) == incoming_agency
        if (same_agency and values.get("solicitation_number") and record.solicitation_number
                and normalized_key(values["solicitation_number"]) == normalized_key(record.solicitation_number)):
            return record
        # A conflicting number identifies a distinct solicitation, even if a
        # portal reuses a generic detail URL or a title.
        if (values.get("solicitation_number") and record.solicitation_number
                and normalized_key(values["solicitation_number"]) != normalized_key(record.solicitation_number)):
            continue
        if values.get("opportunity_url") and canonical_url(record.opportunity_url) == values["opportunity_url"]:
            return record
        if record.content_hash == content_hash(values):
            return record
        dates_match = record.due_date == values.get("due_date")
        other_title = normalized_key(record.title)
        if same_agency and dates_match and title == other_title:
            return record
        if (same_agency and dates_match and record.due_date is not None
                and min(len(title), len(other_title)) >= 20
                and SequenceMatcher(None, title, other_title).ratio() >= 0.95):
            return record
    return None


def upsert_opportunity(session: Session, item: OpportunityInput, weights: dict[str, int]) -> tuple[Opportunity, bool]:
    values = item.model_dump()
    record = find_duplicate(session, values)
    added = record is None
    if record is None:
        record = Opportunity(**values)
        session.add(record)
    else:
        for key, value in values.items():
            if value is not None:
                setattr(record, key, value)
    record.last_seen = utcnow()
    merged = {key: getattr(record, key) for key in OpportunityInput.model_fields}
    record.category, record.subcategories = classify(" ".join(merged.get(key) or "" for key in ("title", "description", "raw_text")))
    record.match_score = score_match(merged, Category(record.category), weights)
    record.content_hash = content_hash(merged)
    session.flush()
    return record, added
