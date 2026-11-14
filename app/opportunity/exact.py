"""小实例精确枚举与可达性校验。

enumerate_states：枚举满足固定度序列、禁配与冻结的全部二部状态，
用于小实例的精确参照分布，并校验抽样链。
reachable_states：从已观察状态出发按合法交换做 BFS，
与全空间比较可识别约束导致的状态空间碎片化。
两者均有上限保护，超限显式报告 capped，不静默截断结论。
"""
from itertools import combinations

class _CapExceeded(Exception):
    pass

def enumerate_states(ctx, state_cap, visit_cap):
    """返回 {'status': 'exact', 'states': [...]} 或 {'status': 'capped', 'reason': ...}。"""
    team_res = {t: 0 for t in ctx.teams}
    event_res = {e: 0 for e in ctx.events}
    for t, e in ctx.edges:
        team_res[t] += 1
        event_res[e] += 1
    for t, e in ctx.frozen:
        team_res[t] -= 1
        event_res[e] -= 1
    movable_teams = [t for t in ctx.teams if team_res[t] > 0]
    candidates = {
        t: sorted(e for e in ctx.events
                  if (t, e) not in ctx.forbidden and (t, e) not in ctx.frozen)
        for t in movable_teams
    }
    order = sorted(movable_teams, key=lambda t: (len(candidates[t]) - team_res[t], t))
    states = []
    assignment = []
    visits = [0]

    def rec(i, event_res):
        visits[0] += 1
        if visits[0] > visit_cap:
            raise _CapExceeded('visit_cap')
        if len(states) > state_cap:
            raise _CapExceeded('state_cap')
        if i == len(order):
            edges = set(ctx.frozen)
            for t, combo in assignment:
                edges.update((t, e) for e in combo)
            states.append(frozenset(edges))
            return
        t = order[i]
        need = team_res[t]
        avail = [e for e in candidates[t] if event_res[e] > 0]
        if len(avail) < need:
            return
        for combo in combinations(avail, need):
            assignment.append((t, combo))
            for e in combo:
                event_res[e] -= 1
            rec(i + 1, event_res)
            for e in combo:
                event_res[e] += 1
            assignment.pop()

    try:
        rec(0, dict(event_res))
    except _CapExceeded as exc:
        return {'status': 'capped', 'reason': str(exc)}
    return {'status': 'exact', 'states': states}

def reachable_states(ctx, cap):
    """从已观察状态出发的合法交换可达集；返回 {'status': 'exact', 'count': n} 或 capped。"""
    start = frozenset(ctx.edges)
    seen = {start}
    stack = [start]
    while stack:
        state = stack.pop()
        movable = sorted(state - ctx.frozen)
        for (t1, e1), (t2, e2) in combinations(movable, 2):
            if t1 == t2 or e1 == e2:
                continue
            new1, new2 = (t1, e2), (t2, e1)
            if new1 in state or new2 in state:
                continue
            if new1 in ctx.forbidden or new2 in ctx.forbidden:
                continue
            nxt = frozenset((state - {(t1, e1), (t2, e2)}) | {new1, new2})
            if nxt not in seen:
                if len(seen) >= cap:
                    return {'status': 'capped'}
                seen.add(nxt)
                stack.append(nxt)
    return {'status': 'exact', 'count': len(seen)}

def exact_distributions(ctx, stat_factories, states):
    """对枚举状态逐一完整重算统计量，返回 {分量键: Counter}。"""
    from .projection import project
    stats = [f() for f in stat_factories]
    counters = None
    for state in states:
        proj = project(ctx.teams, ctx.events, state)
        values = {}
        for stat in stats:
            values.update(stat.full(ctx, proj))
        if counters is None:
            from collections import Counter
            counters = {k: Counter() for k in values}
        for k, v in values.items():
            counters[k][v] += 1
    return counters or {}
