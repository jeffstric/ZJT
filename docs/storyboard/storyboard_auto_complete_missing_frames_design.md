# 故事板自动补全未生成分镜设计

## 1. 背景

故事板已经具备 `auto-generate-missing-images` 批量生成接口，以及页面首次打开或剧本拆分完成后自动生成缺失首帧的能力。但是当前前端只保存一个布尔式 `sessionStorage` 标志，未保存批次状态；批次后续进入 `partial` 或 `failed` 时，页面只停止轮询，不会清除标志、展示失败统计或提供重新补全入口。

因此，用户会看到部分分镜长期没有首帧，但页面上没有明确的批量补全按钮。刷新同一浏览器标签页时，旧的去重标志还可能继续阻止自动提交。

## 2. 目标

1. 在时间轴视图的“分镜序列”标题栏右侧展示“自动补全未生成分镜”按钮。
2. 在网格视图的“故事板总览”标题栏右侧同步展示同一按钮。
3. 按钮状态与每个分镜缩略图状态由同一份批次状态驱动。
4. 页面刷新后能够恢复并继续轮询当前批次。
5. 当前端尚未同步、但后端已经存在活动批次时，接管已有批次而不是重复提交。
6. 批次部分失败或全部失败后，允许用户只补全仍未生成的分镜。
7. 保持后端现有鉴权、算力扣减、幂等和 quality 宫格生成链路不变。

## 3. 非目标

1. 不新增自动无限重试。生成失败后由用户主动点击按钮重新补全，避免不可控地持续消耗算力。
2. 不新增“查询当前活动批次”的后端 API。复用现有提交接口、批次状态接口及 `active_batch_exists` 返回信息。
3. 不改变 `speed`、`balanced`、`quality` 三种生成模式的后端调度语义。
4. 不允许用户在已有活动批次时并行提交另一个首帧补全批次。

## 4. 页面布局

### 4.1 时间轴视图

按钮位于底部“分镜序列”标题栏右侧、所有缩略图上方：

```text
分镜序列 · 12 个分镜 · 3 个待生成          [自动补全未生成分镜]
┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐
│分镜01│  │分镜02│  │待生成│  │分镜04│
└──────┘  └──────┘  └──────┘  └──────┘
```

### 4.2 网格视图

同一入口同步放到“故事板总览”标题栏右侧，并与“时间轴”视图切换按钮组成右侧操作区：

```text
故事板总览 · 12 个分镜 · 3 个待生成   [自动补全未生成分镜] [时间轴]
```

两种视图必须调用同一个 `renderAutoCompleteControl()`，不能分别实现按钮状态和文案。

### 4.3 响应式

标题栏使用左右布局，空间不足时允许标题摘要和操作区换行。按钮文字不得通过 viewport 宽度缩放；窄屏下保持可读文字和稳定高度，不退化成难以识别的纯图标按钮。

## 5. 前端状态模型

在 `web/js/storyboard/state.js` 增加统一状态：

```javascript
autoImageBatch: {
    batchId: null,
    status: 'idle',
    totalCount: 0,
    completedCount: 0,
    runningCount: 0,
    pendingCount: 0,
    failedCount: 0,
    itemsBySceneId: {},
    message: '',
    submitting: false,
}
```

批次状态：

| 状态 | 含义 |
| --- | --- |
| `idle` | 没有活动批次 |
| `submitting` | 正在提交补全请求 |
| `pending` | 批次已创建，等待调度 |
| `running` | 批次正在调度或生成 |
| `partial` | 部分成功、部分失败 |
| `failed` | 本轮目标全部失败 |
| `completed` | 本轮目标全部完成 |

`itemsBySceneId` 保存当前批次中每个真实目标分镜的状态、`asset_id`、`result_url`、错误码和错误消息。按钮、标题统计、时间轴缩略图和网格卡片统一读取该状态。

建议把批次状态归一化和派生选择器放入独立的纯前端模块，例如 `web/js/storyboard/auto_missing_images_state.js`。该模块不发请求、不渲染 DOM，只负责：

- 初始化和重置批次状态；
- 应用后端 batch status 响应；
- 按 `scene_id` 查询当前 item；
- 计算按钮视图模型；
- 计算分镜首帧显示状态；
- 序列化和解析批次恢复信息。

这样可避免 `auto_missing_images.js`、`polling.js` 和 `render.js` 之间形成循环依赖。

## 6. 统计口径

后端批次 item 包含故事板中的所有分镜，其中可能有：

