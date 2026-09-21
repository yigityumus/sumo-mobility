import L from "leaflet";

const DEFAULT_PRECISION = {
  km: 2,
  ha: 2,
  m: 0,
  mi: 2,
  ac: 2,
  yd: 0,
};

/**
 * leaflet-draw 1.0.4 contains an undeclared `type` variable in
 * L.GeometryUtil.readableArea. Vite serves dependencies as strict-mode ES
 * modules, so the undeclared variable throws a ReferenceError while the mouse
 * moves during rectangle or polygon drawing.
 *
 * Replace only that formatter at runtime instead of modifying node_modules.
 */
export function patchLeafletDrawReadableArea() {
  const geometryUtil = L.GeometryUtil as any;

  if (!geometryUtil?.formattedNumber) {
    return;
  }

  geometryUtil.readableArea = function readableArea(
    area,
    isMetric: boolean | string | string[] = true,
    precision = {},
  ) {
    const resolvedPrecision = {
      ...DEFAULT_PRECISION,
      ...precision,
    };

    if (isMetric) {
      let units = ["ha", "m"];
      if (typeof isMetric === "string") {
        units = [isMetric];
      } else if (Array.isArray(isMetric)) {
        units = isMetric;
      }

      if (area >= 1_000_000 && units.includes("km")) {
        return `${geometryUtil.formattedNumber(
          area * 0.000001,
          resolvedPrecision.km,
        )} km²`;
      }

      if (area >= 10_000 && units.includes("ha")) {
        return `${geometryUtil.formattedNumber(
          area * 0.0001,
          resolvedPrecision.ha,
        )} ha`;
      }

      return `${geometryUtil.formattedNumber(
        area,
        resolvedPrecision.m,
      )} m²`;
    }

    const squareYards = area / 0.836127;

    if (squareYards >= 3_097_600) {
      return `${geometryUtil.formattedNumber(
        squareYards / 3_097_600,
        resolvedPrecision.mi,
      )} mi²`;
    }

    if (squareYards >= 4_840) {
      return `${geometryUtil.formattedNumber(
        squareYards / 4_840,
        resolvedPrecision.ac,
      )} acres`;
    }

    return `${geometryUtil.formattedNumber(
      squareYards,
      resolvedPrecision.yd,
    )} yd²`;
  };
}
