import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import app
from backend.effect_evaluation import EvaluationInput, topsis
from backend.engineering import canonical_sha


class EffectEvaluationTests(unittest.TestCase):
    def body(self):
        return {'project_id': 'test', 'project_revision': 1, 'name': '手算比较', 'criteria': [
            {'id': 'cost', 'name': '成本', 'direction': 'cost', 'unit': '元'},
            {'id': 'supply', 'name': '保供率', 'direction': 'benefit', 'unit': '比例', 'safety_limit': .95}],
            'alternatives': [{'id': 'A', 'name': '低成本高保供', 'values': [100, 1], 'provenance': '人工边界测试'},
                             {'id': 'B', 'name': '高成本低保供', 'values': [200, .8], 'provenance': '人工边界测试'}]}

    def test_dominance_orientation_and_safety_separate(self):
        r = topsis(EvaluationInput(**self.body()))
        self.assertEqual(r['normalized'], [[1, 1], [0, 0]])
        self.assertAlmostEqual(r['ranking'][0]['score'], 1)
        self.assertAlmostEqual(r['ranking'][1]['score'], 0)
        self.assertEqual(r['ranking'][0]['gate'], 'not_checked')
        self.assertEqual(r['ranking'][1]['gate'], 'failed')
        self.assertFalse(r['ranking'][0]['engineering_recommendation'])
        self.assertTrue(r['critic_fallback_to_entropy'])
        self.assertAlmostEqual(sum(w['combined'] for w in r['weights']), 1)

    def test_constant_criterion_and_identical_rows_have_no_false_preference(self):
        body = self.body()
        body['alternatives'][1]['values'] = [200, 1]
        r = topsis(EvaluationInput(**body))
        self.assertEqual(r['weights'][1]['combined'], 0)
        self.assertFalse(r['weights'][1]['active'])
        body['alternatives'][1]['values'] = [100, 1]
        r = topsis(EvaluationInput(**body))
        self.assertEqual([a['rank'] for a in r['ranking']], [1, 1])
        self.assertEqual([a['score'] for a in r['ranking']], [.5, .5])
        self.assertTrue(all(w['combined'] == 0 for w in r['weights']))

    def test_tradeoff_tie_and_affine_unit_invariance(self):
        body = self.body()
        body['alternatives'][0]['values'] = [100, .8]
        body['alternatives'][1]['values'] = [200, 1]
        original = topsis(EvaluationInput(**body))
        self.assertEqual([r['rank'] for r in original['ranking']], [1, 1])
        self.assertAlmostEqual(original['ranking'][0]['score'], .5)
        for alternative in body['alternatives']:
            alternative['values'][0] = alternative['values'][0] * 10000 + 50
        converted = topsis(EvaluationInput(**body))
        self.assertEqual(original['normalized'], converted['normalized'])
        self.assertEqual(original['weights'], converted['weights'])

    def test_explicit_evidence_does_not_hide_failed_threshold(self):
        body = self.body()
        for a in body['alternatives']:
            a['checks'] = [{'name': n, 'status': 'passed', 'evidence': '外部测试报告'} for n in ['电压稳定', '频率稳定', '黑启动可行性']]
        r = topsis(EvaluationInput(**body))
        self.assertEqual(r['ranking'][0]['gate'], 'passed_as_supplied')
        self.assertEqual(r['ranking'][1]['gate'], 'failed')
        self.assertFalse(any(a['engineering_recommendation'] for a in r['ranking']))

    def test_api_validation_persistence_and_isolation(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'data').mkdir()
            with patch('backend.workspace.ROOT', root), patch('backend.effect_evaluation.ROOT', root):
                c = TestClient(app)
                p = c.post('/api/projects', json={'name': '评价隔离'}).json()
                other = c.post('/api/projects', json={'name': '另一工程'}).json()
                body = {**self.body(), 'project_id': p['id']}
                for change in ['missing', 'duplicate', 'overflow', 'missing_evidence']:
                    invalid = copy.deepcopy(body)
                    if change == 'missing':
                        invalid['alternatives'][0]['values'] = [100]
                    elif change == 'duplicate':
                        invalid['criteria'][1]['id'] = 'cost'
                    elif change == 'overflow':
                        invalid['alternatives'][0]['values'][0] = 1e300
                    else:
                        invalid['alternatives'][0]['checks'] = [{'name': '电压稳定', 'status': 'passed'}]
                    self.assertEqual(c.post('/api/effect-evaluations', json=invalid).status_code, 422, change)
                self.assertEqual(c.post('/api/effect-evaluations', json={**body, 'project_revision': 99}).status_code, 409)
                r = c.post('/api/effect-evaluations', json=body)
                self.assertEqual(r.status_code, 200, r.text)
                record = r.json()
                self.assertEqual(record['input_sha256'], canonical_sha(record['input']))
                self.assertEqual(c.get('/api/effect-evaluations/' + record['id']).json(), record)
                self.assertEqual(len(c.get('/api/effect-evaluations?project_id=' + p['id']).json()), 1)
                self.assertEqual(c.get('/api/effect-evaluations?project_id=' + other['id']).json(), [])


if __name__ == '__main__':
    unittest.main()