- `plan_status=already_ready`：提交前已经有图；
- `plan_status=already_running`：提交前已有单图任务运行；
- `plan_status=pending`：本轮需要生成；
- `plan_status=limit_reached`：受 limit 限制未纳入本轮。

按钮进度不能直接使用 job 的全局 `completed_count`。重新补 5 张图时，原本已有的 13 张不能让按钮一开始显示为“13/18”。

本轮目标集合定义为：

```text
plan_status in {pending, already_running}
```

排除 `already_ready` 和 `limit_reached`。按钮中的 `补全中 2/5` 表示本轮 5 个真实目标中已有 2 个完成。

标题栏的“待生成”数量以页面当前真实状态为准：没有 `firstFrameUrl`，且不属于当前活动批次的 `pending/running` item。

## 7. 分镜显示状态

增加统一选择器 `getFirstFrameDisplayStatus(scene)`，优先级如下：

1. `scene.firstFrameUrl` 已存在：`ready`；
2. 当前 batch item 为 `running`：`running`；
3. 当前 batch item 为 `pending`：`pending`；
4. 当前 batch item 为 `failed` 且仍无图片：`failed`；
5. `scene.taskStatus.first_frame` 为后端运行状态：`running`；
6. 其他无图场景：`missing`。

显示规则：

| 状态 | 缩略图标记 | 样式 |
| --- | --- | --- |
| `missing` | 待生成 | 浅灰底、深灰文字 |
| `pending` | 排队中 | 浅蓝底、蓝色文字 |
| `running` | 生成中 | 蓝色底、白字、小型旋转图标 |
| `failed` | 生成失败 | 浅红底、红色文字 |
| `ready` | 不显示覆盖标记 | 保持图片干净 |

状态标记固定在缩略图左上角。无图片时，缩略图中央文字从“无画面”改为当前状态文案。状态变化不能改变缩略图宽高或挤压操作按钮。

## 8. 按钮状态

| 条件 | 图标和文案 | 交互 |
| --- | --- | --- |
| 有缺图、无活动批次 | wand 图标 + 自动补全未生成分镜 | 蓝色次主按钮，可点击 |
| `submitting=true` | loading 图标 + 正在提交补全任务 | 锁定 |
| 批次 `pending/running` | loading 图标 + 补全中 2/5 | 锁定 |
| 批次 `partial/failed` 且仍有缺图 | wand 图标 + 自动补全未生成分镜 | 恢复可点击 |
| 无缺图、无活动批次 | success 图标 + 分镜已全部生成 | 原生禁用 |

运行中的按钮不能使用原生 `disabled`，因为需求要求用户再次点击时得到说明。运行态使用：

```html
aria-disabled="true"
data-batch-locked="true"
```

点击锁定按钮时不提交请求，显示 toast：

```text
已有 5 个分镜正在排队或生成，请等待当前任务完成。
```

无缺图的“分镜已全部生成”按钮可以使用原生 `disabled`。

## 9. 生命周期与数据流

### 9.1 页面首次加载

1. 完成故事板、场景、模型偏好和鉴权信息加载。
2. 统计缺失首帧的分镜。
3. 读取当前 storyboard 对应的批次恢复记录。
4. 如果恢复记录含有效 `batch_id`，先请求 `GET /api/storyboard/image-batches/{batch_id}/status`。
5. 若批次仍为 `pending/running`，恢复前端状态并继续轮询。
6. 若批次已终结，应用终态、清除恢复记录，然后根据实际缺图决定是否展示可点击按钮。
7. 没有可恢复批次时，保持现有“首次打开自动生成缺失首帧”的行为。

### 9.2 用户点击补全

1. 同步设置 `submitting=true` 并局部刷新按钮，阻止双击。
2. 按页面实际缺图数量传入 `limit`，调用现有 `POST /api/storyboard/{storyboard_id}/auto-generate-missing-images`。
3. 成功后保存 `batch_id`，应用响应中的 items，并开始批次轮询。
4. 每个 `submitted/already_running/running` 分镜继续复用现有单分镜状态轮询。
5. 不改变 `sequence_mode`、`task_type`、`ratio` 等现有参数来源。

### 9.3 后端已有活动批次

现有后端可能返回：

- 相同幂等参数：直接返回已有 batch status，并带 `idempotent_reuse=true`；
- 不同参数但同 storyboard/asset_type 有活动批次：返回 HTTP 409、`active_batch_exists` 和 `payload.active_batch_id`。

