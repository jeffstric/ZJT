# 内容审核 / 违禁错误友好展示 — 设计定稿（A + D）

> **状态：方案 A + D 已实现（代码已落地）。**  
> 本文为设计与实现对照说明：方案选择、分类模型、文案约定、接入点与 D 侧 LLM 联动。

| 项 | 说明 |
|----|------|
| 定稿方案 | **A 规则映射**（解释失败）+ **D 用户主动 LLM 改写提示词**（修复内容） |
| 核心模块 | `utils/content_moderation_error.py` |
| 失败归一 | `task/visual_task.py` → `_normalize_failure_reason` |
| 降低违规 | `POST /api/reduce-violation`（支持可选 `failure_reason` / `source`） |
| 单测 | `tests/utils/test_content_moderation_error.py` |
| 不做 | 失败时自动调 LLM 解释；提交前预检；本地违禁词库（本期） |

---

## 1. 背景与目标

### 1.1 问题

生图 / 生视频任务被上游内容安全策略拦截时，失败原因会原样写入 `ai_tools.message`，再经 `/api/get-status` 的 `reason` 展示给前端。用户常见文案为冗长英文，例如：

```text
任务提交失败: Your request was rejected by the safety system. If you believe this is an error,
contact us at Azure support ticket and include the request ID .... safety_violations=[violence].
```

```text
API 错误 [OutputImageSensitiveContentDetected]: The request failed because the output image
may contain sensitive information.
```

```text
Gemini image generation blocked [IMAGE_SAFETY]: The generated image was blocked due to safety
policy violation, please modify your prompt and try again (request id: ...)
```

**痛点：**

1. 看不懂英文错误码 / Azure 话术，不知道发生了什么。  
2. **提示词违规**、**参考图违规**、**生成结果敏感**、**版权/商标** 混在一起，无法针对性处理。  
3. 分镜页虽有「降低违规」入口，但失败提示本身没有引导用户用对手段。

### 1.2 目标

1. 失败 `reason` 为可读中文，并尽可能区分：提示词 / 参考图 / 生成结果 / 版权。  
2. 提示词相关失败可引导用户使用 LLM「降低违规」改写提示词（**用户主动**，非自动）。  
3. 规则集中维护；原文进日志便于运维。  
4. 写入 DB 的 `message` 即为友好文案，所有消费 `reason` 的 UI 自动受益。

### 1.3 非目标（本期）

1. 不做本地违禁词词典预检（成本高、误杀多，且各供应商策略不一致）。  
2. **失败瞬间不自动调用 LLM** 解释错误或改写提示词。  
3. 不做提交前全量预检（另一类问题，且与上游策略难对齐）。  
4. 不默认改变企业版「失败后切换实现方」策略（可二期加开关）。  
5. 审核失败应保持 **USER** 错误，不因文案改写误判为 SYSTEM 报警。

---

## 2. 方案选择：A + D

### 2.1 分层职责

| 层 | 方案 | 职责 |
|----|------|------|
| **解释失败** | **A 规则映射** | `code` / `message` → `source` + 固定中文模板；零额外算力、确定、可测 |
| **修复内容** | **D 按需 LLM** | 用户点击后调 `/api/reduce-violation` 改写提示词；复用现网能力 |

**一句话：** 解释错误用规则；帮用户改提示词用 LLM，且仅在用户点击时调用。

### 2.2 方案对比（为何不定纯 LLM）

| 方案 | 说明 | 结论 |
|------|------|------|
| **A 规则映射** | 白名单 code + 关键字 → 中文模板 | **解释路径主方案** |
| **B 纯 LLM 解释** | 每次失败把 error 丢给 LLM 生成文案 | **不做**：热路径贵、慢、不确定；日志错误高度模板化 |
| **C 规则 + LLM 兜底分类** | 规则未命中再 LLM | **二期可选**，配置开关默认关 |
| **D 按需 LLM 改写** | 用户点「降低违规」再改 prompt | **与 A 组合，本期设计** |
| **E 一刀切通用文案** | 不区分来源 | 不满足「提示词 vs 参考图单独拎出」 |
| **F 提交前预检** | 生成前过审核 API/LLM | 远期；不能替代上游拒绝后的友好提示 |

