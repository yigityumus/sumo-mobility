export function isHomeRoute(pathname: string) {
  return pathname === "/" || pathname === "/home";
}

export function simulationModelIdFromRoute(pathname: string) {
  const match = String(pathname ?? "").match(/^\/model-([^/]+)\/simulation\/?$/);
  return match ? decodeURIComponent(match[1]) : null;
}

export function isSimulationRoute(pathname: string) {
  return pathname === "/simulation" || simulationModelIdFromRoute(pathname) !== null;
}

export function isAnalyticsRoute(pathname: string) {
  return pathname === "/analytics" || pathname === "/analytics/";
}

export function isDocumentationRoute(pathname: string) {
  return pathname === "/documentation" || pathname === "/documentation/";
}

export function modelIdFromRoute(pathname: string) {
  const match = String(pathname ?? "").match(/^\/model-([^/]+)\/?$/);
  return match ? decodeURIComponent(match[1]) : null;
}

export function routeForModel(modelId: string) {
  return `/model-${encodeURIComponent(modelId)}`;
}

export function routeForSimulation(modelId: string) {
  return `${routeForModel(modelId)}/simulation`;
}
