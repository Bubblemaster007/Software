"""Fixed worker entry point: never executes user-supplied scripts or paths."""
from datetime import datetime
import io,os,sys,traceback
from backend.native_jobs import ROOT,JOBS,read_job,update_job,process_identity

def run(id):
 record=read_job(id)
 if record['status'] not in ('queued','running'):raise ValueError('任务已结束')
 update_job(id,status='running',pid=os.getpid(),process_identity=process_identity(os.getpid()),started=datetime.now().isoformat(timespec='seconds'))
 sys.path.insert(0,str(ROOT/'vendor/topic2'))
 try:
  import pandas as pd
  from src.chapter3.current_paper_adapter import run_paper_downstream
  output=JOBS/id/'outputs';output.mkdir(parents=True,exist_ok=True)
  result=run_paper_downstream(pd.read_csv(io.StringIO(record['csv'])),record['config'],output,{'method':'platform imported source/load/weather; original topic2 downstream'})
  update_job(id,status='succeeded',completed=datetime.now().isoformat(timespec='seconds'),result=result)
 except Exception as e:
  traceback.print_exc();update_job(id,status='failed',completed=datetime.now().isoformat(timespec='seconds'),error=str(e))

if __name__=='__main__':run(sys.argv[1])