两种情况都必须接管已有 `batch_id`，立即把按钮切换为“补全中”，并开始状态轮询。不得再次提交任务。

当前 `web/js/storyboard/api.js` 的 `readJson()` 只抛出错误文字，会丢失状态码和 payload。需要扩展错误对象：

```javascript
error.status = response.status;
error.code = data.error_code || data.error;
error.payload = data.payload || {};
```

### 9.4 批次轮询

扩展 `pollImageBatchStatus(batchId, callbacks)`，支持可选回调：

```javascript
pollImageBatchStatus(batchId, {
    onUpdate,
    onTerminal,
    onRecoverableError,
});
```

`auto_missing_images.js` 提供回调并更新统一状态；`polling.js` 不反向导入业务模块，避免循环依赖。

每次响应后：

1. 按 `plan_status` 过滤本轮目标；
2. 更新 `itemsBySceneId` 和派生统计；
3. 对返回 `result_url` 的 completed item，立即回填对应 scene 的 `firstFrameUrl`；
4. 对返回 `asset_id` 的 item，更新 `selectedFirstFrameId`；
5. 继续触发现有单分镜轮询，补齐候选资产等信息；
6. 只刷新标题栏、状态变化的缩略图和当前分镜相关区域。

直接应用 batch item 的 `result_url/asset_id`，可以避免批次已经完成、按钮显示“全部生成”，但缩略图仍短暂空白的问题。

### 9.5 批次终态

- `completed`：应用所有结果，清除恢复记录；如果页面不存在实际缺图，按钮显示“分镜已全部生成”。
- `partial`：应用成功结果，清除恢复记录；失败或未生成场景恢复为可补全状态。
- `failed`：清除恢复记录；所有仍无图场景恢复为可补全状态。
- 终态后不自动创建下一轮补全任务。

## 10. SessionStorage 设计

沿用 storyboard 级 key：

```text
storyboard_auto_missing_images_{storyboardId}
```

值从旧版字符串 `'1'` 升级为 JSON：

```json
{
  "version": 2,
  "storyboardId": 16,
  "batchId": 38,
  "targetSceneIds": [544, 545, 546, 547, 548],
  "updatedAt": "2026-07-11T10:00:00.000Z"
}
```

规则：

1. 恢复时不信任缓存中的 status，只信任 `batchId`，并向后端重新查询。
2. 读到旧值 `'1'` 或无法解析的内容时，删除旧值并重新执行当前缺图检查。
3. 批次进入终态后删除记录。
4. 删除全部分镜并重新拆分时，继续调用现有 reset 方法，同时清空内存中的 `autoImageBatch`。
5. `sessionStorage` 是标签页级缓存；其他标签页或其他浏览器创建的活动批次由后端幂等返回或 HTTP 409 接管。

## 11. 局部刷新

现有轮询已经通过 `updateSceneThumb()`、`updateCurrentSceneDetail()` 等方法避免全量 `renderApp()`。本功能保持该原则，新增：

- `updateAutoCompleteHeader()`：更新当前可见视图的标题摘要和按钮；
- `updateSceneFirstFrameStatus(scene)`：更新指定时间轴缩略图或网格卡片状态；
- 状态容器使用 `aria-live="polite"`；
- 运行按钮使用 `aria-busy="true"`。

批次轮询期间不得重置时间轴横向滚动位置、当前分镜选择、文本编辑焦点或右侧候选区滚动位置。

## 12. 异常处理

| 场景 | 行为 |
| --- | --- |
| 快速重复点击 | 第一次点击同步设置 submitting；后续点击只提示，不重复提交 |
| HTTP 409 `active_batch_exists` | 读取 `active_batch_id`，接管并轮询已有任务 |
| HTTP 400/403 等业务错误 | 解锁按钮，保留缺图状态，展示后端明确错误信息 |
| 网络提交失败 | 解锁按钮，不写 batch 缓存，允许再次点击 |
| 批次轮询暂时失败 | 保持按钮锁定，沿用退避轮询，不误判为任务失败 |
| 恢复的 batch 返回 404 | 清除失效缓存，恢复当前缺图按钮状态 |
| 分镜在批次运行时被删除 | 依赖后端已有 `scene_deleted` 收敛机制；前端忽略已不存在的 scene_id |
| 批次运行时新增缺图分镜 | 不加入当前批次；当前批次终结后计入“待生成”数量 |
| 切换时间轴/网格视图 | 保留同一个内存批次状态，新视图立即渲染一致状态 |
| 算力不足 | 展示后端错误，失败分镜保留“生成失败/待生成”，不自动重试 |

