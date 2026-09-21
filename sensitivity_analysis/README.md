# Resumable sensitivity analysis

This folder contains a dependency-free, one-factor-at-a-time (OFAT) study runner for the SUMO application. It does not start anything until you explicitly use the `run` command and confirm the printed plan.

## Quick start

From the project root:

```bash
cp sensitivity_analysis/config.example.json sensitivity_analysis/config.json
python3 sensitivity_analysis/sensitivity.py plan --config sensitivity_analysis/config.json
python3 sensitivity_analysis/sensitivity.py run --config sensitivity_analysis/config.json
```

Start the normal headless stack first (`make docker-run`, or your usual non-GUI startup command). The `plan` command only reads the API and writes `plan.csv`; it does not submit simulations. The `run` command prints the same plan and asks you to type `RUN` before it submits anything. Use `--yes` only when you intentionally want a non-interactive start.

If the terminal or script is interrupted, simulations already submitted to the server continue. Restart only the unfinished work with:

```bash
python3 sensitivity_analysis/sensitivity.py resume --config sensitivity_analysis/config.json
```

Failed cases are not silently repeated. To retry them as new runs:

```bash
python3 sensitivity_analysis/sensitivity.py resume --config sensitivity_analysis/config.json --retry-failed
```

Rebuild CSV files and mathematical fits without starting simulations:

```bash
python3 sensitivity_analysis/sensitivity.py analyze --config sensitivity_analysis/config.json
```

## What is tested

Every design point changes one parameter from the baseline and restores every other setting to the baseline. The baseline run is shared across experiments, so identical runs are not paid for repeatedly.

- Each of the 8 vehicle Fourier peak amplitudes.
- Each of the 8 pedestrian Fourier peak amplitudes.
- Residential pedestrians while total independent pedestrians remain fixed.
- Vehicle count while independent pedestrians remain fixed.
- Every saved vehicle entry point discovered from the model. When one entry's share changes, the remaining percentage is divided equally among all other current entries.
- Every parking-search choice parameter.

The entry-point count is never hard-coded. With four entries, the baseline is 25% each. If entries are added or removed later, a new study automatically uses equal shares across the new set.

Ranges can be written as `minimum`, `maximum`, and `step`, or as an explicit `values` / `values_percent` list. The baseline value is added automatically even if the selected step does not land on it.

`other_peaks_percent` controls the non-tested peaks during a Fourier experiment. It is `100` in the supplied baseline-consistent configuration. Set it to `50` if you specifically want the experiment described as “one peak varies while all seven others remain at 50%”; that is a different experimental baseline and will require a new output directory.

## Progress and recovery

The study directory contains:

- `state.json`: atomic checkpoint with every payload, server run ID, status, timestamps, duration, and attempt.
- `config.snapshot.json` and `model_context.json`: the exact study settings and resolved model/origin/detector identities.
- `results/*.json`: compact analytics extracted from each completed run.
- `plan.csv`: every requested design point and the deduplicated run that supplies it.
- `runs.csv`: one row per actual simulation, including queue time and execution time.
- `detector_timeseries.csv`: detector output for every interval and run.
- `metrics.csv`: normalized detector, parking, search, and real-world error metrics.
- `effects.csv`: parameter ranges, local slopes, elasticities, and monotonicity.
- `response_models.csv`: linear, quadratic, and Hill fits with R² and AICc.
- `report.md`: a compact ranked summary.

The terminal progress line reports completed, failed, running, queued, planned, total, and an ETA based on measured durations from this study. `max_in_flight` defaults to 4, matching the current worker limit, and is configurable.

## Interpreting equations

For each numeric output metric the analyzer fits:

- linear: `y = a + b*x`
- quadratic: `y = a + b*x + c*x^2`
- Hill: `y = y0 + vmax*x^n/(k_half^n + x^n)`

The lowest finite AICc is marked as the best descriptive model. A Hill curve is useful only when the response is genuinely monotonic and saturating. Route changes, parking spillover, congestion, and detector placement can produce thresholds or non-monotonic responses, so the script also reports Spearman monotonicity and does not force a Hill equation.

Equations are fitted both to whole-run detector summaries and to every detector time interval. The interval fits are what let you ask, for example, “if vehicle peak 1 rises by 50 percentage points, what happens at this detector around 07:45?” Effects can only be measured at saved detectors; add detectors before starting a new study if you need coverage of more campus roads.

With one replicate, differences are deterministic only while choice randomness is zero and the seed is fixed. For non-zero `stochastic_scale`, increase `replicates` (for example to 3 or 5) before starting a new study.

## Model changes

The plan records a fingerprint of the saved model, its classifications, origins, and detectors. If the model changes while a study is in progress, resume stops rather than mixing incompatible results. Change `study_name` and `output_directory` to start a new comparable study after fixing building reachability.
