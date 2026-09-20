# GLM-5.3-Flash（火山方舟）接入说明

> 接入时间：2026-09-21（迁移 no_139_20260921_add_glm_5_3_flash）
> 接入模式：**复用 volcengine 供应商**（智谱 GLM-5.3-Flash 上架在火山方舟，
> 与 doubao / deepseek 共用同一 api_key 与 OpenAI 兼容端点，不新增 vendor）

## 1. 供应商与端点

| 项目 | 值 |
|---|---|
| vendor_name | `volcengine`（存量供应商，复用） |
| 协议 | OpenAI 兼容（`/v3/chat/completions`） |
| Base URL | `https://ark.cn-beijing.volces.com/api/v3`（`volcengine.base_url` 可覆盖） |
| API Key 配置键 | `volcengine.api_key`（与 doubao 共用，无新增配置项） |
| 客户端 | `llm/volcengine_openai_client.py` → `VolcengineOpenAIClient`（继承 `OpenAIBaseClient`） |
| 前缀路由 | `glm` → `LLMVendor.VOLCENGINE`（`MODEL_PREFIX_VENDOR_MAP`） |
| 名称映射 | `glm-5.3-flash`（model 表友好名）→ `glm-5-3-flash-260828`（API model ID，`_MODEL_NAME_MAP`） |

## 2. 模型规格（按官方模型页）

| 项目 | 值 |
|---|---|
| 上下文窗口 | 1,024,000（1024k） |
| 最大输出 / 最大思考 | 128,000 / 128,000 |
| 工具调用 / 思考 / 视觉 | 1 / 1 / 1（原生多模态，支持图片输入） |
| 限速 | TPM 1000k / RPM 0.5k |
| 结构化输出 / Function Call / 联网搜索 | 支持 |

## 3. 思考模式特性（与 doubao 不同，重点）

GLM-5.3-Flash **始终启用思考**：`thinking.type` 仅支持 `enabled`（默认即开），
服务端无法关闭——用户侧关闭思考时（`enable_thinking=False`），本系统不发思考
参数，模型仍会在内部思考，响应可能携带 `reasoning_content`（基类已兼容解析）。

`reasoning_effort` 仅支持 **low / high / max**（默认 max，无 `medium`），
而前端思考强度为 low/medium/high 三档，直传 `medium` 会被方舟拒绝。故
`VolcengineOpenAIClient._apply_thinking_params` 覆写：按实际 API model ID 的
`glm` 前缀识别 GLM 系列，经 `LLMModel.GLM_REASONING_EFFORT_MAP` 映射：

| 前端 thinking_effort | 方舟 reasoning_effort |
|---|---|
| low | low |
| medium | high |
| high | max |
| max | max |

非 GLM 模型（doubao / deepseek）仍走基类默认行为（直传 `reasoning_effort`）。

## 4. 计费档位（按官方按量价折算）

公式：`threshold = 0.04 × 10^6 / 单价(元/百万token)`（1 点算力 = 0.04 元），
normal 时段、不分段（`raw_token_threshold = NULL`）。

| 模型 | input（未命中） | out | cache_read（命中） |
|---|---|---|---|
| glm-5.3-flash | 50000（¥0.8/百万） | 14285（¥2.8/百万） | 173913（¥0.23/百万） |

代码默认档位目录同步维护于 `config/default_vendor_model_billing.py`
（管理后台「还原默认档位」使用）。调价时改 vendor_model 档位并同步该文件。

## 5. 改动文件清单

- `config/constant.py`：`LLMModel.GLM_5_3_FLASH`、`GLM_REASONING_EFFORT_MAP`、
  `MODEL_PREFIX_VENDOR_MAP['glm']`、`LLMVendor._LABELS['VOLCENGINE']` 标签
- `llm/volcengine_openai_client.py`：`_MODEL_NAME_MAP['glm-5.3-flash']`、
  `_apply_thinking_params` GLM 思考强度映射覆写
- `alembic/versions/no_139_20260921_add_glm_5_3_flash.py`：model 记录 +
  volcengine vendor_model 计费档位（不新增 vendor）
- `config/default_vendor_model_billing.py`：volcengine/glm-5.3-flash 默认档位
- `config/model_catalog.py`：`MODEL_FAMILIES['glm-5.3-flash'] = "GLM"` 及
  `get_model_family` 的 `glm` 模糊分组

## 6. 注意事项

- 无需新增配置项 / 管理后台供应商卡片（复用 volcengine），`config.example.yml`
  等配置文件与 `config/default_configs.py` 均不需要改动。
- 回滚迁移只删 `vendor_model` 关联与 `model` 记录，**不动 volcengine vendor**
  （doubao / deepseek 仍在使用）。
- 若后续方舟替换版本后缀（如 `glm-5-3-flash-26xxxx`），只需更新
  `_MODEL_NAME_MAP` 映射值，model 表友好名保持 `glm-5.3-flash` 不变。
