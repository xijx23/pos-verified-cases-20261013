from __future__ import annotations
import json
from pathlib import Path
from gurobipy import Model, GRB, quicksum

def _index_iter(obj):
    if isinstance(obj, int): return range(1, obj + 1)
    if isinstance(obj, float): return range(1, int(obj) + 1)
    if isinstance(obj, list): return range(1, len(obj) + 1)
    if isinstance(obj, dict): return list(obj.keys())
    raise TypeError(f'Unsupported dimension source: {obj!r}')

def build_model():
    data = json.loads((Path(__file__).with_name('data.json')).read_text(encoding='utf-8'))
    NumBuses = data['NumBuses']
    BusId = data['BusId']
    BusType = data['BusType']
    BusPD = data['BusPD']
    NumGenerators = data['NumGenerators']
    GenBus = data['GenBus']
    GenStatus = data['GenStatus']
    GenPMin = data['GenPMin']
    GenPMax = data['GenPMax']
    GenRampAGC = data['GenRampAGC']
    NumBranches = data['NumBranches']
    BranchFromBus = data['BranchFromBus']
    BranchToBus = data['BranchToBus']
    BranchReactance = data['BranchReactance']
    BranchRateA = data['BranchRateA']
    BranchStatus = data['BranchStatus']
    Tap = data['Tap']
    Shift = data['Shift']
    BranchAngleMin = data['BranchAngleMin']
    BranchAngleMax = data['BranchAngleMax']
    GenCostModel = data['GenCostModel']
    GenStartupCost = data['GenStartupCost']
    GenShutdownCost = data['GenShutdownCost']
    GenCostNCost = data['GenCostNCost']
    GenQuadraticCost = data['GenQuadraticCost']
    GenMarginalCost = data['GenMarginalCost']
    GenNoLoadCost = data['GenNoLoadCost']
    BaseMVA = data['BaseMVA']
    NumPeriods = data['NumPeriods']
    LoadShape = data['LoadShape']
    ReserveFraction = data['ReserveFraction']
    model = Model('OptiAgentModel')

    p = model.addVars(_index_iter(NumGenerators), _index_iter(NumPeriods), lb=0, vtype=GRB.CONTINUOUS, name='p')
    theta = model.addVars(_index_iter(NumBuses), _index_iter(NumPeriods), lb=-GRB.INFINITY, vtype=GRB.CONTINUOUS, name='theta')
    flow = model.addVars(_index_iter(NumBranches), _index_iter(NumPeriods), lb=-GRB.INFINITY, vtype=GRB.CONTINUOUS, name='flow')

    # Constraint c_001
    model.addConstrs(
        (p[i, t] >= GenStatus[i - 1] * GenPMin[i - 1]
         for i in _index_iter(NumGenerators)
         for t in range(1, len(LoadShape) + 1)),
        name="c_001__GeneratorMinimumOutput"
    )

    # Constraint c_002
    model.addConstrs(
        (p[i, t] <= GenPMax[i - 1] * GenStatus[i - 1]
         for i in _index_iter(NumGenerators)
         for t in range(1, len(LoadShape) + 1)),
        name="c_002__GeneratorMaximumOutput"
    )

    # Constraint c_003
    model.addConstrs(
        (p[i, t] == 0
         for i in _index_iter(NumGenerators)
         for t in range(1, len(LoadShape) + 1)
         if GenStatus[i - 1] == 0),
        name="c_003__OfflineGeneratorZeroOutput"
    )

    # Constraint c_004
    model.addConstrs(
        (p[i, t] - p[i, t - 1] <= 0.30 * GenPMax[i - 1]
         for i in _index_iter(NumGenerators)
         for t in range(2, len(LoadShape) + 1)),
        name="c_004__GeneratorRampUpLimit"
    )

    # Constraint c_005
    model.addConstrs(
        (p[i, t - 1] - p[i, t] <= 0.30 * GenPMax[i - 1]
         for i in _index_iter(NumGenerators)
         for t in range(2, len(LoadShape) + 1)),
        name="c_005__GeneratorRampDownLimit"
    )

    # Constraint c_006
    model.addConstrs(
        (quicksum(p[i, t] for i in _index_iter(NumGenerators) if GenBus[i - 1] == b)
         - BusPD[b - 1] * LoadShape[t - 1]
         - quicksum(flow[l, t] for l in _index_iter(NumBranches) if BranchFromBus[l - 1] == b)
         + quicksum(flow[l, t] for l in _index_iter(NumBranches) if BranchToBus[l - 1] == b)
         == 0
         for b in _index_iter(NumBuses)
         for t in range(1, len(LoadShape) + 1)),
        name="c_006__BusPowerBalance"
    )

    # Constraint c_007
    model.addConstrs(
        (flow[l, t] == BranchStatus[l - 1] * (BaseMVA / BranchReactance[l - 1]) * (theta[BranchFromBus[l - 1], t] - theta[BranchToBus[l - 1], t])
         for l in _index_iter(NumBranches)
         for t in range(1, len(LoadShape) + 1)),
        name="c_007__DCPowerFlowEquation"
    )

    # Constraint c_008
    model.addConstrs(
        (flow[l, t] <= BranchRateA[l - 1]
         for l in _index_iter(NumBranches)
         for t in range(1, len(LoadShape) + 1)),
        name="c_008__BranchFlowUpperLimit"
    )

    # Constraint c_009
    model.addConstrs(
        (flow[l, t] >= -BranchRateA[l - 1]
         for l in _index_iter(NumBranches)
         for t in range(1, len(LoadShape) + 1)),
        name="c_009__BranchFlowLowerLimit"
    )

    # Constraint c_010
    model.addConstrs(
        (theta[b, t] == 0
         for b in _index_iter(NumBuses)
         for t in range(1, len(LoadShape) + 1)
         if BusType[b - 1] == 3),
        name="c_010__ReferenceBusAngle"
    )

    # Constraint c_011
    model.addConstrs(
        (quicksum(GenStatus[i - 1] * GenPMax[i - 1] - p[i, t] for i in _index_iter(NumGenerators)) >=
         ReserveFraction * LoadShape[t - 1] * sum(BusPD[b - 1] for b in _index_iter(NumBuses))
         for t in range(1, len(LoadShape) + 1)),
        name="c_011__SystemReserveRequirement"
    )

    # Objective
    model.setObjective(
        quicksum(
            GenQuadraticCost[i - 1] * p[i, t] * p[i, t] +
            GenMarginalCost[i - 1] * p[i, t] +
            GenNoLoadCost[i - 1] * GenStatus[i - 1]
            for i in _index_iter(NumGenerators)
            for t in range(1, len(LoadShape) + 1)
        ),
        GRB.MINIMIZE
    )
    return model

def main():
    model = build_model()
    model.setParam(GRB.Param.MIPGap, 0.005)
    model.optimize()
    print('STATUS', model.Status)

if __name__ == '__main__':
    main()
