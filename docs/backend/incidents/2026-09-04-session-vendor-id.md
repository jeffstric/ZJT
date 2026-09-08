# 2026-09-04 运行中切换模型丢失 vendor_id，本地模型被误路由到 DeepSeek（400）

## 现象

用户在 PM 任务运行中切换 LLM 模型（13:16:20 从 deepseek-v4-flash 切到 `vllm:qwen3.8:27b`），下一轮 PM 循环开始持续报 DeepSeek API 400，连续 3 次失败后任务停止。

时间线（`logs/app.2026-09-04.log`）：

1. 13:14:51 创建任务 `bc2151f0`：`agent_tasks` 记录 vendor_id=7（deepseek）、model_id=1005（deepseek-v4-flash），PM 开始运行。
2. 13:16:20 用户切换模型：日志「模型切换成功 - session_id: 939fd7e2, model: vllm:qwen3.8:27b」。
3. 13:16:42 起 PM 循环调用 `get_llm_client('vllm:qwen3.8:27b', vendor_id=7)`：工厂中 vendor_id 优先于前缀路由 → 返回 DeepSeek client → 本地模型名被原样透传给 DeepSeek API → 400。

## 根因

「切换模型」链路全链路丢失 vendor_id：

- 前端 `web/js/script_writer.js` 的 `changeModel()` 只 POST `{model, model_id, auth_token}`；
- `api/script_writer.py` 的 `ModelChangeRequest` 没有 vendor_id 字段；
- `chat_sessions` 表没有 vendor_id 列，`ChatSession.set_model` 只更新 model/model_id。

结果：会话/PM 内存里是新模型字符串，运行中任务的 `task.vendor_id` 还是旧 vendor，两者脱钩，vendor_id 优先路由必然误路由。

注意 vendor_id 优先级不能整体取消：`MODEL_PREFIX_VENDOR_MAP` 中 `'qwen'` 排在 `'qwen3.5'/'qwen3.6'` 前，zjt_api 的 qwen3.5/3.6 必须靠 vendor_id 路由。只有 `vllm:`/`ollama:` 这种「vendor:模型名」显式本地格式可安全作为路由信号。

## 修复

- 前端 `changeModel()` 请求体携带 `vendor_id`；`ModelChangeRequest` 增加 `vendor_id` 字段；`set_session_model` 校验与 model_id 的 DB 关联一致性（不一致告警、以用户显式选择为准），并持久化到 `chat_sessions.vendor_id`（迁移 `no_126_20260904_add_vendor_id_to_chat_sessions`）。
- `ChatSession.set_model()` 同步 `pm_agent._vendor_id`，运行中的 PM 循环下一轮即生效；`session_storage` 加载/保存会话时带上 vendor_id（多 worker 部署下重载不丢失）。
- PM 循环中所有以 `self.model` 发起的调用改用 `getattr(self, '_vendor_id', None) or task.vendor_id`；`use_config_model` 专家路径（`_resolve_model_routing`）保持原逻辑。
- 防御层：`llm_client_factory.get_client` 中 `vllm:`/`ollama:` 显式前缀优先于 vendor_id，冲突时 warning；云端模型逻辑不变。
- `create_agent_task` 兜底：vendor_id 为默认值 1 时优先用会话保存的 vendor_id，DB 反查仅作兜底（`get_vendor_id_by_model_id` 为 `LIMIT 1` 无 ORDER BY，且关联可能缺失，不可靠）。

## 遗留数据问题（另行处理，本次未动数据）

- `vendor_model` 表 model_id=1011（qwen3.8:27b）无关联行，`get_available_models` 不会列出它；
- model_id=1005 存在重复关联（vendor 6 两行、vendor 7 两行）。
