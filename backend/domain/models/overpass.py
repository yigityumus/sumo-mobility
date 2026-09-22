"""Overpass API access and response caching."""

import asyncio
import hashlib
import json
import time
import xml.etree.ElementTree as ET
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


def _point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    px, py = point
    ax, ay = start
    bx, by = end
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > 1e-12:
        return False
    return (
        min(ax, bx) - 1e-12 <= px <= max(ax, bx) + 1e-12
        and min(ay, by) - 1e-12 <= py <= max(ay, by) + 1e-12
    )


def _point_in_ring(
    point: tuple[float, float],
    ring: list[tuple[float, float]],
) -> bool:
    """Return True for points inside or on the edge of the polygon ring."""
    inside = False
    px, py = point
    for start, end in zip(ring, ring[1:] + ring[:1]):
        if _point_on_segment(point, start, end):
            return True
        ax, ay = start
        bx, by = end
        if (ay > py) != (by > py):
            intersection_x = (bx - ax) * (py - ay) / (by - ay) + ax
            if px < intersection_x:
                inside = not inside
    return inside


def _orientation(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> float:
    return (
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    )


def _segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    orientations = (
        _orientation(first_start, first_end, second_start),
        _orientation(first_start, first_end, second_end),
        _orientation(second_start, second_end, first_start),
        _orientation(second_start, second_end, first_end),
    )
    if (
        ((orientations[0] > 0) != (orientations[1] > 0))
        and ((orientations[2] > 0) != (orientations[3] > 0))
    ):
        return True
    return any(
        abs(orientation) <= 1e-12 and _point_on_segment(point, start, end)
        for orientation, point, start, end in (
            (orientations[0], second_start, first_start, first_end),
            (orientations[1], second_end, first_start, first_end),
            (orientations[2], first_start, second_start, second_end),
            (orientations[3], first_end, second_start, second_end),
        )
    )


def _way_intersects_ring(
    coordinates: list[tuple[float, float]],
    ring: list[tuple[float, float]],
) -> bool:
    if any(_point_in_ring(point, ring) for point in coordinates):
        return True
    way_segments = zip(coordinates, coordinates[1:])
    ring_segments = list(zip(ring, ring[1:] + ring[:1]))
    if any(
        _segments_intersect(way_start, way_end, ring_start, ring_end)
        for way_start, way_end in way_segments
        for ring_start, ring_end in ring_segments
    ):
        return True
    return (
        len(coordinates) >= 4
        and coordinates[0] == coordinates[-1]
        and any(_point_in_ring(point, coordinates) for point in ring)
    )


def _tags(element: ET.Element) -> dict[str, str]:
    return {
        str(tag.get("k")): str(tag.get("v"))
        for tag in element.findall("tag")
        if tag.get("k") is not None and tag.get("v") is not None
    }


def _relevant_way(element: ET.Element) -> bool:
    tags = _tags(element)
    return bool(
        tags.get("highway")
        or tags.get("railway")
        or tags.get("building")
        or tags.get("amenity") == "parking"
    )


def _relevant_relation(element: ET.Element) -> bool:
    tags = _tags(element)
    return bool(
        tags.get("building")
        or tags.get("amenity") == "parking"
        or tags.get("type") == "restriction"
    )


def filter_osm_xml_to_polygon(
    xml_text: str,
    ring: list[tuple[float, float]],
) -> str:
    """Filter a small OSM map-API bbox response back to an exact polygon."""
    root = ET.fromstring(xml_text)
    nodes = {
        str(element.get("id")): element
        for element in root.findall("node")
        if element.get("id") is not None
    }
    node_coordinates = {
        node_id: (float(element.get("lon")), float(element.get("lat")))
        for node_id, element in nodes.items()
        if element.get("lon") is not None and element.get("lat") is not None
    }
    ways = {
        str(element.get("id")): element
        for element in root.findall("way")
        if element.get("id") is not None
    }
    relations = {
        str(element.get("id")): element
        for element in root.findall("relation")
        if element.get("id") is not None
    }

    intersecting_ways = {
        way_id
        for way_id, element in ways.items()
        if _way_intersects_ring(
            [
                node_coordinates[ref]
                for nd in element.findall("nd")
                if (ref := str(nd.get("ref"))) in node_coordinates
            ],
            ring,
        )
    }
    selected_ways = {
        way_id
        for way_id in intersecting_ways
        if _relevant_way(ways[way_id])
    }
    inside_nodes = {
        node_id
        for node_id, coordinates in node_coordinates.items()
        if _point_in_ring(coordinates, ring)
    }
    selected_relations = {
        relation_id
        for relation_id, element in relations.items()
        if _relevant_relation(element)
        and any(
            (member.get("type") == "node" and str(member.get("ref")) in inside_nodes)
            or (member.get("type") == "way" and str(member.get("ref")) in intersecting_ways)
            for member in element.findall("member")
        )
    }

    # Building/parking multipolygons and turn restrictions need their complete
    # member geometry, even when an outer member lies beyond the polygon edge.
    selected_nodes: set[str] = set()
    pending_relations = list(selected_relations)
    while pending_relations:
        relation_id = pending_relations.pop()
        for member in relations[relation_id].findall("member"):
            member_type = member.get("type")
            member_id = str(member.get("ref"))
            if member_type == "way" and member_id in ways:
                selected_ways.add(member_id)
            elif member_type == "node" and member_id in nodes:
                selected_nodes.add(member_id)
            elif (
                member_type == "relation"
                and member_id in relations
                and member_id not in selected_relations
            ):
                selected_relations.add(member_id)
                pending_relations.append(member_id)

    for way_id in selected_ways:
        selected_nodes.update(
            str(nd.get("ref"))
            for nd in ways[way_id].findall("nd")
            if nd.get("ref") is not None
        )

    output_root = ET.Element(root.tag, root.attrib)
    for element in root:
        element_id = str(element.get("id"))
        if (
            element.tag == "bounds"
            or (element.tag == "node" and element_id in selected_nodes)
            or (element.tag == "way" and element_id in selected_ways)
            or (element.tag == "relation" and element_id in selected_relations)
        ):
            output_root.append(element)
    return ET.tostring(
        output_root,
        encoding="unicode",
        xml_declaration=True,
    )


async def _fetch_official_osm_map(
    ring: list[tuple[float, float]],
    settings: Settings,
) -> tuple[str, str]:
    longitudes = [point[0] for point in ring]
    latitudes = [point[1] for point in ring]
    bbox_area = (max(longitudes) - min(longitudes)) * (
        max(latitudes) - min(latitudes)
    )
    if bbox_area > settings.osm_map_max_bbox_area_degrees:
        raise OverpassError(
            "The boundary is too large for the official OSM map API fallback."
        )
    bbox = ",".join(
        f"{value:.7f}"
        for value in (
            min(longitudes),
            min(latitudes),
            max(longitudes),
            max(latitudes),
        )
    )
    try:
        async with httpx.AsyncClient(
            timeout=_http_timeout(settings),
            follow_redirects=True,
            headers=_base_headers(settings),
        ) as client:
            response = await client.get(
                settings.osm_map_api_endpoint,
                params={"bbox": bbox},
            )
    except httpx.HTTPError as exc:
        raise OverpassError(
            _exception_error(settings.osm_map_api_endpoint, "GET", exc)
        ) from exc
    if not response.is_success:
        raise OverpassError(
            _response_error(settings.osm_map_api_endpoint, "GET", response)
        )
    if "<osm" not in response.text[:1000]:
        raise OverpassError(
            f"{settings.osm_map_api_endpoint} (GET): successful HTTP response "
            "but the body did not look like OSM XML"
        )
    return filter_osm_xml_to_polygon(response.text, ring), settings.osm_map_api_endpoint


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
            try:
                async with asyncio.timeout(settings.overpass_endpoint_budget_seconds):
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
            except TimeoutError:
                errors.append(
                    f"{endpoint}: exceeded the "
                    f"{settings.overpass_endpoint_budget_seconds:g}s endpoint budget"
                )

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
            try:
                async with asyncio.timeout(settings.overpass_endpoint_budget_seconds):
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
            except TimeoutError:
                errors.append(
                    f"{endpoint}: exceeded the "
                    f"{settings.overpass_endpoint_budget_seconds:g}s endpoint budget"
                )

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
    official_error = None
    try:
        return await _fetch_official_osm_map(ring, settings)
    except (OverpassError, ET.ParseError, ValueError) as exc:
        official_error = str(exc)

    try:
        return await _fetch_query_text(build_osm_extract_query(ring), settings)
    except OverpassError as exc:
        raise OverpassError(
            "All OpenStreetMap export sources failed. The selected boundary is "
            f"still available; you can retry. Official OSM API: {official_error}; "
            f"Overpass: {exc}"
        ) from exc
