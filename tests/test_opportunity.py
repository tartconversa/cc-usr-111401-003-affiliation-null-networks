"""机会校正网络分析的验证：定义域、交换链、精确枚举、诊断与报告。"""
import copy
import json
import os
import random
import subprocess
import sys
import unittest
from pathlib import Path

from app.catalog import load
from app.service import SCHEMAS
from app.opportunity import inspect, DEFAULT_CONFIG
from app.opportunity.domain import build_contexts
from app.opportunity.exact import enumerate_states, reachable_states
from app.opportunity.report import benjamini_hochberg
from app.opportunity.sampler import SwapChain, run_chain, autocorr_ess
from app.opportunity.statistics import instantiate

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'fixtures' / 'opportunity.json').read_text(encoding='utf-8'))

FAST = {'samples_per_chain': 60, 'thin_swaps': 4, 'burnin_swaps': 20,
        'min_total_samples': 60, 'min_ess': 10}

def contexts_of(payload):
    return build_contexts(load(payload, SCHEMAS))[0]

def summer_ctx():
    return contexts_of(FIXTURE)['2025夏']

def fragmented_payload():
    return {
        'schema_version': 1,
        'metadata': {'data_version': 'frag-1',
                     'forbidden': [['L', 'e1', 't0'], ['L', 'e1', 't1'], ['L', 'e0', 't2'],
                                   ['L', 'e1', 't2'], ['L', 'e4', 't3'], ['L', 'e0', 't4'],
                                   ['L', 'e3', 't4']],
                     'frozen': []},
        'collections': {
            'events': [
                {'id': 'e0', 'revision': 1, 'layer': 'L', 'members': ['t0', 't1', 't3']},
                {'id': 'e1', 'revision': 1, 'layer': 'L', 'members': ['t3']},
                {'id': 'e2', 'revision': 1, 'layer': 'L', 'members': ['t0', 't1', 't2', 't3', 't4']},
                {'id': 'e3', 'revision': 1, 'layer': 'L', 'members': ['t0']},
                {'id': 'e4', 'revision': 1, 'layer': 'L', 'members': ['t1', 't2', 't4']},
            ],
            'teams': [{'id': t, 'revision': 1, 'kind': 'k', 'village': 'v', 'layers': ['L']}
                      for t in ['t0', 't1', 't2', 't3', 't4']],
        },
    }

class DomainTests(unittest.TestCase):
    def test_forbidden_conflicts_with_observed(self):
        data = copy.deepcopy(FIXTURE)
        data['metadata']['forbidden'] = [['2025夏', 'a1', 't1']]
        with self.assertRaisesRegex(ValueError, '禁配与已观察参与冲突'):
            contexts_of(data)

    def test_frozen_must_be_observed(self):
        data = copy.deepcopy(FIXTURE)
        data['metadata']['frozen'] = [['2025夏', 'a2', 't3']]
        with self.assertRaisesRegex(ValueError, '冻结参与未在资料中出现'):
            contexts_of(data)

    def test_frozen_forbidden_contradiction(self):
        data = copy.deepcopy(FIXTURE)
        data['metadata']['forbidden'] = [['2025夏', 'a1', 't3']]
        data['metadata']['frozen'] = [['2025夏', 'a1', 't3']]
        with self.assertRaisesRegex(ValueError, '禁配与已观察参与冲突'):
            contexts_of(data)

    def test_unknown_ids_and_layer_mismatch(self):
        data = copy.deepcopy(FIXTURE)
        data['metadata']['forbidden'] = [['2025夏', 'zz', 't1']]
        with self.assertRaisesRegex(ValueError, '禁配指向未知活动'):
            contexts_of(data)
        data['metadata']['forbidden'] = [['2025夏', 'a1', 'zz']]
        with self.assertRaisesRegex(ValueError, '禁配指向未知团队'):
            contexts_of(data)
        data['metadata']['forbidden'] = [['2025冬', 'a1', 't2']]
        with self.assertRaisesRegex(ValueError, '禁配层与活动层不一致'):
            contexts_of(data)

    def test_malformed_triple_and_member_validity(self):
        data = copy.deepcopy(FIXTURE)
        data['metadata']['forbidden'] = [['2025夏', 'a1']]
        with self.assertRaisesRegex(ValueError, '三元组'):
            contexts_of(data)
        data = copy.deepcopy(FIXTURE)
        data['collections']['events'][0]['members'].append('zz')
        with self.assertRaisesRegex(ValueError, '活动成员或有效层不存在'):
            contexts_of(data)

    def test_redundant_forbidden_is_noted_not_rejected(self):
        data = copy.deepcopy(FIXTURE)
        data['metadata']['forbidden'].append(['2025夏', 'a1', 't5'])  # t5 本可参加但未参加
        data['metadata']['forbidden'].append(['2025冬', 'b1', 't3'])  # t3 在冬季本无资格
        _, notes = build_contexts(load(data, SCHEMAS))
        self.assertEqual(notes['redundant_forbidden'], [['2025冬', 'b1', 't3']])

