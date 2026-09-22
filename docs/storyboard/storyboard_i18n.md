# 故事板编辑器多语言（i18n）接入

## 概述

`web/storyboard.html`（故事板编辑器）已完整接入项目 i18n 框架（`web/i18n/`），支持中文（zh-CN）与英文（en）切换。语言选择持久化在 localStorage（`zjt_locale`），刷新后保持。

词条规模：`web/i18n/locales/{zh-CN,en}/storyboard.json` 各约 750 条，两份键集合完全一致（由 CI 之外的校验脚本保证，见下）。

## 接入架构

### 1. 渲染期求值（核心模式）

storyboard 的 UI 由 `web/js/storyboard/` 下的 ES module（render.js 等）动态生成。所有用户可见文案统一走：

```js
import { t } from './utils.js';          // render.js 中为 `t as i18nT`
t('btn_generate_image', '生成图片')       // 键命中 → 翻译；未命中 → 中文兜底
```

`utils.js` 的 `t(key, fallback)` 在 `ZJTi18n.t(key)` 返回键名（未命中）或框架缺失时回落到中文 `fallback`，保证语言包漏词条时中文界面永不露出英文键名。

**红线：`t()` 禁止在模块顶层求值**。模块加载时 i18n 尚未 init，且顶层求值的文案无法随语言切换更新。UI 文案常量一律改为 getter 函数运行时求值（如 `utils.js getEmoVecLabel(i)`、`playback.js subtitleSampleText()`）。

### 2. 语言切换 → 整页重渲染

`bootstrap.js initI18n()` 注册：

```js
ZJTi18n.on('locale-changed', () => { document.title = t('storyboard_title', ...); renderApp(); });
```

页面文案在渲染期经 `t()` 求值，整页重建后即切换语言。`i18n-dom.js` 的 `data-i18n` 扫描只负责静态壳（页面 `<title>`、加载占位文案）。

### 3. 语言切换器挂载（单例复用）

- `render.js` 的 header 右侧输出槽位 `<span data-lang-switcher-slot>`；
- `web/js/storyboard/lang_switcher.js` 的 `ensureLanguageSwitcher()` 在每次 `renderAppFull()` 后把**同一个**切换器 DOM 节点 appendChild 进新槽位（浏览器自动移动节点）。
- 单例是必须的：`ZJTi18nSwitcher.createSwitcherElement()` 内部会向 `document` 注册 click / locale-changed 监听，若每次重建 DOM 都新建切换器，监听器会随渲染次数累积。

### 4. 切换时加载 storyboard 命名空间

`web/i18n/i18n-switcher.js` 的 `selectLanguage` 内置命名空间列表原不含 `storyboard`，已追加；否则切到英文后 `storyboard.json(en)` 不会加载，所有 `t()` 都回落中文兜底。

### 5. 兼容测试沙箱的本地 t

`adapters.js`、`first_frame_coloring.js`、`auto_missing_images_state.js`、`video_type_switch_state.js` 被既有测试以 `new Function` / `vm.runInNewContext` 执行源码，静态 `import` 会直接 SyntaxError，因此这些文件使用带 `window` 守卫的本地 `t` 实现（语义与 `utils.js` 一致），不新增 import。

## 范围与例外

- 已接入：按钮、标签、弹窗、确认框、toast/notify、状态角标、placeholder/title/aria-label、拆分进度步骤名、批量操作结果消息等全部 UI 文案。
- 保持中文/不翻：注释与 console.*；发后端的枚举值与字段值（如 `data-action`、`videoType`、难度 `'易/中/难'`、后端 `mode_label` 数据兜底）；用户数据（分镜标题、台词）；剧本解析正则（与后端 `llm/script_parser.py` 有同步契约）；品牌字 `智`（loading-mark）。
- 模块顶层少量初始兜底值（如 `state.editionInfo.mode_label: '社区版'`）保留中文：均为后端数据返回前的短暂初始值，渲染期会被覆盖。

## 校验

- 语法：全部改动 js 通过 `node --check`（以 `.mjs` 方式检查 ES module 语法）。
- 词条覆盖：`temp/i18n_merge/verify_keys.py` 逻辑——扫描 `web/js/storyboard/*.js` 中全部 `t()/i18nT()` 调用键与 `storyboard.html` 的 `data-i18n` 键，对照 `zh-CN/storyboard.json`，0 缺失。
- 测试：`npx vitest run web/tests/` 580/580 通过；`python scripts/lint_frontend_xss.py` OK。`tests/js/test_storyboard_*.js` 中 8 个为改动前即失败的存量脚本（与本功能无关）；4 个受影响的测试已同步更新断言（`web/tests/storyboard_direct_submit_feedback.test.js`、`web/tests/storyboard_video_batch_confirm.test.js`、`tests/js/test_storyboard_digital_human_audio_hint.js`、`tests/js/test_storyboard_model_config_resolution_close.js`、`tests/js/test_storyboard_quality_enterprise_gate.js`）。

## 维护约定

1. 新增 UI 文案必须走 `t(key, '中文')`，并在 `web/i18n/locales/zh-CN/storyboard.json` 与 `en/storyboard.json` **同步**添加词条；同一文案复用同一 key。
2. 键命名沿用 `btn_ label_ tab_ title_ msg_ placeholder_ status_ option_ dialog_ aria_ hint_ step_ confirm_` 前缀 + snake_case。
3. 含插值的句子在词条里写 `{n}` 占位（`ZJTi18n.t` 支持 `{name}`/`{{name}}` 替换），调用处 `.replace('{n}', ...)`。
4. 英文界面少量长句为拼接生成（如批量工具条 `批量+生成+分镜图` 按语素拆分词条），语义以词条注释为准；后续新增此类拼接建议改用整句词条。
