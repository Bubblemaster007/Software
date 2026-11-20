"""Hand-checkable command timing, physical replay and secondary-control counterexamples."""
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from backend.engineering import Inventory
from backend.network_data import Network
from backend.resource_dispatch import DispatchInput, DispatchInfeasible, dispatch
from backend.restoration import (RestorationInput, State, communication_route, plan_restoration,
                                 validate_restoration, sync_check, SyncEvidence)
from backend.study_control import StudyCancelled


class RestorationTests(unittest.TestCase):
    def setUp(self):
        self.network = Network(base_voltage_kv=10, nodes=[{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 20}],
                               lines=[{'line': 7, 'from_node': 1, 'to_node': 2, 'r_ohm': 0, 'x_ohm': 0}])
        self.source = {'id': 'D', 'name': '启动柴油机', 'node': 1, 'kind': '柴油机', 'rated_kw': 100,
                       'fuel_kwh': 1000, 'grid_forming': True, 'black_start': True, 'startup_minutes': 5}
        self.load = {'id': 'L', 'name': '医院', 'node': 2, 'peak_kw': 20, 'target_hours': 1, 'load_class': '基本保障'}
        self.switch = {'id': 'S', 'name': '线路开关', 'node': 1, 'line_id': 7, 'operation_minutes': 1}
        self.inventory = Inventory(sources=[self.source], loads=[self.load], switches=[self.switch])
        self.base = {'project_id': 'test', 'project_revision': 1, 'engineering_revision': 1, 'steps': 12,
                     'step_hours': 5/60, 'grid_available_kw': [0], 'time_limit_seconds': 10}
        self.req = RestorationInput(base=self.base, manual_resource_ids=['D'], manual_switch_ids=['S'], manual_load_ids=['L'], maximum_evaluations=80)

    def test_operation_timing_and_full_replay(self):
        result = plan_restoration(self.req, self.inventory, self.network)
        self.assertEqual([a['kind'] for a in result['actions']], ['start', 'close', 'pickup'])
        self.assertEqual([a['end_step'] for a in result['actions']], [2, 3, 4])
        self.assertEqual(result['load_recovery'][0]['first_sustained_full_supply_minutes'], 20)
        replay = dispatch(DispatchInput.model_validate(result['replay_parameters']), Inventory.model_validate(result['replay_inventory']), self.network)
        self.assertAlmostEqual(replay['metrics']['served_energy_kwh'], 20*8/12, places=4)
        self.assertEqual(result['operational_clearance'], 'not_cleared')
        self.assertTrue(any(c['status'] == 'not_checked' for c in result['checks']))
        self.assertEqual(len(result['preallocation'][0]['path_lines']), 1)

    def test_no_self_start_and_no_fuel_cannot_form_dead_island(self):
        for change in [{'black_start': False}, {'fuel_kwh': 0}]:
            inventory = Inventory(sources=[self.source | change], loads=[self.load], switches=[self.switch])
            r = plan_restoration(self.req, inventory, self.network)
            self.assertEqual(r['goal_status'], 'unrestored')
            self.assertEqual(r['actions'], [])

    def test_zero_demand_controlled_load_still_requires_a_pickup(self):
        inv = self.inventory.model_copy(deep=True)
        inv.loads = Inventory(loads=[self.load, self.load | {'id': 'Z', 'peak_kw': 0, 'load_class': '一般负荷'}]).loads
        req = self.req.model_copy(update={'manual_load_ids': ['L', 'Z'], 'maximum_evaluations': 200})
        result = plan_restoration(req, inv, self.network)
        self.assertEqual(result['goal_status'], 'restored_to_horizon')
        self.assertIn('Z', [a['target_id'] for a in result['actions'] if a['kind'] == 'pickup'])

    def test_uncontrolled_load_cannot_be_shed_to_fake_success(self):
        inv = Inventory(sources=[self.source | {'rated_kw': 10}], loads=[self.load], switches=[self.switch])
        req = self.req.model_copy(update={'manual_load_ids': [], 'initial_closed_lines': [7]})
        r = plan_restoration(req, inv, self.network)
        self.assertEqual(r['goal_status'], 'unrestored')
        self.assertEqual(r['actions'], [])
        self.assertTrue(any('不可行' in x['reason'] for x in r['rejected_candidates']))

    def test_closed_nonoperable_line_and_unavailable_switch(self):
        inv = self.inventory.model_copy(deep=True)
        inv.switches[0].available = False
        r = plan_restoration(self.req, inv, self.network)
        self.assertEqual(r['goal_status'], 'unrestored')
        self.assertFalse(any(a['kind'] == 'close' for a in r['actions']))
        req = self.req.model_copy(update={'initial_closed_lines': [7]})
        with self.assertRaises(ValueError):
            validate_restoration(req, inv, self.network)

    def test_remote_requires_route_station_power_coverage_and_latency(self):
        inventory = Inventory(controllers=[{'id': 'C', 'name': '控制器', 'node': 1, 'covered_nodes': [1, 2]}],
                              terminals=[{'id': 'T', 'name': '终端', 'node': 1, 'controller_id': 'C'}],
                              communication=[{'id': 'fiber', 'from_device': 'C', 'to_device': 'T', 'latency_ms': 10}])
        req = self.req.model_copy(update={'backup_powered_devices': ['C', 'T']})
        state = State()
        self.assertEqual(communication_route(req, inventory, state, 'T', 1, 0)['route'], ['fiber'])
        self.assertIsNone(communication_route(req.model_copy(update={'backup_powered_devices': []}), inventory, state, 'T', 1, 0))
        self.assertIsNone(communication_route(req.model_copy(update={'maximum_communication_latency_ms': 5}), inventory, state, 'T', 1, 0))
        inventory.communication[0].available = False
        self.assertIsNone(communication_route(req, inventory, state, 'T', 1, 0))
        inventory.communication[0].available = True
        inventory.controllers[0].covered_nodes = []
        self.assertIsNone(communication_route(req, inventory, state, 'T', 2, 0))

    def test_failed_remote_does_not_fall_back_to_unauthorized_manual(self):
        inventory = Inventory(sources=[self.source], loads=[self.load], switches=[self.switch | {'remote_control': True, 'terminal_id': 'T'}],
                              controllers=[{'id': 'C', 'name': '控制器', 'node': 1, 'covered_nodes': [1, 2]}],
                              terminals=[{'id': 'T', 'name': '终端', 'node': 1, 'controller_id': 'C'}],
                              communication=[{'id': 'link', 'from_device': 'C', 'to_device': 'T', 'available': False}])
        req = self.req.model_copy(update={'manual_switch_ids': [], 'backup_powered_devices': ['C', 'T']})
        result = plan_restoration(req, inventory, self.network)
        self.assertEqual(result['goal_status'], 'unrestored')
        self.assertFalse(any(a['kind'] == 'close' for a in result['actions']))
        req = req.model_copy(update={'equipment_ready_step': {'link': 5}})
        result = plan_restoration(req, inventory, self.network)
        close = next(a for a in result['actions'] if a['kind'] == 'close')
        self.assertGreaterEqual(close['start_step'], 5)

    def test_sync_numeric_window_and_limits(self):
        e = SyncEvidence(target='line:7', valid_from_step=2, valid_to_step=4, voltage_difference_pu=.01,
                         frequency_difference_hz=.05, angle_difference_degrees=5, provenance='外部人工同步工况')
        req = self.req.model_copy(update={'synchronization': [e]})
        self.assertEqual(sync_check(req, 'line:7', 3)['status'], 'external_passed')
        self.assertIsNone(sync_check(req, 'line:7', 5))
        e.angle_difference_degrees = 15
        self.assertIsNone(sync_check(req, 'line:7', 3))

    def test_hot_merge_requires_evidence_and_replays_combined_capacity(self):
        inv = Inventory(sources=[self.source | {'rated_kw': 20, 'startup_minutes': 0},
                                 self.source | {'id': 'B', 'node': 2, 'rated_kw': 20, 'startup_minutes': 0}],
                        loads=[self.load | {'node': 1, 'peak_kw': 30}], switches=[self.switch])
        req = self.req.model_copy(update={'manual_resource_ids': ['D', 'B'], 'manual_crews': 2, 'maximum_evaluations': 200})
        result = plan_restoration(req, inv, self.network)
        self.assertEqual(result['goal_status'], 'unrestored')
        self.assertTrue(any('预同步' in r['reason'] for r in result['rejected_candidates']))
        e = SyncEvidence(target='line:7', valid_from_step=0, valid_to_step=11, voltage_difference_pu=.01,
                         frequency_difference_hz=.01, angle_difference_degrees=2, provenance='人工研究同步输入，非实测')
        result = plan_restoration(req.model_copy(update={'synchronization': [e]}), inv, self.network)
        self.assertEqual(result['goal_status'], 'restored_to_horizon')
        close = next(a for a in result['actions'] if a['kind'] == 'close')
        self.assertEqual(close['synchronization']['status'], 'external_passed')
        self.assertEqual(result['operational_clearance'], 'not_cleared')

    def test_inrush_envelope_rejects_and_missing_not_passed(self):
        inv = self.inventory.model_copy(deep=True)
        inv.transformers = Inventory(transformers=[{'id': 'TR', 'name': '变压器', 'node': 1, 'to_node': 2, 'rated_kva': 100,
                                                   'inrush_multiple': 6}]).transformers
        req = self.req.model_copy(update={'energizing_current_limits_a': {'D': 1}, 'transient_parameter_provenance': '人工限额'})
        r = plan_restoration(req, inv, self.network)
        self.assertEqual(r['goal_status'], 'unrestored')
        self.assertTrue(any('励磁' in e['reason'] for e in r['rejected_candidates']))
        r = plan_restoration(self.req, inv, self.network)
        close = next(a for a in r['actions'] if a['kind'] == 'close')
        self.assertEqual(close['inrush_screen']['status'], 'not_checked')
        r = plan_restoration(self.req.model_copy(update={'require_inrush_parameters': True}), inv, self.network)
        self.assertEqual(r['goal_status'], 'unrestored')

    def test_parallel_islands_and_manual_crew_resources(self):
        net = Network(nodes=[{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 20}, {'node': 3, 'pd_kw': 10}],
                      lines=[{'line': 7, 'from_node': 1, 'to_node': 2, 'r_ohm': 0, 'x_ohm': 0},
                             {'line': 8, 'from_node': 1, 'to_node': 3, 'r_ohm': 0, 'x_ohm': 0}])
        inv = Inventory(sources=[self.source, self.source | {'id': 'B', 'node': 3, 'startup_minutes': 0}],
                        loads=[self.load, self.load | {'id': 'R', 'node': 3, 'peak_kw': 10, 'load_class': '居民生活'}], switches=[self.switch])
        req = self.req.model_copy(update={'manual_resource_ids': ['D', 'B'], 'manual_crews': 2, 'maximum_evaluations': 200})
        parallel = plan_restoration(req, inv, net)
        serial = plan_restoration(req.model_copy(update={'mode': 'serial'}), inv, net)
        self.assertEqual(len(parallel['partitions']), 2)
        self.assertGreater(parallel['dispatch']['metrics']['served_energy_kwh'], serial['dispatch']['metrics']['served_energy_kwh'])
        starts = [a for a in parallel['actions'] if a['kind'] == 'start']
        self.assertTrue(all(a['start_step'] == 0 for a in starts))

    def test_search_budget_cancel_and_invalid_parameters(self):
        req = self.req.model_copy(update={'maximum_evaluations': 1})
        r = plan_restoration(req, self.inventory, self.network)
        self.assertEqual(r['evaluations'], 1)
        self.assertEqual(r['status'], 'incomplete_search')
        with self.assertRaises(StudyCancelled):
            plan_restoration(self.req, self.inventory, self.network, cancelled=lambda: True)
        bad = self.req.model_dump()
        bad['base']['grid_available_kw'] = [1]
        with self.assertRaises(ValidationError):
            RestorationInput.model_validate(bad)

    def test_one_minute_integral_and_forced_full_pickup_capacity(self):
        base = self.base | {'step_hours': 1/60, 'steps': 6, 'grid_available_kw': [100]}
        r = dispatch(DispatchInput.model_validate(base), self.inventory, self.network)
        self.assertAlmostEqual(r['metrics']['load_energy_kwh'], 2)
        base['required_energized_nodes'] = {2: [1]}
        base['minimum_load_when_energized'] = {'L': 1}
        base['grid_available_kw'] = [10]
        base['device_availability'] = {'D': [0]}
        with self.assertRaises(DispatchInfeasible):
            dispatch(DispatchInput.model_validate(base), self.inventory, self.network)


if __name__ == '__main__':
    unittest.main()
