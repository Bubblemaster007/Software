"""Hard consecutive interruption limits and joint chance witness counterexamples."""
import unittest
from backend.engineering import Inventory
from backend.network_data import Network
from backend.resource_dispatch import DispatchInput, dispatch, DispatchInfeasible
from backend.investment_planning import InvestmentInput, investment_plan


class InterruptionTargetTests(unittest.TestCase):
    def setUp(self):
        self.net = Network(nodes=[{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 10}],
                           lines=[{'line': 1, 'from_node': 1, 'to_node': 2, 'r_ohm': 0, 'x_ohm': 0}])
        self.load = {'id': 'L', 'name': '人工负荷', 'node': 2, 'peak_kw': 10, 'target_hours': 3,
                     'load_class': '基本保障', 'interruption_allowed': True, 'maximum_interruption_hours': 1}
        self.base = {'project_id': 't', 'project_revision': 1, 'engineering_revision': 1, 'steps': 3,
                     'enforce_load_targets': True, 'grid_available_kw': [0, 10, 0]}

    def run_dispatch(self, load=None, **params):
        return dispatch(DispatchInput.model_validate(self.base | params), Inventory(loads=[self.load | (load or {})]), self.net)

    def test_separated_gaps_pass_continuous_limit_not_total_limit(self):
        r = self.run_dispatch()
        l = r['load_metrics'][0]
        self.assertEqual(l['maximum_target_interruption_hours'], 1)
        self.assertEqual(l['total_target_interruption_hours'], 2)
        self.assertEqual(l['target_status'], 'passed')
        self.assertAlmostEqual(r['metrics']['served_energy_kwh'], 10)

    def test_consecutive_gaps_and_forbidden_interruption_are_infeasible(self):
        with self.assertRaises(DispatchInfeasible):
            self.run_dispatch(grid_available_kw=[10, 0, 0])
        with self.assertRaises(DispatchInfeasible):
            self.run_dispatch({'interruption_allowed': False, 'maximum_interruption_hours': 0})

    def test_soft_mode_retains_shortage_evidence(self):
        r = self.run_dispatch(grid_available_kw=[10, 0, 0], enforce_load_targets=False)
        self.assertEqual(r['load_metrics'][0]['maximum_target_interruption_hours'], 2)
        self.assertEqual(r['load_metrics'][0]['target_status'], 'failed')

    def test_fractional_final_target_step_is_clipped(self):
        r = self.run_dispatch({'target_hours': 1.5, 'maximum_interruption_hours': .5}, steps=2, grid_available_kw=[10, 0])
        self.assertEqual(r['load_metrics'][0]['maximum_target_interruption_hours'], .5)
        with self.assertRaises(DispatchInfeasible):
            self.run_dispatch({'target_hours': 1.5, 'maximum_interruption_hours': .49}, steps=2, grid_available_kw=[10, 0])

    def test_zero_target_demand_resets_clock(self):
        r = self.run_dispatch({'curve_kw': [10, 0, 10]}, grid_available_kw=[0])
        self.assertEqual(r['load_metrics'][0]['maximum_target_interruption_hours'], 1)
        self.assertEqual(r['load_metrics'][0]['total_target_interruption_hours'], 2)

    def test_horizon_short_rejected_and_curtailment_not_exempted(self):
        with self.assertRaisesRegex(ValueError, '完整目标时长'):
            self.run_dispatch(steps=2, grid_available_kw=[10])
        with self.assertRaises(DispatchInfeasible):
            self.run_dispatch({'minimum_supply_ratio': .6, 'maximum_curtailment_ratio': .8},
                              allow_demand_response=True, grid_available_kw=[5])

    def plan(self, policy, holdout):
        inv = Inventory(loads=[self.load], sources=[{'id': 'D', 'name': '人工备用候选', 'node': 2, 'kind': '柴油机',
                          'rated_kw': 10, 'existing': False, 'fuel_kwh': 100, 'black_start': True, 'grid_forming': True}])
        values = {'base': self.base | {'enforce_load_targets': False}, 'candidates': [{'asset_id': 'D', 'capex_yuan': 100}],
                  'stages': [{'name': '近期', 'year': 2026, 'annual_occurrences': 0}],
                  'scenarios': [{'id': 'train', 'weight': 1, 'grid_available_kw': [0, 10, 0]}],
                  'validation_scenarios': [{'id': 'holdout', 'weight': 1, 'grid_available_kw': holdout}],
                  'target_policy': policy, 'required_probability': 1, 'relative_gap': 0}
        return investment_plan(InvestmentInput.model_validate(values), inv, self.net)

    def test_budget_chance_avoids_unnecessary_build_and_failed_holdout_is_proved(self):
        budget = self.plan('interruption_budget', [10, 0, 0])
        self.assertEqual(budget['selected_assets'], [])
        self.assertEqual(budget['compliance'][0]['actual_probability'], 1)
        self.assertEqual(budget['validation'][0]['success_probability_upper'], 0)
        self.assertEqual(budget['recommendation_status'], 'not_recommended_validation_failed')
        strict = self.plan('every_step', [10, 0, 0])
        self.assertEqual(strict['selected_assets'][0]['asset_id'], 'D')
        self.assertEqual(strict['validation'][0]['success_probability_lower'], 1)

    def test_budget_holdout_witness_passes_without_extra_investment(self):
        r = self.plan('interruption_budget', [10, 0, 10])
        self.assertEqual(r['selected_assets'], [])
        self.assertEqual(r['validation'][0]['success_probability_lower'], 1)
        self.assertEqual(r['validation'][0]['samples'][0]['result']['load_metrics'][0]['maximum_target_interruption_hours'], 1)

    def test_disaster_scan_rejects_hard_base_instead_of_losing_failure_traces(self):
        from backend.disaster_studies import DisasterInput
        with self.assertRaisesRegex(ValueError, '保留缺供轨迹'):
            DisasterInput.model_validate({'base': self.base, 'intensities': [1], 'durations_hours': [1],
                'fragilities': [{'kind': 'grid', 'target_id': 'grid', 'provenance': '人工'}]})


if __name__ == '__main__':
    unittest.main()
