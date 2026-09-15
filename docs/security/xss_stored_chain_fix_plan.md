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

cookie 与 header 双读后，旧版本前端（localStorage 模式）继续用 header 正常工作。当前实施为 **A 方案双写**（见文末）：登录同时种 HttpOnly cookie 并把同一 token 写入 localStorage，存量 Form/JSON 调用点继续工作。3c 收口（停写 localStorage）必须等前端判据、请求凭据、后端出站/快照三层都扫完。

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
| — | 该包装必须是 `const escapeHtml = function`，禁止 `function escapeHtml` | 非 module 脚本的 function 声明会写成 `window.escapeHtml`，覆盖 escape.js 后自递归爆栈（加载历史消息 `Maximum call stack size exceeded`） |
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
6. **剧本创作发消息须 header 优先于会话存档 token**：`POST /api/session/{id}/task` 曾用 `body.auth_token or session.auth_token`。cookie 登录后 body 为空、复用会话里仍是上次登录已顶号作废的 token，历史接口走 header 能打开页面，一发送就误报「登录已过期」。已改为 `resolve_request_auth_token`（header/cookie > body > 会话）。

## 后续修复记录（develop_f833，2026-09-14）

阶段 3c 落地后端到端回归发现：首页「剧本智能创作系统」入口在 cookie 会话登录成功后仍弹「请先登录」，无法进入 `/script-writer`。根因是部分入口仍以 `localStorage.auth_token`（cookie 会话下恒为空）作为登录判据，属阶段 3c 漏网点，本次一并修复：

| 文件 | 问题 | 修复 |
|---|---|---|
| `web/js/pages/list_page.js` `handleScriptWriterClick` | 登录判据只看 `auth_token`，cookie 会话用户被拦截（用户报告的症状） | 判据改为 `logged_in === '1' || auth_token`，与「authToken 或 cookieSession」约定一致 |
| `web/js/index_app.js` `isLoggedIn` | computed 漏改，banner 对 cookie 会话用户显示「登录」按钮 | 判据补上 `cookieSession`（userPhone/userEmail 在 mounted 时已无条件从 localStorage 恢复，探测成功后即可正确显示） |
| `web/js/script_writer.js` `LOGIN_URL` | `redirect_url` 硬编码 `video-workflow-list`，登录过期后被带去视频工作流列表而非原页 | 改为带回当前 `pathname + search`（含 user_id/world_id/workflow_id），登录后还原完整上下文 |
| `web/js/video_workflow_list.js` `handleAgentClick` | 把读不到的空 `auth_token` 写回 localStorage（`setItem(k, '')` 会存入空串脏数据，干扰其他页面登录判断） | 删除写回与无用变量，凭据仅由 HttpOnly cookie 携带 |

验证方式：真实登录后点击首页卡片可正常进入 `/script-writer`；直接访问该页不再被踢回 `/?login=1&redirect_url=video-workflow-list`。

### 二次全面排查（同日）

按同一根因对 `web/` 全量 `auth_token` 引用点（79 处）分类复查：登录拦截类、请求凭据类（header/body/query）、写入点、页面初始化跳转。后端 `resolve_request_auth_token`（header/cookie > body > 会话，空 body token 不压过 cookie）与「有 token 才附加」类调用点确认无害；另发现并修复 8 处漏网：

| 文件 | 问题（cookie 会话用户受影响） | 修复 |
|---|---|---|
| `web/js/pages/list_page.js` `handleStoryboardListClick` | 首页「故事板」卡片误弹「请先登录」（与剧本创作卡片同款） | 判据改 `logged_in === '1' \|\| auth_token` |
| `web/js/storyboard_list.js` `init` | 故事板列表页加载即被踢回 `/?login=1` | 同上 |
| `web/js/workflow.js` `fetchComputingPower` | 无 token 即踢登录页，画布页对 cookie 会话用户整页不可用 | `logged_in` 也算已登录；无 token 时不带 Authorization 头走 cookie 翻译 |
| `web/js/workflow.js` poll-status 轮询 | 判据 `!userId \|\| !authToken` 静默 return，画布状态轮询失效 | 改 `logged_in` 判据 |
| `web/js/events.js` 世界/角色/场景/道具选择器（4 处） | 弹「请先登录后再操作」，弹窗功能全废 | 判据补 `logged_in`（空头由中间件翻译） |
| `web/js/marketing_agent.js` 初始化 | `!authToken.value` 即 `redirectToLogin()`，营销智能体整页不可用；算力日志弹窗同被拦 | 补 `logged_in` 会话标记 |
| `web/js/storyboard/events.js` 算力日志弹窗 | 误拦 cookie 会话用户 | 判据补 `logged_in === '1'` |
| `web/js/storyboard/api.js` `handleAuthError` | 无 error_code 的 401：旧 token 用户受「不清不跳」误报保护，cookie 会话用户反而立即跳登录 | 本地凭据判定补 `logged_in`，两类用户同等保护 |

