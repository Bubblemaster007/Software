"""Isolated queue transitions, immutable inputs, cancellation races and execution."""
from pathlib import Path
from contextlib import closing
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy
import json
import unittest
from fastapi.testclient import TestClient
from backend.app import app
from backend.engineering import Inventory
from backend.network_data import Network
from backend import study_jobs as jobs
from backend.resource_dispatch import DispatchIncomplete


class StudyJobTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.schedule_impl = jobs.schedule
        self.root = Path(self.folder.name)
        (self.root/'data').mkdir()
        self.patches = [patch('backend.workspace.ROOT', self.root), patch('backend.engineering.ROOT', self.root),
                        patch('backend.study_jobs.ROOT', self.root), patch('backend.study_jobs.schedule')]
        for p in self.patches:
            p.start()
        self.client = TestClient(app)
        self.network = Network(nodes=[{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 100}],
                               lines=[{'line': 7, 'from_node': 1, 'to_node': 2, 'r_ohm': 0, 'x_ohm': 0}])
        self.project = self.client.post('/api/projects', json={'name': '后台隔离测试', 'state': {'network': self.network.model_dump()}}).json()
        self.inventory = Inventory(loads=[{'id': 'L', 'name': '重要负荷', 'node': 2, 'peak_kw': 100, 'target_hours': 2}]).model_dump()
        self.url = '/api/engineering/projects/'+self.project['id']
        self.client.put(self.url, json={'project_revision': 1, 'expected_revision': 0, 'inventory': self.inventory}).raise_for_status()
        self.params = {'project_id': self.project['id'], 'project_revision': 1, 'engineering_revision': 1,
                       'steps': 2, 'grid_available_kw': [100]}

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.folder.cleanup()

    def submit(self, module='device_dispatch', parameters=None):
        response = self.client.post('/api/study-jobs', json={'module': module, 'parameters': parameters or self.params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def execute(self, job):
        jobs.update(job['id'], {'queued'}, launch_token='test-token')
        jobs.execute(job['id'], 'test-token')
        return jobs.get(job['id'], True, True)

    def test_execution_frozen_inventory_and_exports(self):
        job = self.submit()
        changed = copy.deepcopy(self.inventory)
        changed['loads'][0]['peak_kw'] = 200
        self.client.put(self.url, json={'project_revision': 1, 'expected_revision': 1, 'inventory': changed}).raise_for_status()
        result = self.execute(job)
        self.assertEqual(result['status'], 'succeeded')
        self.assertAlmostEqual(result['result']['metrics']['served_energy_kwh'], 200)
        self.assertEqual(result['input']['engineering']['inventory']['loads'][0]['peak_kw'], 100)
        self.assertNotIn('input', self.client.get('/api/study-jobs/'+job['id']).json())
        csv = self.client.get('/api/study-jobs/'+job['id']+'/csv')
        self.assertEqual(len(csv.text.strip().splitlines()), 3)
        full = self.client.get('/api/study-jobs/'+job['id']+'/download').json()
        self.assertEqual(full['input_sha256'], job['input_sha256'])
        self.assertFalse(jobs.update(job['id'], {'succeeded'}, status='failed'))

    def test_annual_window_archives_csv_and_report(self):
        job = self.submit('annual_dispatch', {'base': self.params, 'coverage_mode': 'series',
                                             'total_steps': 3, 'commit_steps': 1})
        result = self.execute(job)
        self.assertEqual(result['status'], 'succeeded', result.get('error'))
        prefix = '/api/study-jobs/'+job['id']
        windows = self.client.get(prefix+'/annual-windows').json()
        self.assertEqual(len(windows), 3)
        artifact = self.client.get(prefix+'/annual-windows/window-00001').json()
        self.assertEqual(artifact['committed_rows'][0]['global_step'], 0)
        self.assertEqual(artifact['state_after']['elapsed_hours'], 1)
        self.assertEqual(len(self.client.get(prefix+'/csv').text.strip().splitlines()), 4)
        self.assertIn('300.0', self.client.get(prefix+'/report').text)

    def test_cancelled_annual_keeps_only_committed_window_evidence(self):
        job = self.submit('annual_dispatch', {'base': self.params, 'coverage_mode': 'series',
                                             'total_steps': 3, 'commit_steps': 1})
        from backend.resource_dispatch import dispatch
        calls = 0
        def cancel_in_second_window(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                jobs.cancel(job['id'])
            return dispatch(*args, **kwargs)
        with patch('backend.annual_dispatch.dispatch', side_effect=cancel_in_second_window):
            result = self.execute(job)
        self.assertEqual(result['status'], 'cancelled')
        self.assertIsNone(result['result'])
        prefix = '/api/study-jobs/'+job['id']
        self.assertEqual(len(self.client.get(prefix+'/annual-windows').json()), 1)
        self.assertEqual(len(self.client.get(prefix+'/csv').text.strip().splitlines()), 2)
        self.assertEqual(self.client.get(prefix+'/report').status_code, 409)

    def test_annual_csv_releases_connection_between_stream_chunks(self):
        from concurrent.futures import ThreadPoolExecutor
        import sqlite3
        job = self.submit('annual_dispatch', {'base': self.params, 'coverage_mode': 'series',
                                             'total_steps': 3, 'commit_steps': 1})
        self.execute(job)
        with patch.object(jobs, 'StreamingResponse', side_effect=lambda content, **kwargs: content):
            iterator = jobs.annual_csv(job)
        with ThreadPoolExecutor(max_workers=1) as first, ThreadPoolExecutor(max_workers=1) as second:
            chunks = []
            for executor in (first, second, first, second):
                chunks.append(executor.submit(next, iterator).result())
                with closing(sqlite3.connect(self.root/'data/platform.db', timeout=.1)) as connection:
                    connection.execute('BEGIN EXCLUSIVE')
                    connection.rollback()
        self.assertEqual(len(''.join(chunks).strip().splitlines()), 4)
        iterator.close()

    def test_queued_cancel_and_late_worker_cannot_commit(self):
        job = self.submit()
        jobs.update(job['id'], {'queued'}, launch_token='token')
        self.client.post('/api/study-jobs/'+job['id']+'/cancel').raise_for_status()
        jobs.execute(job['id'], 'token')
        r = jobs.get(job['id'], include_result=True)
        self.assertEqual(r['status'], 'cancelled')
        self.assertIsNone(r['result'])

    def test_cancel_during_final_solver_call_wins_over_success(self):
        job = self.submit()
        from backend.resource_dispatch import dispatch
        def cancel_inside(*args, **kwargs):
            result = dispatch(*args, **kwargs)
            jobs.cancel(job['id'])
            return result
        with patch('backend.study_jobs.dispatch', side_effect=cancel_inside):
            r = self.execute(job)
        self.assertEqual(r['status'], 'cancelled')
        self.assertIsNone(r['result'])

    def test_retry_preserves_old_snapshot_and_new_identity(self):
        job = self.submit()
        self.client.post('/api/study-jobs/'+job['id']+'/cancel')
        r = self.client.post('/api/study-jobs/'+job['id']+'/retry').json()
        self.assertNotEqual(r['id'], job['id'])
        self.assertEqual(r['retry_from'], job['id'])
        original, retried = jobs.get(job['id'], True), jobs.get(r['id'], True)
        self.assertEqual(original['input']['engineering'], retried['input']['engineering'])
        self.assertEqual(original['status'], 'cancelled')
        self.assertEqual(self.client.post('/api/study-jobs/'+r['id']+'/retry').status_code, 409)

    def test_stale_build_is_rejected_and_no_incumbent_not_infeasible(self):
        job = self.submit()
        snap = jobs.get(job['id'], True)['input']
        snap['runtime'] = {**snap['runtime'], 'build_id': 'different'}
        stale = jobs.enqueue(snap)
        r = self.execute(stale)
        self.assertEqual(r['status'], 'failed')
        self.assertIn('构建已变化', r['error'])
        with patch('backend.study_jobs.dispatch', side_effect=DispatchIncomplete('尚无可行解')):
            r = self.execute(job)
        self.assertEqual(r['status'], 'incomplete')
        self.assertIsNone(r['result'])

    def test_worker_failure_and_dead_process_reconciliation(self):
        job = self.submit()
        with patch('backend.study_jobs.dispatch', side_effect=ValueError('输入错误反例')):
            r = self.execute(job)
        self.assertEqual(r['status'], 'failed')
        another = self.submit()
        jobs.update(another['id'], {'queued'}, status='running', pid=123456, process_identity='original')
        with patch('backend.study_jobs.process_identity', return_value='reused-pid'):
            jobs.audit()
        self.assertEqual(jobs.get(another['id'])['status'], 'interrupted')

    def test_global_two_worker_reservation_and_cancel_frees_slot(self):
        tasks = [self.submit() for _ in range(3)]
        with patch('backend.study_jobs.subprocess.Popen') as spawn, patch('backend.study_jobs.process_identity', return_value='stamp'):
            spawn.return_value.pid = 123456
            self.schedule_impl()
            self.assertEqual(spawn.call_count, 2)
            self.schedule_impl()
            self.assertEqual(spawn.call_count, 2)
            jobs.cancel(tasks[0]['id'])
            self.schedule_impl()
            self.assertEqual(spawn.call_count, 3)
        self.assertIsNotNone(jobs.get(tasks[2]['id']).get('launch_token'))

    def test_snapshot_tampering_never_computes(self):
        job = self.submit()
        snap = jobs.get(job['id'], True)['input']
        snap['parameters']['grid_available_kw'] = [999]
        with closing(jobs.connection()) as c, c:
            c.execute('UPDATE study_jobs SET input=? WHERE id=?', (json.dumps(snap), job['id']))
        with patch('backend.study_jobs.dispatch') as compute:
            r = self.execute(job)
            compute.assert_not_called()
        self.assertEqual(r['status'], 'failed')
        self.assertIn('摘要不匹配', r['error'])

    def test_real_disaster_worker_and_project_history_isolation(self):
        params = {'base': self.params, 'intensities': [0, 1], 'durations_hours': [1], 'samples': 1,
                  'criterion': 'energy_budget', 'judgement': 'empirical', 'fragilities': [
                      {'kind': 'line', 'target_id': '7', 'failure_probability': 1, 'repair_hours': 1, 'provenance': '人工测试'}]}
        job = self.submit('disaster_scan', params)
        r = self.execute(job)
        self.assertEqual(r['status'], 'succeeded')
        self.assertAlmostEqual(r['result']['cases'][1]['mean_unsupplied_kwh'], 100)
        other = self.client.post('/api/projects', json={'name': '另一工程'}).json()
        self.assertEqual(self.client.get('/api/study-jobs?project_id='+other['id']).json(), [])
        self.assertEqual(self.client.post('/api/study-jobs', json={'module': 'arbitrary_script', 'parameters': {}}).status_code, 422)

    def test_restoration_worker_frozen_controls_and_csv(self):
        inv = copy.deepcopy(self.inventory)
        inv['sources'] = [{'id': 'D', 'name': '柴油黑启动源', 'kind': '柴油机', 'node': 2, 'rated_kw': 100,
                           'fuel_kwh': 1000, 'grid_forming': True, 'black_start': True}]
        self.client.put(self.url, json={'project_revision': 1, 'expected_revision': 1, 'inventory': inv}).raise_for_status()
        params = {'base': self.params | {'engineering_revision': 2, 'grid_available_kw': [0]},
                  'initial_closed_lines': [7], 'manual_resource_ids': ['D']}
        job = self.submit('restoration', params)
        r = self.execute(job)
        self.assertEqual(r['status'], 'succeeded')
        self.assertEqual(r['result']['actions'][0]['target_id'], 'D')
        self.assertEqual(r['result']['operational_clearance'], 'not_cleared')
        self.assertAlmostEqual(r['result']['dispatch']['metrics']['served_energy_kwh'], 100)
        exported = self.client.get('/api/study-jobs/'+job['id']+'/csv')
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(len(exported.text.strip().splitlines()), 2)

    def test_experiment_worker_separate_case_archive_csv_and_escaped_report(self):
        inv = copy.deepcopy(self.inventory)
        inv['sources'] = [{'id':'D','name':'候选','node':2,'kind':'柴油机','rated_kw':100,'existing':False,
                           'fuel_kwh':1000,'grid_forming':True,'black_start':True}]
        self.client.put(self.url, json={'project_revision':1,'expected_revision':1,'inventory':inv}).raise_for_status()
        params = {'base':self.params | {'engineering_revision':2}, 'name':'<script>对比</script>',
                  'candidates':[{'asset_id':'D','capex_yuan':100}], 'stages':[{'name':'近期','year':2026,'annual_occurrences':0}],
                  'scenarios':[{'id':'grid','weight':.8,'grid_available_kw':[100]},{'id':'off','weight':.2}],
                  'required_probability':1,'probability_levels':[.8,1],'sensitivities':[]}
        job = self.submit('investment_experiments', params)
        result = self.execute(job)
        self.assertEqual(result['status'], 'succeeded', result.get('error'))
        self.assertEqual(len(result['result']['cases']), 2)
        self.assertNotIn('detail', result['result']['cases'][0])
        detail = self.client.get('/api/study-jobs/'+job['id']+'/experiment-cases/baseline')
        self.assertEqual(detail.status_code,200)
        self.assertEqual(detail.json()['result']['objective_yuan'],100)
        self.assertTrue(detail.json()['result']['scenario_results'][0]['result']['rows'])
        self.assertEqual(self.client.get('/api/study-jobs/'+job['id']+'/experiment-cases/unknown').status_code,404)
        csv = self.client.get('/api/study-jobs/'+job['id']+'/csv')
        self.assertEqual(len(csv.text.strip().splitlines()),3)
        report = self.client.get('/api/study-jobs/'+job['id']+'/report')
        self.assertEqual(report.status_code,200)
        self.assertIn('&lt;script&gt;', report.text)
        self.assertNotIn('<script>', report.text)
        from backend.backup import create_backup
        content,manifest = create_backup(self.root/'data/platform.db')
        self.assertTrue(content)
        self.assertIn('study_case_results', str(manifest))

    def test_investment_worker_shared_build_and_selected_assets_csv(self):
        inv = copy.deepcopy(self.inventory)
        inv['sources'] = [{'id': 'D', 'name': '待建柴油机', 'node': 2, 'kind': '柴油机', 'existing': False,
                           'rated_kw': 100, 'fuel_kwh': 1000, 'grid_forming': True, 'black_start': True}]
        self.client.put(self.url, json={'project_revision': 1, 'expected_revision': 1, 'inventory': inv}).raise_for_status()
        params = {'base': self.params | {'engineering_revision': 2, 'grid_available_kw': [0]},
                  'name': '<script>alert(1)</script>',
                  'candidates': [{'asset_id': 'D', 'capex_yuan': 100}], 'stages': [{'name': '近期', 'year': 2026, 'annual_occurrences': 0}],
                  'scenarios': [{'id': 'A', 'weight': .8, 'grid_available_kw': [100]}, {'id': 'B', 'weight': .2}],
                  'required_probability': 1}
        job = self.submit('investment', params)
        result = self.execute(job)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['result']['selected_assets'][0]['asset_id'], 'D')
        self.assertAlmostEqual(result['result']['objective_yuan'], 100)
        self.assertEqual(len(self.client.get('/api/study-jobs/'+job['id']+'/csv').text.strip().splitlines()), 2)
        self.assertEqual(result['input']['engineering']['revision'], 2)
        cash = self.client.get('/api/study-jobs/'+job['id']+'/csv?dataset=cashflows')
        self.assertEqual(len(cash.text.strip().splitlines()), 2)
        report = self.client.get('/api/study-jobs/'+job['id']+'/report')
        self.assertEqual(report.status_code, 200)
        self.assertIn('&lt;script&gt;', report.text)
        self.assertNotIn('<script>', report.text)
        self.assertIn('未提供或未执行样本外验证', report.text)
        self.assertEqual(self.client.get('/api/study-jobs/'+job['id']+'/csv?dataset=arbitrary').status_code, 422)


if __name__ == '__main__':
    unittest.main()
