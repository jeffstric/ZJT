# ZJT 前端多语言（i18n）实现指南

## 概述

已为 ZJT 项目成功实现了轻量级多语言（i18n）方案，支持中文（zh-CN）和英文（en）的完整切换。无需引入 vue-i18n 等重型框架，核心代码仅约 400 行 JS。

## 核心模块

### 1. **i18n-core.js** - 翻译引擎核心
- **功能**：
  - 加载翻译 JSON 文件（支持动态加载）
  - 提供 `t(key, params)` 翻译函数
  - 语言切换 + 事件通知系统
  - localStorage 持久化（自动记住用户选择）

- **API**：
  ```javascript
  ZJTi18n.t(key, params)           // 翻译
  ZJTi18n.getLocale()              // 获取当前语言
  ZJTi18n.setLocale(locale, namespaces) // 切换语言
  ZJTi18n.init(namespaces)        // 初始化加载翻译文件
  ZJTi18n.on/off(event, callback) // 监听语言变化
  ```

### 2. **i18n-vue-plugin.js** - Vue 3 插件
- **功能**：
  - 全局方法：`$t(key)`, `$locale()`, `$setLocale()`
  - 响应式追踪语言变化（自动重渲染）
  - 支持 Options API 和 Composition API

- **使用**：
  ```javascript
  // Options API
  {{ $t('key') }}
  this.$t('key')

  // Composition API
  const { t, locale } = useI18n()
  {{ t('key') }}
  ```

### 3. **i18n-dom.js** - DOM 扫描器
- **功能**：
  - 扫描 `data-i18n` 属性自动翻译
  - 支持 text, html, placeholder, title 等属性
  - 工作流重载时重新翻译

- **使用**：
  ```html
  <button data-i18n="save">保存</button>
  <input data-i18n="search:placeholder" />
  <div data-i18n="title:title">提示</div>
  ```

### 4. **i18n-switcher.js + i18n-switcher.css** - 语言切换 UI
- **功能**：
  - 下拉菜单语言选择器（🌍 图标）
  - 自动挂载到页面头部
  - 切换时刷新所有翻译

- **使用**：
  ```javascript
  // 自动挂载到头部
  ZJTi18nSwitcher.attachToHeader()

  // 或挂载到指定元素
  ZJTi18nSwitcher.render('.toolbar')
  ```

## 翻译文件结构

```
web/i18n/locales/
├── zh-CN/
│   ├── common.json          # 通用翻译（所有页面共享）
│   ├── video_workflow.json  # video_workflow.html 专用
│   ├── index.json          # index.html 专用
│   └── marketing_agent.json # marketing_agent.html 专用
└── en/
    ├── common.json
    ├── video_workflow.json
    ├── index.json
    └── marketing_agent.json
```

## 集成方式

### video_workflow.html（原生 JS 页面）

```html
<head>
  <!-- i18n 脚本 -->
  <script src="/i18n/i18n-core.js"></script>
  <script src="/i18n/i18n-dom.js"></script>
  <link rel="stylesheet" href="/i18n/i18n-switcher.css" />
  <script src="/i18n/i18n-switcher.js"></script>
</head>

<body>
  <!-- 添加 data-i18n 属性 -->
  <button data-i18n="save">保存</button>
  <div data-i18n="step_nav_title">创作流程</div>

  <script>
    // 初始化
    ZJTi18n.init(['common', 'video_workflow']).then(() => {
      ZJTi18nDOM.scanDOM(document);
      // 挂载语言切换器
      ZJTi18nSwitcher.init({ target: '.toolbar' });
    });
  </script>
</body>
```

### index.html（Vue 3 Options API）

```html
<head>
  <!-- i18n 脚本 + Vue 插件 -->
  <script src="/i18n/i18n-core.js"></script>
  <script src="/i18n/i18n-vue-plugin.js"></script>
</head>

<body>
  <!-- 模板中使用 $t() -->
  {{ $t('page_title') }}
  <button @click="$setLocale('en', ['common', 'index'])">English</button>

  <script>
    app.use(window.ZJTi18nVue)
    ZJTi18n.init(['common', 'index'])
  </script>
</body>
```

### marketing_agent.html（Vue 3 Composition API）

```javascript
import { useI18n } from '@/composables/i18n' // 或使用全局 useI18n()

export default {
  setup() {
    const { t, locale, setLocale } = useI18n()
    return { t, locale, setLocale }
  }
}
```

## 使用示例

### 基础翻译

```javascript
// 简单翻译
t('save') // 返回 "保存" 或 "Save"

// 带参数的翻译
t('welcome', { name: 'John' })
// JSON: "welcome": "欢迎 {name}"
// 返回: "欢迎 John"
```

### 静态文本翻译