审查确认无需改动：`external_recharge.html`（支付回调 URL token 属遗留事项 1 同类白名单）、`computing_power_logs.html`（已按双通道注释实现）、`web/js/pages/*` AI 工具箱子页（仅查 `user_id`）、`video_workflow.html` 充值套餐等「条件附加」类调用。

回归验证（真实登录态）：首页四张卡片全部可进；`/script-writer`、`/storyboard-list`、`/marketing-agent`、`/video-workflow` 均正常加载且算力显示正确；vitest 49 文件 569 用例通过（含 `handleAuthError` 新增 cookie 会话误报保护用例）。

### 三次深挖：服务端出站校验与任务快照链（同日）

前端入口清完后继续深挖，发现**中间件翻译不了的场景**：cookie 翻译中间件只作用于「进入本服务的请求」，而服务端业务逻辑里把 body/form/query 中的 token 拿去做**内部算力校验/扣费/快照存档**时，若前端传空（cookie 会话下必然为空），内部校验同样失败。修复：

| 位置 | 问题 | 修复 |
|---|---|---|
| `server.py` `/api/recharge/wechat-pay` | body 无 token 直接 400「Authentication token is required」，**充值功能对 cookie 会话用户完全不可用**；首页/剧本页/营销页/视频页四处前端调用全部受累 | body 为空时从 Authorization 头解析（`normalize_authorization_token`），后续 `check_computing_power`、首充校验统一用解析结果 |
| `server.py` `/api/image-edit`、`/api/text-to-image`、`/api/ai-app-run`、`/api/ai-app-run-image` | form token 为空 → 内部 `check_computing_power` 携空 Bearer 调用失败 → **图片编辑/文生视频等核心生成功能对 cookie 会话用户报错** | 四端点开头统一 `auth_token = auth_token or extract_bearer_token(request.headers.get("authorization")) or ''` |
| `server.py` `/api/runninghub-status/{id}` | 失败退款用 query token，cookie 会话下为空 → 退款环节静默跳过 | 同上兜底（query 优先，空头兜底） |
| `api/script_writer.py` `/location-multi-angle-tasks` | 任务表快照存 body token（空）→ 后台 worker 调 `/api/image-edit` 时认证失败，任务执行失败 | 创建时 body 为空则快照 Authorization 头 token |
| `api/script_writer.py` `/recognize-style` | body token 传 `_vl_call` 做用量计费上报，cookie 会话下漏报 | 空时从 Authorization 头解析 |

审查确认无需改动：`api/script_writer.py` 的 session/task 消息链（已有 `resolve_request_auth_token` header>body>会话）、`/api/parse-script` 与 `/storyboard/{id}/generate-from-script`（token 走 Header，翻译后有效）、`/api/auth/logout`（已有 cookie 兜底）、storyboard agent CLI 链（agent_token 换发凭据，非浏览器会话）、`sse_client.js`（有 token 才带头，空头由中间件翻译）。

**排查方法论沉淀**：此类漏网共三层——①前端登录判据读 `auth_token`（localStorage）；②前端把空 token 放进请求凭据；③后端拿 body/query token 做内部校验/快照（出站调用不经中间件）。前两层翻前端引用即可覆盖，第三层需查「token 进入业务流后的消费点」——凡 token 被存库快照或用于服务端出站鉴权调用处，都需显式兜底。

### 四次深挖：?login=1 弹框时序（同日）

`index_app.js` mounted 里 `?login=1`（401 跳回）与 `redirect_after_login` 两个弹登录框的分支是**同步判断**，而 `probeCookieSession` 是异步的——cookie 会话用户被 401 踢回首页时，即使 cookie 仍有效（误报场景），`cookieSession` 此刻还是初始 `false`，登录框会弹出且 probe 成功后不会自动关闭。

修复：`?login=1` 且带 `logged_in` 标记时不做同步弹框，弹框决策交给 probe 结果——`probeCookieSession` 新增 `onInvalid` 回调，会话确证失效（非 2xx / 401）才弹框。与旧 token 流程 `verifyAuthTokenOnLoginEntry`（确证失效才清理并弹框）语义对称。

