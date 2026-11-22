const fs=require('fs');const p='C:/Users/13411/Desktop/software/frontend/src/App.vue';let s=fs.readFileSync(p,'utf8');
const start=s.indexOf('async function load(id:string)');const end=s.indexOf('async function upload(',start);if(start<0||end<0)throw Error('load anchor');
s=s.slice(0,start)+`let archiveRead=0;
async function load(id:string){const request=++archiveRead;const projectId=project.value?.id;error.value='';try{const loaded=await api('/api/runs/'+id);if(request!==archiveRead||project.value?.id!==projectId)return;if(loaded.project_id&&loaded.project_id!==projectId)throw Error('该档案不属于当前工程');result.value=loaded;stageSnapshot.value=JSON.stringify(loaded.stages||[]);active.value='电力电量平衡';subsection.value='平衡结果';balanceMode.value='汇总／网络平衡';projectMessage.value='已读取档案 '+id.slice(0,8)+'，当前工程输入未被覆盖';await draw()}catch(e){if(request===archiveRead&&project.value?.id===projectId)error.value=String(e)}}
`+s.slice(end);
s=s.replace("async function refresh(){history.value=await api('/api/runs'+(project.value?'?project_id='+project.value.id:''))}","async function refresh(){const id=project.value?.id;const records=await api('/api/runs'+(id?'?project_id='+id:''));if(project.value?.id===id)history.value=records}");
s=s.replace("busy.value=true;error.value='';result.value=null;try{await saveProject();result.value=await api('/api/balance'", "busy.value=true;error.value='';const submittedProject=project.value?.id;try{await saveProject();const calculated=await api('/api/balance'");
s=s.replace("});stageSnapshot.value=JSON.stringify(stages.value);await refresh();await draw()}catch(e)", "});if(project.value?.id!==submittedProject)return;result.value=calculated;stageSnapshot.value=JSON.stringify(stages.value);await refresh();if(active.value==='电力电量平衡'&&subsection.value==='计算任务')subsection.value='平衡结果';projectMessage.value='计算完成并已归档 · '+calculated.id;await draw()}catch(e)");
s=s.replace("if(menu==='保供能力提升') return ['选择基准','策略库','资源调整','复算','效果对比','保存方案'];", "if(menu==='保供能力提升') return ['策略库','资源调整','效果对比'];");
s=s.replace("if(menu==='源储协同配置') return ['候选资源','目标与约束','规划阶段','配置方式','优化运行','配置结果'];", "if(menu==='源储协同配置') return ['候选资源','目标与约束','规划阶段','配置结果'];");
s=s.replace("if(menu==='方案与报告') return ['打开档案','方案对比','质效评价','导出报告','归档'];", "if(menu==='方案与报告') return ['打开档案','方案对比','质效评价'];");
s=s.replace("if(tool==='分析设置'&&['承灾极限分析','离网稳定判别','黑启动路径优化'].includes(active.value)){projectMessage.value='当前页面已处于分析设置，请按需打开参数面板';return}","if(tool==='分析设置'&&['承灾极限分析','离网稳定判别','黑启动路径优化'].includes(active.value)){navigateSection(active.value,active.value==='离网稳定判别'?'判别对象':active.value==='黑启动路径优化'?'恢复分区':'分析设置');return}");
s=s.replace("return ['工程信息','任务中心'];", "return ['任务中心','保存工程'];");
fs.writeFileSync(p,s);console.log('Archive reading and task navigation repaired');
