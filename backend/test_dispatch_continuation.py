"""Committed-prefix state matches monolithic schedules at physical boundaries."""
import unittest
from backend.engineering import Inventory
from backend.network_data import Network
from backend.resource_dispatch import (DispatchInput, dispatch, continuation_state,
                                        DispatchInfeasible)


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.network = Network(nodes=[{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 10}],
                               lines=[{'line': 1, 'from_node': 1, 'to_node': 2, 'r_ohm': 0, 'x_ohm': 0}])
        self.load = {'id': 'L', 'name': '人工负荷', 'node': 2, 'peak_kw': 10,
                     'target_hours': 4, 'load_class': '基本保障'}
        self.source = {'id': 'D', 'name': '人工机组', 'node': 2, 'kind': '柴油机', 'rated_kw': 10,
                       'fuel_kwh': 100, 'grid_forming': True, 'black_start': True}
        self.base = {'project_id': 't', 'project_revision': 1, 'engineering_revision': 1,
                     'steps': 4, 'grid_available_kw': [0]}

    def solve(self, inventory=None, **changes):
        req = DispatchInput.model_validate(self.base | changes)
        inv = inventory or Inventory(sources=[self.source], loads=[self.load])
        return req, inv, dispatch(req, inv, self.network)

    def test_startup_remaining_zero_and_positive_survive_boundary(self):
        inv = Inventory(sources=[self.source | {'startup_minutes': 120}], loads=[self.load])
        req, inv, full = self.solve(inv)
        self.assertAlmostEqual(full['metrics']['served_energy_kwh'], 20)
        for cut in (1, 2):
            with self.subTest(cut=cut):
                state = continuation_state(req, inv, full, cut)
                self.assertEqual(state['initial_source_startup_remaining_steps']['D'], 2-cut)
                _, _, next_result = self.solve(inv, **(state | {'steps': 4-cut}))
                self.assertAlmostEqual(next_result['metrics']['served_energy_kwh'], 20)
                self.assertFalse(any(row['sources'][0]['startup_command'] for row in next_result['rows']))
                self.assertAlmostEqual(next_result['rows'][-1]['sources'][0]['fuel_remaining_kwh'], 80)

    def test_storage_energy_and_live_non_black_start_bus_survive_boundary(self):
        inv = Inventory(storage=[{'id': 'B', 'name': '储能', 'node': 2, 'power_kw': 10, 'energy_kwh': 100,
                                  'grid_forming': True, 'black_start': False, 'charge_efficiency': 1,
                                  'discharge_efficiency': 1}], loads=[self.load])
        req, inv, full = self.solve(inv, grid_available_kw=[20, 0, 0, 0])
        state = continuation_state(req, inv, full, 2)
        self.assertIn(2, state['initial_energized_nodes'])
        _, _, second = self.solve(inv, **(state | {'steps': 2, 'grid_available_kw': [0]}))
        self.assertAlmostEqual(second['rows'][0]['storage'][0]['energy_begin_kwh'], state['initial_storage_energy_kwh']['B'])
        self.assertAlmostEqual(second['rows'][-1]['storage'][0]['energy_end_kwh'], full['rows'][-1]['storage'][0]['energy_end_kwh'])
        self.assertAlmostEqual(second['metrics']['served_energy_kwh'], 20)

    def test_warm_previous_power_controls_first_step_ramp(self):
        inv = Inventory(sources=[self.source | {'ramp_kw_per_minute': .1}], loads=[self.load])
        _, _, cold = self.solve(inv)
        _, _, warm = self.solve(inv, initial_source_on={'D': 1}, initial_source_power_kw={'D': 10})
        self.assertAlmostEqual(cold['rows'][0]['served_kw'], 6)
        self.assertAlmostEqual(warm['rows'][0]['served_kw'], 10)
        self.assertFalse(warm['rows'][0]['sources'][0]['startup_command'])

    def test_used_runtime_budget_is_not_reset(self):
        inv = Inventory(sources=[self.source | {'fuel_kwh': None, 'available_hours': 1}], loads=[self.load])
        _, _, result = self.solve(inv, initial_source_used_hours={'D': 1})
        self.assertEqual(result['metrics']['served_energy_kwh'], 0)

    def test_future_delivery_cannot_power_an_earlier_step(self):
        inv = Inventory(sources=[self.source | {'fuel_kwh': 0}], loads=[self.load])
        _, _, result = self.solve(inv, source_energy_additions_kwh={'D': [0, 100, 0, 0]})
        self.assertEqual(result['rows'][0]['served_kw'], 0)
        self.assertFalse(result['rows'][0]['sources'][0]['on'])
        self.assertEqual(result['rows'][1]['served_kw'], 10)
        self.assertAlmostEqual(result['rows'][-1]['sources'][0]['fuel_remaining_kwh'], 70)

    def test_remaining_fuel_and_fixed_reserve_survive_export(self):
        req, inv, first = self.solve(initial_source_fuel_kwh={'D': 50}, source_forming_reserve_kwh={'D': 7})
        state = continuation_state(req, inv, first, 1)
        self.assertAlmostEqual(state['initial_source_fuel_kwh']['D'], 40)
        self.assertEqual(state['source_forming_reserve_kwh']['D'], 7)
        self.assertEqual(state['source_energy_additions_kwh'], {})
        _, _, second = self.solve(inv, **(state | {'steps': 3}))
        self.assertAlmostEqual(second['rows'][-1]['sources'][0]['fuel_remaining_kwh'], 10)

    def test_absolute_arrival_and_target_window_use_elapsed_event_time(self):
        inv = Inventory(sources=[self.source | {'arrival_minutes': 120}], loads=[self.load | {'target_hours': 2}])
        _, _, result = self.solve(inv, elapsed_hours=2, steps=1, prior_target_history_complete=True)
        self.assertEqual(result['rows'][0]['served_kw'], 10)
        self.assertEqual(result['rows'][0]['loads'][0]['target_kw'], 0)

    def test_outage_clock_and_previous_maximum_are_not_forgotten(self):
        inv = Inventory(loads=[self.load | {'interruption_allowed': True, 'maximum_interruption_hours': 1}])
        req, inv, first = self.solve(inv, grid_available_kw=[0, 10, 10, 10])
        state = continuation_state(req, inv, first, 1)
        self.assertEqual(state['initial_target_interruption_hours']['L'], 1)
        with self.assertRaises(DispatchInfeasible):
            self.solve(inv, **(state | {'steps': 3, 'enforce_load_targets': True, 'grid_available_kw': [0]}))
        _, _, next_result = self.solve(inv, **(state | {'steps': 3, 'enforce_load_targets': True, 'grid_available_kw': [10]}))
        self.assertEqual(next_result['load_metrics'][0]['maximum_target_interruption_hours'], 1)
        self.assertEqual(next_result['load_metrics'][0]['total_target_interruption_hours'], 1)

    def test_repaired_past_failure_still_fails_whole_event(self):
        inv = Inventory(loads=[self.load | {'interruption_allowed': True, 'maximum_interruption_hours': 1}])
        req, inv, first = self.solve(inv, grid_available_kw=[0, 0, 10, 10])
        state = continuation_state(req, inv, first, 3)
        self.assertEqual(state['initial_target_interruption_hours']['L'], 0)
        self.assertEqual(state['initial_max_target_interruption_hours']['L'], 2)
        _, _, result = self.solve(inv, **(state | {'steps': 1, 'grid_available_kw': [10]}))
        self.assertEqual(result['load_metrics'][0]['target_status'], 'failed')

    def test_incomplete_history_stays_unchecked_and_cannot_support_hard_goal(self):
        inv = Inventory(loads=[self.load])
        _, _, result = self.solve(inv, elapsed_hours=1, steps=3, grid_available_kw=[10])
        self.assertEqual(result['load_metrics'][0]['target_status'], 'not_checked')
        with self.assertRaisesRegex(ValueError, '完整中断前史'):
            self.solve(inv, elapsed_hours=1, steps=3, grid_available_kw=[10], enforce_load_targets=True)

    def test_invalid_states_rejected(self):
        for changes in [{'initial_source_power_kw': {'D': 5}}, {'initial_source_on': {'missing': 1}},
                        {'initial_source_startup_remaining_steps': {'D': 1}},
                        {'source_energy_additions_kwh': {'D': [1, -1, 0, 0]}},
                        {'source_forming_reserve_kwh': {'D': 0}},
                        {'initial_target_interruption_hours': {'L': 2}, 'elapsed_hours': 1}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.solve(**changes)
        with self.assertRaises(ValueError):
            continuation_state(*self.solve(), committed_steps=0)

    def test_source_energy_matrix_growth_is_linear_in_steps(self):
        from backend.resource_dispatch import build_dispatch_model
        inv = Inventory(sources=[self.source], loads=[self.load])
        matrices = [build_dispatch_model(DispatchInput.model_validate(self.base | {'steps': count}),
                                        inv, self.network).m for count in (32, 64)]
        self.assertLess(len(matrices[1].data)/len(matrices[0].data), 2.2)


if __name__ == '__main__':
    unittest.main()
