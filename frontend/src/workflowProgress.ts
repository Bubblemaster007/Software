export type ProgressState={label:string;tone:string;detail:string};
const status=(label:string,tone:string,detail:string):ProgressState=>({label,tone,detail});
export function taskProgress(jobs:any[]):ProgressState|null{
 jobs=[...jobs].sort((a,b)=>(b.created_epoch??(typeof b.created==='number'?b.created:Date.parse(b.created)/1000||0))-(a.created_epoch??(typeof a.created==='number'?a.created:Date.parse(a.created)/1000||0)));
 const active=jobs.find(j=>j.status==='running')||jobs.find(j=>j.status==='cancel_requested')||jobs.find(j=>j.status==='queued');
 if(active)return status(active.status==='queued'?'排队中':active.status==='cancel_requested'?'取消中':'计算中','running',`任务 ${active.id} · ${active.progress?.phase||active.status}`);
 const latest=jobs[0];if(!latest)return null;
 if(latest.status==='failed')return status('计算失败','failed',`任务 ${latest.id} 执行失败，可在任务中心查看原因`);
 if(['incomplete','cancelled','interrupted'].includes(latest.status))return status(latest.status==='incomplete'?'未完整':latest.status==='cancelled'?'已取消':'已中断','warning',`任务 ${latest.id} 未形成完整结果`);
 if(['succeeded','completed','complete'].includes(latest.status))return latest.matches_saved_input===false?status('待复算','warning',`已有任务 ${latest.id}，但对应旧输入；请核对冻结快照`):status('已完成','done',`任务 ${latest.id} 已结束；不代表可行性或算法验收通过`);
 return status('未完成','pending','尚无已完成任务');
}
export function workflowStatuses(input:{snapshot:any;ready:boolean;error:boolean;dataReady:boolean;dataSaved:boolean;dirty:boolean;working:Record<string,boolean>}){
 const {snapshot:s,ready,error,dataReady,dataSaved,dirty,working}=input;
 const result:Record<string,ProgressState>={};
 result['数据准备']=!dataReady?status('未完成','pending','请完成连续源荷录入与当前模型所需网络准备'):!dataSaved?status('待保存','warning','当前源荷或网络有未保存修改'):status('已完成','done','源荷格式与网络输入已准备并保存；不替代设备参数和算法校核');
 const pending=status('未完成','pending','本工程尚无相应产物');
 for(const group of ['场景生成','平衡分析','保供优化','成果管理'])result[group]=!ready?status(error?'状态未知':'读取中',error?'warning':'pending',error?'进度读取失败，稍后自动重试':'正在读取当前工程的真实记录'):pending;
 if(ready&&s){
  const scenario=s.scenario_evidence?.state;
  result['场景生成']=scenario==='applied'?status('已应用','done','当前已保存场景/生产序列引用属于本工程且与当前时间轴或时序匹配'):scenario==='stale'?status('待重新生成','warning','当前引用缺失或时间轴/序列已变化，请重新核对并明确应用'):(s.scenario_count+s.source_study_count+s.production_count)>0?status('已生成待应用','warning','存在历史产物，但当前工程未引用已验证的场景或生产序列'):status('待生成','pending','常规运行可直接使用历史源荷，不强制生成故障');
  const balanceJobs=s.jobs.filter((j:any)=>['device_dispatch','annual_dispatch','native'].includes(j.module));const activeBalance=balanceJobs.some((j:any)=>['queued','running','cancel_requested'].includes(j.status));
  result['平衡分析']=(activeBalance||!s.latest_run?.created_epoch||balanceJobs[0]?.created_epoch>=s.latest_run.created_epoch?taskProgress(balanceJobs):null)||(s.run_count?status(s.latest_run?.matches_saved_input===false?'待复算':'已完成',s.latest_run?.matches_saved_input===false?'warning':'done',`已归档${s.run_count}次平衡；最近任务 ${s.latest_run?.id}，工程版本${s.latest_run?.project_revision??'未记录'}`):pending);
  result['保供优化']=taskProgress(s.jobs.filter((j:any)=>['investment','investment_experiments'].includes(j.module)))||(s.adjustment_count?status('已完成','done',`已归档${s.adjustment_count}次策略调整复算`):pending);
  const artifacts=s.run_count+s.jobs.filter((j:any)=>j.status==='succeeded').length;
  result['成果管理']=artifacts?status('已完成','done',`已有${artifacts}项计算成果归档，可查看与导出；不代表交付验收完成`):pending;
  if(dirty&&scenario==='applied')result['场景生成']=status('待核对','warning','当前输入已有修改，已保存引用仍对应原状态；请核对后保存或重新生成');
  if(dirty){for(const group of ['平衡分析','保供优化'])if(result[group].tone==='done')result[group]=status('待复算','warning','工程输入已修改；已有结果仍属于原任务快照')}
 }
 if(working.scenario)result['场景生成']=status('计算中','running','正在生成场景，成功保存后更新状态');
 if(working.balance)result['平衡分析']=status('计算中','running','正在提交或计算当前工程平衡任务');
 if(working.optimization)result['保供优化']=status('计算中','running','正在执行策略调整复算');
 return result;
}
