/**
 * 剧本编排页「单次任务算力上限」前端行为（fix 796d6db2「保存失败前端可见」）。
 *
 * 契约：
 * - 输入校验：非负整数才提交，非法值提示并回显上次生效值 powerBudgetCurrent
 * - 清空输入 = DELETE 偏好回退平台默认
 * - PUT 失败（HTTP 非 2xx / code!=0）时输入框回显上次生效值并展示后端 detail
 * - is_custom 状态控制「恢复默认」按钮可见性
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/script_writer.js'), 'utf8');

const blockStart = source.indexOf('// ===== 单次任务算力上限（PowerBudget） =====');
const blockEnd = source.indexOf('async function loadVendors', blockStart);
const block = source.slice(blockStart, blockEnd);

const payload = (limit, is_custom = false, default_limit = 30) => ({
  code: 0, data: { limit, is_custom, default_limit },
});

function createHarness() {
  document.body.innerHTML = `
    <input id="power-budget-input" />
    <button id="power-budget-reset" style="display:none"></button>
    <span id="power-budget-icon"></span>
  `;
  const showError = vi.fn();
  const updateStatus = vi.fn();
  const checkTokenExpired = vi.fn(() => false);
  const fetchMock = vi.fn();

  const factory = new Function(
    'fetch', 'document', 'window', 'AUTH_TOKEN',
    'checkTokenExpired', 'showError', 'updateStatus',
    `${block};
     return {
      loadPowerBudgetPreference, savePowerBudgetLimit,
      onPowerBudgetChange, resetPowerBudget,
      getState: () => ({ powerBudgetCurrent, powerBudgetDefault, powerBudgetIsCustom }),
    };`
  );
  const api = factory(
    fetchMock, document, { t: null }, 'tok-1',
    checkTokenExpired, showError, updateStatus
  );
  return { api, showError, fetchMock };
}

const jsonResponse = (data, ok = true, status = 200) => ({
  ok, status, json: async () => data,
});

async function seedLoaded(api, fetchMock, { limit = 42, is_custom = true } = {}) {
  fetchMock.mockResolvedValueOnce(jsonResponse(payload(limit, is_custom)));
  await api.loadPowerBudgetPreference();
  fetchMock.mockReset();
  return document.getElementById('power-budget-input');
}

describe('loadPowerBudgetPreference', () => {
  it('GET 携带 Bearer 头并回填输入框与状态', async () => {
    const { api, fetchMock } = createHarness();
    fetchMock.mockResolvedValueOnce(jsonResponse(payload(66, true)));

    await api.loadPowerBudgetPreference();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/user/power-budget');
    expect(init.headers.Authorization).toBe('Bearer tok-1');
    expect(document.getElementById('power-budget-input').value).toBe('66');
    expect(api.getState().powerBudgetCurrent).toBe(66);
    // is_custom=true → 恢复默认按钮可见
    expect(document.getElementById('power-budget-reset').style.display).toBe('');
  });

  it('非自定义时隐藏恢复默认按钮', async () => {
    const { api, fetchMock } = createHarness();
    fetchMock.mockResolvedValueOnce(jsonResponse(payload(30, false)));

    await api.loadPowerBudgetPreference();

    expect(document.getElementById('power-budget-reset').style.display).toBe('none');
    expect(api.getState().powerBudgetIsCustom).toBe(false);
  });
});

describe('onPowerBudgetChange 输入校验', () => {
  it.each(['-5', '1.5', 'abc', 'Infinity'])('非法值 %s 提示并回显上次生效值', async (raw) => {
    const { api, showError, fetchMock } = createHarness();
    await seedLoaded(api, fetchMock, { limit: 42 });

    document.getElementById('power-budget-input').value = raw;
    await api.onPowerBudgetChange();

    expect(showError).toHaveBeenCalled();
    expect(document.getElementById('power-budget-input').value).toBe('42');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('清空输入触发 DELETE（回退平台默认）', async () => {
    const { api, fetchMock } = createHarness();
    await seedLoaded(api, fetchMock, { limit: 42, is_custom: true });
    fetchMock.mockResolvedValue(jsonResponse(payload(30, false)));

    document.getElementById('power-budget-input').value = '';
    await api.onPowerBudgetChange();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/user/power-budget');
    expect(init.method).toBe('DELETE');
    expect(api.getState().powerBudgetIsCustom).toBe(false);
    expect(document.getElementById('power-budget-reset').style.display).toBe('none');
  });

  it('合法整数提交 PUT', async () => {
    const { api, fetchMock } = createHarness();
    await seedLoaded(api, fetchMock, { limit: 42 });
    fetchMock.mockResolvedValue(jsonResponse(payload(55, true)));

    document.getElementById('power-budget-input').value = '55';
    await api.onPowerBudgetChange();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/user/power-budget');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ limit: 55 });
    expect(api.getState().powerBudgetCurrent).toBe(55);
  });

  it('0（不限制）是合法值', async () => {
    const { api, fetchMock } = createHarness();
    await seedLoaded(api, fetchMock, { limit: 42 });
    fetchMock.mockResolvedValue(jsonResponse(payload(0, true)));

    document.getElementById('power-budget-input').value = '0';
    await api.onPowerBudgetChange();

    expect(fetchMock).toHaveBeenCalled();
  });
});

describe('保存失败前端可见', () => {
  it('HTTP 500 时回显上次生效值并展示后端 detail', async () => {
    const { api, showError, fetchMock } = createHarness();
    await seedLoaded(api, fetchMock, { limit: 42 });
    fetchMock.mockResolvedValue(jsonResponse({ detail: '系统繁忙' }, false, 500));

    document.getElementById('power-budget-input').value = '99';
    await api.onPowerBudgetChange();

    expect(showError).toHaveBeenCalled();
    expect(showError.mock.calls[0][0]).toContain('系统繁忙');
    // 关键：回显上次生效值，避免误以为 99 已生效
    expect(document.getElementById('power-budget-input').value).toBe('42');
  });

  it('HTTP 200 但 code!=0 时同样回显旧值', async () => {
    const { api, showError, fetchMock } = createHarness();
    await seedLoaded(api, fetchMock, { limit: 42 });
    fetchMock.mockResolvedValue(jsonResponse({ code: 1, error: '参数非法' }));

    document.getElementById('power-budget-input').value = '99';
    await api.onPowerBudgetChange();

    expect(showError).toHaveBeenCalled();
    expect(document.getElementById('power-budget-input').value).toBe('42');
  });
});
