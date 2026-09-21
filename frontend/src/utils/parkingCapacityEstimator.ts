import { getFeatureId } from "./osmFeatures.ts";
import { CALCULATED_CAPACITY_SOURCE } from "./parkingSpecs.ts";

const SLOT_WIDTH_METRES = 2.3;
const MIN_INTERNAL_WAY_INSIDE_RATIO = 0.5;
const MIN_SPATIAL_WAY_INSIDE_RATIO = 0.5;
const MIN_SPATIAL_PARKING_AISLE_LENGTH_METRES = 3;

function parseTags(element) {
  const tags = {};
  for (const tag of element.querySelectorAll(":scope > tag")) {
    const key = tag.getAttribute("k");
    if (key) {
      tags[key] = tag.getAttribute("v") ?? "";
    }
  }
  return tags;
}

function parseOsmWayId(feature) {
  const featureId = getFeatureId(feature);
  const [type, id] = featureId.split("/");
  if (type !== "way" || !id) {
    return null;
  }
  return id;
}

async function readBlobAsText(blob, filename = "") {
  const isProbablyGzip = String(filename).toLocaleLowerCase().endsWith(".gz");

  if (isProbablyGzip && "DecompressionStream" in window) {
    try {
      const decompressedStream = blob.stream().pipeThrough(new DecompressionStream("gzip"));
      return await new Response(decompressedStream).text();
    } catch (_error) {
      // Some existing files can have a .gz suffix while containing plain XML.
      // Fall through to normal text reading.
    }
  }

  return blob.text();
}

function parseOsmXml(xmlText) {
  const parser = new DOMParser();
  const document = parser.parseFromString(xmlText, "application/xml");
  const parseError = document.querySelector("parsererror");

  if (parseError) {
    throw new Error("The source OSM file could not be parsed as XML.");
  }

  const nodes = new Map();
  const ways = new Map();
  const nodeToWayIds = new Map();

  for (const node of document.querySelectorAll("node")) {
    const id = node.getAttribute("id");
    const lat = Number(node.getAttribute("lat"));
    const lon = Number(node.getAttribute("lon"));

    if (id && Number.isFinite(lat) && Number.isFinite(lon)) {
      nodes.set(id, { id, lat, lon });
    }
  }

  for (const way of document.querySelectorAll("way")) {
    const id = way.getAttribute("id");
    if (!id) {
      continue;
    }

    const nodeRefs = [...way.querySelectorAll(":scope > nd")]
      .map((nd) => nd.getAttribute("ref"))
      .filter(Boolean);

    ways.set(id, {
      id,
      nodeRefs,
      tags: parseTags(way),
    });

    for (const nodeRef of nodeRefs) {
      if (!nodeToWayIds.has(nodeRef)) {
        nodeToWayIds.set(nodeRef, new Set());
      }
      nodeToWayIds.get(nodeRef).add(id);
    }
  }

  return { nodes, ways, nodeToWayIds };
}

function isVehicleServiceWay(way) {
  if (!way || way.tags.highway !== "service") {
    return false;
  }

  const access = way.tags.access ?? way.tags.vehicle ?? way.tags.motor_vehicle;
  if (["no", "private"].includes(String(access ?? "").toLocaleLowerCase())) {
    // Private roads can still be relevant inside parking areas, but
    // do not exclude them here; only strict no-access roads are excluded.
    return access !== "no";
  }

  return true;
}

function createProjection(points) {
  const averageLatitude =
    points.reduce((sum, point) => sum + point.lat, 0) / Math.max(points.length, 1);
  const cosLatitude = Math.cos((averageLatitude * Math.PI) / 180);

  return (point) => ({
    x: point.lon * 111_320 * cosLatitude,
    y: point.lat * 110_540,
  });
}

function pointInPolygon(point, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].x;
    const yi = polygon[i].y;
    const xj = polygon[j].x;
    const yj = polygon[j].y;

    const intersects =
      yi > point.y !== yj > point.y &&
      point.x < ((xj - xi) * (point.y - yi)) / (yj - yi || Number.EPSILON) + xi;

    if (intersects) {
      inside = !inside;
    }
  }
  return inside;
}

function distanceMetres(left, right) {
  const dx = left.x - right.x;
  const dy = left.y - right.y;
  return Math.sqrt(dx * dx + dy * dy);
}

function wayGeometry(way, nodes, project) {
  return way.nodeRefs
    .map((nodeRef) => nodes.get(nodeRef))
    .filter(Boolean)
    .map((node) => ({
      id: node.id,
      projected: project(node),
    }));
}