### 2.3 为何解释失败不必默认上 LLM

1. `customer_log` 抽样错误几乎全是固定模板（见 §3），规则可覆盖绝大多数。  
2. 失败路径再调 LLM：延迟、费用、可用性、超时红线（项目禁止无超时阻塞）。  
3. 把完整用户提示词发给 LLM 有隐私与二次内容风险；仅用 error 串时 LLM 也只是在「翻译模板」。  
4. LLM 更适合 **改写提示词**（已有 `/api/reduce-violation`），而不是翻译 error code。

---

## 3. 日志证据

### 3.1 `logs/customer_log/api_requests.2026-07-15.log`

抽样日共 **116** 条带 `error` 的 Response Body，**几乎全部为内容安全类**：

| 类型 | 约次数 | code / type | message 特征 |
|------|--------|-------------|--------------|
| Gemini `IMAGE_SAFETY` | 55 | `channel:image_generation_failed` / `channel_error` | `blocked [IMAGE_SAFETY]` + safety policy |
| GPT `moderation_blocked`（无标签） | ~34 | `moderation_blocked` / `image_generation_user_error` | rejected by the safety system |
| GPT + `safety_violations=[violence]` | 13 | 同上 | 带暴力标签 |
| Gemini `IMAGE_OTHER` | 9 | channel 同上 | copyright / trademark |
| Gemini `PROHIBITED` 系列 | 5 | channel 同上 | `IMAGE_PROHIBITED_CONTENT` / `PROHIBITED_CONTENT` |

**结论：客户侧最高频是 Gemini 网关 channel 错误，其次是 GPT Image moderation_blocked。**

### 3.2 其它 api_requests 样本

| 供应商 | 典型 code | 说明 |
|--------|-----------|------|
| GPT Image | `moderation_blocked` | 可带 `safety_violations=[violence\|sexual\|...]` |
| GPT Image | `invalid_prompt` | 明确提示词侧 |
| Seedream | `OutputImageSensitiveContentDetected` | 输出图敏感 |
| Seedream | `InputImageSensitiveContentDetected`（约定） | 参考图 / 输入图 |
| Seedream | `InputTextSensitiveContentDetected`（约定） | 输入文本 / 提示词 |

### 3.3 实现时必须覆盖的原始报文示例

**GPT Image**

```json
{
  "error": {
    "message": "Your request was rejected by the safety system. ... safety_violations=[violence].",
    "type": "image_generation_user_error",
    "code": "moderation_blocked"
  }
}
```

```json
{
  "error": {
    "message": "Your request was rejected by the safety system.",
    "type": "invalid_request_error",
    "code": "invalid_prompt"
  }
}
```

**Gemini（网关）**

```json
{
  "error": {
    "message": "Gemini image generation blocked [IMAGE_SAFETY]: The generated image was blocked due to safety policy violation, please modify your prompt and try again",
    "type": "channel_error",
    "code": "channel:image_generation_failed"
  }
}
```

```json
{
  "error": {
    "message": "Gemini image generation blocked [IMAGE_OTHER]: Image generation was stopped, often related to copyright or trademark concerns, please modify your prompt and try again",
    "type": "channel_error",
    "code": "channel:image_generation_failed"
  }
}
```

**Seedream**

```json
{
  "error": {
    "code": "OutputImageSensitiveContentDetected",
    "message": "The request failed because the output image may contain sensitive information."
  }
}
```

---

## 4. 现状链路与目标链路

### 4.1 现状（未实现前）

```text
上游 API 400
  → 驱动 submit_task / check_status 返回 error 字符串（多为英文）
  → visual_task._handle_task_failure(reason=...)
  → _normalize_failure_reason(reason) 仅做 str/json 归一
  → AIToolsModel.update(..., message=reason)
  → GET /api/get-status → reason
  → 前端 truncateErrorMessage 截断后 Toast / 状态行展示
```

| 层级 | 位置 | 现状 |
|------|------|------|
| 驱动 | `task/visual_drivers/*` | 拼接 `任务提交失败: {英文}` 或 `API 错误 [code]: ...` |
| 任务失败 | `task/visual_task.py` | 不识别审核类错误 |
| 状态 API | `server.py` `get_status` | 透传 `task_record.message` |
| 前端展示 | `web/js/nodes.js` | 截断，不做语义改写 |
| 降低违规 | `server.py` `/api/reduce-violation`、`shot_frame_node.js` | 已有 LLM 改写，与失败 reason 未联动 |

