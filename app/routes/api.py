"""REST endpoints delegate querying and collection to dedicated services."""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import CollectionRun, Opportunity, Source
from app.schemas.opportunity import OpportunityPage, OpportunityPatch, OpportunityRead
from app.security import require_csrf
from app.services.collection import CollectionBusy, SourceUnavailable
from app.services.query import OpportunityFilters, list_opportunities

router = APIRouter(prefix="/api", tags=["opportunities"])
DB = Annotated[Session, Depends(get_session)]


def get_opportunity(session: Session, opportunity_id: int) -> Opportunity:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(404, "Opportunity not found")
    return opportunity


@router.get("/health")
def health(request: Request, session: DB):
    session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "scheduler_enabled": request.app.state.settings.enable_scheduler,
            "csrf_token": request.state.csrf_token}


@router.get("/opportunities", response_model=OpportunityPage)
def opportunities(session: DB, filters: Annotated[OpportunityFilters, Query()]):
    return list_opportunities(session, filters)


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityRead)
def opportunity(opportunity_id: int, session: DB):
    return get_opportunity(session, opportunity_id)


@router.patch("/opportunities/{opportunity_id}", response_model=OpportunityRead, dependencies=[Depends(require_csrf)])
def patch_opportunity(opportunity_id: int, payload: OpportunityPatch, session: DB):
    record = get_opportunity(session, opportunity_id)
    record.status = payload.status.value
    session.commit()
    return record


@router.get("/sources")
def sources(session: DB):
    return jsonable_encoder(session.scalars(select(Source).order_by(Source.name)).all())


def start_collection(request: Request, background: BackgroundTasks, source: str | None = None):
    try:
        run_id = request.app.state.collection.reserve(source)
    except SourceUnavailable as exc:
        raise HTTPException(404, str(exc)) from exc
    except CollectionBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    background.add_task(request.app.state.collection.execute, run_id)
    return {"run_id": run_id, "outcome": "RUNNING", "status_url": f"/api/scrape-runs/{run_id}"}


@router.post("/scrape", status_code=202, dependencies=[Depends(require_csrf)])
def scrape(request: Request, background: BackgroundTasks):
    return start_collection(request, background)


@router.post("/scrape/{source}", status_code=202, dependencies=[Depends(require_csrf)])
def scrape_source(source: str, request: Request, background: BackgroundTasks):
    return start_collection(request, background, source)


@router.get("/scrape-runs/{run_id}")
def scrape_run(run_id: str, session: DB):
    run = session.get(CollectionRun, run_id)
    if run is None:
        raise HTTPException(404, "Collection run not found")
    return jsonable_encoder({"run": run, "sources": session.scalars(select(CollectionRun).where(CollectionRun.parent_id == run_id).order_by(CollectionRun.started_at)).all()})
