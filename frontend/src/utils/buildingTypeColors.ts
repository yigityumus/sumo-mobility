const BUILDING_TYPE_COLOR_TOKENS = [
  "--chart-1",
  "--chart-2",
  "--chart-3",
  "--chart-4",
  "--chart-5",
  "--primary",
  "--sidebar-primary",
  "--destructive",
  "--ring",
  "--foreground",
];

const FALLBACK_COLORS = [
  "oklch(0.811 0.111 293.571)",
  "oklch(0.606 0.25 292.717)",
  "oklch(0.541 0.281 293.009)",
  "oklch(0.491 0.27 292.581)",
  "oklch(0.432 0.232 292.759)",
  "oklch(0.5 0.134 242.749)",
  "oklch(0.588 0.158 241.966)",
  "oklch(0.577 0.245 27.325)",
  "oklch(0.708 0 0)",
  "oklch(0.145 0 0)",
];

export function buildingTypeColor(index: number) {
  const normalizedIndex = Math.abs(index) % BUILDING_TYPE_COLOR_TOKENS.length;
  const token = BUILDING_TYPE_COLOR_TOKENS[normalizedIndex];

  if (typeof window === "undefined") {
    return FALLBACK_COLORS[normalizedIndex];
  }

  const value = window.getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  return value || FALLBACK_COLORS[normalizedIndex];
}
