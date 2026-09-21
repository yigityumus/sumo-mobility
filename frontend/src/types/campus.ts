import type { Feature, FeatureCollection, Geometry } from "geojson";

export type JsonObject = Record<string, unknown>;
export type CampusFeatureProperties = Record<string, unknown>;
export type CampusFeature = Feature<Geometry, CampusFeatureProperties> & {
  id?: string | number;
};
export type CampusFeatureCollection = FeatureCollection<Geometry, CampusFeatureProperties>;

export type CampusBoundaryFeature = CampusFeature | null;

export type RequestInfo = {
  source?: "overpass" | "upload" | "saved-model" | string;
  endpoint?: string;
  cacheHit?: boolean;
  filename?: string;
  modelName?: string;
  stats?: unknown;
  [key: string]: unknown;
};

export type ParkingSpec = {
  access?: string | null;
  accessSource?: string | null;
  capacity?: number | null;
  capacitySource?: string | null;
  capacityMethod?: Record<string, any> | null;
  originalCapacity?: number | null;
  originalCapacitySource?: string | null;
  internalRoads?: "not_checked" | "not_found" | string[];
  changeDate?: string | null;
  [key: string]: unknown;
};

export type ParkingSpecsById = Record<string, ParkingSpec>;

export type BuildingClassificationType = {
  id: string;
  name: string;
  createdAt?: string;
  updatedAt?: string;
};

export type BuildingClassificationDemandDistribution = {
  pedestrian: number;
  vehicle: number;
};

export type BuildingClassification = {
  id: string;
  name: string;
  types: BuildingClassificationType[];
  assignments: Record<string, string>;
  demandDistribution?: Record<string, BuildingClassificationDemandDistribution>;
  createdAt?: string;
  updatedAt?: string;
};

export type ParkingClassification = Omit<BuildingClassification, "demandDistribution">;

export type DetectorLaneCandidate = {
  lane_id: string;
  edge_id: string;
  lane_index: number;
  position_metres: number;
  distance_metres: number;
  lane_length_metres: number;
  edge_name: string;
  heading_degrees: number;
  allows_passenger: boolean;
  allows_pedestrian: boolean;
  shape: Array<{ longitude: number; latitude: number }>;
  snapped: { longitude: number; latitude: number };
};

export type DetectorLaneSelection = {
  mode: "lane" | "edge_all" | "lanes";
  edgeId: string;
  laneId?: string;
  laneIndex?: number;
  laneIds?: string[];
};

export type DetectorPoint = {
  location: { longitude: number; latitude: number };
  laneSelection: DetectorLaneSelection;
};

export type E1Detector = DetectorPoint & {
  id: string;
  name: string;
  type: "e1";
  periodSeconds: number;
};

export type E3Detector = {
  id: string;
  name: string;
  type: "e3";
  periodSeconds: number;
  detects?: Array<"vehicles" | "pedestrians">;
  entry: DetectorPoint;
  exit: DetectorPoint;
};

export type TrafficDetector = E1Detector | E3Detector;

export type PublicTransportOrigin = {
  id: string;
  name: string;
  sourceType: "building" | "point";
  location: { longitude: number; latitude: number };
  buildingId?: string;
};

export type VehicleGenerationPoint = {
  id: string;
  name: string;
  location: { longitude: number; latitude: number };
  positionMetres: number;
  laneSelection: DetectorLaneSelection & {
    mode: "lane";
    laneId: string;
  };
};

export type VehicleOriginAllocation = {
  origin_id: string;
  origin_name?: string;
  vehicle_count: number;
  percentage?: number;
};

export type CampusModel = {
  id: string;
  name: string;
  createdAt?: string | null;
  updatedAt?: string | null;
  dataSourceLabel?: string;
  requestInfo?: RequestInfo | null;
  boundaryFeature?: CampusBoundaryFeature;
  buildings?: CampusFeatureCollection;
  parkingAreas?: CampusFeatureCollection;
  selectedBuildingIds?: string[];
  selectedParkingIds?: string[];
  parkingSpecs?: ParkingSpecsById;
  buildingClassifications?: BuildingClassification[];
  parkingClassifications?: ParkingClassification[];
  detectors?: TrafficDetector[];
  publicTransportOrigins?: PublicTransportOrigin[];
  vehicleGenerationPoints?: VehicleGenerationPoint[];
  sourceOsmFilename?: string;
  sourceOsmIsUploaded?: boolean;
  sourceOsmCached?: boolean;
  sourceOsmBlob?: Blob | File | null;
};

