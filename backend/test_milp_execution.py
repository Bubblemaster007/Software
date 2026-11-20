"""Actual numeric child protocol, confirmed owned-child cancellation, native faults."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from backend.resource_dispatch import SparseModel
from backend.milp_execution import native_milp
from backend.study_control import StudyCancelled


class NativeMilpTests(unittest.TestCase):
    def model(self):
        model = SparseModel()
        variable = model.var(0, 1, binary=True)
        model.add({variable: 1}, lower=1)
        return model, variable

    def test_actual_child_returns_binary_optimum(self):
        model, x = self.model()
        result = native_milp(model, {x: 3}, 20, 0)
        self.assertEqual(result.status, 0)
        self.assertAlmostEqual(result.x[x], 1)
        self.assertAlmostEqual(result.fun, 3)

    def test_cancellation_stops_only_owned_live_child(self):
        model, x = self.model()
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            return calls >= 3
        with self.assertRaises(StudyCancelled):
            native_milp(model, {x: 1}, 20, 0, cancelled=cancelled)
        self.assertGreaterEqual(calls, 3)

    def test_native_error_is_not_infeasibility_and_retains_numeric_input(self):
        model, x = self.model()
        with TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                native_milp(model, {x: float('nan')}, 20, 0, log_dir=directory)
            retained = list(Path(directory).glob('solver-failure-*/input.npz'))
            self.assertEqual(len(retained), 1)
            self.assertTrue((Path(directory)/'solver.log').exists())
            self.assertIn('finite numbers', (Path(directory)/'solver.log').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
