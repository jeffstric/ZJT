# 调查：为什么「选择 AI 介入程度」似乎没有作用

- 调查日期：2026-08-30
- 涉及功能：剧本创作页（script_writer.html）顶栏的「AI 介入程度」下拉选择器
- 结论先行：**该设置此前从未生效过。前端确实发送了 `intervention_level` 参数，但后端接收任务请求的数据模型（`TaskCreateRequest`）中没有这个字段，参数在 API 边界被 Pydantic 静默丢弃，从未传递给任何智能体；同时系统提示词/SOP 中也不存在任何消费「介入程度」的逻辑。** 属于"前端单方面实现"的半成品功能。
- **⚠️ 状态更新（2026-08-30 当日）：已按第 6 节方案接入后端并生效**，精细档（detailed）会恢复"角色卡/场景道具满意度确认 + 选择生成形象的对象"流程，见第 6.5 节实施记录。

## 1. 功能现象

用户在剧本创作页顶栏可以选择「AI 介入程度」三档之一：

| 值 | 显示文案 | 预期行为 |
|----|---------|---------|
| `balanced` | 标准 | 默认行为 |
| `concise` | 简洁·少提问 | AI 更少打断用户、减少确认提问 |
| `detailed` | 精细·多确认 | AI 每个关键节点多向用户确认 |

实际现象：无论选择哪一档，剧本架构师（PM 智能体）的提问频率和确认行为没有任何变化。

## 2. 前端实现（正常）

前端实现是完整的，选择、持久化、发送三环节都在：

- `web/script_writer.html:302-315`：选择器 DOM（`#intervention-level-selector`），三个 option 的 value 为 `balanced` / `concise` / `detailed`
- `web/js/script_writer.js:2891-2937`：
  - `onInterventionLevelChange()`：切换时写入 `localStorage.lastInterventionLevel`
  - `restoreInterventionLevel()`：页面加载时恢复上次选择
  - `getInterventionLevel()`：读取当前值（默认 `balanced`）
- `web/js/script_writer.js:1307`：每次创建智能体任务时随请求体发送：
  ```js
  body: JSON.stringify({
      message,
      auth_token: AUTH_TOKEN,
      model: ...,
      ...
      intervention_level: getInterventionLevel()   // ← 这里发出了
  })
  ```

## 3. 后端接收（断裂点）

请求打到 `POST /api/session/{session_id}/task`（`api/script_writer.py:3745`），接收模型为 `TaskCreateRequest`（`api/script_writer.py:1016`）：

```python
class TaskCreateRequest(BaseModel):
    message: str
    auth_token: str = ""
    model: Optional[str] = None
    model_id: Optional[int] = None
    vendor_id: int = 1
    enable_thinking: bool = False
    thinking_effort: str = "medium"
    image_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None
    audio_urls: Optional[List[str]] = None
    thumbnail_urls: Optional[List[str]] = None
    image_preferences: Optional[Dict[str, Any]] = None
    video_preferences: Optional[Dict[str, Any]] = None
    language: Optional[str] = None
    # ← 没有 intervention_level 字段
```

Pydantic 对请求体中模型未声明的额外字段默认**静默忽略**（不报错、不透传），因此 `intervention_level` 在此处被丢弃。

对比可以佐证这是"漏接"而非"有意拒绝"：同类的 `enable_thinking` / `thinking_effort`（思维开关）和 `image_preferences` / `video_preferences`（偏好）都既有前端发送、也在此模型中声明并往下传递；唯独 `intervention_level` 只做了前端一半。

## 4. 全链路均无消费逻辑

对全仓代码检索 `intervention` 关键词，命中仅两处前端文件（`script_writer.html`、`script_writer.js`）和一份响应式 UI 文档，后端 `script_writer_core/`（PM 智能体、专家智能体、工具执行器）与 `api/` 中零命中。也就是说：

1. `TaskCreateRequest` 不接收该参数（如上）；
2. `PMAgent` / `ChatSession`（`script_writer_core/agents/pm_agent.py`、`script_writer_core/chat_session.py`）没有任何介入程度相关的属性；
3. 系统提示词构建（`pm_agent.py` 的 `_build_system_prompt`）注入的是技能文件（SKILL.md + SOP），其中所有「必须 ask_user 确认」的规则是无条件的，不存在按介入程度分支的措辞；
4. i18n 文案（`intervention_balanced/concise/detailed`）只有展示作用。

