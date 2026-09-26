"""One filter contract shared by the API and HTML dashboard."""
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.opportunity import Category, Opportunity, Status


class Sort(StrEnum):
    MATCH_SCORE = "match_score"
    DUE_DATE = "due_date"
    POSTED_DATE = "posted_date"
    NEWEST = "newest"


class OpportunityFilters(BaseModel):
    q: str | None = Field(default=None, max_length=300)
    category: Category | None = None
    agency: str | None = None
    county: str | None = None
    city: str | None = None
    source: str | None = None
    min_score: int = Field(default=0, ge=0, le=100)
    due_from: date | None = None
    due_to: date | None = None
    status: Status | None = None
    sort: Sort = Sort.MATCH_SCORE
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def date_range(self):
        if self.due_from and self.due_to and self.due_from > self.due_to:
            raise ValueError("due_from must be on or before due_to")
        return self


def list_opportunities(session: Session, filters: OpportunityFilters) -> dict:
    conditions = [Opportunity.match_score >= filters.min_score]
    for name in ("category", "agency", "county", "city", "status"):
        if value := getattr(filters, name):
            conditions.append(getattr(Opportunity, name) == value)
    if filters.source:
        conditions.append(Opportunity.source_name == filters.source)
    if filters.q and filters.q.strip():
        pattern = "%" + filters.q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(or_(*(getattr(Opportunity, key).ilike(pattern, escape="\\") for key in ("title", "agency", "description", "solicitation_number", "raw_text"))))
    if filters.due_from:
        conditions.append(Opportunity.due_date >= filters.due_from)
    if filters.due_to:
        conditions.append(Opportunity.due_date <= filters.due_to)
    ordering = {
        Sort.MATCH_SCORE: Opportunity.match_score.desc(),
        Sort.DUE_DATE: Opportunity.due_date.asc().nullslast(),
        Sort.POSTED_DATE: Opportunity.posted_date.desc().nullslast(),
        Sort.NEWEST: Opportunity.first_seen.desc(),
    }
    total = session.scalar(select(func.count()).select_from(Opportunity).where(*conditions))
    items = session.scalars(select(Opportunity).where(*conditions).order_by(ordering[filters.sort], Opportunity.id.desc())
                            .offset((filters.page - 1) * filters.page_size).limit(filters.page_size)).all()
    return {"items": items, "total": total, "page": filters.page, "page_size": filters.page_size}
