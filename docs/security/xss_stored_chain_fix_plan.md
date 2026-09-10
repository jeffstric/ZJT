# 前端存储型 XSS 链修复方案（P1）

> 对应安全审计：[安全审计 P1] 前端存储型 XSS 链：LLM 输出渲染无净化 + 落库、sanitizeHtml 正则可绕过、token 存 localStorage。
> 审计三项在当前 develop（c045c64b）上逐条核实属实，本文为修复设计。
>
> **实施状态（develop_2837 分支）：阶段 1/2/3a/3b/3c/4a 第一步/4b/5 已全部落地**，
> 与原设计的差异及遗留事项见文末「实施记录」。

## 0. 设计原则

1. **净化时机在渲染端**：LLM 输出原文必须原样落库（剥离会破坏代码块/示例 HTML），唯一可靠的净化时机是「插入 DOM 之前」。落库侧只做纵深防御，不做白名单改写。
2. **白名单，不是黑名单正则**：废弃正则净化器，统一走 DOMPurify 显式白名单。正则黑名单永远存在新绕过（无引号属性、`/` 分隔、实体编码等已实测绕过现有实现）。
3. **单一入口**：所有「不可信文本 → HTML」渲染收敛到一个函数；所有 escapeHtml 副本收敛到公共模块。
4. **分 MR 独立上线**：每个阶段可单独合入、单独回滚，按风险从低到高排序。
5. **遵守项目红线**（AGENTS.md）：新中间件必须 async 非阻塞；DB 操作走 `asyncio.to_thread`；新增常量入 `config/constant.py`；改动后同步 docs。

---

## 阶段 1（P0）：统一净化入口 `secureRenderMarkdown`

### 1.1 引入 DOMPurify（本地 vendor）

项目前端无构建体系，第三方库一律本地化（`web/js/vendor/` 已有 marked/axios/vue 等），离线部署不受影响：

- 下载 DOMPurify 3.x 的 `purify.min.js` → `web/js/vendor/purify.min.js`
- 仅两个 markdown 页面需要引入，且必须**先 marked 后 purify 后 security.js**：

```html
<!-- marketing_agent.html / script_writer.html，紧跟 marked.min.js -->
<script src="/js/vendor/purify.min.js"></script>
<script src="/js/security.js"></script>
```

### 1.2 新建 `web/js/security.js`（唯一净化入口）

```javascript
// DOMPurify 白名单：显式列举，事件属性（on*）一律不在白名单即被移除。
// 不依赖 DOMPurify 默认行为，避免版本升级时默认清单变化引入回归。
(function () {
    'use strict';

    var ALLOWED_TAGS = [
        // markdown 基础
        'p','br','hr','h1','h2','h3','h4','h5','h6','blockquote','pre','code',
        'ul','ol','li','del','em','strong','b','i','s','sup','sub','table','thead',
        'tbody','tr','th','td','a','img','span','div','input',
        // 营销 agent 渲染的媒体（renderMarkdown 会把裸视频 URL 转成 <video>）
        'video','audio','source'
    ];
    var ALLOWED_ATTR = [
        'href','src','alt','title','class','id','target','rel',
        'style','controls','preload','type','disabled','checked'
    ];

    window.secureSanitize = function (html) {
        return DOMPurify.sanitize(html, {
            ALLOWED_TAGS: ALLOWED_TAGS,
            ALLOWED_ATTR: ALLOWED_ATTR,
            // 锚点一律强制新窗口 + 断开 opener，防反向 tabnabbing
            ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel|blob):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i,
            KEEP_CONTENT: false   // script/iframe 等危险标签连同内容一起丢弃
        });
    };

    // 唯一 markdown 渲染入口：parse 之后、返回之前强制净化
    window.secureRenderMarkdown = function (text) {
        if (typeof marked === 'undefined' || typeof window.secureSanitize !== 'function') {
            return window.escapeHtml ? window.escapeHtml(text) : String(text || '');
        }
        var raw;
        try { raw = marked.parse(String(text || '')); }
        catch (e) { return window.escapeHtml(String(text || '')); }
        return window.secureSanitize(raw);
    };
})();
```

要点：

- **事件属性不进 `ALLOWED_ATTR`** → 现有 `renderMarkdown` 拼进 HTML 的内联 `onclick`（marketing_agent.js:1677 的图片点击放大）会被一并剥掉，因此**必须同 MR 完成 1.3 的事件委托改造**，否则功能回归。
- `KEEP_CONTENT: false` 保证 `<script>alert(1)</script>` 连内容一起消失。

### 1.3 marketing_agent.js 改造（渲染 + 事件委托）

