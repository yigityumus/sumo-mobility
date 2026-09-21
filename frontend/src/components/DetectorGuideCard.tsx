import { useEffect, useState } from "react";
import { Binary, CircleHelp, Crosshair, Gauge, Route } from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";

const DETECTOR_GUIDE_SEEN_KEY = "sumo-campus-builder:detector-guide-v1";

const guideSections = [
  {
    icon: Crosshair,
    title: "How to add a detector",
    content: (
      <ol className="space-y-2 text-xs leading-5 text-muted-foreground">
        <li><strong className="text-foreground">1.</strong> Choose <strong className="text-foreground">Add E1</strong> or <strong className="text-foreground">Add E3</strong>.</li>
        <li><strong className="text-foreground">2.</strong> For E1, click one road cross-section. For E3, click the entry first and then the exit.</li>
        <li><strong className="text-foreground">3.</strong> Refresh nearby lanes and select the lanes that pass through the real sensor's visible area.</li>
        <li><strong className="text-foreground">4.</strong> Use <strong className="text-foreground">900 seconds</strong> for 15-minute output, then click <strong className="text-red-600">Unsaved Changes</strong> in the header to save.</li>
      </ol>
    ),
  },
  {
    icon: Gauge,
    title: "E1 and E3 are different measurements",
    content: (
      <div className="space-y-3 text-xs leading-5 text-muted-foreground">
        <p><Badge variant="outline" className="mr-1.5">E1</Badge> A point counter on a vehicle lane. It measures passages, flow, speed and occupancy at one cross-section.</p>
        <p><Badge variant="outline" className="mr-1.5">E3</Badge> Vehicles use an entry-to-exit measurement with counts, travel time, speed and stops. Pedestrians use a safe bidirectional zone between the markers and are counted when entering from either end.</p>
        <p className="font-medium text-foreground">Use E1 for a simple fixed-point vehicle count. Use E3 when the observed area and movement through it matter.</p>
      </div>
    ),
  },
  {
    icon: Route,
    title: "Why E3 is suggested for this simulation",
    content: (
      <div className="space-y-2 text-xs leading-5 text-muted-foreground">
        <p>The university's Telraam-style camera observes several vehicle and pedestrian lanes together. One logical E3 detector creates linked vehicle traversal and pedestrian zone measurements.</p>
        <p>Vehicle measurements preserve travel-time and stopping information. Pedestrian zones deliberately record direction-independent entries because walkers can legitimately use a sidewalk in either direction.</p>
        <p className="rounded-md border border-amber-200 bg-amber-50 p-2.5 text-amber-900 dark:border-amber-900 dark:bg-amber-950/35 dark:text-amber-100">
          <strong>Vehicles:</strong> direction matters, so create a corresponding E3 for each traffic direction. <strong>Pedestrians:</strong> select the same sidewalk lane at both markers; either walking direction is counted safely.
        </p>
      </div>
    ),
  },
  {
    icon: Binary,
    title: "What the lane IDs mean",
    content: (
      <div className="space-y-2 text-xs leading-5 text-muted-foreground">
        <p>A lane ID identifies one lane in the generated SUMO network. It is not necessarily the same as an OpenStreetMap ID.</p>
        <p>IDs often end in an index such as <code className="rounded bg-muted px-1 py-0.5 text-foreground">_0</code> or <code className="rounded bg-muted px-1 py-0.5 text-foreground">_1</code>. The index distinguishes lanes on the same SUMO edge; the edge also defines their reference direction.</p>
        <p>Use the <strong className="text-foreground">vehicle</strong> and <strong className="text-foreground">pedestrian</strong> badges to choose compatible lanes. Hover a lane ID to highlight it on the map before selecting it.</p>
        <p>Include every lane that crosses the detector line, but exclude nearby lanes that are outside the real camera's field of view.</p>
      </div>
    ),
  },
];

export default function DetectorGuideCard() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try {
      if (!window.localStorage.getItem(DETECTOR_GUIDE_SEEN_KEY)) setOpen(true);
    } catch {
      setOpen(true);
    }
  }, []);

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      try {
        window.localStorage.setItem(DETECTOR_GUIDE_SEEN_KEY, "seen");
      } catch {
        // The guide remains available from the card when browser storage is restricted.
      }
    }
  };

  return (
    <>
      <Card className="border-blue-200 bg-blue-50/70 shadow-sm dark:border-blue-900 dark:bg-blue-950/25">
        <CardHeader className="p-4 pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <CircleHelp className="size-4 text-blue-700 dark:text-blue-300" />
            Detector guide
          </CardTitle>
          <CardDescription className="text-xs leading-5">
            Learn how to place E1 and E3 detectors, choose lanes, and reproduce 15-minute multi-lane sensor counts.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-4 pt-1">
          <Button type="button" variant="outline" size="sm" className="w-full bg-background/80" onClick={() => setOpen(true)}>
            <CircleHelp className="size-4" /> Open detector guide
          </Button>
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <div className="mb-1 flex items-center gap-2">
              <Badge variant="secondary">Detector setup</Badge>
              <span className="text-xs text-muted-foreground">E1 · E3 · SUMO lanes</span>
            </div>
            <DialogTitle>How detectors work in this model</DialogTitle>
            <DialogDescription>
              Configure a detector to match the physical area and directions observed by the real sensor.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 sm:grid-cols-2">
            {guideSections.map((section) => {
              const Icon = section.icon;
              return (
                <section key={section.title} className="rounded-xl border bg-card p-4 shadow-sm">
                  <div className="mb-3 flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="size-4" />
                  </div>
                  <h3 className="mb-2 text-sm font-semibold">{section.title}</h3>
                  {section.content}
                </section>
              );
            })}
          </div>

          <DialogFooter>
            <Button type="button" onClick={() => handleOpenChange(false)}>Got it</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
