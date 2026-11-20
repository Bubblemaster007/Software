// Artificial two-node epsilon sweep and capital OAT. Prices are test values.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require('C:/Users/13411/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

(async () => {
  const root = process.env.DEVICE_STUDY_URL;
  assert(root, 'Set DEVICE_STUDY_URL to the current launcher URL');
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  const page = await browser.newPage({viewport: {width: 1600, height: 1100}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));

  async function json(response) {
    assert(response.ok(), await response.text());
    return response.json();
  }
  async function terminal(id) {
    for (let index = 0; index < 300; index++) {
      const record = await json(await page.request.get(root + '/api/study-jobs/' + id + '?include_input=true&include_result=true'));
      if (['succeeded', 'incomplete', 'failed', 'cancelled', 'interrupted'].includes(record.status)) return record;
      await page.waitForTimeout(200);
    }
    throw Error('Observed experiment did not finish in the test window');
  }

  try {
    const network = {
      name: '风险成本人工网络', source: '人工研究验证', base_voltage_kv: 10,
      nodes: [{node: 1, pd_kw: 0}, {node: 2, pd_kw: 10}],
      lines: [{line: 7, from_node: 1, to_node: 2, r_ohm: 0, x_ohm: 0, status: 1, capacity_kva: 100}],
    };
    const project = await json(await page.request.post(root + '/api/projects', {
      data: {name: '风险成本敏感性人工验证', kind: '乡镇级', state: {network}},
    }));
    const engineering = await json(await page.request.get(root + '/api/engineering/projects/' + project.id));
    engineering.inventory.loads = [{id: 'L', name: '医院（人工）', node: 2, peak_kw: 10, target_hours: 2, load_class: '基本保障'}];
    engineering.inventory.sources = [{id: 'D', name: '柴油候选（人工）', node: 2, kind: '柴油机', rated_kw: 10, fuel_kwh: 100, existing: false, grid_forming: true, black_start: true}];
    await json(await page.request.put(root + '/api/engineering/projects/' + project.id, {
      data: {project_revision: 1, expected_revision: 0, inventory: engineering.inventory},
    }));
    await page.addInitScript(id => localStorage.setItem('terminal-power.last-project', id), project.id);
    await page.goto(root);
    await page.getByText('当前工程：风险成本敏感性人工验证 · 版本 1', {exact: true}).waitFor();
    await page.getByRole('button', {name: '07源储协同配置', exact: true}).click();
    await page.getByRole('checkbox', {name: '选择 D', exact: true}).check();
    await page.getByRole('spinbutton', {name: 'D 投资成本 元', exact: true}).fill('100');
    await page.getByRole('button', {name: '目标与约束', exact: true}).click();
    await page.getByLabel('事件计算步数', {exact: true}).fill('2');
    await page.getByLabel('训练场景 JSON', {exact: true}).fill(JSON.stringify([
      {id: 'grid', weight: .8, grid_available_kw: [20]}, {id: 'outage', weight: .2, grid_available_kw: [0]},
    ]));
    await page.getByLabel('独立样本外验证 JSON', {exact: true}).fill(JSON.stringify([
      {id: 'heldout', weight: 1, device_availability: {D: [0]}},
    ]));
    await page.getByRole('button', {name: '规划阶段', exact: true}).click();
    await page.locator('table tr').nth(1).locator('td').nth(5).locator('input').fill('0');
    await page.getByRole('button', {name: '配置结果', exact: true}).click();
    await page.getByRole('button', {name: '载入当前配置参数作为研究基准', exact: true}).click();
    await page.getByLabel('扫描达标概率', {exact: true}).fill('.8,.95,1');
    await page.getByRole('button', {name: '添加敏感性因素', exact: true}).click();
    await page.getByLabel('敏感性名称 1', {exact: true}).fill('资本减半');
    await page.getByLabel('敏感性参数值 1', {exact: true}).fill('0.5');
    await page.getByRole('button', {name: '添加敏感性因素', exact: true}).click();
    await page.getByLabel('敏感性名称 2', {exact: true}).fill('资本加倍');
    await page.getByLabel('敏感性参数值 2', {exact: true}).fill('2');
    const posted = page.waitForResponse(response => response.url().endsWith('/api/study-jobs') && response.request().method() === 'POST');
    await page.getByRole('button', {name: '提交风险成本与敏感性比较', exact: true}).click();
    const created = await json(await posted);
    assert.equal(created.module, 'investment_experiments');
    const record = await terminal(created.id);
    assert.equal(record.status, 'succeeded', record.error);
    const result = record.result;
    assert.equal(result.cases.length, 5);
    const cases = Object.fromEntries(result.cases.map(item => [item.id, item]));
    assert.equal(cases.baseline.objective_yuan, 100);
    assert.equal(cases['risk-01'].objective_yuan, 0);
    assert.equal(cases['risk-01'].training_success_probability, .8);
    assert.equal(cases['risk-01'].worst_period_expected_event_unsupplied_kwh, 4);
    assert.equal(cases['sensitivity-01'].objective_yuan, 50);
    assert.equal(cases['sensitivity-02'].objective_yuan, 200);
    assert.deepEqual(result.validated_non_dominated, []);
    assert(result.cases.every(item => item.validation_status === 'failed'));
    await page.getByRole('heading', {name: '风险—成本已计算点', exact: true}).waitFor();
    const chart = page.getByRole('img', {name: '风险成本已计算点', exact: true});
    await chart.waitFor();
    assert.equal(await chart.locator('circle').count(), 3);
    await page.screenshot({path: 'docs/配置风险成本与敏感性验证.png', fullPage: true});
    await page.getByRole('combobox', {name: '概率口径', exact: true}).selectOption('validation');
    await page.getByRole('button', {name: '查看 baseline', exact: true}).click();
    await page.getByRole('heading', {name: '比较单例 · 基准', exact: true}).waitFor();
    const detail = await json(await page.request.get(root + '/api/study-jobs/' + created.id + '/experiment-cases/baseline'));
    assert.equal(detail.frozen_experiment_input_sha256, record.input_sha256);
    assert.equal(detail.result.scenario_results.length, 2);
    assert.equal(detail.result.scenario_results[0].result.rows.length, 2);
    assert.equal(detail.result.selected_assets[0].asset_id, 'D');
    const csv = await page.request.get(root + '/api/study-jobs/' + created.id + '/csv');
    assert(csv.ok());
    assert.equal((await csv.text()).trim().split(/\r?\n/).length, 6);
    const report = await page.request.get(root + '/api/study-jobs/' + created.id + '/report');
    assert(report.ok());
    const html = await report.text();
    assert(html.includes('样本外概率下界'));
    fs.writeFileSync('docs/配置风险成本敏感性人工报告.html', html);
    fs.writeFileSync('docs/配置风险成本敏感性人工联调.json', JSON.stringify({root, source: '人工验证', record, detail, errors}, null, 2));
    await page.screenshot({path: 'docs/配置比较单例证据与验证口径.png', fullPage: true});
    const reportPage = await browser.newPage({viewport: {width: 1600, height: 1000}});
    await reportPage.setContent(html);
    await reportPage.screenshot({path: 'docs/配置比较研究报告验证.png', fullPage: true});
    await reportPage.close();

    // Observe this experiment's owned native process before cancellation.
    const retried = page.waitForResponse(response => response.url().endsWith('/' + created.id + '/retry'));
    await page.getByRole('button', {name: '按冻结输入重试比较', exact: true}).click();
    const retry = await json(await retried);
    let nativeSeen = false;
    for (let index = 0; index < 150; index++) {
      const log = await (await page.request.get(root + '/api/study-jobs/' + retry.id + '/log')).text();
      if (log.includes('Native MILP pid=')) { nativeSeen = true; break; }
      await page.waitForTimeout(100);
    }
    assert(nativeSeen);
    await page.getByRole('button', {name: '取消比较研究', exact: true}).click();
    const stopped = await terminal(retry.id);
    assert.equal(stopped.status, 'cancelled');
    assert.equal(stopped.result, null);
    await page.reload();
    await page.getByText('当前工程：风险成本敏感性人工验证 · 版本 1', {exact: true}).waitFor();
    await page.getByRole('button', {name: '07源储协同配置', exact: true}).click();
    await page.getByRole('button', {name: '配置结果', exact: true}).click();
    await page.locator('button.record').filter({hasText: '计算结束'}).first().click();
    await chart.waitFor();
    await page.getByRole('button', {name: '查看 baseline', exact: true}).click();
    await page.getByRole('heading', {name: '比较单例 · 基准', exact: true}).waitFor();
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({job_id: created.id, cases: result.cases.length, costs: result.cases.map(item => item.objective_yuan), validated: result.validated_non_dominated, live_native_cancelled: true, errors}));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
