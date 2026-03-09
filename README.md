# marine-route-actuary

Flag shipping routes that intersect high risk areas.

## Install (editable during development)

```bash
pip install -e .
```

Optional extras:

```bash
pip install -e ".[geocoding,searoute]"
```

## Usage (name -> route via scgraph)

```python
import pandas as pd
from shapely.geometry import Polygon
from marine_route_actuary import flag_high_risk_routes

# Sample data (place names)
rows = [
    {"FROM": "Singapore", "TO": "Dubai"},
    {"FROM": "Hong Kong", "TO": "Los Angeles"},
]

df = pd.DataFrame(rows)

# Lookup of place name -> (lon, lat)
lookup = {
    "Singapore": (103.8198, 1.3521),
    "Dubai": (55.2708, 25.2048),
    "Hong Kong": (114.1694, 22.3193),
    "Los Angeles": (-118.4085, 33.9416),
}

# High risk area polygon (example)
area = Polygon([
    (45.0, 10.0),
    (60.0, 10.0),
    (60.0, 30.0),
    (45.0, 30.0),
])

out = flag_high_risk_routes(
    df,
    from_col="FROM",
    to_col="TO",
    location_lookup=lookup,
    route_engine="scgraph",
    high_risk_areas=[area],
)

print(out)
```

## Usage (geocode place names)

```python
import pandas as pd
from shapely.geometry import Polygon
from marine_route_actuary import flag_high_risk_routes, make_nominatim_resolver

rows = [
    {"FROM": "Singapore", "TO": "Dubai"},
]

df = pd.DataFrame(rows)
area = Polygon([
    (45.0, 10.0),
    (60.0, 10.0),
    (60.0, 30.0),
    (45.0, 30.0),
])

resolver = make_nominatim_resolver()

out = flag_high_risk_routes(
    df,
    place_resolver=resolver,
    route_engine="scgraph",
    high_risk_areas=[area],
)

print(out)
```

## Notes

- `location_lookup` expects coordinates in `(lon, lat)` order.
- Place names are normalized (lowercase, strip diacritics). Set `place_normalizer=None` to disable.
- `route_engine="scgraph"` builds a maritime route; `route_engine="searoute"` is supported as an optional engine.
- Provide a `route_geometry_col` if you already have accurate route geometries.
