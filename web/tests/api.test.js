// api.js 工具函数测试

// 模拟依赖的全局函数
globalThis.getAuthToken = () => 'test_auth_token';
globalThis.getUserId = () => 'test_user_id';
globalThis.showToast = vi.fn();
globalThis.TaskConfig = { getTaskIdByKey: () => null };
globalThis.state = { testMode: false };

// 加载 api.js
const api = require('../js/api.js');

// ── getAuthHeaders ──
describe('getAuthHeaders', () => {
  test('返回包含 Authorization 和 X-User-Id 的对象', () => {
    const headers = api.getAuthHeaders();
    expect(headers).toHaveProperty('Authorization');
    expect(headers).toHaveProperty('X-User-Id');
  });

  test('Authorization 值为 auth_token', () => {
    const headers = api.getAuthHeaders();
    expect(headers['Authorization']).toBe('test_auth_token');
  });

  test('X-User-Id 值为 user_id', () => {
    const headers = api.getAuthHeaders();
    expect(headers['X-User-Id']).toBe('test_user_id');
  });

  test('无 auth_token 时返回空字符串', () => {
    const origGetAuthToken = globalThis.getAuthToken;
    globalThis.getAuthToken = () => '';
    const headers = api.getAuthHeaders();
    expect(headers['Authorization']).toBe('');
    globalThis.getAuthToken = origGetAuthToken;
  });

  test('无 user_id 时返回空字符串', () => {
    const origGetUserId = globalThis.getUserId;
    globalThis.getUserId = () => '';
    const headers = api.getAuthHeaders();
    expect(headers['X-User-Id']).toBe('');
    globalThis.getUserId = origGetUserId;
  });
});

// ── appendAuthToForm ──
describe('appendAuthToForm', () => {
  test('向 FormData 追加 user_id 和 auth_token', () => {
    const form = new FormData();
    api.appendAuthToForm(form);
    expect(form.get('user_id')).toBe('test_user_id');
    expect(form.get('auth_token')).toBe('test_auth_token');
  });

  test('无 user_id 时不追加', () => {
    const origGetUserId = globalThis.getUserId;
    globalThis.getUserId = () => '';
    const form = new FormData();
    api.appendAuthToForm(form);
    expect(form.has('user_id')).toBe(false);
    expect(form.get('auth_token')).toBe('test_auth_token');
    globalThis.getUserId = origGetUserId;
  });

  test('无 auth_token 时不追加', () => {
    const origGetAuthToken = globalThis.getAuthToken;
    globalThis.getAuthToken = () => '';
    const form = new FormData();
    api.appendAuthToForm(form);
    expect(form.get('user_id')).toBe('test_user_id');
    expect(form.has('auth_token')).toBe(false);
    globalThis.getAuthToken = origGetAuthToken;
  });

  test('两者都为空时不追加任何字段', () => {
    const origGetUserId = globalThis.getUserId;
    const origGetAuthToken = globalThis.getAuthToken;
    globalThis.getUserId = () => '';
    globalThis.getAuthToken = () => '';
    const form = new FormData();
    api.appendAuthToForm(form);
    expect(form.has('user_id')).toBe(false);
    expect(form.has('auth_token')).toBe(false);
    globalThis.getUserId = origGetUserId;
    globalThis.getAuthToken = origGetAuthToken;
  });
});

// ── authPostForm ──
describe('authPostForm', () => {
  test('携带 Bearer Authorization 头 POST FormData', async () => {
    const origFetch = globalThis.fetch;
    const fetchCalls = [];
    globalThis.fetch = (url, opts) => {
      fetchCalls.push({ url, opts });
      return Promise.resolve({ ok: true });
    };
    const form = new FormData();
    await api.authPostForm('/api/image-edit', form);
    expect(fetchCalls).toHaveLength(1);
    expect(fetchCalls[0].url).toBe('/api/image-edit');
    expect(fetchCalls[0].opts.method).toBe('POST');
    expect(fetchCalls[0].opts.headers['Authorization']).toBe('Bearer test_auth_token');
    expect(fetchCalls[0].opts.body).toBe(form);
    globalThis.fetch = origFetch;
  });

  test('无 auth_token 时不带 Authorization 头（仍可走 cookie 会话）', async () => {
    const origGetAuthToken = globalThis.getAuthToken;
    const origFetch = globalThis.fetch;
    globalThis.getAuthToken = () => '';
    const fetchCalls = [];
    globalThis.fetch = (url, opts) => {
      fetchCalls.push({ url, opts });
      return Promise.resolve({ ok: true });
    };
    await api.authPostForm('/api/text-to-image', new FormData());
    expect(fetchCalls[0].opts.headers).toEqual({});
    globalThis.fetch = origFetch;
    globalThis.getAuthToken = origGetAuthToken;
  });
});

// ── extractApiErrorMessage ──
describe('extractApiErrorMessage', () => {
  test('优先返回字符串型 detail', () => {
    expect(api.extractApiErrorMessage({ detail: '算力不足' }, { status: 400 })).toBe('算力不足');
  });

  test('其次返回字符串型 message', () => {
    expect(api.extractApiErrorMessage({ message: '配额超限' }, { status: 429 })).toBe('配额超限');
  });

  test('401 且无 detail/message 时返回重新登录引导而非"提交任务失败"', () => {
    const msg = api.extractApiErrorMessage(
      { success: false, error_code: 'missing_auth_token' },
      { status: 401 }
    );
    expect(msg).toContain('重新登录');
    expect(msg).not.toBe('提交任务失败');
  });

  test('非 401 且无 detail/message 时保留原兜底文案', () => {
    expect(api.extractApiErrorMessage({}, { status: 500 })).toBe('提交任务失败');
  });

  test('data 为空对象/无 res 时安全返回兜底文案', () => {
    expect(api.extractApiErrorMessage({}, undefined)).toBe('提交任务失败');
    expect(api.extractApiErrorMessage(undefined, undefined)).toBe('提交任务失败');
  });
});
