import type { ReactNode } from "react";
import { BarChart3, BookOpen, Building2, BusFront, CircleHelp, MapPinned, Play, Radar, Route, Search, SquareParking } from "lucide-react";
import TopNavigation from "../../components/TopNavigation";
import { Alert, AlertDescription, AlertTitle } from "../../components/ui/alert";
import { Badge } from "../../components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";

type Props = { onHome: () => void; onAnalytics: () => void; onDocumentation: () => void };
type Row = { name: string; meaning: string; effect: string };
type Graph = { title: string; axes: string; meaning: string; use: string };

const pageLinks = [
  ["new-model", "Start a New Model"], ["model", "Model page"], ["detectors", "Edit Detectors"],
  ["origins", "Public & Vehicle Origins"], ["parking", "Edit Parking Specs"],
  ["buildings", "Edit Building Specs"], ["simulation", "Run Simulation"], ["analytics", "Analytics"],
] as const;

function Table({ rows }: { rows: Row[] }) {
  return <div className="overflow-x-auto rounded-lg border"><table className="w-full min-w-[760px] text-left text-sm">
    <thead className="bg-muted/60 text-xs uppercase text-muted-foreground"><tr><th className="w-[22%] px-3 py-2.5">Control or result</th><th className="w-[39%] px-3 py-2.5">What it means</th><th className="w-[39%] px-3 py-2.5">What changes and why it matters</th></tr></thead>
    <tbody className="divide-y">{rows.map((row) => <tr key={row.name} className="align-top"><td className="px-3 py-3 font-medium">{row.name}</td><td className="px-3 py-3 leading-6 text-muted-foreground">{row.meaning}</td><td className="px-3 py-3 leading-6 text-muted-foreground">{row.effect}</td></tr>)}</tbody>
  </table></div>;
}

function Section({ id, icon, title, description, children }: { id: string; icon: ReactNode; title: string; description: string; children: ReactNode }) {
  return <section id={id} className="scroll-mt-6"><Card className="overflow-hidden shadow-sm"><CardHeader className="border-b bg-muted/25"><CardTitle className="flex items-center gap-3 text-xl">{icon}{title}</CardTitle><CardDescription className="max-w-4xl text-sm leading-6">{description}</CardDescription></CardHeader><CardContent className="space-y-6 p-5 sm:p-6">{children}</CardContent></Card></section>;
}

function Topic({ title, children }: { title: string; children: ReactNode }) {
  return <div className="space-y-2"><h3 className="text-base font-semibold">{title}</h3><div className="space-y-2 text-sm leading-6 text-muted-foreground">{children}</div></div>;
}

function GraphCard({ graph }: { graph: Graph }) {
  return <div className="rounded-lg border p-4"><h4 className="font-semibold">{graph.title}</h4><p className="mt-2 text-sm leading-6 text-muted-foreground"><strong className="text-foreground">Axes:</strong> {graph.axes}</p><p className="mt-1 text-sm leading-6 text-muted-foreground"><strong className="text-foreground">Represents:</strong> {graph.meaning}</p><p className="mt-1 text-sm leading-6 text-muted-foreground"><strong className="text-foreground">Use it to:</strong> {graph.use}</p></div>;
}

const newModelRows: Row[] = [
  { name: "Upload a .osm file", meaning: "Uses an existing .osm, .osm.xml, or compressed OSM extract.", effect: "This becomes the source geography. Use it for repeatable studies or when online OSM download is unavailable." },
  { name: "Draw rectangle or polygon", meaning: "Defines the area downloaded from OpenStreetMap.", effect: "Larger areas create larger networks and slower preparation/runs. Include required approach roads but keep the study boundary focused." },
  { name: "Load buildings and parking areas", meaning: "Extracts candidate features inside the boundary.", effect: "Loaded does not mean included: review which objects are selected." },
  { name: "Download selected area as .osm", meaning: "Saves the raw OSM source for the drawn area.", effect: "Archive it to recreate the same source without another online request." },
  { name: "Selected / unselected shapes", meaning: "Solid shapes are included; dashed shapes are excluded.", effect: "Selected buildings may receive demand and selected parking may be generated. Excluded objects remain visible only for reference." },
  { name: "Deselect unnamed", meaning: "Excludes features without a readable OSM name.", effect: "It is only a shortcut. Inspect them because an unnamed feature may still matter." },
  { name: "Model name and Save", meaning: "Stores the current physical model and settings.", effect: "Simulation is disabled while changes are unsaved, ensuring every run uses a reproducible model version." },
];

