// Artificial grid sequence: 0/10/0 meets max consecutive gap=1h, total gap=2h.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/13411/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const root=process.env.DEVICE_STUDY_URL;if(!root)throw Error('Use current launcher URL');
 const browser=await chromium.launch({headless:true,channel:'msedge'}),page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function json(r){assert(r.ok(),await r.text());return r.json()}
 try{
 const network={name:'硬中断约束人工网络',source:'人工研究，非地区数据',base_voltage_kv:10,nodes:[{node:1,pd_kw:0},{node:2,pd_kw:10}],lines:[{line:1,from_node:1,to_node:2,r_ohm:0,x_ohm:0,status:1,capacity_kva:100}]};
 const p=await json(await page.request.post(root+'/api/projects',{data:{name:'中断预算与机会约束人工验证',kind:'乡镇级',state:{network}}}));
 const e=await json(await page.request.get(root+'/api/engineering/projects/'+p.id));
 e.inventory.loads=[{id:'L',name:'研究负荷（人工）',node:2,peak_kw:10,target_hours:3,load_class:'基本保障',interruption_allowed:true,maximum_interruption_hours:1}];
 e.inventory.sources=[{id:'D',name:'候选备用（人工）',node:2,kind:'柴油机',rated_kw:10,fuel_kwh:100,existing:false,grid_forming:true,black_start:true}];
 await json(await page.request.put(root+'/api/engineering/projects/'+p.id,{data:{project_revision:1,expected_revision:0,inventory:e.inventory}}));
 await page.addInitScript(id=>localStorage.setItem('terminal-power.last-project',id),p.id);await page.goto(root);await page.getByText('当前工程：中断预算与机会约束人工验证 · 版本 1',{exact:true}).waitFor();
 await page.getByRole('button',{name:'05电力电量平衡',exact:true}).click();await page.getByRole('button',{name:'逐设备时序调度',exact:true}).click();
 await page.getByLabel('计算步数',{exact:true}).fill('3');await page.getByLabel('强制满足台账保供目标',{exact:true}).check();await page.getByRole('textbox',{name:/外部供电容量/}).fill('0,10,0');
 let posted=page.waitForResponse(r=>r.url().endsWith('/api/device-dispatch')&&r.request().method()==='POST');await page.getByRole('button',{name:'执行逐设备调度并归档',exact:true}).click();const dispatch=await json(await posted);
 assert.equal(dispatch.input.algorithm,'devices.radial.horizon-milp.v4');assert.equal(dispatch.input.parameters.enforce_load_targets,true);const l=dispatch.result.load_metrics[0];assert.equal(l.maximum_target_interruption_hours,1);assert.equal(l.total_target_interruption_hours,2);assert.equal(l.target_status,'passed');
 await page.getByRole('heading',{name:'逐设备结果 · 逐设备时序调度',exact:true}).waitFor();await page.screenshot({path:'docs/硬中断约束与累计指标验证.png',fullPage:true});
 await page.getByRole('textbox',{name:/外部供电容量/}).fill('10,0,0');posted=page.waitForResponse(r=>r.url().endsWith('/api/device-dispatch')&&r.request().method()==='POST');await page.getByRole('button',{name:'执行逐设备调度并归档',exact:true}).click();const rejected=await posted;assert.equal(rejected.status(),422);await page.getByText(/给定逐设备调度约束不可行/).waitFor();
 await page.getByRole('button',{name:'07源储协同配置',exact:true}).click();await page.getByRole('checkbox',{name:'选择 D',exact:true}).check();await page.getByRole('spinbutton',{name:'D 投资成本 元',exact:true}).fill('100');await page.getByRole('button',{name:'目标与约束',exact:true}).click();await page.getByLabel('事件计算步数',{exact:true}).fill('3');await page.getByRole('combobox',{name:'保供目标判据',exact:true}).selectOption('interruption_budget');
 await page.getByLabel('训练场景 JSON',{exact:true}).fill(JSON.stringify([{id:'train',weight:1,grid_available_kw:[0,10,0]}]));await page.getByLabel('独立样本外验证 JSON',{exact:true}).fill(JSON.stringify([{id:'holdout',weight:1,grid_available_kw:[10,0,0]}]));
 await page.getByRole('button',{name:'规划阶段',exact:true}).click();await page.locator('table tr').nth(1).locator('td').nth(5).locator('input').fill('0');
 posted=page.waitForResponse(r=>r.url().endsWith('/api/study-jobs')&&r.request().method()==='POST');await page.getByRole('button',{name:'提交多阶段机会约束配置',exact:true}).click();const created=await json(await posted);let record;
 for(let i=0;i<200;i++){record=await json(await page.request.get(root+'/api/study-jobs/'+created.id+'?include_input=true&include_result=true'));if(['succeeded','failed','incomplete','interrupted','cancelled'].includes(record.status))break;await page.waitForTimeout(200)}
 assert.equal(record.status,'succeeded',record.error);assert.equal(record.result.target_policy,'interruption_budget');assert.equal(record.result.selected_assets.length,0);assert.equal(record.result.compliance[0].actual_probability,1);assert.equal(record.result.validation[0].success_probability_upper,0);assert.equal(record.result.recommendation_status,'not_recommended_validation_failed');
 await page.getByRole('button',{name:'配置结果',exact:true}).click();await page.getByText(/样本外验证未达到目标/).waitFor();await page.getByRole('heading',{name:'台账中断指标（配置达标以所选判据为准）',exact:true}).waitFor();await page.screenshot({path:'docs/中断预算机会约束与验证失败.png',fullPage:true});
 const html=await (await page.request.get(root+'/api/study-jobs/'+created.id+'/report')).text();assert(html.includes('interruption_budget'));fs.writeFileSync('docs/中断预算人工算例报告.html',html);fs.writeFileSync('docs/中断预算人工联调.json',JSON.stringify({root,source:'人工研究验证，非地区数据',dispatch,investment:record,errors},null,2));
 await page.reload();await page.getByText('当前工程：中断预算与机会约束人工验证 · 版本 1',{exact:true}).waitFor();await page.getByRole('button',{name:'07源储协同配置',exact:true}).click();await page.getByText(/本次配置目标判据：台账最大连续中断预算/).waitFor();assert.deepEqual(errors,[]);console.log('PASS: hard target UI/archive, 1h consecutive vs 2h total, 2h infeasible, actual joint worker, no unnecessary build, failed holdout, report and archive criterion.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
