# marine-route-actuary

Python package for actuaries to flag whether a shipping route passes through high‑risk areas.

The workflow is:
1. Provide a DataFrame with `FROM` and `TO` place names.
2. Resolve place names to coordinates (lookup table or geocoding).
3. Build a maritime route (default: `scgraph`).
4. Check if the route intersects any high‑risk area polygons.

## Installation

For development from source:

```bash
pip install -e .
```

Optional extras:

```bash
pip install -e ".[geocoding,searoute]"
```

## Quick Start (lookup table, recommended)

```python
import pandas as pd
from shapely.geometry import Polygon
from marine_route_actuary import flag_high_risk_routes

# Input data
rows = [
    {"FROM": "Nottingham", "TO": "Viet Nam"},
    {"FROM": "Singapore", "TO": "Dubai"},
]

df = pd.DataFrame(rows)

# Place name -> (lon, lat)
lookup = {
    "Nottingham": (-1.1581, 52.9548),
    "Viet Nam": (105.8342, 21.0278),
    "Singapore": (103.8198, 1.3521),
    "Dubai": (55.2708, 25.2048),
}

# High‑risk area (example polygon)
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
    route_engine="scgraph",  # default
    high_risk_areas=[area],
)

print(out[["FROM", "TO", "high_risk"]])
```

## Quick Start (geocoding place names)

If you do not have a lookup table, you can geocode place names with OpenStreetMap (Nominatim).

```python
import pandas as pd
from shapely.geometry import box
from marine_route_actuary import flag_high_risk_routes, make_nominatim_resolver

rows = [
    {"FROM": "Nottingham", "TO": "Viet Nam"},
]

df = pd.DataFrame(rows)

# Example: Strait of Hormuz bounding box (lon, lat)
hormuz_bbox = box(55.5, 25.5, 57.5, 27.5)

resolver = make_nominatim_resolver()

out = flag_high_risk_routes(
    df,
    place_resolver=resolver,
    route_engine="scgraph",
    high_risk_areas=[hormuz_bbox],
)

print(out[["FROM", "TO", "high_risk"]])
```

## Quick Start (geocoding + cache)

If you want automatic conversion but avoid repeated API calls, use the cached resolver.
The first run calls the geocoder and writes to a CSV cache; later runs reuse it.

```python
import pandas as pd
from shapely.geometry import box
from marine_route_actuary import flag_high_risk_routes, make_cached_resolver

df = pd.DataFrame([{"FROM": "Nottingham", "TO": "Viet Nam"}])
hormuz_bbox = box(55.5, 25.5, 57.5, 27.5)

resolver = make_cached_resolver("places_cache.csv")

out = flag_high_risk_routes(
    df,
    place_resolver=resolver,
    route_engine="scgraph",
    high_risk_areas=[hormuz_bbox],
)

print(out[["FROM", "TO", "high_risk"]])
```

## Inputs and Outputs

**Inputs**
- DataFrame with two columns: `FROM` and `TO` (place names).
- `high_risk_areas`: list of Shapely polygons or bounding boxes `(min_lon, min_lat, max_lon, max_lat)`.
- Either `location_lookup` or `place_resolver` to resolve place names to `(lon, lat)`.

**Output**
- Returns a DataFrame with an added boolean column `high_risk`.

## Name Normalization (English + Vietnamese)

Place names are normalized by default (lowercase, strip diacritics). This helps match:
- `"Hồ Chí Minh City"` == `"Ho Chi Minh City"`

Disable normalization if you need exact matching:

```python
out = flag_high_risk_routes(
    df,
    location_lookup=lookup,
    place_normalizer=None,
    high_risk_areas=[area],
)
```

## Notes for Actuarial Use

- If a place name cannot be resolved, the route is treated as missing and `high_risk=False`.
  Keep a QA step to detect unresolved names.
- `scgraph` builds a maritime route (not a straight line). This is the default engine.
- `searoute` is available as an optional engine if you install `.[searoute]`.
- Coordinates are always `(lon, lat)`.

## Insurance Pricing Workflow Example (illustrative)

This example shows a simple pricing workflow where a high‑risk route adds a surcharge.
Adjust rates and logic to your internal pricing models.

```python
import pandas as pd
from shapely.geometry import box
from marine_route_actuary import flag_high_risk_routes

# 1 record for a quick demo
df = pd.DataFrame(
    [
        {"FROM": "Singapore", "TO": "Dubai", "sum_insured_usd": 1_000_000, "base_rate": 0.0010},
    ]
)

# Place name -> (lon, lat)
lookup = {
    "Singapore": (103.8198, 1.3521),
    "Dubai": (55.2708, 25.2048),
}

# Toy high‑risk box (covers the route area for demo)
toy_risk = box(40.0, 0.0, 110.0, 30.0)

# Step 1: Flag high‑risk routes
df = flag_high_risk_routes(
    df,
    location_lookup=lookup,
    route_engine="straight",  # for a deterministic demo
    high_risk_areas=[toy_risk],
)

# Step 2: Apply risk load (+40% if high‑risk)
df["risk_load"] = df["high_risk"].map(lambda x: 1.40 if x else 1.00)

# Step 3: Price
df["premium_usd"] = df["sum_insured_usd"] * df["base_rate"] * df["risk_load"]

print(df[["FROM", "TO", "high_risk", "premium_usd"]])
# Expected: high_risk=True, premium_usd=1400.0
```

For production, set `route_engine="scgraph"` (default) to use maritime routes.

```python
import pandas as pd
from shapely.geometry import Polygon
from marine_route_actuary import flag_high_risk_routes

# Portfolio inputs
df = pd.DataFrame(
    [
        {"FROM": "Singapore", "TO": "Dubai", "sum_insured_usd": 2_000_000, "base_rate": 0.0015},
        {"FROM": "Hong Kong", "TO": "Los Angeles", "sum_insured_usd": 3_500_000, "base_rate": 0.0012},
    ]
)

# Place name -> (lon, lat)
lookup = {
    "Singapore": (103.8198, 1.3521),
    "Dubai": (55.2708, 25.2048),
    "Hong Kong": (114.1694, 22.3193),
    "Los Angeles": (-118.4085, 33.9416),
}

# Example high‑risk area polygon
area = Polygon([
    (45.0, 10.0),
    (60.0, 10.0),
    (60.0, 30.0),
    (45.0, 30.0),
])

# Step 1: Flag high‑risk routes
df = flag_high_risk_routes(
    df,
    location_lookup=lookup,
    high_risk_areas=[area],
)

# Step 2: Apply risk load (example: +40% if high‑risk)
df["risk_load"] = df["high_risk"].map(lambda x: 1.40 if x else 1.00)

# Step 3: Price
df["premium_usd"] = df["sum_insured_usd"] * df["base_rate"] * df["risk_load"]

print(df[["FROM", "TO", "high_risk", "premium_usd"]])
```

## Version Requirements

- Python >= 3.10 (required by `scgraph`).
