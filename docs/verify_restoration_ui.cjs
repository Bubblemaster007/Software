// Artificial two-node study: 5min command + 5min start, 5min switch, 5min pickup.
const fs=require('node:fs');const assert=require('node:assert/strict');
const {chromium}=require('C:/Users/13411/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const root=process.env.DEVICE_STUDY_URL||'http://127.0.0.1:8771';const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1600,height:1050}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function json(r){assert(r.ok(),await r.text());return r.json()}
 try{
  const network={name:'黑启动两节点人工网络',source:'人工时序验证，非地区实测',base_voltage_kv:10,nodes:[{node:1,pd_kw:0},{node:2,pd_kw:20}],lines:[{line:7,from_node:1,to_node:2,r_ohm:0,x_ohm:0,status:1,capacity_kva:200}]};
  const project=await json(await page.request.post(root+'/api/projects',{data:{name:'黑启动操作与回放人工验证',kind:'乡镇级',state:{network}}}));
  const current=await json(await page.request.get(root+'/api/engineering/projects/'+project.id));
  current.inventory.sources=[{id:'D',name:'柴油启动源（人工）',node:1,kind:'柴油机',rated_kw:100,fuel_kwh:1000,grid_forming:true,black_start:true,startup_minutes:5}];
  current.inventory.loads=[{id:'L',name:'医院负荷（人工）',node:2,peak_kw:20,target_hours:1,load_class:'基本保障'}];
  current.inventory.switches=[{id:'S',name:'线路开关（人工）',node:1,line_id:7,operation_minutes:1}];
  await json(await page.request.put(root+'/api/engineering/projects/'+project.id,{data:{project_revision:1,expected_revision:0,inventory:current.inventory}}));
  await page.addInitScript(id=>localStorage.setItem('terminal-power.last-project',id),project.id);await page.goto(root);
  await page.getByText('当前工程：黑启动操作与回放人工验证 · 版本 1',{exact:true}).waitFor();
  await page.getByRole('button',{name:'09黑启动路径优化',exact:true}).click();await page.getByText(/工程版本 1 \/ 台账版本 1/).waitFor();
  await page.getByRole('heading',{name:'黑启动路径优化 · 恢复分区',exact:true}).waitFor();
  assert.equal(await page.getByRole('checkbox',{name:/线路 7/}).isChecked(),false);
  await page.getByRole('button',{name:'启动资源',exact:true}).click();
  await page.getByRole('checkbox',{name:'人工启动 D',exact:true}).check();await page.getByRole('checkbox',{name:/独立人工投入 L/}).check();
  await page.getByRole('button',{name:'一二次约束',exact:true}).click();await page.getByRole('checkbox',{name:/人工操作 S/}).check();
  const submitted=page.waitForResponse(r=>r.url().endsWith('/api/study-jobs')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'提交黑启动恢复规划',exact:true}).click();const created=await json(await submitted);
  let record;for(let i=0;i<100;i++){record=await json(await page.request.get(root+'/api/study-jobs/'+created.id+'?include_input=true&include_result=true'));if(['succeeded','incomplete','failed','cancelled','interrupted'].includes(record.status))break;await page.waitForTimeout(200)}
  assert.equal(record.status,'succeeded',record.error);const r=record.result;
  assert.deepEqual(r.actions.map(a=>a.kind),['start','close','pickup']);assert.deepEqual(r.actions.map(a=>a.end_step),[2,3,4]);
  assert.equal(r.operational_clearance,'not_cleared');assert.equal(r.load_recovery[0].first_sustained_full_supply_minutes,20);
  assert(Math.abs(r.dispatch.metrics.served_energy_kwh-20*8/12)<1e-4);assert(record.input_sha256);assert(record.process_identity);
  await page.getByRole('heading',{name:'约束校核状态',exact:true}).waitFor();await page.getByText('频率/电压暂态稳定',{exact:true}).waitFor();
  await page.screenshot({path:'docs/黑启动一次二次约束验证.png',fullPage:true});
  await page.getByRole('button',{name:'恢复序列',exact:true}).click();await page.getByRole('combobox',{name:/查看时刻/}).selectOption('4');
  await page.locator('svg[aria-label="黑启动恢复时刻拓扑"]').waitFor();assert.equal(await page.locator('svg circle[fill="#087b7b"]').count(),2);
  await page.screenshot({path:'docs/黑启动操作序列与恢复回放验证.png',fullPage:true});
  await page.getByRole('button',{name:'恢复分区',exact:true}).click();await page.getByRole('heading',{name:'最终带电分区',exact:true}).waitFor();
  await page.screenshot({path:'docs/黑启动电气分区与预分配验证.png',fullPage:true});
  const csv=await page.request.get(root+'/api/study-jobs/'+record.id+'/csv');assert.equal((await csv.text()).trim().split(/\r?\n/).length,4);
  fs.writeFileSync('docs/黑启动恢复人工联调.json',JSON.stringify(record,null,2));
  await page.reload();await page.getByText('当前工程：黑启动操作与回放人工验证 · 版本 1',{exact:true}).waitFor();await page.getByRole('button',{name:'09黑启动路径优化',exact:true}).click();
  await page.getByRole('heading',{name:'最终带电分区',exact:true}).waitFor();
  await page.getByRole('button',{name:'11系统与接口',exact:true}).click();await page.getByRole('button',{name:'计算任务',exact:true}).click();await page.getByRole('button',{name:'查看',exact:true}).first().click();await page.getByText(/恢复规划：3步操作 \/ 1个带电分区/).waitFor();
  assert.deepEqual(errors,[]);console.log('PASS: actual worker, start/switch/pickup at 10/15/20min, 13.333kWh, frozen archive, CSV, two energized nodes, partition, unmet transient checks and task manager.');
 }catch(e){console.error((await page.locator('body').innerText()).slice(-5000));throw e}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