位置：`web/js/marketing_agent.js:1616`（`renderMarkdown`）、`web/marketing_agent.html:181`。

1. `renderMarkdown` 内部改为：`marked.parse` → 立即 `secureSanitize` → 再执行现有的图片/视频 URL 代理替换（1665-1701 行）。代理替换作用于**净化后**的 HTML，其输入是白名单内的 `src` 属性值、输出是代码控制的同源签名 URL，不重新引入注入面。
2. 内联 `onclick` 改为 **data 属性 + 容器级事件委托**：

```javascript
// 原来（1677 行）：return `<img ... onclick="document.getElementById('imgModal')...">`;
// 改为：
return `<img${proxiedAttrs} data-full-src="${escapeHtmlAttr(displaySrc)}" style="..." alt="...">`;

// 页面初始化时一次性委托（聊天容器挂一次即可，重新加载/切会话不重复绑）：
chatMessages.addEventListener('click', function (e) {
    var img = e.target.closest('img[data-full-src]');
    if (!img) return;
    showImageModal(img.dataset.fullSrc);
});
```

注意 video_workflow.html 有"重新加载复原"要求，本改造不涉及工作流节点，无此顾虑；事件委托挂在容器上，历史消息重渲染天然复用。

3. 历史消息回放（`parseHistoryMessage` → `v-html="renderMarkdown(...)"`）走同一函数即自动净化，**存量已渲染 HTML 入库的旧消息无需数据迁移**——渲染端白名单会剥掉其中残留的事件属性与危险标签。

### 1.4 script_writer.js 改造（废弃正则净化器）

位置：`web/js/script_writer.js:1767-1787`。

- 删除 `sanitizeHtml`（1767-1776 行），`renderMarkdown`（1778 行）改为调用 `window.secureRenderMarkdown`。
- 自定义 renderer 与 hljs 高亮（1746-1763 行）保留：hljs 输出 `span/code/pre + class`，均在白名单内。
- 该文件其余 27 处 `innerHTML =` 拼接走 escapeHtml 的调用不在本阶段动（阶段 2 收敛副本后天然受益）。

### 1.5 排查清单（本阶段确认过、暂不动）

| 渲染点 | 现状 | 结论 |
|---|---|---|
| `marketing_agent.js:1662` | 无净化 | 阶段 1 修复 |
| `script_writer.js:1781` | 正则净化 | 阶段 1 替换 |
| `index.html:923` `v-html="termsContent"` | 管理员发布的条款内容 | 内容管理员可控，低危；改为 `secureSanitize` 一行即可，顺带做 |
| `storyboard/js/*.js` 27 处 innerHTML | 均经本地 escapeHtml 拼接 | 非 markdown 渲染；阶段 2 收敛副本时统一复核 |
| `storyboard` AI 聊天（`api/storyboard.py:4917` history 前端渲染） | 拼接渲染 | 排查确认非富文本路径，副本收敛时复核 |

---

## 阶段 2（P1）：escapeHtml 副本收敛

现状 13 文件 16 处定义，且已确认互不一致（`script_writer_library.js:173` 降级版不转义单引号、`marketing_inspiration.js:7` escapeHtmlAttr 不转义单引号——属性上下文可逃逸）。`web/js/utils.js:24` 已有公共 `window.escapeHtml` 但仅 2 个页面引入。

### 做法

1. `utils.js` 增补 `window.escapeHtmlAttr`（额外转义单引号）并导出；两个函数补注释「新增转义需求一律改这里，禁止再拷贝副本」。
2. 全部 HTML 页面统一引入 `<script src="/js/utils.js"></script>`（放在业务 js 之前）。
3. 各副本文件**删除函数体、保留同名薄别名**，避免触碰成百上千调用点：

```javascript
// 例：marketing_agent.js 原 304/316 行的两份实现替换为
const escapeHtml = window.escapeHtml;
const escapeHtmlAttr = window.escapeHtmlAttr;
```

嵌套闭包内的（script_writer.js、marketing_agent.js）同理，在闭包顶部赋别名。

4. 收敛清单（定义位置 → 处理）：

