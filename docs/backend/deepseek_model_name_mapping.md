# DeepSeek 官方模型名映射（deepseek-flash 切换）

## 背景

2026-09 官方文档（<https://api-docs.deepseek.com/zh-cn/>）公告：

- 旧模型名 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 对应的模型已下线，
  请求将由 **DeepSeek-V4.1-Flash**（model ID：`deepseek-flash`）提供服务，按 Flash 价格计费。
  实测直接以旧名请求官方 endpoint 已返回 `404 InvalidEndpointOrModel.NotFound`。
- `deepseek-v4-pro` 在 2026-09-14 之后继续提供调用服务，计费方式不变，模型 ID 保持 `deepseek-v4-pro`。
- 视觉（VL）请求同样使用 `deepseek-flash`。

## 事故现象

任务执行时 DeepSeek 调用报错：

```
Error code: 404 - {'error': {'code': 'InvalidEndpointOrModel.NotFound',
'message': 'The model or endpoint deepseek-v4-flash does not exist or you do not have access to it. ...'}}
```

原因：`llm/openai_deepseek.py` 的 `_MODEL_NAME_MAP` 此前将内部友好名原样透传
（`deepseek-v4-flash` → `deepseek-v4-flash`），官方下线该模型名后即 404。

## 修复方案

只调整 DeepSeek 官方客户端出口处的映射，数据库 `model` 表、`config/model_catalog.py`
推荐位、计费（`config/default_vendor_model_billing.py`）等全链路继续使用原友好名，不做改动：

| model 表友好名（内部） | 实际 API model ID（出口） | 说明 |
| --- | --- | --- |
| `deepseek-v4-flash` | `deepseek-flash` | 修复点：旧名 404 |
| `deepseek-v4-flash-vision-exp` | `deepseek-flash` | 旧名同批下线，VL 请求统一走 `deepseek-flash` |
| `deepseek-v4-pro` | `deepseek-v4-pro` | 官方继续提供，不变 |
| `deepseek-chat`（旧兼容名） | `deepseek-flash` | 单级映射不链式传递，需直接指向最终 ID |
| `deepseek-reasoner`（旧兼容名） | `deepseek-v4-pro` | 不变 |

注意 `_resolve_model_name` 为单级查表：`deepseek-chat → deepseek-v4-flash` 这类
"先映射到中间名"的写法不会二次映射到 `deepseek-flash`，兼容旧名时必须直接指向最终 API model ID。

## 影响范围

- 仅 `LLMVendor.DEEPSEEK`（官方 `https://api.deepseek.com`）走 `DeepSeekOpenAIClient`，受此映射影响。
- `zjt_api` 等中转供应商有独立客户端（`llm/llm_client_factory.py` 路由），模型名体系不受影响。
- 计费单价、上下文窗口等元数据仍按 `model` 表中友好名对应的记录扣减，行为不变。

## 火山方舟托管 DeepSeek 同步下线（2026-09-12 补充）

火山方舟托管的 DeepSeek 为官方同源模型，模型名跟随官方体系：官方下线
`deepseek-v4-flash` 旧名后，方舟同步下线，`VolcengineOpenAIClient` 的恒等
映射（`deepseek-v4-flash` → `deepseek-v4-flash`）随之失效，调用报
`404 InvalidEndpointOrModel.NotFound`。

线上表现（vendor_model 关联 model 1005 同时挂在 volcengine / zjt_api /
deepseek 三家，2026-08-07 起配置）：

- `vendor=deepseek`（已修映射）：正常；
- `vendor=zjt_api`（中转站自有模型名体系）：正常；
- `vendor=volcengine`（恒等映射透传旧名）：**100% 404**，且 PM 智能体循环
  吞错重试 3 次后任务曾被标成 `completed`（error 未落库），用户侧只见 SSE
  error 事件。

本次修复（`llm/volcengine_openai_client.py`）：

1. `_MODEL_NAME_MAP` 与官方客户端同步：`deepseek-v4-flash` /
   `deepseek-v4-flash-vision-exp` → `deepseek-flash`（`deepseek-v4-pro` 不变）。
2. 新增 `_humanize_api_error` 钩子（`llm/openai_base_client.py` 基类提供默认
   不翻译实现）：方舟返回 `InvalidEndpointOrModel.NotFound` 时上抛中文提示
   「火山方舟账号未开通模型/接入点「xxx」……请改用其他供应商，或在火山方舟
   控制台开通该模型」，原始错误保留为 `__cause__`。
3. 任务创建入口前置校验（`llm/llm_client_factory.py`
   `get_vendor_model_unusable_reason`）：显式 (vendor_id, model_id) 的
   vendor_model 关联缺失或供应商凭据未配置时直接 400，不再把必败路由放进
   任务队列（`api/script_writer.py` `/session/{id}/task`、
   `api/storyboard.py` `/scene/{id}/ai-chat` 两个入口生效）。注意「凭据已
   配置但平台未开通该模型」入口无法判断，由上述调用期 404 明确报错兜底。
4. PM 连续失败达上限终止时，任务状态落库为 `failed` 并记录最后一次错误
   （`script_writer_core/agents/task_manager.py` `run_task` +
   `script_writer_core/agents/pm_agent.py` `last_loop_error`），不再出现
   「前端已报错、库里 completed」。

## 关联

- 代码：`llm/openai_deepseek.py` `_MODEL_NAME_MAP`、`llm/volcengine_openai_client.py` `_MODEL_NAME_MAP`
- 测试：`tests/script_writer_core/test_vision_model_registration.py::test_deepseek_client_maps_vision_model`
- 测试：`tests/llm/test_volcengine_humanize_error.py`（映射同步 + 404 翻译）
- 测试：`tests/llm/test_vendor_model_unusable_reason.py`（路由前置校验）
