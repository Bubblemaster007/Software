"""Independent probability identities, physical failure cases, and paired mitigation."""
import math
import unittest
from unittest.mock import patch
import numpy as np
from pydantic import ValidationError
from backend.engineering import Inventory
from backend.network_data import Network
from backend.resource_dispatch import DispatchInput, DispatchIncomplete, dispatch
from backend.disaster_studies import (DisasterInput, Fragility, step_probability, draws, materialize,
                                     wilson, boundaries, scan, summarize_case, success_status)
from backend.study_control import StudyCancelled


class DisasterTests(unittest.TestCase):
    def setUp(self):
        self.network = Network(nodes=[{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 100}],
                               lines=[{'line': 7, 'from_node': 1, 'to_node': 2, 'r_ohm': 0, 'x_ohm': 0}])
        self.inventory = Inventory(loads=[{'id': 'L', 'name': '医院', 'node': 2, 'peak_kw': 100,
                                          'target_hours': 4, 'load_class': '基本保障'}])
        self.base = {'project_id': 'test', 'project_revision': 1, 'engineering_revision': 1,
                     'steps': 4, 'grid_available_kw': [100], 'time_limit_seconds': 20}
        self.frag = {'kind': 'line', 'target_id': '7', 'failure_probability': 1, 'repair_hours': 1,
                     'provenance': '人工确定性反例'}
        self.req = DisasterInput(base=self.base, intensities=[0, 1], durations_hours=[1, 2], samples=2,
                                 fragilities=[self.frag], criterion='energy_budget', judgement='empirical',
                                 weakness_targets=['line:7'])

    def test_reference_exposure_and_time_step_probability(self):
        f = Fragility(**(self.frag | {'failure_probability': .3, 'reference_duration_hours': 4}))
        self.assertAlmostEqual(1-(1-step_probability(f, 1, 1))**4, .3)
        self.assertAlmostEqual(1-(1-step_probability(f, 1, .25))**16, .3)
        self.assertLess(step_probability(f, .5, 1), step_probability(f, 1, 1))
        self.assertEqual(step_probability(f, 0, 1), 0)
        self.assertEqual(step_probability(Fragility(**self.frag), 1, .25), 1)
        extreme = f.model_copy(update={'reference_intensity': 1e-300})
        self.assertEqual(step_probability(extreme, 1000000, 1), 1)

    def test_keyed_draws_reorder_independent_and_common_cause(self):
        a = draws(2026, 0, 'target:line:7', 100)
        self.assertTrue(np.array_equal(a, draws(2026, 0, 'target:line:7', 100)))
        self.assertFalse(np.array_equal(a, draws(2026, 1, 'target:line:7', 100)))
        self.assertFalse(np.array_equal(a, draws(2026, 0, 'target:grid:grid', 100)))
        f = self.frag | {'failure_probability': .5, 'common_group': '同一气象冲击'}
        req = self.req.model_copy(update={'fragilities': [Fragility(**f), Fragility(**(f | {'kind': 'grid', 'target_id': 'grid'}))]})
        _, trace = materialize(req, 1, 2, 0, self.network, self.inventory)
        self.assertEqual(trace['availability']['line:7'], trace['availability']['grid:grid'])

    def test_failure_repair_recurrence_and_baseline_outage(self):
        req = self.req.model_copy(update={'fragilities': [Fragility(**(self.frag | {'repair_hours': 2}))]})
        p, trace = materialize(req, 1, 1, 0, self.network, self.inventory)
        self.assertEqual(p.line_status[7], [0, 0, 1, 1])
        self.assertEqual(trace['events'][0]['recover_step'], 2)
        p, _ = materialize(self.req, 1, 2, 0, self.network, self.inventory)
        self.assertEqual(p.line_status[7], [0, 0, 1, 1])
        self.req.base.line_status = {7: [0, 1, 0, 1]}
        p, _ = materialize(self.req, 0, 1, 0, self.network, self.inventory)
        self.assertEqual(p.line_status[7], [0, 1, 0, 1])
        p, _ = materialize(self.req, 1, 2, 0, self.network, self.inventory, 'line:7')
        self.assertEqual(p.line_status[7], [0, 1, 0, 1])

    def test_normally_open_switch_is_not_closed_by_recovered_line(self):
        self.inventory.switches = Inventory(switches=[{'id': 'S', 'name': '常开开关', 'node': 1, 'line_id': 7, 'normally_closed': False}]).switches
        params, _ = materialize(self.req, 1, 1, 0, self.network, self.inventory)
        self.assertEqual(params.line_status[7], [0, 0, 0, 0])
        result = dispatch(params, self.inventory, self.network)
        self.assertAlmostEqual(result['metrics']['total_unsupplied_energy_kwh'], 400)

    def test_spare_line_never_activated(self):
        network = self.network.model_copy(deep=True)
        network.lines[0].status = 0
        p, _ = materialize(self.req, 1, 1, 0, network, self.inventory)
        self.assertEqual(p.line_status[7], [0, 0, 0, 0])

    def test_real_milp_scan_and_paired_weakness(self):
        result = scan(self.req, self.inventory, self.network)
        cells = {(c['intensity'], c['duration_hours']): c for c in result['cases']}
        self.assertEqual(cells[0, 1]['judgement'], 'passed')
        self.assertEqual(cells[1, 1]['judgement'], 'failed')
        self.assertAlmostEqual(cells[1, 1]['mean_unsupplied_kwh'], 100, places=4)
        self.assertAlmostEqual(cells[1, 2]['mean_unsupplied_kwh'], 200, places=4)
        self.assertAlmostEqual(result['weakness'][0]['mean_avoided_unsupplied_kwh'], 200, places=4)
        self.assertEqual(result['weakness'][0]['reliable_pairs'], 2)
        self.assertEqual(result['completed_solves'], 10)
        self.assertEqual(result['boundaries'][0]['maximum_tested_feasible_intensity'], 0)
        self.assertEqual(self.req.base.line_status, {})

    def test_wilson_unknown_and_small_sample_not_proven(self):
        lo, hi = wilson(20, 20, .95)
        self.assertAlmostEqual(lo, .8388748419, places=8)
        self.assertAlmostEqual(hi, 1)
        req = self.req.model_copy(update={'judgement': 'wilson_lower', 'samples': 20})
        rows = [{'success': 'passed', 'unsupplied_kwh': 0}]*20
        self.assertEqual(summarize_case(req, 0, 1, rows)['judgement'], 'uncertain')
        blank = summarize_case(req, 0, 1, [])
        self.assertEqual(blank['unknown'], 20)
        self.assertEqual(blank['judgement'], 'uncertain')
        self.assertIsNone(blank['mean_unsupplied_kwh'])

    def test_boundary_all_feasible_none_and_nonmonotone(self):
        cells = [{'intensity': i, 'duration_hours': 1, 'judgement': s} for i, s in enumerate(['passed', 'failed', 'passed'])]
        b = boundaries(cells)[0]
        self.assertTrue(b['nonmonotone'])
        self.assertTrue(b['right_censored'])
        self.assertEqual(b['tested_feasible_intensities'], [0, 2])
        b = boundaries([{'intensity': 0, 'duration_hours': 1, 'judgement': 'failed'}])[0]
        self.assertIsNone(b['maximum_tested_feasible_intensity'])

    def test_cancel_and_no_incumbent_are_not_failures(self):
        with self.assertRaises(StudyCancelled):
            scan(self.req, self.inventory, self.network, cancelled=lambda: True)
        with self.assertRaises(StudyCancelled):
            dispatch(self.req.base, self.inventory, self.network, cancelled=lambda: True)
        with patch('backend.disaster_studies.dispatch', side_effect=DispatchIncomplete('时限')):
            result = scan(self.req, self.inventory, self.network)
        self.assertTrue(all(c['unknown'] == 2 and c['judgement'] == 'uncertain' for c in result['cases']))
        self.assertIsNone(result['worst_trace'])
        self.assertEqual(result['weakness'][0]['reliable_pairs'], 0)

    def test_target_horizon_and_limited_solution(self):
        req = self.req.model_copy(update={'criterion': 'load_targets'})
        self.assertEqual(success_status(req, {'metrics': {'all_load_targets': 'not_checked'}, 'status': 'optimal'}), 'unknown')
        self.assertEqual(success_status(req, {'metrics': {'all_load_targets': 'failed'}, 'status': 'feasible_limit'}), 'unknown')
        self.assertEqual(success_status(req, {'metrics': {'all_load_targets': 'passed'}, 'status': 'feasible_limit'}), 'passed')

    def test_global_deadline_preserves_all_untested_cells(self):
        req = self.req.model_copy(update={'wall_time_seconds': 1})
        with patch('backend.disaster_studies.time.monotonic', side_effect=[0, 2, 3]):
            result = scan(req, self.inventory, self.network)
        self.assertEqual(result['status'], 'incomplete_time_limit')
        self.assertEqual(result['completed_solves'], 0)
        self.assertEqual(len(result['cases']), 4)
        self.assertTrue(all(c['unknown'] == 2 and c['judgement'] == 'uncertain' for c in result['cases']))
        self.assertIsNone(result['weakness'][0]['mean_avoided_unsupplied_kwh'])

    def test_invalid_and_oversized_requests_rejected(self):
        values = self.req.model_dump()
        for change in [{'durations_hours': [1.1]}, {'intensities': [0, math.nan]}, {'weakness_targets': ['source:missing']},
                       {'samples': 1000, 'intensities': list(range(10))}]:
            with self.assertRaises(ValidationError):
                DisasterInput.model_validate(values | change)
        with self.assertRaises(ValueError):
            scan(self.req.model_copy(update={'fragilities': [Fragility(**(self.frag | {'target_id': '999'}))]}), self.inventory, self.network)


if __name__ == '__main__':
    unittest.main()
