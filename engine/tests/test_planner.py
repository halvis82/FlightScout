from datetime import date, timedelta

from conftest import ticket

from flightscout import planner
from flightscout.multicity import Leg, _window
from flightscout.models import Trip


def req(**kw):
    return planner.PlanRequest(origins=["SAN"], destinations=["DPS"], depart_start=date.today(), **kw)


def test_chain_accepts_valid_gap_and_marks_stopover(dt):
    a = ticket(["SAN", "LAX"], dt, hours=1)
    b = ticket(["LAX", "DPS"], dt + timedelta(hours=5), hours=18)
    t = planner._chain([a, b], req(min_connection_hours=3))
    assert t and t.kind == "split" and t.total_price == 200
    c = ticket(["LAX", "DPS"], dt + timedelta(days=2), hours=18)
    t2 = planner._chain([a, c], req(max_stopover_days=3))
    assert t2.kind == "stopover" and t2.stopovers[0].airport == "LAX"


def test_chain_rejects_tight_long_or_mismatched(dt):
    a = ticket(["SAN", "LAX"], dt, hours=1)
    assert planner._chain([a, ticket(["LAX", "DPS"], dt + timedelta(hours=2))], req(min_connection_hours=3)) is None
    assert planner._chain([a, ticket(["LAX", "DPS"], dt + timedelta(days=5))], req(max_stopover_days=1)) is None
    assert planner._chain([a, ticket(["SFO", "DPS"], dt + timedelta(hours=6))], req()) is None


def test_dates_sampling():
    s = date(2026, 11, 1)
    assert planner._dates(s, None) == [s]
    assert planner._dates(s, s + timedelta(days=1)) == [s, s + timedelta(days=1)]
    got = planner._dates(s, s + timedelta(days=10), cap=3)
    assert got[0] == s and got[-1] == s + timedelta(days=10) and len(got) == 3


def test_select_keeps_each_kind_and_dedupes(dt):
    trips = []
    for i in range(10):
        trips.append(Trip(tickets=[ticket(["SAN", "DPS"], dt, price=900 + i)], total_price=900 + i, currency="USD", score=900 + i))
    trips.append(Trip(tickets=[ticket(["SAN", "LAX"], dt), ticket(["LAX", "DPS"], dt + timedelta(hours=6))],
                      total_price=1200, currency="USD", kind="split", score=1300))
    out = planner.select(trips, max_results=4)
    assert any(t.kind == "split" for t in out), "a split option survives even when pricier"
    assert len({t.id for t in out}) == len(out)


def test_multicity_window_respects_arrive_by():
    d = date.today() + timedelta(days=40)
    lo, hi = _window(Leg(origins=["OSL"], destinations=["CDG"], date=d, before=5, after=5, arrive_by=d + timedelta(days=1)))
    assert lo == d - timedelta(days=5) and hi == d + timedelta(days=1)
    lo, hi = _window(Leg(origins=["OSL"], destinations=["CDG"], date=date.today(), before=3))
    assert lo > date.today()  # never in the past
