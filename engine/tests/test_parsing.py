import json

from conftest import FIXTURES

from flightscout.client import _snake
from flightscout.sources import google_explore, kiwi


def test_kiwi_flight_number_strips_duplicated_carrier():
    assert kiwi._flight_no("H2270", "H2") == "270"  # Sky Airline flight 270
    assert kiwi._flight_no(1200, "KL") == "1200"
    assert kiwi._flight_no(None, "KL") is None


def test_kiwi_itineraries_parse_and_flag_self_transfer():
    data = json.loads((FIXTURES / "kiwi_osl_san.json").read_text())
    its = kiwi._itins(data)
    assert len(its) == 3
    assert all(i.source == "kiwi" and i.seller == "Kiwi.com" and i.booking_url.startswith("https://") for i in its)
    assert any(i.self_transfer for i in its)
    assert its[0].slices[0].origin in ("OSL", "TRF") and its[0].slices[0].destination == "SAN"


def test_google_explore_parse_fixture():
    body = (FIXTURES / "google_explore_san.txt").read_text()
    dests = google_explore.parse([body], "SAN", "USD")
    assert len(dests) >= 40
    las = next(d for d in dests if d.destination == "LAS")
    assert las.city == "Las Vegas" and las.price > 0 and las.departure and las.lat


def test_snake_case_conversion_keeps_payloads():
    out = _snake({"departStart": "x", "bestTrip": {"keepMe": 1}, "items": [{"nightsMin": 3}]})
    assert out["depart_start"] == "x" and out["best_trip"] == {"keepMe": 1} and out["items"][0]["nights_min"] == 3