同时确认无需改动：`/upload-image`、`/upload-character-audio`（token 仅签名占位，函数体不消费）、`marketing_inspiration.js`、`script_split_task.js`、`announcement_center.js`、`admin/user_modules.js`、storyboard 充值调用（后端已兜底）。

### 五次深挖：滑动续期对 cookie 会话失效（同日）

阶段 3b 的滑动续期只挂在 `AuthService.verify_token` 一条校验路径上；而 cookie 会话下大多数请求走 `resolve_authorization_user_id` / `UserTokensModel.get_user_id_by_token`（纯 SELECT，不续期）。结果：持续活跃的 cookie 会话用户 token 也永不续期，7 天后必然过期——「活跃免登录」名存实亡。且 cookie 的 `max_age` 固定 7 天，即使 DB token 续了，cookie 也会先死。

修复（两处配套）：
| 位置 | 改动 |
|---|---|
| `model/user_tokens.py` `get_user_id_by_token` | 滑动续期统一收口到此（所有校验路径的公共咽喉）：剩余有效期 < `USER_TOKEN_RENEW_THRESHOLD_DAYS` 时 touch 顺延到完整有效期；续期失败只记日志不影响校验 |
| `server.py` `auth_cookie_translation_middleware` | 带认证 cookie 的 `/api/` 请求在响应阶段重设 cookie（顺延 max_age），与 DB 侧续期同步；`/api/auth/logout` 例外（避免把刚删的 cookie 种回去） |

验证（连 3313 真实 DB 的三场景断言 + curl 响应头检查）：临期 token（1 天）经一次请求顺延到 7 天（168h）；非临期（6 天）不被误续（144h）；过期 token 仍被拒绝（自然淘汰保留）；`/api/user/role` 响应带 `set-cookie: Max-Age=604800` 刷新，`/api/auth/logout` 响应只删不种。

### 六次深挖：登录 Set-Cookie 被中间件旧值覆盖（同日，严重）

滑动续期的 cookie 刷新落地后端到端回归暴露连锁 bug：中间件响应阶段刷新 cookie 时**无条件使用请求带来的旧值**——用户带着无效旧 cookie 调 `/api/auth/login` 时，handler 登录成功种下新 token、随后中间件又用旧 cookie 值覆盖之。由于登录采用「单会话顶号」（新 token 落库、旧 token 删除），浏览器最终持有的旧值在服务端已不存在——**带旧 cookie 的用户永远无法重新登录**，且无效 cookie 被每次请求「续命」，形成死循环。

修复与配套：
| 位置 | 改动 |
|---|---|
| `server.py` 中间件 | cookie 刷新排除 `/api/auth/*`（login/logout/register 自己管理 cookie）；刷新前提保持「翻译发生 + 有 cookie」 |
| `web/js/index_app.js` 登录/登出/`clearLocalAuthInfo`/登出异常分支 | 清理列表补上更早版本的旧 key `token`（`storyboard/state.js` 仍兜底读取，残留会使请求带作废 Bearer 绕过 cookie 翻译）与 `email` |
| `web/js/index_app.js` mounted + `probeCookieSession` | 自愈闭环：无 token 一律探测 cookie 会话（不再依赖 `logged_in` 标记），成功则写回标记并恢复登录 UI；标记被误清后访问任意页自动恢复 |
| `perseids_server/services/auth_service.py` `verify_token` | 简化：滑动续期已收口到 `get_user_id_by_token`，删除重复的过期查询与续期写（每次校验省 2 次 DB 操作） |

验证：UI 真实登录后 `code=0`（role=admin）、`logged_in` 标记写回、banner 显示登出按钮、点击「剧本智能创作系统」正常进入 `/script-writer?user_id=1`；`verify_token` 简化前后行为一致（临期续期/过期拒绝三场景断言）；vitest 49 文件 569 用例通过；CI lint 全家桶（R4-R7/M/T/X）通过。

### 七次深挖：admin 页登出不吊销服务端 token（develop_f858 补记，2026-09-15）

六轮排查后仍有第 27 处遗漏：管理后台（`web/js/admin.js`）的「退出」只做 `localStorage.removeItem(...)` 后跳转首页，**不调 `/api/auth/logout`**——服务端 `user_tokens` 行未删除、HttpOnly cookie 未清除。实测登出后用原 token 调 `/api/user/checkin/status` 仍 200，token 在剩余有效期内（最长 7 天）持续可用；cookie 会话用户换回带 cookie 的入口仍是登录态。首页 `index_app.js` 的 `handleLogout` 是完整实现（调后端删 token + 清 cookie），admin 页是改造时漏掉的独立登出入口。

