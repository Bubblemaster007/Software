"""Frozen-source extraction, physical accounting and immutable evaluation proof."""
from contextlib import closing
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import app
from backend import study_jobs as jobs
from backend.effect_evaluation import EvaluationInput, evaluation_result, topsis
from backend.engineering import canonical_sha


class ArchiveEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root/'data').mkdir()
        self.patches = [patch('backend.'+name+'.ROOT', self.root) for name in
                        ('workspace', 'engineering', 'resource_dispatch', 'study_jobs', 'effect_evaluation')]
        self.patches.append(patch('backend.study_jobs.schedule'))
        for item in self.patches:
            item.start()
        self.client = TestClient(app)
        network = {'nodes': [{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 10}],
                   'lines': [{'line': 1, 'from_node': 1, 'to_node': 2, 'r_ohm': 0, 'x_ohm': 0}]}
        self.project = self.client.post('/api/projects', json={'name': '指标提取测试', 'state': {'network': network}}).json()
        self.url = '/api/engineering/projects/'+self.project['id']
        self.inventory = self.client.get(self.url).json()['inventory']
        self.inventory['loads'] = [{'id': 'L', 'name': '人工负荷', 'node': 2, 'peak_kw': 10, 'target_hours': 2}]
        self.client.put(self.url, json={'project_revision': 1, 'expected_revision': 0, 'inventory': self.inventory}).raise_for_status()
        self.base = {'project_id': self.project['id'], 'project_revision': 1, 'engineering_revision': 1,
                     'steps': 2, 'grid_available_kw': [10]}

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.folder.cleanup()

    def dispatch(self, **changes):
        response = self.client.post('/api/device-dispatch', json=self.base | changes)
        response.raise_for_status()
        return response.json()

    def execute(self, module, parameters):
        response = self.client.post('/api/study-jobs', json={'module': module, 'parameters': parameters})
        response.raise_for_status()
        job = response.json()
        jobs.update(job['id'], {'queued'}, launch_token='test-token')
        jobs.execute(job['id'], 'test-token')
        result = jobs.get(job['id'], True, True)
        self.assertEqual(result['status'], 'succeeded', result.get('error'))
        return result

    def body(self, references, **changes):
        return {'project_id': self.project['id'], 'project_revision': 1, 'references': references,
                'metric_ids': ['study_dispatch_cost_yuan', 'energy_supply_ratio'], **changes}

    def test_trace_cost_ratio_safety_and_frozen_history(self):
        first = self.dispatch(name='完整供电')
        second = self.dispatch(name='部分供电', grid_available_kw=[5])
        refs = [{'kind': 'device_dispatch', 'id': row['id']} for row in (first, second)]
        response = self.client.post('/api/effect-evaluations/archive-preview', json=self.body(refs))
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertEqual([row['values'] for row in preview['input']['alternatives']], [[10, 1], [5, .5]])
        self.assertEqual(preview['source_evidence']['comparability']['status'], 'same_recorded_basis')
        for ref, proof in zip(refs, preview['source_evidence']['sources']):
            ref['expected_sha256'] = proof['sha256']
        response = self.client.post('/api/effect-evaluations/archive-evaluate', json=self.body(refs))
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual(saved['origin'], 'frozen_archive_indicators')
        self.assertEqual(saved['input_sha256'], canonical_sha(saved['input']))
        ranks = {row['id']: row for row in saved['result']['ranking']}
        self.assertEqual(ranks['archive-1']['gate'], 'not_checked')
        self.assertEqual(ranks['archive-2']['gate'], 'failed')
        self.assertEqual(len(saved['result']['weight_sensitivity']['cases']), 5)
        self.assertFalse(any(row['engineering_recommendation'] for row in ranks.values()))
        self.inventory['loads'][0]['peak_kw'] = 15
        self.client.put(self.url, json={'project_revision': 1, 'expected_revision': 1, 'inventory': self.inventory}).raise_for_status()
        self.assertEqual(self.client.get('/api/effect-evaluations/'+saved['id']).json(), saved)
        catalog = self.client.get('/api/effect-evaluations/archive-sources?project_id='+self.project['id']).json()
        self.assertEqual(len(catalog['sources']), 2)
        self.assertTrue(all(item['id'] != 'reliability' for item in catalog['metrics']))

    def test_foreign_missing_metric_duplicate_and_stale_source_rejected(self):
        first, second = self.dispatch(), self.dispatch()
        refs = [{'kind': 'device_dispatch', 'id': row['id']} for row in (first, second)]
        duplicate = self.client.post('/api/effect-evaluations/archive-preview', json=self.body([refs[0], refs[0]]))
        self.assertEqual(duplicate.status_code, 422)
        self.assertEqual(self.client.post('/api/effect-evaluations/archive-preview', json=self.body(refs,
            metric_ids=['validation_target_success_lower'])).status_code, 422)
        self.assertEqual(self.client.post('/api/effect-evaluations/archive-preview', json=self.body(refs,
            alternatives=[{'values': [0, 0]}])).status_code, 422)
        bad = copy.deepcopy(refs)
        bad[0]['expected_sha256'] = '0'*64
        self.assertEqual(self.client.post('/api/effect-evaluations/archive-evaluate', json=self.body(bad)).status_code, 409)
        other = self.client.post('/api/projects', json={'name': '隔离工程'}).json()
        self.assertEqual(self.client.post('/api/effect-evaluations/archive-preview', json=self.body(refs,
            project_id=other['id'])).status_code, 422)
        self.assertEqual(self.client.post('/api/effect-evaluations/archive-preview', json=self.body(refs,
            project_revision=99)).status_code, 409)

    def test_duration_and_demand_differences_are_exposed(self):
        first, second = self.dispatch(), self.dispatch(steps=3)
        refs = [{'kind': 'device_dispatch', 'id': row['id']} for row in (first, second)]
        result = self.client.post('/api/effect-evaluations/archive-preview', json=self.body(refs)).json()
        comparison = result['source_evidence']['comparability']
        self.assertEqual(comparison['status'], 'differences_present')
        self.assertIn('steps', [row['field'] for row in comparison['differences']])
        self.assertIn('demand_trace_sha256', [row['field'] for row in comparison['differences']])

    def test_annual_uses_committed_rows_and_checks_missing_window(self):
        first = self.execute('annual_dispatch', {'base': self.base | {'steps': 4, 'step_hours': .25},
                             'coverage_mode': 'series', 'total_steps': 5, 'commit_steps': 2})
        second = self.execute('annual_dispatch', {'base': self.base | {'steps': 4, 'step_hours': .25},
                              'coverage_mode': 'series', 'total_steps': 5, 'commit_steps': 2})
        refs = [{'kind': 'study_job', 'id': row['id']} for row in (first, second)]
        body = self.body(refs, metric_ids=['served_energy_kwh', 'study_dispatch_cost_yuan'])
        response = self.client.post('/api/effect-evaluations/archive-preview', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertEqual(preview['input']['alternatives'][0]['values'], [12.5, 6.25])
        self.assertEqual(preview['source_evidence']['sources'][0]['derivation']['steps'], 5)
        self.assertEqual(len(preview['source_evidence']['sources'][0]['derivation']['window_hashes']), 3)
        with closing(jobs.connection()) as connection, connection:
            connection.execute('DELETE FROM study_case_results WHERE job_id=? AND case_id=?', (first['id'], 'window-00002'))
        self.assertEqual(self.client.post('/api/effect-evaluations/archive-preview', json=body).status_code, 422)

    def test_investment_and_case_cashflows_holdout_and_no_fabricated_probability(self):
        self.inventory['sources'] = [{'id': 'D', 'name': '人工候选', 'node': 2, 'kind': '柴油机',
            'rated_kw': 10, 'existing': False, 'fuel_kwh': 100, 'grid_forming': True, 'black_start': True}]
        self.client.put(self.url, json={'project_revision': 1, 'expected_revision': 1, 'inventory': self.inventory}).raise_for_status()
        params = {'base': self.base | {'engineering_revision': 2, 'grid_available_kw': [0]},
            'candidates': [{'asset_id': 'D', 'capex_yuan': 100}],
            'stages': [{'name': '近期', 'year': 2026, 'annual_occurrences': 0}],
            'scenarios': [{'id': 'grid', 'weight': .8, 'grid_available_kw': [10]}, {'id': 'off', 'weight': .2}],
            'required_probability': 1, 'probability_levels': [.8, 1], 'sensitivities': [],
            'validation_scenarios': [{'id': 'holdout', 'weight': 1, 'device_availability': {'D': [0]}}]}
        study = self.execute('investment_experiments', params)
        refs = [{'kind': 'investment_case', 'id': study['id'], 'case_id': case} for case in ('baseline', 'risk-01')]
        body = self.body(refs, metric_ids=['capex_yuan', 'discounted_cost_yuan',
            'training_target_success_probability', 'validation_target_success_lower', 'worst_period_event_unsupplied_kwh'])
        response = self.client.post('/api/effect-evaluations/archive-evaluate', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        values = [row['values'] for row in response.json()['input']['alternatives']]
        self.assertEqual(values[0], [100, 100, 1, 0, 0])
        self.assertAlmostEqual(values[1][4], 4)
        self.assertEqual(values[1][:4], [0, 0, .8, 0])
        self.assertTrue(all(row['gate'] == 'failed' for row in response.json()['result']['ranking']))
        catalog = self.client.get('/api/effect-evaluations/archive-sources?project_id='+self.project['id']).json()
        self.assertEqual(len(catalog['sources']), 2)
        direct = {key: value for key, value in params.items() if key not in ('probability_levels', 'sensitivities', 'validation_scenarios')}
        job = self.execute('investment', direct)
        response = self.client.post('/api/effect-evaluations/archive-preview', json=self.body(
            [{'kind': 'study_job', 'id': job['id']}, refs[0]], metric_ids=['validation_target_success_lower']))
        self.assertEqual(response.status_code, 422)

    def test_manual_sweep_matches_each_recomputation_and_exports_are_escaped(self):
        body = {'project_id': self.project['id'], 'project_revision': 1, 'name': '<script>评价</script>',
                'criteria': [{'id': 'a', 'name': '成本', 'direction': 'cost'},
                             {'id': 'b', 'name': '收益', 'direction': 'benefit'}],
                'alternatives': [{'id': 'a', 'name': 'A', 'values': [100, .5], 'provenance': '人工'},
                                 {'id': 'b', 'name': 'B', 'values': [120, .9], 'provenance': '人工'},
                                 {'id': 'c', 'name': 'C', 'values': [300, 1], 'provenance': '人工'}],
                'entropy_sweep': [0, .3, 1], 'entropy_share': .5}
        req = EvaluationInput.model_validate(body)
        result = evaluation_result(req)
        self.assertEqual(len(result['weight_sensitivity']['cases']), 4)
        for case in result['weight_sensitivity']['cases']:
            self.assertEqual(case['ranking'], topsis(req.model_copy(update={'entropy_share': case['entropy_share']}))['ranking'])
        response = self.client.post('/api/effect-evaluations', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        identity = response.json()['id']
        report = self.client.get('/api/effect-evaluations/'+identity+'/report')
        self.assertIn('&lt;script&gt;', report.text)
        self.assertNotIn('<script>', report.text)
        self.assertIn('组合权重敏感性', report.text)
        self.assertEqual(len(self.client.get('/api/effect-evaluations/'+identity+'/csv?dataset=sensitivity').text.strip().splitlines()), 13)
        self.assertEqual(self.client.get('/api/effect-evaluations/'+identity+'/csv?dataset=unknown').status_code, 422)
        invalid = body | {'entropy_sweep': [0, 0]}
        self.assertEqual(self.client.post('/api/effect-evaluations', json=invalid).status_code, 422)


if __name__ == '__main__':
    unittest.main()
