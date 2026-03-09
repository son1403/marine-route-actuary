"""Core logic for detecting high risk route intersections."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import unicodedata
from pathlib import Path
from typing import Callable, Iterable, List, Mapping, MutableSequence, Optional, Tuple, Union

import pandas as pd

try:
    from shapely.geometry import LineString, box
    from shapely.geometry.base import BaseGeometry
    from shapely.prepared import prep
except Exception as exc:  # pragma: no cover - handled at runtime
    LineString = None  # type: ignore
    BaseGeometry = None  # type: ignore
    box = None  # type: ignore
    prep = None  # type: ignore
    _SHAPELY_IMPORT_ERROR = exc
else:
    _SHAPELY_IMPORT_ERROR = None


BBox = Tuple[float, float, float, float]
LonLat = Tuple[float, float]  # (lon, lat)
RiskAreaInput = Union[BaseGeometry, BBox]
PlaceResolver = Callable[[object], Optional[LonLat]]
PlaceNormalizer = Callable[[object], str]


@dataclass(frozen=True)
class PreparedArea:
    geom: BaseGeometry
    prepared: object


class RiskInputError(ValueError):
    """Raised when inputs are missing or invalid."""


def _ensure_shapely() -> None:
    if _SHAPELY_IMPORT_ERROR is not None:
        raise ImportError(
            "shapely is required for geometry operations. Install with: pip install shapely"
        ) from _SHAPELY_IMPORT_ERROR


def normalize_place_name(value: object) -> str:
    """Normalize place names for matching across languages/diacritics."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


def make_nominatim_resolver(
    *,
    user_agent: str = "marine-route-actuary",
    timeout: int = 10,
) -> PlaceResolver:
    """Create a geocoding resolver backed by Nominatim (OpenStreetMap).

    Requires: pip install geopy
    """
    try:
        from geopy.geocoders import Nominatim
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("geopy is required for geocoding. Install with: pip install geopy") from exc

    geocoder = Nominatim(user_agent=user_agent, timeout=timeout)

    def _resolve(value: object) -> Optional[LonLat]:
        if value is None:
            return None
        location = geocoder.geocode(str(value))
        if location is None:
            return None
        return (float(location.longitude), float(location.latitude))

    return _resolve


def _load_place_cache(path: Path) -> dict[str, LonLat]:
    if not path.exists():
        return {}

    cache: dict[str, LonLat] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row:
                continue
            norm = row.get("place_norm")
            lon = row.get("lon")
            lat = row.get("lat")
            if not norm or lon is None or lat is None:
                continue
            try:
                cache[norm] = (float(lon), float(lat))
            except ValueError:
                continue
    return cache


def _append_place_cache(
    path: Path,
    place_norm: str,
    place_raw: str,
    coord: LonLat,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["place_norm", "place_raw", "lon", "lat"],
        )
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "place_norm": place_norm,
                "place_raw": place_raw,
                "lon": coord[0],
                "lat": coord[1],
            }
        )


def make_cached_resolver(
    cache_path: Union[str, Path],
    *,
    base_resolver: Optional[PlaceResolver] = None,
    normalizer: PlaceNormalizer = normalize_place_name,
    user_agent: str = "marine-route-actuary",
    timeout: int = 10,
) -> PlaceResolver:
    """Create a resolver that caches place lookups to a CSV file.

    Parameters
    ----------
    cache_path:
        CSV file path where resolved coordinates are stored.
    base_resolver:
        Resolver used when a place is not in the cache. If None, uses Nominatim.
    normalizer:
        Normalizes place names for cache keys.
    """
    path = Path(cache_path)
    cache = _load_place_cache(path)

    if base_resolver is None:
        base_resolver = make_nominatim_resolver(user_agent=user_agent, timeout=timeout)

    def _resolve(value: object) -> Optional[LonLat]:
        if value is None:
            return None
        raw = str(value)
        norm = normalizer(value)
        if norm in cache:
            return cache[norm]
        coord = base_resolver(value)
        if coord is None:
            return None
        coord = (float(coord[0]), float(coord[1]))
        cache[norm] = coord
        _append_place_cache(path, norm, raw, coord)
        return coord

    return _resolve


def normalize_high_risk_areas(areas: Iterable[RiskAreaInput]) -> List[PreparedArea]:
    """Normalize high risk area inputs into prepared Shapely geometries.

    Accepts Shapely geometries or bounding boxes as (min_lon, min_lat, max_lon, max_lat).
    """
    _ensure_shapely()

    normalized: List[PreparedArea] = []
    for area in areas:
        if area is None:
            continue
        if isinstance(area, tuple) and len(area) == 4:
            geom = box(*area)
        elif isinstance(area, BaseGeometry):
            geom = area
        else:
            raise RiskInputError(
                "high_risk_areas must contain Shapely geometries or bounding boxes"
            )
        normalized.append(PreparedArea(geom=geom, prepared=prep(geom)))

    if not normalized:
        raise RiskInputError("high_risk_areas is empty after normalization")

    return normalized


