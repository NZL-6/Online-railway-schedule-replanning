"""MDP environment described in Sections 4.2–4.5 of the paper.

Input: the caller constructs the following five components and passes them to PaperMDP:
    groups: PassengerGroup sequence containing passenger demand and times.
    stocks: RollingStock sequence containing vehicle types, capacities, and times.
    plans: StopPlan sequence containing routes and downstream Stop arrival offsets and dwell times.
    route_destinations: {route_id: complete destination sequence}, including destinations with zero demand.
    parameters: EnvironmentParameters containing the decision grid, initial time, thresholds, and reward coefficients.

Usage (see README_CN.md / README_EN.md for the input schema):
    env = PaperMDP(groups, stocks, plans, route_destinations, parameters)
    observation = env.reset()
    result = policy_step(env, my_dispatch_policy, my_planning_policy)

Output: StepResult with before/after states, rewards and components, boarded groups, vehicle, service times, and violations.
The current interface uses integer minutes; demand and capacity use Decimal, and rewards use float.
Decisions include end_time. Terminal counts include the final action, and the final step uses a full step interval.
Headway and crowding violations incur reward penalties; vehicle matching and capacity are enforced as hard rules.
See DispatchPolicy / PlanningPolicy for model interfaces. The caller must replace the placeholder functions.
This module does not read or write data files and does not include training or the Appendix F extension.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import exp, isfinite
from typing import Literal, Mapping, Protocol, Sequence


def _quantity(value: Decimal | int | float, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite, nonnegative quantity")
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or not isfinite(float(result)):
        raise ValueError(f"{name} must be a finite, nonnegative quantity representable as a float")
    return result


def _finite(value: float, name: str) -> None:
    if isinstance(value, bool) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def _index(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer index")


@dataclass(frozen=True)
class PassengerGroup:
    index: int
    route: int
    demand: Decimal | int | float
    arrival_time: int
    desired_departure_time: int
    destination: str | None = None
    leaving_time: int | None = None
    original_destination_arrival: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "demand", _quantity(self.demand, "demand"))


@dataclass(frozen=True)
class RollingStock:
    index: int
    kind: Literal["flexible", "restricted"]
    capacity: Decimal | int | float
    original_departure_time: int
    original_route: int | None = None
    arrival_time: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "capacity", _quantity(self.capacity, "capacity"))


@dataclass(frozen=True)
class Stop:
    station: str
    travel_time: int
    dwell_time: int


@dataclass(frozen=True, order=True)
class PlanningAction:
    route: int
    plan: str


@dataclass(frozen=True)
class StopPlan:
    route: int
    name: str
    stops: tuple[Stop, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "stops", tuple(self.stops))

    @property
    def action(self) -> PlanningAction:
        return PlanningAction(self.route, self.name)


@dataclass(frozen=True)
class RewardWeights:






    alpha1: float
    alpha2: float
    alpha3: float
    alpha4: float
    alpha5: float
    alpha6: float
    beta1: float
    beta2: float
    beta3: float

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            _finite(value, name)
            negative = name in {"alpha1", "alpha2", "alpha4", "alpha5", "alpha6"}
            if (negative and value > 0) or (not negative and value < 0):
                raise ValueError(f"{name} has a sign inconsistent with its reward or penalty direction")


@dataclass(frozen=True)
class EnvironmentParameters:
    start_time: int
    end_time: int
    step: int
    initial_last_departure: int
    min_headway: int
    crowding_threshold: Decimal | int | float
    headway_penalty: float
    weights: RewardWeights

    def __post_init__(self) -> None:
        object.__setattr__(self, "crowding_threshold",
                           _quantity(self.crowding_threshold, "crowding_threshold"))
        for name in ("start_time", "end_time", "step", "initial_last_departure", "min_headway"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer number of minutes")
        if self.step <= 0 or self.min_headway <= 0 or self.end_time < self.start_time:
            raise ValueError("Time step and minimum headway must be positive; end_time must not precede start_time")
        if (self.end_time - self.start_time) % self.step:
            raise ValueError("end_time must lie on the decision grid")
        if self.initial_last_departure > self.start_time:
            raise ValueError("Initial most recent departure must not be later than start_time")
        _finite(self.headway_penalty, "headway_penalty")
        if self.headway_penalty <= 0:
            raise ValueError("headway_penalty must be positive")


@dataclass(frozen=True)
class DispatchState:
    crowdedness: Decimal
    epd: Decimal
    available_stock_count: int
    potential_stock_count: int
    time: int

    def as_vector(self) -> tuple[float, ...]:

        return (float(self.crowdedness), float(self.epd), float(self.available_stock_count),
                float(self.potential_stock_count), float(self.time))


@dataclass(frozen=True)
class PlanningState:
    od_keys: tuple[tuple[int, str], ...]
    od_demand: tuple[Decimal, ...]
    headway: int

    def as_vector(self) -> tuple[float, ...]:

        return tuple(float(q) for q in self.od_demand) + (float(self.headway),)


@dataclass(frozen=True)
class Observation:
    dispatch: DispatchState
    planning: PlanningState


@dataclass(frozen=True)
class AvailableActions:
    dispatch: tuple[int, ...]
    planning_if_dispatch: tuple[PlanningAction, ...]


@dataclass(frozen=True)
class StationTime:
    station: str
    arrival: int
    departure: int


@dataclass(frozen=True)
class TrainService:
    stock_index: int
    action: PlanningAction
    departure: int
    station_times: tuple[StationTime, ...]
    boarded_group_indices: tuple[int, ...]


@dataclass(frozen=True)
class ConstraintViolation:
    equation: int
    station: str | None
    previous_stock_index: int | None
    actual: Decimal | int
    limit: Decimal | int


@dataclass(frozen=True)
class RewardComponents:
    leaving_demand: Decimal
    crowding_exposure: Decimal
    served_demand: Decimal
    weighted_delay: Decimal
    weighted_waiting: Decimal
    headway_penalty: float
    extrinsic: float
    intrinsic: float
    terminal_exponent: float | None
    terminal_bonus: float


@dataclass(frozen=True)
class StepResult:
    before: Observation
    after: Observation
    dispatch_action: int
    planning_action: PlanningAction | None
    dispatch_reward: float
    planning_reward: float
    rewards: RewardComponents
    boarded_groups: tuple[PassengerGroup, ...]
    leaving_group_indices: tuple[int, ...]
    selected_stock: RollingStock | None
    service: TrainService | None
    violations: tuple[ConstraintViolation, ...]
    done: bool


class DispatchPolicy(Protocol):
    def __call__(self, state: DispatchState, available: tuple[int, ...]) -> int: ...


class PlanningPolicy(Protocol):
    def __call__(self, state: PlanningState,
                 available: tuple[PlanningAction, ...]) -> PlanningAction: ...


def dispatch_policy_placeholder(state: DispatchState, available: tuple[int, ...]) -> int:

    raise NotImplementedError("Connect a dispatch model: input DispatchState and available actions; return 0 or 1.")


def planning_policy_placeholder(state: PlanningState,
                                available: tuple[PlanningAction, ...]) -> PlanningAction:

    raise NotImplementedError("Connect a planning model: input PlanningState and available actions; return a PlanningAction.")


class PaperMDP:







    def __init__(self, groups: Sequence[PassengerGroup], stocks: Sequence[RollingStock],
                 plans: Sequence[StopPlan], route_destinations: Mapping[int, Sequence[str]],
                 parameters: EnvironmentParameters) -> None:
        self.parameters = parameters
        self._groups = tuple(groups)
        self._stocks = tuple(stocks)
        self._plan_list = tuple(plans)
        self._destinations = {r: tuple(ds) for r, ds in route_destinations.items()}
        self._validate_inputs()
        self._plans = {p.action: p for p in self._plan_list}
        self._od_keys = tuple((r, d) for r in sorted(self._destinations)
                              for d in sorted(self._destinations[r]))
        self.reset()

    def _validate_inputs(self) -> None:
        def times(obj: object, names: tuple[str, ...]) -> None:
            for name in names:
                if type(getattr(obj, name)) is not int:
                    raise ValueError(f"{type(obj).__name__}.{name} must be an integer number of minutes")

        if not self._destinations:
            raise ValueError("At least one affected route is required")
        for route, stations in self._destinations.items():
            _index(route, "route")
            if route == 0 or not stations or any(not isinstance(s, str) or not s for s in stations):
                raise ValueError("Affected route IDs must be positive, and destination labels must be nonempty strings")
            if len(stations) != len(set(stations)):
                raise ValueError("Destination labels must be unique within each route")
        for items in (self._groups, self._stocks):
            for item in items:
                _index(item.index, "index")
            if len({item.index for item in items}) != len(items):
                raise ValueError("Passenger-group or rolling-stock indices must be unique")
        for g in self._groups:
            times(g, ("arrival_time", "desired_departure_time"))
            _index(g.route, "group.route")
            if g.demand <= 0 or g.desired_departure_time < g.arrival_time:
                raise ValueError("Demand must be positive, and the desired departure cannot precede station entry")
            if g.route == 0:
                continue
            if g.route not in self._destinations or g.destination not in self._destinations[g.route]:
                raise ValueError(f"Route or destination is undefined for passenger group {g.index}")
            times(g, ("leaving_time", "original_destination_arrival"))
            if g.leaving_time < g.arrival_time:
                raise ValueError("Potential leaving time cannot precede station entry")
            if g.original_destination_arrival < g.desired_departure_time:
                raise ValueError("Original destination arrival cannot precede the original departure at the target station")
        for s in self._stocks:
            times(s, ("original_departure_time",))
            if s.kind not in ("flexible", "restricted"):
                raise ValueError("Rolling-stock kind must be flexible or restricted")
            if s.kind == "restricted":
                times(s, ("arrival_time",))
                if s.original_route not in self._destinations:
                    raise ValueError("A restricted vehicle must belong to a defined affected route")
        actions = set()
        for p in self._plan_list:
            if p.route not in self._destinations or not isinstance(p.name, str) or not p.name:
                raise ValueError("Invalid stopping-plan route or name")
            if p.action in actions or not p.stops:
                raise ValueError("Duplicate stopping plan or plan with no downstream stops")
            actions.add(p.action)
            seen = set()
            prior_departure = 0
            for stop in p.stops:
                times(stop, ("travel_time", "dwell_time"))
                if stop.station not in self._destinations[p.route] or stop.station in seen:
                    raise ValueError("Undefined or duplicate stop in the plan")
                if stop.travel_time < prior_departure or stop.dwell_time < 0:
                    raise ValueError("Dwell times must be nonnegative, and downstream arrival cannot precede departure from the previous stop")
                seen.add(stop.station)
                prior_departure = stop.travel_time + stop.dwell_time
        if {p.route for p in self._plan_list} != set(self._destinations):
            raise ValueError("Every affected route must have a predefined stopping plan")

    @property
    def done(self) -> bool:
        return self._done

    @property
    def served_group_indices(self) -> frozenset[int]:
        return frozenset(self._served)

    @property
    def used_stock_indices(self) -> frozenset[int]:
        return frozenset(self._used)

    @property
    def services(self) -> tuple[TrainService, ...]:
        return tuple(self._services)

    def reset(self) -> Observation:

        self._time = self.parameters.start_time
        self._last_departure = self.parameters.initial_last_departure
        self._served: set[int] = set()
        self._used: set[int] = set()
        self._services: list[TrainService] = []
        self._total_served = Decimal(0)
        self._total_exposure = Decimal(0)
        self._done = False
        return self.observe()

    def _present(self, t: int, served: set[int]) -> tuple[PassengerGroup, ...]:

        return tuple(g for g in self._groups if g.index not in served
                     and g.arrival_time <= t
                     and t < (g.desired_departure_time if g.route == 0 else g.leaving_time))

    def _available_stock(self, t: int, used: set[int]) -> tuple[RollingStock, ...]:

        return tuple(s for s in self._stocks if s.index not in used
                     and (s.kind == "flexible" or s.arrival_time < t))

    def _observation(self, t: int, served: set[int], used: set[int],
                     last_departure: int) -> Observation:
        present = self._present(t, served)
        od = dict.fromkeys(self._od_keys, Decimal(0))
        for g in present:
            if g.route != 0:
                od[(g.route, g.destination)] += g.demand


        potential = sum(s.kind == "restricted" and s.index not in used
                        and t < s.arrival_time < self.parameters.end_time for s in self._stocks)
        return Observation(
            DispatchState(sum((g.demand for g in present), Decimal(0)),
                          sum(od.values(), Decimal(0)),
                          len(self._available_stock(t, used)), potential, t),
            PlanningState(self._od_keys, tuple(od[k] for k in self._od_keys), t - last_departure),
        )

    def observe(self) -> Observation:

        return self._observation(self._time, self._served, self._used, self._last_departure)

    def available_actions(self) -> AvailableActions:

        if self._done:
            return AvailableActions((), ())
        stocks = self._available_stock(self._time, self._used)
        flexible = any(s.kind == "flexible" for s in stocks)
        routes = {s.original_route for s in stocks if s.kind == "restricted"}
        planning = tuple(a for a in sorted(self._plans) if flexible or a.route in routes)
        return AvailableActions((0, 1) if planning else (0,), planning)

    def _choose_stock(self, route: int) -> RollingStock:

        stocks = self._available_stock(self._time, self._used)
        restricted = [s for s in stocks if s.kind == "restricted" and s.original_route == route]
        if restricted:
            return min(restricted, key=lambda s: (s.arrival_time, s.index))
        flexible = [s for s in stocks if s.kind == "flexible"]
        if flexible:
            return min(flexible, key=lambda s: (s.original_departure_time, s.index))
        raise ValueError("No available vehicle for the selected route")

    def _board(self, plan: StopPlan, stock: RollingStock,
               present: tuple[PassengerGroup, ...]) -> tuple[PassengerGroup, ...]:
        stations = {s.station for s in plan.stops}
        eligible = sorted((g for g in present if g.route == plan.route and g.destination in stations),
                          key=lambda g: (g.arrival_time, g.index))

        remaining = stock.capacity
        boarded = []
        for g in eligible:
            if g.demand <= remaining:
                boarded.append(g)
                remaining -= g.demand
        return tuple(boarded)

    def _headway_violations(self, service: TrainService) -> list[ConstraintViolation]:
        p = self.parameters
        violations = []
        gap = self._time - self._last_departure
        if gap < p.min_headway:
            previous = self._services[-1].stock_index if self._services else None
            violations.append(ConstraintViolation(18, None, previous, gap, p.min_headway))
        for previous in self._services:
            previous_times = {s.station: s for s in previous.station_times}
            for now in service.station_times:
                past = previous_times.get(now.station)
                if past is None:
                    continue

                for equation, gap in ((19, now.arrival - past.arrival),
                                      (20, now.departure - past.departure)):
                    if gap < p.min_headway:
                        violations.append(ConstraintViolation(equation, now.station,
                                                              previous.stock_index, gap, p.min_headway))
        return violations

    def step(self, dispatch_action: int, planning_action: PlanningAction | None = None) -> StepResult:





        if self._done:
            raise RuntimeError("Episode has terminated; call reset() first.")
        actions = self.available_actions()
        if type(dispatch_action) is not int or dispatch_action not in actions.dispatch:
            raise ValueError("Dispatch action must be an available integer action: 0 or 1.")
        if dispatch_action == 0 and planning_action is not None:
            raise ValueError("planning_action must be None when dispatch is declined.")
        if dispatch_action == 1 and (not isinstance(planning_action, PlanningAction)
                                     or planning_action not in actions.planning_if_dispatch):
            raise ValueError("A currently available PlanningAction is required when dispatching.")

        p, t = self.parameters, self._time
        before = self.observe()
        present = self._present(t, self._served)
        stock = None
        service = None
        boarded: tuple[PassengerGroup, ...] = ()
        violations: list[ConstraintViolation] = []
        served_demand = weighted_waiting = weighted_delay = Decimal(0)
        if dispatch_action == 1:
            plan = self._plans[planning_action]
            stock = self._choose_stock(plan.route)
            boarded = self._board(plan, stock, present)

            station_times = tuple(StationTime(s.station, t + s.travel_time,
                                             t + s.travel_time + s.dwell_time) for s in plan.stops)
            service = TrainService(stock.index, planning_action, t, station_times,
                                   tuple(g.index for g in boarded))
            violations.extend(self._headway_violations(service))
            arrivals = {s.station: s.arrival for s in station_times}
            served_demand = sum((g.demand for g in boarded), Decimal(0))
            weighted_waiting = sum((g.demand * (t - g.arrival_time) for g in boarded), Decimal(0))
            weighted_delay = sum((g.demand * max(0, arrivals[g.destination] -
                                                 g.original_destination_arrival)
                                  for g in boarded), Decimal(0))


        new_served = self._served | {g.index for g in boarded}
        new_used = self._used | ({stock.index} if stock else set())
        new_last_departure = t if dispatch_action else self._last_departure
        next_t = t + p.step


        leaving = tuple(g for g in present if g.route != 0 and g.index not in new_served
                        and t < g.leaving_time <= next_t)
        lost = sum((g.demand for g in leaving), Decimal(0))
        crowd = before.dispatch.crowdedness
        exposure = crowd * p.step if crowd > p.crowding_threshold else Decimal(0)
        if crowd > p.crowding_threshold:
            violations.append(ConstraintViolation(21, None, None, crowd, p.crowding_threshold))
        safety_penalty = p.headway_penalty if any(v.equation in (18, 19, 20) for v in violations) else 0.0
        w = p.weights
        extrinsic = w.alpha1 * float(lost) + w.alpha2 * float(exposure)
        intrinsic = (w.alpha3 * float(served_demand) + w.alpha4 * float(weighted_delay)
                     + w.alpha5 * float(weighted_waiting) + w.alpha6 * safety_penalty)
        total_served = self._total_served + served_demand
        total_exposure = self._total_exposure + exposure
        done = t == p.end_time
        terminal_exponent = None
        terminal_bonus = 0.0
        if done:

            terminal_exponent = (w.beta1 * float(total_served) + w.beta2 * len(new_used)
                                 - w.beta3 * float(total_exposure))
            if not isfinite(terminal_exponent):
                raise OverflowError("The exponent in Eq. (34) is non-finite; adjust the scale of the reward parameters.")
            try:
                terminal_bonus = exp(terminal_exponent)
            except OverflowError as exc:
                raise OverflowError("Exponential reward in Eq. (34) overflowed; the value was not clipped and this step was not committed.") from exc
        dispatch_reward = extrinsic + dispatch_action * intrinsic + terminal_bonus
        planning_reward = dispatch_action * intrinsic
        if not all(isfinite(v) for v in (extrinsic, intrinsic, terminal_bonus,
                                        dispatch_reward, planning_reward)):
            raise OverflowError("Reward is non-finite; this step was not committed. Check the input scales and coefficients.")
        components = RewardComponents(lost, exposure, served_demand, weighted_delay, weighted_waiting,
                                      safety_penalty, extrinsic, intrinsic, terminal_exponent, terminal_bonus)
        after = self._observation(next_t, new_served, new_used, new_last_departure)
        result = StepResult(before, after, dispatch_action, planning_action, dispatch_reward,
                            planning_reward, components, boarded, tuple(g.index for g in leaving),
                            stock, service, tuple(violations), done)
        self._served, self._used = new_served, new_used
        self._time, self._last_departure = next_t, new_last_departure
        self._total_served, self._total_exposure = total_served, total_exposure
        self._done = done
        if service is not None:
            self._services.append(service)
        return result


def policy_step(env: PaperMDP, dispatch_policy: DispatchPolicy = dispatch_policy_placeholder,
                planning_policy: PlanningPolicy = planning_policy_placeholder) -> StepResult:

    if env.done:
        raise RuntimeError("Episode has terminated; call reset() first.")
    state = env.observe()
    actions = env.available_actions()
    dispatch = dispatch_policy(state.dispatch, actions.dispatch)
    if type(dispatch) is not int or dispatch not in actions.dispatch:
        raise ValueError("The dispatch policy output is not in the current available-action set.")
    planning = planning_policy(state.planning, actions.planning_if_dispatch) if dispatch == 1 else None
    return env.step(dispatch, planning)