class SwapChainTests(unittest.TestCase):
    def test_degrees_and_constraints_preserved(self):
        ctx = summer_ctx()
        rng = random.Random('test|degrees')
        chain = SwapChain(ctx, rng)
        team_deg = {t: sum(1 for x, e in ctx.edges if x == t) for t in ctx.teams}
        event_deg = {e: sum(1 for t, x in ctx.edges if x == e) for e in ctx.events}
        accepted = 0
        for _ in range(3000):
            if chain.step():
                accepted += 1
                self.assertTrue(ctx.frozen <= chain.edges)
                self.assertFalse(chain.edges & ctx.forbidden)
                for t in ctx.teams:
                    self.assertEqual(sum(1 for x, e in chain.edges if x == t), team_deg[t])
                for e in ctx.events:
                    self.assertEqual(sum(1 for t, x in chain.edges if x == e), event_deg[e])
        self.assertGreater(accepted, 100)
        self.assertGreater(chain.tally['rejected_forbidden'], 0)

    def test_deterministic_given_seed(self):
        ctx = summer_ctx()
        runs = []
        for _ in range(2):
            result = run_chain(ctx, [lambda: instantiate(['cross_village_pairs'])[0]],
                               random.Random('s|2025夏|chain0'), 10, 2, 20, 10000)
            runs.append(result.samples)
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(len(runs[0]), 20)

class IncrementalTests(unittest.TestCase):
    def test_incremental_matches_full_recompute(self):
        ctx = summer_ctx()
        factories = [lambda n=n: instantiate([n])[0] for n in DEFAULT_CONFIG['statistics']]
        result = run_chain(ctx, factories, random.Random('v|2025夏|c0'), 10, 2, 30, 10000,
                           verify_incremental=True)
        self.assertEqual(len(result.samples), 30)
        for sample in result.samples:
            self.assertIn('pairs.cross_village', sample)
            self.assertIn('triads.cross_kind', sample)

class ExactEnumerationTests(unittest.TestCase):
    def test_summer_space_enumerated_and_connected(self):
        ctx = summer_ctx()
        enum = enumerate_states(ctx, 50000, 2000000)
        self.assertEqual(enum['status'], 'exact')
        self.assertEqual(len(enum['states']), 77)
        self.assertEqual(reachable_states(ctx, 50000)['count'], 77)

    def test_fragmentation_detected(self):
        ctx = contexts_of(fragmented_payload())['L']
        enum = enumerate_states(ctx, 50000, 2000000)
        self.assertEqual(len(enum['states']), 4)
        self.assertEqual(reachable_states(ctx, 50000)['count'], 3)
        report = inspect(fragmented_payload(), FAST)
        layer = report['layers']['L']
        self.assertEqual(layer['domain']['space'], 'fragmented')
        codes = [w['code'] for w in layer['diagnostics']['warnings']]
        self.assertIn('space_fragmented', codes)

    def test_cap_is_reported_not_silent(self):
        ctx = summer_ctx()
        self.assertEqual(enumerate_states(ctx, 10, 2000000)['status'], 'capped')
        self.assertEqual(reachable_states(ctx, 3)['status'], 'capped')