### 4.2 目标链路（A + D）

```text
上游 400 → 驱动 error
  → visual_task._handle_task_failure
  → _normalize_failure_reason   ←【A】规则改写 → 中文 message
  → get-status.reason（中文）
  → 前端展示
  →【D】按 source 露出「降低违规」（提示词相关）
  → 用户点击 → POST /api/reduce-violation → 回填提示词 → 再次生成
```

**失败路径默认零 LLM 调用**；仅用户点击「降低违规」时走 D。

---

## 5. 方案 A 详细设计（规则映射）

### 5.1 分类模型

| 字段 | 含义 |
|------|------|
| `source` | 用户行动建议来源，见下表 |
| `violations` | 可选标签列表（violence、sexual、safety…） |
| `error_code` | 上游 code（便于日志） |
| `friendly_message` | 写入 `ai_tools.message` 的用户文案 |

**source 枚举：**

| source | 含义 | 用户行动 |
|--------|------|----------|
| `prompt` | 提示词 / 输入文本敏感 | 修改提示词；引导「降低违规」 |
| `reference_image` | 参考图 / 输入图敏感 | 更换参考图 |
| `output` | 生成结果被判敏感 | 调整提示词或参考图后重试 |
| `copyright` | 版权 / 商标 | 去掉受保护形象 / 品牌描述或素材 |
| `general` | 能判定为审核失败，无法细分 | 检查提示词和参考图 |

### 5.2 识别优先级

1. **结构化 code**  
   - `invalid_prompt` → `prompt`  
   - `moderation_blocked` → `general`（可用 safety_violations 补标签）  
   - `InputTextSensitiveContentDetected` → `prompt`  
   - `InputImageSensitiveContentDetected` / `InputVideoSensitiveContentDetected` → `reference_image`  
   - `OutputImageSensitiveContentDetected` / `OutputVideoSensitiveContentDetected` / `OutputTextSensitiveContentDetected` → `output`  
   - `SensitiveContentDetected` → `general`  
2. **Gemini 内嵌原因码**（`image generation blocked [REASON]`）  
   - `IMAGE_SAFETY` → `output`（+ 标签 safety）  
   - `IMAGE_PROHIBITED_CONTENT` / `PROHIBITED_CONTENT` → `prompt`（+ prohibited）  
   - `IMAGE_OTHER` + copyright/trademark 文案 → `copyright`  
3. **message 关键字**（safety system、sensitive content、policy violation、copyright…）  
4. **type**  
   - `image_generation_user_error`：可辅助认定为审核类  
   - `channel_error`：**必须**结合 blocked / safety / prohibited / copyright 类 message，不能全盘当审核  

**注意：** `code=channel:image_generation_failed` **单独不足**以判定审核失败。

### 5.3 标签映射（violations → 中文）

| 原始 | 展示 |
|------|------|
| violence | 暴力 |
| sexual | 色情 |
| self_harm / self-harm | 自残 |
| hate | 仇恨 |
| harassment | 骚扰 |
| illegal | 违法 |
| drugs | 毒品 |
| weapon(s) | 武器 |
| child | 未成年人相关 |
| political | 政治敏感 |
| safety | 安全策略 |
| prohibited | 违禁内容 |
| copyright / trademark | 版权/商标 |

解析来源示例：

- GPT：`safety_violations=[violence,sexual]`  
- Gemini：`[IMAGE_SAFETY]` → safety；copyright 文案 → copyright  

### 5.4 用户可见文案（定稿）

统一前缀：`内容审核未通过`

| 场景 | 文案 |
|------|------|
| 提示词 | `内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试` |
| 参考图 | `内容审核未通过：参考图片包含敏感内容，请更换参考图后重试` |
| 生成结果 | `内容审核未通过：生成结果可能包含敏感内容，请调整提示词或参考图后重试` |
| 版权/商标 | `内容审核未通过（版权/商标）：提示词或参考内容可能涉及受保护形象/标识，请修改后重试` |
| 通用 | `内容审核未通过：请求被安全系统拦截，请检查提示词和参考图后重试` |
| 通用 + 标签 | `内容审核未通过（暴力）：请检查提示词和参考图后重试` |
| 输出 + 标签 | `内容审核未通过（安全策略）：生成结果可能包含敏感内容，请调整提示词或参考图后重试` |

