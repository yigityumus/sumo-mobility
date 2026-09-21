# Vehicle-flow calibration

This runner finds vehicle inputs that make the SUP simulation detector follow
the Avenue Paul Langevin Monday weekly-average profile. It changes only vehicle
count, dynamically discovered origin allocations, and the eight relative
Fourier amplitudes. Pedestrian demand, buildings, parking choice, date, time,
behavior, Fourier width, harmonics, and the calibration seed remain locked.

## Run it

Start the normal headless application with four simulation workers first. Then,
from the project root:

```bash
cp vehicle_calibration/config.example.json vehicle_calibration/config.json
python3 vehicle_calibration/calibrate.py plan --config vehicle_calibration/config.json
python3 vehicle_calibration/calibrate.py run --config vehicle_calibration/config.json
```

The `plan` command never submits a simulation. The `run` command prints the
complete plan and requires `RUN` confirmation. An intentional non-interactive
start can use `--yes`.

If the terminal closes or you press Ctrl+C, submitted server simulations keep
running. Resume without duplicating completed work:

```bash
python3 vehicle_calibration/calibrate.py resume --config vehicle_calibration/config.json
```

Retry candidates that exhausted their automatic retry after a failed run or an
incomplete detector file:

```bash
python3 vehicle_calibration/calibrate.py resume --config vehicle_calibration/config.json --retry-failed
```

Rebuild CSV, best-payload, and report files without submitting simulations:

```bash
python3 vehicle_calibration/calibrate.py analyze --config vehicle_calibration/config.json
```

## Execution strategy

The supplied configuration performs:

- 24 vehicle-volume and entry-allocation simulations;
- 32 relative Fourier-shape simulations;
- 16 joint-refinement simulations;
- 12 validation simulations: four finalists under three additional seeds.

The total is 84 new simulations. Initial designs and validation seeds are
preplanned, so a finished job is immediately replaced while pending independent
work remains. Every adaptive batch contains four candidates and waits for all
four results before choosing the next four, because that choice depends on the
newly measured errors.

Initial candidates use a deterministic low-discrepancy Halton design. Later
batches use a Gaussian-process surrogate and expected improvement. The script
imports compatible results from the earlier OFAT study as prior observations,
but it accepts only results with all 48 aligned vehicle intervals. Missing
detector output is retried and is never interpreted as zero flow.

Origin count is not hard-coded. If entry points are added or removed, a new
calibration discovers the current origins and constructs allocations whose
shares always total 100%. An existing checkpoint intentionally refuses to
resume after such a model change.

## Objective

The default objective gives graph shape the highest priority:

```text
J = 0.50 × normalized shape RMSE
  + 0.30 × pointwise NRMSE
  + 0.15 × volume error
  + 0.05 × peak-timing error
```

Fourier amplitudes are constrained to an average of 100%, so they control the
relative departure shape while `vehicle_count` controls demand volume.

## Files

The output directory contains:

- `state.json`: atomic resume checkpoint, payloads, run IDs, attempts and scores;
- `results/*.json`: extracted analytics and calibration score per candidate;
- `candidates.csv`: inputs, errors, timings and status for every candidate;
- `vehicle_timeseries.csv`: all 15-minute simulated vehicle profiles;
- `best_parameters.json`: selected count, origin shares and peak amplitudes;
- `best_payload.json`: complete simulation API payload for the selected result;
- `report.md`: ranked candidates and multi-seed validation summary.

Changing the model, detector, origins, accessible buildings or parking network
changes the response surface. Start a new output directory after such changes.