export type ModelExportOptions = {
  osm: boolean;
  buildings: boolean;
  parkingAreas: boolean;
  modelConfig: boolean;
};

export type CampusFeaturesPayload = {
  features?: {
    buildings?: CampusFeatureCollection;
    parking_areas?: CampusFeatureCollection;
    parkingAreas?: CampusFeatureCollection;
  };
  osm?: unknown;
  boundary?: CampusFeature;
  stats?: unknown;
  endpoint?: string;
  cache_hit?: boolean;
};

export type LoadProgressStepStatus = "pending" | "active" | "complete" | "error";

export type LoadProgressStep = {
  id: string;
  label: string;
  status: LoadProgressStepStatus;
  startedAt: number | null;
  completedAt: number | null;
};

export type LoadProgressState = {
  status: "idle" | "running" | "complete" | "error";
  steps: LoadProgressStep[];
  startedAt: number | null;
  completedAt: number | null;
  errorMessage?: string | null;
};

export type SimulationMode = "sumo" | "sumo-gui";
export type TrafficModel = "constant" | "linear" | "normal" | "fourier";
export type PedestrianModel = "striping" | "nonInteracting";

export type SimulationQueueStatus = {
  concurrency: number;
  running_count: number;
  waiting_count: number;
  available_slots: number;
};

export type FourierTrafficParameters = {
  peak_count: number;
  peak_width_hours: number;
  harmonics: number;
  peak_heights: number[];
};

export type ParkingChoiceWeights = {
  drive_time: number;
  walk_time: number;
  capacity: number;
  absolute_free_space: number;
  relative_free_space: number;
};

export type ParkingChoiceParameters = {
  knowledge_probability: number;
  uninformed_occupancy_mean: number;
  uninformed_occupancy_stddev: number;
  frustration_step: number;
  stochastic_scale: number;
  weights: ParkingChoiceWeights;
};

export type CalibrationSubject = "vehicles" | "pedestrians";

export type FlowCalibrationMetrics = {
  mae_flow_per_hour: number;
  rmse_flow_per_hour: number;
  normalized_mae: number;
  normalized_rmse: number;
  volume_error: number;
  correlation: number;
  shape_error: number;
  mean_bias_flow_per_hour: number;
  normalized_bias: number;
  mean_absolute_percentage_error: number;
  symmetric_mean_absolute_percentage_error: number;
  nash_sutcliffe_efficiency: number;
  real_mean_flow_per_hour: number;
  simulation_mean_flow_per_hour: number;
  peak_count: number;
  peak_spacing_seconds: number;
};

export type FlowCalibrationPeakResult = {
  peak_index: number;
  window_start_seconds: number;
  window_end_seconds: number;
  center_seconds: number;
  real_flow_per_hour: number;
  simulation_flow_per_hour: number;
  raw_ratio: number | null;
  applied_ratio: number | null;
  ratio_capped: boolean;
  adjustment_quantized?: boolean;
  old_percentage: number;
  proposed_percentage?: number;
  new_percentage: number;
  step_percentage?: number;
  update_method?: "proportional" | "local_elasticity" | "hill" | "undefined_zero_flow";
  estimated_elasticity?: number | null;
  hill_model?: {
    baseline: number;
    maximum: number;
    half_saturation_percentage: number;
    hill_coefficient: number;
    r_squared: number;
    squared_error: number;
  } | null;
  predicted_next_flow_per_hour?: number | null;
  residual_flow_per_hour?: number;
  absolute_error_flow_per_hour?: number;
  percentage_error?: number | null;
};

