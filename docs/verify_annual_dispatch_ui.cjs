// Artificial two-node calendar year through the actual browser and background worker.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require('C:/Users/13411/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

(async () => {
  const root = process.env.DEVICE_STUDY_URL;
  assert(root, 'Set the launcher URL');
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  const page = await browser.newPage({viewport: {width: 1500, height: 1050}});
  const errors = [];
  const owned = [];
  page.on('pageerror', error => errors.push(error.message));
  async function json(response) {
    assert(response.ok(), await response.text());
    return response.json();
  }
  async function waitJob(id) {
    for (let index = 0; index < 240; index++) {
      const value = await json(await page.request.get(root + '/api/study-jobs/' + id + '?include_result=true'));
      if (!['queued', 'running', 'cancel_requested'].includes(value.status)) return value;
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    throw Error('Annual worker exceeded test deadline');
  }
  try {
    const network = {name: '年度人工网络', source: '人工验证', base_voltage_kv: 10,
      nodes: [{node: 1, pd_kw: 0}, {node: 2, pd_kw: 10}],
      lines: [{line: 1, from_node: 1, to_node: 2, r_ohm: 0, x_ohm: 0, status: 1, capacity_kva: 100}]};
    const project = await json(await page.request.post(root + '/api/projects', {
      data: {name: '年度滚动人工验证', kind: '乡镇级', state: {network}}
    }));
    const engineering = await json(await page.request.get(root + '/api/engineering/projects/' + project.id));
    engineering.inventory.loads = [{id: 'L', name: '人工负荷', node: 2, peak_kw: 10,
      target_hours: 4, load_class: '基本保障'}];
    await json(await page.request.put(root + '/api/engineering/projects/' + project.id, {
      data: {project_revision: 1, expected_revision: 0, inventory: engineering.inventory}
    }));
    await page.addInitScript(id => localStorage.setItem('terminal-power.last-project', id), project.id);
    await page.goto(root);
    await page.getByText('当前工程：年度滚动人工验证 · 版本 1', {exact: true}).waitFor();
    await page.getByRole('button', {name: '05电力电量平衡', exact: true}).click();
    await page.getByRole('button', {name: '逐设备年度滚动', exact: true}).click();
    await page.getByLabel('常值网供上限 / kW', {exact: true}).fill('10');
    await page.getByLabel('数据来源与工况说明', {exact: true}).fill('人工两节点恒负荷10kW/网供10kW，2026全年，非实测');
    const posted = page.waitForResponse(response => response.url().endsWith('/api/study-jobs') && response.request().method() === 'POST');
    await page.getByRole('button', {name: '提交年度滚动任务', exact: true}).click();
    const submitted = await json(await posted);
    owned.push(submitted.id);
    const job = await waitJob(submitted.id);
    assert.equal(job.status, 'succeeded', job.error);
    assert.equal(job.result.coverage.calendar_year_complete, true);
    assert.equal(job.result.coverage.completed_steps, 8760);
    assert.equal(job.result.windows.length, 365);
    assert.equal(job.result.metrics.served_energy_kwh, 87600);
    assert.equal(job.result.metrics.study_dispatch_cost_yuan, 43800);
    assert.equal(job.result.metrics.total_unsupplied_energy_kwh, 0);
    await page.getByRole('button', {name: '刷新年度任务', exact: true}).click();
    await page.getByText(/覆盖 8760 \/ 8760 步/).waitFor();
    const csv = await page.request.get(root + '/api/study-jobs/' + job.id + '/csv');
    assert(csv.ok());
    const lines = (await csv.text()).trim().split(/\r?\n/);
    assert.equal(lines.length, 8761);
    assert.equal(lines[1].split(',')[0], '0');
    assert.equal(lines[8760].split(',')[0], '8759');
    const report = await page.request.get(root + '/api/study-jobs/' + job.id + '/report');
    assert(report.ok());
    fs.writeFileSync('docs/年度滚动人工报告.html', await report.text());
    await page.getByRole('button', {name: '查看窗口', exact: true}).first().click();
    await page.getByRole('heading', {name: '窗口提交轨迹 · window-00001', exact: true}).waitFor();
    const first = await json(await page.request.get(root + '/api/study-jobs/' + job.id + '/annual-windows/window-00001'));
    const last = await json(await page.request.get(root + '/api/study-jobs/' + job.id + '/annual-windows/window-00365'));
    assert.equal(first.summary.forecast_steps, 48);
    assert.equal(first.committed_rows.length, 24);
    assert.equal(last.state_after.elapsed_hours, 8760);
    assert.equal(last.state_after.start, '2027-01-01T00:00:00');
    await page.screenshot({path: 'docs/年度滚动全年覆盖验证.png', fullPage: false});
    await page.reload();
    await page.getByText('当前工程：年度滚动人工验证 · 版本 1', {exact: true}).waitFor();
    await page.getByRole('button', {name: '05电力电量平衡', exact: true}).click();
    await page.getByRole('button', {name: '逐设备年度滚动', exact: true}).click();
    await page.locator('button.record').first().click();
    await page.getByText(/覆盖 8760 \/ 8760 步/).waitFor();
    const retry = await json(await page.request.post(root + '/api/study-jobs/' + job.id + '/retry'));
    owned.push(retry.id);
    let saved = [];
    for (let index = 0; index < 600; index++) {
      saved = await json(await page.request.get(root + '/api/study-jobs/' + retry.id + '/annual-windows'));
      if (saved.length) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(saved.length > 0);
    await json(await page.request.post(root + '/api/study-jobs/' + retry.id + '/cancel'));
    const cancelled = await waitJob(retry.id);
    assert.equal(cancelled.status, 'cancelled');
    assert.equal(cancelled.result, null);
    saved = await json(await page.request.get(root + '/api/study-jobs/' + retry.id + '/annual-windows'));
    assert(saved.length > 0 && saved.length < 365);
    const partialCsv = await page.request.get(root + '/api/study-jobs/' + retry.id + '/csv');
    assert.equal((await partialCsv.text()).trim().split(/\r?\n/).length, saved.length * 24 + 1);
    const frozen = await json(await page.request.get(root + '/api/study-jobs/' + retry.id + '?include_input=true'));
    assert.equal(frozen.input.project.id, project.id);
    assert.equal(frozen.retry_from, job.id);
    assert.deepEqual(errors, []);
    fs.writeFileSync('docs/年度滚动人工联调.json', JSON.stringify({root, source: '人工验证', job, first, last,
      cancelled, savedWindowCount: saved.length, errors}, null, 2));
    console.log('PASS: actual calendar year 8760 steps/365 windows/87600kWh/43800yuan; committed CSV, report, window states, archive reopen, frozen retry and cancelled partial evidence. Runtime '+job.result.runtime_seconds+'s');
  } finally {
    try {
      for (const id of owned) {
        const response = await page.request.get(root + '/api/study-jobs/' + id);
        if (response.ok() && ['queued', 'running', 'cancel_requested'].includes((await response.json()).status)) {
          await page.request.post(root + '/api/study-jobs/' + id + '/cancel');
        }
      }
    } finally {
      await browser.close();
    }
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
