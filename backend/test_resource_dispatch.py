"""Physical counterexamples, temporal invariants and isolated archive tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy
import unittest
from fastapi.testclient import TestClient
from backend.app import app
from backend.engineering import Inventory
from backend.network_data import Network
from backend.resource_dispatch import DispatchInput, dispatch


class ResourceDispatchTests(unittest.TestCase):
    def setUp(self):
        self.network = Network(nodes=[{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 100}],
                               lines=[{'line': 7, 'from_node': 1, 'to_node': 2, 'r_ohm': 0, 'x_ohm': 0}])
        self.req = {'project_id': 'test', 'project_revision': 1, 'engineering_revision': 1, 'steps': 2,
                    'grid_available_kw': [100], 'time_limit_seconds': 20}
        self.load = {'id': 'L', 'name': '医院', 'node': 2, 'peak_kw': 100, 'target_hours': 2, 'load_class': '基本保障'}

    def run_study(self, inventory, **changes):
        return dispatch(DispatchInput(**(self.req | changes)), Inventory(**inventory), self.network)

    def assert_balanced(self, result):
        self.assertLess(result['metrics']['maximum_balance_residual_kw'], 1e-4)
        self.assertLess(result['maximum_constraint_violation'], 1e-4)
        for row in result['rows']:
            self.assertAlmostEqual(row['load_kw'], row['served_kw'] + row['controlled_curtailment_kw'] + row['shortage_kw'], places=4)
            for battery in row['storage']:
                self.assertTrue(battery['charge_kw'] < 1e-5 or battery['discharge_kw'] < 1e-5)

    def test_class_priority_and_branch_rating(self):
        general = {**self.load, 'id': 'G', 'name': '一般', 'load_class': '一般负荷'}
        result = self.run_study({'loads': [self.load, general]})
        self.assertAlmostEqual(result['load_metrics'][0]['served_kwh'], 200, places=4)
        self.assertAlmostEqual(result['load_metrics'][1]['served_kwh'], 0, places=4)
        self.network.lines[0].capacity_kva = 40
        limited = self.run_study({'loads': [self.load]})
        self.assertAlmostEqual(limited['metrics']['served_energy_kwh'], 80, places=4)
        self.assert_balanced(limited)

    def test_fifteen_minute_integral_and_target_horizon(self):
        load = {**self.load, 'peak_kw': 20, 'target_hours': 2}
        hourly = self.run_study({'loads': [load]}, steps=1)
        quarter = self.run_study({'loads': [load]}, steps=4, step_hours=.25)
        self.assertAlmostEqual(hourly['metrics']['served_energy_kwh'], quarter['metrics']['served_energy_kwh'], places=4)
        self.assertAlmostEqual(quarter['metrics']['served_energy_kwh'], 20, places=4)
        self.assertEqual(quarter['load_metrics'][0]['target_status'], 'not_checked')
        self.assertAlmostEqual(quarter['load_metrics'][0]['continuous_target_supply_hours'], 1)

    def test_forming_fuel_reserve_is_independent_of_time_step(self):
        source = {'id': 'D', 'name': '构网机组', 'node': 2, 'kind': '柴油机', 'rated_kw': 100,
                  'fuel_kwh': 50, 'grid_forming': True, 'black_start': True}
        hourly = self.run_study({'loads': [self.load], 'sources': [source]}, steps=1, grid_available_kw=[0])
        quarter = self.run_study({'loads': [self.load], 'sources': [source]}, steps=4, step_hours=.25, grid_available_kw=[0])
        self.assertAlmostEqual(hourly['metrics']['served_energy_kwh'], 49, places=4)
        self.assertAlmostEqual(quarter['metrics']['served_energy_kwh'], 49, places=4)

    def test_following_renewable_cannot_energize_dead_island(self):
        inventory = {'loads': [{**self.load, 'peak_kw': 20}], 'sources': [
            {'id': 'PV', 'name': '跟网光伏', 'node': 2, 'kind': '光伏', 'rated_kw': 50, 'curve_kw': [50]}]}
        dead = self.run_study(inventory, line_status={7: [0]}, grid_available_kw=[100])
        self.assertAlmostEqual(dead['metrics']['served_energy_kwh'], 0, places=4)
        self.assertFalse(dead['rows'][0]['nodes'][1]['energized'])
        inventory['storage'] = [{'id': 'B', 'name': '构网储能', 'node': 2, 'power_kw': 10, 'energy_kwh': 100,
                                 'grid_forming': True, 'black_start': True}]
        live = self.run_study(inventory, line_status={7: [0]})
        self.assertAlmostEqual(live['metrics']['served_energy_kwh'], 40, places=4)
        self.assertTrue(live['rows'][0]['nodes'][1]['energized'])
        self.assertEqual(live['checks'][2]['status'], 'not_checked')
        self.assert_balanced(live)

    def test_empty_or_unstarted_grid_former_does_not_create_energy(self):
        inventory = {'loads': [self.load], 'sources': [{'id': 'PV', 'name': '光伏', 'node': 2, 'kind': '光伏', 'rated_kw': 100, 'curve_kw': [100]}],
                     'storage': [{'id': 'B', 'name': '储能', 'node': 2, 'power_kw': 100, 'energy_kwh': 100,
                                  'initial_soc': .1, 'minimum_soc': .1, 'grid_forming': True, 'black_start': True}]}
        result = self.run_study(inventory, grid_available_kw=[0])
        self.assertAlmostEqual(result['metrics']['served_energy_kwh'], 0, places=4)
        inventory['storage'][0].update(initial_soc=.8, black_start=False)
        result = self.run_study(inventory, grid_available_kw=[0])
        self.assertAlmostEqual(result['metrics']['served_energy_kwh'], 0, places=4)

    def test_startup_arrival_fuel_and_recovery(self):
        load = {**self.load, 'peak_kw': 20, 'target_hours': 1}
        source = {'id': 'D', 'name': '移动柴油', 'node': 2, 'kind': '移动发电车', 'rated_kw': 20,
                  'arrival_minutes': 15, 'startup_minutes': 15, 'grid_forming': True, 'black_start': True, 'fuel_kwh': 100}
        result = self.run_study({'loads': [load], 'sources': [source]}, steps=4, step_hours=.25, grid_available_kw=[0])
        self.assertAlmostEqual(result['rows'][0]['served_kw'], 0, places=4)
        self.assertAlmostEqual(result['rows'][1]['served_kw'], 0, places=4)
        self.assertAlmostEqual(result['metrics']['served_energy_kwh'], 10, places=4)
        self.assert_balanced(result)
        source.update(arrival_minutes=0, startup_minutes=60)
        result = self.run_study({'loads': [load], 'sources': [source]}, steps=4, step_hours=1, grid_available_kw=[0], device_availability={'D': [1, 1, 0, 1]})
        self.assertAlmostEqual(result['rows'][0]['served_kw'], 0, places=4)
        self.assertAlmostEqual(result['rows'][1]['served_kw'], 20, places=4)
        self.assertAlmostEqual(result['rows'][2]['served_kw'], 0, places=4)
        self.assertAlmostEqual(result['rows'][3]['served_kw'], 0, places=4)

    def test_storage_and_fuel_conservation(self):
        battery = {'id': 'B', 'name': '储能', 'node': 2, 'power_kw': 30, 'energy_kwh': 100, 'initial_soc': .8,
                   'minimum_soc': .1, 'discharge_efficiency': .8, 'grid_forming': True, 'black_start': True}
        result = self.run_study({'loads': [{**self.load, 'peak_kw': 30}], 'storage': [battery]}, steps=4, grid_available_kw=[0])
        self.assertLessEqual(result['metrics']['served_energy_kwh'], (.8 - .1 - .02) * 100 * .8 + 1e-4)
        for row in result['rows']:
            b = row['storage'][0]
            self.assertAlmostEqual(b['energy_end_kwh'], b['energy_begin_kwh'] + b['charge_kw'] * .95 - b['discharge_kw'] / .8, places=4)
        self.assert_balanced(result)
        source = {'id': 'D', 'name': '柴油', 'node': 2, 'kind': '柴油机', 'rated_kw': 100, 'fuel_kwh': 30, 'grid_forming': True, 'black_start': True}
        fuel = self.run_study({'loads': [self.load], 'sources': [source]}, grid_available_kw=[0])
        self.assertLessEqual(fuel['metrics']['served_energy_kwh'], 30 + 1e-4)
        self.assertGreaterEqual(fuel['rows'][-1]['sources'][0]['fuel_remaining_kwh'], 0)

    def test_reactive_rating_and_explicit_demand_response(self):
        self.network.lines[0].capacity_kva = 10
        load = {**self.load, 'peak_kw': 10, 'reactive_kvar': 10}
        r = self.run_study({'loads': [load]}, grid_reactive_limit_kvar=100)
        self.assertAlmostEqual(r['metrics']['served_energy_kwh'], 2 * 10 / 2 ** .5, places=4)
        self.assert_balanced(r)
        load = {**self.load, 'maximum_curtailment_ratio': .2, 'minimum_supply_ratio': .8}
        self.network.lines[0].capacity_kva = 100
        controlled = self.run_study({'loads': [load]}, grid_available_kw=[80], allow_demand_response=True)
        self.assertAlmostEqual(controlled['metrics']['controlled_curtailment_energy_kwh'], 40, places=4)
        self.assertAlmostEqual(controlled['metrics']['shortage_energy_kwh'], 0, places=4)
        self.assert_balanced(controlled)

    def test_missing_renewable_curve_and_invalid_schedule_rejected(self):
        with self.assertRaisesRegex(ValueError, '缺少风光'):
            self.run_study({'loads': [self.load], 'sources': [{'id': 'PV', 'name': '无曲线', 'node': 2, 'kind': '光伏', 'rated_kw': 10}]})
        with self.assertRaisesRegex(ValueError, '不存在'):
            self.run_study({'loads': [self.load]}, device_availability={'missing': [0]})
        with self.assertRaises(ValueError):
            DispatchInput(**(self.req | {'grid_available_kw': [1, 2, 3]}))
        with self.assertRaisesRegex(ValueError, '无限燃料'):
            self.run_study({'loads': [self.load], 'sources': [{'id': 'D', 'name': '无燃料数据', 'node': 2, 'kind': '柴油机', 'rated_kw': 10}]})

    def test_candidates_and_controlled_curtailment_are_opt_in(self):
        candidate = {'id': 'D', 'name': '待建机组', 'node': 2, 'kind': '柴油机', 'rated_kw': 100, 'existing': False,
                     'fuel_kwh': 200, 'grid_forming': True, 'black_start': True}
        baseline = self.run_study({'loads': [self.load], 'sources': [candidate]}, grid_available_kw=[0])
        self.assertAlmostEqual(baseline['metrics']['served_energy_kwh'], 0, places=4)
        proposed = self.run_study({'loads': [self.load], 'sources': [candidate]}, grid_available_kw=[0], include_candidates=True)
        self.assertGreater(proposed['metrics']['served_energy_kwh'], 0)
        load = {**self.load, 'maximum_curtailment_ratio': .2, 'minimum_supply_ratio': .8}
        disabled = self.run_study({'loads': [load]}, grid_available_kw=[80])
        self.assertAlmostEqual(disabled['metrics']['controlled_curtailment_energy_kwh'], 0)
        self.assertAlmostEqual(disabled['metrics']['shortage_energy_kwh'], 40, places=4)

    def test_open_switch_and_failed_switch_cannot_conduct(self):
        switch = {'id': 'SW', 'name': '常开开关', 'node': 1, 'line_id': 7, 'normally_closed': False}
        opened = self.run_study({'loads': [self.load], 'switches': [switch]})
        self.assertAlmostEqual(opened['metrics']['served_energy_kwh'], 0)
        closed = self.run_study({'loads': [self.load], 'switches': [switch]}, line_status={7: [1]})
        self.assertAlmostEqual(closed['metrics']['served_energy_kwh'], 200, places=4)
        failed = self.run_study({'loads': [self.load], 'switches': [switch]}, line_status={7: [1]}, device_availability={'SW': [0]})
        self.assertAlmostEqual(failed['metrics']['served_energy_kwh'], 0)

    def test_archive_freezes_inventory_and_exports_actual_steps(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'data').mkdir()
            with patch('backend.workspace.ROOT', root), patch('backend.engineering.ROOT', root), patch('backend.resource_dispatch.ROOT', root):
                c = TestClient(app)
                p = c.post('/api/projects', json={'name': '逐设备隔离', 'state': {'network': self.network.model_dump()}}).json()
                inventory = Inventory(loads=[self.load]).model_dump()
                url = '/api/engineering/projects/' + p['id']
                self.assertEqual(c.put(url, json={'project_revision': 1, 'expected_revision': 0, 'inventory': inventory}).status_code, 200)
                r = c.post('/api/device-dispatch', json=self.req | {'project_id': p['id']})
                self.assertEqual(r.status_code, 200, r.text)
                record = r.json()
                inventory['loads'][0]['peak_kw'] = 200
                c.put(url, json={'project_revision': 1, 'expected_revision': 1, 'inventory': inventory})
                frozen = c.get('/api/device-dispatch/' + record['id']).json()
                self.assertEqual(frozen['input']['engineering']['inventory']['loads'][0]['peak_kw'], 100)
                self.assertEqual(len(c.get('/api/device-dispatch/' + record['id'] + '/csv').text.strip().splitlines()), 3)
                self.assertEqual(len(c.get('/api/device-dispatch?project_id=' + p['id']).json()), 1)
                boundary = c.get('/api/device-dispatch/'+record['id']+'/continuation?committed_steps=1')
                self.assertEqual(boundary.status_code, 200, boundary.text)
                self.assertEqual(boundary.json()['engineering_revision'], 1)
                self.assertEqual(boundary.json()['parameters']['elapsed_hours'], 1)
                self.assertTrue(boundary.json()['parameters']['prior_target_history_complete'])
                self.assertEqual(boundary.json()['parameters']['initial_max_target_interruption_hours']['L'], 0)
                self.assertEqual(c.get('/api/device-dispatch/'+record['id']+'/continuation?committed_steps=0').status_code, 422)


if __name__ == '__main__':
    unittest.main()