export type FlowCalibrationRunMetadata = {
  id: string;
  name: string;
  iteration: number;
  total_iterations: number;
  source_id: string;
  detector_logical_id: string;
  subjects: CalibrationSubject[];
  step_percentage?: number;
  update_strategy?: "adaptive_hill";
  profiles: Record<CalibrationSubject, FourierTrafficParameters>;
  result: {
    subjects: Partial<Record<CalibrationSubject, {
      metrics: FlowCalibrationMetrics;
      peaks: FlowCalibrationPeakResult[];
    }>>;
  } | null;
};

export type FlowCalibrationSession = {
  id: string;
  name: string;
  model_id: string;
  model_name: string;
  status: "running" | "completed" | "failed";
  source_id: string;
  detector_logical_id: string;
  subjects: CalibrationSubject[];
  total_iterations: number;
  step_percentage?: number;
  update_strategy?: "adaptive_hill";
  completed_iterations: number;
  run_ids: string[];
  failure_reason?: string | null;
  created_at: string;
  updated_at: string;
};

export type SimulationParkingSnapshot = {
  id: string;
  model_parking_id: string;
  osm_way_id: number;
  name: string;
  configured_capacity?: number | null;
  generated_capacity?: number | null;
  capacity_source?: string;
};

export type SimulationRun = {
  id: string;
  model_id: string;
  model_name: string;
  status: "queued" | "running" | "completed" | "failed";
  queue_position?: number | null;
  queued_ahead?: number | null;
  vehicle_count: number;
  pedestrian_count: number;
  total_people?: number;
  vehicle_percentage?: number | null;
  building_classification_id?: string | null;
  residential_pedestrian_count?: number;
  public_transport_pedestrian_count?: number;
  parked_car_pedestrian_count?: number;
  pedestrian_source_counts?: {
    residential: number;
    public_transport: number;
    parked_cars: number;
  };
  person_based_demand?: boolean;
  duration_hours: number;
  duration_seconds: number;
  simulation_start_at?: string | null;
  simulation_end_at?: string | null;
  simulation_timezone?: string | null;
  mode: SimulationMode;
  pedestrian_model?: PedestrianModel;
  diagnostic_tracing?: boolean;
  random_seed?: number;
  parking_choice?: ParkingChoiceParameters;
  vehicle_traffic_model?: TrafficModel;
  pedestrian_traffic_model?: TrafficModel;
  vehicle_fourier_parameters?: FourierTrafficParameters;
  pedestrian_fourier_parameters?: FourierTrafficParameters;
  progress_percent?: number;
  progress_phase?:
    | "queued"
    | "queue_failed"
    | "preparing_snapshot"
    | "building_network"
    | "configuring_parking"
    | "configuring_scenario"
    | "configuring_detectors"
    | "resolving_access"
    | "generating_demand"
    | "writing_configuration"
    | "starting_sumo"
    | "demand"
    | "finishing"
    | "finalizing"
    | "completed"
    | "interrupted";
  simulated_seconds?: number;
  estimated_remaining_seconds?: number | null;
  planned_agents?: number;
  completed_agents?: number;
  remaining_agents?: number;
  active_agents?: number;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  message?: string | null;
  failure_reason?: string | null;
  stop_requested_at?: string | null;
  output_directory?: string | null;
  log_tail?: string | null;
  parking_area_count?: number;
  parking_areas?: SimulationParkingSnapshot[];
  detector_count?: number;
  detectors?: unknown[];
  building_destination_count?: number;
  public_transport_origin_count?: number;
  vehicle_generation_point_count?: number;
  vehicle_origin_allocations?: VehicleOriginAllocation[];
  excluded_building_destination_count?: number;
  pedestrian_accessible_parking_count?: number;
  calibration?: FlowCalibrationRunMetadata | null;
};

