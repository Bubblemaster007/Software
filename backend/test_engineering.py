"""Isolated regressions against hand-computable topic1 and immutable inventory."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy
import json
import sqlite3
import unittest
from fastapi.testclient import TestClient
from backend.app import app
from backend.engineering import canonical_sha


class EngineeringTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / 'data').mkdir()
        self.patches = [patch('backend.workspace.ROOT', self.root), patch('backend.engineering.ROOT', self.root),
                        patch('backend.module_contracts.ROOT', self.root), patch('backend.app.DATA', self.root / 'data')]
        for p in self.patches:
            p.start()
        self.c = TestClient(app)
        self.project = self.c.post('/api/projects', json={'name': '隔离测试', 'kind': '乡镇级'}).json()
        self.url = '/api/engineering/projects/' + self.project['id']
        self.inventory = self.c.get(self.url).json()['inventory']

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.folder.cleanup()

    def save(self, inventory=None, revision=0, project_revision=1):
        return self.c.put(self.url, json={'inventory': inventory or self.inventory,
                                         'expected_revision': revision, 'project_revision': project_revision})

    def test_eleven_templates_cover_exact_ppt_combinations(self):
        rows = self.c.get('/api/engineering/scenario-templates').json()['templates']
        self.assertEqual(len(rows), 11)
        self.assertEqual(len({r['id'] for r in rows}), 11)
        self.assertEqual([sum(r['kind'] == k for r in rows) for k in ['县域级', '乡镇级', '村级']], [2, 6, 3])
        for r in rows:
            self.assertIsNone(r['probability'])
            self.assertFalse(r['calibrated'])
            if r['kind'] == '村级':
                self.assertEqual(r['return_period_years'], 20)
            self.assertEqual(r['targets'][0]['target_hours'], 72 if r['region'] == '西部' else 48)

    def test_priority_formula_and_cti_thresholds(self):
        body = {'cti': .75, 'historical_consequence': .8, 'repair_hours': 24, 'repair_reference_hours': 72,
                'disaster_hours': 48, 'disaster_reference_hours': 72, 'supply_kw': 100, 'supply_reference_kw': 500,
                'interruptibility': 0, 'curtailability': 0, 'weights': [.2, .15, .2, .15, .15, .15], 'beta': .6}
        expected = .2 * .8 + .15 * (1 - 24 / 72) + .2 * (48 / 72) + .15 * .8 + .15 + .15
        for cti, cls, importance in [(.75, '基本保障', .93), (.74999, '居民生活', .7), (.3, '居民生活', .7), (.29999, '一般负荷', .56)]:
            r = self.c.post('/api/engineering/priority', json={**body, 'cti': cti})
            self.assertEqual(r.status_code, 200, r.text)
            d = r.json()
            self.assertEqual(d['load_class'], cls)
            self.assertAlmostEqual(d['demand_index'], expected)
            self.assertAlmostEqual(d['priority_score'], .6 * expected + .4 * importance)
            self.assertAlmostEqual(sum(t['contribution'] for t in d['components']), expected)
        for change in [{'weights': [1, 1, 1, 1, 1, 1]}, {'repair_reference_hours': 0}, {'supply_kw': 501}, {'repair_hours': 73}]:
            self.assertEqual(self.c.post('/api/engineering/priority', json={**body, **change}).status_code, 422)

    def test_inventory_versions_concurrency_and_project_isolation(self):
        self.inventory['loads'] = [{'id': 'load-A', 'name': '卫生院', 'node': 2, 'peak_kw': 100,
                                    'load_class': '基本保障', 'target_hours': 72}]
        r = self.save()
        self.assertEqual(r.status_code, 200, r.text)
        first = r.json()
        self.assertEqual(first['sha256'], canonical_sha(first['inventory']))
        self.assertEqual(self.save().status_code, 409)
        self.inventory['loads'][0]['peak_kw'] = 200
        self.assertEqual(self.save(revision=1).status_code, 200)
        old = self.c.get(self.url + '/versions/1').json()
        self.assertEqual(old['inventory']['loads'][0]['peak_kw'], 100)
        self.assertEqual(self.c.get(self.url).json()['inventory']['loads'][0]['peak_kw'], 200)
        other = self.c.post('/api/projects', json={'name': '另一工程', 'kind': '村级'}).json()
        self.assertEqual(self.c.get('/api/engineering/projects/' + other['id']).json()['revision'], 0)
        self.assertEqual(self.c.get('/api/engineering/projects/' + other['id'] + '/versions/1').status_code, 404)

    def test_geography_disaster_draft_validation(self):
        url='/api/drafts/地理与灾害?project_id='+self.project['id']
        base={'geography':{'region':'阿拉山口','longitude':82.56,'latitude':45.17,'coordinate_system':'WGS84'},
              'disaster':{'event_id':'E1','hazard_type':'覆冰','start_time':'2026-01-01T00:00','end_time':'2026-01-02T00:00','verified':True,'source':'历史台账','affected_devices':'line-1,line-2'}}
        self.assertEqual(self.c.put(url,json={'values':base}).status_code,200)
        self.assertEqual(self.c.get(url).json()['values']['geography']['region'],'阿拉山口')
        bad=copy.deepcopy(base); bad['geography']['longitude']=181
        self.assertEqual(self.c.put(url,json={'values':bad}).status_code,422)
        bad=copy.deepcopy(base); bad['disaster']['end_time']='2025-01-01T00:00'
        self.assertEqual(self.c.put(url,json={'values':bad}).status_code,422)
        bad=copy.deepcopy(base); bad['disaster']['source']=''
        self.assertEqual(self.c.put(url,json={'values':bad}).status_code,422)

    def test_joint_and_flexible_network_draft_validation(self):
        joint={'primary_candidates':[],'switches':[],'terminals':[],'controllers':[],'communication_links':[],
               'budget_yuan':1000,'objective':'可靠性','provenance':'工程草稿'}
        u='/api/drafts/一二次协同规划?project_id='+self.project['id']
        self.assertEqual(self.c.put(u,json={'values':joint}).status_code,200)
        bad=copy.deepcopy(joint); bad['switches']={}
        self.assertEqual(self.c.put(u,json={'values':bad}).status_code,422)
        flex={'zones':[],'tie_lines':[],'normally_open_switches':[],'islanding_rules':[],
              'source_priority':[],'communication_dependencies':[],'objective':'组网','provenance':'工程草稿'}
        f='/api/drafts/灵活组网?project_id='+self.project['id']
        self.assertEqual(self.c.put(f,json={'values':flex}).status_code,200)
        bad=copy.deepcopy(flex); bad.pop('provenance')
        self.assertEqual(self.c.put(f,json={'values':bad}).status_code,422)

    def test_deliverables_draft_validation(self):
        u='/api/drafts/成果与交付?project_id='+self.project['id']
        body={'rows':[{'id':'manual','name':'用户手册','status':'待补','source':'','note':''}]}
        self.assertEqual(self.c.put(u,json={'values':body}).status_code,200)
        bad={'rows':[{'id':'manual','name':'用户手册','status':'未知','source':'','note':''}]}
        self.assertEqual(self.c.put(u,json={'values':bad}).status_code,422)

    def test_demonstration_evidence_validation(self):
        u='/api/drafts/示范区实证?project_id='+self.project['id']
        e={'region':'阿拉山口','project_level':'乡镇级','basis':'实测','measurement_period':'2026-01','measured_metrics':'缺供电量','conclusion':'待项目组确认','source':'现场记录','status':'待补'}
        self.assertEqual(self.c.put(u,json={'values':{'evidence':e}}).status_code,200)
        bad=copy.deepcopy(e);bad['status']='未知';self.assertEqual(self.c.put(u,json={'values':{'evidence':bad}}).status_code,422)
        bad=copy.deepcopy(e);bad['status']='已验收';bad['source']='';self.assertEqual(self.c.put(u,json={'values':{'evidence':bad}}).status_code,422)
        bad={'rows':[{'id':'manual','name':'用户手册','status':'待补','source':'','note':''},{'id':'manual','name':'重复','status':'待补','source':'','note':''}]}
        self.assertEqual(self.c.put(u,json={'values':bad}).status_code,422)
        self.assertEqual(self.save(revision=2, project_revision=99).status_code, 409)

    def test_constraints_references_and_coordinates(self):
        cases = [
            ('storage', {'id': 'E', 'name': '储能', 'node': 2, 'power_kw': 10, 'energy_kwh': 20, 'initial_soc': .05}),
            ('sources', {'id': 'P', 'name': '光伏', 'node': 2, 'kind': '光伏', 'rated_kw': 10, 'minimum_kw': 11}),
            ('sources', {'id': 'P', 'name': '光伏', 'node': 2, 'kind': '光伏', 'rated_kw': 10, 'black_start': True}),
            ('loads', {'id': 'L', 'name': '负荷', 'node': 99, 'peak_kw': 10}),
            ('loads', {'id': 'L', 'name': '负荷', 'node': 2, 'peak_kw': 10, 'longitude': 80}),
            ('loads', {'id': 'L', 'name': '负荷', 'node': 2, 'peak_kw': 10, 'curve_kw': [5, -1]}),
            ('switches', {'id': 'S', 'name': '开关', 'node': 2, 'line_id': 1, 'remote_control': True}),
            ('terminals', {'id': 'T', 'name': '终端', 'node': 2, 'controller_id': 'missing'}),
            ('communication', {'id': 'C', 'from_device': 'missing', 'to_device': 'also-missing'}),
        ]
        for group, asset in cases:
            with self.subTest(asset=asset):
                data = copy.deepcopy(self.inventory)
                data[group] = [asset]
                self.assertEqual(self.save(data).status_code, 422)
        data = copy.deepcopy(self.inventory)
        data['loads'] = [{'id': 'same', 'name': '负荷', 'node': 2, 'peak_kw': 10}]
        data['sources'] = [{'id': 'same', 'name': '电源', 'node': 2, 'kind': '柴油机', 'rated_kw': 10}]
        self.assertEqual(self.save(data).status_code, 422)

    def test_secondary_inventory_and_exchange_snapshot(self):
        self.inventory['controllers'] = [{'id': 'C1', 'name': '控制器', 'node': 1, 'covered_nodes': [1, 2]}]
        self.inventory['terminals'] = [{'id': 'T1', 'name': '终端', 'node': 2, 'controller_id': 'C1'}]
        self.inventory['communication'] = [{'id': 'route1', 'from_device': 'C1', 'to_device': 'T1'}]
        self.inventory['switches'] = [{'id': 'SW1', 'name': '开关', 'node': 2, 'line_id': 1, 'remote_control': True, 'terminal_id': 'T1'}]
        self.assertEqual(self.save().status_code, 200)
        task = self.c.post('/api/integration/requests', json={'project_id': self.project['id'], 'project_revision': 1, 'module': 'black_start'})
        self.assertEqual(task.status_code, 200, task.text)
        record = task.json()
        self.assertEqual(record['input']['engineering']['revision'], 1)
        self.inventory['communication'][0]['available'] = False
        self.save(revision=1)
        frozen = self.c.get('/api/integration/requests/' + record['id']).json()
        self.assertTrue(frozen['input']['engineering']['inventory']['communication'][0]['available'])

    def test_saved_custom_topology_is_used_in_exchange(self):
        network = {'name': '测试', 'source': '人工', 'base_voltage_kv': 10, 'nodes': [{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 1}],
                   'lines': [{'line': 1, 'from_node': 1, 'to_node': 2, 'r_ohm': 0, 'x_ohm': 0, 'status': 1}]}
        p = self.c.put('/api/projects/' + self.project['id'], json={'name': '测试', 'expected_revision': 1, 'state': {'network': network, 'model': 'case33'}})
        self.assertEqual(p.status_code, 200)
        # The local import of case33 is a fallback only; supplied custom topology must win.
        r = self.c.post('/api/integration/requests', json={'project_id': self.project['id'], 'project_revision': 2, 'module': 'black_start'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['input']['network'], network)

    def test_balance_and_strategy_keep_original_inventory_revision(self):
        self.inventory['loads'] = [{'id': 'L1', 'name': '已存负荷', 'node': 2, 'peak_kw': 100}]
        self.assertEqual(self.save().status_code, 200)
        body = {'csv': 'timestamp,load_kw,wind_kw,pv_kw\n2026-01-01 00:00,100,0,0\n2026-01-01 01:00,100,0,0\n',
                'project_id': self.project['id'], 'project_revision': 1, 'parameters': {'grid_channel_kw': 100}}
        r = self.c.post('/api/balance', json=body)
        self.assertEqual(r.status_code, 200, r.text)
        source = r.json()
        self.assertEqual(source['engineering']['revision'], 1)
        self.assertIn('未使用', source['engineering_usage'])
        self.inventory['loads'][0]['peak_kw'] = 200
        self.save(revision=1)
        adjusted = self.c.post('/api/strategy-evaluation', json={'source_run_id': source['id'], 'parameters': source['parameters']})
        self.assertEqual(adjusted.status_code, 200, adjusted.text)
        record = self.c.get('/api/runs/' + adjusted.json()['run_id']).json()
        self.assertEqual(record['engineering'], source['engineering'])
        # An explicit empty revision must stay empty after engineering inventory exists.
        empty = self.c.post('/api/balance', json={**body, 'engineering_revision': 0}).json()
        self.assertEqual(empty['engineering']['revision'], 0)
        self.assertEqual(empty['engineering']['inventory']['loads'], [])

    def test_plan_covers_each_menu_and_requirement_has_acceptance(self):
        r = self.c.get('/api/development-plan')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data['requirements']), 66)
        self.assertEqual(len({r['menu'] for r in data['requirements']}), 11)
        self.assertEqual(sum(data['counts'].values()), 66)
        for row in data['requirements']:
            self.assertTrue(row['inputs'] and row['outputs'] and row['acceptance'])
        self.assertEqual(self.c.get('/api/development-plan/document').status_code, 200)

    def test_historical_default_network_does_not_inherit_current_custom_topology(self):
        source = self.c.post('/api/balance', json={
            'csv': 'timestamp,load_kw,wind_kw,pv_kw\n2026-01-01 00:00,100,0,0\n2026-01-01 01:00,100,0,0\n',
            'model': 'case33', 'parameters': {'grid_channel_kw': 1000},
            'project_id': self.project['id'], 'project_revision': 1})
        self.assertEqual(source.status_code, 200, source.text)
        self.c.put('/api/projects/' + self.project['id'], json={'name': '新网络', 'expected_revision': 1,
                   'state': {'model': 'case33', 'network': {'name': '当前新网络'}}})
        default = {'source': 'historical default IEEE33'}
        with patch('backend.workspace.case33', return_value=default):
            r = self.c.post('/api/integration/requests', json={'project_id': self.project['id'], 'project_revision': 2,
                           'module': 'island_stability', 'source_run_id': source.json()['id']})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['input']['network'], default)


if __name__ == '__main__':
    unittest.main()
