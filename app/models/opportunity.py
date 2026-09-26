"""Opportunity fields and user-managed workflow states."""
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, Date, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, utcnow


class Category(StrEnum):
    ROADWAY = "ROADWAY"
    SITE_DEVELOPMENT = "SITE DEVELOPMENT"
    DRAINAGE = "DRAINAGE"
    WATER_SEWER = "WATER_SEWER"
    SURVEY = "SURVEY"
    BRIDGE = "BRIDGE"
    TRANSPORTATION_PLANNING = "TRANSPORTATION_PLANNING"
    CEI = "CEI"
    MUNICIPAL = "MUNICIPAL"
    LAND_DEVELOPMENT = "LAND_DEVELOPMENT"
    UTILITIES = "UTILITIES"
    OTHER = "OTHER"


class Status(StrEnum):
    NEW = "NEW"
    REVIEWING = "REVIEWING"
    INTERESTED = "INTERESTED"
    NOT_INTERESTED = "NOT_INTERESTED"
    SUBMITTED = "SUBMITTED"
    ARCHIVED = "ARCHIVED"


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        CheckConstraint("match_score >= 0 AND match_score <= 100"),
        CheckConstraint("status IN ('NEW','REVIEWING','INTERESTED','NOT_INTERESTED','SUBMITTED','ARCHIVED')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    agency: Mapped[str | None] = mapped_column(String(300), index=True)
    source_name: Mapped[str] = mapped_column(String(200), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    opportunity_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), default=Category.OTHER, index=True)
    subcategories: Mapped[list[str]] = mapped_column(JSON, default=list)
    county: Mapped[str | None] = mapped_column(String(100), index=True)
    city: Mapped[str | None] = mapped_column(String(100), index=True)
    state: Mapped[str | None] = mapped_column(String(100))
    posted_date: Mapped[date | None] = mapped_column(Date, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(100))
    solicitation_number: Mapped[str | None] = mapped_column(String(200), index=True)
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    procurement_type: Mapped[str | None] = mapped_column(String(100))
    professional_services: Mapped[bool | None] = mapped_column(Boolean)
    engineering_required: Mapped[bool | None] = mapped_column(Boolean)
    raw_text: Mapped[str | None] = mapped_column(Text)
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    status: Mapped[str] = mapped_column(String(30), default=Status.NEW, index=True)
    match_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