const modelRows: Row[] = [
  { name: "Map and legend", meaning: "Shows boundary, buildings, parking, origins, detectors, and relevant SUMO lanes.", effect: "Click building or parking shapes to include/exclude them. Legend colours identify selected, highlighted, and expanded objects." },
  { name: "Current Model", meaning: "Shows name, timestamps, and Saved/Unsaved status.", effect: "Save before running. Editing a model does not rewrite completed-run snapshots." },
  { name: "Select buildings", meaning: "Chooses candidate destinations.", effect: "More buildings create more destinations, although disconnected buildings may be excluded during route preparation." },
  { name: "Select parking areas", meaning: "Chooses facilities generated in SUMO.", effect: "Selection, capacity, and road connection determine available parking supply." },
  { name: "Configuration buttons", meaning: "Open Building Specs, Parking Specs, Origins, Detectors, or Simulation.", effect: "Each edits a different layer: destinations, supply, entry locations, measurement, or run-time demand." },
  { name: "Demand Distribution overlay", meaning: "For each building type, the slider splits destination capacity between pedestrian and vehicle demand, while the capacity constant scales floor area × building levels.", effect: "The resulting mode-specific capacity is used as the destination probability weight. A constant of 0 prevents that type from receiving destinations. Unassigned buildings use constant 1 and a neutral 50/50 split." },
  { name: "Download model", meaning: "Exports chosen OSM, building, parking, and model-config files in a ZIP.", effect: "Use it to archive, inspect, or share inputs independently of results." },
  { name: "Duplicate / Rename / Delete", meaning: "Actions on saved model cards on Home.", effect: "Duplicate before experimental changes. Delete is destructive; completed runs retain their own snapshots." },
];

const detectorRows: Row[] = [
  { name: "E1", meaning: "A point detector on one lane or all passenger lanes of a road edge.", effect: "Measures traffic at one cross-section; best for a simple precise vehicle count." },
  { name: "E3", meaning: "A group with entry and exit cross-sections.", effect: "Tracks vehicle entry-to-exit traversal. Pedestrians use bidirectional sidewalk zones between markers." },
  { name: "Placement order", meaning: "E1 needs one click; E3 needs entry first and exit second.", effect: "Order defines vehicle direction. Reversed or mismatched markers can record entries without completed traversals." },
  { name: "Native interval", meaning: "Seconds combined into one SUMO record; default 900.", effect: "Short intervals add detail and noise. Physical validation is always aligned to 900-second buckets." },
  { name: "Measure", meaning: "Select vehicles, pedestrians, or both for E3.", effect: "Both must be enabled to validate both subjects against a physical sensor." },
  { name: "Lane selection", meaning: "Exact SUMO lanes crossed by the detector.", effect: "Missing lanes undercount; unrelated lanes overcount. Blue lanes permit cars, magenta pedestrians, violet both." },
  { name: "Lane shortcuts / Refresh", meaning: "Select all nearby, vehicle, or pedestrian lanes and refresh geometry.", effect: "Use shortcuts as a starting point, then verify every highlighted lane. First lookup may build and cache the network." },
  { name: "Entry/exit compatibility", meaning: "E3 sections should cover the same corridor and corresponding sidewalks.", effect: "Unequal or incompatible lanes can leave vehicles inside and prevent a valid pedestrian zone." },
];

const originRows: Row[] = [
  { name: "Building transit origin", meaning: "A building used as an independent pedestrian start.", effect: "Public-transport walkers may begin there and travel to reachable destinations." },
  { name: "Custom transit point", meaning: "A bus stop, station entrance, or other pedestrian map point.", effect: "It snaps to a nearby walkable lane; bad placement may snap to a wrong or disconnected footpath." },
  { name: "Vehicle generation point", meaning: "An exact road lane where cars enter.", effect: "Origin location changes routes, detector flow, congestion, and parking choice." },
  { name: "Passenger lane and direction", meaning: "Controls insertion lane and travel direction.", effect: "Choose a lane pointing into the area; the opposite lane can send cars away or invalidate routes." },
  { name: "Multiple points", meaning: "The count is dynamic, not fixed to four.", effect: "Simulation creates an allocation input for every saved point, so points can be added or removed later." },
  { name: "No vehicle points", meaning: "Automatic fringe-road origins are used.", effect: "Older models remain runnable, but entry distribution is less controllable." },
];

