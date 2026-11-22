import assert from 'node:assert/strict';
import {createServer} from 'vite';
import {createSSRApp,h,ref} from 'vue';
import {renderToString} from '@vue/server-renderer';
const server=await createServer({server:{middlewareMode:true},appType:'custom',optimizeDeps:{noDiscovery:true,include:[]}});
try{
 const {workspaces,resolveWorkspace}=await server.ssrLoadModule('/src/workspaceRegistry.ts');
 assert.equal(new Set(workspaces.map(w=>w.id)).size,workspaces.length);
 for(const section of ['模型与资源','计算任务','平衡结果','网络逐时结果','逐设备年度滚动'])assert.equal(resolveWorkspace('电力电量平衡',section).id,'balance.workspace');
 assert.equal(resolveWorkspace('数据管理','电网拓扑').id,'data.network');
 assert.equal(resolveWorkspace('保供场景生成','生产序列嵌入').id,'scenario.workspace');
 assert.equal(workspaces.filter(w=>w.stage==='场景生成').length,1);
 const {useCommands}=await server.ssrLoadModule('/src/commands.ts');
 let count=0,finish,errors=[];let enabled=true;
 const commands=useCommands([{id:'save',label:'保存',execute:()=>{count++;return new Promise(r=>finish=r)},enabled:()=>enabled},{id:'hidden',label:'隐藏',execute:()=>count++,visible:()=>false},{id:'fail',label:'失败',execute:()=>{throw Error('真实失败')}}],e=>errors.push(e));
 const saving=commands.execute('save');await commands.execute('save');assert.equal(count,1);finish();await saving;
 enabled=false;await commands.execute('save');await commands.execute('hidden');assert.equal(count,1);
 await commands.execute('fail');assert.match(errors[0],/真实失败/);assert.equal(commands.running.value.length,0);
 const {recordedCondition,balanceMetrics}=await server.ssrLoadModule('/src/balanceResultAdapter.ts');
 const {stageSignature}=await server.ssrLoadModule('/src/balanceInputContext.ts');
 assert.equal(stageSignature([],48,[2]),stageSignature([{name:'全时域',end_hour:48,grid_ratio:1,emergency_ratio:1,failed_lines:[2]}],48));
 assert.notEqual(stageSignature([],48),stageSignature([{name:'全时域',end_hour:48,grid_ratio:0,emergency_ratio:1,failed_lines:[]}],48));
 assert.equal(recordedCondition({scenario_id:'s'}),'工况未记录');assert.equal(recordedCondition({operating_condition:'normal'}),'常规运行');
 const cards=balanceMetrics({metrics:{max_power_deficit_kw:2000,expected_energy_deficit_kwh:5000,loss_of_load_probability:.25,max_curtailment_kw:NaN}});
 assert.equal(cards.length,6);assert.equal(cards[0].value,'25.000');assert.equal(cards[2].value,'2.000');assert.equal(cards[4].value,'5.000');assert.equal(cards[3].value,null);assert.equal(cards[5].value,null);
 const {useParameterTransaction}=await server.ssrLoadModule('/src/useParameterTransaction.ts');
 await renderToString(createSSRApp({setup(){
  const open=ref(false),parameters=ref({power:10,assets:[1]}),name=ref('original');
  const commit=useParameterTransaction(open,{parameters,name});
  open.value=true;parameters.value.power=20;parameters.value.assets.push(2);name.value='draft';open.value=false;
  assert.deepEqual(parameters.value,{power:10,assets:[1]});assert.equal(name.value,'original');
  open.value=true;const identity=parameters.value;open.value=false;assert.equal(parameters.value,identity);
  open.value=true;parameters.value.power=30;commit();assert.equal(open.value,false);assert.equal(parameters.value.power,30);
  open.value=true;parameters.value.power=40;commit(false);parameters.value.power=50;open.value=false;assert.equal(parameters.value.power,40);
  return()=>h('div','transaction-verified');
 }}));
 console.log('PASS: 稳定导航与旧入口兼容、单一工作区、命令防重入/禁用/隐藏/失败清理、工况不推断、指标单位及缺失值保真');
}finally{await server.close()}