export type SimulationRunRequest = {
  vehicle_count: number;
  pedestrian_count: number;
  total_people: number;
  vehicle_percentage: number;
  building_classification_id?: string | null;
  residential_pedestrian_count: number;
  public_transport_pedestrian_count: number;
  duration_hours: number;
  simulation_start_at: string;
  simulation_timezone: string;
  mode: SimulationMode;
  pedestrian_model: PedestrianModel;
  diagnostic_tracing: boolean;
  random_seed?: number;
  vehicle_traffic_model: TrafficModel;
  pedestrian_traffic_model: TrafficModel;
  vehicle_fourier_parameters: FourierTrafficParameters;
  pedestrian_fourier_parameters: FourierTrafficParameters;
  parking_choice: ParkingChoiceParameters;
  vehicle_origin_allocations?: VehicleOriginAllocation[];
};

export type AnalyticsRun = {
  id: string;
  model_id: string;
  model_name: string;
  status: string;
  message?: string | null;
  failure_reason?: string | null;
  created_at: string;
  completed_at?: string | null;
  mode: SimulationMode;
  vehicle_count: number;
  pedestrian_count: number;
  total_people?: number;
  vehicle_percentage?: number | null;
  building_classification_id?: string | null;
  residential_pedestrian_count?: number;
  public_transport_pedestrian_count?: number;
  parked_car_pedestrian_count?: number;
  pedestrian_source_counts?: {
    residential: number;
    public_transport: number;
    parked_cars: number;
  };
  building_destination_count?: number;
  excluded_building_destination_count?: number;
  pedestrian_accessible_parking_count?: number;
  duration_hours: number;
  duration_seconds: number;
  simulation_start_at?: string | null;
  simulation_end_at?: string | null;
  simulation_timezone?: string | null;
  vehicle_traffic_model: TrafficModel;
  pedestrian_traffic_model: TrafficModel;
  vehicle_fourier_parameters: FourierTrafficParameters;
  pedestrian_fourier_parameters: FourierTrafficParameters;
  random_seed?: number;
  parking_choice?: ParkingChoiceParameters;
  vehicle_origin_allocations?: VehicleOriginAllocation[];
  parking_area_count: number;
  parking_areas: SimulationParkingSnapshot[];
  detector_count?: number;
  detectors?: unknown[];
  calibration?: FlowCalibrationRunMetadata | null;
  availability: {
    occupancy: boolean;
    search_times: boolean;
    trip_segments: boolean;
    debug: boolean;
    detectors: boolean;
  };
};

export type SimulationLogEntry = {
  message: string;
  count: number;
  first_line: number;
};

export type SimulationLogSection = {
  total: number;
  unique: number;
  entries: SimulationLogEntry[];
};

export type ParkingResultOption = {
  id: string;
  name: string;
  capacity: number;
};

export type ParkingOccupancyPoint = {
  time_seconds: number;
  capacity: number;
  occupied: number;
  unoccupied: number;
  occupied_percent: number;
  unoccupied_percent: number;
};

export type SearchTimePoint = {
  time_seconds: number;
  average_search_seconds: number;
  vehicle_count: number;
};

export type ParkingAttemptPoint = {
  attempt_count: number;
  vehicle_count: number;
  percentage: number;
};

export type ParkingDestinationAnalysis = {
  available: boolean;
  outcomes_available: boolean;
  summary: {
    planned_vehicle_people: number;
    parked_people: number;
    unserved_people: number;
    without_parking_outcome: number;
    unused_parking_areas: number;
    destination_buildings: number;
    buildings_receiving_drivers: number;
  };
  parkings: Array<{
    id: string;
    name: string;
    candidate_people: number;
    initial_choice_people: number;
    parked_people: number;
    rerouted_in_people: number;
    rerouted_out_people: number;
    unserved_after_initial_people: number;
    destination_building_count: number;
    eligible_destination_building_count: number;
    pedestrian_access_available: boolean | null;
    unused_reason: string | null;
  }>;
  buildings: Array<{
    id: string;
    name: string;
    planned_vehicle_people: number;
    parked_people: number;
    unserved_people: number;
    without_parking_outcome: number;
    parking_area_count: number;
    vehicle_weight: number;
    eligible_parking_area_count: number;
    zero_driver_reason: string | null;
  }>;
  parking_building_flows: Array<{
    parking_id: string;
    parking_name: string;
    building_id: string;
    building_name: string;
    parked_people: number;
  }>;
};

