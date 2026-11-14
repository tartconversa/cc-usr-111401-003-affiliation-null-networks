"""参照汇总、经验 p 值、多重比较校正。

p 值采用 (k+1)/(n+1) 连续校正的经验尾概率；主方向为 high（超出参照）。
多重比较使用 Benjamini–Hochberg，family 范围由装配层显式披露；
零方差参照与样本不足的分量不进入 family，而是以原因列出。
"""

def round6(value):
    return None if value is None else round(value, 6)

def empirical_p(observed, refs):
    """返回 (p_high, p_low)；refs 为空时返回 (None, None)。"""
    n = len(refs)
    if n == 0:
        return None, None
    ge = sum(1 for x in refs if x >= observed)
    le = sum(1 for x in refs if x <= observed)
    return (1 + ge) / (1 + n), (1 + le) / (1 + n)

def exact_p_high(observed, counter, total):
    if counter is None or not total:
        return None
    ge = sum(c for v, c in counter.items() if v >= observed)
    return ge / total

def ks_statistic(refs, counter, total):
    """经验样本与精确分布的最大 CDF 差；无精确分布时返回 None。"""
    if counter is None or not total or not refs:
        return None
    support = sorted(set(counter) | set(refs))
    ordered = sorted(refs)
    n = len(ordered)
    ks = 0.0
    idx = 0
    cum_exact = 0.0
    for x in support:
        while idx < n and ordered[idx] <= x:
            idx += 1
        cum_exact += sum(c for v, c in counter.items() if v == x) / total
        ks = max(ks, abs(idx / n - cum_exact))
    return ks

def summarize_component(observed, refs, ess_total, exact_counter, exact_total, min_ess):
    """单分量参照汇总；零方差显式标记，不编造 z 或显著性。"""
    n = len(refs)
    mean = sum(refs) / n
    var = sum((x - mean) ** 2 for x in refs) / n
    sd = var ** 0.5
    p_high, p_low = empirical_p(observed, refs)
    flags = []
    degenerate = sd == 0
    if degenerate:
        flags.append('zero_variance_reference')
    if ess_total is not None and ess_total < min_ess:
        flags.append('low_effective_samples')
    return {
        'samples': n,
        'ess': round6(ess_total),
        'mean': round6(mean),
        'sd': round6(sd),
        'z': round6((observed - mean) / sd) if sd > 0 else None,
        'p_high': round6(p_high),
        'p_low': round6(p_low),
        'exact_p_high': round6(exact_p_high(observed, exact_counter, exact_total)),
        'ks_vs_exact': round6(ks_statistic(refs, exact_counter, exact_total)),
        'degenerate': degenerate,
        'flags': flags,
    }

def benjamini_hochberg(items):
    """items 为 (引用键, p) 列表，返回 {引用键: q}；step-up 单调化。"""
    m = len(items)
    if m == 0:
        return {}
    ordered = sorted(items, key=lambda kv: (kv[1], str(kv[0])))
    qs = {}
    best = 1.0
    for rank in range(m, 0, -1):
        key, p = ordered[rank - 1]
        best = min(best, p * m / rank)
        qs[key] = round6(min(1.0, best))
    return qs
