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

## 关联

- 代码：`llm/openai_deepseek.py` `_MODEL_NAME_MAP`
- 测试：`tests/script_writer_core/test_vision_model_registration.py::test_deepseek_client_maps_vision_model`