const parkingRows: Row[] = [
  { name: "Classifications and types", meaning: "Optional user-defined parking labels.", effect: "They organise facilities but do not automatically change choice unless later model logic uses them." },
  { name: "Highlight filters", meaning: "Highlights access or capacity groups in green.", effect: "Visual only: filters never select, remove, or export anything." },
  { name: "Access", meaning: "Saved access description, initially from OSM when available.", effect: "Useful for auditing suitability; real reachability still depends on the generated road connection." },
  { name: "Capacity", meaning: "Maximum simultaneous parked cars; a positive whole number.", effect: "Lower supply causes earlier rejection, fallback, and unserved cars. Higher supply delays saturation." },
  { name: "Source", meaning: "Whether access/capacity came from OSM, manual entry, or calculation.", effect: "It records confidence and provenance; an estimate is not a measured capacity." },
  { name: "Fill unknown", meaning: "Estimates capacity from related aisle/service-way length at about one slot per 2.3 m.", effect: "Provides a starting assumption. Review irregular geometry manually." },
  { name: "Fill all / Revert", meaning: "Estimates every unknown or restores the original value.", effect: "Bulk fill speeds setup; Revert undoes manual/calculated overrides." },
  { name: "Selected / Not selected", meaning: "Separates simulated facilities from reference-only ones.", effect: "Editing an unselected lot does not include it; select it on the Model page too." },
];

const buildingRows: Row[] = [
  { name: "Classification", meaning: "An optional labeling system such as Usage Policy.", effect: "A run selects one system. Multiple systems support different research questions on the same buildings." },
  { name: "Type", meaning: "A category such as Teaching, Office, Residential, or Laboratory.", effect: "Assigned buildings inherit that type's pedestrian/vehicle split and capacity constant." },
  { name: "Assignment", meaning: "Gives a selected building one type in the active classification.", effect: "It changes relative destination probability, not population size." },
  { name: "Unknown / unspecified", meaning: "No type is assigned.", effect: "The building remains eligible with constant 1 and a neutral 50/50 split; its footprint area and levels still determine capacity." },
  { name: "Residential", meaning: "The one reserved type name, matched case-insensitively.", effect: "Assigned selected buildings may also act as origins for Residential walkers." },
  { name: "Search", meaning: "Filters by name, description, or OSM ID.", effect: "It changes only the visible list, not selection or assignments." },
  { name: "Delete classification", meaning: "Removes it and its assignments after save.", effect: "Future runs cannot select it; completed runs retain their snapshot." },
];

