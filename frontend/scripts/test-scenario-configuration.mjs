import {createServer} from 'vite';import assert from 'node:assert/strict';import {ref,nextTick,effectScope,computed} from 'vue';
const server=await createServer({server:{middlewareMode:true},appType:'custom',optimizeDeps:{noDiscovery:true,include:[]}});
try{
 const {useScenarioConfiguration}=await server.ssrLoadModule('/src/useScenarioConfiguration.ts');
 const {validateScenarioDraft,configurationMatches,scenarioSteps}=await server.ssrLoadModule('/src/scenarioConfiguration.ts');
 const csv='timestamp,load_kw,wind_kw,pv_kw\n2023-01-01 00:00:00,100,20,0\n2023-01-01 01:00:00,100,20,0\n';
 const network={nodes:[{node:1},{node:7}],lines:[{line:300,from_node:1,to_node:7,status:1}]};let navigation=[],calculations=0;
 const c={};for(const [k,v] of Object.entries({project:{id:'A',state:{}},csv,customNetwork:network,operatingCondition:'常规运行',scenarioId:null,activeProductionId:null,faultSelection:[],stages:[],sourceImport:{name:'历史输入'},productionId:null,productionCsv:'',failedLines:'',model:'aggregate',balanceMode:'汇总／网络平衡',projectMessage:''}))c[k]=ref(v);
 c.faultSelection=computed({get:()=>c.failedLines.value.split(',').filter(Boolean).map(Number),set:v=>c.failedLines.value=v.join(',')});c.navigateWorkspace=id=>navigation.push(id);c.run=()=>calculations++;
 const scope=effectScope();const scene=scope.run(()=>useScenarioConfiguration(c));scene.ensure();assert.equal(scenarioSteps('常规运行').length,2);assert.equal(scenarioSteps('极端保供').length,5);
 const original=c.csv.value;scene.selectBackground(csv.replace('100,20','110,20'));assert.equal(c.csv.value,original);assert.equal(navigation.length,0);
 scene.reset();assert.equal(scene.confirm(),true);assert.equal(navigation.at(-1),'balance.workspace');assert.equal(calculations,0);assert.equal(scene.valid.value,true);
 scene.reset();scene.draft.value.condition='极端保供';scene.draft.value.faultMode='manual';scene.draft.value.failedLines=[300];assert.equal(scene.confirm(),true);assert.equal(c.failedLines.value,'300');assert.equal(c.model.value,'case33');assert.equal(c.stages.value.length,0);
 scene.reset();scene.draft.value.faultTiming='stages';scene.draft.value.stages=[{name:'故障',end_hour:1,grid_ratio:1,emergency_ratio:1,failed_lines:[300]},{name:'恢复',end_hour:2,grid_ratio:1,emergency_ratio:1,failed_lines:[]}];assert.equal(scene.confirm(),true);assert.equal(c.failedLines.value,'');assert.equal(c.stages.value[0].failed_lines[0],300);assert.equal(c.stages.value[1].failed_lines.length,0);
 c.csv.value=csv.replace('100,20','111,20');assert.equal(scene.valid.value,false);assert.ok(scene.confirmed.value);scene.reset();scene.draft.value.failedLines=[999];scene.draft.value.faultTiming='full';assert.ok(scene.issues.value.some(v=>v.message.includes('网架')));assert.equal(scene.confirm(),false);assert.equal(scene.draft.value.step,'fault');
 scene.draft.value.failedLines=[300,300];assert.ok(validateScenarioDraft(scene.draft.value,network).length);
 c.project.value={id:'B',state:{}};await nextTick();assert.equal(scene.draft.value,null);assert.equal(scene.confirmed.value,null);assert.equal(scene.libraryOpen.value,false);
 scope.stop();console.log('PASS: A常规/手动线路/分阶段恢复、草稿不写工程、确认不计算、旧结果引用保留、越界故障阻断、工程隔离、动态步骤');
}finally{await server.close()}