| 文件 | 定义 | 处理 |
|---|---|---|
| `js/utils.js:24` | escapeHtml | 公共版，增补 escapeHtmlAttr |
| `js/marketing_agent.js:304,316` | escapeHtmlAttr/escapeHtml | 删实现，留别名 |
| `js/script_writer.js:3672,3678` | escapeHtml/escapeHtmlAttr | 同上 |
| `js/script_writer.js:1767` | sanitizeHtml | 阶段 1 已删 |
| `js/marketing_inspiration.js:7,15` | escapeHtmlAttr/escapeHtml | 同上（修复单引号缺口） |
| `js/script_writer_library.js:173` | escapeHtmlLocal | 删，直接用 window 版（修复单引号缺口） |
| `js/storyboard/events.js:3792`、`render.js:84`、`reference_variant_selector.js:13` | escapeHtml | 同上 |
| `js/storyboard_list.js:39`、`js/agent_message_dedupe.js:27`、`js/dialogue_group_node.js:8`、`js/create_workflow_modal.js:76`（escapeHtmlSafe）、`external_recharge.html:175` | escapeHtml | 同上 |

---

## 阶段 3（P1）：token 治理

现状：30 天 Bearer token + 手机号存 localStorage（`index_app.js:309/1036/2041`、`video_workflow_list.js:526`、有效期常量 `perseids_server/services/auth_service.py:31`）；且 token 还通过 URL query 传递（`video_workflow.html:1224` iframe、`api.js:237/334`），存在 Referer/历史记录/日志泄漏面。

### 3a. 删除 URL query 传 token（低风险，先行合入）

- `video_workflow.html:1224`：iframe 与父页同源共享 localStorage（`computing_power_logs.html:416` 已注释说明），`?auth_token=` 参数直接删除，iframe 内已自行读 localStorage。
- `api.js:237/334`：`?auth_token=` 改为 `Authorization: Bearer` 头；同步检查 `/api/get-status` 等后端 handler 增加 header 读取（后端 `perseids_server/client.py:_extract_token_from_headers` 已是标准入口）。
- 全局 grep 确认无残留 `auth_token=` 进 URL。

### 3b. 缩短有效期 + 滑动续期

- `TOKEN_EXPIRE_DAYS` 30 → 7，常量迁至 `config/constant.py`（AGENTS.md 第 5 条），`auth_service.py` 引用常量。
- 滑动续期：在统一身份解析函数（3c）中，对「剩余有效期 < 2 天且活跃」的 token 顺延 `expire_time`（`UserTokensModel` 增加 `touch` 方法，DB 操作走 `asyncio.to_thread` 保持非阻塞）。用户持续活跃则免登录，闲置 7 天过期。
- 无需 alembic 迁移（不改表结构）。

### 3c. HttpOnly Cookie 双通道（根治，中期）

不直接废弃 Authorization header——`storyboard-agent-api` 等 API 客户端依赖它。设计为**浏览器走 cookie、程序走 header** 的双通道：

1. 登录成功响应 `Set-Cookie: auth_token=<token>; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=604800`（登录接口在 `perseids_server` auth 路由，与现有 token 签发同处）。
2. 新增统一身份解析辅助函数（放 `perseids_server/utils/` 或 `utils/`，所有 handler 复用）：

```python
async def resolve_request_identity(request: Request) -> Optional[int]:
    """优先 Authorization header（程序客户端/agent token），回退 HttpOnly cookie（浏览器）。"""
    token = _extract_token_from_headers(request.headers)
    if not token:
        token = request.cookies.get('auth_token')  # 常量入 config/constant.py
    if not token:
        return None
    return await asyncio.to_thread(AuthService.verify_token, token)
```

3. 现有 27 处 `AuthService.verify_token`/`get_user_id_by_token` 调用点分批迁移到该函数（鸭子签名一致，配 CI 清单防漏改）。
4. CSRF：SameSite=Strict 已挡跨站携带 cookie；本项目写操作均为 POST/PUT 且多数要求自定义 header/JSON body（简单表单请求发不出），风险足够低；敏感操作（改密、提现类）追加 `Origin` 校验一行即可。
5. 前端改造：`getAuthToken()`（state.js:196）及相关 localStorage 读写改为「不存 token、不带凭据的 fetch（`credentials: 'same-origin'` 默认即带 cookie）」。`admin.js:1293`、`computing_power_logs.html:416`、`video_workflow.html:1213` 的读取随之删除。
6. localStorage 中的 `phone`（`index_app.js:310/1037/2042`）是 PII 非凭据：XSS 拿走价值低，但建议改为仅存脱敏值（`138****1234`），完整手机号从 profile 接口实时取。

### 兼容期策略

cookie 与 header 双读后，旧版本前端（localStorage 模式）继续用 header 正常工作，前端发版后可观察一段时间再考虑在 localStorage 写入处加 deprecation 日志。

---

## 阶段 4（P2）：纵深防御

### 4a. CSP 分步（不可一步到位）

项目 HTML 大量内联 `<script>` 且（阶段 1 改造后）基本消除内联事件，`script-src 'self'` 一上来就会全站白屏。分三步：

