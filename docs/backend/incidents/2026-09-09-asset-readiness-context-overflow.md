# 2026-09-09 资产检查专家（asset-readiness-checker）上下文超限事故

## 现象

剧本创作链路最后一步「最终资产检查」失败，前端报错：

```text
专家 asset-readiness-checker 执行失败: Error code: 400 - This model's maximum
context length is 1048576 tokens. However, you requested 1128825 tokens
(744825 in the messages, 384000 in the completion).
```

模型为 `deepseek-v4-flash-vision-exp`（上下文上限 1048576）。

## 日志佐证（logs/llm.2026-09-09.log）

同一专家任务连续三次请求，图片随轮次只增不减：

| 时间 | messages_count | 历史中的图片数 | 结果 |
|------|---------------|----------------|------|
| 16:04:45 | 44 | 0 | 正常 |
| 16:05:15 | 54 | 8 | 正常 |
| 16:05:43 | 64 | 16 | **400 超限** |

失败请求（payload 起于日志 33849 行）中 16 张图片以 `data:image/jpeg;base64,...`
注入，单张 base64 33K–89K 字符（平均约 6 万字符），合计约 97 万字符。
744825 ÷ 16 ≈ 每张图约 4.6 万 tokens，与 base64 字符量高度吻合——该 VL 模型
对图片基本按 base64 文本体量计费，250K 像素 + JPEG q85 的压缩挡不住 token 爆炸。

## 根因（两个叠加）

1. **历史图片只进不出、无数量上限**：`asset-readiness-checker/SKILL.md` 要求对
   每个非空 `reference_image` 的资产逐张调 `fetch_image_as_base64` 目检；工具成功后
   图片作为多模态 user 消息**永久追加**进 `conversation_history`
   （`expert_agent.py` deferred 多模态注入），无数量上限、无旧图清理。
   资产多（本次 16 张）时 messages 冲到 74 万 tokens。
2. **max_tokens 全量透传 DB 值 384000**：`expert_agent.py` / `pm_agent.py` 每次调用前
   读 `model.max_output_tokens` 直接作为 `max_tokens`；迁移
   `no_120_20260830_add_deepseek_v4_flash_vision_exp` 给该模型写的是
   `context_window=1000000, max_output_tokens=384000`——上下文量级数值被当成单次输出
   上限。即使输入只有 66 万 tokens，66 万 + 38.4 万也会超限。

## 修复（develop_f809）

- `config/constant.py` 新增：
  - `AGENT_LLM_MAX_OUTPUT_TOKENS_CAP = 32768`：Agent 链路 max_tokens 静态保险丝（只降不升，防 DB 脏数据）。
  - `AGENT_LLM_CONTEXT_SAFETY_MARGIN_TOKENS = 65536`：动态收缩的安全余量（覆盖估算到实际调用之间单轮新增的输入）。
  - `AGENT_LLM_MIN_OUTPUT_TOKENS = 4096`：动态收缩下限（上下文接近占满时仍保证短回复）。
  - `EXPERT_HISTORY_MAX_IMAGES = 6`：专家对话历史保留的最大图片数。
- `script_writer_core/agents/output_token_budget.py`（新增，`resolve_max_output_tokens`）：
  Agent 调用 max_tokens 统一按 `min(DB 值, 静态上限, context_window - 估算输入 - 安全余量)`
  动态计算——小上下文模型不会因固定上限残留超限风险，大输出模型也不被一刀切。
  估算输入取"上次 API 真实 input_tokens"与"本轮消息字符估算"的较大值
  （文本约 1.5 字符/token，图片按 base64 体量约 1.3 字符/token）。
- `expert_agent.py` / `pm_agent.py`：接入 `resolve_max_output_tokens`；
  expert 侧新增 `last_api_input_tokens` 记录与 `_estimate_input_tokens()`
  （pm 侧复用已有 `_estimate_current_tokens()`）。
- `expert_agent.py` 新增 `_prune_history_images()`：每次 LLM 调用前裁剪
  `conversation_history`，仅保留最近 N 张图片，被裁掉的 `image_url` 片段替换为
  文本占位（URL 仍留在相邻的「[系统注入]」文案中），LLM 需要重新查看时可再次调用
  `fetch_image_as_base64`。裁剪作用于内存历史，持久化的任务状态同步受益，
  恢复会话不会重新引入已裁掉的图片。
- `expert_agent.py` 修复 base64 二次泄漏：`fetch_image_as_base64` 的 result 含
  完整 `base64_data_url`，此前被 `json.dumps(result)` 原样写入 tool 消息历史，
  每张图的 base64 以纯文本形式永久驻留、每轮请求重发（图片裁剪管不到 tool 消息，
  实测 17 条 tool 结果 ≈ 100 万字符，检查后期单次输入仍涨到 74 万 tokens）。
  现在落历史前先 `pop("base64_data_url")`，图片仅通过多模态注入通道送达
  （符合工具 message 自身"图片将自动注入到你的对话中"的设计意图）。
- 测试：`tests/script_writer_core/test_expert_agent.py::TestPruneHistoryImages`、
  `TestFetchImageResultStripped`。

## 备注

- marketing 链路的 image-understanding 专家走同一个 `fetch_image_as_base64` /
  deferred 注入机制，本次修复对它同样生效。
- 前端（marketing_agent / script_writer）均未对图片做喂模型前的 canvas 压缩；
  压缩统一发生在工具侧 `utils/image_compressor.py:compress_local_image_to_base64`
  （≤250K 像素、JPEG q85、≤2MB）。