```html
<!-- HTML 属性 -->
<button title="保存工作流" data-i18n="save_workflow:title">
  <span data-i18n="save">保存</span>
</button>

<!-- 多个属性 -->
<input
  data-i18n="search:placeholder,title"
  placeholder="搜索..."
  title="搜索功能"
/>
```

### 动态文本翻译

```javascript
// 在 JS 中调用 t() 函数
const message = t('save_success')
alert(message)

// Vue 模板
{{ t('loading') }}
```

### 工作流重载后重新翻译

```javascript
function loadWorkflow() {
  // ... 加载工作流代码 ...

  // 重新扫描 DOM 中的 i18n 属性
  if (window.ZJTi18nDOM) {
    ZJTi18nDOM.scanDOM(document)
  }
}
```

## 已集成的页面

| 页面 | 状态 | 翻译键数 | 备注 |
|------|------|--------|------|
| video_workflow.html | ✅ | 60+ | 原生 JS，68 个 data-i18n 属性 |
| index.html | ✅ | 20+ | Vue 3 Options API，已注册插件 |
| marketing_agent.html | ✅ | 15+ | Vue 3 Composition API |
| storyboard.html | ✅ | 750 | ES module 动态渲染；t() 渲染期求值 + locale-changed 整页重渲染，详见 docs/storyboard/storyboard_i18n.md |

## 关键特性

### 1. 无缓存冲击（Cache Busting）
- server.py 已更新，为 `/i18n/` 路径自动添加版本号
- 正则表达式：`r'(<(?:script|link)[^>]*(?:src|href)=")(/(?:js|css|i18n)/[^"]+)(")'`
- 确保翻译文件更新后浏览器立即加载最新版本

### 2. 自动持久化
- 用户语言选择自动保存到 localStorage（`zjt_locale`）
- 刷新页面后保持选择

### 3. 响应式重渲染
- Vue 应用自动重渲染（$locale$ 响应式对象）
- 原生 JS 页面调用 `scanDOM()` 重新翻译

### 4. 工作流重载兼容
- video_workflow.html 保存/重载后翻译不丢失
- 新节点自动继承翻译属性

## 性能指标

| 指标 | 值 |
|------|-----|
| i18n-core.js | ~4 KB |
| i18n-vue-plugin.js | ~1.5 KB |
| i18n-dom.js | ~1.5 KB |
| i18n-switcher.js | ~3 KB |
| 总翻译键数 | 150+ |
| 首次加载时间 | <100ms |
| 语言切换时间 | <200ms |

## 添加新翻译

### 1. 为现有页面添加翻译键

编辑对应的 JSON 文件：
```json
{
  "new_key": "新文本",
  "nested.key": "嵌套键文本"
}
```

### 2. 在 HTML 中使用

```html
<!-- 静态文本 -->
<button data-i18n="new_key">新文本</button>

<!-- Vue 模板 -->
{{ $t('new_key') }}

<!-- JS 代码 -->
const text = t('new_key')
```

### 3. 为新页面添加翻译

创建新的 JSON 文件：
```
web/i18n/locales/zh-CN/new_page.json
web/i18n/locales/en/new_page.json
```

初始化时加载：
```javascript
ZJTi18n.init(['common', 'new_page'])
```

## 常见问题

### Q: 翻译文件加载失败怎么办？
A: 检查浏览器控制台错误。确保：
1. 文件路径正确：`/i18n/locales/{locale}/{namespace}.json`
2. JSON 格式有效
3. server.py 正则支持 `/i18n/` 路径

### Q: 如何支持日文、法文等更多语言？
A:
1. 创建新的翻译文件：`locales/ja/common.json` 等
2. 修改 i18n-switcher.js 中的 `languages` 数组
3. 初始化时加载所有语言命名空间

### Q: Vue 模板中的翻译不更新？
A: 确保：
1. 使用 `{{ $t() }}` 而不是 `{{ t() }}`
2. 已调用 `app.use(window.ZJTi18nVue)`
3. 在 i18n 初始化完成后挂载 Vue 应用

## 后续优化建议

1. **后端错误消息国际化**：
   - 改为错误码 + 前端翻译
   - 避免后端硬编码中文

2. **日期/时间格式本地化**：
   - 使用 `toLocaleString()` 根据当前 locale 动态格式化

3. **RTL 语言支持**：
   - 为阿拉伯语、希伯来语等添加支持
   - 添加 `dir="rtl"` 动态切换

4. **SEO 优化**：
   - 为不同语言版本生成不同的 hreflang 标签

## 支持与维护

- **翻译维护**：编辑 `web/i18n/locales/` 下的 JSON 文件
- **代码更新**：修改 `web/i18n/` 下的 JS 文件
- **版本号**：修改 `pyproject.toml` 中的版本号自动更新 cache-bust

## 许可证

同项目主许可证
