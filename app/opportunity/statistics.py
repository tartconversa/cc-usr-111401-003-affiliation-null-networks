"""可扩展统计量接口与内置统计量。

接口契约：
- components(ctx)：声明本统计量输出的分量（key、label、group）；
- full(ctx, proj)：对任一状态完整重算，返回 {分量键: 数值}，所有统计量必须实现；
- details(ctx, proj)：返回 {分量键: 具体结构明细列表}，供研究者查看闭合/经纪结构与对应活动；
- 增量扩展（可选）：声明 incremental = True 并实现 attach / on_swap / current，
  采样器在每次接受交换后调用 on_swap；抽样器可用 verify_incremental 校验增量与完整重算一致。

新增统计量：实现上述接口后在 REGISTRY 登记即可进入配置、抽样、精确枚举与多重比较流程。
"""
from itertools import combinations
from typing import NamedTuple

ATTRIBUTE_LABEL = {'village': '村庄', 'kind': '类型'}

class Component(NamedTuple):
    key: str
    label: str
    group: str

def attribute_of(ctx, attribute, team):
    """团队属性在该活动发生层取值；未来按层变化的属性只需改此入口。"""
    return ctx.villages[team] if attribute == 'village' else ctx.kinds[team]

class CrossGroupPairs:
    """跨属性共同活动团队对数（二值投影对；推断在二部参照上进行）。"""
    incremental = True

    def __init__(self, attribute):
        self.attribute = attribute
        self.key = f'pairs.cross_{attribute}'

    def components(self, ctx):
        label = ATTRIBUTE_LABEL[self.attribute]
        return [Component(self.key, f'跨{label}共同活动团队对数', '配对')]

    def _diff(self, a, b):
        return attribute_of(self.ctx, self.attribute, a) != attribute_of(self.ctx, self.attribute, b)

    def attach(self, ctx, edges):
        self.ctx = ctx
        self.members = {e: set() for e in ctx.events}
        for t, e in edges:
            self.members[e].add(t)
        self.pair_count = {}
        for ms in self.members.values():
            for a, b in combinations(sorted(ms), 2):
                self.pair_count[(a, b)] = self.pair_count.get((a, b), 0) + 1
        self.cross = sum(1 for pair in self.pair_count if self._diff(*pair))

    def _dec(self, a, b):
        key = (a, b) if a < b else (b, a)
        if key not in self.pair_count:
            raise RuntimeError('增量状态不一致：减少不存在的共同活动对')
        if self.pair_count[key] == 1:
            del self.pair_count[key]
            if self._diff(*key):
                self.cross -= 1
        else:
            self.pair_count[key] -= 1

    def _inc(self, a, b):
        key = (a, b) if a < b else (b, a)
        if key not in self.pair_count and self._diff(*key):
            self.cross += 1
        self.pair_count[key] = self.pair_count.get(key, 0) + 1

    def on_swap(self, removed, added):
        for t, e in removed:
            for x in self.members[e]:
                if x != t:
                    self._dec(t, x)
            self.members[e].discard(t)
        for t, e in added:
            for x in self.members[e]:
                self._inc(t, x)
            self.members[e].add(t)

    def current(self):
        return {self.key: float(self.cross)}

    def full(self, ctx, proj):
        count = sum(1 for a, b in proj.pair_events
                    if attribute_of(ctx, self.attribute, a) != attribute_of(ctx, self.attribute, b))
        return {self.key: float(count)}

    def details(self, ctx, proj):
        items = []
        for (a, b), evs in sorted(proj.pair_events.items()):
            if attribute_of(ctx, self.attribute, a) != attribute_of(ctx, self.attribute, b):
                items.append({'teams': [a, b],
                              self.attribute: [attribute_of(ctx, self.attribute, a),
                                               attribute_of(ctx, self.attribute, b)],
                              'activities': sorted(evs)})
        return {self.key: items}

