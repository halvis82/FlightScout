"""Stateless HTTP API over the engine, deployed as its own Vercel project and
called server side by the web app. Protected by a shared ENGINE_KEY."""

from __future__ import annotations

import os
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import explore as explore_mod
from .models import DatePrice, Destination, SearchQuery, SearchResult
from .planner import PlanRequest, PlanResult, TripRequest, build_trip, plan
from .search import search as run_search
from .sources import google

app = FastAPI(title="FlightScout engine", version="0.1.0")


def auth(x_engine_key: str | None = Header(default=None)) -> None:
    key = os.environ.get("ENGINE_KEY")
    if key and x_engine_key != key:
        raise HTTPException(status_code=401, detail="bad engine key")


class SearchBody(SearchQuery):
    seller_rules: dict[str, str] | None = None


class DatesBody(BaseModel):
    origin: str
    destination: str
    start: date
    end: date
    currency: str = "USD"
    trip_days: int | None = None


class ExploreBody(BaseModel):
    origin: str
    start: date
    end: date
    currency: str = "USD"
    nights_min: int | None = None
    nights_max: int | None = None
    sources: list[str] | None = None
    regions: list[str] | None = None


class ExploreResult(BaseModel):
    destinations: list[Destination]
    errors: dict[str, str]


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/search", dependencies=[Depends(auth)])
@app.post("/api/search", dependencies=[Depends(auth)], include_in_schema=False)
def search(body: SearchBody) -> SearchResult:
    rules = body.seller_rules
    return run_search(SearchQuery(**body.model_dump(exclude={"seller_rules"})), rules)


@app.post("/plan", dependencies=[Depends(auth)])
@app.post("/api/plan", dependencies=[Depends(auth)], include_in_schema=False)
def plan_route(body: PlanRequest) -> PlanResult:
    return plan(body)


@app.post("/trip", dependencies=[Depends(auth)])
@app.post("/api/trip", dependencies=[Depends(auth)], include_in_schema=False)
def trip(body: TripRequest) -> PlanResult:
    return build_trip(body)


@app.post("/dates", dependencies=[Depends(auth)])
@app.post("/api/dates", dependencies=[Depends(auth)], include_in_schema=False)
def dates(body: DatesBody) -> list[DatePrice]:
    return google.dates(body.origin, body.destination, body.start, body.end, body.currency, body.trip_days)


@app.post("/explore", dependencies=[Depends(auth)])
@app.post("/api/explore", dependencies=[Depends(auth)], include_in_schema=False)
def explore(body: ExploreBody) -> ExploreResult:
    nights = (body.nights_min or 1, body.nights_max or body.nights_min or 7) if (body.nights_min or body.nights_max) else None
    d, errs = explore_mod.explore(body.origin, body.start, body.end, body.currency, nights, body.sources, body.regions)
    return ExploreResult(destinations=d, errors=errs)
