"""Full-information MILP based on Appendix C, TR-B 214, 103606.

Input: --input path/to/instance.json (schema: example.json), or
       --data-dir path/to/data --passenger-file passengers.csv.
Output: --output path/to/new_results; default: results/<timestamp>/.
Python API: load_json(path), build_model(instance), model.optimize(),
            validate_solution(built).
Time unit: minutes. See README_CN.md / README_EN.md for input fields and crowding modes.
"""
from __future__ import annotations

import argparse
import ast
import bisect
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import reduce
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time


def D(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f'Non-finite numeric value: {value}')
    return result


@dataclass(frozen=True)
class Stock:
    id: str
    kind: str
    capacity: Decimal
    route: int = 0
    arrival: Decimal | None = None
    original_departure: Decimal = Decimal(0)


@dataclass(frozen=True)
class Group:
    id: int
    route: int
    destination: str
    weight: Decimal
    enter: Decimal
    leave: Decimal
    original_departure: Decimal
    original_arrival: Decimal | None


@dataclass(frozen=True)
class Plan:
    route: int
    id: int
    # Offsets from target-station departure; two event types are independent.
    arrival: dict[str, Decimal]
    departure: dict[str, Decimal]


@dataclass
class Instance:
    times: list[Decimal]
    stocks: list[Stock]
    groups: list[Group]
    plans: list[Plan]
    headway: Decimal = Decimal(5)
    crowd_limit: Decimal = Decimal(1500)
    service_weight: Decimal = Decimal(1)
    waiting_weight: Decimal = Decimal('.001')
    delay_weight: Decimal = Decimal('.00001')

    def validate(self):
        if not self.times or self.times != sorted(set(self.times)):
            raise ValueError('times must be nonempty, strictly increasing and unique')
        if len({s.id for s in self.stocks}) != len(self.stocks):
            raise ValueError('Duplicate stock ID')
        if len({g.id for g in self.groups}) != len(self.groups):
            raise ValueError('Duplicate passenger-group ID')
        if len({(p.route,p.id) for p in self.plans}) != len(self.plans):
            raise ValueError('Duplicate route/plan')
        routes={p.route for p in self.plans}
        if 0 in routes or self.headway < 0 or self.crowd_limit < 0:
            raise ValueError('Invalid route, headway or crowding limit')
        for p in self.plans:
            if not p.arrival or p.arrival.keys()!=p.departure.keys():
                raise ValueError('Each served station requires arrival AND departure offsets')
            if any(p.arrival[s]<0 or p.departure[s]<p.arrival[s] for s in p.arrival):
                raise ValueError('Invalid station offsets')
        for s in self.stocks:
            if s.kind not in ('Flexible','Restricted') or s.capacity<0:
                raise ValueError(f'Invalid stock {s.id}')
            if s.kind=='Restricted' and (s.arrival is None or s.route not in routes):
                raise ValueError(f'Restricted stock {s.id} lacks arrival time or valid route')
        missing=[]
        for g in self.groups:
            if g.weight<=0 or g.route not in routes|{0}:
                raise ValueError(f'Invalid passenger group {g.id}')
            # Presence and eligibility use the input time windows unchanged.
            if g.route!=0 and g.original_arrival is None:
                missing.append(g.id)
        if missing:
            raise ValueError('Missing original destination arrival for affected group IDs: '+str(missing)+
                             '. No departure-time fallback is allowed; supply --arrival-overrides.')


@dataclass(frozen=True)
class Action:
    stock: str
    route: int
    plan: int
    time: Decimal


def present(g, t):
    return g.enter <= t < (g.original_departure if g.route==0 else g.leave)


