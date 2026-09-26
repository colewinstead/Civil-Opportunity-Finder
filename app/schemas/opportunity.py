"""Validated scraper input and public API schemas."""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.opportunity import Category, Status


class OpportunityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    agency: str | None = None
    source_name: str
    source_url: str
    opportunity_url: str | None = None
    description: str | None = None
    county: str | None = None
    city: str | None = None
    state: str | None = None
    posted_date: date | None = None
    due_date: date | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    solicitation_number: str | None = None
    estimated_value: Decimal | None = Field(default=None, ge=0)
    procurement_type: str | None = None
    professional_services: bool | None = None
    engineering_required: bool | None = None
    raw_text: str | None = None

    @field_validator("source_url", "opportunity_url")
    @classmethod
    def safe_url(cls, value: str | None) -> str | None:
        if value is not None:
            from urllib.parse import urlsplit
            url = urlsplit(value)
            if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
                raise ValueError("A public HTTP/HTTPS URL without credentials is required")
        return value


class OpportunityRead(OpportunityInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: Category
    subcategories: list[str]
    first_seen: datetime
    last_seen: datetime
    status: Status
    match_score: int
    content_hash: str


class OpportunityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status


class OpportunityPage(BaseModel):
    items: list[OpportunityRead]
    total: int
    page: int
    page_size: int
