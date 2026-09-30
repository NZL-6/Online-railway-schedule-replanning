# Online railway schedule replanning

[中文](README_CN.md) | [English](README_EN.md)

论文 *An online approach for integrated railway schedule replanning and passenger reassignment with unknown passenger reactions under hub disruptions*（Transportation Research Part B 214, 103606）的 MILP 和 MDP 环境代码。

| 文件 | 用途 | 输入说明 |
|---|---|---|
| [MILP/MILP.py](MILP/MILP.py) | 离线发车、车辆、停站与旅客分配优化 | [MILP README](MILP/README_CN.md) |
| [MDP/MDP.py](MDP/MDP.py) | 在线分层决策的状态、转移与奖励计算 | [MDP README](MDP/README_CN.md) |

## 样例数据

- [MILP/input_structure.json](MILP/input_structure.json)：MILP 各类输入字段样例，可直接读取求解。
- [MILP/example.json](MILP/example.json)：更小的 MILP 输入样例。
- [MDP/input_structure.json](MDP/input_structure.json)：MDP 输入对象的字段结构样例，类型转换见对应 README。

考虑到数据安全问题，所有样例均为人工数据。仓库提供环境与优化代码、字段说明和样例，不包含论文原始数据或已训练模型。

## 运行 MILP

需要 Python 3.12、Gurobi 及有效许可证。在仓库根目录运行：

```bash
python -m pip install -r MILP/requirements.txt
python MILP/MILP.py --input MILP/input_structure.json --inspect
python MILP/MILP.py --input MILP/input_structure.json --output results/sample
```

使用自己的数据时替换 `--input` 路径。输出目录须尚不存在；求解状态和独立校验结果见 `summary.json`。拥挤度口径和完整参数见 [MILP README](MILP/README_CN.md)。

## 使用 MDP

MDP 仅依赖 Python 标准库。将旅客、车辆、停站方案、线路目的站集合和环境参数传入 `PaperMDP(...)`；动作由调用方提供。数据字段、转换示例和输出接口见 [MDP README](MDP/README_CN.md)。
