"""Stateless HTTP API over the engine, deployed as its own Vercel project and
called server side by the web app. Protected by a shared ENGINE_KEY."""

from __future__ import annotations

import os
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import explore as explore_mod
from .models import DatePrice, Destination, SearchQuery, SearchResult
from .multicity import MultiRequest, plan_multicity
from .planner import PlanRequest, PlanResult, TripRequest, build_trip, plan
from .search import search as run_search
from .sources import google

app = FastAPI(title="FlightScout engine", version="0.1.0")

# Local runner mode (`flightscout serve`): the website calls this engine from
# the user's browser, so searches come from their home IP. Only the configured
# site origins may read responses (CORS), and Chrome's Private Network Access
# preflight is answered.
LOCAL = os.environ.get("FLIGHTSCOUT_LOCAL") == "1"
if LOCAL:
    from fastapi.middleware.cors import CORSMiddleware

    origins = [o for o in os.environ.get(
        "FLIGHTSCOUT_ORIGINS", "https://flightscout-app.vercel.app,http://localhost:3000").split(",") if o]

    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["*"], max_age=600,
                       allow_private_network=True)


def auth(x_engine_key: str | None = Header(default=None)) -> None:
    if LOCAL:
        return  # bound to 127.0.0.1 and CORS restricted
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
    batch: int | None = None  # 0 to len(BATCHES)-1: request explore.BATCHES[batch] only


class ExploreResult(BaseModel):
    destinations: list[Destination]
    errors: dict[str, str]


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    from . import __version__

    return {"ok": True, "local": LOCAL, "version": __version__}


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


@app.post("/multicity", dependencies=[Depends(auth)])
@app.post("/api/multicity", dependencies=[Depends(auth)], include_in_schema=False)
def multicity(body: MultiRequest) -> PlanResult:
    return plan_multicity(body)


@app.post("/dates", dependencies=[Depends(auth)])
@app.post("/api/dates", dependencies=[Depends(auth)], include_in_schema=False)
def dates(body: DatesBody) -> list[DatePrice]:
    from .search import cheapest_per_day, direct_dates

    res = google.dates(body.origin, body.destination, body.start, body.end, body.currency, body.trip_days)
    if not body.trip_days:  # airline calendars are one way only
        extra, _ = direct_dates(body.origin, body.destination, body.start, body.end, body.currency)
        res = cheapest_per_day(res + extra)
    return res


@app.post("/explore", dependencies=[Depends(auth)])
@app.post("/api/explore", dependencies=[Depends(auth)], include_in_schema=False)
def explore(body: ExploreBody) -> ExploreResult:
    nights = (body.nights_min or 1, body.nights_max or body.nights_min or 7) if (body.nights_min or body.nights_max) else None
    regions = body.regions
    sources = body.sources
    if body.batch == 0:
        # fast: sources that cover the whole world in one call each
        regions, sources = ["anywhere"], sources or ["kiwiweb", "kayak", "ryanair", "google"]
    elif body.batch is not None and 1 <= body.batch <= len(explore_mod.BATCHES):
        # depth: the older Kiwi region by region lookups (slow)
        regions, sources = explore_mod.BATCHES[body.batch - 1], sources or ["kiwi"]
    d, errs = explore_mod.explore(body.origin, body.start, body.end, body.currency, nights, sources, regions)
    return ExploreResult(destinations=d, errors=errs)
