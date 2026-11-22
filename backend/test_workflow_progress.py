import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from backend import workflow_progress as progress

class WorkflowProgressTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'data').mkdir()
  self.db=sqlite3.connect(self.root/'data/platform.db')
  self.db.executescript('CREATE TABLE projects(id TEXT,payload TEXT);CREATE TABLE study_jobs(id TEXT,project_id TEXT,created REAL,status TEXT,meta TEXT,input TEXT);CREATE TABLE runs(id TEXT,created TEXT,payload TEXT);CREATE TABLE scenarios(id TEXT,project_id TEXT);')
  self.state={'csv':'saved csv','model':'aggregate','parameters':{'grid_channel_kw':100}}
  self.db.execute('INSERT INTO projects VALUES(?,?)',('A',json.dumps({'id':'A','revision':4,'state':self.state})));self.db.commit()
  self.patch=patch.object(progress,'ROOT',self.root);self.patch.start()
 def tearDown(self):self.patch.stop();self.db.close();self.tmp.cleanup()
 def job(self,project='A',status='running',csv='saved csv'):
  frozen={'project':{'revision':3,'state':{**self.state,'csv':csv}}}
  self.db.execute('INSERT INTO study_jobs VALUES(?,?,?,?,?,?)',('task',project,1,status,json.dumps({'module':'investment'}),json.dumps(frozen)));self.db.commit()
 def test_status_from_real_project_and_no_queue_mutation(self):
  self.job();self.job('B','failed');before=self.db.total_changes;r=progress.snapshot('A')
  self.assertEqual(len(r['jobs']),1);self.assertEqual(r['jobs'][0]['status'],'running');self.assertTrue(r['jobs'][0]['matches_saved_input'])
  self.assertEqual(self.db.total_changes,before);self.assertEqual(self.db.execute('SELECT status FROM study_jobs WHERE project_id="A"').fetchone()[0],'running')
 def test_old_snapshot_detected_without_revision_only_false_positive(self):
  self.job(csv='old csv');self.assertFalse(progress.snapshot('A')['jobs'][0]['matches_saved_input'])
 def test_empty_project_and_missing_tables_are_not_completed(self):
  r=progress.snapshot('A');self.assertEqual(r['scenario_count'],0);self.assertEqual(r['source_study_count'],0);self.assertEqual(r['run_count'],0);self.assertEqual(r['jobs'],[])
 def test_archive_parameters_changed(self):
  run={'id':'run','project_id':'A','project_revision':2,'input_csv':'saved csv','model':'aggregate','parameters':{'grid_channel_kw':50}}
  self.db.execute('INSERT INTO runs VALUES(?,?,?)',('run','2026',json.dumps(run)));self.db.commit()
  r=progress.snapshot('A');self.assertEqual(r['run_count'],1);self.assertFalse(r['latest_run']['matches_saved_input'])
 def test_unknown_project(self):
  with self.assertRaises(HTTPException) as e:progress.snapshot('B')
  self.assertEqual(e.exception.status_code,404)
 def test_mixed_job_sources_sort_by_actual_time(self):
  self.job(status='succeeded')
  self.db.execute('CREATE TABLE native_jobs(id TEXT,project_id TEXT,created TEXT,payload TEXT)')
  record={'id':'new-native','status':'failed','created':'2026-11-22T12:00:00','csv':'saved csv'}
  self.db.execute('INSERT INTO native_jobs VALUES(?,?,?,?)',('new-native','A',record['created'],json.dumps(record)));self.db.commit()
  jobs=progress.snapshot('A')['jobs'];self.assertEqual(jobs[0]['id'],'new-native');self.assertGreater(jobs[0]['created_epoch'],jobs[1]['created_epoch'])
 def test_history_is_not_application(self):
  self.db.execute('INSERT INTO scenarios VALUES(?,?)',('old','A'));self.db.commit()
  self.assertEqual(progress.snapshot('A')['scenario_evidence']['state'],'generated')
 def test_applied_sequence_must_match_current_input(self):
  self.db.execute('CREATE TABLE production_sequences(id TEXT,project_id TEXT,payload TEXT)')
  self.db.execute('INSERT INTO production_sequences VALUES(?,?,?)',('seq','A',json.dumps({'csv':'old csv'})))
  self.state['productionSequenceId']='seq';self.db.execute('UPDATE projects SET payload=? WHERE id=?',(json.dumps({'id':'A','revision':4,'state':self.state}),'A'));self.db.commit()
  self.assertEqual(progress.snapshot('A')['scenario_evidence']['state'],'stale')
  self.db.execute('UPDATE production_sequences SET payload=?',(json.dumps({'csv':'saved csv'}),));self.db.commit()
  self.assertEqual(progress.snapshot('A')['scenario_evidence']['state'],'applied')

if __name__=='__main__':unittest.main()
