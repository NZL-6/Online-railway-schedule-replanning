# MDP 仿真环境

[中文](README_CN.md) | [English](README_EN.md)

`MDP.py` 提供正文第 4.2–4.5 节的状态、动作转移和奖励计算，仅依赖 Python 标准库。

## 样例与输入位置

`input_structure.json` 是人工数据的字段结构样例，包含五类顶层输入。它不是命令行运行配置；环境不自动读取 JSON。调用方将数据转为对应数据类后传入：

```python
env = PaperMDP(groups, stocks, plans, route_destinations, parameters)
```

本样例仅展示数据结构，不提供智能体、代理模型或训练流程。

字段名和枚举值区分大小写。当前时间字段均使用整数分钟，例如 08:00 为 `480`，次日 01:00 为 `1500`。需求与容量用相同单位，使用 JSON 数字。索引是唯一非负整数。

## 输入字段（标签）

### 顶层字段

| 字段 | 必填 | 对应 Python 输入 |
|---|---|---|
| `groups` | 是 | `PassengerGroup` 列表 |
| `stocks` | 是 | `RollingStock` 列表 |
| `plans` | 是 | `StopPlan` 列表，其中 `stops` 转为 `Stop` 序列 |
| `route_destinations` | 是 | `{线路整数编号: 完整目的站序列}` |
| `parameters` | 是 | `EnvironmentParameters`，其中 `weights` 转为 `RewardWeights` |

### 旅客组 `groups[]` → `PassengerGroup`

| 字段 | 必填 | 含义 |
|---|---|---|
| `index` | 是 | 唯一组索引；同进站时刻用于 FIFO 排序 |
| `route` | 是 | 正整数受影响线路编号；`0` 表示未受影响线路 |
| `demand` | 是 | 正数需求人数 |
| `arrival_time` | 是 | 进站时刻 |
| `desired_departure_time` | 是 | 目标站原定发车时刻，不早于进站 |
| `destination` | 受影响旅客必填 | 目的站标签，属于 `route_destinations` 中对应线路 |
| `leaving_time` | 受影响旅客必填 | 潜在离站时刻，不早于进站 |
| `original_destination_arrival` | 受影响旅客必填 | 目的站原定到达时刻，不早于原定发车 |

`route=0` 时后三个字段可省略或为 `null`，离站按 `desired_departure_time` 处理。

### 车辆 `stocks[]` → `RollingStock`

| 字段 | 必填 | 含义 |
|---|---|---|
| `index` | 是 | 唯一车辆索引，用于同优先级排序 |
| `kind` | 是 | 小写 `flexible` 或 `restricted` |
| `capacity` | 是 | 可供重分配旅客使用的非负容量 |
| `original_departure_time` | 是 | 目标站原定发车时刻 |
| `original_route` | 限制型必填 | 所属受影响线路编号；灵活车辆可省略 |
| `arrival_time` | 限制型必填 | 到达目标站时刻；灵活车辆可省略 |

### 停站方案 `plans[]` → `StopPlan`

| 字段 | 必填 | 含义 |
|---|---|---|
| `route` | 是 | `route_destinations` 中已定义的受影响线路编号 |
| `name` | 是 | 非空方案名；`(route, name)` 组合唯一 |
| `stops` | 是 | 按运行方向排列的非空下游停站列表，不含目标站 |

每个 `stops[]` 对象转换为 `Stop`：

| 字段 | 必填 | 含义 |
|---|---|---|
| `station` | 是 | 对应线路的目的站标签；同一方案不重复 |
| `travel_time` | 是 | 从目标站发车起算的累计到达偏移，已含之前停站影响，不小于前一站出发偏移 |
| `dwell_time` | 是 | 本站非负停站时长 |

例如到达偏移 `25`、停站 `2`，出发偏移为 `27`。每条受影响线路至少给出一个方案。

### 线路目的站 `route_destinations`

结构示例：`{"1": ["A", "B"]}`。JSON 对象键为字符串，传入环境时须将线路键转为整数。

列出每条线路的完整目的站集合，包括当前零需求目的站；同一路线内标签不得重复。环境按线路编号及车站标签排序，生成 `PlanningState.od_keys`。

### 环境参数 `parameters` → `EnvironmentParameters`

以下字段全部必填：

| 字段 | 含义 |
|---|---|
| `start_time` | 首次决策时刻 |
| `end_time` | 最后决策时刻，不小于开始时刻 |
| `step` | 正整数步长，须整除 `end_time - start_time` |
| `initial_last_departure` | 开始前最近一次发车时刻，不晚于 `start_time` |
| `min_headway` | 正整数最小间隔，分钟 |
| `crowding_threshold` | 非负拥挤人数阈值 |
| `headway_penalty` | 正数安全间隔惩罚常量 |
| `weights` | 下表的完整奖励系数对象 |

### 奖励系数 `parameters.weights` → `RewardWeights`

以下字段全部必填，人工样例数值仅示意输入格式：

| 字段 | 符号 | 对应项 |
|---|---|---|
| `alpha1` | ≤ 0 | 离站未服务需求 |
| `alpha2` | ≤ 0 | 拥挤暴露人时 |
| `alpha3` | ≥ 0 | 服务需求 |
| `alpha4` | ≤ 0 | 旅客加权到达延误 |
| `alpha5` | ≤ 0 | 旅客加权等待 |
| `alpha6` | ≤ 0 | 安全间隔惩罚 |
| `beta1` | ≥ 0 | 终局累计服务需求 |
| `beta2` | ≥ 0 | 终局已发车辆数 |
| `beta3` | ≥ 0 | 终局累计拥挤暴露；公式中的负号由环境施加 |

## 将样例转为输入对象

以下仅为数据读取和类型转换，在本目录的调用脚本中使用：

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

## 接口与输出

- `reset()`：开始回合，返回两个智能体的状态。
- `observe()`：读取当前状态；`available_actions()`：读取可行动作。
- `step(dispatch_action, planning_action=None)`：调度动作 `0` 不发车，`1` 发车；发车时传入 `PlanningAction(route=线路编号, plan=方案名)`。
- `StepResult`：前后状态、两类奖励及分项、上车组、车辆、到发时刻、约束违反和终止标志；不自动保存文件。

车辆匹配和容量为硬规则；间隔和拥挤违反会记录并计入惩罚。决策包含 `end_time`，终局统计包含末步动作，末步使用完整 `step`。决策模型由使用者自行接入。