**文案约束：**

- 单行、偏短（适配前端 `truncateErrorMessage` 默认约 120 字）  
- 不暴露 request id、Azure 工单话术、供应商内部路由  
- 中文为主；已是「内容审核未通过…」的字符串不得二次包裹  

### 5.5 模块约定（已实现）

路径：`utils/content_moderation_error.py`（纯函数，无 I/O）

```text
classify_content_moderation(error_code, error_message, error_type) -> Optional[dict]
format_user_facing_moderation_error(...) -> Optional[str]
build_user_error_from_api_error(error_payload, fallback_prefix=...) -> str
rewrite_failure_reason_if_moderation(reason: str) -> str
extract_api_error_fields(error_payload) -> (code, message, type)
```

- 非审核错误：`format_*` / `classify_*` 返回 `None`，调用方保持原逻辑  
- `build_user_error_from_api_error`：审核类返回友好中文；否则 `fallback_prefix: ...`  

### 5.6 接入策略（实现优先级）

| 优先级 | 位置 | 动作 |
|--------|------|------|
| **P0** | `task/visual_task.py` → `_normalize_failure_reason` | 所有失败写入 message 前统一 rewrite（全链路兜底） |
| **P0** | `utils/content_moderation_error.py` + 单测 | 规则与表驱动用例 |
| **P1** | GPT Image / Gemini Image / Seedream / Seedance 驱动 | error 分支优先友好文案；**日志保留英文原文** |
| **P1** | Seedream / Seedance 校验分支 | 见 §5.7 坑 |
| **P2** | `web/js/nodes.js` `truncateErrorMessage` | 历史英文 reason 前端兜底 |

原则：**后端归一为主，前端兜底为辅。**

### 5.7 实现踩坑（必须写进开发清单）

Seedream / Seedance 存在类似逻辑：

```python
if "API 错误" in error_msg:
    return USER error
else:
    return SYSTEM + 报警
```

若只把文案改成「内容审核未通过…」而不改判断条件，会把用户审核失败误判为系统故障并报警。  
**实现时必须同时将审核类文案视为 USER**（例如 `startswith("内容审核未通过")` 或统一 `error_type`）。

### 5.8 与企业版重试

`_handle_task_failure` 在 USER 失败时仍可能切换实现方（不同供应商审核策略不同，有时有效）。

- **一期默认：** 不改变重试策略，只改用户可见 reason。  
- **二期可选：** `error_subtype=CONTENT_MODERATION` + 配置「审核失败是否切换实现方」。

### 5.9 原始错误日志

无论是否友好化展示：

- 驱动 `logger.warning` 保留完整上游 message / code  
- 可选：`AIToolsLogModel` detail 中保留 `raw_error`  
- 用户 message 只写友好中文  

---

## 6. 方案 D 详细设计（按需 LLM 改写）

### 6.1 定位

| 用 LLM | 不用 LLM |
|--------|----------|
| 用户主动「降低违规 / 改写提示词」 | 失败瞬间自动解释 reason |
| 帮助弱化可能触发审核的表述 | 自动静默重试生图 |

### 6.2 现有接口

**`POST /api/reduce-violation`**（`server.py`）

