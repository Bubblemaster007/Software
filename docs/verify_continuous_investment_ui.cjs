// Artificial 2-node design upper bound 100 kW / 100 kWh, NOT measured project data.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/13411/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const root=process.env.DEVICE_STUDY_URL;if(!root)throw Error('Set DEVICE_STUDY_URL to current launcher URL');
 const browser=await chromium.launch({headless:true,channel:'msedge'}),page=await browser.newPage({viewport:{width:1600,height:1100}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function json(r){assert(r.ok(),await r.text());return r.json()}
 try{
 const network={name:'连续定容人工网络',source:'手算研究验证，非地区实测',base_voltage_kv:10,nodes:[{node:1,pd_kw:0},{node:2,pd_kw:10}],lines:[{line:7,from_node:1,to_node:2,r_ohm:0,x_ohm:0,status:1,capacity_kva:100}]};
 const p=await json(await page.request.post(root+'/api/projects',{data:{name:'连续定容功率能量人工验证',kind:'乡镇级',state:{network}}}));
 const e=await json(await page.request.get(root+'/api/engineering/projects/'+p.id));
 e.inventory.loads=[{id:'L',name:'医院（人工）',node:2,peak_kw:10,target_hours:2,load_class:'基本保障'}];
 e.inventory.storage=[{id:'B',name:'储能可建参考上限（人工）',node:2,power_kw:100,energy_kwh:100,initial_soc:.8,minimum_soc:.1,discharge_efficiency:.95,existing:false,grid_forming:true,black_start:true}];
 e.inventory.sources=[{id:'D',name:'固定柴油候选（人工）',node:2,kind:'柴油机',rated_kw:100,fuel_kwh:1000,existing:false,grid_forming:true,black_start:true}];
 await json(await page.request.put(root+'/api/engineering/projects/'+p.id,{data:{project_revision:1,expected_revision:0,inventory:e.inventory}}));
 await page.addInitScript(id=>localStorage.setItem('terminal-power.last-project',id),p.id);await page.goto(root);
 await page.getByText('当前工程：连续定容功率能量人工验证 · 版本 1',{exact:true}).waitFor();await page.getByRole('button',{name:'07源储协同配置',exact:true}).click();
 await page.getByRole('checkbox',{name:'选择 B',exact:true}).check();await page.getByRole('combobox',{name:'B 容量方式',exact:true}).selectOption('continuous');
 await page.getByRole('button',{name:'提交多阶段机会约束配置',exact:true}).click();await page.getByText(/连续储能须分别填写功率/).waitFor();
 await page.getByRole('spinbutton',{name:'B 功率投资 元',exact:true}).fill('1000');await page.getByRole('spinbutton',{name:'B 能量投资 元',exact:true}).fill('1000');await page.getByRole('spinbutton',{name:'B 固定建设费 元',exact:true}).fill('100');
 await page.getByRole('checkbox',{name:'选择 D',exact:true}).check();await page.getByRole('spinbutton',{name:'D 投资成本 元',exact:true}).fill('1000');
 await page.getByRole('spinbutton',{name:'B 寿命 年',exact:true}).fill('10');
 await page.screenshot({path:'docs/连续定容候选与成本设置.png',fullPage:true});
 await page.getByRole('button',{name:'目标与约束',exact:true}).click();await page.getByLabel('事件计算步数',{exact:true}).fill('2');await page.getByRole('combobox',{name:/联合范围/}).selectOption('all_periods');
 await page.getByLabel('训练场景 JSON',{exact:true}).fill(JSON.stringify([{id:'path',weight:1,grid_available_kw:[20],stage_overrides:{2027:{grid_available_kw:[0]}}}]));
 await page.getByLabel('独立样本外验证 JSON',{exact:true}).fill(JSON.stringify([{id:'holdout',weight:1,grid_available_kw:[20],load_scale:1.01,stage_overrides:{2027:{grid_available_kw:[0]}}}]));
 await page.getByRole('button',{name:'规划阶段',exact:true}).click();let row=page.locator('table tr').nth(1);await row.locator('td').nth(3).locator('input').fill('0');await row.locator('td').nth(5).locator('input').fill('0');await page.getByRole('button',{name:'增加建设阶段',exact:true}).click();row=page.locator('table tr').nth(2);await row.locator('td').nth(3).locator('input').fill('600');await row.locator('td').nth(5).locator('input').fill('0');
 const submitted=page.waitForResponse(r=>r.url().endsWith('/api/study-jobs')&&r.request().method()==='POST');await page.getByRole('button',{name:'提交多阶段机会约束配置',exact:true}).click();const created=await json(await submitted);
 let record;for(let i=0;i<200;i++){record=await json(await page.request.get(root+'/api/study-jobs/'+created.id+'?include_input=true&include_result=true'));if(['succeeded','incomplete','failed','cancelled','interrupted'].includes(record.status))break;await page.waitForTimeout(200)}
 assert.equal(record.status,'succeeded',record.error);const r=record.result,a=r.selected_assets[0],energy=20/(.95*.68);assert.equal(r.status,'complete');assert.equal(r.selected_assets.length,1);assert.equal(a.asset_id,'B');assert.equal(a.commission_year,2027);assert.equal(a.retirement_year,2037);assert.equal(a.sizing_mode,'continuous');assert(Math.abs(a.power_kw-10)<1e-5);assert(Math.abs(a.energy_kwh-energy)<1e-5);assert(Math.abs(a.capex_yuan-(200+10*energy))<1e-5);assert(Math.abs(r.objective_yuan-a.capex_yuan/1.06)<1e-5);
 const first=r.scenario_results[0].result.rows[0].storage[0];assert.equal(first.installed,false);assert.equal(first.effective_capacity_kwh,0);assert.equal(first.reactive_kvar,0);
 assert.equal(r.validation_all_periods.success_probability_upper,0);assert.equal(r.recommendation_status,'not_recommended_validation_failed');assert.equal(record.input.parameters.candidates.find(c=>c.asset_id==='B').power_capex_yuan,1000);
 const csv=await page.request.get(root+'/api/study-jobs/'+created.id+'/csv');assert(csv.ok());const text=await csv.text();assert(text.includes('power_fraction'));assert(text.includes('continuous'));assert.equal(text.trim().split(/\r?\n/).length,2);
 const report=await page.request.get(root+'/api/study-jobs/'+created.id+'/report');assert(report.ok());const html=await report.text();assert(html.includes('功率比例'));assert(html.includes('continuous'));fs.writeFileSync('docs/连续定容人工算例报告.html',html);fs.writeFileSync('docs/连续定容人工联调.json',JSON.stringify({source:'人工手算及UI/实际后台求解，非地区数据',root,record,errors},null,2));
 await page.getByRole('button',{name:'配置结果',exact:true}).click();await page.getByText(/样本外验证未达到目标/).waitFor();await page.screenshot({path:'docs/连续定容功率能量与现金流验证.png',fullPage:true});
 await page.reload();await page.getByText('当前工程：连续定容功率能量人工验证 · 版本 1',{exact:true}).waitFor();await page.getByRole('button',{name:'07源储协同配置',exact:true}).click();await page.getByText(/样本外验证未达到目标/).waitFor();await page.getByText('10.000',{exact:true}).first().waitFor();
 const reportPage=await browser.newPage({viewport:{width:1440,height:1000}});await reportPage.goto('file:///'+process.cwd().replace(/\\/g,'/')+'/docs/连续定容人工算例报告.html');await reportPage.screenshot({path:'docs/连续定容研究报告验证.png',fullPage:true});assert.deepEqual(errors,[]);console.log(JSON.stringify({url:root,job_id:created.id,selected:a,npv:r.objective_yuan,holdout_joint:r.validation_all_periods,errors}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
