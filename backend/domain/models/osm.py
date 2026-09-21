"""OSM XML parsing for campus models."""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from typing import Any, Iterable


class OsmXmlError(ValueError):
    pass


def maybe_decompress_osm_bytes(content: bytes) -> bytes:
    """Return raw XML bytes from either plain XML or gzip-compressed XML."""
    if content.startswith(b"\x1f\x8b"):
        try:
            return gzip.decompress(content)
        except OSError as exc:
            raise OsmXmlError("The uploaded file looks like gzip but could not be decompressed.") from exc
    return content


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _tags(element: ET.Element) -> dict[str, str]:
    tags: dict[str, str] = {}
    for child in element:
        if _strip_namespace(child.tag) != "tag":
            continue
        key = child.get("k")
        value = child.get("v")
        if key is not None and value is not None:
            tags[key] = value
    return tags


def _int_attr(element: ET.Element, name: str) -> int:
    value = element.get(name)
    if value is None:
        raise OsmXmlError(f"OSM element is missing required attribute {name!r}.")
    try:
        return int(value)
    except ValueError as exc:
        raise OsmXmlError(f"OSM element has invalid integer attribute {name!r}: {value!r}.") from exc


def _float_attr(element: ET.Element, name: str) -> float:
    value = element.get(name)
    if value is None:
        raise OsmXmlError(f"OSM node is missing required attribute {name!r}.")
    try:
        return float(value)
    except ValueError as exc:
        raise OsmXmlError(f"OSM node has invalid numeric attribute {name!r}: {value!r}.") from exc


def _is_target_tags(tags: dict[str, str]) -> bool:
    return bool(tags.get("building")) or tags.get("amenity") == "parking"


def _collection_for_tags(tags: dict[str, str]) -> str | None:
    # Parking garages/areas may also carry building=*. Treat them as parking so
    # the same geometry is not returned twice.
    if tags.get("amenity") == "parking":
        return "parking_areas"
    if tags.get("building"):
        return "buildings"
    return None


def _feature(osm_type: str, osm_id: int, tags: dict[str, str], geometry: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": f"{osm_type}/{osm_id}",
        "properties": {
            "type": osm_type,
            "id": osm_id,
            "tags": tags,
        },
        "geometry": geometry,
    }


def _closed_ring_from_refs(
    refs: list[int],
    nodes: dict[int, tuple[float, float]],
) -> list[list[float]] | None:
    if len(refs) < 3:
        return None

    coordinates: list[list[float]] = []
    for ref in refs:
        point = nodes.get(ref)
        if point is None:
            return None
        lon, lat = point
        coordinates.append([lon, lat])

    if coordinates[0] != coordinates[-1]:
        coordinates.append(coordinates[0])

    if len(coordinates) < 4:
        return None

    return coordinates


def _way_polygon_geometry(
    refs: list[int],
    nodes: dict[int, tuple[float, float]],
) -> dict[str, Any] | None:
    ring = _closed_ring_from_refs(refs, nodes)
    if ring is None:
        return None
    return {"type": "Polygon", "coordinates": [ring]}


def _assemble_node_rings(lines: Iterable[list[int]]) -> list[list[int]]:
    """Assemble relation member way node-ref sequences into closed rings.

    This intentionally stays simple. It handles the common OSM multipolygon case
    where member ways join end-to-end. Complex malformed relations are skipped
    rather than slowing down upload parsing.
    """
    remaining = [line[:] for line in lines if len(line) >= 2]
    rings: list[list[int]] = []

    while remaining:
        ring = remaining.pop(0)
        changed = True

        while changed and ring[0] != ring[-1]:
            changed = False
            for index, candidate in enumerate(remaining):
                if ring[-1] == candidate[0]:
                    ring.extend(candidate[1:])
                elif ring[-1] == candidate[-1]:
                    ring.extend(reversed(candidate[:-1]))
                elif ring[0] == candidate[-1]:
                    ring = candidate[:-1] + ring
                elif ring[0] == candidate[0]:
                    ring = list(reversed(candidate[1:])) + ring
                else:
                    continue

                remaining.pop(index)
                changed = True
                break

        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)

    return rings


def _point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    """Return whether [lon, lat] is inside a ring using ray casting."""
    x, y = point
    inside = False
    j = len(ring) - 1

    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-20) + xi
        )
        if intersects:
            inside = not inside
        j = i

    return inside


