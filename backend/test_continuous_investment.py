"""Independent power/energy, rated physics, and cashflow hand checks."""
import unittest
from pydantic import ValidationError
from backend.engineering import Inventory
from backend.investment_planning import InvestmentInput, investment_plan
from backend import test_investment_planning as investment_fixtures


class ContinuousInvestmentTests(unittest.TestCase):
    def setUp(self):
        fixture = investment_fixtures.InvestmentTests()
        fixture.setUp()
        self.network, self.load = fixture.network, fixture.load
        self.values = fixture.values | {'scenarios': [{'id': 'off', 'weight': 1}], 'required_probability': 1}
        self.battery = {'id': 'B', 'name': '参考储能上限', 'node': 2, 'power_kw': 100, 'energy_kwh': 100,
                        'existing': False, 'grid_forming': True, 'black_start': True,
                        'initial_soc': .8, 'minimum_soc': .1, 'discharge_efficiency': .95}
        self.cost = {'asset_id': 'B', 'sizing_mode': 'continuous', 'capex_yuan': 2000,
                     'power_capex_yuan': 1000, 'energy_capex_yuan': 1000, 'lifetime_years': 10}
        self.source = fixture.source | {'rated_kw': 100, 'fuel_kwh': 1000}

    def solve(self, cost=None, battery=None, changes=None, source=None, load=None):
        candidate = self.cost | (cost or {})
        inv = Inventory(storage=[self.battery | (battery or {})], loads=[self.load | (load or {})])
        if source is not None:
            inv = Inventory(sources=[self.source | source], loads=[self.load | (load or {})])
            candidate = {'asset_id': 'D', 'sizing_mode': 'continuous', 'capex_yuan': 1000} | (cost or {})
        return investment_plan(InvestmentInput.model_validate(self.values | {'candidates': [candidate]} | (changes or {})), inv, self.network)

    def test_storage_independent_power_energy_and_actual_soc(self):
        result = self.solve()
        a = result['selected_assets'][0]
        expected_energy = 20/(.95*(.8-.1-.02))
        self.assertAlmostEqual(a['power_kw'], 10, places=5)
        self.assertAlmostEqual(a['energy_kwh'], expected_energy, places=5)
        self.assertNotAlmostEqual(a['power_fraction'], a['energy_fraction'])
        self.assertAlmostEqual(a['capex_yuan'], 100+10*expected_energy, places=5)
        self.assertAlmostEqual(result['objective_yuan'], a['capex_yuan'], places=5)
        rows = result['scenario_results'][0]['result']['rows']
        self.assertAlmostEqual(rows[0]['storage'][0]['effective_capacity_kwh'], expected_energy)
        self.assertAlmostEqual(rows[-1]['storage'][0]['soc'], .12)
        self.assertTrue(all(abs(row['served_kw']-10) < 1e-6 for row in rows))

    def test_duration_design_couples_power_and_energy(self):
        slow = self.solve({'minimum_duration_hours': 4})['selected_assets'][0]
        self.assertAlmostEqual(slow['power_kw'], 10)
        self.assertAlmostEqual(slow['energy_kwh'], 40)
        fast = self.solve({'maximum_duration_hours': 2})['selected_assets'][0]
        self.assertAlmostEqual(fast['energy_kwh']/fast['power_kw'], 2)
        self.assertGreater(fast['power_kw'], 15)

    def test_fixed_cost_does_not_shrink_and_actual_size_maintenance_and_salvage(self):
        result = self.solve({'fixed_capex_yuan': 100, 'annual_maintenance_yuan': 30,
                             'power_maintenance_yuan': 10, 'energy_maintenance_yuan': 20,
                             'fixed_annual_maintenance_yuan': 7}, changes={'salvage_policy': 'linear_remaining_life'})
        a = result['selected_assets'][0]
        self.assertAlmostEqual(a['capex_yuan'], 100+1000*a['power_fraction']+1000*a['energy_fraction'])
        self.assertAlmostEqual(a['annual_maintenance_yuan'], 7+10*a['power_fraction']+20*a['energy_fraction'])
        flow = result['cashflows'][0]
        self.assertAlmostEqual(flow['terminal_salvage_yuan'], a['capex_yuan']*.9)
        self.assertAlmostEqual(result['objective_yuan'], a['capex_yuan']*.1+a['annual_maintenance_yuan'])

    def test_actual_scaled_budget_not_full_reference_cost(self):
        self.assertEqual(self.solve(changes={'total_investment_budget_yuan': 410})['status'], 'complete')
        self.assertEqual(self.solve(changes={'total_investment_budget_yuan': 409})['status'], 'infeasible')
        self.assertEqual(self.solve({'fixed_capex_yuan': 100}, changes={'total_investment_budget_yuan': 500})['status'], 'infeasible')

    def test_holdout_replays_selected_capacity_instead_of_reference(self):
        result = self.solve(changes={'validation_scenarios': [{'id': 'higher', 'weight': 1, 'load_scale': 1.01}]})
        self.assertEqual(result['validation'][0]['success_probability_upper'], 0)
        self.assertEqual(result['recommendation_status'], 'not_recommended_validation_failed')
        self.assertAlmostEqual(result['validation'][0]['samples'][0]['result']['rows'][0]['storage'][0]['effective_capacity_kwh'], result['selected_assets'][0]['energy_kwh'])

    def test_continuous_source_fuel_minimum_ramp_and_inverter(self):
        normal = self.solve(source={})['selected_assets'][0]
        self.assertAlmostEqual(normal['power_kw'], 10)
        fixed = self.solve(source={'fuel_kwh': 30})
        self.assertAlmostEqual(fixed['selected_assets'][0]['power_kw'], 10)
        self.assertAlmostEqual(fixed['scenario_results'][0]['result']['rows'][-1]['sources'][0]['fuel_remaining_kwh'], 10)
        fuel = self.solve({'fuel_budget_mode': 'proportional'}, source={'fuel_kwh': 30})['selected_assets'][0]
        self.assertAlmostEqual(fuel['power_fraction'], 20/(30*.98), places=5)
        ramp = self.solve(source={'ramp_kw_per_minute': .5})['selected_assets'][0]
        self.assertAlmostEqual(ramp['power_fraction'], 10/30, places=5)
        inverter = self.solve(source={'apparent_limit_kva': 20})['selected_assets'][0]
        self.assertAlmostEqual(inverter['power_fraction'], .5, places=5)
        minimum = self.solve(source={'minimum_kw': 50})['selected_assets'][0]
        self.assertAlmostEqual(minimum['power_fraction'], .1, places=5)

    def test_temperature_derates_both_design_dimensions(self):
        result = self.solve(changes={'scenarios': [{'id': 'cold', 'weight': 1, 'storage_temperature_factor': {'B': .5}}]})
        a = result['selected_assets'][0]
        self.assertAlmostEqual(a['power_kw'], 20)
        self.assertAlmostEqual(a['energy_kwh'], 40/(.95*.68))

    def test_reactive_limits_and_source_profile_runtime_scale_correctly(self):
        for source in [False, True]:
            r = self.solve(source={'reactive_limit_kvar': 20} if source else None,
                           battery={'reactive_limit_kvar': 20}, load={'reactive_kvar': 10})
            self.assertAlmostEqual(r['selected_assets'][0]['power_kw'], 50)
        runtime = self.solve(source={'fuel_kwh': None, 'available_hours': 2})
        self.assertAlmostEqual(runtime['selected_assets'][0]['power_kw'], 10)
        curve = self.solve(source={'curve_kw': [30]})
        self.assertAlmostEqual(curve['selected_assets'][0]['power_kw'], 100/3)

    def test_charge_power_scales_and_soc_upper_bound_limits_energy(self):
        r = self.solve(battery={'initial_soc': .1}, changes={'scenarios': [{'id': 'charge', 'weight': 1, 'grid_available_kw': [30, 0]}]})
        a = r['selected_assets'][0]
        energy = 10/(.95*(.95-.12))
        power = (.95-.1)*energy/.95
        self.assertAlmostEqual(a['energy_kwh'], energy)
        self.assertAlmostEqual(a['power_kw'], power)
        rows = r['scenario_results'][0]['result']['rows']
        self.assertAlmostEqual(rows[0]['storage'][0]['charge_kw'], power)
        self.assertAlmostEqual(rows[0]['storage'][0]['soc'], .95)
        self.assertAlmostEqual(rows[1]['storage'][0]['discharge_kw'], 10)

    def test_selected_capacity_inherits_without_per_stage_free_enlargement(self):
        r = self.solve(changes={'stages': [{'name': '一期', 'year': 2026, 'annual_occurrences': 0},
                                          {'name': '二期', 'year': 2027, 'load_scale': 2, 'annual_occurrences': 0}]})
        a = r['selected_assets'][0]
        self.assertEqual(a['commission_year'], 2026)
        self.assertAlmostEqual(a['power_kw'], 20)
        capacities = [t['result']['rows'][0]['storage'][0]['effective_capacity_kwh'] for t in r['scenario_results']]
        self.assertAlmostEqual(capacities[0], capacities[1])
        self.assertAlmostEqual(capacities[0], a['energy_kwh'])

    def test_phase_override_inherits_after_frozen_json_roundtrip(self):
        from backend.investment_planning import scenario_model
        values = self.values | {'candidates': [self.cost],
                                'stages': [{'name': '一期', 'year': 2026}, {'name': '二期', 'year': 2027}],
                                'scenarios': [{'id': 'off', 'weight': 1, 'load_scale': 1.01,
                                               'grid_available_kw': [20], 'storage_temperature_factor': {'B': .5},
                                               'stage_overrides': {2027: {'grid_available_kw': [0]}}}]}
        req = InvestmentInput.model_validate(values)
        frozen = InvestmentInput.model_validate_json(req.model_dump_json())
        inv = Inventory(storage=[self.battery], loads=[self.load])
        for parsed in [req, frozen]:
            params, actual = scenario_model(parsed, inv, parsed.stages[1], parsed.scenarios[0])
            self.assertEqual(params.grid_available_kw, [0])
            self.assertAlmostEqual(actual.loads[0].peak_kw, 10.1)
            self.assertEqual(actual.storage[0].temperature_factor, .5)

    def test_unbuilt_continuous_battery_has_no_energy_q_or_voltage_support(self):
        result = self.solve(changes={'scenarios': [{'id': 'grid', 'weight': 1, 'grid_available_kw': [20]}]})
        self.assertEqual(result['selected_assets'], [])
        trace = result['scenario_results'][0]['result']['rows'][0]['storage'][0]
        self.assertFalse(trace['installed'])
        for field in ['effective_capacity_kwh', 'energy_begin_kwh', 'energy_end_kwh', 'charge_kw', 'discharge_kw', 'reactive_kvar']:
            self.assertEqual(trace[field], 0)

    def test_invalid_bounds_missing_or_inconsistent_costs_rejected(self):
        for cost in [{'minimum_power_fraction': .8, 'maximum_power_fraction': .2},
                     {'minimum_duration_hours': 4, 'maximum_duration_hours': 2},
                     {'power_capex_yuan': None}, {'energy_capex_yuan': 999},
                     {'annual_maintenance_yuan': 3}, {'power_maintenance_yuan': 1},
                     {'sizing_mode': 'block'}]:
            with self.subTest(cost=cost), self.assertRaises((ValueError, ValidationError)):
                self.solve(cost)


if __name__ == '__main__':
    unittest.main()
