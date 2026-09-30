# Online railway schedule replanning

[中文](README_CN.md) | [English](README_EN.md)

MILP and MDP environment code for *An online approach for integrated railway schedule replanning and passenger reassignment with unknown passenger reactions under hub disruptions* (Transportation Research Part B 214, 103606).

| File | Purpose | Input documentation |
|---|---|---|
| [MILP/MILP.py](MILP/MILP.py) | Offline optimization of dispatching, rolling stock, stopping plans, and passenger reassignment | [MILP README](MILP/README_EN.md) |
| [MDP/MDP.py](MDP/MDP.py) | States, transitions, and rewards for online hierarchical decisions | [MDP README](MDP/README_EN.md) |

## Sample data

- [MILP/input_structure.json](MILP/input_structure.json): examples of all MILP input types; can be loaded directly for optimization.
- [MILP/example.json](MILP/example.json): a smaller MILP input example.
- [MDP/input_structure.json](MDP/input_structure.json): an example of the MDP input structure; see the MDP README for conversion to Python objects.

For data security, all examples use synthetic data. This repository contains the environment and optimization code, field descriptions, and samples; it does not include the paper's original data or trained models.

## Run the MILP

Requires Python 3.12, Gurobi, and a valid license. Run from the repository root:

```bash
python -m pip install -r MILP/requirements.txt
python MILP/MILP.py --input MILP/input_structure.json --inspect
python MILP/MILP.py --input MILP/input_structure.json --output results/sample
```

Replace the `--input` path to use your own data. The output directory must not already exist. Solver status and independent validation results are recorded in `summary.json`. See the [MILP README](MILP/README_EN.md) for crowding conventions and all parameters.

## Use the MDP

The MDP uses only the Python standard library. Pass passenger groups, rolling stock, stopping plans, route destinations, and environment parameters to `PaperMDP(...)`; the caller supplies actions. See the [MDP README](MDP/README_EN.md) for input fields, conversion examples, and output interfaces.