def _relation_geometry(
    relation: ET.Element,
    ways: dict[int, dict[str, Any]],
    nodes: dict[int, tuple[float, float]],
) -> dict[str, Any] | None:
    outer_lines: list[list[int]] = []
    inner_lines: list[list[int]] = []

    for child in relation:
        if _strip_namespace(child.tag) != "member":
            continue
        if child.get("type") != "way":
            continue

        ref = child.get("ref")
        if ref is None:
            continue

        try:
            way_id = int(ref)
        except ValueError:
            continue

        way = ways.get(way_id)
        if way is None:
            continue

        role = child.get("role", "")
        refs = way["refs"]
        if role == "inner":
            inner_lines.append(refs)
        else:
            outer_lines.append(refs)

    outer_ref_rings = _assemble_node_rings(outer_lines)
    inner_ref_rings = _assemble_node_rings(inner_lines)

    outer_rings = [
        ring for ring in (_closed_ring_from_refs(refs, nodes) for refs in outer_ref_rings)
        if ring is not None
    ]
    inner_rings = [
        ring for ring in (_closed_ring_from_refs(refs, nodes) for refs in inner_ref_rings)
        if ring is not None
    ]

    if not outer_rings:
        return None

    polygons: list[list[list[list[float]]]] = []
    for outer in outer_rings:
        polygon = [outer]
        for inner in inner_rings:
            if inner and _point_in_ring(inner[0], outer):
                polygon.append(inner)
        polygons.append(polygon)

    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}

    return {"type": "MultiPolygon", "coordinates": polygons}


def _parse_root(content: bytes) -> ET.Element:
    xml_bytes = maybe_decompress_osm_bytes(content)

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise OsmXmlError("The uploaded file is not valid OSM XML.") from exc

    if _strip_namespace(root.tag) != "osm":
        raise OsmXmlError("The uploaded XML file does not have an <osm> root element.")

    return root



def _bounds_feature(root: ET.Element) -> dict[str, Any] | None:
    """Return a GeoJSON polygon from the first <bounds> element, when present."""
    for child in root:
        if _strip_namespace(child.tag) != "bounds":
            continue
        try:
            min_lat = _float_attr(child, "minlat")
            min_lon = _float_attr(child, "minlon")
            max_lat = _float_attr(child, "maxlat")
            max_lon = _float_attr(child, "maxlon")
        except OsmXmlError:
            return None

        if min_lat >= max_lat or min_lon >= max_lon:
            return None

        ring = [
            [min_lon, min_lat],
            [max_lon, min_lat],
            [max_lon, max_lat],
            [min_lon, max_lat],
            [min_lon, min_lat],
        ]
        return {
            "type": "Feature",
            "properties": {
                "source": "osm_bounds",
                "minlat": min_lat,
                "minlon": min_lon,
                "maxlat": max_lat,
                "maxlon": max_lon,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [ring],
            },
        }

    return None


