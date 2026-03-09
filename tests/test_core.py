import pandas as pd
from shapely.geometry import Polygon, box

from marine_route_actuary import flag_high_risk_routes, make_cached_resolver


def test_flag_high_risk_routes_from_to_lookup():
    df = pd.DataFrame(
        [
            {"FROM": "A", "TO": "B"},
            {"FROM": "C", "TO": "D"},
        ]
    )

    lookup = {
        "A": (0.0, 0.0),
        "B": (10.0, 0.0),
        "C": (0.0, 10.0),
        "D": (10.0, 10.0),
    }

    area = Polygon([
        (4.0, -1.0),
        (6.0, -1.0),
        (6.0, 1.0),
        (4.0, 1.0),
    ])

    out = flag_high_risk_routes(
        df,
        location_lookup=lookup,
        route_engine="straight",
        high_risk_areas=[area],
    )

    assert out["high_risk"].tolist() == [True, False]


def test_place_name_normalization_lookup():
    df = pd.DataFrame(
        [
            {"FROM": "Hồ Chí Minh City", "TO": "Singapore"},
        ]
    )

    lookup = {
        "Ho Chi Minh City": (106.6297, 10.8231),
        "Singapore": (103.8198, 1.3521),
    }

    area = box(102.0, 0.0, 107.0, 12.0)

    out = flag_high_risk_routes(
        df,
        location_lookup=lookup,
        route_engine="straight",
        high_risk_areas=[area],
    )

    assert out["high_risk"].tolist() == [True]


def test_cached_resolver_uses_cache(tmp_path):
    calls = {"count": 0}

    def base_resolver(value):
        calls["count"] += 1
        return (106.6297, 10.8231)

    cache_file = tmp_path / "places_cache.csv"
    resolver = make_cached_resolver(cache_file, base_resolver=base_resolver)

    # First call hits base_resolver
    coord1 = resolver("Hồ Chí Minh City")
    assert coord1 == (106.6297, 10.8231)
    assert calls["count"] == 1

    # Second call (normalized) should hit cache
    coord2 = resolver("Ho Chi Minh City")
    assert coord2 == (106.6297, 10.8231)
    assert calls["count"] == 1
