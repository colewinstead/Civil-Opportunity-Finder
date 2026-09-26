"""Jinja pages use the same query and status contracts as the REST API."""
from datetime import datetime, timedelta
from math import ceil
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import ROOT
from app.database import get_session
from app.models import CollectionRun, Opportunity, Source
from app.models.opportunity import Category, Status
from app.routes.api import get_opportunity
from app.security import check_csrf
from app.services.query import OpportunityFilters, Sort, list_opportunities

router = APIRouter()
templates = Jinja2Templates(directory=ROOT / "app" / "templates")
templates.env.filters["category_label"] = lambda value: {
    "CEI": "CE&I", "WATER_SEWER": "Water / sewer", "TRANSPORTATION_PLANNING": "Transportation planning",
}.get(str(value), str(value).replace("_", " ").title())
DB = Annotated[Session, Depends(get_session)]


def common(request: Request) -> dict:
    settings = request.app.state.settings
    today = datetime.now(ZoneInfo(settings.scheduler_timezone)).date()
    return {"request": request, "csrf_token": request.state.csrf_token, "today": today,
            "soon": today + timedelta(days=settings.due_soon_days), "statuses": list(Status)}


@router.get("/")
def dashboard(request: Request, session: DB):
    try:
        filters = OpportunityFilters.model_validate({key: value for key, value in request.query_params.items() if value != ""})
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = list_opportunities(session, filters)
    options = {}
    for key in ("agency", "county", "city", "source_name"):
        field = getattr(Opportunity, key)
        options[key] = session.scalars(select(field).where(field.is_not(None)).distinct().order_by(field)).all()
    context = common(request) | result | {"filters": filters, "options": options, "categories": list(Category),
        "sorts": list(Sort), "pages": max(1, ceil(result["total"] / filters.page_size)),
        "all_count": session.scalar(select(func.count()).select_from(Opportunity)),
        "interested_count": session.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.status == Status.INTERESTED)),
        "due_count": session.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.due_date.between(common(request)["today"], common(request)["soon"])))}
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.get("/opportunities/{opportunity_id}")
def detail(opportunity_id: int, request: Request, session: DB):
    record = get_opportunity(session, opportunity_id)
    return templates.TemplateResponse(request=request, name="detail.html", context=common(request) | {"opportunity": record})


@router.post("/opportunities/{opportunity_id}/status")
def change_status(opportunity_id: int, request: Request, session: DB,
                  status: Annotated[Status, Form()], csrf_token: Annotated[str, Form()]):
    check_csrf(request, csrf_token)
    record = get_opportunity(session, opportunity_id)
    record.status = status.value
    session.commit()
    return RedirectResponse(f"/opportunities/{opportunity_id}", status_code=303)


@router.get("/sources")
def sources(request: Request, session: DB):
    return templates.TemplateResponse(request=request, name="sources.html", context=common(request) | {
        "sources": session.scalars(select(Source).order_by(Source.name)).all(),
        "runs": session.scalars(select(CollectionRun).where(CollectionRun.parent_id.is_(None)).order_by(CollectionRun.started_at.desc()).limit(20)).all(),
        "scheduler_enabled": request.app.state.settings.enable_scheduler,
    })
