// Artificial startup crossing a committed boundary, followed by timed refuelling.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require('C:/Users/13411/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

(async () => {
  const root = process.env.DEVICE_STUDY_URL;
  assert(root, 'Set the current launcher URL');
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  const page = await browser.newPage({viewport: {width: 1600, height: 1100}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  async function json(response) {
    assert(response.ok(), await response.text());
    return response.json();
  }
  async function calculate() {
    const posted = page.waitForResponse(response => response.url().endsWith('/api/device-dispatch') && response.request().method() === 'POST');
    await page.getByRole('button', {name: '执行逐设备调度并归档', exact: true}).click();
    const record = await json(await posted);
    await page.getByRole('heading', {name: '逐设备结果 · 逐设备时序调度', exact: true}).waitFor();
    return record;
  }
  try {
    const network = {name: '衔接人工网络', source: '人工验证', base_voltage_kv: 10,
      nodes: [{node: 1, pd_kw: 0}, {node: 2, pd_kw: 10}],
      lines: [{line: 1, from_node: 1, to_node: 2, r_ohm: 0, x_ohm: 0, status: 1, capacity_kva: 100}]};
    const project = await json(await page.request.post(root + '/api/projects', {
      data: {name: '跨窗口初态与补给人工验证', kind: '乡镇级', state: {network}},
    }));
    const engineering = await json(await page.request.get(root + '/api/engineering/projects/' + project.id));
    engineering.inventory.loads = [{id: 'L', name: '医院（人工）', node: 2, peak_kw: 10, target_hours: 4, load_class: '基本保障'}];
    engineering.inventory.sources = [{id: 'D', name: '启动机组（人工）', node: 2, kind: '柴油机', rated_kw: 10,
      startup_minutes: 120, fuel_kwh: 100, black_start: true, grid_forming: true}];
    await json(await page.request.put(root + '/api/engineering/projects/' + project.id, {
      data: {project_revision: 1, expected_revision: 0, inventory: engineering.inventory},
    }));
    await page.addInitScript(id => localStorage.setItem('terminal-power.last-project', id), project.id);
    await page.goto(root);
    await page.getByText('当前工程：跨窗口初态与补给人工验证 · 版本 1', {exact: true}).waitFor();
    await page.getByRole('button', {name: '05电力电量平衡', exact: true}).click();
    await page.getByRole('button', {name: '逐设备时序调度', exact: true}).click();
    await page.getByLabel('计算步数', {exact: true}).fill('4');
    const first = await calculate();
    assert.equal(first.result.metrics.served_energy_kwh, 20);
    await page.getByRole('combobox', {name: '查看时刻', exact: true}).selectOption('0');
    await page.getByRole('button', {name: '载入所选时刻后的衔接状态', exact: true}).click();
    for (let attempt = 0; attempt < 50 && !await page.getByLabel('使用衔接初态与补给', {exact: true}).isChecked(); attempt++) {
      await page.waitForTimeout(100);
    }
    assert(await page.getByLabel('使用衔接初态与补给', {exact: true}).isChecked());
    assert.equal(await page.getByLabel('计算步数', {exact: true}).inputValue(), '3');
    const loaded = JSON.parse(await page.getByLabel('跨窗口状态与补给 JSON', {exact: true}).inputValue());
    assert.equal(loaded.parameters.initial_source_startup_remaining_steps.D, 1);
    assert.equal(loaded.parameters.initial_source_fuel_kwh.D, 100);
    assert.equal(loaded.parameters.initial_target_interruption_hours.L, 1);
    assert.equal(loaded.parameters.elapsed_hours, 1);
    const second = await calculate();
    assert.equal(second.input.algorithm, 'devices.radial.horizon-milp.v5');
    assert.equal(second.result.rows[0].served_kw, 0);
    assert.equal(second.result.rows[1].served_kw, 10);
    assert.equal(second.result.metrics.served_energy_kwh, 20);
    assert.equal(second.result.rows[2].sources[0].fuel_remaining_kwh, 80);
    assert(second.result.rows.every(row => !row.sources[0].startup_command));
    assert.equal(second.result.load_metrics[0].maximum_target_interruption_hours, 2);
    assert.equal(second.result.load_metrics[0].total_target_interruption_hours, 2);
    assert(second.input.parameters.initial_state_provenance.includes(first.id));
    await page.locator('canvas').waitFor();
    await page.waitForTimeout(100);
    await page.screenshot({path: 'docs/跨窗口启动与中断前史验证.png', fullPage: true});

    engineering.inventory.sources[0].startup_minutes = 0;
    engineering.inventory.sources[0].fuel_kwh = 0;
    await json(await page.request.put(root + '/api/engineering/projects/' + project.id, {
      data: {project_revision: 1, expected_revision: 1, inventory: engineering.inventory},
    }));
    await page.getByRole('button', {name: '重新读取输入', exact: true}).click();
    await page.getByText(/台账版本 2 · 电源1/).waitFor();
    await page.getByLabel('计算步数', {exact: true}).fill('4');
    await page.getByText('跨窗口状态与可发电量补给', {exact: true}).click();
    await page.getByLabel('使用衔接初态与补给', {exact: true}).check();
    await page.getByLabel('跨窗口状态与补给 JSON', {exact: true}).fill(JSON.stringify({source_energy_additions_kwh: {D: [0, 100, 0, 0]}}));
    const refuel = await calculate();
    assert.equal(refuel.result.rows[0].served_kw, 0);
    assert.equal(refuel.result.rows[0].sources[0].on, false);
    assert.equal(refuel.result.metrics.served_energy_kwh, 30);
    assert.equal(refuel.result.rows[3].sources[0].fuel_remaining_kwh, 70);
    const frozen = await json(await page.request.get(root + '/api/device-dispatch/' + first.id + '/continuation?committed_steps=1'));
    assert.equal(frozen.engineering_revision, 1);
    assert.equal(frozen.parameters.initial_source_startup_remaining_steps.D, 1);
    assert.equal(frozen.parameters.source_energy_additions_kwh.D, undefined);
    await page.locator('canvas').waitFor();
    await page.waitForTimeout(100);
    await page.screenshot({path: 'docs/定时补给与燃料守恒验证.png', fullPage: true});
    fs.writeFileSync('docs/跨窗口衔接人工联调.json', JSON.stringify({root, source: '人工验证', first, second, refuel, frozen, errors}, null, 2));
    await page.reload();
    await page.getByText('当前工程：跨窗口初态与补给人工验证 · 版本 1', {exact: true}).waitFor();
    await page.getByRole('button', {name: '05电力电量平衡', exact: true}).click();
    await page.getByRole('button', {name: '逐设备时序调度', exact: true}).click();
    await page.locator('button.record').first().click();
    await page.getByRole('heading', {name: '逐设备结果 · 逐设备时序调度', exact: true}).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: actual state export/load, 120min startup preserved across 1h boundary, 20kWh continuation, 2h history, 100kWh timed addition/70kWh remaining, frozen revision and archive.');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
