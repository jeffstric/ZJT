/**
 * paused 态拆分 UI 辅助：继续拆分按钮文案 + 放弃并重新拆分 + cancelAndWaitTerminal。
 */
require('../js/script_split_task.js');

const ScriptSplitTask = window.ScriptSplitTask;

describe('ScriptSplitTask.applyPausedSplitButtonUI', () => {
  test('paused 时按钮文案改为「继续拆分」', () => {
    document.body.innerHTML = `
      <button id="splitBtn">拆分幕</button>
      <button id="splitGridBtn"><svg></svg><span class="script-split-grid-btn-label">拆分幕 + 宫格生图</span></button>
    `;
    const splitBtn = document.querySelector('#splitBtn');
    const splitGridBtn = document.querySelector('#splitGridBtn');

    ScriptSplitTask.applyPausedSplitButtonUI(splitBtn, splitGridBtn, true);
    expect(splitBtn.textContent).toBe('继续拆分');
    expect(splitGridBtn.querySelector('.script-split-grid-btn-label').textContent)
      .toBe('继续拆分 + 宫格生图');
    // svg 不应被破坏
    expect(splitGridBtn.querySelector('svg')).not.toBeNull();
  });

  test('非 paused 恢复默认文案', () => {
    document.body.innerHTML = `
      <button id="splitBtn">继续拆分</button>
      <button id="splitGridBtn"><span class="script-split-grid-btn-label">继续拆分 + 宫格生图</span></button>
    `;
    const splitBtn = document.querySelector('#splitBtn');
    const splitGridBtn = document.querySelector('#splitGridBtn');

    ScriptSplitTask.applyPausedSplitButtonUI(splitBtn, splitGridBtn, false);
    expect(splitBtn.textContent).toBe('拆分幕');
    expect(splitGridBtn.querySelector('.script-split-grid-btn-label').textContent)
      .toBe('拆分幕 + 宫格生图');
  });

  test('元素缺失时安全跳过', () => {
    expect(() => ScriptSplitTask.applyPausedSplitButtonUI(null, null, true)).not.toThrow();
  });
});

describe('ScriptSplitTask.attachResplitButton / removeResplitButton', () => {
  test('挂载按钮且点击触发回调（stopPropagation）', () => {
    document.body.innerHTML = '<div id="status">任务暂停</div>';
    const statusEl = document.querySelector('#status');
    let clicked = 0;
    ScriptSplitTask.attachResplitButton(statusEl, () => { clicked += 1; });

    const btn = statusEl.querySelector('.script-resplit-btn');
    expect(btn).not.toBeNull();
    expect(btn.textContent).toBe('放弃并重新拆分');
    btn.click();
    expect(clicked).toBe(1);
  });

  test('重复挂载幂等', () => {
    document.body.innerHTML = '<div id="status"></div>';
    const statusEl = document.querySelector('#status');
    ScriptSplitTask.attachResplitButton(statusEl, () => {});
    ScriptSplitTask.attachResplitButton(statusEl, () => {});
    expect(statusEl.querySelectorAll('.script-resplit-btn').length).toBe(1);
  });

  test('移除按钮', () => {
    document.body.innerHTML = '<div id="status"></div>';
    const statusEl = document.querySelector('#status');
    ScriptSplitTask.attachResplitButton(statusEl, () => {});
    ScriptSplitTask.removeResplitButton(statusEl);
    expect(statusEl.querySelector('.script-resplit-btn')).toBeNull();
    expect(() => ScriptSplitTask.removeResplitButton(null)).not.toThrow();
  });
});

describe('ScriptSplitTask.cancelAndWaitTerminal', () => {
  test('取消后轮询到终态即返回', async () => {
    const calls = [];
    global.fetch = vi.fn((url) => {
      calls.push(String(url));
      if (String(url).includes('/cancel')) {
        return Promise.resolve({ json: () => Promise.resolve({ code: 0, data: {} }) });
      }
      // 第一次查询 cancelling，第二次查询 cancelled
      const status = calls.filter((u) => u.includes('/tasks/')).length >= 2
        ? 'cancelled' : 'cancelling';
      return Promise.resolve({
        json: () => Promise.resolve({ code: 0, data: { status } }),
      });
    });

    const finalStatus = await ScriptSplitTask.cancelAndWaitTerminal(123);
    expect(finalStatus).toBe('cancelled');
    expect(calls.some((u) => u.includes('/cancel'))).toBe(true);
  });

  test('取消接口失败时抛错', async () => {
    global.fetch = vi.fn(() => Promise.resolve({
      json: () => Promise.resolve({ code: -1, message: '任务已处于终态' }),
    }));
    await expect(ScriptSplitTask.cancelAndWaitTerminal(456)).rejects.toThrow('任务已处于终态');
  });

  test('超时未终态抛错', async () => {
    vi.useFakeTimers();
    global.fetch = vi.fn((url) => {
      if (String(url).includes('/cancel')) {
        return Promise.resolve({ json: () => Promise.resolve({ code: 0, data: {} }) });
      }
      return Promise.resolve({
        json: () => Promise.resolve({ code: 0, data: { status: 'cancelling' } }),
      });
    });
    const promise = ScriptSplitTask.cancelAndWaitTerminal(789, { timeoutMs: 100 });
    const expectation = expect(promise).rejects.toThrow('取消原任务超时');
    // 推进轮询 sleep（1500ms/轮）与超时时钟
    await vi.advanceTimersByTimeAsync(3200);
    await expectation;
    vi.useRealTimers();
  });
});

describe('ScriptSplitTask.tt', () => {
  test('i18n 缺键时回退默认文案', () => {
    window.t = () => 'script_not_exist_key';
    expect(ScriptSplitTask.tt('script_not_exist_key', '默认文案')).toBe('默认文案');
  });

  test('i18n 命中时返回翻译', () => {
    window.t = (key) => (key === 'script_split_continue_btn' ? '继续拆分' : key);
    expect(ScriptSplitTask.tt('script_split_continue_btn', 'x')).toBe('继续拆分');
  });

  test('window.t 未定义时回退默认文案', () => {
    const original = window.t;
    delete window.t;
    expect(ScriptSplitTask.tt('any', '默认')).toBe('默认');
    window.t = original;
  });
});
