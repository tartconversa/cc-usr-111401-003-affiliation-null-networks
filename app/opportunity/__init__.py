"""机会校正网络分析：固定参与机会的二部参照下的结构异常检验。

参照模型：在每个时间层内，固定各团队参与次数与各活动规模，
在保留结构性禁配与已冻结参与的全部二部状态上取均匀分布
（抽样链实际覆盖从已观察状态可达的连通部分；精确枚举可判定时显式比较）。
结论仅描述该参照下的结构异常，不构成因果归因。
"""
import random

from ..catalog import load
from ..service import SCHEMAS
from .domain import build_contexts
from .exact import enumerate_states, reachable_states, exact_distributions
from .projection import project
from .report import summarize_component, benjamini_hochberg, round6, exact_p_high
from .sampler import run_chain, autocorr_ess, geweke_z, chains_disagreement_z
from .statistics import instantiate

ANALYSIS_VERSION = '1.0.0'

SCOPE_NOTE = ('本报告仅描述给定参照（固定各时间层团队参与次数与活动规模、'
              '保留禁配与冻结参与的均匀二部参照）下的结构异常；'
              '同一活动投影出的团队对不作为独立观测；'
              '结果不构成对产业增长或任何主体贡献的因果归因。')

DEFAULT_CONFIG = {
    'seed': 20261114,
    'chains': 2,
    'samples_per_chain': 400,
    'burnin_swaps': 200,
    'thin_swaps': 20,
    'max_attempts_factor': 100,
    'exact_enabled': True,
    'exact_state_cap': 50000,
    'exact_visit_cap': 2000000,
    'min_total_samples': 200,
    'min_ess': 40,
    'ks_tolerance': 0.12,
    'chain_z_threshold': 2.58,
    'statistics': ['cross_village_pairs', 'cross_kind_pairs',
                   'cross_kind_triads', 'brokerage_village'],
    'detail_cap': 25,
}

_INT_BOUNDS = {
    'seed': (0, None), 'chains': (1, None), 'samples_per_chain': (10, None),
    'burnin_swaps': (0, None), 'thin_swaps': (1, None), 'max_attempts_factor': (1, None),
    'exact_state_cap': (1, None), 'exact_visit_cap': (1000, None),
    'min_total_samples': (1, None), 'min_ess': (1, None), 'detail_cap': (0, None),
}
_FLOAT_BOUNDS = {'ks_tolerance': (0.0, None), 'chain_z_threshold': (0.0, None)}

def resolve_config(config):
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError('配置应为对象')
    unknown = sorted(set(config) - set(DEFAULT_CONFIG))
    if unknown:
        raise ValueError(f'未知配置项: {unknown}')
    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    for key, (lo, _) in _INT_BOUNDS.items():
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < lo:
            raise ValueError(f'配置项{key}应为不小于{lo}的整数')
    for key, (lo, _) in _FLOAT_BOUNDS.items():
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > lo:
            raise ValueError(f'配置项{key}应为大于{lo}的数')
        merged[key] = float(value)
    if not isinstance(merged['exact_enabled'], bool):
        raise ValueError('配置项exact_enabled应为布尔值')
    names = merged['statistics']
    if not isinstance(names, list) or not names or any(not isinstance(n, str) for n in names):
        raise ValueError('配置项statistics应为非空统计量名数组')
    instantiate(names)  # 未知统计量在此拒绝
    if len(set(names)) != len(names):
        raise ValueError('配置项statistics存在重复')
    return merged

def _structures_with_cap(details, cap):
    out = {}
    for key, items in details.items():
        items = sorted(items, key=lambda x: str(sorted(x.items())))
        out[key] = {'total': len(items), 'items': items[:cap], 'truncated': len(items) > cap}
    return out

