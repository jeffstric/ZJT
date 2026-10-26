// asset_library.test.js — 资产库公共模块（web/js/asset_library.js）回归测试
// 覆盖：@资产 token 构造与提交前还原、绝对 URL、弹窗 XSS 转义、
// secureSanitize 对入库按钮（button + data-asset-add-src）的存活白名单。

beforeAll(() => {
  require('../js/escape.js');
  require('../js/security.js');
  require('../js/asset_library.js');
});

const createDOMPurify = require('../js/vendor/purify.min.js');

beforeAll(() => {
  // security.js 需要 DOMPurify（若 setup 未注入）；重复注入无副作用
  if (!window.DOMPurify) {
    const purify = createDOMPurify;
    window.DOMPurify = typeof purify === 'function' && typeof purify.createDOMPurify === 'function'
      ? purify.createDOMPurify(window)
      : (typeof purify === 'function' ? purify(window) : purify);
  }
});

function mockFetch(handler) {
  const fn = vi.fn(handler);
  vi.stubGlobal('fetch', fn);
  return fn;
}

function jsonResponse(body, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.querySelectorAll('.al-overlay').forEach(el => el.remove());
  localStorage.clear();
});

describe('@资产 token 构造与还原', () => {
  test('MENTION_PREFIX 与 buildMentionToken', () => {
    expect(window.AssetLibrary.MENTION_PREFIX).toBe('@资产:');
    expect(window.AssetLibrary.buildMentionToken({ id: 42 })).toBe('@资产:42');
  });

  test('resolveMentionTokens：缓存资产还原为 markdown 图片（绝对 URL）', async () => {
    mockFetch(() => jsonResponse({
      code: 0,
      data: {
        items: [{ id: 7, name: '产品主图', file_url: '/upload/asset_library/1/a.png' }],
        total: 1,
      },
    }));
    await window.AssetLibrary.fetchMentionItems('');
    const out = await window.AssetLibrary.resolveMentionTokens('参考 @资产:7 的风格');
    expect(out).toBe(`参考 ![产品主图](${location.origin}/upload/asset_library/1/a.png) 的风格`);
  });

  test('resolveMentionTokens：无权访问/已清除的 token 保留原文', async () => {
    mockFetch(() => jsonResponse({ detail: '资产不存在或无权访问' }, false, 404));
    const out = await window.AssetLibrary.resolveMentionTokens('参考 @资产:999 的风格');
    expect(out).toBe('参考 @资产:999 的风格');
  });

  test('resolveMentionTokens：未携带 token 的文本原样返回且不发请求', async () => {
    const fetchMock = mockFetch(() => jsonResponse({ code: 0, data: {} }));
    const out = await window.AssetLibrary.resolveMentionTokens('普通提示词，无引用');
    expect(out).toBe('普通提示词，无引用');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('resolveMentionTokens：连续数字 id 不误匹配（@资产:123 与 @资产:1234）', async () => {
    mockFetch(() => jsonResponse({
      code: 0,
      data: { items: [{ id: 123, name: 'A', file_url: '/upload/x.png' }], total: 1 },
    }));
    await window.AssetLibrary.fetchMentionItems('');
    const out = await window.AssetLibrary.resolveMentionTokens('@资产:1234');
    // 1234 未在缓存：详情接口 mock 返回的是列表接口结构，详情 data 为空对象 → token 保留
    expect(out).toContain('@资产:1234');
  });

  test('resolveMentionTokens：资产名含 markdown 语法字符（[]()）不破坏图片语法', async () => {
    mockFetch(() => jsonResponse({
      code: 0,
      data: { items: [{ id: 5, name: '产品图(主视觉)[终版]', file_url: '/upload/b.png' }], total: 1 },
    }));
    await window.AssetLibrary.fetchMentionItems('');
    const out = await window.AssetLibrary.resolveMentionTokens('参考 @资产:5');
    // alt 中 []() 已被清洗，输出为合法 markdown 图片
    expect(out).toBe(`参考 ![产品图主视觉终版](${location.origin}/upload/b.png)`);
  });
});

describe('absoluteUrl', () => {
  test('相对 /upload 路径转绝对，外链原样', () => {
    expect(window.AssetLibrary.absoluteUrl('/upload/a.png')).toBe(location.origin + '/upload/a.png');
    expect(window.AssetLibrary.absoluteUrl('https://cdn.example.com/a.png')).toBe('https://cdn.example.com/a.png');
    expect(window.AssetLibrary.absoluteUrl('')).toBe('');
  });
});

describe('入库/浏览弹窗 XSS 转义', () => {
  test('浏览弹窗：资产名/属主名含 HTML 时转义，不产生真实标签', async () => {
    mockFetch((url) => {
      if (String(url).includes('/assets')) {
        return jsonResponse({
          code: 0,
          data: {
            items: [{
              id: 1,
              name: '<img src=x onerror=alert(1)>',
              owner_name: '<script>bad()</script>',
              file_url: '/upload/a.png',
              file_size: 1024,
              can_edit: false,
              user_id: 999,
            }],
            total: 1,
          },
        });
      }
      if (String(url).includes('/groups')) {
        return jsonResponse({ code: 0, data: { groups: [{ id: 1, name: '<b>组</b>', asset_count: 1, can_manage: false }], ungrouped_count: 0 } });
      }
      if (String(url).includes('/quota')) {
        return jsonResponse({ code: 0, data: { quota_bytes: 0, used_bytes: 0 } });
      }
      if (String(url).includes('/status')) {
        return jsonResponse({ code: 0, data: { enabled: true, allowed: true } });
      }
      return jsonResponse({ code: 0, data: {} });
    });
    window.AssetLibrary.openModal();
    // openModal 经 ensureEnabled 异步打开：轮询等 overlay 出现再等渲染
    let overlay = null;
    for (let i = 0; i < 20 && !overlay; i++) {
      await new Promise(r => setTimeout(r, 10));
      overlay = document.querySelector('.al-overlay');
    }
    expect(overlay).toBeTruthy();
    // DOM 语义断言：无 script 元素、无以恶意 src=x 逃逸出的 img、文本节点为字面转义文本
    // （innerHTML 序列化时属性值内的 < 不转义属合法行为，只要未形成真实元素即安全）
    expect(overlay.querySelectorAll('script').length).toBe(0);
    expect(overlay.querySelectorAll('img[src="x"]').length).toBe(0);
    await new Promise(r => setTimeout(r, 0));
    const nameEl = overlay.querySelector('.al-card-name');
    expect(nameEl).toBeTruthy();
    expect(nameEl.textContent).toBe('<img src=x onerror=alert(1)>');
    const badgeEl = overlay.querySelector('.al-card-badge');
    expect(badgeEl.textContent).toBe('<script>bad()</script>');
  });
});

describe('secureSanitize 入库按钮存活（历史消息回放）', () => {
  test('button + data-asset-add-src 保留，onclick 剥离', () => {
    const html = window.secureSanitize(
      '<div class="generated-result-actions">' +
      '<button class="publish-result-btn" data-asset-add-src="https://x.com/a.png" onclick="steal()">入库</button>' +
      '</div>'
    );
    expect(html).toContain('<button');
    expect(html).toContain('data-asset-add-src="https://x.com/a.png"');
    expect(html).not.toMatch(/onclick/i);
  });
});

describe('指定成员：完整账号精确添加', () => {
  function mockUserApi(handler) {
    return mockFetch((url) => {
      const u = String(url);
      if (u.includes('/users?account=')) return jsonResponse(handler(decodeURIComponent(u.split('account=')[1])));
      if (u.includes('/assets/')) return jsonResponse({ code: 0, data: { id: 1, name: 'x', view_permission: 'private', edit_permission: 'private', view_members: [], edit_members: [], group_id: null, file_url: '/upload/a.png' } });
      if (u.includes('/groups')) return jsonResponse({ code: 0, data: { groups: [], ungrouped_count: 0 } });
      return jsonResponse({ code: 0, data: {} });
    });
  }

  async function openEditAndGetBox() {
    window.AssetLibrary.promptEdit({
      id: 1, name: 'x', view_permission: 'specified', edit_permission: 'private',
      view_members: [], edit_members: [],
    });
    await new Promise(r => setTimeout(r, 0));
    return document.querySelector('.al-overlay');
  }

  test('账号存在：加入成员并提示「用户共享成功」', async () => {
    mockUserApi((account) => account === '13800000000'
      ? { code: 0, data: { user: { user_id: 7, display_name: '张三' } } }
      : { code: 0, data: { user: null } });
    const overlay = await openEditAndGetBox();
    const box = overlay.querySelector('[data-al-memberbox="view"]');
    const input = box.querySelector('[data-al-member-search]');
    const msg = box.querySelector('[data-al-member-msg]');
    input.value = '13800000000';
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));
    expect(msg.textContent).toBe('用户共享成功');
    expect(msg.className).toContain('is-ok');
    const tag = box.querySelector('[data-al-member-tags]');
    expect(tag.textContent).toContain('张三');
  });

  test('账号不存在：提示「没有查找到这个用户」，不加入成员', async () => {
    mockUserApi(() => ({ code: 0, data: { user: null } }));
    const overlay = await openEditAndGetBox();
    const box = overlay.querySelector('[data-al-memberbox="view"]');
    const input = box.querySelector('[data-al-member-search]');
    const msg = box.querySelector('[data-al-member-msg]');
    input.value = 'nobody@x.com';
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));
    expect(msg.textContent).toBe('没有查找到这个用户');
    expect(msg.className).toContain('is-error');
    expect(box.querySelector('[data-al-member-tags]').children.length).toBe(0);
  });

  test('空输入不发起请求，直接提示补全', async () => {
    const fetchMock = mockUserApi(() => ({ code: 0, data: { user: null } }));
    const overlay = await openEditAndGetBox();
    const box = overlay.querySelector('[data-al-memberbox="view"]');
    const msg = box.querySelector('[data-al-member-msg]');
    box.querySelector('[data-al-member-add]').click();
    await new Promise(r => setTimeout(r, 0));
    expect(msg.textContent).toContain('请先输入完整账号');
    const calls = fetchMock.mock.calls.filter(c => String(c[0]).includes('/users?account='));
    expect(calls.length).toBe(0);
  });
});