const simulationRows: Row[] = [
  { name: "Total people", meaning: "Population represented by the run.", effect: "Split into car arrivals and independent walkers. Higher totals increase demand and runtime." },
  { name: "By car", meaning: "One person driving one car.", effect: "After successful parking, the same person becomes a pedestrian; this is not an extra person." },
  { name: "Independent walkers", meaning: "People generated without a car.", effect: "They must be allocated between Residential and Public transport origins." },
  { name: "Vehicle entry allocation", meaning: "Percentages or exact counts across all saved car origins.", effect: "Must total 100% or all cars. It changes approach roads, detector traffic, and parking pressure." },
  { name: "Building classification", meaning: "Destination weighting used by this run.", effect: "No classification uses floor area × building levels with constant 1 and a neutral 50/50 split." },
  { name: "Walking sources", meaning: "Residential, Public transport, and read-only Parked-car drivers.", effect: "Residential + transit equals independent walkers. A parked-driver walk exists only after successful parking." },
  { name: "Start and duration", meaning: "Calendar time for second zero and a 1–168 hour demand window.", effect: "Controls chart labels and physical-data alignment. Travelling agents may finish after the demand window." },
  { name: "Constant / Linear / Normal", meaning: "Uniform, increasing, or midpoint bell-shaped generation.", effect: "They redistribute a fixed total over time without editable individual peaks." },
  { name: "Fourier hills", meaning: "1–16 evenly spaced peaks.", effect: "For N peaks over T hours, cells are T/N and the first centre is T/(2N). Changing N moves all centres." },
  { name: "Width / Harmonics", meaning: "Hill standard deviation and Fourier resolution.", effect: "More width broadens peaks; more harmonics reproduce sharper detail. Narrow peaks with few harmonics are smoothed." },
  { name: "Peak amplitude", meaning: "Relative hill strength from 0–300%.", effect: "Reallocates fixed demand toward that time cell. Detector response may saturate and need not change proportionally." },
  { name: "Profile preview", meaning: "Input rates: blue cars and orange independent walkers in agents/hour.", effect: "Area under each curve equals its total. It is generated demand, not predicted detector output." },
  { name: "Striping / Fast", meaning: "Interacting or simplified non-interacting pedestrian movement.", effect: "Striping is more detailed and slower. Fast is suitable for speed but not detailed crowd interaction." },
  { name: "SUMO / SUMO GUI", meaning: "Headless execution or visual interface.", effect: "SUMO is fastest and required for calibration. GUI needs host display setup and is slower." },
  { name: "Diagnostic trace", meaning: "Detailed TraCI communication log.", effect: "Useful for failures but creates large logs and can slow execution." },
];

const parkingChoiceRows: Row[] = [
  { name: "Driving / Walking time", meaning: "Penalties for car route and final walk duration.", effect: "Higher values favour faster-to-drive or closer-to-walk alternatives." },
  { name: "Capacity", meaning: "Preference for larger facilities.", effect: "Higher values favour high-capacity lots independently of current occupancy." },
  { name: "Free count / ratio", meaning: "Preference for absolute empty bays or proportion empty.", effect: "A large lot may win on count while a small empty lot wins on ratio." },
  { name: "Occupancy knowledge", meaning: "0–1 chance of knowing remote true occupancy.", effect: "Higher values model signs/apps/familiarity and usually reduce wasted searches." },
  { name: "Expected occupancy / error", meaning: "Belief and uncertainty when occupancy is unknown.", effect: "Higher mean expects fuller lots; higher error makes beliefs less consistent." },
  { name: "Frustration", meaning: "Availability's added importance after failure.", effect: "Higher values make drivers adapt more strongly after rejection." },
  { name: "Choice randomness", meaning: "Unobserved preference; 0 is deterministic.", effect: "Higher values spread choices. Coefficients are relative weights and may exceed 1; they are not percentages." },
];

const operationRows: Row[] = [
  { name: "Start simulation", meaning: "Validates the form, snapshots every setting, and submits a standalone job.", effect: "The run enters the durable queue. It may be queued even when no worker is immediately free." },
  { name: "Calibration name / iterations", meaning: "Labels one locked group and sets 1–100 sequential runs.", effect: "Each next iteration depends on the previous result, so iterations within one group do not run concurrently." },
  { name: "Minimum percentage step", meaning: "Smallest nonzero Fourier amplitude adjustment.", effect: "Larger steps react faster but can overshoot; smaller steps allow finer convergence." },
  { name: "Physical sensor / E3 detector", meaning: "Pairs the real target with the virtual observation point.", effect: "They must represent the same location, direction, and subjects or calibration has no physical meaning." },
  { name: "Percentages to update", meaning: "Vehicle peaks, pedestrian peaks, or both.", effect: "Only the chosen peak arrays change; all other inputs remain locked." },
  { name: "Queue counters", meaning: "Running/waiting for this model, running globally, and total worker capacity.", effect: "They explain when a job can start. With four workers, up to four independent runs execute together." },
  { name: "Run history", meaning: "Standalone runs plus expandable calibration groups and iteration status.", effect: "Refresh updates records; active runs may be stopped and inactive runs deleted. Column widths are resizable and resettable." },
];

