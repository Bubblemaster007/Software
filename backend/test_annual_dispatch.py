"""Rolling-prefix accounting, calendar coverage and physical state regression."""
import unittest
from backend.annual_dispatch import AnnualDispatchInput, run_annual, profiles
from backend.engineering import Inventory
from backend.network_data import Network


class AnnualTests(unittest.TestCase):
    def setUp(self):
        self.network = Network(nodes=[{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 10}],
                               lines=[{'line': 1, 'from_node': 1, 'to_node': 2, 'r_ohm': 0, 'x_ohm': 0}])
        self.load = {'id': 'L', 'name': '人工负荷', 'node': 2, 'peak_kw': 10,
                     'target_hours': 4, 'load_class': '基本保障'}
        self.base = {'project_id': 't', 'project_revision': 1, 'engineering_revision': 1,
                     'steps': 4, 'grid_available_kw': [10]}

    def request(self, base=None, **changes):
        return AnnualDispatchInput.model_validate({'base': self.base | (base or {}),
            'coverage_mode': 'series', 'total_steps': 6, 'commit_steps': 2, **changes})

    def test_committed_energy_has_no_forecast_overlap(self):
        result = run_annual(self.request(), Inventory(loads=[self.load]), self.network)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['metrics']['served_energy_kwh'], 60)
        self.assertEqual(result['metrics']['study_dispatch_cost_yuan'], 30)
        self.assertEqual([w['forecast_steps'] for w in result['windows']], [4, 4, 2])
        rows = [r for w in result['window_details'] for r in w['committed_rows']]
        self.assertEqual([r['global_step'] for r in rows], list(range(6)))
        self.assertFalse(result['coverage']['calendar_year_complete'])

    def test_storage_is_not_replenished_at_window_boundaries(self):
        inventory = Inventory(loads=[self.load], storage=[{'id': 'B', 'name': '人工储能',
            'node': 2, 'power_kw': 10, 'energy_kwh': 100, 'grid_forming': True,
            'black_start': True, 'charge_efficiency': 1, 'discharge_efficiency': 1}])
        result = run_annual(self.request(base={'grid_available_kw': [0]}), inventory, self.network)
        self.assertAlmostEqual(result['metrics']['served_energy_kwh'], 60)
        self.assertAlmostEqual(result['terminal_state']['initial_storage_energy_kwh']['B'], 20)

    def test_pending_start_and_fuel_follow_committed_prefix(self):
        inventory = Inventory(loads=[self.load], sources=[{'id': 'D', 'name': '人工机组',
            'node': 2, 'kind': '柴油机', 'rated_kw': 10, 'fuel_kwh': 100,
            'startup_minutes': 120, 'grid_forming': True, 'black_start': True}])
        result = run_annual(self.request(base={'grid_available_kw': [0]}, commit_steps=1), inventory, self.network)
        self.assertAlmostEqual(result['metrics']['served_energy_kwh'], 40)
        self.assertAlmostEqual(result['terminal_state']['initial_source_fuel_kwh']['D'], 60)
        rows = [w['committed_rows'][0] for w in result['window_details']]
        self.assertEqual(sum(r['sources'][0]['startup_command'] for r in rows), 1)

    def test_year_event_target_can_start_after_short_forecast(self):
        req = self.request(base={'steps': 2, 'enforce_load_targets': True,
            'load_target_start_hours': {'L': 2}}, total_steps=4, commit_steps=1,
            grid_available_kw=[0, 0, 10, 10])
        result = run_annual(req, Inventory(loads=[self.load | {'target_hours': 2}]), self.network)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['metrics']['total_unsupplied_energy_kwh'], 20)
        self.assertEqual(result['load_metrics'][0]['target_status'], 'passed')
        self.assertEqual(result['load_metrics'][0]['total_target_interruption_hours'], 0)

    def test_zero_demand_window_and_tail_are_valid(self):
        req = self.request(base={'steps': 2}, total_steps=3, commit_steps=1,
                           load_curve_kw={'L': [0, 0, 10]})
        result = run_annual(req, Inventory(loads=[self.load]), self.network)
        self.assertEqual(result['coverage']['completed_steps'], 3)
        self.assertEqual(result['metrics']['served_energy_kwh'], 10)
        self.assertEqual(result['load_metrics'][0]['target_status'], 'not_checked')

    def test_short_profile_is_rejected_instead_of_repeated(self):
        with self.assertRaises(ValueError):
            profiles(self.request(), Inventory(loads=[self.load | {'curve_kw': [5, 10]}]))

    def test_calendar_year_and_leap_year_are_checked(self):
        AnnualDispatchInput.model_validate({'base': self.base, 'total_steps': 8760, 'commit_steps': 4})
        leap = self.base | {'start': '2028-01-01T00:00:00', 'step_hours': .25}
        AnnualDispatchInput.model_validate({'base': leap, 'total_steps': 35136, 'commit_steps': 4})
        with self.assertRaises(ValueError):
            AnnualDispatchInput.model_validate({'base': leap, 'total_steps': 35040})
        with self.assertRaises(ValueError):
            AnnualDispatchInput.model_validate({'base': self.base | {'start': '2026-02-01T00:00:00'}})


if __name__ == '__main__':
    unittest.main()
