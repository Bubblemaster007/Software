// Artificial two-year catalogue investment; held-out source failure must stay failed.
const fs=require('node:fs');const assert=require('node:assert/strict');
const {chromium}=require('C:/Users/13411/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const root=process.env.DEVICE_STUDY_URL||'http://127.0.0.1:8773';const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1600,height:1050}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function json(r){assert(r.ok(),await r.text());return r.json()}
 async function terminal(id){for(let i=0;i<150;i++){const d=await json(await page.request.get(root+'/api/study-jobs/'+id+'?include_input=true&include_result=true'));if(['succeeded','incomplete','failed','cancelled','interrupted'].includes(d.status))return d;await page.waitForTimeout(200)}throw Error('Observed task did not finish within UI test window')}
 try{
  const network={name:'跨期配置两节点人工网络',source:'人工验证，非地区实测',base_voltage_kv:10,nodes:[{node:1,pd_kw:0},{node:2,pd_kw:10}],lines:[{line:7,from_node:1,to_node:2,r_ohm:0,x_ohm:0,status:1,capacity_kva:100}]};
  const p=await json(await page.request.post(root+'/api/projects',{data:{name:'跨期机会约束配置人工验证',kind:'乡镇级',state:{network}}}));
  const e=await json(await page.request.get(root+'/api/engineering/projects/'+p.id));
  e.inventory.loads=[{id:'L',name:'医院（人工）',node:2,peak_kw:10,target_hours:2,load_class:'基本保障'}];
  e.inventory.sources=[{id:'D',name:'未建设柴油候选（人工）',node:2,kind:'柴油机',rated_kw:10,existing:false,fuel_kwh:100,grid_forming:true,black_start:true}];
  await json(await page.request.put(root+'/api/engineering/projects/'+p.id,{data:{project_revision:1,expected_revision:0,inventory:e.inventory}}));
  await page.addInitScript(id=>localStorage.setItem('terminal-power.last-project',id),p.id);await page.goto(root);
  await page.getByText('当前工程：跨期机会约束配置人工验证 · 版本 1',{exact:true}).waitFor();await page.getByRole('button',{name:'07源储协同配置',exact:true}).click();
  await page.getByText(/工程版本 1 \/ 台账版本 1/).waitFor();await page.getByRole('checkbox',{name:'选择 D',exact:true}).check();
  await page.getByRole('button',{name:'提交多阶段机会约束配置',exact:true}).click();await page.getByText(/请明确填写所选候选的投资成本/).waitFor();
  await page.getByRole('spinbutton',{name:'D 投资成本 元',exact:true}).fill('100');await page.getByRole('spinbutton',{name:'D 寿命 年',exact:true}).fill('10');
  await page.getByRole('button',{name:'目标与约束',exact:true}).click();await page.getByLabel('事件计算步数',{exact:true}).fill('2');
  await page.getByRole('combobox',{name:/联合范围/}).selectOption('all_periods');
  await page.getByLabel('训练场景 JSON',{exact:true}).fill(JSON.stringify([{id:'path',weight:1,grid_available_kw:[20],stage_overrides:{2027:{grid_available_kw:[0]}},provenance:'人工跨期轨迹'}]));
  await page.getByLabel('独立样本外验证 JSON',{exact:true}).fill(JSON.stringify([{id:'holdout',weight:1,grid_available_kw:[5],device_availability:{D:[0]},provenance:'人工样本外机组失效'}]));
  await page.getByRole('button',{name:'规划阶段',exact:true}).click();let row=page.locator('table tr').nth(1);await row.locator('td').nth(3).locator('input').fill('0');await row.locator('td').nth(5).locator('input').fill('0');
  await page.getByRole('button',{name:'增加建设阶段',exact:true}).click();row=page.locator('table tr').nth(2);await row.locator('td').nth(3).locator('input').fill('100');await row.locator('td').nth(5).locator('input').fill('0');
  const submitted=page.waitForResponse(r=>r.url().endsWith('/api/study-jobs')&&r.request().method()==='POST');await page.getByRole('button',{name:'提交多阶段机会约束配置',exact:true}).click();const created=await json(await submitted);const record=await terminal(created.id);
  assert.equal(record.status,'succeeded',record.error);const r=record.result;assert.equal(r.status,'complete');assert.equal(r.selected_assets.length,1);
  assert.equal(r.selected_assets[0].commission_year,2027);assert.equal(r.selected_assets[0].retirement_year,2037);assert(Math.abs(r.objective_yuan-100/1.06)<1e-5);
  assert.equal(r.scenario_results[0].result.rows[0].sources[0].installed,false);assert(r.compliance.every(p=>p.actual_probability>=.95));
  assert(r.validation.every(v=>v.success_probability_lower===0));assert.equal(r.recommendation_status,'not_recommended_validation_failed');
  await page.getByRole('button',{name:'配置结果',exact:true}).click();await page.getByRole('heading',{name:'逐年现金流',exact:true}).waitFor();
  await page.getByText(/样本外验证未达到目标，本方案不能作为已验证可靠方案/).waitFor();await page.screenshot({path:'docs/多阶段配置投运与现金流验证.png',fullPage:true});
  await page.getByRole('combobox',{name:/查看场景/}).selectOption('1');await page.screenshot({path:'docs/联合机会约束与样本外验证.png',fullPage:true});
  const csv=await page.request.get(root+'/api/study-jobs/'+record.id+'/csv');assert.equal((await csv.text()).trim().split(/\r?\n/).length,2);
  const cash=await page.request.get(root+'/api/study-jobs/'+record.id+'/csv?dataset=cashflows');assert.equal((await cash.text()).trim().split(/\r?\n/).length,3);
  const report=await page.request.get(root+'/api/study-jobs/'+record.id+'/report');assert(report.ok());const reportHtml=await report.text();assert(reportHtml.includes('样本外验证失败'));assert(reportHtml.includes(record.input_sha256));
  fs.writeFileSync('docs/多阶段联合配置人工联调.json',JSON.stringify(record,null,2));
  fs.writeFileSync('docs/联合配置人工算例报告.html',reportHtml);await page.setContent(reportHtml);await page.getByRole('heading',{name:'逐年现金流',exact:true}).waitFor();await page.screenshot({path:'docs/联合配置研究报告验证.png',fullPage:true});
  await page.reload();await page.getByText('当前工程：跨期机会约束配置人工验证 · 版本 1',{exact:true}).waitFor();await page.getByRole('button',{name:'07源储协同配置',exact:true}).click();await page.getByRole('heading',{name:'逐年现金流',exact:true}).waitFor();
  await page.getByRole('button',{name:'08离网稳定判别',exact:true}).click();await page.getByRole('heading',{name:'动态模型与验证资料：暂未交付',exact:true}).waitFor();
  await page.screenshot({path:'docs/课题3模型暂留空状态.png',fullPage:true});
  await page.getByRole('button',{name:'11系统与接口',exact:true}).click();await page.getByRole('button',{name:'计算任务',exact:true}).click();await page.getByRole('button',{name:'查看',exact:true}).first().click();await page.getByText(/源储配置：complete/).waitFor();
  // Observe the dedicated native child's actual startup before requesting cancellation.
  const another=await json(await page.request.post(root+'/api/study-jobs',{data:{module:'investment',parameters:record.input.parameters}}));
  let nativeSeen=false;for(let i=0;i<100;i++){const text=await (await page.request.get(root+'/api/study-jobs/'+another.id+'/log')).text();if(text.includes('Native MILP pid=')){nativeSeen=true;break}await page.waitForTimeout(100)}assert(nativeSeen);
  await json(await page.request.post(root+'/api/study-jobs/'+another.id+'/cancel'));const stopped=await terminal(another.id);assert.equal(stopped.status,'cancelled');assert.equal(stopped.result,null);
  assert.deepEqual(errors,[]);console.log('PASS: actual joint/native workers, explicit cost validation, 2027 commission/2037 retirement, 94.339623 yuan NPV, no early resource, failed holdout retained, CSV/archive, empty dynamic model and live native cancellation.');
 }catch(e){console.error((await page.locator('body').innerText()).slice(-6000));throw e}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
