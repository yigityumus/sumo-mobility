import type { KeyboardEvent } from "react";
import { BarChart3, MoreHorizontal } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { cn } from "../lib/utils";
import TopNavigation from "./TopNavigation";

function formatDateTime(value?: string | null) {
  if (!value) return "Unknown";
  return new Date(value).toLocaleString();
}

function handleCardKeyDown(event: KeyboardEvent, action: () => void) {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }

  event.preventDefault();
  action();
}

export default function HomePage({
  savedModels,
  loadingModel,
  busy,
  onStartNewModel,
  onOpenAnalytics,
  onDocumentation,
  onLoadSavedModel,
  onRequestDuplicateModel,
  onRequestRenameModel,
  onRequestDeleteModel,
}) {
  const visibleModels = (savedModels ?? []).slice(0, 7);
  const hiddenModelCount = Math.max((savedModels ?? []).length - visibleModels.length, 0);

  return (
    <main className="min-h-full overflow-y-auto bg-background px-[clamp(22px,5vw,72px)] py-12 text-foreground">
      <TopNavigation active="home" onHome={() => undefined} onAnalytics={onOpenAnalytics} onDocumentation={onDocumentation} className="mx-auto max-w-5xl" />
      <section className="mx-auto max-w-5xl py-20 pb-20">
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          SUMO preprocessing
        </p>
        <h1 className="mb-4 max-w-4xl text-[clamp(2.4rem,5vw,4.8rem)] font-semibold leading-[0.98] tracking-[-0.055em]">
          Area model builder
        </h1>
        <p className="max-w-2xl text-[clamp(1rem,1.7vw,1.18rem)] leading-7 text-muted-foreground">
          Prepare simulation inputs from OpenStreetMap data. Select buildings, parking areas, source OSM extracts, and later extend each model with SUMO access points and routing metadata.
        </p>
      </section>

      <section
        id="home-model-actions"
        className="mx-auto grid max-w-5xl grid-cols-1 gap-4 pb-16 sm:grid-cols-2 lg:grid-cols-3"
      >
        <Card
          role="button"
          tabIndex={busy ? -1 : 0}
          aria-disabled={busy}
          aria-label="Start a new model"
          className={cn(
            "group flex min-h-[178px] cursor-pointer items-center justify-center transition-colors hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            busy && "pointer-events-none opacity-60",
          )}
          onClick={() => {
            if (!busy) onStartNewModel();
          }}
          onKeyDown={(event) => {
            if (!busy) handleCardKeyDown(event, onStartNewModel);
          }}
        >
          <CardContent className="flex flex-col items-center justify-center p-6 text-center">
            <span className="text-5xl font-light leading-none text-muted-foreground transition-colors group-hover:text-foreground">
              +
            </span>
            <span className="mt-3 text-sm font-medium text-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
              Start a New Model
            </span>
          </CardContent>
        </Card>

        <Card
          role="button"
          tabIndex={busy ? -1 : 0}
          aria-disabled={busy}
          aria-label="Open analytics"
          className={cn(
            "group flex min-h-[178px] cursor-pointer items-center justify-center transition-colors hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            busy && "pointer-events-none opacity-60",
          )}
          onClick={() => {
            if (!busy) onOpenAnalytics();
          }}
          onKeyDown={(event) => {
            if (!busy) handleCardKeyDown(event, onOpenAnalytics);
          }}
        >
          <CardContent className="flex flex-col items-center justify-center p-6 text-center">
            <BarChart3 className="size-10 text-muted-foreground transition-colors group-hover:text-foreground" />
            <span className="mt-3 text-sm font-medium">Analytics</span>
            <span className="mt-1 text-xs text-muted-foreground">Parking and search charts</span>
          </CardContent>
        </Card>

        {visibleModels.map((model) => {
          const loadModel = () => onLoadSavedModel(model.id);

          return (
            <Card
              key={model.id}
              role="button"
              tabIndex={busy ? -1 : 0}
              aria-disabled={busy}
              aria-label={`Open model ${model.name}`}
              className={cn(
                "group relative min-h-[178px] cursor-pointer transition-colors hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                busy && "pointer-events-none opacity-60",
              )}
              onClick={() => {
                if (!busy) loadModel();
              }}
              onKeyDown={(event) => {
                if (!busy) handleCardKeyDown(event, loadModel);
              }}
            >
              <CardHeader className="p-5 pb-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="truncate text-base">{model.name}</CardTitle>
                    <CardDescription className="mt-1 text-xs">
                      {model.selectedBuildingCount}/{model.buildingCount} buildings · {" "}
                      {model.selectedParkingCount}/{model.parkingCount} parking
                    </CardDescription>
                  </div>

                  <div
                    onClick={(event) => event.stopPropagation()}
                    onKeyDown={(event) => event.stopPropagation()}
                  >
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={`Open actions for ${model.name}`}
                          disabled={busy}
                          className="-mr-2 -mt-2"
                        >
                          <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => onRequestDuplicateModel(model)}>
                          Duplicate
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => onRequestRenameModel(model)}>
                          Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onSelect={() => onRequestDeleteModel(model)}
                        >
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-1 p-5 pt-1 text-xs leading-5 text-muted-foreground">
                <p>Created at: {formatDateTime(model.createdAt)}</p>
                <p>Last modified at: {formatDateTime(model.updatedAt)}</p>
              </CardContent>
            </Card>
          );
        })}
      </section>

      <section className="mx-auto max-w-5xl pb-12">
        {loadingModel && <p className="text-xs text-muted-foreground">Loading saved area model…</p>}
        {hiddenModelCount > 0 && (
          <p className="text-xs text-muted-foreground">
            Showing the first 7 saved models to keep the home grid within 3 × 3.
          </p>
        )}
      </section>
    </main>
  );
}