def _build_normalized_lookup(
    lookup: Mapping[object, LonLat],
    normalizer: PlaceNormalizer,
) -> Mapping[str, Optional[LonLat]]:
    normalized: dict[str, Optional[LonLat]] = {}
    collisions: dict[str, List[object]] = {}

    for key, coord in lookup.items():
        norm_key = normalizer(key)
        if coord is None:
            new_coord = None
        else:
            new_coord = (float(coord[0]), float(coord[1]))
        if norm_key in normalized and normalized[norm_key] != new_coord:
            collisions.setdefault(norm_key, [key])
            collisions[norm_key].append(key)
        else:
            normalized[norm_key] = new_coord

    if collisions:
        examples = ", ".join(list(collisions.keys())[:3])
        raise RiskInputError(
            "Normalized place names are ambiguous. "
            f"Conflicts for: {examples}. Please adjust your lookup keys."
        )

    return normalized


def _wrap_resolver(
    resolver: PlaceResolver,
    normalizer: Optional[PlaceNormalizer],
) -> PlaceResolver:
    cache: dict[object, Optional[LonLat]] = {}

    def _inner(value: object) -> Optional[LonLat]:
        key = normalizer(value) if normalizer is not None else value
        if key in cache:
            return cache[key]
        cache[key] = resolver(value)
        return cache[key]

    return _inner


def _resolve_place(
    value: object,
    lookup: Optional[Mapping[object, LonLat]],
    normalized_lookup: Optional[Mapping[str, Optional[LonLat]]],
    resolver: Optional[PlaceResolver],
    normalizer: Optional[PlaceNormalizer],
) -> Optional[LonLat]:
    if lookup is not None and value in lookup:
        coord = lookup[value]
        if coord is None:
            return None
        return (float(coord[0]), float(coord[1]))
    if normalizer is not None and normalized_lookup is not None:
        norm_key = normalizer(value)
        if norm_key in normalized_lookup:
            coord = normalized_lookup[norm_key]
            if coord is None:
                return None
            return (float(coord[0]), float(coord[1]))
    if resolver is None:
        return None
    coord = resolver(value)
    if coord is None:
        return None
    return (float(coord[0]), float(coord[1]))


def _build_straight_route(from_coord: LonLat, to_coord: LonLat) -> BaseGeometry:
    _ensure_shapely()
    return LineString([from_coord, to_coord])


def _build_scgraph_route(
    from_coord: LonLat,
    to_coord: LonLat,
    options: Optional[Mapping[str, object]],
) -> Optional[BaseGeometry]:
    _ensure_shapely()
    try:
        from scgraph.geographs.marnet import marnet_geograph
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("scgraph is required. Install with: pip install scgraph") from exc

    opts = dict(options or {})
    origin = {"latitude": from_coord[1], "longitude": from_coord[0]}
    destination = {"latitude": to_coord[1], "longitude": to_coord[0]}

    result = marnet_geograph.get_shortest_path(
        origin_node=origin,
        destination_node=destination,
        **opts,
    )
    path = result.get("coordinate_path") if isinstance(result, dict) else None
    if not path:
        return None

    coords: List[LonLat] = []
    for item in path:
        if isinstance(item, Mapping):
            lat = float(item["latitude"])
            lon = float(item["longitude"])
        else:
            lat = float(item[0])
            lon = float(item[1])
        coords.append((lon, lat))

    if len(coords) < 2:
        return None
    return LineString(coords)


def _extract_searoute_coords(route: object) -> Optional[List[LonLat]]:
    coords = None
    if isinstance(route, Mapping):
        coords = route.get("geometry", {}).get("coordinates")
    if coords is None:
        geometry = getattr(route, "geometry", None)
        if geometry is not None:
            if isinstance(geometry, Mapping):
                coords = geometry.get("coordinates")
            else:
                coords = getattr(geometry, "coordinates", None)
    if not coords:
        return None
    return [(float(lon), float(lat)) for lon, lat in coords]


def _build_searoute_route(
    from_coord: LonLat,
    to_coord: LonLat,
    options: Optional[Mapping[str, object]],
) -> Optional[BaseGeometry]:
    _ensure_shapely()
    try:
        import searoute as sr
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("searoute is required. Install with: pip install searoute") from exc

    opts = dict(options or {})
    route = sr.searoute(list(from_coord), list(to_coord), **opts)
    coords = _extract_searoute_coords(route)
    if not coords or len(coords) < 2:
        return None
    return LineString(coords)


