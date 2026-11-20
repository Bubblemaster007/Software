from contextlib import closing
from pathlib import Path
import hashlib,io,json,sqlite3,tempfile,unittest,zipfile
from backend.backup import create_backup
class BackupTests(unittest.TestCase):
 def test_saved_state_consistent_and_restorable(self):
  with tempfile.TemporaryDirectory() as folder:
   source=Path(folder)/'source.db'
   with closing(sqlite3.connect(source)) as connection:
    connection.execute('CREATE TABLE projects(id TEXT,payload TEXT)');connection.execute('INSERT INTO projects VALUES(?,?)',('one','已保存工程'));connection.commit()
    # Uncommitted changes must not leak into a snapshot from another connection.
    connection.execute('INSERT INTO projects VALUES(?,?)',('two','未提交'))
    content,manifest=create_backup(source)
    connection.rollback()
   with zipfile.ZipFile(io.BytesIO(content)) as archive:
    data=archive.read('platform.db');saved=json.loads(archive.read('manifest.json'))
    self.assertEqual(hashlib.sha256(data).hexdigest(),saved['sha256']);self.assertEqual(saved['table_counts'],{'projects':1});self.assertIn('恢复说明.md',archive.namelist())
    target=Path(folder)/'restored.db';target.write_bytes(data)
   with closing(sqlite3.connect(target)) as restored:
    self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    self.assertEqual(restored.execute('SELECT * FROM projects').fetchall(),[('one','已保存工程')])
 def test_missing_database_does_not_create_empty_file(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'missing.db'
   with self.assertRaises(FileNotFoundError):create_backup(path)
   self.assertFalse(path.exists())
if __name__=='__main__':unittest.main()
