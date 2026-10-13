# 50-case deterministic reference calculation

Run from `E:\code\python\optiAgent`:

```powershell
python standard_calculation/solve_cases.py --audit-only
python -m unittest standard_calculation.test_reference
python standard_calculation/solve_cases.py --time-limit 600
python -m standard_calculation.validate_results
```

Dependencies for this separate calculation: Python, numpy, openpyxl, gurobipy 12.0.3
and its existing licensed solver. No LLM is used. No pipeline, baseline,
benchmark runner, description or Excel data is changed. The reference calculation
defines a new explicitly documented comparison reference, not a modification of
the existing benchmark protocol.

Inputs are only each case's `desc.txt` and `data.xlsx` or its sole case-named
workbook. `audit.json` records the extracted description parameters and input
SHA-256 hashes. `summary.json` records approved modeling conventions, statuses,
objective bounds, gaps and numerical quality. Evidence lives exclusively here.
Each problem receives only `stantard_value.json`, with one `objective_value`.

## Approved interpretation

- The first load array element is the first **operating** period. Its generation
  is solved by power balance, never fixed to zero. All-off pre-horizon status
  controls startup cost and logic, not the first operating dispatch. Without a
  stated pre-horizon dispatch, no boundary ramp is invented. Ramps join operating
  periods 1 and 2 onwards.
- Unless stated otherwise, pre-horizon status is all off. Stochastic cases
  explicitly specifying GenStatus use that status. Initial time already spent
  on/off is not provided, so no invented residual obligation is imposed.
- Operational startup/shutdown ramps allow PMIN. Minimum up/down times use
  rolling startup/shutdown sums and end-of-horizon truncation.
- Empty case300 PMIN cells are zero, as approved. Stochastic cases without a
  stated ramp do not acquire an invented ramp. case39 uses the workbook quadratic
  fuel cost, as approved.
- N-1 case118 has no specified redispatch and uses the approved fixed-dispatch
  interpretation. Other cases follow their explicit redispatch bounds. All
  requested active-branch outages are represented, including islanding. case118
  uses its stated 40 smallest-RATE_A active branches.
- Robust UC follows the explicitly listed reserve coverage, headroom/footroom
  and ramp deliverability constraints. It does not claim network-feasible recourse
  for an unspecified bus-wise, time-wise uncertainty set.
- Fuel is linear where stated, quadratic where stated; other conventional UC
  fuel uses COST_2. All UC fixed/startup/shutdown costs use Gencost. Piecewise
  fuel includes PMIN baseline cost and equal-width increment segments.
- All wind FCUC fuel uses linear COST_2*p by explicit user confirmation.
- Scenario dispatch and penalties are probability weighted; first-stage costs
  are charged once. Wind reserve uses available forecast, not accepted wind.
- Workbooks lack a system BaseMVA field: 100 MVA MATPOWER convention is used.
  Standard DC network includes tap and phase shift; case300 uses the explicit
  no-tap equation in its description. RATE_A=0 denotes no thermal limit.

## Precision and publication

Only Gurobi OPTIMAL results are published. Feasibility and optimality tolerances
are 1e-8, integer tolerance 1e-9. Initial runs requested relative MIP gap 1e-9
and absolute gap 1e-5; the final program tightens these to zero relative gap and
1e-6 absolute gap. The only initial result with a material bound difference,
case300 quadratic SCUC, was recomputed under the tightened tolerances.
Numbers retain full floating-point output precision; this is numerical
optimization, not symbolic exact arithmetic. `INFEASIBLE` is published only after
an infeasibility proof with retained IIS. A timeout incumbent is never a standard.

Validation reopens all inputs/results/solutions, verifies hashes, checks every
linear model row and bound/integer residual, and independently recomputes the
objective from the input cost coefficients and dispatch. Test coverage includes
the first operating period and a hand-computable quadratic dispatch problem.
Fixed-dispatch N-1 uses exact LODF constraints, with explicit nodal models for
islanding outages. Corrective N-1 uses an optimal relaxed master and an independently
solved feasible recourse witness for every requested outage. Infeasible outages
are added to the master until every outage has a witness. This proves the full
optimum: the master supplies a lower bound and its feasible witnesses supply the
same upper bound. Independent validation reconstructs every contingency network
from nodal injections and checks emergency limits and redispatch bounds.

## Rollback

```powershell
python -m standard_calculation.rollback --root E:\code\python\optiAgent
```

`ROLLBACK.sh` wraps that command for Bash. Only recorded result files are restored
or removed; hashes protect subsequently edited outputs. Rollback does not change
input files or any unrelated artifacts. The rollback verification is run on a
separate temporary copy, leaving the actual results intact.