def _build_route_geometry(
    from_coord: LonLat,
    to_coord: LonLat,
    route_engine: str,
    route_engine_options: Optional[Mapping[str, object]],
) -> Optional[BaseGeometry]:
    engine = (route_engine or "straight").lower()
    if engine == "straight":
        return _build_straight_route(from_coord, to_coord)
    if engine == "scgraph":
        return _build_scgraph_route(from_coord, to_coord, route_engine_options)
    if engine == "searoute":
        return _build_searoute_route(from_coord, to_coord, route_engine_options)
    raise RiskInputError(f"Unknown route_engine: {route_engine}")


def _iter_routes(
    df: pd.DataFrame,
    from_col: str,
    to_col: str,
    location_lookup: Optional[Mapping[object, LonLat]],
    place_resolver: Optional[PlaceResolver],
    place_normalizer: Optional[PlaceNormalizer],
    route_geometry_col: Optional[str],
    route_engine: str,
    route_engine_options: Optional[Mapping[str, object]],
) -> List[Optional[BaseGeometry]]:
    routes: List[Optional[BaseGeometry]] = []

    if route_geometry_col:
        if route_geometry_col not in df.columns:
            raise RiskInputError(f"Missing route geometry column: {route_geometry_col}")
        for geom in df[route_geometry_col].tolist():
            routes.append(geom)
        return routes

    if location_lookup is None and place_resolver is None:
        raise RiskInputError(
            "location_lookup or place_resolver is required when route_geometry_col is not provided"
        )

    if from_col not in df.columns or to_col not in df.columns:
        raise RiskInputError("Missing FROM/TO columns in dataframe")

    resolver = (
        _wrap_resolver(place_resolver, place_normalizer) if place_resolver else None
    )
    normalized_lookup = (
        _build_normalized_lookup(location_lookup, place_normalizer)
        if location_lookup is not None and place_normalizer is not None
        else None
    )

    for from_value, to_value in zip(df[from_col], df[to_col]):
        from_coord = _resolve_place(
            from_value,
            location_lookup,
            normalized_lookup,
            resolver,
            place_normalizer,
        )
        to_coord = _resolve_place(
            to_value,
            location_lookup,
            normalized_lookup,
            resolver,
            place_normalizer,
        )
        if from_coord is None or to_coord is None:
            routes.append(None)
            continue
        routes.append(
            _build_route_geometry(
                from_coord,
                to_coord,
                route_engine=route_engine,
                route_engine_options=route_engine_options,
            )
        )

    return routes


def flag_high_risk_routes(
    df: pd.DataFrame,
    *,
    from_col: str = "FROM",
    to_col: str = "TO",
    location_lookup: Optional[Mapping[object, LonLat]] = None,
    place_resolver: Optional[PlaceResolver] = None,
    place_normalizer: Optional[PlaceNormalizer] = normalize_place_name,
    route_geometry_col: Optional[str] = None,
    route_engine: str = "scgraph",
    route_engine_options: Optional[Mapping[str, object]] = None,
    high_risk_areas: Optional[Iterable[RiskAreaInput]] = None,
    return_col: Optional[str] = "high_risk",
) -> Union[pd.DataFrame, pd.Series]:
    """Flag routes that intersect high risk areas.

    Parameters
    ----------
    df:
        DataFrame with FROM/TO columns or a route geometry column.
    from_col, to_col:
        Column names for origin/destination.
    location_lookup:
        Mapping from place names to (lon, lat) coordinates.
    place_resolver:
        Callable that resolves a place name to (lon, lat). Used as fallback after lookup.
    place_normalizer:
        Normalizes place names (e.g., case/diacritics) for matching. Set to None to disable.
    route_geometry_col:
        Optional column name that already contains Shapely LineString geometries.
    route_engine:
        One of: "scgraph", "searoute", or "straight".
    route_engine_options:
        Extra keyword arguments passed to the routing engine.
    high_risk_areas:
        Iterable of Shapely geometries or bounding boxes (min_lon, min_lat, max_lon, max_lat).
    return_col:
        Column name to append to the dataframe. If None, return a boolean Series.
    """
    if high_risk_areas is None:
        raise RiskInputError("high_risk_areas is required")

    areas = normalize_high_risk_areas(high_risk_areas)
    routes = _iter_routes(
        df,
        from_col,
        to_col,
        location_lookup,
        place_resolver,
        place_normalizer,
        route_geometry_col,
        route_engine,
        route_engine_options,
    )

    flags: MutableSequence[bool] = []
    for route in routes:
        if route is None:
            flags.append(False)
            continue
        hit = False
        for area in areas:
            if area.prepared.intersects(route):
                hit = True
                break
        flags.append(hit)

    series = pd.Series(flags, index=df.index, name=return_col or "high_risk")

    if return_col is None:
        return series

    out = df.copy()
    out[return_col] = series
    return out
