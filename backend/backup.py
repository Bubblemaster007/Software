"""Consistent offline backup of the saved local database."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import hashlib,io,json,sqlite3,tempfile,zipfile

def create_backup(source:Path):
 if not source.is_file():raise FileNotFoundError('本地数据库尚未建立，请先保存工程')
 with tempfile.TemporaryDirectory(prefix='power-backup-') as folder:
  target=Path(folder)/'platform.db'
  with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as original,closing(sqlite3.connect(target)) as snapshot:
   original.backup(snapshot)
   check=snapshot.execute('PRAGMA integrity_check').fetchone()[0]
   if check!='ok':raise ValueError('数据库完整性检查未通过')
   names=[row[0] for row in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
   counts={name:snapshot.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in names}
  content=target.read_bytes()
 manifest={'format':'terminal-power-platform.sqlite-backup','version':1,'created':datetime.now().isoformat(timespec='seconds'),'database':'platform.db','sha256':hashlib.sha256(content).hexdigest(),'integrity_check':check,'table_counts':counts,'scope':'全部已保存工程、场景、生产序列、计算和草稿；不含浏览器未保存修改、软件代码、Python环境、外部原始文件与data/native_jobs原生任务产物（须另下载任务ZIP）'}
 guide="""# 本地数据备份恢复说明

此包包含platform.db、manifest.json及本说明。数据库使用SQLite在线备份接口生成，并通过完整性检查；可在服务运行时下载。

恢复前请关闭软件并停止本地8765端口对应的本软件服务，另行备份当前data/platform.db。核对manifest.json记录的数据库SHA256后，将包内platform.db放到软件目录的data/platform.db，再启动软件。

恢复会将整个本地数据库回到备份时点，包含全部工程。不要在服务运行时直接覆盖数据库。当前未提供界面内自动恢复功能。

本包不包含未保存的浏览器修改、软件源代码、依赖环境及外部原始文件。迁移电脑还需另行保留软件目录和运行环境。
"""
 output=io.BytesIO()
 with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
  archive.writestr('platform.db',content);archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2));archive.writestr('恢复说明.md',guide)
 return output.getvalue(),manifest
