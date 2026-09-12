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

## 火山方舟托管 DeepSeek（2026-09-12/13 补充，含 2026-09-13 实测勘误）

线上表现（vendor_model 关联 model 1005 同时挂在 volcengine / zjt_api /
deepseek 三家，2026-08-07 起配置）：

- `vendor=deepseek`（已修映射 → `deepseek-flash`）：正常；
- `vendor=zjt_api`（中转站自有模型名体系）：正常；
- `vendor=volcengine`：**100% 404**，且 PM 智能体循环吞错重试 3 次后任务
  曾被标成 `completed`（error 未落库），用户侧只见 SSE error 事件。

**勘误（2026-09-13 生产 key 实测）**：此前"方舟同步官方下线旧名，映射
`deepseek-flash` 即可修复"的判断是错的。方舟目录（GET /api/v3/models，
131 个模型）中 DeepSeek 共 13 个，**ID 全部带版本后缀，不存在任何裸名**
（`deepseek-v4-flash` / `deepseek-v4-pro` / `deepseek-flash` 均无）——
`deepseek-flash` 是 DeepSeek 官方 API 的命名，方舟从来没有；裸名调用必然
`InvalidEndpointOrModel.NotFound`，与账号开通状态无关（错误码
`ModelNotOpen` 才是未开通）。

实测 200 的方舟 ID（生产 key，2026-09-13）：`deepseek-v4-flash-ga-260731`
（GA 版，实测支持图片输入）、`deepseek-v4-pro-ga-260813`、
`deepseek-v4-pro-260425`；`deepseek-v4-flash-260425` 已 Retiring。

本次修复（`llm/volcengine_openai_client.py`）：

1. `_MODEL_NAME_MAP` 映射到方舟实测可用的带版本 ID：
   `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` →
   `deepseek-v4-flash-ga-260731`（方舟无 vision 变体，ga 版实测支持图片
   输入，作为 vision-exp 的替代）；`deepseek-v4-pro` →
   `deepseek-v4-pro-ga-260813`。
2. 新增 `_humanize_api_error` 钩子（`llm/openai_base_client.py` 基类提供默认
   不翻译实现）：方舟返回 `InvalidEndpointOrModel.NotFound` 时上抛中文提示
   「火山方舟账号未开通模型/接入点「xxx」……请改用其他供应商，或在火山方舟
   控制台开通该模型」，原始错误保留为 `__cause__`。

教训：跨供应商套用模型名映射（DeepSeek 官方的改名不等于方舟的改名），
mock 测试掩盖了从未真实调用过方舟的事实——映射修复必须用真实 key 实测。

## 前端 localStorage 脏缓存治理（2026-09-13 补充）

误选 volcengine 路由的用户浏览器里，`lastSelectedLlmModel` 等 key 存有
`{model_id: 1005, vendor_id: 4}`；页面每次加载由恢复逻辑自动选回 volcengine
条目，而下拉收起只显示纯模型名（不带供应商），用户无从发现，重选动作从未
发生 → 脏值永不被覆盖 → 每次发送仍走 volcengine。

处理：换 key 使全部存量脏缓存一次性失效，不动数据库——

- `lastSelectedLlmModel` → `lastSelectedLlmModelV2`（script_writer.js）
- `storyboard_lastSelectedLlmModel` → `storyboard_lastSelectedLlmModelV2`
- `storyboard_lastScriptSplitLlmModel` → `storyboard_lastScriptSplitLlmModelV2`
- storyboard 恢复逻辑不再回退读 script_writer 的旧公共 key（两页供应商
  体系不同，跨页共享会互相带入坏路由）

所有保存点结构统一为 `{model, model_id, vendor_id}`（vendor_id 必带）。
新 key 首次读取为空 → 恢复逻辑落到场景默认路由（deepseek 官方），存量
中招用户自动治愈，无需任何手动清理。

## 关联

- 代码：`llm/openai_deepseek.py` `_MODEL_NAME_MAP`、`llm/volcengine_openai_client.py` `_MODEL_NAME_MAP`
- 测试：`tests/script_writer_core/test_vision_model_registration.py::test_deepseek_client_maps_vision_model`
- 测试：`tests/llm/test_volcengine_humanize_error.py`（映射同步 + 404 翻译）
