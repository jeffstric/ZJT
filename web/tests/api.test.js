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
