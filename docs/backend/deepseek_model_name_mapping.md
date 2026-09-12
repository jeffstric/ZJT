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

## 关联

- 代码：`llm/openai_deepseek.py` `_MODEL_NAME_MAP`、`llm/volcengine_openai_client.py` `_MODEL_NAME_MAP`
- 测试：`tests/script_writer_core/test_vision_model_registration.py::test_deepseek_client_maps_vision_model`
- 测试：`tests/llm/test_volcengine_humanize_error.py`（映射同步 + 404 翻译）

## 2026-09-12 修正：方舟（volcengine）侧映射目标错误，已实测修正

上文"修复方案"对 **DeepSeek 官方 API**（api.deepseek.com）可能仍然成立（未持官方
key 复测），但 `65d02f83` 把同一映射（→ `deepseek-flash`）套到了**火山方舟**客户端
`llm/volcengine_openai_client.py`，并注释"方舟同步下线旧名（实测 404）"——此判断
经真实调用证伪：

1. `GET /api/v3/models`（方舟模型目录，131 个模型）中 DeepSeek 共 13 个，**全部带
   版本后缀**，且**不存在任何裸名**（`deepseek-v4-flash` / `deepseek-v4-pro` /
   `deepseek-flash` 均无）——`deepseek-flash` 是 DeepSeek 官方 API 的命名，方舟从未有。
   当时的"实测 404"对不存在的名字必然发生，不能证明"下线/改名"。
2. 错误码可区分两种 404：`InvalidEndpointOrModel.NotFound` = 名字不存在；
   `ModelNotOpen` = 名字正确但账号未开通。裸名全部报前者。
3. 生产 key + 开通账号实测：`deepseek-v4-flash-ga-260731`（GA 版，支持图片输入）、
   `deepseek-v4-pro-260425`、`deepseek-v4-pro-ga-260813` 全部 200；
   `deepseek-v4-flash-260425` 已 Retiring。

方舟侧正确映射（已修正进 `volcengine_openai_client._MODEL_NAME_MAP`）：

| model 表友好名 | 方舟实际 model ID | 说明 |
| --- | --- | --- |
| `deepseek-v4-flash` | `deepseek-v4-flash-ga-260731` | GA 在役版 |
| `deepseek-v4-flash-vision-exp` | `deepseek-v4-flash-ga-260731` | 方舟无 vision 变体，ga 版实测支持图片输入 |
| `deepseek-v4-pro` | `deepseek-v4-pro-260425` | ga-260813 亦可用（需账号开通） |

**教训**：vendor=volcengine 的"路由修复"当时仅经 mock 测试验证，从未真实调用方舟；
跨供应商套用模型名映射（官方 API 命名 ≠ 方舟命名）是本次误判根源。
