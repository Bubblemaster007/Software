"""Risk threshold hand checks, OAT isolation, incomplete cases and evidence sinks."""
import unittest
from unittest.mock import patch
from backend import test_investment_planning as fixtures
from backend.engineering import canonical_sha
from backend.investment_experiments import (InvestmentExperimentInput, run_experiments,
                                            apply_case, definitions, non_dominated)
from backend.study_control import StudyCancelled
from backend.resource_dispatch import DispatchIncomplete


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.InvestmentTests(); f.setUp()
        self.inventory, self.network = f.inventory, f.network
        self.values = f.values | {'required_probability': .95, 'probability_levels': [.8, .9, 1],
            'sensitivities': [{'name': '资本减半', 'parameter': 'capital_cost_scale', 'value': .5},
                              {'name': '资本加倍', 'parameter': 'capital_cost_scale', 'value': 2}]}

    def run_study(self, **extra):
        return run_experiments(InvestmentExperimentInput.model_validate(self.values | extra), self.inventory, self.network)

    def test_actual_risk_threshold_and_one_factor_reoptimization(self):
        original = canonical_sha(self.inventory.model_dump())
        r = self.run_study()
        rows = {c['id']: c for c in r['cases']}
        self.assertEqual(r['status'], 'complete')
        self.assertEqual(rows['baseline']['objective_yuan'], 100)
        self.assertEqual(rows['risk-01']['objective_yuan'], 0)
        self.assertAlmostEqual(rows['risk-01']['training_success_probability'], .8)
        self.assertAlmostEqual(rows['risk-01']['worst_period_expected_event_unsupplied_kwh'], 4)
        self.assertEqual(rows['sensitivity-01']['objective_yuan'], 50)
        self.assertEqual(rows['sensitivity-02']['objective_yuan'], 200)
        self.assertEqual(rows['sensitivity-01']['delta_objective_yuan'], -50)
        self.assertNotIn('sensitivity-01', r['training_non_dominated'])
        self.assertEqual(r['validated_non_dominated'], [])
        self.assertEqual(original, canonical_sha(self.inventory.model_dump()))

    def test_validation_failure_does_not_enter_validated_frontier(self):
        r = self.run_study(validation_scenarios=[{'id': 'heldout', 'weight': 1, 'device_availability': {'D': [0]}}])
        self.assertTrue(all(c['validation_status'] == 'failed' for c in r['cases']))
        self.assertEqual(r['validated_non_dominated'], [])
        self.assertTrue(r['training_non_dominated'])

    def test_frontier_dominance_and_sensitivity_costs_not_mixed(self):
        rows = [{'id': 'A', 'kind': 'baseline', 'objective_yuan': 100, 'training_success_probability': .9, 'validation_status': 'failed'},
                {'id': 'B', 'kind': 'risk', 'objective_yuan': 100, 'training_success_probability': 1, 'validation_status': 'passed', 'validation_success_probability_lower':1},
                {'id': 'C', 'kind': 'risk', 'objective_yuan': 0, 'training_success_probability': .8, 'validation_status': 'not_checked'},
                {'id': 'S', 'kind': 'sensitivity', 'objective_yuan': 0, 'training_success_probability': 1, 'validation_status': 'passed'}]
        self.assertEqual(non_dominated(rows), ['B', 'C'])
        self.assertEqual(non_dominated(rows, True), ['B'])

    def test_validated_frontier_uses_holdout_lower_not_training_probability(self):
        rows = [{'id':'cheap','kind':'baseline','objective_yuan':100,'training_success_probability':1,
                 'validation_status':'passed','validation_success_probability_lower':.8},
                {'id':'reliable','kind':'risk','objective_yuan':200,'training_success_probability':1,
                 'validation_status':'passed','validation_success_probability_lower':1}]
        self.assertEqual(non_dominated(rows), ['cheap'])
        self.assertEqual(non_dominated(rows, True), ['cheap','reliable'])

    def test_complete_case_sink_keeps_physical_trace_and_unique_signatures(self):
        sink = {}
        r = run_experiments(InvestmentExperimentInput.model_validate(self.values), self.inventory, self.network,
                            case_sink=lambda i, result: sink.update({i: result}))
        self.assertEqual(len(sink), len(r['cases']))
        self.assertTrue(all(c['detail_archived'] and 'detail' not in c for c in r['cases']))
        self.assertTrue(sink['baseline']['result']['scenario_results'][0]['result']['rows'])
        self.assertNotEqual(sink['baseline']['derived_input_sha256'], sink['sensitivity-01']['derived_input_sha256'])

    def test_zero_baseline_cost_relative_delta_is_unavailable(self):
        r = self.run_study(required_probability=.8)
        self.assertTrue(all(c['relative_objective_change'] is None for c in r['cases']))

    def test_time_limit_and_cancellation_not_infeasible_or_zero_cost(self):
        with patch('backend.investment_experiments.time.monotonic', side_effect=[0]+[2]*40):
            r = self.run_study(wall_time_seconds=1)
        self.assertEqual(r['status'], 'incomplete')
        self.assertTrue(all(c['status']=='not_run_time_limit' and c['objective_yuan'] is None for c in r['cases']))
        self.assertEqual(r['training_non_dominated'], [])
        with self.assertRaises(StudyCancelled):
            run_experiments(InvestmentExperimentInput.model_validate(self.values), self.inventory, self.network, cancelled=lambda: True)
        with patch('backend.investment_experiments.investment_plan', side_effect=DispatchIncomplete('限时')):
            r = self.run_study()
        self.assertTrue(all(c['status'] == 'incomplete_solve' for c in r['cases']))

    def test_protocol_error_is_not_a_feasible_or_infeasible_point(self):
        with patch('backend.investment_experiments.investment_plan', side_effect=RuntimeError('原生进程错误')):
            with self.assertRaisesRegex(RuntimeError, '原生进程错误'):
                self.run_study()

    def test_invalid_levels_and_variations_rejected(self):
        for changes in [{'probability_levels': [.8, .8]}, {'probability_levels': [0]},
                        {'sensitivities': [{'name':'错', 'parameter':'discount_rate','value':1.1}]},
                        {'sensitivities': [{'name':'错', 'parameter':'storage_temperature_factor','value':.5}]}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.run_study(**changes)

    def test_baseline_level_reused_not_duplicated(self):
        req = InvestmentExperimentInput.model_validate(self.values | {'probability_levels': [.95]})
        self.assertEqual(len(definitions(req)), 3)
        params, actual = apply_case(req, self.inventory, definitions(req)[2])
        self.assertEqual(params.candidates[0].capex_yuan, 200)
        self.assertEqual(actual.economics.fuel_yuan_per_kwh, self.inventory.economics.fuel_yuan_per_kwh)

    def test_load_growth_infeasible_point_has_no_cost_or_frontier_credit(self):
        r = self.run_study(probability_levels=[], sensitivities=[{'name':'负荷增加', 'parameter':'load_scale','value':1.1}])
        point = r['cases'][1]
        self.assertEqual(point['status'], 'infeasible')
        self.assertIsNone(point['objective_yuan'])
        self.assertNotIn(point['id'], r['training_non_dominated'])

    def test_temperature_changes_physical_design_not_cost_only(self):
        from backend.engineering import Inventory
        inv = Inventory(storage=[{'id':'B','name':'参考储能','node':2,'power_kw':100,'energy_kwh':100,
                                  'existing':False,'black_start':True,'grid_forming':True}], loads=self.inventory.loads)
        values = self.values | {'probability_levels':[], 'scenarios':[{'id':'off','weight':1}],
            'candidates':[{'asset_id':'B','sizing_mode':'continuous','capex_yuan':2000,'power_capex_yuan':1000,'energy_capex_yuan':1000}],
            'sensitivities':[{'name':'寒冷','parameter':'storage_temperature_factor','value':.5}]}
        r = run_experiments(InvestmentExperimentInput.model_validate(values), inv, self.network)
        a,b = [c['selected_assets'][0] for c in r['cases']]
        self.assertAlmostEqual(b['power_kw'], 2*a['power_kw'])
        self.assertAlmostEqual(b['energy_kwh'], 2*a['energy_kwh'])
        self.assertAlmostEqual(r['cases'][1]['objective_yuan'], 2*r['cases'][0]['objective_yuan'])


if __name__ == '__main__':
    unittest.main()
