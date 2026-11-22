import {inspectTimeSeries} from './timeSeries';
export type FaultMode='none'|'manual'|'random';
export interface ScenarioDraft {name:string;condition:'常规运行'|'极端保供';conditionConfirmed:boolean;backgroundCsv:string;inputCsv:string;source:any;eventCsv:string;eventMode:'none'|'generate'|'existing';faultMode:FaultMode;faultTiming:'full'|'stages';failedLines:number[];stages:any[];scenario:any;productionId:string|null;productionCsv:string;embeddedScenarioId:string|null;upstream:string;step:string;}
export function csvSignature(value:string){let hash=2166136261;for(let i=0;i<value.length;i++){hash^=value.charCodeAt(i);hash=Math.imul(hash,16777619)}return (hash>>>0).toString(16)}
export function configurationSnapshot(input:any){return {csvSignature:csvSignature(input.csv),network:input.network||null,condition:input.condition,scenarioId:input.scenarioId||null,productionId:input.productionId||null,failedLines:input.failedLines||[],stages:input.stages||[]}}
export function configurationMatches(config:any,input:any){return !!config&&JSON.stringify(config.snapshot)===JSON.stringify(configurationSnapshot(input))}
export function scenarioSteps(condition:string){return condition==='常规运行'?[{id:'background',label:'背景时序'},{id:'confirm',label:'场景确认'}]:[{id:'background',label:'背景时序'},{id:'event',label:'极端事件'},{id:'fault',label:'故障设置'},{id:'embed',label:'场景嵌入'},{id:'confirm',label:'场景确认'}]}
export function validateScenarioDraft(d:ScenarioDraft,network:any):{step:string;message:string}[]{
 const issues:{step:string;message:string}[]=[];const fail=(step:string,message:string)=>issues.push({step,message});
 const check=inspectTimeSeries(d.inputCsv);if(check.totalIssues)fail('background','源荷数据：'+check.issues[0]?.message);
 if(!d.name.trim())fail('confirm','请填写场景名称');if(!d.conditionConfirmed)fail('background','旧工程未记录工况，请明确选择并确认运行工况');
 if(d.eventMode!=='none'&&!d.eventCsv)fail('event','已选择极端事件，但尚未选用事件片段');
 if(d.productionId&&d.productionCsv!==d.inputCsv)fail('embed','生产序列与当前草稿不一致，请重新选用或跳过嵌入');
 if(d.productionId&&d.embeddedScenarioId&&(d.faultMode!=='random'||d.scenario?.id!==d.embeddedScenarioId))fail('embed','耦合生产序列必须使用其绑定随机场景，不能同时选择其他故障方式；请跳过或重新构建序列');
 if(d.condition==='常规运行'&&(d.faultMode!=='none'||d.eventMode!=='none'||d.productionId))fail('confirm','常规运行不能携带当前极端事件、故障或嵌入引用；请重置草稿或切回极端保供');
 if(d.faultMode==='manual'){
  if(!network)fail('fault','请先导入真实网架，或明确载入IEEE33示例');
  if(check.count>168)fail('fault','节点网络线路故障计算限168小时，请在数据准备选择连续窗口');
  const available=new Set((network?.lines||[]).filter((l:any)=>l.status===1).map((l:any)=>l.line));
  const validateLines=(ids:number[])=>{if(new Set(ids).size!==ids.length||ids.some(id=>!available.has(id)))fail('fault','故障线路重复、已停运或不属于当前网架')};
  if(d.faultTiming==='full'){validateLines(d.failedLines);if(!d.failedLines.length)fail('fault','请选择至少一条故障线路，或选择无设备故障')}
  else {let end=0;const names=new Set();let failures=0;if(!d.stages.length)fail('fault','请配置故障与恢复阶段');for(const s of d.stages){validateLines(s.failed_lines||[]);failures+=(s.failed_lines||[]).length;if(!s.name?.trim()||names.has(s.name.trim())||!Number.isInteger(s.end_hour)||s.end_hour<=end)fail('fault','阶段名称须唯一，结束小时须严格递增');names.add(s.name?.trim());end=s.end_hour;if([s.grid_ratio,s.emergency_ratio].some(v=>typeof v!=='number'||v<0||v>1))fail('fault','阶段资源比例须为0–1')}if(end!==check.count)fail('fault','末阶段必须覆盖完整输入时序');if(!failures)fail('fault','尚未设置阶段线路故障，或改为无设备故障')}
 }
 if(d.faultMode==='random'){
  if(!d.scenario?.id)fail('fault','请生成或载入并选用随机故障场景');
  else {const times=d.inputCsv.trim().split(/\r?\n/).slice(1).map(r=>new Date(r.split(',')[0].replace(' ','T')).getTime());const actual=(d.scenario.capacity||[]).map((r:any)=>new Date(r.timestamp.replace(' ','T')).getTime());if(times.length!==actual.length||times.some((v,i)=>v!==actual[i]))fail('fault','随机故障与最终输入时间轴不一致；需要匹配场景或使用耦合嵌入序列')}
 }
 return issues;
}