- 请求：`{ "prompt": "...", "failure_reason"?: "...", "source"?: "prompt|reference_image|output|copyright|general", "model"?: "...", "vendor_id"?: <int>, "model_id"?: <int> }`
- 实现：走统一 LLM 工厂 `get_llm_client(model, vendor_id)`（`_rewrite_with_llm` 辅助函数），**已废弃**旧的 `call_qwen_chat_async`（遗留 `llm/qwen.py`，静态读取 `llm.qwen.api_key` 且不查数据库，生产环境空 key 导致 500）
- 改写模型来源：优先用前端传入的拆分模型（`model`/`vendor_id`）；前端未传或该供应商未配置 api_key 时，降级用 `LLMModel.REDUCE_VIOLATION_DEFAULT`（默认 `deepseek-v4-flash`，走 DEEPSEEK 供应商独立 key；2026-08 原默认 `gemini-3-flash-preview` 已下线）
  - **凭据可用性判断**：`_client_configured()` 对 Ollama 等本地部署 client（无需联网鉴权）直接视为已配置，避免被 `api_key` 为空的判断误伤而强制切兜底
  - **兜底二次校验**：切到 `REDUCE_VIOLATION_DEFAULT` 后再次校验 api_key，若兜底模型同样未配置（社区版/新装环境），抛出明确错误（提示去管理后台配置），而非让底层 `call_api` 抛晦涩的 500
  - **计费 ID 跟随实际模型**：切兜底后 `vendor_id`/`model_id` 置 None，避免兜底调用的 token 用量被记到原拆分模型账上
- user prompt 已改为通用「内容安全 / 生图审核」表述，去掉写死 sora
- 响应：`{ code: 0, data: { prompt: "改写后..." } }`
- 前端：`web/js/shot_frame_node.js` 的「降低违规」按钮调用，点击时从分镜节点向上追溯（分镜→分镜组→剧本）取出剧本拆分模型随请求传入

### 6.3 产品行为（按 source 引导）

| 失败 source | UI 行为 |
|-------------|---------|
| `prompt` | **强引导**「降低违规 / 改写提示词」 |
| `general` / `output` | 提供按钮（生成结果敏感也常与提示词相关） |
| `reference_image` | **不**主推只改提示词；文案引导更换参考图 |
| `copyright` | 引导去掉品牌/形象；改写可选，并提示「版权类改写可能无效」 |

展示位置（实现时按页面拆）：

- 工作流：图片节点 / 分镜节点失败状态旁  
- 故事板：失败 reason 旁操作  
- 已有分镜「降低违规」按钮：扩展触发条件与文案，与 A 的 reason 联动  

### 6.4 接口演进建议（设计，待开发）

> 状态更新：`failure_reason` / `source` / `model` / `vendor_id` / `model_id` 与「去掉写死 sora」**均已落地实现**（见 6.2）。以下保留原始设计描述供参考。

兼容现有只传 `prompt`；可选扩展：

```json
{
  "prompt": "用户原始提示词",
  "failure_reason": "内容审核未通过（暴力）：请检查提示词和参考图后重试",
  "source": "prompt",
  "model": "deepseek-v4-flash",
  "vendor_id": 1,
  "model_id": 2
}
```

- `failure_reason` / `source`：帮助模型针对性弱化暴力、色情等方向
- `model` / `vendor_id` / `model_id`：跟随剧本拆分时选用的模型改写（前端从分镜节点追溯到剧本节点传入）；未传时后端用 `LLMModel.REDUCE_VIOLATION_DEFAULT` 兜底
- 改写指令应 **去掉写死 sora**，改为通用「内容安全 / 生图审核」表述，覆盖 GPT / Gemini / Seedream 等
- 输出：仅改写后的提示词，无解释段落（与现网一致）

### 6.5 算力与超时（产品 / 技术待定）

| 项 | 建议 |
|----|------|
| 是否扣用户算力 | **实现前核对现网** `reduce-violation` 行为；文档不擅自假定。产品可定为「工具类改写免费」或「按 LLM 计价」 |
| 超时 | 沿用 async LLM 客户端；前端 loading；禁止无超时阻塞 |
| 失败路径 | 用户未点击则 **零** LLM 调用 |

### 6.6 A 与 D 状态机

```text
任务 FAILED
  message = A 规则中文（如「内容审核未通过：提示词…」）
  （一期可不新增 DB 字段，靠文案区分 source；二期可 structured reason）
        │
        ├─ source≈prompt/general/output → 展示「降低违规」
        │         │
        │         └─ 用户点击
        │               → POST /api/reduce-violation
        │               → 回填编辑框
        │               → 用户再次点生成
        │
        └─ source≈reference_image → 引导换图，不强调改写
```

### 6.7 一期 vs 二期（D 相关）

