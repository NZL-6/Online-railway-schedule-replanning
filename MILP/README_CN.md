# Appendix C MILP

[中文](README_CN.md) | [English](README_EN.md)

`MILP.py`：全信息车辆调度、停站规划和旅客分配模型。

## 样例与运行

`input_structure.json` 展示灵活/限制型车辆、受影响/未受影响旅客、多个停站方案和参数的字段结构，全部为人工数据。`example.json` 保留为更小的输入样例。

**使用 JSON 方式时，一份包含下述字段的数据文件即可提供 MILP 所需输入，不再需要 CSV、Excel、智能体、代理模型或训练权重。** 运行还需要 Python 3.12、Gurobi 及有效许可证。

在本目录运行：

```bash
python -m pip install -r requirements.txt
python MILP.py --input input_structure.json --inspect
python MILP.py --input input_structure.json --output results/sample
```

将 `--input` 后的路径替换为自己的 JSON。`--inspect` 只检查输入；最后一条命令建模求解。`--output` 必须为尚不存在的目录。

## 输入字段（标签）

字段名和枚举值区分大小写。时间统一为分钟，例如 08:00 为 `480`，次日 01:00 为 `1500`；不是 `HHMM`。需求与容量使用相同单位，论文需求按整数人数填写。数值可写为 JSON 数字或十进制字符串；编号使用整数，车辆 `id` 使用字符串。

### 顶层字段

| 字段 | 必填 | 结构 |
|---|---|---|
| `times` | 是 | 非空、严格递增且不重复的决策时刻列表 |
| `stocks` | 是 | 车辆对象列表 |
| `groups` | 是 | 旅客组对象列表 |
| `plans` | 是 | 停站方案对象列表 |
| `settings` | 否，建议填写 | 环境阈值及目标权重对象，省略时使用下表默认值 |

### 车辆 `stocks[]`

| 字段 | 必填 | 含义 |
|---|---|---|
| `id` | 是 | 唯一车辆编号，如 `F1`、`R1`；同优先级按该字符串排序 |
| `kind` | 是 | `Flexible` 或 `Restricted` |
| `capacity` | 是 | 可供重分配旅客使用的非负容量 |
| `original_departure` | 否，建议填写 | 目标站原定发车时刻；默认 `0`，用于灵活车辆选择顺序 |
| `route` | 限制型必填 | 所属受影响线路编号，与 `plans[].route` 一致；灵活车辆可省略 |
| `arrival` | 限制型必填 | 到达目标站时刻；只有严格晚于该时刻才可使用；灵活车辆可省略 |

### 旅客组 `groups[]`

| 字段 | 必填 | 含义 |
|---|---|---|
| `id` | 是 | 唯一整数编号；相同进站时刻按该编号排序 |
| `route` | 是 | 受影响线路编号；`0` 表示未受影响旅客 |
| `destination` | 是 | 目的站标签，与方案中的车站标签一致 |
| `weight` | 是 | 正数需求人数 |
| `enter` | 是 | 进站时刻 |
| `leave` | 是 | 受影响旅客潜在离站时刻；`route=0` 也需保留该数值字段，但在站判断使用 `original_departure` |
| `original_departure` | 是 | 目标站原定发车时刻 |
| `original_arrival` | 受影响旅客必填 | 目的站原定到达时刻；`route=0` 可为 `null` 或省略 |

受影响组在站区间为 `[enter, leave)`；未受影响组为 `[enter, original_departure)`。旅客仅能分配到所属线路中停靠其目的站的方案。

### 停站方案 `plans[]`

| 字段 | 必填 | 含义 |
|---|---|---|
| `route` | 是 | 正整数线路编号 |
| `id` | 是 | 整数方案编号；`(route, id)` 组合唯一 |
| `arrival` | 是 | `{车站标签: 到达偏移分钟数}` |
| `departure` | 是 | `{车站标签: 出发偏移分钟数}`，车站集合须与 `arrival` 相同 |

偏移均从目标站发车时刻算起，已包含之前运行及停站时间；不是逐区间时长。例如 `arrival.A=10`、`departure.A=12` 表示发车后第 10 分钟到 A、第 12 分钟离开 A。仅列出该方案停靠的下游站；到达偏移非负，出发偏移不小于到达偏移。

### 参数 `settings`

| 字段 | 必填 | 默认值 | 含义 |
|---|---|---:|---|
| `headway` | 否 | 5 | 最小安全间隔，分钟 |
| `crowd_limit` | 否 | 1500 | 在站人数上限 |
| `service_weight` | 否 | 1 | 服务人数收益系数 |
| `waiting_weight` | 否 | 0.001 | 旅客加权等待时间成本系数 |
| `delay_weight` | 否 | 0.00001 | 旅客加权到达延误成本系数 |

目标为 `service_weight × 服务人数 − waiting_weight × 加权等待 − delay_weight × 加权延误`。默认值和人工样例参数可替换为自己的设置；不需要 MDP 的奖励参数。

拥挤度选项：

- `--crowding appendix-c`：默认，使用附录 C 印刷公式，从基线人数扣除所有此前已服务人数。
- `--crowding state-consistent`：使用正文式 (13) 的当前未服务在站人数。两种定义不等价，所选口径写入结果。

## 可选：原格式数据适配

已有原格式数据时，也可运行：

```bash
python MILP.py --data-dir path/to/data --passenger-file passengers.csv --output results/case1
```

此方式与上述 JSON 输入二选一。该目录需包含旅客 CSV、`scenario.txt`、`Rolling_stock.txt`、`stop_plan_times.csv`、`Origin_timetable.xlsx`。`--arrival-overrides arrivals.json` 可提供 `{组编号: 目的站原定到达分钟数}` 映射。

## 输出

`--output` 指定尚不存在的目录；省略时输出到程序目录的 `results/<时间戳>/`。

| 文件 | 内容 |
|---|---|
| `summary.json` | 求解状态、目标值、界、gap、耗时及校验状态 |
| `validation.json` | 独立回放校验及明细，有解时生成 |
| `selected_actions.csv` | 发车车辆、线路、方案、时刻和服务人数 |
| `assignments.csv` | 旅客组分配、等待和延误 |
| `crowding.csv` | 两种定义下的各时刻拥挤度 |
| `gurobi.log` | 求解日志 |
| `infeasibility.ilp` | 模型被证明不可行时的 IIS |
| `model.lp` | 指定 `--write-model` 时导出的模型 |

结果 CSV 仅在独立校验通过后生成。读取结果时同时检查 `status_name`、`mip_gap` 和 `validation_passed`；`TIME_LIMIT` 表示达到时间限制。

其他参数：`--time-limit`（求解秒数）、`--threads`（线程数）、`--mip-gap`（相对最优性容差）。完整参数见 `--help`。

## Python 调用

```python
from MILP import load_json, build_model, validate_solution

instance = load_json("example.json")  # 在此指定输入文件
built = build_model(instance, crowding="appendix-c")
try:
    built.model.optimize()
    if built.model.SolCount:
        result = validate_solution(built)
        print(result["passed"], result["objective"])
finally:
    built.model.dispose()
```