1. **立即**：中间件只加无副作用的指令头（新 `@app.middleware("http")`，纯 async 加 response header，不碰 DB/IO，符合非阻塞红线）：

   ```
   Content-Security-Policy: object-src 'none'; base-uri 'none'; frame-ancestors 'self'
   X-Content-Type-Options: nosniff
   Referrer-Policy: strict-origin-when-cross-origin
   ```

   `base-uri 'none'` 直接封死审计提到的 `<base href>` 攻击面；`frame-ancestors 'self'` 允许 computing_power_logs 同源 iframe。
2. **第二步**：`Content-Security-Policy-Report-Only` 加 `script-src 'self'` + report-uri，收集内联脚本清单（各 HTML 内联 JS 需 nonce 化改造，量大，独立专项）。
3. **第三步**：report 清零后切 enforcement。

### 4b. CORS 收紧（本次调查顺带发现）

`server.py:569` `allow_origins=["*"]` 与 `allow_credentials=True` 组合不当。改为配置化白名单（`config/unified_config.py`），无跨域部署需求时直接去掉 credentials 或限 `self`。

### 4c. 落库侧（可选，默认不做）

后端剥离会破坏 LLM 正常输出的代码块内容（剧本场景高发），**推荐不做**；若合规要求纵深，仅在 `ConversationRecorder.append_message` 对 assistant 消息剥 `<script>/<iframe>/<object>/<embed>` 完整标签（只删标签不动属性，避免误伤正文），做成开关入 `unified_config`，默认关。

---

## 阶段 5：防回归

1. **vitest 单测**（`web/tests/security.test.js`）：XSS payload 回归集，覆盖本次审计的全部绕过向量：

   ```
   <img src=x onerror=...> / <a href=javascript:alert(1)>（无引号）
   &#106;avascript: 实体编码 / <img/src=x/onerror=...>（/ 分隔）
   <iframe srcdoc=...> / <base href=...> / <svg onload=...> / data:text/html
   ```

   断言 `secureRenderMarkdown` 输出不含 `onerror=`、`javascript:`、`<script`、`<iframe`、`<base`。CI 已跑 vitest，天然拦截。

2. **CI lint**（仿 `scripts/lint_blocking_calls.py` 体系新增 `scripts/lint_frontend_xss.py`）：
   - 禁止 `marked.parse(` 出现在 `secureRenderMarkdown` 之外；
   - 禁止新增 `function escapeHtml`/`function sanitizeHtml` 定义（web 目录）；
   - 禁止 `?auth_token=` 进 URL 拼接。
3. **docs 同步**：本文档随各 MR 更新完成状态；`AGENTS.md` 增补一条：「前端渲染不可信文本（LLM 输出/用户输入/历史消息）必须走 `window.secureRenderMarkdown`，禁止裸 `marked.parse` + innerHTML/v-html」。

---

## 实施顺序与工作量

| MR | 内容 | 风险 | 工作量 | 依赖 |
|---|---|---|---|---|
| MR1 | 阶段 1：purify vendor + security.js + 两处 renderMarkdown 改造 + onclick 委托化 + index.html termsContent | 低（有单测护栏） | 1~1.5 天 | 无 |
| MR2 | 阶段 2：escapeHtml 副本收敛（13 文件） | 低（纯等价替换+修复两处单引号缺口） | 0.5~1 天 | MR1（security.js 依赖 utils） |
| MR3 | 阶段 3a：删 URL query 传 token | 低 | 0.5 天 | 无（可与 MR1 并行） |
| MR4 | 阶段 3b+3c：有效期/续期 + cookie 双通道 | 中（触 27 处校验点 + 全前端认证读取） | 3~5 天 | MR3 |
| MR5 | 阶段 4+5：CSP 第一步头 + CORS 收紧 + lint/测试/docs | 低 | 1 天 | MR1 |

MR1+MR2+MR3 合入后，审计所述「LLM 输出 → 渲染 → 拖库」链即告切断（渲染端白名单 + 无 URL 泄漏面）；MR4 完成后凭据彻底不进 JS 可读存储，XSS 即便发生也仅能以用户身份发当次请求，无法持久窃取凭据。

---

## 实施记录（develop_2837）

### 与原设计的差异