const analyticsControlRows: Row[] = [
  { name: "Primary simulation set", meaning: "A standalone run or one calibration group.", effect: "For a group, choose the primary iteration separately; the group stays one logical experiment." },
  { name: "Compare simulations", meaning: "Adds up to four other runs to supported charts.", effect: "Colours identify runs. Use compatible maps, detectors, durations, and time windows for meaningful overlays." },
  { name: "Run summary", meaning: "Model, dates, totals, duration, parking count, demand profiles, and entry allocation.", effect: "These are requested inputs and context; verify them before attributing an output difference to one parameter." },
  { name: "Parking snapshot", meaning: "Configured and actually generated capacity for every parking area in that run.", effect: "It preserves the run-time supply even if the model is edited later." },
  { name: "Raw observations", meaning: "Physical measurements from one selected real date/time window.", effect: "Useful for reproducing one day, but special events and noise may dominate." },
  { name: "Weekly average", meaning: "Mean of the same weekday and 15-minute slot across available weeks.", effect: "Usually a steadier calibration target; the sample badge shows approximate observations per average point." },
  { name: "Download graph CSV", meaning: "Exports the aligned input, simulated detector, and physical graph series.", effect: "Use it for external analysis, reporting, and reproducible figures." },
];

const analyticsGraphs: Graph[] = [
  { title: "Parking → buildings", axes: "Bars list destination buildings; length/count is parked people.", meaning: "Where people who actually used one parking area intended to go. Cards show candidate, initial choice, parked, rerouted, and capacity counts.", use: "Understand which destinations a lot serves and whether it was never eligible, rarely chosen, full, or rerouted away." },
  { title: "Building → parkings", axes: "Bars list actual parking outcomes and counts.", meaning: "Where drivers destined for one building parked, including Did not park.", use: "Find dependence on particular lots and unserved destination demand." },
  { title: "Destination selections over time", axes: "X is planned departure time; Y is destination assignments per 15-minute interval.", meaning: "Separate lines show drivers and standalone pedestrians assigned to the selected building. The selector reports its final destination capacity: footprint area × levels × classification constant.", use: "Compare when each mode creates demand for a destination and relate the counts to its final capacity." },
  { title: "Parking capacity over time", axes: "X is simulated time; Y is occupied or empty capacity, 0–100%.", meaning: "Parked cars only; approaching and queued cars are excluded. Comparisons overlay other runs.", use: "Explain rejection/fallback near 100%, or investigate route/choice issues when a lot stays empty." },
  { title: "Parking areas attempted", axes: "X is distinct lots attempted per car; Y is number of cars.", meaning: "Histogram of search and fallback before parking or exhausting choices.", use: "A peak at 1 means direct parking; a long tail suggests capacity, information, or first-choice problems." },
  { title: "Recorded parking search duration", axes: "X is time; Y is binned average minutes.", meaning: "Line values are bin averages; summary median/P95 are individual-car statistics and may exceed every bin average.", use: "Locate difficult periods and compare them with demand and occupancy." },
  { title: "Vehicle journey segment duration", axes: "X is segment start; Y is average minutes.", meaning: "Selected stage: to parking, inside parking, between parking after fallback, or parked. Repeated visits stay separate.", use: "Separate road delay, internal circulation, and fallback travel." },
  { title: "Traffic detector measurements", axes: "X is interval end; Y is agents entering per native detector interval.", meaning: "Raw E1/E2/E3 interval counts and a full-run entry total.", use: "Confirm which traffic crossed selected lanes. This is count per interval, not agents/hour." },
  { title: "Simulation detector vs real-world sensor", axes: "X is aligned time; Y is agents/hour in 15-minute buckets.", meaning: "Dashed is network-wide input; solid blue detector output; physical sensor is the real target. Physical vehicles combine cars and large vehicles.", use: "Match shape and level after verifying sensor location, direction, weekday, start, and duration. Input need not equal location-specific output." },
  { title: "Calibration Input vs output", axes: "X is time; Y is agents/hour, separately for cars and pedestrians.", meaning: "Dashed iteration input, solid iteration detector output, thick black weekly-average target.", use: "Toggle iterations to see how peak edits move detector output." },
  { title: "Calibration input percentage", axes: "X is iteration; Y is selected peak amplitude %.", meaning: "The exact parameter value used each iteration.", use: "Check direction, quantized step, oscillation, or boundary limits." },
  { title: "Calibration peak-window response", axes: "X is iteration; Y is average agents/hour in the selected peak cell.", meaning: "Simulated output versus physical target as input changes.", use: "Reveal sensitivity and saturation; a flat response suggests weak influence or another constraint." },
  { title: "Calibration error curves", axes: "X is iteration; Y is error %.", meaning: "NRMSE, NMAE, shape error, and volume error across all peak windows.", use: "Look for downward trends, but inspect trade-offs and profiles rather than choosing by one metric." },
];