function wayLengthStats(way, nodes, project, polygon) {
  const geometry = wayGeometry(way, nodes, project);
  let totalLength = 0;
  let insideLength = 0;

  for (let index = 0; index < geometry.length - 1; index += 1) {
    const start = geometry[index].projected;
    const end = geometry[index + 1].projected;
    const length = distanceMetres(start, end);
    const midpoint = {
      x: (start.x + end.x) / 2,
      y: (start.y + end.y) / 2,
    };

    totalLength += length;
    if (pointInPolygon(midpoint, polygon)) {
      insideLength += length;
    }
  }

  return {
    totalLength,
    insideLength,
    insideRatio: totalLength > 0 ? insideLength / totalLength : 0,
  };
}

function parkingPolygonFromWay(parkingWay, nodes) {
  const polygonNodes = parkingWay.nodeRefs.map((nodeRef) => nodes.get(nodeRef)).filter(Boolean);

  if (polygonNodes.length < 4) {
    throw new Error(`Parking way ${parkingWay.id} does not have enough nodes for a polygon.`);
  }

  return polygonNodes;
}

function shouldAcceptSpatialInternalWay(way, stats) {
  if (!isVehicleServiceWay(way)) {
    return false;
  }

  if (stats.insideRatio >= MIN_SPATIAL_WAY_INSIDE_RATIO) {
    return true;
  }

  // Some parking aisles are split strangely or lie on the edge of a mapped
  // parking polygon. If OSM explicitly marks the way as a parking aisle, keep
  // it when a useful amount of its length is inside the parking polygon.
  return (
    way.tags.service === "parking_aisle" &&
    stats.insideLength >= MIN_SPATIAL_PARKING_AISLE_LENGTH_METRES
  );
}

function findRelatedParkingWays(parkingWay, data) {
  const { nodes, ways, nodeToWayIds } = data;
  const polygonNodes = parkingPolygonFromWay(parkingWay, nodes);
  const project = createProjection(polygonNodes);
  const polygon = polygonNodes.map(project);
  const parkingNodeRefs = new Set(parkingWay.nodeRefs);

  const statsCache = new Map();
  function statsForWay(way) {
    if (!statsCache.has(way.id)) {
      statsCache.set(way.id, wayLengthStats(way, nodes, project, polygon));
    }
    return statsCache.get(way.id);
  }

  const gateWayIds = new Set();
  const gateWayDetailsById = new Map();

  // Strategy 1: strict topological gates. These are ways that reuse one of the
  // parking polygon boundary nodes, like C6 -> 155507726 and 39980931.
  for (const nodeRef of parkingNodeRefs) {
    const parentWays = nodeToWayIds.get(nodeRef) ?? new Set();

    for (const wayId of parentWays) {
      if (wayId === parkingWay.id) {
        continue;
      }

      const way = ways.get(wayId);
      if (!isVehicleServiceWay(way)) {
        continue;
      }

      const stats = statsForWay(way);
      gateWayIds.add(wayId);

      const current = gateWayDetailsById.get(wayId) ?? {
        wayId,
        sharedNodeIds: [],
        service: way.tags.service ?? null,
        insideRatio: stats.insideRatio,
        insideLength: stats.insideLength,
      };
      current.sharedNodeIds.push(nodeRef);
      gateWayDetailsById.set(wayId, current);
    }
  }

  const acceptedWayIds = new Set(gateWayIds);
  const internalWayIds = new Set();
  const internalWayDetails = [];
  const queue = [...gateWayIds];

  // Strategy 2: graph expansion from topological gate ways.
  while (queue.length) {
    const currentWayId = queue.shift();
    const currentWay = ways.get(currentWayId);
    if (!currentWay) {
      continue;
    }

    for (const nodeRef of currentWay.nodeRefs) {
      const parentWays = nodeToWayIds.get(nodeRef) ?? new Set();

      for (const candidateWayId of parentWays) {
        if (acceptedWayIds.has(candidateWayId) || candidateWayId === parkingWay.id) {
          continue;
        }

        const candidateWay = ways.get(candidateWayId);
        if (!isVehicleServiceWay(candidateWay)) {
          continue;
        }

        const stats = statsForWay(candidateWay);
        if (stats.insideRatio < MIN_INTERNAL_WAY_INSIDE_RATIO) {
          continue;
        }

        acceptedWayIds.add(candidateWayId);
        internalWayIds.add(candidateWayId);
        queue.push(candidateWayId);
        internalWayDetails.push({
          wayId: candidateWayId,
          connectedFrom: currentWayId,
          service: candidateWay.tags.service ?? null,
          insideRatio: stats.insideRatio,
          insideLength: stats.insideLength,
        });
      }
    }
  }

  const spatialOnlyWayIds = new Set();
  const spatialOnlyWayDetails = [];

  // Strategy 3: spatial fallback. Many OSM parking polygons contain service
  // roads that are visually inside the parking lot but do not share a boundary
  // node with the parking polygon. Connectivity-only detection misses those.
  for (const [candidateWayId, candidateWay] of ways) {
    if (candidateWayId === parkingWay.id || acceptedWayIds.has(candidateWayId)) {
      continue;
    }

    const stats = statsForWay(candidateWay);
    if (!shouldAcceptSpatialInternalWay(candidateWay, stats)) {
      continue;
    }

    acceptedWayIds.add(candidateWayId);
    spatialOnlyWayIds.add(candidateWayId);
    spatialOnlyWayDetails.push({
      wayId: candidateWayId,
      service: candidateWay.tags.service ?? null,
      insideRatio: stats.insideRatio,
      insideLength: stats.insideLength,
    });
  }

  const relatedWayIds = [...acceptedWayIds].sort((left, right) => Number(left) - Number(right));
  const relatedWayLengths = [];
  let totalInsideLength = 0;

  for (const wayId of relatedWayIds) {
    const way = ways.get(wayId);
    if (!way) {
      continue;
    }

    const stats = statsForWay(way);
    totalInsideLength += stats.insideLength;
    relatedWayLengths.push({
      way_id: wayId,
      inside_length_m: Number(stats.insideLength.toFixed(2)),
      total_length_m: Number(stats.totalLength.toFixed(2)),
      inside_ratio: Number(stats.insideRatio.toFixed(3)),
      service: way.tags.service ?? null,
      detection: gateWayIds.has(wayId)
        ? "boundary_shared_node_gate"
        : internalWayIds.has(wayId)
          ? "connected_internal_way"
          : spatialOnlyWayIds.has(wayId)
            ? "spatial_inside_fallback"
            : "related",
    });
  }

  return {
    gateWayIds: [...gateWayIds].sort((left, right) => Number(left) - Number(right)),
    gateWayDetails: [...gateWayDetailsById.values()].sort(
      (left, right) => Number(left.wayId) - Number(right.wayId),
    ),
    internalWayIds: [...internalWayIds].sort((left, right) => Number(left) - Number(right)),
    internalWayDetails,
    spatialOnlyWayIds: [...spatialOnlyWayIds].sort((left, right) => Number(left) - Number(right)),
    spatialOnlyWayDetails,
    relatedWayIds,
    relatedWayLengths,
    totalInsideLength,
  };
}