| 项 | 阶段 |
|----|------|
| 失败 reason 已是中文（A）后，文案层提示可改提示词 | 一期 |
| 失败 UI 露出/高亮「降低违规」 | 一期（可紧随 A） |
| reduce-violation 去掉 sora 写死、支持 failure_reason | ✅ 已落地 |
| reduce-violation 迁移统一 LLM 工厂、跟随剧本拆分模型改写、废弃 llm/qwen.py | ✅ 已落地（修复生产空 key 500） |
| structured `error_subtype` / source 入库 | 二期 |
| 规则未命中时 LLM 兜底分类错误（方案 C） | 二期，默认关 |

---

## 7. 明确不做与二期

| 项 | 阶段 |
|----|------|
| 方案 A 规则映射 | **实现一期** |
| 方案 D 联动 + reduce-violation 泛化 | **实现一期**（可紧随 A） |
| 方案 C：规则未命中再 LLM 分类 | 二期，配置开关默认关 |
| 方案 F 提交前预检 | 远期 |
| 方案 B 纯 LLM 解释失败 | **不做** |
| 审核失败禁止切换实现方 | 二期产品决策 |

---

## 8. 将来实现顺序（本文不执行）

1. `utils/content_moderation_error.py` + 单测（customer_log 模板表驱动）  
2. `visual_task._normalize_failure_reason` 接入  
3. 主要驱动 error 分支 + Seedream/Seedance USER 判断修补  
4. 前端 reason 展示确认；`truncateErrorMessage` 兜底（可选）  
5. reduce-violation 泛化 + 失败 UI 引导「降低违规」  
6. 真机：GPT / Gemini / Seedream 各验证一条审核失败 + 一条改写  

---

## 9. 测试与验收标准（实现后）

### 9.1 方案 A

| 用例 | 期望 |
|------|------|
| GPT `moderation_blocked` + violence | 中文 + 暴力标签 |
| GPT `invalid_prompt` | 提示词向文案 |
| Gemini `IMAGE_SAFETY` | 生成结果 / 安全策略向 |
| Gemini `IMAGE_OTHER` + copyright | 版权/商标文案 |
| Seedream `OutputImageSensitive*` | 生成结果向 |
| Seedream `InputImageSensitive*` | 参考图向 |
| 网络超时 / rate limit | **不**改写为内容审核 |
| 已是「内容审核未通过…」 | 不二次包裹 |
| 失败热路径 | **无**默认 LLM 调用 |

### 9.2 方案 D

| 用例 | 期望 |
|------|------|
| prompt 源失败 | 可见「降低违规」入口 |
| reference_image 源失败 | 不误导为「只改提示词即可」 |
| 点击改写 | 返回可用新 prompt；失败有错误提示 |
| 未点击 | 无 LLM 请求 |

---

## 10. 相关文件索引

| 文件 | 角色 |
|------|------|
| `task/visual_task.py` | 失败归一、写 message（A 接入点） |
| `utils/content_moderation_error.py` | 规则模块（已实现） |
| `task/visual_drivers/gpt_image_common_v1_driver.py` | GPT 提交错误 |
| `task/visual_drivers/gemini_image_preview_common_v1_driver.py` | Gemini 提交错误 |
| `task/visual_drivers/seedream_volcengine_v1_driver.py` | Seedream 校验/提交 |
| `task/visual_drivers/seedance_volcengine_v1_driver.py` | Seedance 校验/提交 |
| `server.py` `get_status` | reason 透传 |
| `server.py` `/api/reduce-violation` | D：LLM 改写提示词 |
| `web/js/nodes.js` | 前端截断展示 / 可选兜底 |
| `web/js/shot_frame_node.js` | 已有「降低违规」按钮 |
| `logs/customer_log/` | 客户侧真实错误样本 |

---

## 11. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-16 | 初稿：基于 customer_log 与 api_requests 的规则向设计 |
| 2026-07-16 | 撤销试写代码，仅保留设计文档 |
| 2026-07-16 | **定稿 A + D**：解释失败用规则，修复提示词用按需 LLM；补充方案对比、D 联动、reduce-violation 演进与验收标准 |
| 2026-07-16 | **实现落地**：util + visual_task + GPT/Gemini/Seedream/Seedance 驱动 + 前端兜底 + reduce-violation 泛化 + 分镜降低违规联动 |
