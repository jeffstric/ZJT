const { getAuthToken, getUserId, showToast } = require('../js/state.js');

describe('getAuthToken', () => {
  test('localStorage 有值时返回 token', () => {
    localStorage.setItem('auth_token', 'test_token_123');
    expect(getAuthToken()).toBe('test_token_123');
  });

  test('localStorage 无值时返回空字符串', () => {
    expect(getAuthToken()).toBe('');
  });
});

describe('getUserId', () => {
  test('localStorage 有值时返回 user_id', () => {
    localStorage.setItem('user_id', 'user_456');
    expect(getUserId()).toBe('user_456');
  });

  test('localStorage 无值时返回空字符串', () => {
    expect(getUserId()).toBe('');
  });
});

describe('showToast', () => {
  beforeEach(() => {
    // 创建 toast DOM 元素
    const toast = document.createElement('div');
    toast.id = 'toast';
    document.body.appendChild(toast);
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  test('设置消息文本', () => {
    vi.useFakeTimers();
    showToast('操作成功');
    const toast = document.getElementById('toast');
    expect(toast.textContent).toBe('操作成功');
  });

  test('添加 show class', () => {
    vi.useFakeTimers();
    showToast('测试消息');
    const toast = document.getElementById('toast');
    expect(toast.classList.contains('show')).toBe(true);
  });

  test('指定 type 参数时添加对应 class', () => {
    vi.useFakeTimers();
    showToast('错误', 'error');
    const toast = document.getElementById('toast');
    expect(toast.classList.contains('error')).toBe(true);
  });

  test('3 秒后移除 show class', () => {
    vi.useFakeTimers();
    showToast('即将消失');
    const toast = document.getElementById('toast');
    expect(toast.classList.contains('show')).toBe(true);

    vi.advanceTimersByTime(3000);
    expect(toast.classList.contains('show')).toBe(false);
  });
});