def lattice(values):
    values=list(values)
    places=max([max(0,-v.as_tuple().exponent) for v in values]+[0])
    scale=10**places
    integers=[int(v*scale) for v in values]
    divisor=reduce(math.gcd,integers,0) or 1
    unit=Decimal(divisor)/Decimal(scale)
    if max([abs(n//divisor) for n in integers]+[0])>2**52:
        raise ValueError('Scaled integers exceed exact double-integer range; revise input precision explicitly')
    return unit


def candidates(instance):
    actions=[]
    for t in instance.times:
        for s in instance.stocks:
            if s.kind=='Restricted' and not s.arrival<t:
                continue
            for p in instance.plans:
                if s.kind=='Flexible' or s.route==p.route:
                    actions.append(Action(s.id,p.route,p.id,t))
    return actions


def conflict_threshold(p, q, headway):
    limits=[headway]
    for s in p.arrival.keys() & q.arrival.keys():
        limits.extend([p.arrival[s]-q.arrival[s]+headway,
                       p.departure[s]-q.departure[s]+headway])
    return max(limits)


def stock_choice(instance, route, t, used):
    restricted=[s for s in instance.stocks if s.id not in used and s.kind=='Restricted'
                and s.route==route and s.arrival<t]
    if restricted:
        return min(restricted,key=lambda s:(s.arrival,s.id))
    return min((s for s in instance.stocks if s.id not in used and s.kind=='Flexible'),
               key=lambda s:(s.original_departure,s.id),default=None)


@dataclass
class BuiltModel:
    model: object
    instance: Instance
    actions: list
    x: object
    z: dict
    pairs_by_action: dict
    quantum: Decimal
    crowding: str


def build_model(instance, *, crowding='appendix-c', env=None, output_flag=False):
    import gurobipy as gp
    from gurobipy import GRB
    instance.validate()
    if crowding not in ('appendix-c','state-consistent'):
        raise ValueError('Unknown crowdedness convention')
    unit=lattice([g.weight for g in instance.groups]+[s.capacity for s in instance.stocks])
    W={g.id:float(g.weight) for g in instance.groups}
    K={s.id:float(s.capacity) for s in instance.stocks}
    groups={g.id:g for g in instance.groups}
    stocks={s.id:s for s in instance.stocks}
    plans={(p.route,p.id):p for p in instance.plans}
    actions=candidates(instance)
    by_time=defaultdict(list);by_stock_time=defaultdict(list);by_service=defaultdict(list)
    for a,act in enumerate(actions):
        by_time[act.time].append(a)
        by_stock_time[act.stock,act.time].append(a)
        by_service[act.route,act.plan,act.time].append(a)
    by_route=defaultdict(list)
    for g in instance.groups:
        if g.route!=0:by_route[g.route].append(g)
    for r in by_route:by_route[r].sort(key=lambda g:(g.enter,g.id))
    pa={};pg_time=defaultdict(list);pair_list=[]
    for a,act in enumerate(actions):
        p=plans[act.route,act.plan]
        eligible=[g.id for g in by_route[act.route]
                  if g.enter<=act.time<g.leave and g.destination in p.arrival]
        pa[a]=eligible
        for gid in eligible:
            pair_list.append((gid,a));pg_time[gid,act.time].append(a)
    m=gp.Model('Appendix_C',env=env)
    m.Params.OutputFlag=int(output_flag)
    m.Params.MIPGap=1e-6
    m.Params.FeasibilityTol=1e-9
    m.Params.IntFeasTol=1e-9
    m.Params.IntegralityFocus=1
    m.Params.NumericFocus=3
    m.Params.Seed=20260520
    x=m.addVars(len(actions),vtype=GRB.BINARY,name='x')
    z=m.addVars(pair_list,vtype=GRB.BINARY,name='z')
    for t,idx in by_time.items():m.addConstr(gp.quicksum(x[a] for a in idx)<=1,name=f'one_departure[{t}]')
    stock_before={}
    for s in instance.stocks:
        previous=gp.LinExpr(0)
        for ti,t in enumerate(instance.times):
            stock_before[s.id,t]=previous
            after=m.addVar(lb=0,ub=1,name=f'stock_cumulative[{s.id},{ti}]')
            m.addConstr(after==previous+gp.quicksum(x[a] for a in by_stock_time[s.id,t]),
                        name=f'stock_once_transition[{s.id},{ti}]')
            previous=after
    serve_before={}
    for g in instance.groups:
        if g.route==0:continue
        previous=gp.LinExpr(0)
        for ti,t in enumerate(instance.times):
            serve_before[g.id,t]=previous
            idx=pg_time[g.id,t]
            if idx:
                after=m.addVar(lb=0,ub=1,name=f'serve_cumulative[{g.id},{ti}]')
                m.addConstr(after==previous+gp.quicksum(z[g.id,a] for a in idx),
                            name=f'group_once_transition[{g.id},{ti}]')
                previous=after
    # Eq.12 identity selection, including the earlier flexible departure rule.
    # ID is the deterministic tie break when the paper's argmin is not unique.
    for a,act in enumerate(actions):
        own=stocks[act.stock]
        for s in instance.stocks:
            if s.id==own.id:continue
            precedes=False
            if s.kind=='Restricted' and s.route==act.route and s.arrival<act.time:
                precedes=(own.kind=='Flexible' or (s.arrival,s.id)<(own.arrival,own.id))
            elif s.kind=='Flexible' and own.kind=='Flexible':
                precedes=(s.original_departure,s.id)<(own.original_departure,own.id)
            if precedes:m.addConstr(x[a]<=stock_before[s.id,act.time],name=f'stock_priority[{a},{s.id}]')
    for a,act in enumerate(actions):
        cap=K[act.stock]
        gids=pa[a]
        load=gp.LinExpr(0)
        for position,gid in enumerate(gids):
            weight=W[gid]
            m.addConstr(z[gid,a]<=x[a],name=f'link[{gid},{a}]')
            residual=cap*x[a]-load
            m.addConstr(residual>=weight-weight*(1-z[gid,a]),name=f'C1[{gid},{a}]')
            M=max(cap,weight)+float(unit)
            m.addConstr(residual<=weight-float(unit)+M*(1-x[a]+serve_before[gid,act.time]+z[gid,a]),
                        name=f'C2[{gid},{a}]')
            cumulative=m.addVar(lb=0,ub=cap,name=f'boarded_load[{a},{position}]')
            m.addConstr(cumulative==load+weight*z[gid,a],name=f'C3_prefix[{gid},{a}]')
            load=cumulative
        m.addConstr(load<=cap*x[a],name=f'capacity[{a}]')
    # Precomputed signed target/arrival/departure conflicts. Aggregating stock
    # identities is exact here because there is at most one dispatch per time.
    service_expr={key:gp.quicksum(x[a] for a in idx) for key,idx in by_service.items()}
    profiles=sorted(plans)
    times_by_profile={p:sorted(t for r,n,t in by_service if (r,n)==p) for p in profiles}
    n_conflicts=0
    for pkey in profiles:
        for qkey in profiles:
            threshold=conflict_threshold(plans[pkey],plans[qkey],instance.headway)
            later_times=times_by_profile[qkey]
            for t in times_by_profile[pkey]:
                lo=bisect.bisect_right(later_times,t)
                hi=bisect.bisect_left(later_times,t+threshold)
                for u in later_times[lo:hi]:
                    m.addConstr(service_expr[*pkey,t]+service_expr[*qkey,u]<=1,
                                name=f'headway[{n_conflicts}]')
                    n_conflicts+=1
    for ti,t in enumerate(instance.times):
        baseline=sum((g.weight for g in instance.groups if present(g,t)),Decimal(0))
        terms=[float(g.weight)*serve_before[g.id,t] for g in instance.groups if g.route!=0
               and (crowding=='appendix-c' or present(g,t))]
        m.addConstr(float(baseline)-gp.quicksum(terms)<=float(instance.crowd_limit),name=f'crowding[{ti}]')
    obj=gp.LinExpr()
    for gid,a in pair_list:
        g=groups[gid];act=actions[a];p=plans[act.route,act.plan]
        wait=act.time-g.enter
        delay=max(Decimal(0),act.time+p.arrival[g.destination]-g.original_arrival)
        coefficient=g.weight*(instance.service_weight-instance.waiting_weight*wait-instance.delay_weight*delay)
        obj+=float(coefficient)*z[gid,a]
    m.setObjective(obj,GRB.MAXIMIZE)
    m.update()
    m._appendix_c_counts=dict(actions=len(actions),assignments=len(pair_list),headway_conflicts=n_conflicts,
                              variables=m.NumVars,constraints=m.NumConstrs)
    return BuiltModel(m,instance,actions,x,z,pa,unit,crowding)


def validate_solution(built):
    m=built.model;ins=built.instance
    groups={g.id:g for g in ins.groups};plans={(p.route,p.id):p for p in ins.plans}
    selected=sorted([a for a in range(len(built.actions)) if built.x[a].X>.5],key=lambda a:built.actions[a].time)
    served={};used=set();history=[];assignments=[];action_rows=[];errors=[]
    for a in selected:
        act=built.actions[a];p=plans[act.route,act.plan]
        stock=stock_choice(ins,act.route,act.time,used)
        if stock is None or stock.id!=act.stock:
            errors.append(f'Eq.12: stock selection at action {a}')
        for old in history:
            oldplan=plans[old.route,old.plan]
            if act.time<=old.time or act.time-old.time<conflict_threshold(oldplan,p,ins.headway):
                errors.append(f'Headway: {old} / {act}')
        capacity=next(s.capacity for s in ins.stocks if s.id==act.stock)
        expected=[]
        for gid in built.pairs_by_action[a]:
            g=groups[gid]
            if gid not in served and g.weight<=capacity:
                expected.append(gid);capacity-=g.weight
        actual=[gid for gid in built.pairs_by_action[a] if built.z[gid,a].X>.5]
        if actual!=expected:errors.append(f'Algorithm2: action {a}, MILP={actual}, replay={expected}')
        for gid in actual:
            g=groups[gid]
            if gid in served:errors.append(f'Duplicate assignment: group {gid}')
            served[gid]=act.time
            wait=g.weight*(act.time-g.enter)
            delay=g.weight*max(Decimal(0),act.time+p.arrival[g.destination]-g.original_arrival)
            assignments.append(dict(group_id=gid,action_id=a,stock=act.stock,route=act.route,plan=act.plan,
                                    departure=str(act.time),weight=str(g.weight),waiting=str(wait),delay=str(delay)))
        action_rows.append(dict(action_id=a,stock=act.stock,route=act.route,plan=act.plan,departure=str(act.time),
                                served_groups=len(actual),served_weight=str(sum((groups[g].weight for g in actual),Decimal(0)))))
        used.add(act.stock);history.append(act)
    for (gid,a),var in built.z.items():
        if var.X>.5 and a not in selected:errors.append(f'Unselected service assignment: {gid},{a}')
    crowd=[]
    for t in ins.times:
        baseline=sum((g.weight for g in ins.groups if present(g,t)),Decimal(0))
        printed=baseline-sum((groups[gid].weight for gid,dep in served.items() if dep<t),Decimal(0))
        physical=sum((g.weight for g in ins.groups if present(g,t) and not (g.id in served and served[g.id]<t)),Decimal(0))
        evaluated=printed if built.crowding=='appendix-c' else physical
        if evaluated>ins.crowd_limit:errors.append(f'Crowding at {t}: {evaluated}>{ins.crowd_limit}')
        crowd.append(dict(time=str(t),appendix_c_literal=str(printed),state_consistent=str(physical)))
    epd=sum((D(r['weight']) for r in assignments),Decimal(0))
    waiting=sum((D(r['waiting']) for r in assignments),Decimal(0))
    delay=sum((D(r['delay']) for r in assignments),Decimal(0))
    objective=ins.service_weight*epd-ins.waiting_weight*waiting-ins.delay_weight*delay
    if not math.isclose(float(objective),m.ObjVal,rel_tol=1e-9,abs_tol=1e-6):errors.append('Objective replay mismatch')
    return dict(passed=not errors,errors=errors,objective=str(objective),satisfied_epd=str(epd),
                weighted_waiting=str(waiting),weighted_delay=str(delay),actions=action_rows,assignments=assignments,
                crowding=crowd,negative_literal_times=sum(D(r['appendix_c_literal'])<0 for r in crowd),
                physical_overcrowding_times=sum(D(r['state_consistent'])>ins.crowd_limit for r in crowd))


def load_json(path):
    raw=json.loads(Path(path).read_text(encoding='utf-8'),parse_float=Decimal)
    stocks=[Stock(str(s['id']),s['kind'],D(s['capacity']),int(s.get('route',0)),
                  None if s.get('arrival') is None else D(s['arrival']),D(s.get('original_departure',0))) for s in raw['stocks']]
    groups=[Group(int(g['id']),int(g['route']),str(g['destination']),D(g['weight']),D(g['enter']),D(g['leave']),
                  D(g['original_departure']),None if g.get('original_arrival') is None else D(g['original_arrival'])) for g in raw['groups']]
    plans=[Plan(int(p['route']),int(p['id']),{s:D(v) for s,v in p['arrival'].items()},
                {s:D(v) for s,v in p['departure'].items()}) for p in raw['plans']]
    settings=raw.get('settings',{})
    ins=Instance([D(t) for t in raw['times']],stocks,groups,plans,
                 **{key:D(value) for key,value in settings.items()})
    ins.validate();return ins


def clock_minutes(value):
    match=re.fullmatch(r'\s*(\d+):(\d+):(\d+(?:\.\d+)?)\s*',str(value))
    return None if match is None else D(match[1])*60+D(match[2])+D(match[3])/60


def numeric_expression(raw):
    def walk(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):return D(node.value)
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            return walk(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
        if isinstance(node,ast.BinOp):
            left,right=walk(node.left),walk(node.right)
            if isinstance(node.op,ast.Add):return left+right
            if isinstance(node.op,ast.Sub):return left-right
            if isinstance(node.op,ast.Mult):return left*right
            if isinstance(node.op,ast.Div):return left/right
            if isinstance(node.op,ast.Pow) and right==int(right) and abs(right)<=20:return left**int(right)
        raise ValueError('Unsupported numeric expression: '+raw)
    return walk(ast.parse(raw,mode='eval').body)


def load_legacy(folder, passenger_file, arrival_overrides=None):
    import pandas as pd
    folder=Path(folder);settings={}
    for line in (folder/'scenario.txt').read_text(encoding='utf-8-sig').splitlines():
        line=line.split('#')[0].strip()
        if '=' in line:
            key,value=line.split('=',1)
            if key.strip()!='objective':settings[key.strip()]=numeric_expression(value.strip())
    stocks=[]
    for line in (folder/'Rolling_stock.txt').read_text(encoding='utf-8-sig').splitlines():
        if '&' not in line or '\\\\' not in line:continue
        parts=[re.sub(r'\\\\.*','',part).strip() for part in line.split('&')]
        if len(parts)<6 or parts[4] not in ('Flexible','Restricted'):continue
        stocks.append(Stock(parts[0],parts[4],D(parts[5]),int(parts[3]),clock_minutes(parts[1]),clock_minutes(parts[2])))
    plan_rows=defaultdict(list)
    with (folder/'stop_plan_times.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if not any(str(v or '').strip() for v in r.values()):continue
            # Original CSV includes total-runtime footer rows: ,,,572.6666667.
            if not any(r[k].strip() for k in ('route','plan','station')):continue
            plan_rows[int(r['route']),int(r['plan'])].append(r)
    plans=[]
    for (route,pid),rows in sorted(plan_rows.items()):
        elapsed=D(0);arr={};dep={}
        for r in rows:
            elapsed+=D(r['interval_runtime']);station=r['station']
            if station in arr:raise ValueError(f'Duplicate station in plan {route},{pid}: {station}')
            arr[station]=elapsed;dep[station]=elapsed+settings['DWELL_TIME']
            elapsed=dep[station]
        plans.append(Plan(route,pid,arr,dep))
    timetable=pd.read_excel(folder/'Origin_timetable.xlsx',sheet_name='Sheet1')
    original={}
    for train,part in timetable.groupby('TrainCode',sort=False):
        last=D(-1);day=0
        for r in part.sort_values('OrderID').itertuples(index=False):
            minute=clock_minutes(r.ArriveTime)
            if minute is None:continue
            absolute=minute+day*1440
            if absolute<last:day+=1;absolute=minute+day*1440
            last=absolute;original[str(train),str(r.TrainStation)]=absolute
    overrides={} if arrival_overrides is None else json.loads(Path(arrival_overrides).read_text(encoding='utf-8'))
    groups=[]
    with (folder/passenger_file).open(encoding='utf-8-sig',newline='') as f:
        for index,r in enumerate(csv.DictReader(f)):
            gid=int(r.get('PassengerGroupID',index))
            original_arrival=original.get((r['Train'],r['DestinationStation']))
            if str(gid) in overrides:original_arrival=D(overrides[str(gid)])
            groups.append(Group(gid,int(r['Route']),r['DestinationStation'],D(r['weight']),D(r['Enter']),D(r['Denied']),
                                D(r['Departure']),original_arrival))
    start,end,step=settings['START_TIME'],settings['END_TIME'],settings['STEP']
    if step<=0 or end<start or (end-start)%step!=0:raise ValueError('Invalid time grid')
    times=[start+i*step for i in range(int((end-start)/step)+1)]
    ins=Instance(times,stocks,groups,plans,settings['MIN_HEADWAY'],settings['OMEGA_CR'],
                 settings['ALPHA_1'],settings['ALPHA_2'],settings['ALPHA_3'])
    ins.validate();return ins


def write_csv(path,rows,fieldnames=None):
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fieldnames or list(rows[0]));writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--input',type=Path,help='Input JSON path; see example.json for fields')
    source.add_argument('--data-dir',type=Path,help='Directory containing the original CSV/TXT/XLSX inputs')
    parser.add_argument('--passenger-file',default='Env_data_scenario_1.csv',
                        help='Passenger CSV filename under --data-dir (default: Env_data_scenario_1.csv)')
    parser.add_argument('--arrival-overrides',type=Path,help='JSON map of group ID to original destination arrival minute')
    parser.add_argument('--crowding',choices=['appendix-c','state-consistent'],default='appendix-c',
                        help='Crowding convention: printed Appendix C or Eq. (13) state occupancy')
    parser.add_argument('--inspect',action='store_true',help='Validate/read inputs only; do not build or solve')
    parser.add_argument('--output',type=Path,help='New output directory (default: results/<timestamp> beside this script)')
    parser.add_argument('--time-limit',type=float,default=None)
    parser.add_argument('--threads',type=int,default=4)
    parser.add_argument('--mip-gap',type=float,default=1e-6)
    parser.add_argument('--write-model',action='store_true',help='Save full LP (potentially very large)')
    args=parser.parse_args()
    if args.time_limit is not None and args.time_limit<=0:parser.error('--time-limit must be positive')
    if args.threads<0 or args.mip_gap<0:parser.error('Invalid solver parameters')
    ins=load_json(args.input) if args.input else load_legacy(args.data_dir,args.passenger_file,args.arrival_overrides)
    empty_windows=[g.id for g in ins.groups if g.enter >= (g.original_departure if g.route==0 else g.leave)]
    print(json.dumps(dict(groups=len(ins.groups),stocks=len(ins.stocks),plans=len(ins.plans),
                          time_points=len(ins.times),crowding=args.crowding,
                          empty_presence_window_count=len(empty_windows),empty_window_id_examples=empty_windows[:10],
                          demand_quantum=str(lattice([g.weight for g in ins.groups]+[s.capacity for s in ins.stocks]))),indent=2))
    if args.inspect:return 0
    output=(args.output or Path(__file__).resolve().parent/'results'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')).resolve()
    output.mkdir(parents=True,exist_ok=False)
    begun=time.perf_counter()
    built=build_model(ins,crowding=args.crowding,output_flag=True);m=built.model
    original_cwd=Path.cwd()
    try:
        os.chdir(output)
        m.Params.LogFile='gurobi.log'
        m.Params.Threads=args.threads;m.Params.MIPGap=args.mip_gap
        if args.time_limit is not None:m.Params.TimeLimit=args.time_limit
        if args.write_model:m.write('model.lp')
        construction=time.perf_counter()-begun
        m.optimize()
        summary=dict(status=int(m.Status),solution_count=int(m.SolCount),crowding_mode=args.crowding,
                     construction_sec=construction,solver_sec=m.Runtime,total_sec=time.perf_counter()-begun,
                     demand_quantum=str(built.quantum),counts=m._appendix_c_counts,
                     source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        summary['status_name']={2:'OPTIMAL',3:'INFEASIBLE',9:'TIME_LIMIT',11:'INTERRUPTED',13:'SUBOPTIMAL'}.get(m.Status,str(m.Status))
        if m.SolCount:
            check=validate_solution(built)
            summary.update(objective=m.ObjVal,objective_bound=m.ObjBound,mip_gap=m.MIPGap,
                           validation_passed=check['passed'],validation_errors=check['errors'],
                           negative_literal_times=check['negative_literal_times'],
                           physical_overcrowding_times=check['physical_overcrowding_times'])
            summary['empty_presence_window_ids']=empty_windows
            for key in ['satisfied_epd','weighted_waiting','weighted_delay']:summary[key]=check[key]
            (output/'validation.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf-8')
            if check['passed']:
                write_csv(output/'selected_actions.csv',check['actions'],
                          ['action_id','stock','route','plan','departure','served_groups','served_weight'])
                write_csv(output/'assignments.csv',check['assignments'],
                          ['group_id','action_id','stock','route','plan','departure','weight','waiting','delay'])
                write_csv(output/'crowding.csv',check['crowding'])
        elif m.Status==3:
            m.computeIIS();m.write('infeasibility.ilp')
        (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False,indent=2))
        print('Output:',output.resolve())
        return 0 if m.SolCount and summary.get('validation_passed') else 2
    finally:
        m.dispose()
        os.chdir(original_cwd)


if __name__=='__main__':
    raise SystemExit(main())