def _analyze_layer(ctx, stat_factories, cfg):
    stats_obs = instantiate(cfg['statistics'])
    proj_obs = project(ctx.teams, ctx.events, ctx.edges)
    observed = {}
    details = {}
    components = {}
    for stat in stats_obs:
        observed.update(stat.full(ctx, proj_obs))
        details.update(stat.details(ctx, proj_obs))
        for comp in stat.components(ctx):
            components[comp.key] = {'label': comp.label, 'group': comp.group, 'direction': 'high'}

    warnings = []
    domain = {'assignable_pairs': sum(1 for t in ctx.teams for e in ctx.events
                                      if (t, e) not in ctx.forbidden),
              'frozen_pairs': len(ctx.frozen),
              'movable_edges': len(ctx.edges - ctx.frozen),
              'exact_states': None, 'reachable_states': None,
              'enumeration': 'disabled', 'space': 'unknown'}
    exact_counters, exact_total = None, None
    if cfg['exact_enabled']:
        enum = enumerate_states(ctx, cfg['exact_state_cap'], cfg['exact_visit_cap'])
        reach = reachable_states(ctx, cfg['exact_state_cap'])
        if enum['status'] == 'exact':
            domain['enumeration'] = 'exact'
            domain['exact_states'] = len(enum['states'])
            exact_total = len(enum['states'])
            exact_counters = exact_distributions(ctx, stat_factories, enum['states'])
        else:
            domain['enumeration'] = 'capped'
            warnings.append({'code': 'enumeration_capped',
                             'message': f"状态数或访问数超限（{enum['reason']}），本层无精确参照"})
        if reach['status'] == 'exact':
            domain['reachable_states'] = reach['count']
        if domain['exact_states'] == 1:
            domain['space'] = 'unique_state'
            warnings.append({'code': 'unique_state_proven',
                             'message': '约束下仅存在一个可行状态，无可交换状态'})
        elif domain['exact_states'] is not None and domain['reachable_states'] is not None:
            if domain['reachable_states'] < domain['exact_states']:
                domain['space'] = 'fragmented'
                warnings.append({'code': 'space_fragmented',
                                 'message': f"约束使状态空间碎片化：可达 {domain['reachable_states']} / "
                                            f"全部 {domain['exact_states']}；抽样参照仅覆盖可达部分"})
            else:
                domain['space'] = 'fully_connected'

    max_attempts = (cfg['burnin_swaps'] + cfg['thin_swaps'] * cfg['samples_per_chain']) \
        * cfg['max_attempts_factor']
    skip_sampling = False
    if domain['movable_edges'] < 2:
        skip_sampling = True
        if not any(w['code'] == 'unique_state_proven' for w in warnings):
            warnings.append({'code': 'no_exchangeable_states',
                             'message': '可动边不足两条，约束下不存在可交换状态'})
    elif domain['exact_states'] == 1:
        skip_sampling = True
    chains = []
    if not skip_sampling:
        for i in range(cfg['chains']):
            rng = random.Random(f"{cfg['seed']}|{ctx.layer}|chain{i}")
            chains.append(run_chain(ctx, stat_factories, rng,
                                    cfg['burnin_swaps'], cfg['thin_swaps'],
                                    cfg['samples_per_chain'], max_attempts))
    total_accepted = sum(c.accepted for c in chains)
    total_attempts = sum(c.attempts for c in chains)
    if chains and any(c.truncated for c in chains):
        warnings.append({'code': 'attempt_cap_reached',
                         'message': '达到提议次数上限，样本数低于配置；拒绝占比过高'})
    if chains and total_accepted == 0:
        warnings.append({'code': 'no_accepted_swaps',
                         'message': '全部链未接受任何交换：约束下可能不存在可交换状态，参照退化'})

    keys = list(components)
    pooled = {k: [] for k in keys}
    chain_reports = []
    for i, chain in enumerate(chains):
        ess_map, z_map = {}, {}
        for k in keys:
            series = [s[k] for s in chain.samples]
            pooled[k].extend(series)
            ess_map[k] = round6(autocorr_ess(series))
            z_map[k] = round6(geweke_z(series))
        rejected = {k: v for k, v in sorted(chain.tally.items())
                    if k not in ('attempts', 'accepted')}
        chain_reports.append({'label': f'chain{i}', 'samples': len(chain.samples),
                              'accepted': chain.accepted, 'attempts': chain.attempts,
                              'rejected': rejected, 'ess': ess_map, 'geweke_z': z_map})

    reference = {}
    for k in keys:
        refs = pooled[k]
        per_chain = [[s[k] for s in c.samples] for c in chains]
        ess_parts = [autocorr_ess(s) for s in per_chain]
        ess_total = None if all(e is None for e in ess_parts) \
            else sum(e for e in ess_parts if e is not None)
        if not refs:
            exact_counter = exact_counters.get(k) if exact_counters else None
            reason = 'no_exchangeable_states' if skip_sampling \
                else 'insufficient_reference_samples'
            reference[k] = {'samples': 0, 'ess': None, 'mean': None, 'sd': None, 'z': None,
                            'p_high': None, 'p_low': None,
                            'exact_p_high': round6(exact_p_high(observed[k], exact_counter,
                                                                exact_total)),
                            'ks_vs_exact': None, 'degenerate': True,
                            'flags': [reason]}
            continue
        summary = summarize_component(observed[k], refs, ess_total,
                                      exact_counters.get(k) if exact_counters else None,
                                      exact_total, cfg['min_ess'])
        disagree = chains_disagreement_z(per_chain, ess_parts)
        if disagree is not None and disagree > cfg['chain_z_threshold']:
            summary['flags'].append('chains_disagree')
        if any(z is not None and abs(z) > cfg['chain_z_threshold']
               for z in (geweke_z(s) for s in per_chain)):
            summary['flags'].append('geweke_unstable')
        if summary['ks_vs_exact'] is not None and summary['ks_vs_exact'] > cfg['ks_tolerance']:
            summary['flags'].append('exact_mismatch')
        if len(refs) < cfg['min_total_samples']:
            summary['flags'].append('insufficient_reference_samples')
            summary['p_high'] = None
            summary['p_low'] = None
        summary['chains_disagreement_z'] = round6(disagree)
        reference[k] = summary

    return {
        'size': {'teams': len(ctx.teams), 'events': len(ctx.events), 'edges': len(ctx.edges),
                 'forbidden': len(ctx.forbidden), 'frozen': len(ctx.frozen)},
        'domain': domain,
        'components': components,
        'observed': observed,
        'reference': reference,
        'structures': _structures_with_cap(details, cfg['detail_cap']),
        'diagnostics': {
            'chains': chain_reports,
            'acceptance_rate': round6(total_accepted / total_attempts) if total_attempts else None,
            'warnings': warnings,
        },
    }

