"""Metadata and archive compatibility tests use an isolated database."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from backend import app as platform

class WorkspaceMetadataTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.path=Path(self.tmp.name)/'isolated.db'
  with closing(sqlite3.connect(self.path)) as c,c:c.execute('CREATE TABLE runs(id TEXT PRIMARY KEY,created TEXT,payload TEXT)')
  self.dbpatch=patch.object(platform,'db',lambda:sqlite3.connect(self.path));self.dbpatch.start()
  self.csv='timestamp,load_kw,wind_kw,pv_kw\n2023-01-01T00:00:00,100,20,0\n2023-01-01T01:00:00,120,15,0\n'
 def tearDown(self):self.dbpatch.stop();self.tmp.cleanup()
 def test_optional_condition_does_not_change_algorithm_output(self):
  old=platform.balance(platform.Request(parameters=platform.Parameters(),csv=self.csv))
  normal=platform.balance(platform.Request(parameters=platform.Parameters(),csv=self.csv,operating_condition='normal'))
  self.assertIsNone(old['operating_condition']);self.assertEqual(normal['operating_condition'],'normal')
  self.assertEqual(old['metrics'],normal['metrics']);self.assertEqual(old['rows'],normal['rows'])
  self.assertEqual(platform.get_run(normal['id'])['operating_condition'],'normal')
 def test_archive_filter_uses_recorded_condition_only(self):
  for condition in (None,'normal','extreme'):
   platform.balance(platform.Request(parameters=platform.Parameters(),csv=self.csv,operating_condition=condition))
  self.assertEqual(platform.run_archive_page(None,20,0)['total'],3)
  for condition in ('unknown','normal','extreme'):
   archive=platform.run_archive_page(None,20,0,operating_condition=condition)
   self.assertEqual(archive['total'],1)
   self.assertEqual(archive['items'][0]['operating_condition'],None if condition=='unknown' else condition)
 def test_strategy_retains_explicit_baseline_condition(self):
  base=platform.balance(platform.Request(parameters=platform.Parameters(),csv=self.csv,operating_condition='extreme'))
  checked=platform.evaluate_strategy(platform.StrategyEvaluation(source_run_id=base['id'],parameters=platform.Parameters()))
  self.assertEqual(platform.get_run(checked['run_id'])['operating_condition'],'extreme')
 def test_invalid_condition_is_rejected(self):
  with self.assertRaises(ValidationError):platform.Request(parameters=platform.Parameters(),csv=self.csv,operating_condition='invented')

if __name__=='__main__':unittest.main()

