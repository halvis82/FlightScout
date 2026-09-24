from flightscout import airports


def test_lookup_and_city_names():
    assert airports.get("SAN").city == "San Diego"
    assert airports.get("MXP").city == "Milan"  # not the municipality "Ferno (VA)"
    assert airports.get("JAC").city == "Jackson Hole"
    assert airports.get("nope") is None


def test_find_is_accent_insensitive_and_ranks_codes_first():
    assert airports.find("cancun")[0].iata == "CUN"
    assert airports.find("OSL")[0].iata == "OSL"
    sj = [a.iata for a in airports.find("san jose")]
    assert {"SJC", "SJD", "SJO"} <= set(sj)


def test_expand_metros_and_dedupe():
    assert airports.expand("NYC") == ["JFK", "EWR", "LGA"]
    assert airports.expand(["BAY", "SFO"]) == ["SFO", "OAK", "SJC"]
    assert airports.expand("osl, trf") == ["OSL", "TRF"]


def test_nearby_links_tijuana_to_san_diego():
    near = airports.nearby("SAN", 150)
    assert near[0] == "TIJ"  # Cross Border Xpress
    assert "SNA" in near and "SAN" not in near
    assert airports.nearby("SAN", 0) == []


def test_gateways_near_prefers_real_hubs():
    assert "LAX" in airports.gateways_near("SAN")
    assert airports.gateways_near("SJC") == ["SFO"]


def test_candidate_hubs_are_on_the_way():
    hubs = airports.candidate_hubs("OSL", "SAN", limit=10)
    assert hubs and "OSL" not in hubs and "SAN" not in hubs
    for h in hubs:
        direct = airports.haversine_km("OSL", "SAN")
        assert airports.haversine_km("OSL", h) + airports.haversine_km(h, "SAN") <= direct * 1.35 * 1.3
