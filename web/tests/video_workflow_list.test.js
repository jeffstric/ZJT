// state.js 的函数在浏览器中通过 <script> 标签加载成为全局函数
// 在测试环境中需要手动挂载到 globalThis
const stateModule = require('../js/state.js');
globalThis.getAuthToken = stateModule.getAuthToken;
globalThis.getUserId = stateModule.getUserId;
globalThis.showToast = stateModule.showToast;
globalThis.state = stateModule.state;

const { ensureLoggedIn } = require('../js/video_workflow_list.js');

describe('video_workflow_list - ensureLoggedIn', () => {
  beforeEach(() => {
    localStorage.clear();
    // mock toast DOM
    const toast = document.createElement('div');
    toast.id = 'toast';
    document.body.appendChild(toast);
    vi.useFakeTimers();
  });

  afterEach(() => {
    document.body.innerHTML = '';
    localStorage.clear();
    vi.useRealTimers();
  });

  test('有 user_id 时返回 true', () => {
    localStorage.setItem('user_id', 'user_123');
    expect(ensureLoggedIn()).toBe(true);
  });

  test('无 user_id 时返回 false 并显示 toast', () => {
    expect(ensureLoggedIn()).toBe(false);
    const toast = document.getElementById('toast');
    expect(toast.textContent).toBeTruthy();
    expect(toast.classList.contains('show')).toBe(true);
  });
});
