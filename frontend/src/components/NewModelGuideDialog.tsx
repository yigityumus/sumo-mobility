import { useEffect, useState } from "react";
import {
  CheckCircle2,
  BusFront,
  Clock3,
  MapPinned,
  MousePointerClick,
} from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { cn } from "../lib/utils";

const GUIDE_STEPS = [
  {
    title: "Choose how to provide the area",
    shortTitle: "Choose a source",
    icon: MapPinned,
    description: "Start with either a map selection or an OSM file. You only need one of them.",
    details: [
      "Draw on the map when you want the app to fetch the latest data for a small area.",
      "When you already have a .osm, .osm.xml, or compressed OSM extract, drag it onto the upload box or choose it from your computer.",
    ],
    note: "For a first model, drawing a rectangle on the map is usually the simplest path.",
  },
  {
    title: "Draw the boundary on the map",
    shortTitle: "Select the area",
    icon: MousePointerClick,
    description: "The drawing tools are in the map's upper-left corner.",
    details: [
      "Rectangle: choose the square tool, then hold and drag diagonally across the area.",
      "Polygon: click each corner, then click the first point again to finish.",
      "When the purple boundary appears, click “Load buildings and parking areas” in the sidebar.",
    ],
    note: "Keep the boundary focused. Very large areas take longer and may be rejected by public OSM services.",
  },
  {
    title: "Wait while OpenStreetMap is processed",
    shortTitle: "Let it load",
    icon: Clock3,
    description: "The app sends the boundary to the server, downloads OSM data, and extracts usable shapes.",
    details: [
      "This can take a few minutes, especially for a detailed area or when the OSM service is busy.",
      "A live status card and elapsed timer remain visible while the request is running.",
      "Keep the page open. You can continue when buildings appear in blue and parking areas in red.",
    ],
    note: "A changing elapsed timer and pulsing loader mean the app is still working, even if the current step takes a while.",
  },
  {
    title: "Keep only the features your model needs",
    shortTitle: "Refine features",
    icon: CheckCircle2,
    description: "Loaded features start selected. Click a map shape or its checkbox to include or exclude it.",
    details: [
      "Selected buildings become candidate destinations and can receive building types and demand settings.",
      "Selected parking areas are the parking facilities included in the saved model and simulation.",
      "“Deselect unnamed” quickly excludes OSM features without a name, which are often minor or incomplete entries.",
    ],
    note: "Deselecting never changes OpenStreetMap or the uploaded file. Review unnamed shapes on the map before excluding them—some may still be important.",
  },
  {
    title: "Choose pedestrian and vehicle origins",
    shortTitle: "Set travel origins",
    icon: BusFront,
    description: "Tell the simulation where independently generated pedestrians and vehicles enter the campus.",
    details: [
      "Open Public & Vehicle Origins from the Current Model card.",
      "Public-transport origins are unchanged: choose a building or add a custom pedestrian point.",
      "Add one or more vehicle generation points on the map, select each passenger lane and direction, then save the model.",
    ],
    note: "When vehicle points are saved, configure their percentages or exact car counts on the Simulation page. Without saved points, automatic vehicle origins remain active.",
  },
];

type NewModelGuideDialogProps = {
  open: boolean;
  initialStep?: number;
  onOpenChange: (open: boolean) => void;
};

export default function NewModelGuideDialog({
  open,
  initialStep = 0,
  onOpenChange,
}: NewModelGuideDialogProps) {
  const [activeStep, setActiveStep] = useState(initialStep);

  useEffect(() => {
    if (open) {
      setActiveStep(Math.min(Math.max(initialStep, 0), GUIDE_STEPS.length - 1));
    }
  }, [initialStep, open]);

  const step = GUIDE_STEPS[activeStep];
  const StepIcon = step.icon;
  const isLastStep = activeStep === GUIDE_STEPS.length - 1;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto p-0">
        <DialogHeader className="border-b px-6 py-5 pr-12">
          <div className="mb-1 flex items-center gap-2">
            <Badge variant="secondary">New model guide</Badge>
            <span className="text-xs text-muted-foreground">
              Step {activeStep + 1} of {GUIDE_STEPS.length}
            </span>
          </div>
          <DialogTitle>Build an area model in five steps</DialogTitle>
          <DialogDescription>
            Follow this once from left to right. You can reopen this guide from the sidebar at any time.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-5 px-6 py-5 sm:grid-cols-[170px_minmax(0,1fr)]">
          <nav aria-label="New model guide steps" className="space-y-1">
            {GUIDE_STEPS.map((guideStep, index) => {
              const Icon = guideStep.icon;
              return (
                <button
                  key={guideStep.title}
                  type="button"
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-xs transition-colors",
                    index === activeStep
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                  onClick={() => setActiveStep(index)}
                  aria-current={index === activeStep ? "step" : undefined}
                >
                  <span
                    className={cn(
                      "flex size-7 shrink-0 items-center justify-center rounded-full border",
                      index === activeStep ? "border-primary-foreground/30" : "border-border bg-background",
                    )}
                  >
                    <Icon className="size-3.5" />
                  </span>
                  <span>{guideStep.shortTitle}</span>
                </button>
              );
            })}
          </nav>

          <section aria-live="polite">
            <div className="mb-4 flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <StepIcon className="size-5" />
            </div>
            <h3 className="text-lg font-semibold tracking-tight">{step.title}</h3>
            <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{step.description}</p>

            <ol className="mt-4 space-y-3">
              {step.details.map((detail, index) => (
                <li key={detail} className="flex gap-3 text-sm leading-5">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-[0.68rem] font-semibold text-muted-foreground">
                    {index + 1}
                  </span>
                  <span>{detail}</span>
                </li>
              ))}
            </ol>

            <div className="mt-5 rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-800 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-200">
              <strong>Good to know:</strong> {step.note}
            </div>
          </section>
        </div>

        <DialogFooter className="border-t px-6 py-4">
          <Button
            type="button"
            variant="outline"
            disabled={activeStep === 0}
            onClick={() => setActiveStep((current) => Math.max(0, current - 1))}
          >
            Back
          </Button>
          <Button
            type="button"
            onClick={() => {
              if (isLastStep) {
                onOpenChange(false);
              } else {
                setActiveStep((current) => Math.min(GUIDE_STEPS.length - 1, current + 1));
              }
            }}
          >
            {isLastStep ? "Start building" : "Next"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
