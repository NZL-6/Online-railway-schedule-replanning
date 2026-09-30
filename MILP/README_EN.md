# Appendix C MILP

[中文](README_CN.md) | [English](README_EN.md)

`MILP.py`: a full-information model for rolling-stock dispatching, stopping-plan selection, and passenger reassignment.

## Samples and execution

`input_structure.json` demonstrates flexible and restricted rolling stock, affected and unaffected passenger groups, multiple stopping plans, and settings. All values are synthetic. `example.json` provides a smaller input example.

**With JSON input, a single file containing the fields below supplies all data required by the MILP. No CSV, Excel files, agents, surrogate models, or trained weights are required.** Execution also requires Python 3.12, Gurobi, and a valid license.

Run from this directory:

```bash
python -m pip install -r requirements.txt
python MILP.py --input input_structure.json --inspect
python MILP.py --input input_structure.json --output results/sample
```

Replace the path after `--input` with your own JSON file. `--inspect` checks inputs only; the last command builds and solves the model. The `--output` directory must not already exist.

## Input fields

Field names and enumeration values are case-sensitive. All times are in minutes: for example, 08:00 is `480`, and 01:00 on the next day is `1500`, not an `HHMM` value. Demand and capacity must use the same unit; use integer passenger counts for the paper's demand definition. Numeric values may be JSON numbers or decimal strings. Identifiers are integers, except vehicle `id`, which is a string.

### Top-level fields

| Field | Required | Structure |
|---|---|---|
| `times` | Yes | A nonempty list of strictly increasing, unique decision times |
| `stocks` | Yes | List of rolling-stock objects |
| `groups` | Yes | List of passenger-group objects |
| `plans` | Yes | List of stopping-plan objects |
| `settings` | No; recommended | Environmental thresholds and objective weights; omitted values use the defaults below |

### Rolling stock: `stocks[]`

| Field | Required | Meaning |
|---|---|---|
| `id` | Yes | Unique vehicle identifier, such as `F1` or `R1`; equal-priority vehicles are ordered by this string |
| `kind` | Yes | `Flexible` or `Restricted` |
| `capacity` | Yes | Nonnegative capacity available for reassigned passengers |
| `original_departure` | No; recommended | Original departure time at the target station; defaults to `0` and determines selection order among flexible vehicles |
| `route` | For restricted vehicles | Affected route identifier matching `plans[].route`; may be omitted for flexible vehicles |
| `arrival` | For restricted vehicles | Arrival time at the target station; the vehicle becomes available strictly after this time; may be omitted for flexible vehicles |

### Passenger groups: `groups[]`

| Field | Required | Meaning |
|---|---|---|
| `id` | Yes | Unique integer identifier; breaks ties between equal station-entry times |
| `route` | Yes | Affected route identifier; `0` denotes unaffected passengers |
| `destination` | Yes | Destination label matching the station labels in stopping plans |
| `weight` | Yes | Positive passenger demand |
| `enter` | Yes | Station-entry time |
| `leave` | Yes | Potential leaving time for affected passengers; retain this numeric field for `route=0`, although presence is then determined using `original_departure` |
| `original_departure` | Yes | Original departure time at the target station |
| `original_arrival` | For affected passengers | Original arrival time at the destination; may be `null` or omitted for `route=0` |

Affected groups are present during `[enter, leave)`; unaffected groups during `[enter, original_departure)`. Passengers can only be assigned to plans on their route that stop at their destination.

### Stopping plans: `plans[]`

| Field | Required | Meaning |
|---|---|---|
| `route` | Yes | Positive integer route identifier |
| `id` | Yes | Integer plan identifier; each `(route, id)` pair must be unique |
| `arrival` | Yes | `{station_label: arrival_offset_in_minutes}` |
| `departure` | Yes | `{station_label: departure_offset_in_minutes}`, with the same station keys as `arrival` |

Offsets are measured from departure at the target station and include preceding running and dwell times; they are not individual segment durations. For example, `arrival.A=10` and `departure.A=12` mean arrival at A 10 minutes after dispatch and departure from A 12 minutes after dispatch. Include only downstream stations served by the plan. Arrival offsets must be nonnegative, and departure offsets must be no smaller than the corresponding arrival offsets.

### Settings: `settings`

| Field | Required | Default | Meaning |
|---|---|---:|---|
| `headway` | No | 5 | Minimum safety headway, in minutes |
| `crowd_limit` | No | 1500 | Maximum in-station passenger count |
| `service_weight` | No | 1 | Benefit coefficient for served demand |
| `waiting_weight` | No | 0.001 | Cost coefficient for passenger-weighted waiting time |
| `delay_weight` | No | 0.00001 | Cost coefficient for passenger-weighted arrival delay |

The objective is `service_weight × served demand − waiting_weight × weighted waiting − delay_weight × weighted delay`. Replace the defaults and synthetic sample values with your own settings. MDP reward parameters are not required.

Crowding options:

- `--crowding appendix-c`: the default; uses the printed Appendix C expression, subtracting all previously served demand from baseline occupancy.
- `--crowding state-consistent`: uses the current unserved in-station demand from Eq. (13). The definitions are not equivalent; the selected convention is recorded in the results.

## Optional: original-format data adapter

If you already have data in the original format, run:

```bash
python MILP.py --data-dir path/to/data --passenger-file passengers.csv --output results/case1
```

Use this mode or JSON input, not both. The directory must contain the passenger CSV, `scenario.txt`, `Rolling_stock.txt`, `stop_plan_times.csv`, and `Origin_timetable.xlsx`. `--arrival-overrides arrivals.json` accepts a mapping of `{group_id: original_destination_arrival_in_minutes}`.

## Outputs

`--output` specifies a new directory. If omitted, results are saved to `results/<timestamp>/` beside the script.

| File | Contents |
|---|---|
| `summary.json` | Solver status, objective value, bound, gap, runtime, and validation status |
| `validation.json` | Independent replay validation and details; generated when a solution exists |
| `selected_actions.csv` | Dispatched vehicles, routes, plans, times, and served demand |
| `assignments.csv` | Passenger-group assignments, waiting, and delay |
| `crowding.csv` | Crowding at each decision time under both definitions |
| `gurobi.log` | Solver log |
| `infeasibility.ilp` | Irreducible inconsistent subsystem (IIS), generated when the model is proven infeasible |
| `model.lp` | Model exported when `--write-model` is specified |

Solution CSV files are generated only after independent validation passes. Check `status_name`, `mip_gap`, and `validation_passed` together. `TIME_LIMIT` means the solver reached its time limit.

Other options: `--time-limit` (solver time in seconds), `--threads` (thread count), and `--mip-gap` (relative optimality tolerance). See `--help` for all options.

## Python API

```python
from MILP import load_json, build_model, validate_solution

instance = load_json("example.json")  # Specify the input file here.
built = build_model(instance, crowding="appendix-c")
try:
    built.model.optimize()
    if built.model.SolCount:
        result = validate_solution(built)
        print(result["passed"], result["objective"])
finally:
    built.model.dispose()
```
