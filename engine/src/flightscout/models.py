"""Normalized data model shared by every source, the planner, the CLI, the MCP
server and the web API. Anything that leaves the engine is one of these, dumped
to JSON with ``model_dump(mode="json")``."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

Source = Literal["google", "kiwi", "ryanair", "serpapi", "volaris", "wideroe", "skyairline", "norse", "volotea",
                 "condor", "flair", "wizzair", "vivaaerobus", "kiwiweb", "kayak", "skyscanner",
                 # direct airline sources that need a real browser (sources/_browser.py)
                 "transavia", "norwegian", "southwest", "allegiant",
                 # OTAs and metasearch sites, live search results
                 "booking", "kayakweb", "momondo", "cheapflights", "tripcom", "expedia", "orbitz", "travelocity",
                 "priceline", "aviasales", "wego", "omio", "edreams", "opodo", "gotogate", "mytrip", "almosafer",
                 "cleartrip", "traveloka",
                 # Americas direct airline sources
                 "frontier", "breeze", "avelo", "jetblue", "alaska", "united", "westjet", "porter",
                 "aeromexico", "arajet", "caribbean", "caymanairways", "wingo", "aerolineas",
                 # world direct airline sources (Europe, Middle East, Africa, Asia, Oceania)
                 "finnair", "afklm", "jet2", "aerlingus", "vueling", "level", "skyexpress", "tap", "aegean",
                 "flydubai", "jazeera", "flysafair", "qatar", "etihad", "spicejet", "vietjet", "akasa",
                 "tigerair", "zipair", "jejuair", "virginaustralia", "airnewzealand",
                 # East / Southeast Asia and Oceania direct airline sources (wave 2a)
                 "nokair", "spring", "linkairways", "bangkokair", "airniugini", "vietnamairlines",
                 "philippineairlines",
                 # fare engines and hidden city search (wave 2c)
                 "ita", "skiplagged", "easemytrip", "agoda", "ixigo", "avianca", "sas",
                 # Middle East, Africa, South and Central Asia direct airline sources (wave 2b)
                 "biman", "flyarystan", "starair", "allianceair", "fly91"]
Cabin = Literal["economy", "premium", "business", "first"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class Segment(BaseModel):
    """One physical flight."""

    origin: str
    destination: str
    departure: datetime  # local time at origin, naive
    arrival: datetime  # local time at destination, naive
    carrier: str  # IATA airline code, e.g. "KL"
    carrier_name: str | None = None
    flight_number: str | None = None
    duration_min: int | None = None
    aircraft: str | None = None


class Slice(BaseModel):
    """A directional journey (outbound or inbound) made of segments."""

    segments: list[Segment]
    duration_min: int

    @computed_field
    @property
    def origin(self) -> str:
        return self.segments[0].origin

    @computed_field
    @property
    def destination(self) -> str:
        return self.segments[-1].destination

    @computed_field
    @property
    def departure(self) -> datetime:
        return self.segments[0].departure

    @computed_field
    @property
    def arrival(self) -> datetime:
        return self.segments[-1].arrival

    @computed_field
    @property
    def stops(self) -> int:
        return len(self.segments) - 1

    @computed_field
    @property
    def carriers(self) -> list[str]:
        return sorted({s.carrier for s in self.segments})


class Fare(BaseModel):
    name: str | None = None  # "Saver", "Main Basic", ...
    price: float
    features: list[str] = Field(default_factory=list)  # bags, changes, refunds


class Offer(BaseModel):
    """One seller on Google's booking page for an itinerary."""

    seller: str
    is_airline: bool
    fares: list[Fare]

    @property
    def cheapest(self) -> float:
        return min(f.price for f in self.fares)


class Itinerary(BaseModel):
    """A single bookable ticket (one price, one booking link)."""

    source: Source
    price: float
    currency: str
    slices: list[Slice]
    booking_url: str
    seller: str | None = None  # "Kiwi.com", "Google Flights", airline name...
    seller_kind: Literal["airline", "ota", "metasearch"] = "metasearch"
    self_transfer: bool = False  # connections inside this ticket are not protected
    # Round trip where only the outbound is known: the price is Google's round
    # trip "from" price and the return is picked on the booking page.
    return_pending: bool = False
    # with return_pending: the return date that "from" price was searched for
    pending_return: date | None = None
    # Where Google Flights ranks the outbound on its "Best" tab (0 = first)
    # and whether it is in "Top departing flights". None/False for others.
    google_rank: int | None = None
    google_top: bool = False
    baggage: dict | None = None
    offers: list[Offer] | None = None  # seller breakdown, when fetched
    price_insight: str | None = None  # e.g. "$461 is low, usually $680 to $2,850"
    warnings: list[str] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=now_utc)

    @computed_field
    @property
    def id(self) -> str:
        key = "|".join(
            f"{s.origin}{s.destination}{s.departure:%Y%m%d%H%M}{s.carrier}{s.flight_number}"
            for sl in self.slices
            for s in sl.segments
        )
        return hashlib.sha1(f"{self.source}:{key}".encode()).hexdigest()[:16]

    @computed_field
    @property
    def trip_type(self) -> Literal["oneway", "roundtrip", "multi"]:
        if self.return_pending:
            return "roundtrip"
        if len(self.slices) == 1:
            return "oneway"
        if len(self.slices) == 2 and self.slices[0].origin == self.slices[1].destination:
            return "roundtrip"
        return "multi"

    @property
    def duration_min(self) -> int:
        return sum(s.duration_min for s in self.slices)

    @property
    def flight_key(self) -> str:
        """Source independent identity, used to merge the same flights found
        on several sources."""
        # without a flight number, the departure time tells flights apart
        return "|".join(
            f"{s.carrier}{s.flight_number}@{s.departure:%Y%m%d}" if s.flight_number
            else f"{s.carrier}{s.origin}{s.destination}@{s.departure:%Y%m%d%H%M}"
            for sl in self.slices
            for s in sl.segments
        )


