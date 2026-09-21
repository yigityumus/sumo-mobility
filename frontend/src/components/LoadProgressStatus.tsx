import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, LoaderCircle } from "lucide-react";
import { Button } from "./ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./ui/collapsible";
import { Progress } from "./ui/progress";
import type { LoadProgressState, LoadProgressStep } from "../types/campus";

function formatDuration(milliseconds: number) {
  const safeMilliseconds = Number.isFinite(milliseconds) && milliseconds > 0 ? milliseconds : 0;
  const totalSeconds = Math.floor(safeMilliseconds / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function stepDuration(step: LoadProgressStep, now: number) {
  if (!step.startedAt) {
    return "--:--";
  }
  return formatDuration((step.completedAt ?? now) - step.startedAt);
}

function currentStep(progress: LoadProgressState) {
  return (
    progress.steps.find((step) => step.status === "active") ??
    [...progress.steps].reverse().find((step) => step.status === "complete") ??
    progress.steps[0] ??
    null
  );
}

type LoadProgressStatusProps = {
  progress: LoadProgressState;
};

export default function LoadProgressStatus({ progress }: LoadProgressStatusProps) {
  const [expanded, setExpanded] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (progress.status !== "running") {
      setNow(Date.now());
      return undefined;
    }

    const intervalId = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(intervalId);
  }, [progress.status]);

  useEffect(() => {
    if (progress.status === "running") {
      setExpanded(true);
    }
  }, [progress.status]);

  const activeOrLastStep = currentStep(progress);
  const hasSteps = progress.steps.length > 0;
  const isRunning = progress.status === "running";
  const isComplete = progress.status === "complete";
  const isError = progress.status === "error";
  const completedSteps = progress.steps.filter((step) => step.status === "complete").length;
  const percent = progress.steps.length ? (completedSteps / progress.steps.length) * 100 : 0;

  const collapsedLabel = useMemo(() => {
    if (isComplete) return "OSM data is ready";
    if (isError) return "Load failed — view details";
    if (activeOrLastStep) return activeOrLastStep.label;
    return "Waiting to start.";
  }, [activeOrLastStep, isComplete, isError]);

  const collapsedTime =
    (isComplete || isError) && progress.startedAt
      ? formatDuration((progress.completedAt ?? now) - progress.startedAt)
      : activeOrLastStep
        ? stepDuration(activeOrLastStep, now)
        : "00:00";

  return (
    <Collapsible open={expanded} onOpenChange={setExpanded} className="mt-3 overflow-hidden rounded-lg border bg-muted/20 text-xs text-muted-foreground">
      {isRunning && (
        <div className="border-b border-blue-200 bg-blue-50 p-3 text-blue-800 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-200" role="status" aria-live="polite">
          <div className="flex items-start gap-2.5">
            <LoaderCircle className="mt-0.5 size-4 shrink-0 animate-spin" />
            <div>
              <strong className="text-sm">The app is still working</strong>
              <p className="mt-1 leading-5">
                Downloading and processing OSM data can take a few minutes. Keep this page open while the elapsed timer continues.
              </p>
            </div>
          </div>
        </div>
      )}
      <CollapsibleTrigger asChild>
      <Button
        type="button"
        variant="ghost"
        className="h-auto w-full justify-start gap-2 rounded-lg px-3 py-2 text-left text-xs font-normal text-muted-foreground hover:bg-muted/30"
        disabled={!hasSteps}
      >
        <span className="flex h-4 w-4 items-center justify-center text-muted-foreground">
          {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </span>
        <span className="relative flex h-2.5 w-2.5 shrink-0 items-center justify-center">
          {isRunning && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/35" />}
          <span
            className={`h-2 w-2 rounded-full ${
              isError
                ? "bg-destructive"
                : isComplete
                  ? "bg-primary"
                  : isRunning
                    ? "bg-primary"
                    : "bg-muted-foreground/30"
            }`}
          />
        </span>
        <span className="min-w-0 flex-1 truncate">{collapsedLabel}</span>
        <span className="font-mono tabular-nums text-muted-foreground/80">{collapsedTime}</span>
      </Button>
      </CollapsibleTrigger>

      {hasSteps && <Progress value={percent} className="h-1 rounded-none" />}

      <CollapsibleContent>
        <div className="border-t px-3 py-2">
          {hasSteps ? (
            <div className="space-y-1.5">
              {progress.steps.map((step) => (
                <div key={step.id} className="grid grid-cols-[1fr_auto] items-start gap-3">
                  <div className="flex min-w-0 items-start gap-2">
                    <span
                      className={`mt-[0.35rem] h-1.5 w-1.5 shrink-0 rounded-full ${
                        step.status === "error"
                          ? "bg-destructive"
                          : step.status === "complete"
                            ? "bg-primary"
                            : step.status === "active"
                              ? "bg-primary animate-pulse"
                              : "bg-muted-foreground/30"
                      }`}
                    />
                    <span className="min-w-0 text-left leading-5">{step.label}</span>
                  </div>
                  <span className="font-mono tabular-nums text-muted-foreground/80">
                    {stepDuration(step, now)}
                  </span>
                </div>
              ))}
              {progress.errorMessage && (
                <p className="pt-1 text-left leading-5 text-destructive">{progress.errorMessage}</p>
              )}
            </div>
          ) : (
            <p className="leading-5">
              No progress recorded yet.
            </p>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