const statisticRows: Row[] = [
  { name: "NRMSE / NMAE", meaning: "Root-mean-square or mean-absolute error divided by mean real flow.", effect: "Lower is better; NRMSE penalizes large misses more strongly." },
  { name: "MAPE", meaning: "Mean absolute percentage error where real flow is positive.", effect: "Lower is better, but tiny targets can make it unstable." },
  { name: "Bias", meaning: "Mean simulation minus real flow, normalized.", effect: "Positive is systematic overproduction; negative is underproduction. Zero may hide cancelling errors." },
  { name: "Correlation / Shape", meaning: "Co-movement from −1 to 1; shape error = (1 − correlation)/2.", effect: "Correlation near 1 and shape error near 0 mean timing/shape agree, not necessarily volume." },
  { name: "Volume error", meaning: "Absolute difference in mean simulated and real flow, normalized.", effect: "Lower is better; it ignores when peaks occur." },
  { name: "NSE", meaning: "Nash–Sutcliffe efficiency against using the real mean.", effect: "1 perfect, 0 no better than mean, negative worse than mean." },
  { name: "Residual", meaning: "Simulated minus real peak-window flow.", effect: "Positive is too high; negative too low." },
  { name: "Update model", meaning: "Proportional, local elasticity, Hill saturation, or undefined zero-flow update.", effect: "R² describes Hill fit. Proposed is raw, Next is bounded/quantized, Predicted output is the forecast." },
];

