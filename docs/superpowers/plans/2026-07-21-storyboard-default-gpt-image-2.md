# Storyboard Default GPT Image 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在没有故事板配置和有效历史选择时，将故事板拆分剧本页面的默认生图模型设为 GPT Image 2。

**Architecture:** 保留现有 `config_json` 与 `localStorage` 恢复链路，只扩展 `state.js` 的模型兜底选择函数，使生图模型可指定首选稳定 key。选择结果继续使用后端返回的 `task_id`，GPT Image 2 不可用时回退列表第一项。

**Tech Stack:** JavaScript ES Modules、Vitest、浏览器 `localStorage`、Markdown

## Global Constraints

- 保留已有故事板配置和有效 `localStorage` 历史选择。
- 仅改变故事板生图模型的首次默认值；视频、数字人和 LLM 默认逻辑不变。
- GPT Image 2 使用 `short_key === 'gpt-image-2'` 识别，并兼容 `key === 'gpt-image-2'`。
- GPT Image 2 不可用时回退当前模型列表第一项。
- 功能相关改动同步更新 `docs` 目录文档。
- 前端代码不得引入阻塞式 Web 调用。
- 保持 Windows、Linux、macOS 兼容，不新增平台相关路径逻辑。

---

### Task 1: 故事板生图模型默认选择

**Files:**
- Create: `web/tests/storyboard_default_image_model.test.js`
- Modify: `web/js/storyboard/state.js:545-598`
- Modify: `docs/storyboard/storyboard_ui_style_and_models.md:131-144`

**Interfaces:**
- Consumes: `setModels({ image_models, video_models, ... })` 接收后端模型数组；每个模型含 `task_id`、`key`、`short_key`。
- Produces: `pickRememberedTaskId(models, storageKey, preferredModelKey)` 返回历史 `task_id`、首选模型 `task_id` 或列表首项 `task_id`；`setModels()` 为生图选择传入 `'gpt-image-2'`。

- [ ] **Step 1: 写入失败测试**

创建 `web/tests/storyboard_default_image_model.test.js`：

```javascript
import { beforeEach, describe, expect, it } from 'vitest';

import state, { setModels } from '../js/storyboard/state.js';

describe('storyboard default image model', () => {
    const nanoBanana = {
        task_id: 1,
        key: 'gemini-2.5-flash-image-preview',
        short_key: 'gemini-2.5-flash',
        name: 'nano-banana',
    };
    const gptImage2 = {
        task_id: 26,
        key: 'gpt-image-2-edit',
        short_key: 'gpt-image-2',
        name: 'GPT Image 2 图片编辑',
    };

    beforeEach(() => {
        state.selectedImageTaskId = null;
        state.imageModels = [];
        state.textToImageModels = [];
        localStorage.removeItem('storyboard_lastSelectedImageTaskId');
    });

    it('无历史选择时优先选择 GPT Image 2', () => {
        setModels({ image_models: [nanoBanana, gptImage2] });
        expect(state.selectedImageTaskId).toBe(26);
        expect(localStorage.getItem('storyboard_lastSelectedImageTaskId')).toBe('26');
    });

    it('保留仍然有效的 nano-banana 历史选择', () => {
        localStorage.setItem('storyboard_lastSelectedImageTaskId', '1');
        setModels({ image_models: [nanoBanana, gptImage2] });
        expect(state.selectedImageTaskId).toBe(1);
    });

    it('GPT Image 2 不可用时回退模型列表第一项', () => {
        setModels({ image_models: [nanoBanana] });
        expect(state.selectedImageTaskId).toBe(1);
    });

    it('兼容 GPT Image 2 使用 key 标识的模型数据', () => {
        setModels({
            image_models: [
                nanoBanana,
                { task_id: 26, key: 'gpt-image-2', short_key: '', name: 'GPT Image 2' },
            ],
        });
        expect(state.selectedImageTaskId).toBe(26);
    });
});
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `npm test -- web/tests/storyboard_default_image_model.test.js`

Expected: 第一项和第四项失败，实际 `selectedImageTaskId` 为 `1`，证明现有逻辑仍取模型列表第一项。

- [ ] **Step 3: 实现最小默认选择逻辑**

在 `web/js/storyboard/state.js` 中扩展兜底函数并只为生图模型指定首选 key：

```javascript
function pickRememberedTaskId(models, storageKey, preferredModelKey = null) {
    const preferredModel = preferredModelKey
        ? models.find(m => m.short_key === preferredModelKey)
            || models.find(m => m.key === preferredModelKey)
        : null;
    const fallback = preferredModel?.task_id ?? models[0].task_id;
    let remembered = null;
    try {
        remembered = localStorage.getItem(storageKey);
    } catch {}
    if (remembered != null && models.some(m => String(m.task_id) === String(remembered))) {
        return Number(remembered);
    }
    try {
        localStorage.setItem(storageKey, String(fallback));
    } catch {}
    return fallback;
}
```

将生图模型调用改为：

```javascript
state.selectedImageTaskId = pickRememberedTaskId(
    image_models,
    'storyboard_lastSelectedImageTaskId',
    'gpt-image-2',
);
```

视频模型调用保持原样，不传首选 key。

- [ ] **Step 4: 运行定向测试并确认通过**

Run: `npm test -- web/tests/storyboard_default_image_model.test.js web/tests/storyboard_default_video_model.test.js`

Expected: 两个测试文件全部通过，确认生图默认值改变且视频默认逻辑无回归。

- [ ] **Step 5: 同步故事板文档**

更新 `docs/storyboard/storyboard_ui_style_and_models.md` 的优先级描述为：

```markdown
**生图模型优先级链路**：`config_json`（当前故事板，主记忆）> `localStorage`（跨故事板兜底）> GPT Image 2（`short_key=gpt-image-2`）> 模型列表第一项。

**视频模型优先级链路**：`config_json`（当前故事板，主记忆）> `localStorage`（跨故事板兜底）> 模型列表第一项。
```

同时说明有效历史选择（包括 nano-banana）继续保留，只有没有有效历史的首次选择才默认 GPT Image 2。

- [ ] **Step 6: 运行前端回归测试和静态检查**

Run: `npm test -- web/tests/storyboard_default_image_model.test.js web/tests/storyboard_default_video_model.test.js web/tests/state.test.js web/tests/state_pure.test.js`

Expected: 所有测试通过，无未处理异常或警告。

Run: `git diff --check`

Expected: 无输出，退出码为 0。

- [ ] **Step 7: 提交实现**

```bash
git add web/tests/storyboard_default_image_model.test.js web/js/storyboard/state.js docs/storyboard/storyboard_ui_style_and_models.md docs/superpowers/plans/2026-07-21-storyboard-default-gpt-image-2.md
git commit -m "feat(storyboard): 默认使用 GPT Image 2"
```
