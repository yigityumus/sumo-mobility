import { BookOpen, BusFront, ExternalLink } from "lucide-react";
import TopNavigation from "../../components/TopNavigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";

type Props = {
  onHome: () => void;
  onAnalytics: () => void;
  onDocumentation: () => void;
};

export default function DocumentationPage({ onHome, onAnalytics, onDocumentation }: Props) {
  return (
    <main className="min-h-full overflow-y-auto bg-muted/30 px-5 py-6 sm:px-8 sm:py-9">
      <div className="mx-auto w-full max-w-5xl">
        <TopNavigation active="documentation" onHome={onHome} onAnalytics={onAnalytics} onDocumentation={onDocumentation} />
        <header className="mb-7 mt-12">
          <h1 className="flex items-center gap-3 text-3xl font-semibold tracking-tight"><BookOpen className="size-7 text-primary" /> Documentation</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">Quick references for developing and running the campus simulation project.</p>
        </header>

        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Traffic demand models</CardTitle><CardDescription>The simulation implementation and the graph preview are intentionally separate.</CardDescription></CardHeader>
            <CardContent className="space-y-3 text-sm leading-6">
              <p><strong>Simulation departures:</strong> <code>backend/sumo/scenario/demand/generate.py</code>, function <code>distributed_departure_times</code>.</p>
              <p><strong>Fourier engine:</strong> <code>backend/domain/demand/fourier.py</code>. It supports both fitting measured profiles and generating profiles with up to 16 hills and 0.01-hour width input. Extremely narrow hills are smoothed by the selected finite harmonic count.</p>
              <p><strong>Frontend preview:</strong> <code>frontend/src/features/simulation/TrafficProfileChart.tsx</code>. Its Fourier coefficients mirror the backend profile.</p>
              <p><strong>Parking choice:</strong> each run snapshots editable weights for driving time, walking time, capacity, absolute and relative free space, plus occupancy knowledge, perception error, frustration, and random preference. Every new run receives a fresh saved seed, so repeated setups vary while each result remains reproducible.</p>
              <p><strong>Accepted model names:</strong> <code>backend/services/api/schemas.py</code> and <code>frontend/src/types/campus.ts</code>.</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Building demand classifications</CardTitle><CardDescription>Classifications refine destination demand but are optional.</CardDescription></CardHeader>
            <CardContent className="space-y-3 text-sm leading-6">
              <p>A simulation can run without a building classification. In that mode, every selected building is an eligible destination with equal random demand treatment.</p>
              <p>Classification and type names are user-defined; no special name such as <code>Teaching</code> is required. When a classification is selected for a run, assigned buildings use their type’s pedestrian and vehicle demand weights.</p>
              <p>Buildings left unassigned are not excluded. They remain eligible with neutral 50/50 weights, while the Simulation page’s global split continues to set exact car and pedestrian totals.</p>
              <p>The optional pedestrian-origin source named <strong>Residential</strong> is the one intentional reserved name: when requested on the Simulation page, selected buildings assigned to a classification type named Residential become walking origins. The source is disabled when that type or its assigned buildings are absent.</p>
              <p>Independent walkers are divided exactly between Residential buildings and saved Public Transportation Origins. Car arrivals are shown as a third, read-only source because each successfully parked driver then becomes a pedestrian at the parking access. These are the same people changing travel mode, not additional demand.</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Development services</CardTitle><CardDescription>Local endpoints available while the project is running.</CardDescription></CardHeader>
            <CardContent className="space-y-3 text-sm leading-6">
              <p>Frontend: <code>http://localhost:5173</code></p>
              <p>Backend: <code>http://127.0.0.1:8000</code></p>
              <a className="inline-flex items-center gap-2 font-medium text-primary underline-offset-4 hover:underline" href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">Interactive API documentation <ExternalLink className="size-4" /></a>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>E1 and E3 traffic detectors</CardTitle><CardDescription>Detector locations are model data and are resolved for each generated network.</CardDescription></CardHeader>
            <CardContent className="space-y-3 text-sm leading-6">
              <p>Open a saved model and choose <strong>Edit Detectors</strong>. E1 placement uses one map click. E3 placement uses two clicks: the measured area's entry cross-section first and its exit cross-section second.</p>
              <p>Nearby SUMO lane geometry is overlaid on the map: blue lanes permit vehicles, magenta lanes permit pedestrians, and violet lanes permit both. E3 entry and exit sections support selecting multiple individual lanes; the closest small lane group is selected automatically and can be edited.</p>
              <p>An E3 website group may measure vehicles, pedestrians, or both. Vehicles use SUMO's directional E3 entry/exit measurement. Pedestrians use one E2 lane-area zone per selected sidewalk, spanning the two markers, so a walker entering from either direction is counted safely. Exact lane IDs and offsets are resolved and stored with every simulation run.</p>
              <p><strong>Traffic detector measurements</strong> in Analytics include count, flow, and speed. Vehicle E3 measurements also provide travel time, halts, time loss, and agents still inside; pedestrian zones provide direction-independent entry counts and occupancy.</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><BusFront className="size-5 text-primary" /> Public and vehicle origins</CardTitle><CardDescription>Choose independent pedestrian origins and exact vehicle generation lanes.</CardDescription></CardHeader>
            <CardContent className="space-y-3 text-sm leading-6">
              <p>Open a model and choose <strong>Public &amp; Vehicle Origins</strong>. Public-transport origins are unchanged: click a building or add a custom point for a bus stop, metro entrance, tram stop, or another pedestrian arrival location.</p>
              <p>Each origin is snapped to a nearby walkable SUMO lane when the simulation is prepared. Pedestrians are distributed across the selected origins and sent only to destination buildings that SUMO can reach on foot.</p>
              <p>Under <strong>Vehicle generation points</strong>, click <strong>Add generation point</strong>, click the map, and choose the required passenger lane and travel direction. Add as many points as needed. On the Simulation page, allocate cars by percentage or exact count across the current points. If none are saved, automatic road-boundary selection is used.</p>
              <p>Building classifications control destination types and demand weighting. They do not need a Metro Station or Public Transportation building type.</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Language support plan</CardTitle><CardDescription>Keep English complete while making additional languages incremental.</CardDescription></CardHeader>
            <CardContent className="space-y-3 text-sm leading-6">
              <p>Use <code>i18next</code> with <code>react-i18next</code>, English as <code>fallbackLng</code>, and namespaced locale files such as <code>locales/en/simulation.json</code> and <code>locales/fr/simulation.json</code>.</p>
              <p>Dates, times, percentages, and counts should use <code>Intl</code> with the active locale. Backend failures should expose stable error codes so the frontend can translate friendly messages while preserving raw SUMO logs exactly.</p>
              <p>German, Spanish, or Dutch then become additional locale files rather than new application logic. Translation can be introduced page by page without removing any English text.</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </main>
  );
}