export type VehicleJourneySegmentType =
  | "to_parking"
  | "inside_parking"
  | "between_parkings"
  | "parked";

export type VehicleJourneySegmentPoint = {
  time_seconds: number;
  segment_type: VehicleJourneySegmentType;
  parking_id: string;
  average_duration_seconds: number;
  segment_count: number;
  vehicle_count: number;
};

export type VehicleJourneySegmentSummary = {
  segment_type: VehicleJourneySegmentType;
  parking_id: string;
  segment_count: number;
  vehicle_count: number;
  average_seconds: number;
  median_seconds: number;
  p95_seconds: number;
  maximum_seconds: number;
};

export type RealWorldSource = {
  id: string;
  segment_id: string;
  name: string;
  street: string;
  city: string;
  files: string[];
  start_at: string;
  end_at: string;
  observation_count: number;
  interval_seconds: number;
};

export type RealWorldSeries = {
  source: Pick<RealWorldSource, "id" | "segment_id" | "name" | "street" | "city" | "files">;
  mode: "raw" | "weekly_average";
  subject: "vehicles" | "pedestrians";
  duration_seconds: number;
  interval_seconds: number;
  start_at: string | null;
  start_weekday: number | null;
  start_time_seconds: number | null;
  units: "agents_per_hour";
  points: Array<{
    time_seconds: number;
    flow_per_hour: number;
    interval_count: number;
    sample_count: number;
    observed_at?: string;
    weekday?: number;
    time_of_day_seconds?: number;
  }>;
};

export type AnalyticsData = {
  schema_version?: number;
  run: AnalyticsRun;
  parkings: ParkingResultOption[];
  occupancy: Record<string, ParkingOccupancyPoint[]>;
  search_times: {
    points: SearchTimePoint[];
    summary: {
      vehicle_count: number;
      average_seconds: number;
      median_seconds: number;
      p95_seconds: number;
      maximum_seconds: number;
    };
  };
  parking_attempts?: {
    available: boolean;
    distribution: ParkingAttemptPoint[];
    summary: {
      vehicle_count: number;
      average_attempts: number;
      maximum_attempts: number;
      vehicles_using_fallback: number;
      fallback_percentage: number;
      unserved_vehicle_count: number;
    };
  };
  parking_destinations?: ParkingDestinationAnalysis;
  trip_segments: {
    available: boolean;
    points: VehicleJourneySegmentPoint[];
    summaries: VehicleJourneySegmentSummary[];
    parkings: Array<{ id: string; name: string }>;
    segment_types: VehicleJourneySegmentType[];
  };
  detectors: {
    available: boolean;
    definitions: Array<{
      id: string;
      logical_id: string;
      logical_name: string;
      label: string;
      type: "e1" | "e2" | "e3";
      subject?: "vehicles" | "pedestrians";
      lane_id?: string;
      edge_id?: string;
      lane_index?: number;
      period_seconds: number;
      entries?: Array<{ lane_id: string; edge_id: string; lane_index: number; position_metres: number }>;
      exits?: Array<{ lane_id: string; edge_id: string; lane_index: number; position_metres: number }>;
      physical_detectors?: Array<{
        id: string;
        lane_id: string;
        edge_id: string;
        lane_index: number;
        start_position_metres: number;
        end_position_metres: number;
      }>;
    }>;
    series: Record<string, Array<{
      begin_seconds: number;
      end_seconds: number;
      vehicle_count: number;
      flow_vehicles_per_hour: number;
      entry_count: number;
      entry_flow_per_hour: number;
      occupancy_percent: number;
      mean_speed_metres_per_second: number;
      mean_travel_time_seconds?: number;
      mean_halts_per_vehicle?: number;
      mean_time_loss_seconds?: number;
      vehicles_within?: number;
    }>>;
    comparison_interval_seconds: number;
    comparison_series: Record<string, Array<{
      begin_seconds: number;
      end_seconds: number;
      interval_count: number;
      flow_per_hour: number;
    }>>;
  };
  debug: {
    log_available: boolean;
    warnings: SimulationLogSection;
    errors: SimulationLogSection;
  };
};
