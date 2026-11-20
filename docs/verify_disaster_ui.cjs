// Reproducible artificial two-node study, never presented as regional observations.
const assert=require('node:assert/strict');const fs=require('node:fs');
const {chromium}=require('C:/Users/13411/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const root=process.env.DEVICE_STUDY_URL||'http://127.0.0.1:8769';
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1600,height:1050}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function json(response){assert(response.ok(),await response.text());return response.json()}
 async function awaitTerminal(id){for(let i=0;i<100;i++){const j=await json(await page.request.get(root+'/api/study-jobs/'+id+'?include_input=true&include_result=true'));if(['succeeded','incomplete','failed','cancelled','interrupted'].includes(j.status))return j;await page.waitForTimeout(250)}throw Error('Worker did not reach terminal state within observation window')}
 let cancellationProbeId=null;
 try{
  const network={name:'承灾扫描两节点人工算例',source:'人工联调，非地区实测',nodes:[{node:1,pd_kw:0},{node:2,pd_kw:100}],lines:[{line:7,from_node:1,to_node:2,r_ohm:0,x_ohm:0,status:1,capacity_kva:200}]};
  const p=await json(await page.request.post(root+'/api/projects',{data:{name:'承灾与薄弱性人工验证',kind:'乡镇级',state:{network}}}));
  const e=await json(await page.request.get(root+'/api/engineering/projects/'+p.id));e.inventory.loads=[{id:'L',name:'人工医院负荷',node:2,peak_kw:100,target_hours:4,load_class:'基本保障'}];
  await json(await page.request.put(root+'/api/engineering/projects/'+p.id,{data:{project_revision:1,expected_revision:0,inventory:e.inventory}}));
  await page.addInitScript(id=>localStorage.setItem('terminal-power.last-project',id),p.id);await page.goto(root);
  await page.getByText('当前工程：承灾与薄弱性人工验证 · 版本 1',{exact:true}).waitFor();
  await page.getByRole('button',{name:'04承灾极限分析',exact:true}).click();await page.getByText(/工程版本 1 \/ 台账版本 1/).waitFor();
  await page.getByLabel('总步数',{exact:true}).fill('4');await page.getByLabel('扫描强度',{exact:true}).fill('0,1');
  await page.getByLabel('事件时长 / h',{exact:true}).fill('1,2');await page.getByLabel('外部供电 / kW',{exact:true}).fill('100');
  await page.getByLabel('每个工况样本数',{exact:true}).fill('2');await page.getByRole('combobox',{name:/成功判据/}).selectOption('energy_budget');
  await page.getByRole('combobox',{name:/判定方法/}).selectOption('empirical');
  const row=page.locator('tbody tr').first();await row.locator('select').selectOption('line:7');
  await row.locator('td').nth(3).locator('input').fill('1');await row.locator('td').nth(5).locator('input').fill('1');
  await row.locator('input[type=checkbox]').check();
  const submitted=page.waitForResponse(r=>r.url().endsWith('/api/study-jobs')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'冻结输入并提交后台扫描',exact:true}).click();const created=await json(await submitted);
  const job=await awaitTerminal(created.id);assert.equal(job.status,'succeeded',job.error);assert.equal(job.result.completed_solves,10);
  assert(Math.abs(job.result.weakness[0].mean_avoided_unsupplied_kwh-200)<1e-4);
  assert.deepEqual(job.result.cases.map(c=>c.judgement),['passed','failed','passed','failed']);
  assert(job.input.runtime.build_id);assert(job.process_identity);assert(job.result.worst_trace.rows.length===4);
  await page.getByRole('heading',{name:'已测承灾边界',exact:true}).waitFor();
  await page.getByRole('button',{name:'承灾边界',exact:true}).click();await page.getByRole('heading',{name:'承灾极限分析 · 承灾边界',exact:true}).waitFor();
  await page.screenshot({path:'docs/承灾强度时长扫描验证.png',fullPage:true});
  await page.getByRole('button',{name:'薄弱环节',exact:true}).click();await page.getByText('line:7',{exact:true}).first().waitFor();
  await page.screenshot({path:'docs/设备薄弱性配对验证.png',fullPage:true});
  const csv=await page.request.get(root+'/api/study-jobs/'+created.id+'/csv');assert.equal((await csv.text()).trim().split(/\r?\n/).length,11);
  fs.writeFileSync('docs/承灾扫描人工联调.json',JSON.stringify(job,null,2));
  await page.reload();await page.getByText('当前工程：承灾与薄弱性人工验证 · 版本 1',{exact:true}).waitFor();
  await page.getByRole('button',{name:'04承灾极限分析',exact:true}).click();await page.getByRole('heading',{name:'已测承灾边界',exact:true}).waitFor();
  await page.getByRole('button',{name:'11系统与接口',exact:true}).click();await page.getByRole('button',{name:'计算任务',exact:true}).click();
  await page.getByRole('button',{name:'查看',exact:true}).first().click();await page.getByText(/承灾扫描完成 10 \/ 10 次/).waitFor();
  await page.screenshot({path:'docs/统一研究任务与档案验证.png',fullPage:true});
  // Test the real process cancellation path with a sufficiently large queue workload.
  const params=structuredClone(job.input.parameters);params.samples=500;params.weakness_targets=[];params.intensities=[0,1,2,3,4];params.durations_hours=[1,2];
  const long=await json(await page.request.post(root+'/api/study-jobs',{data:{module:'disaster_scan',parameters:params}}));cancellationProbeId=long.id;
  let running=false;const runningDeadline=Date.now()+60000;while(Date.now()<runningDeadline){const state=await json(await page.request.get(root+'/api/study-jobs/'+long.id));if(state.status==='running'&&(state.progress?.completed||0)>0){running=true;break}if(['failed','succeeded','incomplete','interrupted'].includes(state.status))throw Error('Long task ended before running-cancel test: '+JSON.stringify(state));await page.waitForTimeout(100)}assert(running,'No live computation observed before cancellation');
  await json(await page.request.post(root+'/api/study-jobs/'+long.id+'/cancel'));
  const stopped=await awaitTerminal(long.id);assert.equal(stopped.status,'cancelled');assert.equal(stopped.result,null);
  // Use the actual device UI's new asynchronous action as well.
  await page.getByRole('button',{name:'05电力电量平衡',exact:true}).click();await page.getByRole('button',{name:'逐设备时序调度',exact:true}).click();
  await page.getByText(/台账版本 1 · 电源0/).waitFor();await page.getByLabel('计算步数',{exact:true}).fill('4');
  const bg=page.waitForResponse(r=>r.url().endsWith('/api/study-jobs')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'按当前输入提交后台调度',exact:true}).click();const device=await json(await bg);const solved=await awaitTerminal(device.id);
  assert.equal(solved.status,'succeeded',solved.error);assert(Math.abs(solved.result.metrics.total_unsupplied_energy_kwh-400)<1e-4);
  assert.equal(errors.length,0,errors.join('\n'));
  console.log('PASS: actual worker, 10 MILPs, 100/200 kWh outages, 200 kWh paired mitigation, CSV/JSON/history, task manager, cancellation and device background UI.');
 }catch(e){console.error((await page.locator('body').innerText()).slice(-5000));throw e}finally{
  if(cancellationProbeId){
   try{
    const probe=await json(await page.request.get(root+'/api/study-jobs/'+cancellationProbeId));
    if(!['succeeded','incomplete','failed','cancelled','interrupted'].includes(probe.status)){
     await json(await page.request.post(root+'/api/study-jobs/'+cancellationProbeId+'/cancel'));
     await awaitTerminal(cancellationProbeId);
    }
   }catch(cleanupError){console.error('Cancellation probe cleanup:',cleanupError)}
  }
  await browser.close()
 }
})().catch(e=>{console.error(e);process.exit(1)});