class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = inspect(FIXTURE, FAST)
        cls.summer = cls.report['layers']['2025夏']
        cls.winter = cls.report['layers']['2025冬']

    def test_observed_values(self):
        self.assertEqual(self.summer['observed']['pairs.cross_village'], 5.0)
        self.assertEqual(self.summer['observed']['pairs.cross_kind'], 6.0)
        self.assertEqual(self.summer['observed']['triads.cross_kind'], 4.0)
        self.assertEqual(self.summer['observed']['brokerage.village:t3'], 3.0)
        self.assertEqual(self.summer['observed']['brokerage.village:t1'], 0.0)

    def test_structures_list_concrete_activities(self):
        triads = self.summer['structures']['triads.cross_kind']
        self.assertEqual(triads['total'], 4)
        first = triads['items'][0]
        self.assertIn('sides', first)
        sides = {tuple(s['pair']): s['activities'] for s in first['sides']}
        self.assertTrue(all(sides[p] for p in sides))
        brokerage = self.summer['structures']['brokerage.village:t3']
        self.assertEqual(brokerage['total'], 3)
        for item in brokerage['items']:
            self.assertEqual(item['activities']['broker_right'], ['a4'])
            self.assertIn(item['pair'][1], ('t5',))
        pairs = self.summer['structures']['pairs.cross_village']
        self.assertEqual(pairs['total'], 5)
        for item in pairs['items']:
            self.assertTrue(item['activities'])

    def test_degenerate_layer_reported_explicitly(self):
        codes = [w['code'] for w in self.winter['diagnostics']['warnings']]
        self.assertIn('unique_state_proven', codes)
        self.assertEqual(self.winter['domain']['space'], 'unique_state')
        for key, ref in self.winter['reference'].items():
            self.assertTrue(ref['degenerate'])
            self.assertIn('no_exchangeable_states', ref['flags'])
            self.assertIsNone(ref['p_high'])
            self.assertEqual(ref['exact_p_high'], 1.0)

    def test_family_scope_disclosed_and_bh_applied(self):
        family = self.report['family']
        self.assertEqual(family['method'], 'benjamini-hochberg')
        self.assertEqual(family['tested'], len(family['components']))
        excluded_reasons = {e['reason'] for e in family['excluded']}
        self.assertIn('zero_variance_reference', excluded_reasons)
        self.assertIn('no_exchangeable_states', excluded_reasons)
        for comp in family['components']:
            layer, key = comp.split('|', 1)
            ref = self.report['layers'][layer]['reference'][key]
            self.assertIsNotNone(ref['q_high'])
            self.assertGreaterEqual(ref['q_high'], ref['p_high'] - 1e-9)

    def test_rejection_reasons_tallied(self):
        for chain in self.summer['diagnostics']['chains']:
            self.assertIn('rejected_forbidden', chain['rejected'])
            self.assertGreater(chain['rejected']['rejected_forbidden'], 0)
        self.assertIsNotNone(self.summer['diagnostics']['acceptance_rate'])

    def test_reproducibility_block_and_identity(self):
        repro = self.report['reproducibility']
        self.assertEqual(repro['seed'], DEFAULT_CONFIG['seed'])
        self.assertIn('stream_derivation', repro)
        from app.service import inspect as base_inspect
        self.assertEqual(self.report['input_digest'], base_inspect(FIXTURE)['input_digest'])
        self.assertEqual(self.report['data_version'], 'opportunity-1')
        self.assertIn('scope_note', self.report)

    def test_determinism_same_process(self):
        self.assertEqual(inspect(FIXTURE, FAST), self.report)

    def test_determinism_across_hash_seeds(self):
        outputs = []
        for seed in ('1', '99'):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            out = subprocess.run(
                [sys.executable, '-m', 'app.opportunity', 'fixtures/opportunity.json'],
                cwd=ROOT, env=env, capture_output=True, text=True, check=True)
            outputs.append(out.stdout)
        self.assertEqual(outputs[0], outputs[1])

    def test_input_order_does_not_change_report(self):
        data = copy.deepcopy(FIXTURE)
        for rows in data['collections'].values():
            rows.reverse()
        data['metadata']['forbidden'].reverse()
        self.assertEqual(inspect(data, FAST), self.report)