class Stopover(BaseModel):
    airport: str
    hours: float


class Trip(BaseModel):
    """One or more tickets combined into a door to door plan. A trip with a
    single ticket is a normal search result. Several tickets means a split
    ticket or stopover plan built by the planner."""

    tickets: list[Itinerary]
    total_price: float
    currency: str
    kind: Literal["single", "split", "stopover", "nested", "multicity", "nearby"] = "single"
    stopovers: list[Stopover] = Field(default_factory=list)
    # "nearby": leaves from or lands at another airport than asked, e.g.
    # "Lands at TRF (Sandefjord), 110 km from OSL"
    note: str | None = None
    risks: list[str] = Field(default_factory=list)
    savings_vs_direct: float | None = None
    score: float | None = None

    @computed_field
    @property
    def id(self) -> str:
        return hashlib.sha1("+".join(t.id for t in self.tickets).encode()).hexdigest()[:16]

    @computed_field
    @property
    def route(self) -> list[str]:
        """Airports in travel order across all tickets."""
        legs = sorted(
            (sl for t in self.tickets for sl in t.slices), key=lambda sl: sl.departure
        )
        out: list[str] = []
        for sl in legs:
            for s in sl.segments:
                if not out or out[-1] != s.origin:
                    out.append(s.origin)
                out.append(s.destination)
        return out

    @computed_field
    @property
    def departure(self) -> datetime:
        return min(sl.departure for t in self.tickets for sl in t.slices)

    @computed_field
    @property
    def arrival(self) -> datetime:
        return max(sl.arrival for t in self.tickets for sl in t.slices)

    @computed_field
    @property
    def travel_min(self) -> int:
        """Time spent in transit for the outbound journey (first slice chain)."""
        return sum(t.slices[0].duration_min for t in self.tickets)


class DatePrice(BaseModel):
    """Cheapest known price for a date (or date pair) on a route."""

    origin: str
    destination: str
    departure: date
    return_date: date | None = None
    price: float
    currency: str
    source: Source
    booking_url: str | None = None


class Destination(BaseModel):
    """An explore result: a cheap place to go from an origin."""

    origin: str
    destination: str
    city: str | None = None
    country: str | None = None
    price: float
    currency: str
    departure: date | None = None
    return_date: date | None = None
    source: Source
    booking_url: str | None = None
    lat: float | None = None
    lon: float | None = None


class SearchQuery(BaseModel):
    origins: list[str]
    destinations: list[str]
    departure: date
    return_date: date | None = None
    adults: int = 1
    cabin: Cabin = "economy"
    max_stops: int | None = None
    currency: str = "USD"
    # "airlines" = every direct airline source that flies the route,
    # "otas" = every booking site / metasearch source
    sources: list[Source | Literal["airlines", "otas", "otas_fast", "otas_slow"]] = Field(default_factory=lambda: [
        "google", "kiwi", "kiwiweb", "airlines", "otas"])
    departure_flex_days: int = 0
    return_flex_days: int = 0
    nearby_km: int = 0  # also search airports within this radius of each side

    @model_validator(mode="after")
    def _sane(self) -> "SearchQuery":
        from datetime import date as _d, timedelta as _td

        if not self.origins or not self.destinations:
            raise ValueError("pick where you fly from and to")
        if self.departure < _d.today() - _td(days=1):
            raise ValueError(f"the departure date {self.departure} is in the past")
        if self.return_date and self.return_date < self.departure:
            raise ValueError("the return date is before the departure date")
        if not 1 <= self.adults <= 9:
            raise ValueError("1 to 9 adults")
        if not (len(self.currency) == 3 and self.currency.isalpha()):
            raise ValueError(f"{self.currency!r} is not a currency code")
        self.currency = self.currency.upper()
        self.origins = [c.strip().upper() for c in self.origins]
        self.destinations = [c.strip().upper() for c in self.destinations]
        return self


class SearchResult(BaseModel):
    query: SearchQuery
    trips: list[Trip]
    errors: dict[str, str] = Field(default_factory=dict)
    searched_at: datetime = Field(default_factory=now_utc)
    google_url: str | None = None