export async function parseOsmCapacitySource(blob, filename) {
  if (!blob) {
    throw new Error("No source OSM file is available for capacity estimation.");
  }

  const text = await readBlobAsText(blob, filename);
  return parseOsmXml(text);
}

type ParkingCapacityResult = {
  capacity: number | null;
  error?: string;
  capacitySource?: string;
  method?: Record<string, unknown>;
  relatedWayIds: unknown[];
  [key: string]: unknown;
};

export function estimateParkingCapacityFromOsmData(feature, osmData): ParkingCapacityResult {
  const osmWayId = parseOsmWayId(feature);
  if (!osmWayId) {
    return {
      capacity: null,
      error: "Only OSM way-based parking polygons can be estimated automatically.",
      relatedWayIds: [],
    };
  }

  const parkingWay = osmData.ways.get(osmWayId);
  if (!parkingWay) {
    return {
      capacity: null,
      error: `Parking way ${osmWayId} was not found in the source OSM file.`,
      relatedWayIds: [],
    };
  }

  const related = findRelatedParkingWays(parkingWay, osmData);
  const capacity = Math.floor(related.totalInsideLength / SLOT_WIDTH_METRES);

  if (!Number.isInteger(capacity) || capacity <= 0) {
    return {
      capacity: null,
      error: "No related internal service-way length was found for this parking area.",
      ...related,
    };
  }

  return {
    capacity,
    capacitySource: CALCULATED_CAPACITY_SOURCE,
    method: {
      name: "related_service_way_length_2_3m",
      slot_width_m: SLOT_WIDTH_METRES,
      total_inside_length_m: Number(related.totalInsideLength.toFixed(2)),
      formula: "floor(total_inside_related_service_way_length_m / 2.3)",
    },
    ...related,
  };
}