class SamplerVsExactTests(unittest.TestCase):
    def test_sampler_tracks_exact_distribution(self):
        cfg = {'samples_per_chain': 300, 'thin_swaps': 10, 'burnin_swaps': 100,
               'min_total_samples': 200, 'min_ess': 10}
        report = inspect(FIXTURE, cfg)
        summer = report['layers']['2025夏']
        self.assertEqual(summer['domain']['space'], 'fully_connected')
        checked = 0
        for key, ref in summer['reference'].items():
            if ref['degenerate']:
                continue
            self.assertLessEqual(abs(ref['p_high'] - ref['exact_p_high']), 0.08, key)
            self.assertLessEqual(ref['ks_vs_exact'], 0.12, key)
            checked += 1
        self.assertGreaterEqual(checked, 5)

class DiagnosticsTests(unittest.TestCase):
    def test_no_swap_space_without_exact(self):
        payload = {
            'schema_version': 1,
            'metadata': {'data_version': 'x', 'forbidden': [['L', 'e2', 't1']], 'frozen': []},
            'collections': {
                'events': [
                    {'id': 'e1', 'revision': 1, 'layer': 'L', 'members': ['t1']},
                    {'id': 'e2', 'revision': 1, 'layer': 'L', 'members': ['t2']},
                ],
                'teams': [
                    {'id': 't1', 'revision': 1, 'kind': 'a', 'village': 'v1', 'layers': ['L']},
                    {'id': 't2', 'revision': 1, 'kind': 'b', 'village': 'v2', 'layers': ['L']},
                ],
            },
        }
        report = inspect(payload, {**FAST, 'exact_enabled': False})
        layer = report['layers']['L']
        codes = [w['code'] for w in layer['diagnostics']['warnings']]
        self.assertIn('no_accepted_swaps', codes)
        chain = layer['diagnostics']['chains'][0]
        self.assertGreater(chain['rejected']['rejected_forbidden'], 0)
        for ref in layer['reference'].values():
            self.assertIn('insufficient_reference_samples', ref['flags'])
            self.assertIsNone(ref['p_high'])

    def test_insufficient_samples_suppresses_p(self):
        report = inspect(FIXTURE, {'samples_per_chain': 10, 'thin_swaps': 2,
                                   'burnin_swaps': 5, 'chains': 1})
        for ref in report['layers']['2025夏']['reference'].values():
            self.assertIn('insufficient_reference_samples', ref['flags'])
            self.assertIsNone(ref['p_high'])
        self.assertEqual(report['family']['tested'], 0)

    def test_ess_behaviour(self):
        self.assertIsNone(autocorr_ess([3.0] * 50))
        rng = random.Random('ess')
        series = [rng.gauss(0, 1) for _ in range(200)]
        ess = autocorr_ess(series)
        self.assertGreater(ess, 100)
        self.assertLessEqual(ess, 200)
        self.assertEqual(autocorr_ess([1.0, 2.0]), 2.0)

class ConfigTests(unittest.TestCase):
    def test_unknown_key_and_bad_types(self):
        with self.assertRaisesRegex(ValueError, '未知配置项'):
            inspect(FIXTURE, {'nope': 1})
        with self.assertRaisesRegex(ValueError, 'seed'):
            inspect(FIXTURE, {'seed': 'abc'})
        with self.assertRaisesRegex(ValueError, 'chains'):
            inspect(FIXTURE, {'chains': 0})
        with self.assertRaisesRegex(ValueError, 'statistics'):
            inspect(FIXTURE, {'statistics': ['cross_village_pairs', 'cross_village_pairs']})
        with self.assertRaisesRegex(ValueError, '未知统计量'):
            inspect(FIXTURE, {'statistics': ['made_up']})

class BhTests(unittest.TestCase):
    def test_step_up_values(self):
        qs = benjamini_hochberg([('a', 0.01), ('b', 0.02), ('c', 0.5)])
        self.assertAlmostEqual(qs['a'], 0.03)
        self.assertAlmostEqual(qs['b'], 0.03)
        self.assertAlmostEqual(qs['c'], 0.5)
        self.assertEqual(benjamini_hochberg([]), {})

if __name__ == '__main__':
    unittest.main()