因此三档设置对智能体行为的影响严格为零。

## 5. 附带发现：与 SOP 改造的关系

同轮需求已把「角色卡/场景道具创建后的满意度确认」从 SOP 默认流程中移除（一步到位直接生成形象，见 `script_writer_core/skills/script-orchestrator/sops/sop-*.md`）：

- 默认（标准/简洁档）下，原 SOP 中最频繁的两类确认提问已被删除，「简洁·少提问」诉求的核心场景已通过 SOP 改造落地；
- **精细档**下，SOP 的"精细模式例外"条款会恢复这两类确认（满意度 + 选择生成形象的对象）；
- 大纲确认、剧本确认等步骤在所有档位均保留（文字内容仍需用户把关）。

## 6. 修复建议（已于 2026-08-30 实施）

若要真正让该设置生效，建议按以下最小闭环实施：

1. **接收**：`TaskCreateRequest` 增加 `intervention_level: Optional[str] = None`（校验取值 ∈ {balanced, concise, detailed}）。
2. **传递**：`create_agent_task` 中将其存到会话（如 `session.intervention_level`），随会话持久化（`session_storage`），避免每条消息都依赖前端重传。
3. **消费**：在 `PMAgent._build_system_prompt`（或系统提示词组装处）按档位追加一段行为指令，例如：
   - `concise`：「非关键决策不使用 ask_user，能自行决定的直接执行并汇报；仅在大纲、剧本定稿等必要节点询问」
   - `detailed`：「每个关键步骤（大纲/剧本/角色卡/场景道具/形象生成前后）都使用 ask_user 向用户确认」
   - `balanced`：不追加（维持 SOP 默认）
4. **生效范围**：只需影响 PM 智能体（提问行为由 PM 的 SOP 驱动）；专家智能体（expert agents）不直接面向用户提问，无需处理。
5. **回归验证**：切换三档分别创建剧本任务，观察 PM 在「大纲确认」等节点的提问行为差异。

### 6.5 实际实施记录（与建议方案的差异及原因）

| 环节 | 实施方式 | 说明 |
|------|---------|------|
| 常量 | `config/constant.py` 新增 `INTERVENTION_LEVEL_*`、`VALID_INTERVENTION_LEVELS`、`INTERVENTION_LEVEL_INSTRUCTIONS` | 档位指令文本集中在常量维护 |
| 接收 | `TaskCreateRequest.intervention_level`，API 层校验非法值回落 balanced | 同建议 |
| 传递 | `AgentTask.intervention_level` 字段 + `create_task` 透传；**不持久化到 agent_tasks 表** | 行为由指令文本驱动（见下），DB 重建任务时回落 balanced 仅影响日志 |
| 消费 | **指令文本由 API 层拼在 user_message 开头**（`create_agent_task`），而非改 system prompt | 原因：① system prompt 是 PM 初始化时构建的，中途切档无法更新；② PM 内存历史与 chat_messages 持久化共用 `task:{id}:user:initial` 幂等键，若由 PM 侧拼接会被幂等去重丢弃——必须在上游 API 层拼；与既有 `[用户视频偏好]` 注入方式一致 |
| SOP | 三个 SOP + script-orchestrator SKILL.md 的「一步到位」条款增加**精细模式例外**：detailed 档恢复"满意度确认 + 选择生成形象对象"两步 ask_user | 指令文本与 SOP 条款双向呼应，避免规则冲突 |
| 前端 | 无需改动 | `script_writer.js` 已在每条任务消息发送 `intervention_level`，切档即时生效 |

## 7. 相关文件索引

| 环节 | 文件 | 位置 |
|------|------|------|
| 前端选择器 | `web/script_writer.html` | 302-315 |
| 前端读取/发送 | `web/js/script_writer.js` | 1307、2891-2937 |
| 后端请求模型（断裂点） | `api/script_writer.py` | 1016-1029 |
| 任务接口 | `api/script_writer.py` | 3745 |
| PM 系统提示词构建 | `script_writer_core/agents/pm_agent.py` | 139-176 |
| SOP 确认节点（本轮已改造部分） | `script_writer_core/skills/script-orchestrator/sops/` | — |
