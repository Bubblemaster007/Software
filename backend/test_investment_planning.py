"""Hand-calculated chance decisions, location, commission/retirement and cash flows."""
import unittest
from pydantic import ValidationError
from backend.engineering import Inventory
from backend.network_data import Network
from backend.investment_planning import (InvestmentInput, CandidateInvestment, ConstructionStage, WeightedScenario,
                                         investment_plan, validate_investment, operating_periods, validate_portfolio)
from backend.study_control import StudyCancelled


class InvestmentTests(unittest.TestCase):
    def setUp(self):
        self.network = Network(nodes=[{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 10}],
                               lines=[{'line': 7, 'from_node': 1, 'to_node': 2, 'r_ohm': 0, 'x_ohm': 0}])
        self.source = {'id': 'D', 'name': '候选构网机组', 'node': 2, 'kind': '柴油机', 'rated_kw': 10,
                       'fuel_kwh': 100, 'grid_forming': True, 'black_start': True, 'existing': False}
        self.load = {'id': 'L', 'name': '医院', 'node': 2, 'peak_kw': 10, 'target_hours': 2, 'load_class': '基本保障'}
        self.inventory = Inventory(sources=[self.source], loads=[self.load])
        self.base = {'project_id': 'test', 'project_revision': 1, 'engineering_revision': 1,
                     'steps': 2, 'grid_available_kw': [0]}
        self.candidate = {'asset_id': 'D', 'capex_yuan': 100, 'lifetime_years': 10}
        self.scenarios = [{'id': 'grid', 'weight': .8, 'grid_available_kw': [20]}, {'id': 'outage', 'weight': .2, 'grid_available_kw': [0]}]
        self.values = {'base': self.base, 'candidates': [self.candidate], 'stages': [{'name': '现状阶段', 'year': 2026, 'annual_occurrences': 0}],
                       'scenarios': self.scenarios, 'required_probability': .8, 'discount_rate': 0, 'relative_gap': 0}

    def run_plan(self, changes=None, inventory=None):
        return investment_plan(InvestmentInput.model_validate(self.values | (changes or {})), inventory or self.inventory, self.network)

    def test_weighted_joint_chance_changes_actual_investment(self):
        low = self.run_plan()
        high = self.run_plan({'required_probability': .81})
        self.assertEqual(low['selected_assets'], [])
        self.assertEqual(high['selected_assets'][0]['asset_id'], 'D')
        self.assertAlmostEqual(low['objective_yuan'], 0)
        self.assertAlmostEqual(high['objective_yuan'], 100)
        self.assertAlmostEqual(low['compliance'][0]['actual_probability'], .8)
        self.assertAlmostEqual(high['compliance'][0]['actual_probability'], 1)
        self.assertLess(high['certificate']['primal_violation'], 1e-4)

    def test_expected_operating_loss_and_discount_drive_tradeoff(self):
        stages = [{'name': '一年运营', 'year': 2026, 'annual_occurrences': 1}]
        cheap = self.run_plan({'stages': stages, 'candidates': [self.candidate | {'capex_yuan': 60}]})
        expensive = self.run_plan({'stages': stages, 'candidates': [self.candidate | {'capex_yuan': 90}]})
        self.assertEqual(cheap['selected_assets'][0]['asset_id'], 'D')
        self.assertAlmostEqual(cheap['objective_yuan'], 60+8+4.6+.00002, places=4)
        self.assertEqual(expensive['selected_assets'], [])
        self.assertAlmostEqual(expensive['objective_yuan'], 8+80, places=4)
        discounted = self.run_plan({'stages': stages, 'candidates': [self.candidate | {'capex_yuan': 75}], 'discount_rate': .1})
        self.assertEqual(discounted['selected_assets'], [])
        self.assertAlmostEqual(discounted['objective_yuan'], 88/1.1, places=4)

    def test_network_location_not_replaced_by_aggregate_capacity(self):
        inv = Inventory(sources=[self.source | {'id': 'root', 'node': 1}, self.source], loads=[self.load])
        cases = [self.scenarios[0], self.scenarios[1] | {'line_status': {7: [0]}}]
        r = self.run_plan({'scenarios': cases, 'required_probability': 1,
                           'candidates': [self.candidate, self.candidate | {'asset_id': 'root', 'capex_yuan': 1}]}, inv)
        self.assertEqual([s['asset_id'] for s in r['selected_assets']], ['D'])

    def test_unbuilt_storage_has_no_initial_energy_or_voltage_formation(self):
        inv = Inventory(storage=[{'id': 'B', 'name': '候选储能', 'node': 2, 'existing': False, 'power_kw': 10,
                                  'energy_kwh': 100, 'grid_forming': True, 'black_start': True}], loads=[self.load])
        r = self.run_plan({'candidates': [self.candidate | {'asset_id': 'B'}]}, inv)
        self.assertEqual(r['selected_assets'], [])
        outage = next(s['result'] for s in r['scenario_results'] if s['scenario_id'] == 'outage')
        self.assertAlmostEqual(outage['metrics']['served_energy_kwh'], 0)
        self.assertFalse(outage['rows'][0]['storage'][0]['installed'])
        self.assertEqual(outage['rows'][0]['storage'][0]['energy_begin_kwh'], 0)
        self.assertIsNone(outage['rows'][0]['storage'][0]['soc'])

    def test_unbuilt_storage_cannot_give_free_reactive_power(self):
        inv = Inventory(storage=[{'id': 'B', 'name': '候选逆变储能', 'node': 2, 'existing': False, 'power_kw': 10,
                                  'energy_kwh': 100, 'reactive_limit_kvar': 20}], loads=[self.load | {'reactive_kvar': 10}])
        r = self.run_plan({'candidates': [self.candidate | {'asset_id': 'B'}]}, inv)
        self.assertEqual(r['selected_assets'][0]['asset_id'], 'B')

    def test_cold_scenario_reduces_storage_energy_not_only_power(self):
        inv = Inventory(sources=[self.source], storage=[{'id': 'B', 'name': '储能块', 'node': 2, 'existing': False,
                        'power_kw': 100, 'energy_kwh': 100, 'grid_forming': True, 'black_start': True}], loads=[self.load])
        cases = [{'id': 'warm', 'weight': .5}, {'id': 'cold', 'weight': .5, 'storage_temperature_factor': {'B': .2}}]
        changes = {'scenarios': cases, 'candidates': [self.candidate, self.candidate | {'asset_id': 'B', 'capex_yuan': 50}]}
        low = self.run_plan(changes | {'required_probability': .5}, inv)
        high = self.run_plan(changes | {'required_probability': 1}, inv)
        self.assertEqual([a['asset_id'] for a in low['selected_assets']], ['B'])
        self.assertEqual([a['asset_id'] for a in high['selected_assets']], ['D'])

    def test_stage_override_does_not_clear_another_device_fault(self):
        inv = Inventory(sources=[self.source, self.source | {'id': 'E', 'existing': True, 'rated_kw': 0}], loads=[self.load])
        cases = [{'id': 'path', 'weight': 1, 'grid_available_kw': [20], 'device_availability': {'D': [0]},
                  'stage_overrides': {2027: {'grid_available_kw': [0], 'device_availability': {'E': [1]}}}}]
        stages = [{'name': '一期', 'year': 2026, 'annual_occurrences': 0}, {'name': '二期', 'year': 2027, 'annual_occurrences': 0}]
        r = self.run_plan({'scenarios': cases, 'stages': stages, 'required_probability': 1}, inv)
        self.assertEqual(r['status'], 'infeasible')

    def test_budget_infeasible_not_zero_cost_success(self):
        r = self.run_plan({'required_probability': 1, 'total_investment_budget_yuan': 99})
        self.assertEqual(r['status'], 'infeasible')
        self.assertIsNone(r['objective_yuan'])

    def test_commission_not_available_early_and_stage_budgets(self):
        stages = [{'name': '近期', 'year': 2026, 'budget_yuan': 0, 'annual_occurrences': 0},
                  {'name': '中期', 'year': 2027, 'budget_yuan': 100, 'annual_occurrences': 0}]
        case = {'id': 'trajectory', 'weight': 1, 'grid_available_kw': [20], 'stage_overrides': {2027: {'grid_available_kw': [0]}}}
        r = self.run_plan({'stages': stages, 'scenarios': [case], 'required_probability': 1,
                           'candidates': [self.candidate | {'earliest_year': 2027}]})
        self.assertEqual(r['selected_assets'][0]['commission_year'], 2027)
        early = next(s['result'] for s in r['scenario_results'] if s['period'] == 0)
        self.assertFalse(early['rows'][0]['sources'][0]['installed'])
        self.assertEqual(r['cashflows'][0]['capex_yuan'], 0)
        self.assertEqual(r['cashflows'][1]['capex_yuan'], 100)

    def test_lifetime_inheritance_and_midstage_retirement_split(self):
        stages = [{'name': '三年规划', 'year': 2026, 'duration_years': 3, 'annual_occurrences': 0}]
        cases = [{'id': 'outage', 'weight': 1, 'grid_available_kw': [0]}]
        r = self.run_plan({'stages': stages, 'scenarios': cases, 'required_probability': 1,
                           'candidates': [self.candidate | {'lifetime_years': 1}]})
        self.assertEqual(r['status'], 'infeasible')
        inv = Inventory(sources=[self.source, self.source | {'id': 'old', 'existing': True}], loads=[self.load])
        r = self.run_plan({'stages': stages, 'scenarios': cases, 'required_probability': 1, 'existing_retirement_year': {'old': 2027}}, inv)
        self.assertEqual([c['year'] for c in r['compliance']], [2026, 2027])
        self.assertIn('old', r['compliance'][0]['active_assets'])
        self.assertNotIn('old', r['compliance'][1]['active_assets'])
        self.assertEqual(r['selected_assets'][0]['asset_id'], 'D')

    def test_discount_maintenance_and_terminal_salvage(self):
        r = self.run_plan({'required_probability': 1, 'stages': [{'name': '三年', 'year': 2026, 'duration_years': 3, 'annual_occurrences': 0}],
                           'candidates': [self.candidate | {'annual_maintenance_yuan': 5}], 'salvage_policy': 'linear_remaining_life'})
        self.assertAlmostEqual(r['objective_yuan'], 100+3*5-70)
        self.assertEqual(r['cashflows'][-1]['terminal_salvage_yuan'], 70)
        self.assertAlmostEqual(sum(c['discounted_total_yuan'] for c in r['cashflows']), r['objective_yuan'])

    def test_existing_maintenance_stops_at_retirement_without_losing_fixed_cost(self):
        inv = Inventory(sources=[self.source, self.source | {'id': 'old', 'existing': True}], loads=[self.load], economics={'annual_maintenance_yuan': 2})
        r = self.run_plan({'stages': [{'name': '三年', 'year': 2026, 'duration_years': 3, 'annual_occurrences': 0}],
                           'scenarios': [{'id': 'outage', 'weight': 1}], 'required_probability': 1,
                           'existing_retirement_year': {'old': 2027}, 'existing_annual_maintenance_yuan': {'old': 5}}, inv)
        self.assertAlmostEqual(r['objective_yuan'], 100+3*2+5)
        self.assertEqual([c['existing_asset_maintenance_yuan'] for c in r['cashflows']], [5, 0, 0])

    def test_cross_period_joint_probability_not_only_marginals(self):
        stages = [{'name': '一期', 'year': 2026, 'annual_occurrences': 0}, {'name': '二期', 'year': 2027, 'annual_occurrences': 0}]
        cases = [{'id': 'A', 'weight': .5, 'grid_available_kw': [20], 'stage_overrides': {2027: {'grid_available_kw': [0]}}},
                 {'id': 'B', 'weight': .5, 'grid_available_kw': [0], 'stage_overrides': {2027: {'grid_available_kw': [20]}}}]
        marginal = self.run_plan({'stages': stages, 'scenarios': cases, 'required_probability': .5})
        joint = self.run_plan({'stages': stages, 'scenarios': cases, 'required_probability': .5, 'risk_scope': 'all_periods'})
        self.assertEqual(marginal['selected_assets'], [])
        self.assertLess(marginal['all_periods_actual_probability'], .5)
        self.assertTrue(joint['selected_assets'])
        self.assertGreaterEqual(joint['all_periods_actual_probability'], .5)

    def test_holdout_failure_and_unmeasured_probability_mass_preserved(self):
        validation = [{'id': 'holdout', 'weight': 1, 'device_availability': {'D': [0]}}]
        r = self.run_plan({'required_probability': 1, 'validation_scenarios': validation})
        self.assertEqual(r['validation'][0]['success_probability_lower'], 0)
        self.assertEqual(r['validation'][0]['samples'][0]['status'], 'failed')
        req = InvestmentInput.model_validate(self.values | {'validation_scenarios': validation})
        selected = [{'asset_id': 'D', 'commission_year': 2026, 'retirement_year': 2036}]
        unknown = validate_portfolio(req, self.inventory, self.network, operating_periods(req), selected, lambda: 0, None, None)
        self.assertEqual(unknown[0]['unknown_probability'], 1)
        self.assertEqual(unknown[0]['success_probability_upper'], 1)

    def test_invalid_weights_targets_and_duplicate_holdout_rejected(self):
        for change in [{'scenarios': [self.scenarios[0]]}, {'validation_scenarios': [self.scenarios[0] | {'id': 'renamed', 'weight': 1}]},
                       {'stages': [{'name': 'a', 'year': 2026}, {'name': 'b', 'year': 2028}]}]:
            with self.assertRaises(ValidationError):
                InvestmentInput.model_validate(self.values | change)
        bad = Inventory(sources=[self.source], loads=[self.load | {'target_hours': 48}])
        with self.assertRaises(ValueError):
            self.run_plan(inventory=bad)
        with self.assertRaises(ValueError):
            validate_investment(InvestmentInput.model_validate(self.values), Inventory(sources=[self.source | {'existing': True}], loads=[self.load]), self.network)

    def test_cancelled_job_produces_no_investment_conclusion(self):
        with self.assertRaises(StudyCancelled):
            investment_plan(InvestmentInput.model_validate(self.values), self.inventory, self.network, cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