export default function DocumentationPage({ onHome, onAnalytics, onDocumentation }: Props) {
  return <main className="min-h-full overflow-y-auto bg-muted/30 px-4 py-6 sm:px-8 sm:py-9"><div className="mx-auto max-w-7xl">
    <TopNavigation active="documentation" onHome={onHome} onAnalytics={onAnalytics} onDocumentation={onDocumentation} />
    <header className="mb-7 mt-12 max-w-4xl"><Badge variant="secondary" className="mb-3">User guide</Badge><h1 className="flex items-center gap-3 text-3xl font-semibold"><BookOpen className="size-7 text-primary" /> Campus simulation documentation</h1><p className="mt-3 text-sm leading-6 text-muted-foreground">A complete guide from map creation to result interpretation. No prior knowledge of SUMO, OpenStreetMap, traffic modelling, or this project is assumed.</p></header>
    <Alert className="mb-6 border-blue-200 bg-blue-50/70 dark:border-blue-900 dark:bg-blue-950/30"><CircleHelp className="size-4" /><AlertTitle>Three layers to remember</AlertTitle><AlertDescription className="leading-6">A <strong>model</strong> describes the physical area. A <strong>run</strong> combines a saved model with demand and behaviour. <strong>Analytics</strong> reports what actually happened. Completed runs keep their own snapshot when the model later changes.</AlertDescription></Alert>
    <nav className="mb-8 grid gap-2 rounded-xl border bg-background p-4 sm:grid-cols-2 lg:grid-cols-4">{pageLinks.map(([id, label], i) => <a key={id} href={`#${id}`} className="rounded-md border px-3 py-2 text-sm font-medium hover:bg-muted"><span className="mr-2 text-muted-foreground">{i + 1}.</span>{label}</a>)}</nav>
    <div className="space-y-6">
      <Section id="new-model" icon={<MapPinned className="size-5 text-primary" />} title="Start a New Model page" description="Creates the geographical foundation used by later runs."><Topic title="Workflow"><ol className="list-decimal space-y-1 pl-5"><li>Upload one OSM extract or draw one map boundary.</li><li>Load and review extracted buildings and parking.</li><li>Keep only study features, name the model, and save.</li><li>Configure specs, origins, and detectors before running.</li></ol></Topic><Table rows={newModelRows} /></Section>
      <Section id="model" icon={<Building2 className="size-5 text-primary" />} title="Model page" description="The map is the physical workspace; the sidebar controls inclusion and opens specialised configuration."><Table rows={modelRows} /></Section>
      <Section id="detectors" icon={<Radar className="size-5 text-primary" />} title="Edit Detectors page" description="Detectors observe traffic without influencing it. Place them at the same cross-section as the measurement you want to reproduce."><Table rows={detectorRows} /><Alert><AlertDescription>A low count can mean low demand, routes avoiding the road, reversed direction, or incomplete lane coverage. Check all four before changing demand.</AlertDescription></Alert></Section>
      <Section id="origins" icon={<BusFront className="size-5 text-primary" />} title="Public & Vehicle Origins page" description="Origins specify where independent walkers and cars enter; destinations specify where they intend to go."><Table rows={originRows} /><p className="text-sm text-muted-foreground">Transit origins are independent of classifications. Only the Residential building type has reserved origin behaviour.</p></Section>
      <Section id="parking" icon={<SquareParking className="size-5 text-primary" />} title="Edit Parking Specs page" description="Configures parking supply and metadata, separately from driver preference weights."><Table rows={parkingRows} /></Section>
      <Section id="buildings" icon={<Building2 className="size-5 text-primary" />} title="Edit Building Specs page" description="Classifies destinations and redistributes fixed demand; it does not create more people."><Table rows={buildingRows} /><Alert><AlertDescription>Selected and classified does not guarantee reachable. Disconnected destinations can be excluded during run preparation and are reported in Analytics.</AlertDescription></Alert></Section>
      <Section id="simulation" icon={<Play className="size-5 text-primary" />} title="Run Simulation page" description="Combines a saved model with population, time, demand shape, behaviour, and execution settings, then submits an immutable run snapshot to the worker queue."><Topic title="Demand and execution"><Table rows={simulationRows} /></Topic><Topic title="Parking-search choice model"><p>These are non-negative relative coefficients, not percentages, so values may exceed 1.</p><Table rows={parkingChoiceRows} /></Topic><Topic title="Calibration, queue, and history"><p>Locked calibration freezes totals, allocation, classification, date, duration, behaviour, random seed, peak count, width, and harmonics. Early updates use ratios; later runs may use local elasticity or a reliable saturating Hill fit. Browser closure is safe, but Docker and the computer must remain running.</p><Table rows={operationRows} /></Topic></Section>
      <Section id="analytics" icon={<BarChart3 className="size-5 text-primary" />} title="Analytics page" description="Separates requested input from observed output. Choose a standalone run or one calibration group, select its primary iteration, and optionally overlay up to four other runs."><Topic title="Selecting and aligning results"><Table rows={analyticsControlRows} /><p>Reachability warnings mean selected destinations were excluded because SUMO found no pedestrian route. Multiple-run charts use elapsed time when calendar windows differ.</p></Topic><Topic title="Every graph"><div className="grid gap-3 xl:grid-cols-2">{analyticsGraphs.map((graph) => <GraphCard key={graph.title} graph={graph} />)}</div></Topic><Topic title="Detector messages"><p>A <strong>genuine zero</strong> means valid intervals existed but no simulated agent entered. <strong>Entries but no completed traversal</strong> means an E3 saw entry events but not its configured exit; entry flow is still compared, but check direction and lane pairing.</p></Topic><Topic title="Statistics"><Table rows={statisticRows} /></Topic><Topic title="Debug menu"><p>Repeated SUMO errors and warnings are grouped with total count, unique count, and first log line. A completed run may still contain important routing, reachability, detector, or unserved-agent warnings.</p></Topic><Alert className="border-amber-300 bg-amber-50/70 dark:border-amber-800 dark:bg-amber-950/30"><Search className="size-4" /><AlertTitle>Use graphs together</AlertTitle><AlertDescription>Generated input is network-wide, detector flow is location-specific, occupancy is parking-specific, and real data is sensor/time-specific. A credible explanation normally combines several views.</AlertDescription></Alert></Section>
    </div>
    <footer className="py-10 text-center text-xs text-muted-foreground"><Route className="mr-1 inline size-3.5" /> Model geography → specifications → origins → detectors → simulation inputs → analytics validation.</footer>
  </div></main>;
}
