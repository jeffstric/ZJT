# 故事板新建：视频比例确认与继承

## 背景

新建故事板时若静默写入默认 `16:9`，会导致：

1. 世界内首个故事板未让用户选择横屏/竖屏；
2. 后续集不会继承第 1 集比例，多集画幅不一致；
3. 若在比例未定前触发分镜拆分，错误画幅会贯穿整集构图与生成结果。

## 行为规则

| 场景 | 行为 |
|------|------|
| 当前用户 + 当前世界下 **没有任何** 故事板 | Web 弹出比例确认门禁（仅 `16:9` / `9:16`）；确认后才 `POST /create` |
| 已有故事板，且存在 **第 1 集** | 新建时继承第 1 集 `workflow_ratio`，不弹窗 |
| 已有故事板，但 **没有第 1 集** | 取 `episode_number` 最小且 ratio 非空的故事板继承 |
| 当前集故事板已存在 | get-or-create 直接返回，不改比例 |

范围：`user_id`（空间隔离时）+ `world_id`，与唯一键 `uk_user_world_episode` 一致。

## 硬门禁（红线）

比例未确认 / 故事板尚未以明确比例创建完成时：

- **不**调用 `POST /api/storyboard/create`
- **不**进入完整编辑器
- **不**弹出「根据剧本生成分镜」
- **不**跑自动补全首帧/视频
- 前端 `state.ratioGateActive === true` 时事件白名单仅允许比例确认相关 action

后端兜底：`POST /api/storyboard/{id}/generate-from-script` 在 `workflow_ratio` 为空时返回 `400`（「请先设定视频比例」）。

## 接口

### `GET /api/storyboard/create-defaults?world_id=`

权限：`storyboard:create`

```json
{
  "success": true,
  "needs_ratio_confirm": true,
  "workflow_ratio": null,
  "source_episode_number": null,
  "storyboard_count": 0
}
```

已有可继承比例时：

```json
{
  "success": true,
  "needs_ratio_confirm": false,
  "workflow_ratio": "9:16",
  "source_episode_number": 1,
  "storyboard_count": 3
}
```

### `POST /api/storyboard/create`

Body 增加可选 `workflow_ratio`：

- Web 首建必须传入用户选择的 `16:9` 或 `9:16`
- 未传时服务端：`显式值 > 同世界继承（优先第1集）> 16:9`
- 合法白名单：`16:9`、`9:16`、`3:4`、`1:1`、`4:3`（兼容 header 历史选项）

## 前端时序

```
initStateFromUrl
  → 有 storyboardId：get → finishBootstrap
  → 无 id：
       GET create-defaults
       → needs_ratio_confirm：
            ratioGateActive=true
            仅渲染比例弹窗
            用户确认 → create(带 ratio) → 解除门禁 → finishBootstrap
       → 否则：create（后端继承）→ finishBootstrap
  → finishBootstrap 内才允许 maybePromptGenerateFromScript
```

关键文件：

- `web/js/storyboard/bootstrap.js`：探测、门禁、`continueCreateWithRatio`、`finishBootstrapAfterStoryboardReady`；`main()` 启动时将 `continueCreateWithRatio` 注册到 `state` 上
- `web/js/storyboard/render.js`：`renderRatioConfirmDialog` + 门禁态整页渲染
- `web/js/storyboard/events.js`：门禁 action 白名单；「确认创建」通过 `state.continueCreateWithRatio(...)` 调用，**不要**用 `await import('./bootstrap.js')`（见下方已知坑）
- `web/css/storyboard.css`：`.sb-ratio-*` 样式（对齐工作流列表比例卡片）

## 已知坑：禁止动态 import 入口模块

`events.js` 处理「确认创建」时，**不能**用 `await import('./bootstrap.js')` 反向引用入口模块：

- HTML 入口为 `bootstrap.js?v=<ver>`（带版本号，详见 [`docs/frontend_static_version.md`](../frontend_static_version.md)）；
- 而 ES 模块内部的 `import './bootstrap.js'` 会被解析为**不带版本号**的 URL（`bootstrap.js`）；
- 浏览器把两者视为**两个不同的模块**分别求值，导致 `bootstrap.js` 顶层副作用（`main()` 调用）被执行两次：
  1. 第一次 `main()` 正常进入门禁、等待用户选择比例；
  2. 用户点「确认创建」→ `import('./bootstrap.js')` 触发第二次求值 → 第二个 `main()` 又调用 `loadStoryboard()`，此时故事板可能尚未创建完成，于是再次进入门禁分支，把 `pendingCreateRatio` 重置为默认 `16:9` 并重新渲染弹窗；
- 表现为「选择尺寸后立刻又弹出一个默认值（16:9）的弹框，随后消失，数据库保存的却是用户第一次的选择」。

修复方式：`main()` 启动时把 `continueCreateWithRatio` 注册到共享的 `state` 对象，`events.js` 通过 `state.continueCreateWithRatio(...)` 调用，彻底避免动态 import 入口模块。

## 与 header 比例切换的关系

- 新建弹窗仅提供 `16:9` / `9:16`
- 创建后 header 下拉仍可改当前故事板比例（含 3:4 / 1:1 / 4:3 等）
- **不**级联修改同世界其它集
- 后续新建集继承的是「第 1 集（或最小集号）当时库中的值」

## Agent / CLI

无 UI：`workflow_ratio` 可选；未传走服务端继承/默认 `16:9`，不要求弹窗确认。

## 相关代码

- `model/storyboard.py`：`list_ratios_by_world` / `resolve_inherited_workflow_ratio`
- `api/storyboard.py`：`resolve_storyboard_create_ratio` / `GET /create-defaults` / create 与 generate-from-script 门禁