def parse_osm_xml_to_area_feature_collections(content: bytes) -> dict[str, Any]:
    """Extract only building and parking polygons from uploaded OSM XML.

    This is the fast upload path. It avoids returning every OSM node/way to the
    browser and avoids running a large OSM-to-GeoJSON conversion in the frontend.
    """
    root = _parse_root(content)

    nodes: dict[int, tuple[float, float]] = {}
    ways: dict[int, dict[str, Any]] = {}
    relations: list[ET.Element] = []
    total_nodes = 0
    total_ways = 0
    total_relations = 0

    for child in root:
        tag = _strip_namespace(child.tag)
        if tag == "node":
            total_nodes += 1
            node_id = _int_attr(child, "id")
            nodes[node_id] = (_float_attr(child, "lon"), _float_attr(child, "lat"))
        elif tag == "way":
            total_ways += 1
            way_id = _int_attr(child, "id")
            refs: list[int] = []
            for grandchild in child:
                if _strip_namespace(grandchild.tag) != "nd":
                    continue
                ref = grandchild.get("ref")
                if ref is None:
                    continue
                try:
                    refs.append(int(ref))
                except ValueError:
                    continue
            ways[way_id] = {"refs": refs, "tags": _tags(child)}
        elif tag == "relation":
            total_relations += 1
            relations.append(child)

    buildings: list[dict[str, Any]] = []
    parking_areas: list[dict[str, Any]] = []
    seen_feature_ids: set[str] = set()

    for way_id, way in ways.items():
        tags = way["tags"]
        collection_name = _collection_for_tags(tags)
        if collection_name is None:
            continue

        geometry = _way_polygon_geometry(way["refs"], nodes)
        if geometry is None:
            continue

        feature_id = f"way/{way_id}"
        if feature_id in seen_feature_ids:
            continue
        seen_feature_ids.add(feature_id)

        if collection_name == "parking_areas":
            parking_areas.append(_feature("way", way_id, tags, geometry))
        else:
            buildings.append(_feature("way", way_id, tags, geometry))

    for relation in relations:
        relation_id = _int_attr(relation, "id")
        tags = _tags(relation)
        collection_name = _collection_for_tags(tags)
        if collection_name is None:
            continue

        geometry = _relation_geometry(relation, ways, nodes)
        if geometry is None:
            continue

        feature_id = f"relation/{relation_id}"
        if feature_id in seen_feature_ids:
            continue
        seen_feature_ids.add(feature_id)

        if collection_name == "parking_areas":
            parking_areas.append(_feature("relation", relation_id, tags, geometry))
        else:
            buildings.append(_feature("relation", relation_id, tags, geometry))

    return {
        "buildings": {
            "type": "FeatureCollection",
            "features": buildings,
        },
        "parking_areas": {
            "type": "FeatureCollection",
            "features": parking_areas,
        },
        "boundary": _bounds_feature(root),
        "stats": {
            "input_nodes": total_nodes,
            "input_ways": total_ways,
            "input_relations": total_relations,
            "building_features": len(buildings),
            "parking_area_features": len(parking_areas),
        },
    }


# Backward-compatible helper kept for older frontend code paths and tests.
def parse_osm_xml_to_overpass_json(content: bytes) -> dict[str, Any]:
    """
    Convert an OSM XML extract into an Overpass-like JSON payload.

    Prefer parse_osm_xml_to_area_feature_collections for interactive uploads.
    This function keeps older code paths available.
    """
    root = _parse_root(content)

    nodes: dict[int, dict[str, Any]] = {}
    way_elements: list[ET.Element] = []
    relation_elements: list[ET.Element] = []

    for child in root:
        tag = _strip_namespace(child.tag)
        if tag == "node":
            node_id = _int_attr(child, "id")
            nodes[node_id] = {
                "type": "node",
                "id": node_id,
                "lat": _float_attr(child, "lat"),
                "lon": _float_attr(child, "lon"),
                "tags": _tags(child),
            }
        elif tag == "way":
            way_elements.append(child)
        elif tag == "relation":
            relation_elements.append(child)

    elements: list[dict[str, Any]] = []
    elements.extend(nodes.values())

    for way in way_elements:
        way_id = _int_attr(way, "id")
        node_refs: list[int] = []
        geometry: list[dict[str, float]] = []

        for child in way:
            if _strip_namespace(child.tag) != "nd":
                continue
            ref = child.get("ref")
            if ref is None:
                continue
            try:
                node_id = int(ref)
            except ValueError:
                continue
            node_refs.append(node_id)
            node = nodes.get(node_id)
            if node is not None:
                geometry.append({"lat": node["lat"], "lon": node["lon"]})

        element: dict[str, Any] = {
            "type": "way",
            "id": way_id,
            "nodes": node_refs,
            "tags": _tags(way),
        }

        if geometry:
            element["geometry"] = geometry

        elements.append(element)

    for relation in relation_elements:
        relation_id = _int_attr(relation, "id")
        members: list[dict[str, Any]] = []

        for child in relation:
            if _strip_namespace(child.tag) != "member":
                continue

            member_type = child.get("type")
            ref = child.get("ref")
            role = child.get("role", "")

            if member_type is None or ref is None:
                continue

            try:
                member_ref = int(ref)
            except ValueError:
                continue

            members.append({
                "type": member_type,
                "ref": member_ref,
                "role": role,
            })

        elements.append({
            "type": "relation",
            "id": relation_id,
            "members": members,
            "tags": _tags(relation),
        })

    return {
        "version": 0.6,
        "generator": "sumo-area-builder-upload-parser",
        "osm3s": {
            "timestamp_osm_base": None,
            "copyright": "Data from uploaded OSM XML file.",
        },
        "elements": elements,
    }
