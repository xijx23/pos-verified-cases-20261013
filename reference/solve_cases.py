"""Deterministic reference models; only desc.txt and the case workbook are inputs."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import time

import numpy as np
import openpyxl
from gurobipy import GRB, Model, quicksum

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
CONVENTIONS = {
    'input': 'data.xlsx if present, otherwise the sole case-named xlsx; no other artifacts read',
    'time': 'load array[0] is operating period 1; generation in period 1 is NOT fixed to zero',
    'initial_status': 'explicit desc status, otherwise all off; only used in commitment transition',
    'initial_ramp': 'no pre-horizon ramp when pre-horizon generation is not specified',
    'startup_ramp': 'p[t]-p[t-1] <= RU*u[t-1]+PMIN*su[t]; symmetric shutdown',
    'minimum_times': 'rolling startup/shutdown sums; horizon is truncated, no invented terminal obligations',
    'missing_pmin': 'empty PMIN cells in case300 interpreted as 0 by user approval',
    'missing_ramp': 'no ramp added where description provides none',
    'case39_cost': 'full quadratic fuel from Gencost by user approval',
    'wind_fuel': 'linear COST_2*p for all wind FCUC cases by explicit user approval',
    'n1_unspecified': 'fixed base dispatch when redispatch is not specified',
    'robust': 'the listed up/down reserve coverage and unit deliverability constraints; no invented uncertainty set',
    'base_mva': '100 MVA when the workbook has no system base; MATPOWER convention',
    'network': 'active branches only; standard DC tap and phase shift except case300 explicit no-tap formula',
    'result': 'one key objective_value; INFEASIBLE only after solver proof; no time-limit incumbent published',
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(text: str, pattern: str, default=None):
    match = re.search(pattern, text, re.I)
    if match:
        return float(match.group(1))
    if default is not None:
        return default
    raise ValueError(f'Missing description parameter: {pattern}')


def literal(text: str, name: str):
    match = re.search(rf'{name}\s*=\s*(\[[^]]+\])', text)
    if not match:
        raise ValueError(f'Missing {name}')
    return ast.literal_eval(match.group(1))


def ratios(line: str) -> list[float]:
    # Backticks hold symbols as well as scalar values; only accept numeric ones.
    return [float(m.group(1)) / (100 if m.group(2) else 1)
            for m in re.finditer(r'`?(0\.\d+|\d+(?:\.\d+)?)\s*(%)?`?', line)
            if float(m.group(1)) < 1 or m.group(2)]


def read_case(folder: Path) -> dict:
    desc_path = folder / 'desc.txt'
    text = desc_path.read_text(encoding='utf-8-sig')
    files = sorted(folder.glob('*.xlsx'))
    workbook_path = folder / 'data.xlsx'
    if not workbook_path.exists():
        if len(files) != 1:
            raise ValueError(f'Expected one input workbook, found {len(files)}')
        workbook_path = files[0]
    workbook = openpyxl.load_workbook(workbook_path, data_only=True)
    tables = {}
    for name in ('Bus', 'Gen', 'Branch', 'Gencost'):
        rows = list(workbook[name].values)
        tables[name] = [dict(zip(rows[0], row)) for row in rows[1:] if row[0] is not None]
    workbook.close()
    if len(tables['Gen']) != len(tables['Gencost']):
        raise ValueError('Generator / cost row mismatch')
    for gen in tables['Gen']:
        if gen['PMIN'] is None:
            if folder.name != 'scuc_quad_reserve_case300':
                raise ValueError('Missing PMIN')
            gen['PMIN'] = 0.0
    arrays = [ast.literal_eval(s) for s in re.findall(r'```text\s*(\[[^]]+\])', text)]
    load = arrays[0]
    family = folder.name.rsplit('_case', 1)[0]
    ramp_match = re.search(r'(0\.\d+)\s*\*\s*GenPMax', text)
    ramp = float(ramp_match.group(1)) if ramp_match else None
    settings = {'family': family, 'load': load, 'ramp': ramp,
                'quadratic': family in ('ed_quadratic', 'scuc_quad_reserve') or
                (family == 'uc_emission_cap' and ('二次燃料' in text or folder.name.endswith('case39')))}
    is_uc = family not in ('ed_quadratic', 'opf_load_shedding')
    if is_uc:
        settings['up'] = int(number(text, r'(?:minimum up time\s*(?:为)?|最小开机(?:时间)?\s*(?:为)?|MinUpTime\s*=)\s*`?\s*(\d+)'))
        settings['down'] = int(number(text, r'(?:minimum down time\s*(?:为)?|最小停机(?:时间)?\s*(?:为)?|MinDownTime\s*=)\s*`?\s*(\d+)'))
        settings['initial_online'] = '初始机组状态使用表格' in text
    reserve_lines = [line for line in text.splitlines() if
                     ('备用' in line or 'reserve factor' in line) and
                     ('总' in line or 'spinning' in line or '旋转' in line or '备用需求' in line)]
    settings['reserve'] = 0.0
    if family in ('ed_quadratic', 'scuc_quad_reserve', 'scuc_n1', 'scuc_zonal_reserve', 'uc_piecewise_cost', 'uc_emission_cap'):
        if 'ReserveFactor =' in text:
            settings['reserve'] = number(text, r'ReserveFactor\s*=\s*([\d.]+)')
        else:
            for line in reserve_lines:
                values = ratios(line)
                if values:
                    settings['reserve'] = values[0]
                    break
    if family == 'opf_load_shedding':
        settings['shed_cost'] = number(text, r'SheddingPenalty\s*=\s*([\d.]+)',
                                       number(text, r'削负荷惩罚为\s*`?([\d.]+)', 10000))
        settings['dr_cost'] = number(text, r'DRCost\s*=\s*([\d.]+)', 0)
    if family == 'uc_piecewise_cost':
        segment_count = number(text, r'NumSegments\s*=\s*(\d+)',
                               number(text, r'均分为\s*(\d+)\s*段', 3))
        settings['segments'] = int(segment_count)
        settings['increments'] = [0, number(text, r'MarginalCostIncrement2\s*=\s*([\d.]+)',
                                           number(text, r'第\s*2\s*段[^\n]*?\+\s*([\d.]+)', 0)),
                                  number(text, r'MarginalCostIncrement3\s*=\s*([\d.]+)',
                                         number(text, r'第\s*3\s*段[^\n]*?\+\s*([\d.]+)', 0))]
        if settings['segments'] == 4:
            settings['increments'].append(number(text, r'第 4 段[^\n]*?\+\s*([\d.]+)'))
    if family == 'uc_emission_cap':
        settings['emission_rates'] = arrays[1]
        settings['emission_cap'] = number(text, r'EmissionCap\s*=\s*([\d.]+)',
                                          number(text, r'全周期排放上限为\s*([\d.]+)', 0))
        settings['carbon_cost'] = number(text, r'CarbonPrice\s*=\s*([\d.]+)',
                                         number(text, r'碳成本为\s*([\d.]+)', 0))
    if family == 'scuc_zonal_reserve':
        if 'ZoneReserveRatio' in text:
            settings['zones'] = literal(text, 'ZoneReserveRatio')
        else:
            zone_line = next(line for line in text.splitlines() if '本地备用分别' in line)
            settings['zones'] = ratios(zone_line)
        settings['reserve_cost'] = number(text, r'ReserveCost\s*=\s*([\d.]+)',
                                          number(text, r'备用持有成本为\s*([\d.]+)', 0))
    if family == 'robust_uc_load_uncertainty':
        settings['uncertainty'] = number(text, r'LoadUncertaintyFactor\s*=\s*([\d.]+)')
        settings['up_cost'] = number(text, r'ReserveUpCost\s*=\s*([\d.]+)',
                                     number(text, r'上备用成本为\s*([\d.]+)', 0))
        settings['down_cost'] = number(text, r'ReserveDownCost\s*=\s*([\d.]+)',
                                       number(text, r'下备用成本为\s*([\d.]+)', 0))
    if family.startswith('fcuc'):
        wind_line = next(line for line in text.splitlines() if 'wind bus' in line)
        settings['wind_buses'] = [int(s) for s in re.findall(r'bus\s+(\d+)', wind_line)]
        settings['wind_max'] = literal(text, 'WindPMax')
        settings['wind_shape'] = arrays[1]
        if len(settings['wind_buses']) != len(settings['wind_max']):
            raise ValueError('Wind bus / capacity mismatch')
        line = next(line for line in text.splitlines() if '上备用' in line and '覆盖' in line and ratios(line))
        values = ratios(line)
        settings['wind_reserve_load'], settings['wind_reserve_wind'] = values[:2]
        settings['curt_cost'] = number(text, r'弃风惩罚为\s*`?([\d.]+)')
        if family == 'fcuc_stochastic_wind':
            settings['multipliers'] = literal(text, 'WindScenarioMultiplier')
            settings['probabilities'] = literal(text, 'ScenarioProbability')
            settings['shed_cost'] = number(text, r'负荷削减惩罚为\s*`?([\d.]+)')
            if abs(sum(settings['probabilities']) - 1) > 1e-12:
                raise ValueError('Scenario probabilities do not sum to 1')
        else:
            line = next(line for line in text.splitlines() if '下备用' in line and '覆盖' in line and ratios(line))
            settings['wind_down'] = ratios(line)[-1]
    if family == 'scuc_n1':
        settings['redispatch'] = number(text, r'(0\.\d+)\s*\*\s*GenPMax[^\n]*(?:再调度|偏离)', 0)
        if '快速再调度' in text and settings['redispatch'] == 0:
            settings['redispatch'] = number(text, r'不超过\s*`?(0\.\d+)\s*\*\s*GenPMax', 0)
        settings['contingency_limit'] = int(number(text, r'前\s*(\d+)\s*条', 0))
        settings['largest_unit_reserve'] = '最大在线机组容量' in text
    return {'name': folder.name, 'folder': folder, 'text': text, 'tables': tables,
            'settings': settings, 'inputs': {str(desc_path): digest(desc_path), str(workbook_path): digest(workbook_path)}}


def outage_factors(buses: list[dict], branches: list[dict]) -> dict[int, np.ndarray]:
    """Exact fixed-injection LODF for connected, zero-phase-shift DC networks.

    Islanding outages are deliberately omitted and use explicit nodal equations.
    """
    index = {int(b['BUS_I']): k for k,b in enumerate(buses)}
    incidence = np.zeros((len(branches),len(buses)))
    susceptance = np.zeros(len(branches))
    for k,br in enumerate(branches):
        if not br['BR_STATUS']:
            continue
        if float(br['SHIFT'] or 0) != 0:
            return {}
        incidence[k,index[int(br['F_BUS'])]] = 1
        incidence[k,index[int(br['T_BUS'])]] = -1
        susceptance[k] = 100/float(br['BR_X'])/(float(br['TAP'] or 0) or 1)
    laplacian = incidence.T @ (susceptance[:,None]*incidence)
    try:
        transfer = (susceptance[:,None]*incidence[:,1:]) @ np.linalg.solve(laplacian[1:,1:],incidence[:,1:].T)
    except np.linalg.LinAlgError:
        return {}
    factors = {}
    for k in range(len(branches)):
        denominator = 1-transfer[k,k]
        if branches[k]['BR_STATUS'] and abs(denominator) > 1e-8:
            vector = transfer[:,k]/denominator
            vector[k] = -1
            factors[k+1] = vector
    return factors


def build_model(case: dict, compact_n1: bool = True, outages_override: list[int] | None = None):
    s, tables = case['settings'], case['tables']
    family = s['family']
    buses, gens, branches, costs = (tables[k] for k in ('Bus', 'Gen', 'Branch', 'Gencost'))
    B = [int(b['BUS_I']) for b in buses]
    I = range(1, len(gens) + 1)
    T = range(1, len(s['load']) + 1)
    L = range(1, len(branches) + 1)
    uc = family not in ('ed_quadratic', 'opf_load_shedding')
    stochastic = family == 'fcuc_stochastic_wind'
    S = range(1, len(s.get('probabilities', [1])) + 1)
    prob = s.get('probabilities', [1])
    m = Model(case['name'])
    m.Params.OutputFlag = 0
    m.Params.Threads = 8
    m.Params.Seed = 0
    m.Params.FeasibilityTol = 1e-8
    m.Params.OptimalityTol = 1e-8
    m.Params.IntFeasTol = 1e-9
    m.Params.MIPGap = 0
    m.Params.MIPGapAbs = 1e-6
    m.Params.BarConvTol = 1e-10
    m.Params.NumericFocus = 1
    p = m.addVars(I, T, S, lb=0, name='p')
    u = m.addVars(I, T, vtype=GRB.BINARY, name='u') if uc else None
    su = m.addVars(I, T, vtype=GRB.BINARY, name='su') if uc else None
    sd = m.addVars(I, T, vtype=GRB.BINARY, name='sd') if uc else None
    objective = 0
    for i in I:
        g, c = gens[i - 1], costs[i - 1]
        lo, hi = float(g['PMIN']), float(g['PMAX'])
        on = int(g['GEN_STATUS'])
        if lo < 0 or hi < lo:
            raise ValueError(f'Invalid generation bounds for {i}')
        if uc:
            initial = on if s['initial_online'] else 0
            for t in T:
                u[i, t].UB = on
                previous = u[i, t - 1] if t > 1 else initial
                m.addConstr(su[i, t] - sd[i, t] == u[i, t] - previous, name=f'transition[{i},{t}]')
                m.addConstr(su[i, t] + sd[i, t] <= 1, name=f'exclusive[{i},{t}]')
                m.addConstr(quicksum(su[i, k] for k in range(max(1, t-s['up']+1), t+1)) <= u[i, t], name=f'minup[{i},{t}]')
                m.addConstr(quicksum(sd[i, k] for k in range(max(1, t-s['down']+1), t+1)) <= 1-u[i, t], name=f'mindown[{i},{t}]')
                objective += float(c['COST_1']) * u[i,t] + float(c['STARTUP']) * su[i,t] + float(c['SHUTDOWN']) * sd[i,t]
        for t in T:
            for scene in S:
                v = p[i,t,scene]
                state = u[i,t] if uc else on
                m.addConstr(v >= lo*state, name=f'pmin[{i},{t},{scene}]')
                m.addConstr(v <= hi*state, name=f'pmax[{i},{t},{scene}]')
                if t > 1 and s['ramp'] is not None:
                    ramp = s['ramp'] * hi
                    rise = ramp*u[i,t-1] + lo*su[i,t] if uc else ramp
                    fall = ramp*u[i,t] + lo*sd[i,t] if uc else ramp
                    m.addConstr(v-p[i,t-1,scene] <= rise, name=f'rampup[{i},{t},{scene}]')
                    m.addConstr(p[i,t-1,scene]-v <= fall, name=f'rampdown[{i},{t},{scene}]')
                if family == 'uc_piecewise_cost':
                    n = s['segments']
                    seg = m.addVars(range(1,n+1), lb=0, name=f'seg[{i},{t}]')
                    m.addConstr(v == lo*u[i,t]+quicksum(seg.values()), name=f'segsum[{i},{t}]')
                    objective += float(c['COST_2'])*lo*u[i,t]
                    for k in range(1,n+1):
                        m.addConstr(seg[k] <= (hi-lo)/n*u[i,t], name=f'segwidth[{i},{t},{k}]')
                        objective += (float(c['COST_2'])+s['increments'][k-1])*seg[k]
                else:
                    fuel = float(c['COST_2'])*v
                    if s['quadratic']:
                        if float(c['COST_3']) < 0:
                            raise ValueError('Nonconvex quadratic cost')
                        fuel += float(c['COST_3'])*v*v
                    if family == 'ed_quadratic':
                        fuel += float(c['COST_1'])
                    objective += prob[scene-1]*fuel
    wind = family.startswith('fcuc')
    J = range(1,len(s.get('wind_buses',[]))+1)
    w = m.addVars(J,T,S,lb=0,name='wind') if wind else None
    curt = m.addVars(J,T,S,lb=0,name='curt') if wind else None
    shed = m.addVars(B,T,S,lb=0,name='shed') if stochastic or family == 'opf_load_shedding' else None
    dr = m.addVars(B,T,S,lb=0,name='dr') if s.get('dr_cost') else None
    for t in T:
        for scene in S:
            for j in J:
                avail = s['wind_max'][j-1]*s['wind_shape'][t-1]*s.get('multipliers',[1])[scene-1]
                m.addConstr(w[j,t,scene]+curt[j,t,scene] == avail, name=f'windavail[{j},{t},{scene}]')
                objective += prob[scene-1]*s['curt_cost']*curt[j,t,scene]
            for b in buses:
                bid = int(b['BUS_I'])
                load = float(b['PD'])*s['load'][t-1]
                if shed is not None:
                    if load < 0:
                        raise ValueError('Negative load with shedding')
                    shed[bid,t,scene].UB = load
                    objective += prob[scene-1]*s['shed_cost']*shed[bid,t,scene]
                if dr is not None:
                    dr[bid,t,scene].UB = 0.05*load
                    objective += s['dr_cost']*dr[bid,t,scene]

    def network(dispatch, label, scene=1, outage=None, emergency=1.0):
        theta = m.addVars(B,T,lb=-GRB.INFINITY,name=f'theta_{label}')
        flow = m.addVars(L,T,lb=-GRB.INFINITY,name=f'flow_{label}')
        for t in T:
            for l in L:
                br = branches[l-1]
                if not int(br['BR_STATUS']) or l == outage:
                    flow[l,t].LB = flow[l,t].UB = 0
                    continue
                x = float(br['BR_X'])
                if x == 0:
                    raise ValueError(f'Zero branch reactance at {l}')
                # case300 expressly gives a no-tap DC equation.
                tap = 1 if case['name'] == 'scuc_quad_reserve_case300' else (float(br['TAP'] or 0) or 1)
                shift = 0 if case['name'] == 'scuc_quad_reserve_case300' else math.radians(float(br['SHIFT'] or 0))
                m.addConstr(flow[l,t] == 100/x/tap*(theta[int(br['F_BUS']),t]-theta[int(br['T_BUS']),t]-shift), name=f'dc_{label}[{l},{t}]')
                rate = float(br['RATE_A'])
                if rate > 0:
                    flow[l,t].LB = -emergency*rate
                    flow[l,t].UB = emergency*rate
            for b in buses:
                bid = int(b['BUS_I'])
                if int(b['BUS_TYPE']) == 3:
                    theta[bid,t].LB = theta[bid,t].UB = 0
                injection = quicksum(dispatch[i,t] for i in I if int(gens[i-1]['GEN_BUS']) == bid)
                if wind:
                    injection += quicksum(w[j,t,scene] for j in J if s['wind_buses'][j-1] == bid)
                if shed is not None:
                    injection += shed[bid,t,scene]
                if dr is not None:
                    injection += dr[bid,t,scene]
                net = quicksum(flow[l,t] for l in L if int(branches[l-1]['F_BUS']) == bid)-quicksum(flow[l,t] for l in L if int(branches[l-1]['T_BUS']) == bid)
                m.addConstr(injection-float(b['PD'])*s['load'][t-1] == net, name=f'balance_{label}[{bid},{t}]')
        return theta, flow

    base_flows = {}
    for scene in S:
        _,base_flows[scene] = network({(i,t):p[i,t,scene] for i in I for t in T}, f'base{scene}', scene)
    explicit_up = family in ('robust_uc_load_uncertainty','fcuc_wind_reserve','scuc_zonal_reserve')
    rup = m.addVars(I,T,S,lb=0,name='rup') if explicit_up else None
    rdn = m.addVars(I,T,S,lb=0,name='rdn') if family in ('robust_uc_load_uncertainty','fcuc_wind_reserve') else None
    for t in T:
        total_load = sum(float(b['PD']) for b in buses)*s['load'][t-1]
        for scene in S:
            headroom = quicksum(float(gens[i-1]['PMAX'])*(u[i,t] if uc else int(gens[i-1]['GEN_STATUS']))-p[i,t,scene] for i in I)
            if s['reserve']:
                m.addConstr(headroom >= s['reserve']*total_load, name=f'reserve[{t},{scene}]')
            if stochastic:
                forecast = sum(s['wind_max'])*s['wind_shape'][t-1]*s['multipliers'][scene-1]
                m.addConstr(headroom >= s['wind_reserve_load']*total_load+s['wind_reserve_wind']*forecast, name=f'scenarioreserve[{t},{scene}]')
            if rup is not None:
                for i in I:
                    hi, lo = float(gens[i-1]['PMAX']), float(gens[i-1]['PMIN'])
                    m.addConstr(rup[i,t,scene] <= hi*u[i,t]-p[i,t,scene],name=f'rupcap[{i},{t},{scene}]')
                    m.addConstr(rup[i,t,scene] <= s['ramp']*hi*u[i,t],name=f'rupramp[{i},{t},{scene}]')
                    if rdn is not None:
                        m.addConstr(rdn[i,t,scene] <= p[i,t,scene]-lo*u[i,t],name=f'rdncap[{i},{t},{scene}]')
                        m.addConstr(rdn[i,t,scene] <= s['ramp']*hi*u[i,t],name=f'rdnramp[{i},{t},{scene}]')
                up_total = quicksum(rup[i,t,scene] for i in I)
                if family == 'scuc_zonal_reserve':
                    m.addConstr(up_total >= s['reserve']*total_load,name=f'systemreserve[{t}]')
                    for z, ratio in enumerate(s['zones'],1):
                        zone_load = sum(float(b['PD']) for b in buses if int(b['BUS_AREA']) == z)*s['load'][t-1]
                        zone_buses = {int(b['BUS_I']) for b in buses if int(b['BUS_AREA']) == z}
                        m.addConstr(quicksum(rup[i,t,scene] for i in I if int(gens[i-1]['GEN_BUS']) in zone_buses) >= ratio*zone_load,name=f'zonereserve[{z},{t}]')
                    objective += s['reserve_cost']*up_total
                else:
                    down_total = quicksum(rdn[i,t,scene] for i in I)
                    if family == 'robust_uc_load_uncertainty':
                        up_need = down_need = s['uncertainty']*total_load
                        objective += s['up_cost']*up_total+s['down_cost']*down_total
                    else:
                        forecast = sum(s['wind_max'])*s['wind_shape'][t-1]
                        up_need = s['wind_reserve_load']*total_load+s['wind_reserve_wind']*forecast
                        down_need = s['wind_down']*forecast
                    m.addConstr(up_total >= up_need,name=f'upcoverage[{t},{scene}]')
                    m.addConstr(down_total >= down_need,name=f'downcoverage[{t},{scene}]')
    if family == 'uc_emission_cap':
        rates = [s['emission_rates'][(i-1)%len(s['emission_rates'])] for i in I]
        emissions = quicksum(rates[i-1]*p[i,t,1] for i in I for t in T)
        m.addConstr(emissions <= s['emission_cap'],name='emissioncap')
        objective += s['carbon_cost']*emissions
    if family == 'scuc_n1':
        factors = outage_factors(buses,branches) if compact_n1 and not s['redispatch'] else {}
        outages = [l for l in L if int(branches[l-1]['BR_STATUS'])]
        if s['contingency_limit']:
            outages = sorted(outages,key=lambda l: (float(branches[l-1]['RATE_A']), l))[:s['contingency_limit']]
        if outages_override is not None:
            outages = outages_override
        for outage in outages:
            if outage in factors:
                for l in L:
                    br = branches[l-1]
                    if l == outage or not br['BR_STATUS'] or float(br['RATE_A']) <= 0:
                        continue
                    coefficient = float(factors[outage][l-1])
                    for t in T:
                        post_flow = base_flows[1][l,t]+coefficient*base_flows[1][outage,t]
                        limit = 1.15*float(br['RATE_A'])
                        m.addConstr(post_flow <= limit,name=f'n1upper[{outage},{l},{t}]')
                        m.addConstr(post_flow >= -limit,name=f'n1lower[{outage},{l},{t}]')
                continue
            dispatch = {(i,t):p[i,t,1] for i in I for t in T}
            if s['redispatch']:
                pc = m.addVars(I,T,lb=0,name=f'pc_{outage}')
                for i in I:
                    hi, lo = float(gens[i-1]['PMAX']), float(gens[i-1]['PMIN'])
                    for t in T:
                        m.addConstr(pc[i,t] >= lo*u[i,t],name=f'pcmin[{outage},{i},{t}]')
                        m.addConstr(pc[i,t] <= hi*u[i,t],name=f'pcmax[{outage},{i},{t}]')
                        m.addConstr(pc[i,t]-p[i,t,1] <= s['redispatch']*hi,name=f'pcup[{outage},{i},{t}]')
                        m.addConstr(p[i,t,1]-pc[i,t] <= s['redispatch']*hi,name=f'pcdown[{outage},{i},{t}]')
                dispatch = pc
            network(dispatch,f'outage{outage}',outage=outage,emergency=1.15)
        if s['largest_unit_reserve']:
            for t in T:
                headroom = quicksum(float(gens[i-1]['PMAX'])*u[i,t]-p[i,t,1] for i in I)
                for i in I:
                    m.addConstr(headroom >= float(gens[i-1]['PMAX'])*u[i,t],name=f'largestreserve[{i},{t}]')
    m.setObjective(objective, GRB.MINIMIZE)
    m.update()
    return m


def solve(case: dict, time_limit: float = 600, publish: bool = True) -> dict:
    start = time.monotonic()
    log_dir = HERE / 'evidence' / case['name']
    log_dir.mkdir(parents=True,exist_ok=True)
    corrective = case['settings']['family'] == 'scuc_n1' and case['settings']['redispatch'] > 0
    active_outages = []
    m = build_model(case,outages_override=active_outages if corrective else None)
    m.Params.LogFile = str(log_dir / 'solver.log')
    m.Params.OutputFlag = 1
    m.Params.LogToConsole = 0
    m.Params.TimeLimit = time_limit
    m.write(str(log_dir / 'model.lp'))
    m.optimize()
    recourse = {}
    if corrective:
        all_outages = [k for k,br in enumerate(case['tables']['Branch'],1) if br['BR_STATUS']]
        while m.Status == GRB.OPTIMAL:
            fixed = {v.VarName:v.X for v in m.getVars() if v.VarName.startswith(('u[','p['))}
            failed = None
            recourse = {}
            for outage in all_outages:
                check = build_model(case,outages_override=[outage])
                for name,value in fixed.items():
                    var = check.getVarByName(name)
                    var.LB = var.UB = round(value) if name.startswith('u[') else value
                check.setObjective(0)
                check.Params.TimeLimit = time_limit
                check.optimize()
                if check.Status != GRB.OPTIMAL:
                    if check.Status not in (GRB.INFEASIBLE,GRB.INF_OR_UNBD):
                        raise ValueError(f'Contingency feasibility check did not finish: {outage}, {check.Status}')
                    failed = outage
                    check.dispose()
                    break
                recourse.update({v.VarName:v.X for v in check.getVars() if
                                 v.VarName.startswith((f'pc_{outage}[',f'theta_outage{outage}[',f'flow_outage{outage}['))})
                check.dispose()
            if failed is None:
                break
            if failed in active_outages:
                raise ValueError('Numerical inconsistency in fixed-dispatch feasibility check')
            active_outages.append(failed)
            m.dispose()
            m = build_model(case,outages_override=active_outages)
            m.Params.LogFile = str(log_dir/'solver.log')
            m.Params.OutputFlag = 1
            m.Params.LogToConsole = 0
            m.Params.TimeLimit = time_limit
            m.optimize()
        m.write(str(log_dir/'model.lp'))
        if m.Status == GRB.OPTIMAL:
            (log_dir/'contingency_recourse.json').write_text(json.dumps(recourse),encoding='utf-8')
    record = {'case':case['name'],'settings':case['settings'],'inputs':case['inputs'],
              'solver':'Gurobi 12.0.3','status':m.Status,'runtime_seconds':time.monotonic()-start,
              'variables':m.NumVars,'constraints':m.NumConstrs, 'published':False,
              'contingency_certificate': {'method':'optimal relaxed master plus feasible LP witness for every outage',
                                          'active_outages':active_outages,'witness_variables':len(recourse)} if corrective else None}
    value = None
    if m.Status == GRB.OPTIMAL:
        record.update(objective=m.ObjVal, bound=m.ObjBound,
                      gap=m.MIPGap if m.IsMIP else 0,
                      constraint_violation=m.ConstrVio,bound_violation=m.BoundVio,
                      integer_violation=m.IntVio if m.IsMIP else 0)
        if max(record['constraint_violation'],record['bound_violation'],record['integer_violation']) > 1e-6:
            raise ValueError(f'Solution quality exceeds tolerance: {record}')
        value = m.ObjVal
        m.write(str(log_dir / 'solution.sol'))
    elif m.Status in (GRB.INFEASIBLE,GRB.INF_OR_UNBD):
        if m.Status == GRB.INF_OR_UNBD:
            m.Params.DualReductions = 0
            m.optimize()
            record['status'] = m.Status
        if m.Status == GRB.INFEASIBLE:
            m.computeIIS()
            m.write(str(log_dir / 'infeasible.ilp'))
            value = 'INFEASIBLE'
    else:
        if m.SolCount:
            record.update(incumbent=m.ObjVal,bound=m.ObjBound,gap=m.MIPGap if m.IsMIP else 0)
    if value is not None and publish:
        output = case['folder'] / 'stantard_value.json'
        backup = log_dir / 'original_result.json'
        before = log_dir / 'output_before.json'
        if not before.exists():
            if output.exists():
                backup.write_bytes(output.read_bytes())
            before.write_text(json.dumps({'existed':output.exists(),'sha256':digest(output) if output.exists() else None}),encoding='utf-8')
        output.write_text(json.dumps({'objective_value':value},ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
        assert json.loads(output.read_text(encoding='utf-8')) == {'objective_value':value}
        record.update(published=True,output=str(output),output_sha256=digest(output))
    (log_dir / 'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    m.dispose()
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', action='append')
    parser.add_argument('--time-limit',type=float,default=600)
    parser.add_argument('--audit-only',action='store_true')
    parser.add_argument('--no-publish',action='store_true')
    args = parser.parse_args()
    cases = sorted(p for p in (ROOT/'problems').iterdir() if p.is_dir() and (p/'desc.txt').exists() and p.name != 'demo')
    if args.case:
        cases = [p for p in cases if p.name in args.case]
        if len(cases) != len(set(args.case)):
            raise ValueError('Unknown case name')
    summary = {'conventions':CONVENTIONS,'command':__import__('sys').argv,'cases':[]}
    for folder in cases:
        try:
            case = read_case(folder)
            record = {'case':folder.name,'settings':case['settings'],'inputs':case['inputs']} if args.audit_only else solve(case,args.time_limit,not args.no_publish)
            summary['cases'].append(record)
            print(folder.name,json.dumps(record.get('objective', record.get('status','AUDITED'))),flush=True)
        except Exception as exc:
            summary['cases'].append({'case':folder.name,'error':str(exc),'published':False})
            print(folder.name,'ERROR',str(exc),flush=True)
        (HERE/('audit.json' if args.audit_only else 'summary.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    if not args.audit_only and any(not r.get('published') for r in summary['cases']) and not args.no_publish:
        return 1
    return int(any('error' in r for r in summary['cases']))


if __name__ == '__main__':
    raise SystemExit(main())
