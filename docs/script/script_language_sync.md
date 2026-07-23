# 剧本节点语言联动功能

## 更新内容
- 版本：2026-06-18
- 说明：剧本节点的"输出语言"已细化为"对话语言"和"提示词语言"两个独立选项。"提示词语言"与右上角界面语言切换器联动。

## 功能说明

### 语言字段细化

剧本节点的参数配置区域包含两个独立的语言选择器：

| 字段 | 存储属性 | 控制范围 |
|------|-----------|----------|
| 对话语言 | `node.data.dialogueLanguage` | 对话文本（dialogue.text）的输出语言 |
| 提示词语言 | `node.data.promptLanguage` | 描述性字段（description、action、scene_detail 等）的输出语言 |

两个语言支持相同的选项：中文（默认）、English、Deutsch、Français、Русский、自定义语言。

### 联动规则

| 界面语言 | 提示词语言 |
|----------|-------------|
| 中文 (zh-CN) | 中文（默认）- 空值 |
| English (en) | English |

注意：语言联动仅影响"提示词语言"，不影响"对话语言"。

### 交互行为

1. 用户点击右上角语言切换器选择"English"
2. 界面语言切换为英文
3. 剧本节点的"提示词语言"下拉框自动切换为"English"
4. 节点数据 `node.data.promptLanguage` 同步更新为 `"English"`

5. 用户点击右上角语言切换器选择"中文"
6. 界面语言切换为中文
7. 剧本节点的"提示词语言"下拉框自动切换为"中文（默认）"
8. 节点数据 `node.data.promptLanguage` 同步更新为 `""`

### 解说模式规则（已移除）

剧本节点不再提供"解说剧（仅旁白说话）"模式。前端不再发送 `narration_as_dialogue`，后端也不再执行解说模式后处理。旁白解说能力改由世界级 `story_type=narration` 和脚本智能体流程管理。
### 向后兼容

加载旧版工作流时，旧的 `node.data.language` 字段会自动迁移为 `dialogueLanguage` 和 `promptLanguage` 的默认值。

### 技术实现

#### 相关文件

| 文件 | 说明 |
|------|------|
| `web/js/nodes.js` | 剧本节点定义，包含语言选择器和联动逻辑 |
| `web/js/workflow.js` | 工作流加载恢复，包含语言数据迁移逻辑 |
| `llm/script_parser.py` | 后端剧本解析，支持双语言 prompt |
| `web/i18n/i18n-core.js` | i18n 核心模块，提供 `locale-changed` 事件 |
| `web/i18n/i18n-switcher.js` | 语言切换器 UI 组件 |

#### 实现代码

语言选择器通过通用绑定函数实现：

```javascript
function bindLanguageSelect(selectEl, customEl, dataKey) {
  // selectEl: 下拉框元素
  // customEl: 自定义输入框元素
  // dataKey: 节点数据中的属性名（'dialogueLanguage' 或 'promptLanguage'）
}
bindLanguageSelect(dialogueLanguageSelectEl, dialogueLanguageCustomEl, 'dialogueLanguage');
bindLanguageSelect(promptLanguageSelectEl, promptLanguageCustomEl, 'promptLanguage');
```

语言联动仅绑定在提示词语言选择器上：

```javascript
if(window.ZJTi18n && promptLanguageSelectEl) {
  window.ZJTi18n.on('locale-changed', ({ locale }) => {
    const newLanguage = { 'en': 'English', 'zh-CN': '' }[locale];
    if(newLanguage !== undefined) {
      node.data.promptLanguage = newLanguage;
      // 更新下拉框显示...
    }
  });
}
```

#### 事件机制

- `ZJTi18n.on('locale-changed', callback)` - 监听语言变化事件
- 事件参数 `{ locale }` - 新的语言代码（如 `'en'`, `'zh-CN'`）

### 注意事项

1. 语言联动仅在用户切换界面语言时触发，不影响"对话语言"
2. 如果用户手动选择了非预设语言，切换界面语言后会被覆盖为对应的语言
3. 语言映射表 `localeToLanguage` 可以根据需要扩展
4. 后端 API `/api/parse-script` 同时接受 `dialogue_language`、`prompt_language` 和旧的 `language` 参数，新参数为空时回退到 `language`
