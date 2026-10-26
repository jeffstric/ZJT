# 2026-10-26 火山下线 doubao-seed-2-0-lite-260215 快照致营销 PM 全量失败

## 现象

- 用户侧（2026-10-26 19:41~19:44 会话，另 12:12 一批）：营销智能体对话报错
  `Error code: 400 - {'error': {'code': 'InvalidEndpoint.ClosedEndpoint', ...}}`。
- `logs/llm.2026-10-26.log`：`doubao-seed-2-0-lite-260215` 当日 15 次请求**全部失败**，
  出错点在 `script_writer_core/agents/pm_agent.py` 的 PM 主循环（loop 内重试导致短时间内连续报错）。

## 根因

**火山方舟下线了 `doubao-seed-2-0-lite-260215` 版本快照**（10-23 最后一个正常日，
10-25 02:09 起 100% 失败，判定官方于 10-24 前后停服）。

- `llm/volcengine_openai_client.py` 的 `_MODEL_NAME_MAP` 写死了该快照号：
  `'doubao-seed-2-0-lite' -> 'doubao-seed-2-0-lite-260215'`。
- 受影响面：所有走 `doubao-seed-2-0-lite` 的场景——营销 PM 对话
  （`config/model_catalog.py` `LLM_MARKETING` 推荐位）、画风识别、图片描述、
  VL 识图类节点（`config/constant.py` 的 `IMAGE_STYLE_PREFERRED_MODEL` /
  `IMAGE_DESCRIBE_PREFERRED_MODEL` / VL gateway 偏好等）。
- 数据库 `model` / `vendor` / `vendor_model` 表只存友好名，无快照号，改代码映射即可。
- 同日期 pro 快照 `doubao-seed-2-0-pro-260215` 生产 key 实测仍 200，未受影响。

## 修复（develop）

1. `llm/volcengine_openai_client.py` `_MODEL_NAME_MAP`：
   `doubao-seed-2-0-lite` → `doubao-seed-2-0-lite-260428`（生产 key 2026-10-26 实测 200；
   由 `GET /api/v3/models` 目录确认其为最新可用 2.0-lite 快照）。
2. `_humanize_api_error` 新增 `InvalidEndpoint.ClosedEndpoint` 翻译：上抛中文提示
   「版本快照已被官方下线停服，请更新 _MODEL_NAME_MAP 或改用其他供应商」，
   避免下次同类下线再出现裸英文 400。
3. `llm/zjt_openai_client.py` 同名映射同步改为 260428。注意：该渠道
   （`api_aggregator.site_0`）生产未配置 key，**无法实测**，启用前须先验证。
4. 测试：`tests/llm/test_volcengine_humanize_error.py` 新增 lite 映射断言与
   ClosedEndpoint 翻译断言。

## 候选但未采用的方案

- `doubao-seed-2-1-lite-260915`（更新一代 lite）：实测 404 `ModelNotOpen`，
  账号未开通，需控制台开通后才可用，故选同为 2.0 系且实测可用的 260428。
- 裸名 `doubao-seed-2-0-lite`：实测 404 `InvalidEndpointOrModel.NotFound`，
  方舟目录不存在裸名（与 DeepSeek 系结论一致，见
  `docs/backend/deepseek_model_name_mapping.md`）。

## 教训

`_MODEL_NAME_MAP` 里写死的带日期快照号是**易过期资产**：火山会滚动下线旧快照
（Retiring → ClosedEndpoint）。2026-09-13 的 DeepSeek 事故（方舟无裸名）之后，
本次是同一机制的第二击——映射目标必须定期用 `GET /api/v3/models` 对账；
上游返回 `InvalidEndpoint.ClosedEndpoint` 即为快照停服信号，优先怀疑映射过期，
而不是账号或网络问题。