def inspect(payload, config=None):
    """机会校正网络分析入口；输出为可 JSON 序列化的报告字典。"""
    cfg = resolve_config(config)
    snapshot = load(payload, SCHEMAS)
    contexts, notes = build_contexts(snapshot)
    stat_factories = [lambda n=n: instantiate([n])[0] for n in cfg['statistics']]
    layers_out = {}
    family_items = []
    excluded = []
    for layer in sorted(contexts):
        result = _analyze_layer(contexts[layer], stat_factories, cfg)
        layers_out[layer] = result
        for key, ref in result['reference'].items():
            comp = f'{layer}|{key}'
            if ref['p_high'] is None or ref['degenerate']:
                reason = next((f for f in ('no_exchangeable_states',
                                           'insufficient_reference_samples',
                                           'zero_variance_reference')
                               if f in ref['flags']), 'degenerate_reference')
                excluded.append({'component': comp, 'reason': reason})
            else:
                family_items.append((comp, ref['p_high']))
    qs = benjamini_hochberg(family_items)
    for comp, q in qs.items():
        layer, key = comp.split('|', 1)
        layers_out[layer]['reference'][key]['q_high'] = q
    for item in excluded:
        layer, key = item['component'].split('|', 1)
        layers_out[layer]['reference'][key]['q_high'] = None

    warnings = []
    if notes['redundant_forbidden']:
        warnings.append({'code': 'redundant_forbidden_entries',
                         'message': '部分禁配条目指向本无本层参与资格的团队，已按空转处理',
                         'entries': notes['redundant_forbidden']})
    return {
        'schema_version': 1,
        'analysis': 'opportunity_network',
        'analysis_version': ANALYSIS_VERSION,
        'input_digest': snapshot.digest,
        'data_version': snapshot.metadata.get('data_version'),
        'config': cfg,
        'layers': layers_out,
        'family': {
            'scope': 'run',
            'scope_note': '本次运行全部层内全部非退化分量合并为一个family',
            'method': 'benjamini-hochberg',
            'direction': 'high',
            'tested': len(family_items),
            'components': sorted(comp for comp, _ in family_items),
            'excluded': sorted(excluded, key=lambda x: x['component']),
        },
        'reproducibility': {
            'seed': cfg['seed'],
            'stream_derivation': 'random.Random(f"{seed}|{layer}|chain{i}")',
            'analysis_version': ANALYSIS_VERSION,
            'parameters': {k: cfg[k] for k in
                           ('chains', 'samples_per_chain', 'burnin_swaps', 'thin_swaps',
                            'max_attempts_factor', 'exact_state_cap', 'exact_visit_cap',
                            'min_total_samples', 'min_ess', 'ks_tolerance',
                            'chain_z_threshold', 'statistics')},
        },
        'warnings': warnings,
        'scope_note': SCOPE_NOTE,
    }