## 13. 文件改动范围

### 前端

- `web/js/storyboard/state.js`
  - 新增 `autoImageBatch`。
- `web/js/storyboard/auto_missing_images_state.js`
  - 新增纯状态归一化、派生统计、session 序列化逻辑。
- `web/js/storyboard/auto_missing_images.js`
  - 拆分“首次自动提交”“用户手动补全”“恢复已有批次”逻辑。
- `web/js/storyboard/api.js`
  - 保留非 2xx 响应的 HTTP status、error code 和 payload。
- `web/js/storyboard/polling.js`
  - 批次轮询增加回调；继续复用单分镜轮询。
- `web/js/storyboard/render.js`
  - 新增共用标题栏控制、按钮状态、缩略图状态标记和局部刷新函数。
- `web/js/storyboard/events.js`
  - 新增 `auto-complete-missing-frames` 点击处理和锁定提示。
- `web/css/storyboard.css`
  - 新增标题栏布局、次主按钮、状态标记、旋转动画和窄屏规则。

### 后端

不新增接口，不修改批次表结构。继续使用：

- `POST /api/storyboard/{storyboard_id}/auto-generate-missing-images`
- `GET /api/storyboard/image-batches/{batch_id}/status`

如果实施中发现 409 响应没有稳定返回 `payload.active_batch_id`，只修正现有错误响应契约，不增加新 API。

### 文档

实现完成后同步更新 `docs/storyboard/storyboard_auto_missing_images.md`，说明手动补全入口、批次恢复和状态显示规则。

## 14. 测试设计

### 14.1 状态模型单元测试

1. `already_ready` 不进入本轮目标总数。
2. `pending/already_running` 正确进入本轮目标总数。
3. completed item 的 `result_url/asset_id` 能回填 scene。
4. scene 已有 `firstFrameUrl` 时始终优先显示 ready。
5. quality 宫格尚未创建单分镜 ai_tools 时，batch pending/running 仍能显示排队中或生成中。
6. partial/failed 后仍无图的 scene 恢复为可补全。
7. 旧 session 值 `'1'`、损坏 JSON 和 storyboardId 不匹配时安全清理。

### 14.2 前端交互测试

1. 时间轴和网格标题栏都显示同一按钮和统计。
2. 有 3 个缺图时按钮可点击，并只提交一次请求。
3. 连续点击锁定按钮不重复提交，并出现已有任务提示。
4. 批次从 pending 到 running 到 completed 时，按钮和缩略图状态同步变化。
5. partial/failed 后按钮恢复可点击，再次点击只补无图分镜。
6. HTTP 409 后自动接管 `active_batch_id`。
7. 页面刷新后根据保存的 batchId 恢复轮询。
8. 无缺图时按钮显示“分镜已全部生成”并禁用。
9. 切换视图时状态不丢失、不重复提交。
10. 轮询局部刷新不改变时间轴滚动、选中分镜和输入焦点。

### 14.3 后端回归测试

1. 相同参数的活动批次继续返回 idempotent reuse。
2. 不同参数的活动批次继续返回 409 和 `active_batch_id`。
3. 终态批次不会阻止新一轮只生成缺图分镜。
4. speed、balanced、quality 模式的批次提交和算力扣减路径不变。

### 14.4 浏览器验收

在 `16:9`、`9:16` 项目和桌面/窄屏视口下检查：

- 标题和按钮无重叠、无溢出；
- 时间轴缩略图尺寸稳定；
- 纵向图片完整显示；
- 状态角标不遮挡时长和复制/删除按钮；
- 生成过程中滚动位置不跳动；
- 两种视图的状态和计数一致。

## 15. 验收标准

1. 任意故事板存在未生成首帧时，时间轴和网格视图都能看到补全入口。
2. 用户能从标题栏准确知道总分镜数、待生成数和当前补全进度。
3. 后端已有活动批次时，前端在一次接口响应内切换到锁定状态，不创建重复批次。
4. 批次失败后无需清缓存或重新拆分剧本，即可再次补全剩余分镜。
5. 重试不会重新生成已有成功首帧的分镜。
6. 页面刷新、切换视图和轮询更新不会丢失批次状态或破坏编辑体验。
7. 不新增数据库迁移，不改变现有算力扣减和 quality 宫格拆分链路。
