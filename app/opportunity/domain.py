"""每层合法参与域：团队有效性、禁配与冻结三元组的解析和校验。

定义域规则：
- 团队只有在自身 layers 列出的时间层内才是合法参与候选；
- forbidden 为 [层, 活动, 团队] 三元组，声明结构性禁配（参照状态中不得出现）；
- frozen 为同结构三元组，声明已冻结参与（参照状态中必须保留，交换不可移除）；
- 团队类型与村庄归属按层取值：当前资料模型中属性由快照钉住的团队记录给出，
  层有效性由 layers 列表界定；未来若引入按层变化的属性，仅需替换本模块的取值入口。
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class LayerContext:
    layer: str
    teams: tuple        # 本层合法团队键（已排序）
    events: tuple       # 本层活动键（已排序）
    kinds: dict         # 团队 -> 类型（本层取值）
    villages: dict      # 团队 -> 村庄（本层取值）
    edges: frozenset    # 已观察参与 (团队, 活动)
    forbidden: frozenset  # 结构零 (团队, 活动)
    frozen: frozenset     # 冻结参与 (团队, 活动)

def _require_str(value, message):
    if not isinstance(value, str) or not value:
        raise ValueError(message)
    return value

def _triples(raw, label):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f'{label}应为[层,活动,团队]三元组数组')
    out = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 3 \
                or any(not isinstance(x, str) or not x for x in item):
            raise ValueError(f'{label}条目应为[层,活动,团队]三元组')
        out.append(tuple(item))
    return out

def build_contexts(snapshot):
    """从快照构建各层定义域，返回 (层 -> LayerContext, 定义域提示)。"""
    teams = {}
    for row in snapshot.rows('teams'):
        tid = _require_str(row.get('id'), '团队键应为非空字符串')
        kind = _require_str(row.get('kind'), '团队类型应为非空字符串')
        village = _require_str(row.get('village'), '团队村庄应为非空字符串')
        layers = row.get('layers')
        if not isinstance(layers, list) or any(not isinstance(x, str) or not x for x in layers):
            raise ValueError('团队有效层应为非空字符串数组')
        teams[tid] = {'kind': kind, 'village': village, 'layers': set(layers)}
    events = {}
    for row in snapshot.rows('events'):
        eid = _require_str(row.get('id'), '活动键应为非空字符串')
        layer = _require_str(row.get('layer'), '活动时间层应为非空字符串')
        members = row.get('members')
        if not isinstance(members, list) or any(not isinstance(m, str) or not m for m in members):
            raise ValueError('活动成员应为团队键数组')
        members = sorted(set(members))  # 同一团队在同一活动只计一次
        for m in members:
            if m not in teams or layer not in teams[m]['layers']:
                raise ValueError('活动成员或有效层不存在')
        events[eid] = {'layer': layer, 'members': members}
    meta = snapshot.metadata
    forbidden_raw = _triples(meta.get('forbidden'), '禁配')
    frozen_raw = _triples(meta.get('frozen'), '冻结')
    edges = {(t, e) for e, ev in events.items() for t in ev['members']}
    forbidden, redundant = set(), []
    for layer, eid, tid in forbidden_raw:
        if eid not in events:
            raise ValueError('禁配指向未知活动')
        if events[eid]['layer'] != layer:
            raise ValueError('禁配层与活动层不一致')
        if tid not in teams:
            raise ValueError('禁配指向未知团队')
        if (tid, eid) in edges:
            raise ValueError('禁配与已观察参与冲突')
        if layer not in teams[tid]['layers']:
            redundant.append([layer, eid, tid])  # 团队在该层本无合法资格，条目为空转
        forbidden.add((tid, eid))
    frozen = set()
    for layer, eid, tid in frozen_raw:
        if eid not in events:
            raise ValueError('冻结指向未知活动')
        if events[eid]['layer'] != layer:
            raise ValueError('冻结层与活动层不一致')
        if tid not in teams:
            raise ValueError('冻结指向未知团队')
        if (tid, eid) not in edges:
            raise ValueError('冻结参与未在资料中出现')
        if (tid, eid) in forbidden:
            raise ValueError('冻结与禁配冲突')
        frozen.add((tid, eid))
    contexts = {}
    for layer in sorted({ev['layer'] for ev in events.values()}):
        layer_teams = tuple(sorted(t for t, r in teams.items() if layer in r['layers']))
        layer_events = tuple(sorted(e for e, ev in events.items() if ev['layer'] == layer))
        event_set = set(layer_events)
        contexts[layer] = LayerContext(
            layer=layer,
            teams=layer_teams,
            events=layer_events,
            kinds={t: teams[t]['kind'] for t in layer_teams},
            villages={t: teams[t]['village'] for t in layer_teams},
            edges=frozenset((t, e) for (t, e) in edges if e in event_set),
            forbidden=frozenset((t, e) for (t, e) in forbidden if e in event_set),
            frozen=frozenset((t, e) for (t, e) in frozen if e in event_set),
        )
    return contexts, {'redundant_forbidden': redundant}
