"""Re-solve unchanged POS models and independently check workbook requirements."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import gurobipy as gp
from reference.solve_cases import read_case, build_model

ROOT = Path(__file__).resolve().parent
FEAS_TOL = 1e-5
OBJ_TOL = 1e-3


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def clean_log(text):
    return re.sub(r'Set parameter LicenseID to value \d+', 'Set parameter LicenseID to value [REDACTED]', text)


def mapped_name(name):
    if name.startswith(('p[', 'shed[')):
        assert name.endswith(',1]'), name
        return name[:-3] + ']'
    return name.replace('theta_base1[', 'theta[').replace('flow_base1[', 'flow[')


def residuals(reference, values):
    mapped = {v.VarName: values[mapped_name(v.VarName)] for v in reference.getVars()}
    assert all(math.isfinite(value) for value in mapped.values())
    bound = max(max(v.LB - mapped[v.VarName], mapped[v.VarName] - v.UB, 0) for v in reference.getVars())
    worst, worst_name = 0.0, None
    for constraint in reference.getConstrs():
        row = reference.getRow(constraint)
        lhs = sum(row.getCoeff(k) * mapped[row.getVar(k).VarName] for k in range(row.size()))
        delta = lhs - constraint.RHS
        violation = abs(delta) if constraint.Sense == '=' else max(0, delta if constraint.Sense == '<' else -delta)
        if violation > worst:
            worst, worst_name = violation, constraint.ConstrName
    return {'max_row_violation': worst, 'worst_row': worst_name, 'max_bound_violation': bound}


def check_parameters(case, data):
    fields = {
        'Bus': {'BusId': 'BUS_I', 'BusType': 'BUS_TYPE', 'BusPD': 'PD'},
        'Gen': {'GenBus': 'GEN_BUS', 'GenStatus': 'GEN_STATUS', 'GenPMin': 'PMIN', 'GenPMax': 'PMAX'},
        'Branch': {'BranchFromBus': 'F_BUS', 'BranchToBus': 'T_BUS', 'BranchReactance': 'BR_X', 'BranchRateA': 'RATE_A', 'BranchStatus': 'BR_STATUS', 'Tap': 'TAP', 'Shift': 'SHIFT'},
        'Gencost': {'GenQuadraticCost': 'COST_3', 'GenMarginalCost': 'COST_2', 'GenNoLoadCost': 'COST_1'},
    }
    for table, pairs in fields.items():
        for parameter, column in pairs.items():
            actual = data[parameter]
            expected = [float(row[column] or 0) for row in case['tables'][table]]
            assert len(actual) == len(expected), parameter
            assert all(abs(a-b) <= 1e-10 for a,b in zip(actual, expected)), parameter
    assert data['LoadShape'] == case['settings']['load']
    assert data['BaseMVA'] == 100
    assert data['NumPeriods'] == 24
    assert data['BusId'] == list(range(1, len(data['BusId'])+1))
    assert all(tap in (0, 1) for tap in data['Tap'])
    assert all(shift == 0 for shift in data['Shift'])
    assert all(status == 1 for status in data['BranchStatus'])
    assert all(status == 1 for status in data['GenStatus'])
    assert min(data['BranchRateA']) > 0
    if 'ReserveFraction' in data:
        assert data['ReserveFraction'] == case['settings']['reserve']
    if 'RampFactor' in data:
        assert data['RampFactor'] == case['settings']['ramp']
    if 'RampLimit' in data:
        assert all(abs(r - case['settings']['ramp'] * p) <= 1e-10 for r,p in zip(data['RampLimit'],data['GenPMax']))
    if case['settings']['family'] == 'opf_load_shedding':
        assert data['SheddingPenalty'] == case['settings']['shed_cost'] == 10000


def recompute_objective(case, values):
    result = 0.0
    for t in range(1,25):
        for i, cost in enumerate(case['tables']['Gencost'],1):
            p = values[f'p[{i},{t}]']
            result += float(cost['COST_2']) * p
            if case['settings']['quadratic']:
                result += float(cost['COST_3']) * p*p + float(cost['COST_1'])
        if case['settings']['family'] == 'opf_load_shedding':
            result += case['settings']['shed_cost'] * sum(values[f'shed[{int(b["BUS_I"])},{t}]'] for b in case['tables']['Bus'])
    return result


def verify(folder, output):
    spec = importlib.util.spec_from_file_location('pos_case', folder/'solve_model.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.build_model()
    model.Params.OutputFlag = 0
    model.Params.MIPGap = 0.005
    model.optimize()
    assert model.Status == gp.GRB.OPTIMAL, folder.name
    values = {v.VarName: v.X for v in model.getVars()}
    assert not model.IsMIP, 'ED/OPF must not introduce commitment variables'
    case = read_case(folder)
    check_parameters(case, json.loads((folder/'data.json').read_text(encoding='utf-8')))
    reference = build_model(case)
    reference.optimize()
    assert reference.Status == gp.GRB.OPTIMAL
    quality = residuals(reference, values)
    assert max(quality['max_row_violation'], quality['max_bound_violation']) <= FEAS_TOL, quality
    independent = recompute_objective(case, values)
    archived = json.loads((folder/'stantard_value.json').read_text(encoding='utf-8'))['objective_value']
    difference = abs(model.ObjVal - reference.ObjVal)
    assert difference <= OBJ_TOL, (model.ObjVal, reference.ObjVal)
    assert abs(model.ObjVal-independent) <= OBJ_TOL
    assert abs(reference.ObjVal-archived) <= OBJ_TOL
    # Negative control: an invalid dispatch must be caught, not just solved again.
    bad = values.copy()
    bad['p[1,1]'] += 1
    negative = residuals(reference, bad)
    assert max(negative['max_row_violation'], negative['max_bound_violation']) > 0.9
    expected_variables = {mapped_name(v.VarName) for v in reference.getVars()}
    assert expected_variables == set(values), 'Unexpected or missing POS decision variables'
    result = {'case':folder.name, 'status':'PASS', 'pos_status':model.Status,
              'reference_status':reference.Status, 'pos_objective':model.ObjVal,
              'reference_objective':reference.ObjVal, 'archived_reference_objective':archived,
              'absolute_objective_difference':difference,
              'objective_recompute_error':abs(model.ObjVal-independent),
              'pos_constraint_violation':model.ConstrVio, 'pos_bound_violation':model.BoundVio,
              'reference_quality_on_pos_solution':quality,
              'parameter_mapping':'PASS', 'negative_control':'PASS',
              'total_shed':sum(v for k,v in values.items() if k.startswith('shed[')),
              'variables':model.NumVars,'constraints':model.NumConstrs,
              'reference_variables':reference.NumVars,'reference_constraints':reference.NumConstrs,
              'solver':'.'.join(map(str,gp.gurobi.version())),
              'feasibility_tolerance':FEAS_TOL,'absolute_objective_tolerance':OBJ_TOL}
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/'verification.json',result)
    write_json(output/'solution.json',{'status':model.Status,'objective':model.ObjVal,'variables':values})
    model.write(str(output/'model.lp'))
    model.dispose()
    reference.dispose()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'verification')
    args = parser.parse_args()
    names = json.loads((ROOT/'selection.json').read_text(encoding='utf-8'))['selected']
    args.output.mkdir(parents=True,exist_ok=True)
    results = []
    for name in names:
        folder = ROOT/'cases'/name
        if args.baseline:
            proc = subprocess.run([sys.executable,'solve_model.py'],cwd=folder,capture_output=True,text=True)
            stdout,stderr = clean_log(proc.stdout),clean_log(proc.stderr)
            result = {'case':name,'command':'python solve_model.py','cwd':f'cases/{name}',
                      'exit_status':proc.returncode,'stdout':stdout,'stderr':stderr}
            assert proc.returncode == 0 and 'STATUS 2' in stdout, result
        else:
            result = verify(folder,args.output/name)
        results.append(result)
        print(name,'PASS', 'STATUS 2' if args.baseline else f'objective={result["pos_objective"]:.9f} difference={result["absolute_objective_difference"]:.3g}')
    write_json(args.output/'summary.json',results)
    print('PASS: 5/5 cases')


if __name__ == '__main__':
    main()
