# 视频工作流自动保存上传去重门

## 背景：ECS 公网出带宽周期性打满

生产入口流量经 frp 转发（用户 → ECS:80 → frp 隧道 → 本机 5173）。曾出现 ECS
公网出带宽周期性高峰（均值 ~5 Mbps、峰值 8.3 Mbps 触顶），排查结论：

1. **触发链**：前端每 60s 轮询 `/api/video-workflow/{id}/poll-status`
   （`web/js/workflow.js` 的 `pollWorkflowNodeStatus`），只要返回的
   `updated_nodes` 非空就调用 `autoSaveWorkflow()` 做**全量 PUT**。
2. **空转放大**：poll-status 服务端只返回「`project_id` 非空且 `url` 为空」
   的节点。**失败节点**（status=-1 永远没有结果 url）与 **CDN PENDING 节点**
   每一轮都会重复返回；前端对前者只是重复赋相同的 `error` 文案、对后者不写
   任何字段——**序列化内容逐字节不变，却每 60 秒全量上传一次**。
3. **请求体巨大**：`workflow_data` 存在结构性冗余（每个 `shot_frame` 节点嵌入
   全量 `scriptData`，`videoPrompt` 与 `shotJson` 内容重复），单个工作流可达
   9~18MB。多个挂机页面叠加即打满带宽。

## 方案：前端按"已确认内容基线"去重

不引入哈希库、不改后端协议：**直接比较序列化字符串**。

- 入口为 `http://`（非 secure context）时 `crypto.subtle` 不可用；
- body 字符串在保存路径本就构造好，`===` 比较为长度 + memcmp，
  零碰撞、零依赖。

### 状态机扩展（`web/js/auto_save_state.js`）

| 方法 | 说明 |
|------|------|
| `setConfirmedBody(workflowId, body)` | 记录服务端已确认的 body 基线，`workflowId` 参与匹配（切工作流自动失效） |
| `isConfirmedBody(workflowId, body)` | 去重门：与当前工作流基线逐字节一致才返回 true |
| `confirmSkipped()` | 门命中跳过上传后推进 `confirmedVersion`，保证关页 `isDirty()` 归零、不会触发 keepalive 补发绕过门 |
| `reset()` | 同时清理基线 |

### 门的位置与基线来源（`web/js/workflow.js`）

`autoSaveWorkflow()` 在 body 构造后、发起请求前过门；基线有三个写入点：

1. **自动/手动 PUT 返回 `code === 0`**——服务端已落库这份 body
   （失败不记录，下次照常重传，不存在假确认丢数据）；
2. **`loadWorkflow` 成功后**——加载即基线，页面刷新后无真实修改时
   第一次防抖保存也会跳过；
3. 恢复重放（`maybeRecoverPendingAutoSave`）成功后重新 `loadWorkflow`，
   基线随重放后的最新服务端内容重建。

自动保存与手动保存共用 `buildAutoSaveBody()`（`{workflow_data,
default_world_id, workflow_ratio}`）保证 body 严格同构——构造不一致会导致
基线永不命中（退化为总是上传，安全方向）。

### 正确性边界

- **跳过仅当「内容 == 服务端已确认内容」**：内容真实变化（如任务完成写入
  url）正常上传，丢失保护不受影响；
- **上传失败不记基线**：下次同内容仍会重传；
- **多标签页**：各自维护基线互不干扰；跨标签页 PUT 乱序是全量保存的既有
  问题（需后端 CAS 根治），去重门反而降低了覆盖频率；
- **服务端被其他端改写**：基线命中跳过 = 不覆盖服务端新内容，是保护而非丢失。

## 效果

挂机页面的稳态流量从「每 60s × 全量 body 永续」降为**零**；真实变化按事件
上传（有限次）。多页面同开的周期性带宽尖峰随之消失。

## 测试

`web/tests/auto_save_upload_gate.test.js`：基线命中/不命中、跨工作流隔离、
`confirmSkipped` 推进与关页决策兼容、reset 清理等 13 个用例。

## 后续优化（未包含在本改动）

`workflow_data` 结构性瘦身（`shot_frame` 不嵌入全量 `scriptData`、
`videoPrompt` 与 `shotJson` 二选一）可把单个工作流从 18MB 降到 ~3MB，
从根本上降低保存/加载/序列化成本。见《ECS 带宽问题调查》相关记录。
