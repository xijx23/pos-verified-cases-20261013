# POS Input and Output Examples

This repository contains five selected, independently verified cases illustrating the inputs and outputs of POS.
Each case provides a problem description (`desc.txt`), input workbook (`.xlsx`), reference objective (`stantard_value.json`), complete solver code (`solve_model.py`), and historical execution report (`execution_report.json`).
The solver code embeds the original extracted parameters so that no separate data file is required, without changing the model equations or objective.
Run `python solve_model.py` inside a case directory with Python and a licensed installation of Gurobi (`gurobipy`).
