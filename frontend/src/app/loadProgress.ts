import { useCallback, useState } from "react";
import type { LoadProgressState } from "../types/campus";

export const EMPTY_LOAD_PROGRESS: LoadProgressState = {
  status: "idle",
  steps: [],
  startedAt: null,
  completedAt: null,
  errorMessage: null,
};

const FEATURE_LOAD_STEPS = [
  { id: "prepare-boundary", label: "Preparing selected area" },
  { id: "request-backend", label: "Sending request to FastAPI" },
  { id: "fetch-overpass", label: "Fetching OSM data from Overpass" },
  { id: "receive-osm", label: "OSM response received" },
  { id: "extract-buildings", label: "Extracting building polygons" },
  { id: "extract-parking", label: "Extracting parking-area polygons" },
  { id: "prepare-ui", label: "Preparing selection lists" },
];

export function waitForNextFrame() {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => window.requestAnimationFrame(resolve));
  });
}

export function useLoadProgress() {
  const [loadProgress, setLoadProgress] = useState<LoadProgressState>(EMPTY_LOAD_PROGRESS);

  const resetLoadProgress = useCallback(() => {
    setLoadProgress(EMPTY_LOAD_PROGRESS);
  }, []);

  const startLoadProgress = useCallback(() => {
    const timestamp = Date.now();
    setLoadProgress({
      status: "running",
      startedAt: timestamp,
      completedAt: null,
      errorMessage: null,
      steps: FEATURE_LOAD_STEPS.map((step, index) => ({
        ...step,
        status: index === 0 ? "active" : "pending",
        startedAt: index === 0 ? timestamp : null,
        completedAt: null,
      })),
    });
  }, []);

  const activateLoadProgressStep = useCallback((stepId: string) => {
    const timestamp = Date.now();
    setLoadProgress((current) => ({
      ...current,
      status: "running",
      steps: current.steps.map((step) => {
        if (step.status === "active" && step.id !== stepId) {
          return { ...step, status: "complete", completedAt: step.completedAt ?? timestamp };
        }
        if (step.id === stepId) {
          return { ...step, status: "active", startedAt: step.startedAt ?? timestamp, completedAt: null };
        }
        return step;
      }),
    }));
  }, []);

  const completeLoadProgress = useCallback(() => {
    const timestamp = Date.now();
    setLoadProgress((current) => ({
      ...current,
      status: "complete",
      completedAt: timestamp,
      errorMessage: null,
      steps: current.steps.map((step) =>
        step.status === "pending"
          ? step
          : { ...step, status: "complete", completedAt: step.completedAt ?? timestamp },
      ),
    }));
  }, []);

  const failLoadProgress = useCallback((message: string) => {
    const timestamp = Date.now();
    setLoadProgress((current) => ({
      ...current,
      status: "error",
      completedAt: timestamp,
      errorMessage: message,
      steps: current.steps.map((step) => {
        if (step.status === "active") {
          return { ...step, status: "error", completedAt: step.completedAt ?? timestamp };
        }
        return step;
      }),
    }));
  }, []);

  return {
    loadProgress,
    resetLoadProgress,
    startLoadProgress,
    activateLoadProgressStep,
    completeLoadProgress,
    failLoadProgress,
  };
}
