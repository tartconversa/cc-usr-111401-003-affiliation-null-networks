"""二部棋盘交换链：固定层内团队参与次数与活动规模的均匀参照抽样。

每次提议从可动边（非冻结）中有序抽取两条 (t1,e1)、(t2,e2)，
若目标位置 (t1,e2)、(t2,e1) 均非现有边且非禁配则接受。
提议矩阵对称（可动边数在各状态间不变），平稳分布为可达状态类上的均匀分布；
拒绝构成自环，不改变均匀性。所有拒绝按原因计数并随报告披露。
"""
from collections import Counter, namedtuple

from .projection import project

class SwapChain:
    """单层状态上的交换链；冻结边不可移除，禁配不可创建。"""

    def __init__(self, ctx, rng):
        self.ctx = ctx
        self.rng = rng
        self.edges = set(ctx.edges)
        self.movable = sorted(self.edges - ctx.frozen)
        self.tally = Counter()

    def step(self):
        """执行一次提议；接受时返回 (移除边, 新增边)，否则返回 None。"""
        self.tally['attempts'] += 1
        if len(self.movable) < 2:
            self.tally['rejected_no_movable'] += 1
            return None
        (t1, e1), (t2, e2) = self.rng.sample(self.movable, 2)
        if t1 == t2 or e1 == e2:
            self.tally['rejected_degenerate'] += 1
            return None
        new1, new2 = (t1, e2), (t2, e1)
        if new1 in self.edges or new2 in self.edges:
            self.tally['rejected_duplicate'] += 1
            return None
        if new1 in self.ctx.forbidden or new2 in self.ctx.forbidden:
            self.tally['rejected_forbidden'] += 1
            return None
        self.edges.discard((t1, e1))
        self.edges.discard((t2, e2))
        self.edges.add(new1)
        self.edges.add(new2)
        self.movable[self.movable.index((t1, e1))] = new1
        self.movable[self.movable.index((t2, e2))] = new2
        self.tally['accepted'] += 1
        return ([(t1, e1), (t2, e2)], [new1, new2])

ChainResult = namedtuple('ChainResult', ['samples', 'tally', 'accepted', 'attempts', 'truncated'])

def run_chain(ctx, stat_factories, rng, burnin, thin, n_samples, max_attempts,
              verify_incremental=False):
    """驱动一条链：burnin 次接受后每 thin 次接受记录一个样本。"""
    stats = [f() for f in stat_factories]
    trackers = [s for s in stats if s.incremental]
    full_stats = [s for s in stats if not s.incremental]
    chain = SwapChain(ctx, rng)
    for tracker in trackers:
        tracker.attach(ctx, chain.edges)
    samples = []
    accepted = 0
    while len(samples) < n_samples and chain.tally['attempts'] < max_attempts:
        swap = chain.step()
        if swap is None:
            continue
        accepted += 1
        removed, added = swap
        for tracker in trackers:
            tracker.on_swap(removed, added)
        if accepted > burnin and (accepted - burnin) % thin == 0:
            sample = {}
            for tracker in trackers:
                sample.update(tracker.current())
            proj = None
            if full_stats or verify_incremental:
                proj = project(ctx.teams, ctx.events, chain.edges)
            for stat in full_stats:
                sample.update(stat.full(ctx, proj))
            if verify_incremental:
                for tracker in trackers:
                    if tracker.current() != tracker.full(ctx, proj):
                        raise RuntimeError('增量统计量与完整重算不一致')
            samples.append(sample)
    return ChainResult(samples, dict(chain.tally), accepted,
                       chain.tally['attempts'], len(samples) < n_samples)

def autocorr_ess(series):
    """初始正序列估计的有效样本量；零方差序列返回 None。"""
    n = len(series)
    if n < 4:
        return float(n)
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series) / n
    if var == 0:
        return None
    rhos = []
    for k in range(1, n // 2 + 1):
        cov = sum((series[i] - mean) * (series[i + k] - mean) for i in range(n - k)) / n
        rhos.append(cov / var)
    tail = 0.0
    i = 0
    while i + 1 < len(rhos):
        pair = rhos[i] + rhos[i + 1]
        if pair < 0:
            break
        tail += pair
        i += 2
    return max(1.0, min(float(n), n / (1 + 2 * tail)))

def geweke_z(series, first_frac=0.1, last_frac=0.5):
    """首尾段均值差的粗略 z（未做谱密度校正，仅作失稳警示）；无法定义时返回 None。"""
    n = len(series)
    n1 = max(2, int(n * first_frac))
    n2 = max(2, int(n * last_frac))
    if n1 + n2 >= n:
        return None
    head, tail = series[:n1], series[n - n2:]
    m1, m2 = sum(head) / n1, sum(tail) / n2
    v1 = sum((x - m1) ** 2 for x in head) / (n1 - 1) / n1
    v2 = sum((x - m2) ** 2 for x in tail) / (n2 - 1) / n2
    if v1 + v2 == 0:
        return 0.0 if m1 == m2 else None
    return (m1 - m2) / (v1 + v2) ** 0.5

def chains_disagreement_z(series_list, ess_list):
    """多链均值差的最大 |z|（按各链 ESS 折算）；不足两条链或无法定义时返回 None。"""
    if len(series_list) < 2:
        return None
    worst = None
    for i in range(len(series_list)):
        for j in range(i + 1, len(series_list)):
            a, b = series_list[i], series_list[j]
            na = ess_list[i] if ess_list[i] else len(a)
            nb = ess_list[j] if ess_list[j] else len(b)
            ma, mb = sum(a) / len(a), sum(b) / len(b)
            va = sum((x - ma) ** 2 for x in a) / max(1, len(a) - 1)
            vb = sum((x - mb) ** 2 for x in b) / max(1, len(b) - 1)
            se2 = va / na + vb / nb
            if se2 == 0:
                continue
            z = abs(ma - mb) / se2 ** 0.5
            if worst is None or z > worst:
                worst = z
    return worst
