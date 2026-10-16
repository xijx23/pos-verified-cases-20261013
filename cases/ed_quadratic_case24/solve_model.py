from __future__ import annotations
from gurobipy import Model, GRB, quicksum

def _index_iter(obj):
    if isinstance(obj, int): return range(1, obj + 1)
    if isinstance(obj, float): return range(1, int(obj) + 1)
    if isinstance(obj, list): return range(1, len(obj) + 1)
    if isinstance(obj, dict): return list(obj.keys())
    raise TypeError(f'Unsupported dimension source: {obj!r}')

def build_model():
    # Parameters extracted from the accompanying input workbook and description.
    data = {'NumBuses': 24,
     'BusId': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24],
     'BusType': [3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
     'BusPD': [21.939,
               28.141,
               34.343,
               18.063,
               24.265,
               30.467,
               42.289,
               20.389,
               26.591,
               32.793,
               16.513,
               22.715,
               0.0,
               40.739,
               18.838,
               25.04,
               31.242,
               37.444,
               21.164,
               27.366,
               39.188,
               17.288,
               23.49,
               29.692],
     'NumGenerators': 7,
     'GenBus': [1, 3, 8, 14, 17, 21, 2],
     'GenStatus': [1, 1, 1, 1, 1, 1, 1],
     'GenPMin': [13.073, 21.231, 15.137, 12.139, 20.051, 14.449, 11.205],
     'GenPMax': [137.607, 176.923, 216.239, 127.778, 167.094, 206.41, 117.949],
     'GenRampAGC': [39.906, 58.385, 80.008, 31.945, 48.457, 68.115, 43.641],
     'NumBranches': 37,
     'BranchFromBus': [1,
                       2,
                       3,
                       4,
                       5,
                       6,
                       7,
                       8,
                       9,
                       10,
                       11,
                       12,
                       13,
                       14,
                       15,
                       16,
                       17,
                       18,
                       19,
                       20,
                       21,
                       22,
                       23,
                       24,
                       1,
                       6,
                       11,
                       16,
                       21,
                       2,
                       7,
                       12,
                       17,
                       22,
                       3,
                       8,
                       13],
     'BranchToBus': [2,
                     3,
                     4,
                     5,
                     6,
                     7,
                     8,
                     9,
                     10,
                     11,
                     12,
                     13,
                     14,
                     15,
                     16,
                     17,
                     18,
                     19,
                     20,
                     21,
                     22,
                     23,
                     24,
                     1,
                     5,
                     11,
                     17,
                     23,
                     5,
                     6,
                     12,
                     18,
                     24,
                     6,
                     7,
                     13,
                     19],
     'BranchReactance': [0.039,
                         0.043,
                         0.047,
                         0.051,
                         0.055,
                         0.059,
                         0.063,
                         0.035,
                         0.039,
                         0.043,
                         0.047,
                         0.051,
                         0.055,
                         0.059,
                         0.063,
                         0.035,
                         0.039,
                         0.043,
                         0.047,
                         0.051,
                         0.055,
                         0.059,
                         0.063,
                         0.035,
                         0.045,
                         0.05,
                         0.055,
                         0.06,
                         0.065,
                         0.07,
                         0.075,
                         0.08,
                         0.085,
                         0.09,
                         0.045,
                         0.05,
                         0.055],
     'BranchRateA': [530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0,
                     530.0],
     'BranchStatus': [1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1,
                      1],
     'Tap': [0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0,
             0.0],
     'Shift': [0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0,
               0.0],
     'BranchAngleMin': [-360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0,
                        -360.0],
     'BranchAngleMax': [360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0,
                        360.0],
     'GenCostModel': [2, 2, 2, 2, 2, 2, 2],
     'GenStartupCost': [57.385, 65.923, 74.462, 71.5, 80.038, 88.577, 85.615],
     'GenShutdownCost': [14.346, 16.481, 18.616, 17.875, 20.009, 22.144, 21.404],
     'GenCostNCost': [3, 3, 3, 3, 3, 3, 3],
     'GenQuadraticCost': [0.00092, 0.00114, 0.00136, 0.00158, 0.0018, 0.0007, 0.00092],
     'GenMarginalCost': [21.072, 23.078, 25.155, 27.739, 29.718, 31.781, 19.017],
     'GenNoLoadCost': [12.702, 15.831, 18.96, 10.044, 13.174, 16.303, 17.387],
     'BaseMVA': 100.0,
     'NumPeriods': 24,
     'LoadShape': [0.6,
                   0.56,
                   0.53,
                   0.52,
                   0.55,
                   0.65,
                   0.81,
                   0.96,
                   1.08,
                   1.12,
                   1.09,
                   1.02,
                   0.96,
                   0.92,
                   0.91,
                   0.96,
                   1.05,
                   1.14,
                   1.18,
                   1.1,
                   1.0,
                   0.88,
                   0.76,
                   0.65],
     'ReserveFraction': 0.05}
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