修复（develop_f858）：`admin.js logout()` 改为先 `axios.post('/api/auth/logout', { auth_token }, { headers: Authorization, timeout: 3000 })`（与 admin.js 其余调用一致显式带 Bearer；cookie-only 会话由服务端翻译兜底），**无论成败**（网络/超时不阻塞）都保留原本地清理并跳转首页。防回归：`web/tests/admin_logout_revokes_server_token.test.js` 静态断言 admin logout 必须含 `/api/auth/logout` 调用，且后端 `auth_service.logout` 删 token 行、`server.py` 清 `AUTH_COOKIE_NAME`。

## 兼容期双写（A 方案，develop_f833）

阶段 3c 冷切「停写 localStorage」后，前端仍有大量入口读 `localStorage.auth_token` 再塞进 Form/JSON；后端不少接口用 body/form token 做出站校验/任务快照，cookie 翻译中间件管不到。一天内无法完成全站回归，因此进入兼容期：

1. **双写同一 token**：登录成功响应体的 `data.token` 写入 `localStorage.auth_token`，同时服务端 `Set-Cookie`（同一字符串）。权威在 DB `user_tokens`。注册走自动登录，复用同一路径。
2. **cookie-only 旧会话强制重新登录**：JS 读不到 HttpOnly cookie，无法补写 localStorage。`probeCookieSession` 发现 cookie 有效但本地无 token 时，清掉 `logged_in` 并弹「登录方式已更新，请重新登录」。重新登录后两份副本对齐。
3. **门禁以 localStorage token 为准**：`logged_in` 单独不算完整登录，避免 cookie-only 用户进得了页面、生成/扣费空 token。
4. **作废 Bearer 优先于 cookie**：中间件「有 Authorization 就不看 cookie」。登录/登出仍清旧 key `token`；确证失效（`invalid_auth_token` / `TOKEN_EXPIRED`）时清本地 token，避免旧头压过新 cookie。
5. **cookie 在兼容期是备份**：前端带头后中间件不会刷新 cookie（刷新只在翻译发生时）。身份以 localStorage + header 为准，行为回到 3c 之前。

3c 真正收口（删除 `persistBrowserAuth` 里的 localStorage 写入）前，必须扫完：前端登录判据、请求是否还带空 token、后端 body/query token 出站校验与任务快照。

### 八次深挖：script-writer 登录过期连环弹窗回环（develop_f862，2026-09-15）

兼容期双写第 4 条「确证失效时清本地 token」只在 `index_app.js`（`handleAuthError` / `verifyAuthTokenOnLoginEntry`）落地，`script_writer.js` 的 `handleTokenExpired` 漏掉了。dev 环境（192.168.10.101:9003）实测复现回环：用户 localStorage 残留失效 token（单会话顶号/过期被删）→ 页面以快照携带非空失效 Bearer，压住 cookie 翻译中间件 → `world-files` 等 init 请求集体 401 → `handleTokenExpired` 裸 `alert + location.href = LOGIN_URL`，**无防重入**，页面 init 并发 7+ 请求各自触发 → 连环弹窗、反复重设跳转目标。access.log 实录：登录成功（`POST /api/auth/login` 200）后用户仍被残留 401 弹窗拽回 `/?login=1`，被迫二次登录才恢复——「登录后进页面仍提示过期」。

修复（develop_f862，`web/js/script_writer.js`）：
| 改动 | 说明 |
|---|---|
| `tokenExpiredHandled` 防重入 | 多份并发 401 只处理第一份，杜绝连环 alert 与跳转目标反复重置 |
| 先清 `localStorage.auth_token` / 旧 key `token` 再探测 | 失效 Bearer 不再压住 cookie 翻译；与 `clearLocalAuthInfo` 的 key 集合对齐 |
| cookie 会话自愈 | 无 Authorization 头探测 `/api/user/role`，cookie 有效则 `reload()`——重载后 `AUTH_TOKEN` 为空，空 Bearer 走 cookie 翻译，无感恢复；`sessionStorage` 记录自愈时间，60 秒内只自愈一次防 reload 循环 |
| cookie 也失效才提示 | 单次 alert（沿用 `alert_login_expired` i18n key）+ 跳 `LOGIN_URL`（已带回当前页） |

防回归：`web/tests/script_writer_token_expired_self_heal.test.js` 静态断言防重入标志、清 token、无 Authorization 头探测、reload 自愈与 60 秒节流、单次 alert 回退。其余以「快照 token + 裸 401 弹窗」模式工作的独立页面（marketing_agent 等）可复制同构方案，待后续批次收口。
