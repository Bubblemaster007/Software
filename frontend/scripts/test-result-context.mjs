import assert from 'node:assert/strict';
import {createServer} from 'vite';
import {createSSRApp,h} from 'vue';
import {renderToString} from '@vue/server-renderer';
const server=await createServer({server:{middlewareMode:true},appType:'custom',optimizeDeps:{noDiscovery:true,include:[]}});
try{
 const {beginWorkflowActivity,workflowActivity}=await server.ssrLoadModule('/src/workflowActivity.ts');
 const finishA=beginWorkflowActivity('project-a','balance'),finishB=beginWorkflowActivity('project-b','balance');
 assert.equal(workflowActivity.value['project-a:balance'],1);assert.equal(workflowActivity.value['project-b:balance'],1);
 finishA();finishA();assert.equal(workflowActivity.value['project-a:balance'],0);assert.equal(workflowActivity.value['project-b:balance'],1);finishB();
 const Result=(await server.ssrLoadModule('/src/ResultOverview.vue')).default;
 const Scenario=(await server.ssrLoadModule('/src/ScenarioDashboard.vue')).default;
 const result={id:'audit-task',model:'aggregate',project_revision:7,metrics:{loss_of_load_probability:.25,max_power_deficit_kw:2000,expected_energy_deficit_kwh:5000},rows:[{timestamp:'2026-01-01T00:00',load_kw:1000,load_served_kw:500,soc:.8},{timestamp:'2026-01-01T01:00',load_kw:2000,load_served_kw:1000,soc:.6}]};
 const html=await renderToString(createSSRApp({render:()=>h(Result,{result})}));
 assert.match(html,/25\.000/);assert.match(html,/2\.000/);assert.match(html,/5\.000/);
 assert.match(html,/缺供时段占比/);assert.match(html,/累计缺供电量/);
 assert.doesNotMatch(html,/电力不足概率|电量不足期望值/);
 assert.doesNotMatch(html,/>网络结果</);assert.match(html,/弃电电力极大值/);assert.match(html,/未计算/);
 const scenarioHtml=await renderToString(createSSRApp({render:()=>h(Scenario,{csv:'timestamp,load_kw,wind_kw,pv_kw\n2026-01-01T00:00,100,20,0',condition:'极端保供',eventCsv:'',scenario:{id:'fault-7',name:'已保存的故障场景',states:[]}})}));
 assert.match(scenarioHtml,/尚未选定/);assert.match(scenarioHtml,/已保存的故障场景/);assert.match(scenarioHtml,/fault-7/);
 assert.match(scenarioHtml,/当前任务未输出对应数据/);
 console.log('PASS: 真实结果单位转换、缺失字段明确未计算、单轨迹口径、无网络结果不显示网络标签、极端片段空状态、所选场景标识（Vue SSR）');
}finally{await server.close()}
