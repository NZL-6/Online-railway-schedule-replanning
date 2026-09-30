# MDP simulation environment

[中文](README_CN.md) | [English](README_EN.md)

`MDP.py` implements the states, action transitions, and rewards described in Sections 4.2–4.5. It uses only the Python standard library.

## Sample and input entry point

`input_structure.json` is a synthetic example showing the five top-level input categories. It is not a command-line configuration file; the environment does not load JSON automatically. The caller converts the data into the corresponding data classes and passes them to:

```python
env = PaperMDP(groups, stocks, plans, route_destinations, parameters)
```

This sample illustrates the data structure only. It does not provide agents, surrogate models, or training procedures.

Field names and enumeration values are case-sensitive. The current interface uses integer minutes for all time fields: for example, 08:00 is `480`, and 01:00 on the next day is `1500`. Demand and capacity use the same unit and are supplied as JSON numbers. Indices are unique nonnegative integers.

## Input fields

### Top-level fields

| Field | Required | Corresponding Python input |
|---|---|---|
| `groups` | Yes | List of `PassengerGroup` objects |
| `stocks` | Yes | List of `RollingStock` objects |
| `plans` | Yes | List of `StopPlan` objects, with `stops` converted to a sequence of `Stop` objects |
| `route_destinations` | Yes | `{integer_route_id: complete_destination_sequence}` |
| `parameters` | Yes | `EnvironmentParameters`, with `weights` converted to `RewardWeights` |

### Passenger groups: `groups[]` → `PassengerGroup`

| Field | Required | Meaning |
|---|---|---|
| `index` | Yes | Unique group index; breaks FIFO ties between equal station-entry times |
| `route` | Yes | Positive integer affected-route identifier; `0` denotes an unaffected route |
| `demand` | Yes | Positive passenger demand |
| `arrival_time` | Yes | Station-entry time |
| `desired_departure_time` | Yes | Original departure time at the target station, no earlier than station entry |
| `destination` | For affected passengers | Destination label belonging to the route in `route_destinations` |
| `leaving_time` | For affected passengers | Potential leaving time, no earlier than station entry |
| `original_destination_arrival` | For affected passengers | Original arrival time at the destination, no earlier than the original departure |

For `route=0`, the last three fields may be omitted or set to `null`; passengers leave according to `desired_departure_time`.

### Rolling stock: `stocks[]` → `RollingStock`

| Field | Required | Meaning |
|---|---|---|
| `index` | Yes | Unique vehicle index used to break equal-priority ties |
| `kind` | Yes | Lowercase `flexible` or `restricted` |
| `capacity` | Yes | Nonnegative capacity available for reassigned passengers |
| `original_departure_time` | Yes | Original departure time at the target station |
| `original_route` | For restricted vehicles | Affected route identifier; may be omitted for flexible vehicles |
| `arrival_time` | For restricted vehicles | Arrival time at the target station; may be omitted for flexible vehicles |

### Stopping plans: `plans[]` → `StopPlan`

| Field | Required | Meaning |
|---|---|---|
| `route` | Yes | Affected route identifier defined in `route_destinations` |
| `name` | Yes | Nonempty plan name; each `(route, name)` pair must be unique |
| `stops` | Yes | Nonempty list of downstream stops in travel order, excluding the target station |

Convert each `stops[]` object to a `Stop`:

| Field | Required | Meaning |
|---|---|---|
| `station` | Yes | Destination label on the route; each station appears at most once per plan |
| `travel_time` | Yes | Cumulative arrival offset from dispatch at the target station, including preceding dwell times; no smaller than the previous station's departure offset |
| `dwell_time` | Yes | Nonnegative dwell time at this station |

For example, an arrival offset of `25` and a dwell time of `2` give a departure offset of `27`. Provide at least one plan for every affected route.

### Route destinations: `route_destinations`

Example: `{"1": ["A", "B"]}`. JSON object keys are strings; convert route keys to integers before passing them to the environment.

List the complete destination set for each route, including destinations with zero current demand. Labels within a route must be unique. The environment sorts route identifiers and station labels to construct `PlanningState.od_keys`.

### Environment parameters: `parameters` → `EnvironmentParameters`

All fields below are required:

| Field | Meaning |
|---|---|
| `start_time` | First decision time |
| `end_time` | Last decision time, no earlier than the start |
| `step` | Positive integer time step that divides `end_time - start_time` |
| `initial_last_departure` | Most recent departure time at initialization, no later than `start_time` |
| `min_headway` | Positive integer minimum headway, in minutes |
| `crowding_threshold` | Nonnegative crowding threshold in passenger units |
| `headway_penalty` | Positive constant for safety-headway penalties |
| `weights` | Complete reward-coefficient object described below |

### Reward coefficients: `parameters.weights` → `RewardWeights`

All fields below are required. The synthetic sample values illustrate the input format only.

| Field | Sign | Associated term |
|---|---|---|
| `alpha1` | ≤ 0 | Unserved demand leaving the station |
| `alpha2` | ≤ 0 | Crowding exposure in passenger-minutes |
| `alpha3` | ≥ 0 | Served demand |
| `alpha4` | ≤ 0 | Passenger-weighted arrival delay |
| `alpha5` | ≤ 0 | Passenger-weighted waiting time |
| `alpha6` | ≤ 0 | Safety-headway penalty |
| `beta1` | ≥ 0 | Cumulative served demand at termination |
| `beta2` | ≥ 0 | Number of dispatched vehicles at termination |
| `beta3` | ≥ 0 | Cumulative crowding exposure at termination; the environment applies the minus sign in the formula |

## Convert the sample to input objects

The following code reads and converts the data only. Use it in a calling script in this directory:

```python
import json
from pathlib import Path
from MDP import (
    PassengerGroup, RollingStock, Stop, StopPlan,
    RewardWeights, EnvironmentParameters,
)

raw = json.loads(Path("input_structure.json").read_text(encoding="utf-8"))
groups = [PassengerGroup(**row) for row in raw["groups"]]
stocks = [RollingStock(**row) for row in raw["stocks"]]
plans = [StopPlan(
    route=row["route"], name=row["name"],
    stops=tuple(Stop(**stop) for stop in row["stops"]),
) for row in raw["plans"]]
route_destinations = {int(route): stations
                      for route, stations in raw["route_destinations"].items()}
parameter_values = dict(raw["parameters"])
parameter_values["weights"] = RewardWeights(**parameter_values["weights"])
parameters = EnvironmentParameters(**parameter_values)
```

## Interfaces and outputs

- `reset()`: starts an episode and returns the states for both agents.
- `observe()`: returns the current states; `available_actions()` returns the available actions.
- `step(dispatch_action, planning_action=None)`: dispatch action `0` means no dispatch and `1` means dispatch. When dispatching, supply `PlanningAction(route=route_id, plan=plan_name)`.
- `StepResult`: includes states before and after the action, both rewards and their components, boarded groups, selected vehicle, arrival and departure times, constraint violations, and the termination flag. Files are not saved automatically.

Vehicle-route matching and capacity are hard rules. Headway and crowding violations are recorded and penalized. Decisions include `end_time`; terminal statistics include the final action, and the final step uses the full `step` duration. Users supply their own decision models.
