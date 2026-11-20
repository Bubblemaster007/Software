// Artificial four-step study: arrival at 15min + 15min startup; exactly 10kWh served.
const {chromium}=require('C:/Users/13411/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1600,height:1050}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  const root=process.env.DEVICE_STUDY_URL||'http://127.0.0.1:8765';
  const network={name:'两节点人工验证网络',source:'人工联调，非实测',base_voltage_kv:10,
   nodes:[{node:1,pd_kw:0},{node:2,pd_kw:20}],lines:[{line:7,from_node:1,to_node:2,r_ohm:0,x_ohm:0,status:1,capacity_kva:100}]};
  const create=await page.request.post(root+'/api/projects',{data:{name:'逐设备移动电源联调工程',kind:'乡镇级',state:{network}}});
  if(!create.ok())throw Error(await create.text());const project=await create.json();
  const current=await (await page.request.get(root+'/api/engineering/projects/'+project.id)).json();
  current.inventory.loads=[{id:'hospital',name:'医院（人工验证）',node:2,peak_kw:20,target_hours:1,load_class:'基本保障'}];
  current.inventory.sources=[{id:'mobile-D',name:'移动电源（人工验证）',node:2,kind:'移动发电车',rated_kw:20,
   arrival_minutes:15,startup_minutes:15,grid_forming:true,black_start:true,fuel_kwh:100}];
  const saved=await page.request.put(root+'/api/engineering/projects/'+project.id,{data:{project_revision:1,expected_revision:0,inventory:current.inventory}});
  if(!saved.ok())throw Error(await saved.text());
  await page.addInitScript(id=>localStorage.setItem('terminal-power.last-project',id),project.id);
  await page.goto(root);await page.getByText('当前工程：逐设备移动电源联调工程 · 版本 1',{exact:true}).waitFor();
  await page.getByRole('button',{name:'05电力电量平衡',exact:true}).click();
  await page.getByRole('button',{name:'逐设备时序调度',exact:true}).click();
  await page.getByText(/台账版本 1 · 电源1/).waitFor();
  await page.getByRole('combobox',{name:/时间步长/}).selectOption('0.25');
  await page.getByLabel('计算步数',{exact:true}).fill('4');
  const posted=page.waitForResponse(r=>r.url().endsWith('/api/device-dispatch')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'执行逐设备调度并归档',exact:true}).click();
  const response=await posted;if(!response.ok())throw Error(await response.text());const record=await response.json();
  if(record.input.algorithm!=='devices.radial.horizon-milp.v3'||!record.input.runtime?.build_id)throw Error('Unexpected backend build or missing algorithm fingerprint');
  if(Math.abs(record.result.metrics.served_energy_kwh-10)>1e-4)throw Error('Expected 10kWh after delayed arrival/start');
  if(record.result.rows[0].served_kw>1e-5||record.result.rows[1].served_kw>1e-5)throw Error('Resource supplied before arrival/startup');
  await page.getByRole('heading',{name:'逐设备结果 · 逐设备时序调度',exact:true}).waitFor();
  await page.locator('canvas').waitFor();
  await page.getByRole('combobox',{name:/查看时刻/}).selectOption('2');
  await page.screenshot({path:'docs/逐设备调度到位与启动验证.png',fullPage:true});
  const exported=await page.request.get(root+'/api/device-dispatch/'+record.id+'/csv');
  if((await exported.text()).trim().split(/\r?\n/).length!==5)throw Error('CSV step count mismatch');
  await page.reload();await page.getByText('当前工程：逐设备移动电源联调工程 · 版本 1',{exact:true}).waitFor();
  await page.getByRole('button',{name:'05电力电量平衡',exact:true}).click();
  await page.getByRole('button',{name:'逐设备时序调度',exact:true}).click();
  await page.getByRole('button',{name:/逐设备时序调度 · 分层目标已求解/}).click();
  await page.getByRole('heading',{name:'逐设备结果 · 逐设备时序调度',exact:true}).waitFor();
  if(errors.length)throw Error(errors.join('\n'));
  console.log('PASS: 15min UI study, delayed mobile resource, 10kWh, chart, CSV and archived reload.');
 }catch(e){console.error((await page.locator('body').innerText()).slice(-4000));throw e}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