class CrossGroupTriads:
    """跨属性闭合三元组：投影中两两相连且属性不唯一的三元组，附支撑活动明细。"""
    incremental = False

    def __init__(self, attribute):
        self.attribute = attribute
        self.key = f'triads.cross_{attribute}'

    def components(self, ctx):
        label = ATTRIBUTE_LABEL[self.attribute]
        return [Component(self.key, f'跨{label}闭合三元组数', '闭合')]

    def _triangles(self, ctx, proj):
        out = []
        neigh = proj.neighbors
        for a in ctx.teams:
            for b in neigh[a]:
                if b <= a:
                    continue
                for c in neigh[a] & neigh[b]:
                    if c > b:
                        out.append((a, b, c))
        return out

    def _cross(self, ctx, triad):
        return len({attribute_of(ctx, self.attribute, t) for t in triad}) >= 2

    def full(self, ctx, proj):
        count = sum(1 for triad in self._triangles(ctx, proj) if self._cross(ctx, triad))
        return {self.key: float(count)}

    def details(self, ctx, proj):
        items = []
        for triad in self._triangles(ctx, proj):
            if not self._cross(ctx, triad):
                continue
            sides = [{'pair': [x, y], 'activities': sorted(proj.pair_events[(x, y)])}
                     for x, y in combinations(triad, 2)]
            items.append({'teams': list(triad),
                          self.attribute: {t: attribute_of(ctx, self.attribute, t) for t in triad},
                          'sides': sides})
        return {self.key: items}

class Brokerage:
    """Gould–Fernandez 经纪：团队连接的两两未直接相连邻居对数，按属性分组分类。"""
    incremental = False

    def __init__(self, attribute):
        self.attribute = attribute
        self.prefix = f'brokerage.{attribute}'

    def components(self, ctx):
        label = ATTRIBUTE_LABEL[self.attribute]
        return [Component(f'{self.prefix}:{t}', f'{t}的跨{label}经纪对数', '经纪') for t in ctx.teams]

    def _instances(self, ctx, proj):
        out = {}
        for t in ctx.teams:
            pairs = []
            for a, b in combinations(sorted(proj.neighbors[t]), 2):
                if b not in proj.neighbors[a]:
                    pairs.append((a, b))
            out[t] = pairs
        return out

    def _role(self, ctx, broker, a, b):
        gt = attribute_of(ctx, self.attribute, broker)
        ga = attribute_of(ctx, self.attribute, a)
        gb = attribute_of(ctx, self.attribute, b)
        if ga == gb == gt:
            return 'coordinator'
        if ga == gb:
            return 'consultant'
        if ga != gt and gb != gt:
            return 'liaison'
        return 'gatekeeper_representative'

    def full(self, ctx, proj):
        inst = self._instances(ctx, proj)
        return {f'{self.prefix}:{t}': float(len(pairs)) for t, pairs in inst.items()}

    def details(self, ctx, proj):
        inst = self._instances(ctx, proj)
        out = {}
        for t, pairs in inst.items():
            items = []
            for a, b in pairs:
                items.append({'pair': [a, b],
                              'role': self._role(ctx, t, a, b),
                              'activities': {
                                  'broker_left': sorted(proj.pair_events[tuple(sorted((t, a)))]),
                                  'broker_right': sorted(proj.pair_events[tuple(sorted((t, b)))]),
                              }})
            out[f'{self.prefix}:{t}'] = items
        return out

REGISTRY = {
    'cross_village_pairs': lambda: CrossGroupPairs('village'),
    'cross_kind_pairs': lambda: CrossGroupPairs('kind'),
    'cross_village_triads': lambda: CrossGroupTriads('village'),
    'cross_kind_triads': lambda: CrossGroupTriads('kind'),
    'brokerage_village': lambda: Brokerage('village'),
    'brokerage_kind': lambda: Brokerage('kind'),
}

def instantiate(names):
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise ValueError(f'未知统计量: {sorted(unknown)}')
    return [REGISTRY[n]() for n in names]