| 设计 | 实际实施 | 原因 |
|---|---|---|
| 转义函数收敛到 `utils.js` | 新建 `web/js/escape.js`（escapeHtml/escapeHtmlAttr） | utils.js 为 video_workflow 节点工具集，不宜全站引入；escape.js 为纯转义、零依赖 |
| 13 文件副本全部删为薄别名 | 12 处收敛；`agent_message_dedupe.js`、`script_writer_library.js`、storyboard 三个 ES module 保留「优先 window.escapeHtml，Node/Vitest 环境降级」的实现 | 这些文件会被 vitest 在无 window 环境直接 import（tests 已验证）；降级实现与权威版逐字等价，CI X1 规则锁定只减不增 |
| — | `marketing_agent.js` 的 `escapeHtmlAttr` 保留（JS 字符串字面量转义器，与 HTML 属性转义语义不同），已加注释防混用 | 它往内联 JS 上下文嵌值，额外转义反斜杠/换行 |
| — | `script_writer.js` 的 `escapeHtml` 保留 `\n → <br>` 历史行为，函数体改为统一转义后再替换 | 调用点依赖该行为 |
| cookie 双通道后端改 27 处校验点 | **零改动校验点**：新增 `auth_cookie_translation_middleware` 把 cookie 翻译成 Authorization 头 | 中间件是唯一咽喉，风险与工作量大幅降低 |
| CSP 第一步仅 3 指令 | 加了 `form-action 'self'` | 同为无副作用的强指令，一并收下 |
| — | 登录态 UI 一致性：`index_app.js` 新增 `cookieSession` 状态 + `probeCookieSession()`（登录标记 `logged_in` + `/api/user/role` 探测），19 处 `!this.authToken` gating 统一改为「authToken 或 cookieSession」 | cookie 会话下若只看 localStorage 会误判为未登录 |
| — | `/api/get-status` 后端未改 | 其 auth_token Query 参数从未被函数体使用（历史遗留），前端删 query 无行为差异 |

### 新增文件

- `web/js/vendor/purify.min.js` — DOMPurify 3.2.6（本地 vendor，UMD）
- `web/js/escape.js` — HTML 转义唯一权威实现（window.escapeHtml / window.escapeHtmlAttr）
- `web/js/security.js` — secureSanitize / secureRenderMarkdown / migrateLegacyOnclick
- `scripts/lint_frontend_xss.py` — CI 防回归（X1 转义副本 / X2 裸 marked.parse / X3 URL token / X4 生成内容内联 onclick）
- `web/tests/security.test.js` — 45 条用例（转义完整性、34 条 XSS payload 回归集、历史 onclick 迁移、安全降级）

### 关键改动点

- 渲染净化：`marketing_agent.js renderMarkdown`（parse → 迁移历史 onclick → secureSanitize → URL 代理重签）；`script_writer.js renderMarkdown`（正则 sanitizeHtml 已删）；点击放大/发布按钮全部改 `data-full-src`/`data-modal-src`/`data-publish-*` + `bindGeneratedMediaDelegation` 事件委托
- token 治理：`config/constant.py` 新增 `USER_TOKEN_EXPIRE_DAYS=7`、`USER_TOKEN_RENEW_THRESHOLD_DAYS=2`、`AUTH_COOKIE_NAME`、`AUTH_COOKIE_MAX_AGE_SECONDS`；`UserTokensModel.touch`；`AuthService.verify_token` 滑动续期；`/api/auth/login` Set-Cookie（HttpOnly + SameSite=Strict + Secure 自适应反代）、`/api/auth/logout` Delete-Cookie；`server.py` 新增 `auth_cookie_translation_middleware`、`security_headers_middleware`、`extract_bearer_token`
- URL token 清理：`video_workflow.html`、`index.html`（iframe）、`api.js`（get-status/poll）、`script_writer.js`（world 导入导出等 14 处）、`script_writer_library.js`、`storyboard/api.js`、recharge/packages 三处调用 + 后端 header 兼容
- CORS：`server.cors_allow_origins` 白名单（含凭据）/ 默认无凭据跨源

### 遗留事项（后续 MR）

1. **微信授权回调 URL token**（`index_app.js` init 的 `?token=` 注入流程）：token 经页面 URL 传入后写 localStorage 的入口仍保留——涉及第三方授权链路，需后端在回调处理时改种 cookie 后一并移除。
2. **管理员切换用户**（Ctrl+Shift+A，手动输入目标用户 token）：运营工具语义，凭据经人工通道传递，维持现状。
3. **CSP 第二步**：`Content-Security-Policy-Report-Only: script-src 'self'` + report-uri，收集内联 script 清单后做 nonce 化改造，再切 enforcement。
4. **后端 `require_permission` 装饰器为空实现**（perseids_server/utils/permission.py，TODO 标注）：本次调查顺带确认，权限系统落地属独立专项。落地前 story_writer world 文件等接口实际无鉴权。
5. **登录标记 `logged_in`、phone 等非凭据字段仍在 localStorage**：不含可被利用的凭据；phone 建议后续只存脱敏值。
