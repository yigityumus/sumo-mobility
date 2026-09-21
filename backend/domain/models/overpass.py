"""Overpass API access and response caching."""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from shared.config import Settings


class OverpassError(RuntimeError):
    pass


@dataclass
class CacheEntry:
    created_at: float
    endpoint: str
    payload: dict[str, Any]


class TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> CacheEntry | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if time.monotonic() - entry.created_at > self.ttl_seconds:
                self._entries.pop(key, None)
                return None
            return entry

    async def set(self, key: str, endpoint: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            self._entries[key] = CacheEntry(
                created_at=time.monotonic(),
                endpoint=endpoint,
                payload=payload,
            )


def normalize_ring(
    coordinates: list[tuple[float, float]],
    settings: Settings,
) -> list[tuple[float, float]]:
    ring = list(coordinates)

    if ring[0] == ring[-1]:
        ring = ring[:-1]

    if len(ring) < 3:
        raise ValueError("The area boundary must contain at least three distinct points.")

    if len(ring) > settings.max_boundary_vertices:
        raise ValueError(
            f"The area boundary contains too many points. "
            f"Maximum: {settings.max_boundary_vertices}."
        )

    longitudes = [point[0] for point in ring]
    latitudes = [point[1] for point in ring]

    longitude_span = max(longitudes) - min(longitudes)
    latitude_span = max(latitudes) - min(latitudes)

    if max(longitude_span, latitude_span) > settings.max_boundary_span_degrees:
        raise ValueError(
            "The selected area is too large for this area-oriented endpoint. "
            "Draw a smaller boundary or raise MAX_BOUNDARY_SPAN_DEGREES in backend/.env."
        )

    return ring


def _polygon_filter(ring: list[tuple[float, float]]) -> str:
    # Overpass polygon filters use "latitude longitude" pairs.
    return " ".join(f"{lat:.7f} {lon:.7f}" for lon, lat in ring)


def build_building_query(ring: list[tuple[float, float]]) -> str:
    polygon = _polygon_filter(ring)

    return f'''
[out:json][timeout:90];
(
  way["building"](poly:"{polygon}");
  relation["building"](poly:"{polygon}");
);
out tags geom;
'''.strip()


def build_area_features_query(ring: list[tuple[float, float]]) -> str:
    """Load building polygons and parking-area polygons in one Overpass request."""
    polygon = _polygon_filter(ring)

    return f'''
[out:json][timeout:90];
(
  way["building"](poly:"{polygon}");
  relation["building"](poly:"{polygon}");
  way["amenity"="parking"](poly:"{polygon}");
  relation["amenity"="parking"](poly:"{polygon}");
);
out tags geom;
'''.strip()


def build_osm_extract_query(ring: list[tuple[float, float]]) -> str:
    """Build an Overpass XML query for a reusable local OSM extract."""
    polygon = _polygon_filter(ring)

    return f'''
[out:xml][timeout:90];
(
  node(poly:"{polygon}");
  way(poly:"{polygon}");
  relation(poly:"{polygon}");
);
(._;>;);
out meta;
'''.strip()


def cache_key_for_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _response_error(endpoint: str, method: str, response: httpx.Response) -> str:
    excerpt = " ".join(response.text.strip().split())[:300]
    suffix = f": {excerpt}" if excerpt else ""
    return f"{endpoint} ({method}): HTTP {response.status_code}{suffix}"


def _exception_error(endpoint: str, method: str, exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return f"{endpoint} ({method}): {message}"


async def _parse_success(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict) or "elements" not in payload:
        return None

    return payload


def _http_timeout(settings: Settings) -> httpx.Timeout:
    return httpx.Timeout(
        settings.overpass_timeout_seconds,
        connect=min(20.0, settings.overpass_timeout_seconds),
    )


def _base_headers(settings: Settings) -> dict[str, str]:
    # [out:json]/[out:xml] controls the response format. Avoid a restrictive
    # Accept header because some Overpass frontends reject content negotiation.
    return {
        "User-Agent": settings.osm_user_agent,
    }


async def _fetch_query(
    query: str,
    settings: Settings,
    cache: TTLCache,
) -> tuple[dict[str, Any], str, bool]:
    cache_key = cache_key_for_query(query)
    cached = await cache.get(cache_key)

    if cached is not None:
        return cached.payload, cached.endpoint, True

    encoded_body = urlencode({"data": query})
    errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=_http_timeout(settings),
        follow_redirects=True,
        headers=_base_headers(settings),
    ) as client:
        for endpoint in settings.endpoints:
            attempts = (
                (
                    "POST",
                    lambda: client.post(
                        endpoint,
                        content=encoded_body,
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
                        },
                    ),
                ),
                (
                    "GET",
                    lambda: client.get(endpoint, params={"data": query}),
                ),
            )

            for method, request in attempts:
                try:
                    response = await request()
                except httpx.HTTPError as exc:
                    errors.append(_exception_error(endpoint, method, exc))
                    continue

                if not response.is_success:
                    errors.append(_response_error(endpoint, method, response))
                    continue

                payload = await _parse_success(response)
                if payload is None:
                    errors.append(
                        f"{endpoint} ({method}): successful HTTP response but "
                        "the body was not valid Overpass JSON"
                    )
                    continue

                await cache.set(cache_key, endpoint, payload)
                return payload, endpoint, False

    detail = "; ".join(errors) if errors else "No Overpass endpoints are configured."
    raise OverpassError(
        "All Overpass requests failed. The selected boundary is still available; "
        f"you can retry. Details: {detail}"
    )


async def _fetch_query_text(
    query: str,
    settings: Settings,
) -> tuple[str, str]:
    encoded_body = urlencode({"data": query})
    errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=_http_timeout(settings),
        follow_redirects=True,
        headers=_base_headers(settings),
    ) as client:
        for endpoint in settings.endpoints:
            attempts = (
                (
                    "POST",
                    lambda: client.post(
                        endpoint,
                        content=encoded_body,
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
                        },
                    ),
                ),
                (
                    "GET",
                    lambda: client.get(endpoint, params={"data": query}),
                ),
            )

            for method, request in attempts:
                try:
                    response = await request()
                except httpx.HTTPError as exc:
                    errors.append(_exception_error(endpoint, method, exc))
                    continue

                if not response.is_success:
                    errors.append(_response_error(endpoint, method, response))
                    continue

                text = response.text
                if "<osm" not in text[:1000]:
                    errors.append(
                        f"{endpoint} ({method}): successful HTTP response but "
                        "the body did not look like OSM XML"
                    )
                    continue

                return text, endpoint

    detail = "; ".join(errors) if errors else "No Overpass endpoints are configured."
    raise OverpassError(
        "All Overpass OSM export requests failed. The selected boundary is still "
        f"available; you can retry. Details: {detail}"
    )


async def fetch_buildings(
    ring: list[tuple[float, float]],
    settings: Settings,
    cache: TTLCache,
) -> tuple[dict[str, Any], str, bool]:
    return await _fetch_query(build_building_query(ring), settings, cache)


async def fetch_area_features(
    ring: list[tuple[float, float]],
    settings: Settings,
    cache: TTLCache,
) -> tuple[dict[str, Any], str, bool]:
    return await _fetch_query(build_area_features_query(ring), settings, cache)


async def fetch_osm_extract(
    ring: list[tuple[float, float]],
    settings: Settings,
) -> tuple[str, str]:
    return await _fetch_query_text(build_osm_extract_query(ring), settings)
