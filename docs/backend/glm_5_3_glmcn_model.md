# GLM-5.3（智谱 BigModel 国内站 / glmcn）接入说明

> 接入时间：2026-09-21（迁移 no_140_20260921_add_glmcn_vendor）
> 接入模式：**新增 glmcn 供应商**，直连智谱 BigModel 国内站官方 API
> （open.bigmodel.cn），与火山方舟（volcengine）相互独立的供应商/密钥

## 1. 供应商与端点

| 项目 | 值 |
|---|---|
| vendor_name | `glmcn`（新增供应商） |
| 协议 | OpenAI 兼容（`/api/paas/v4/chat/completions`） |
| Base URL | `https://open.bigmodel.cn/api/paas/v4`（`llm.glmcn.base_url` 可覆盖） |
| API Key 配置键 | `llm.glmcn.api_key`（`config/default_configs.py` 热更新，`is_sensitive`） |
| 客户端 | `llm/openai_glmcn.py` → `GlmcnOpenAIClient`（继承 `OpenAIBaseClient`） |
| 前缀路由 | `glm` → `LLMVendor.GLMCN`（`MODEL_PREFIX_VENDOR_MAP`） |
| 名称映射 | 无（BigModel 官方 API model ID 即 `glm-5.3`，友好名与 API ID 一致） |

## 2. 模型规格（按 BigModel 官方模型页）

| 项目 | 值 |
|---|---|
| 上下文窗口 | 1,024,000（1M） |
| 最大输出 | 128,000（128K） |
| 工具调用 / 思考 / 视觉 | 1 / 1 / 0（**纯文本输入**，不支持图片；多模态请用 glm-5.3-flash） |
| 结构化输出 / Function Call | 支持 |

## 3. 思考模式特性

GLM-5.3 **始终启用思考**：服务端无法关闭——用户侧关闭思考时
（`enable_thinking=False`），本系统不发思考参数，模型仍会在内部思考，
响应可能携带 `reasoning_content`（基类已兼容解析）。

`reasoning_effort` 仅支持 **low / high / max**（无 `medium`），而前端思考
强度为 low/medium/high 三档，直传 `medium` 会被拒绝。故
`GlmcnOpenAIClient._apply_thinking_params` 覆写：本供应商下全部模型均为
GLM 系列，无需按模型前缀区分，统一经 `LLMModel.GLM_REASONING_EFFORT_MAP`
映射（与火山方舟的 GLM-5.3 共用同一张映射表）：

| 前端 thinking_effort | GLM reasoning_effort |
|---|---|
| low | low |
| medium | high |
| high | max |
| max | max |

## 4. 前缀路由注意事项（与火山方舟 GLM 的前缀重叠）

`MODEL_PREFIX_VENDOR_MAP` 为插入序先命中先路由，存在前缀重叠：

- `glm-5.3-flash`（火山方舟）以 `glm-5.3` 开头，**必须先命中**专属前缀项
  `'glm-5.3-flash' → VOLCENGINE`，再落到通配项 `'glm' → GLMCN`；
- 新增方舟 GLM 模型时，须把更长的具体前缀排在 `'glm'` 通配项之前，
  否则会被误路由到 glmcn。

## 5. 计费档位（按 BigModel 国内站刊例价折算）

公式：`threshold = 0.04 × 10^6 / 单价(元/百万token)`（1 点算力 = 0.04 元），
normal 时段、不分段（`raw_token_threshold = NULL`）。

| 模型 | input（未命中） | out | cache_read（命中） |
|---|---|---|---|
| glm-5.3 | 5000（¥8/百万） | 1428（¥28/百万） | 17391（¥2.3/百万） |
| glm-5.3-flash | 50000（¥0.8/百万） | 14285（¥2.8/百万） | 173913（¥0.23/百万） |

> glm-5.3-flash 自迁移 no_141 起同时关联 glmcn 与 volcengine 两个供应商，
> BigModel 官方定价与火山方舟一致，故阈值相同；model 记录两供应商共用。

glm-5.3-flash（¥0.8/2.8/0.23 每百万）为 glm-5.3 定价的 1/10，可交叉核对。
代码默认档位目录同步维护于 `config/default_vendor_model_billing.py`
（管理后台「还原默认档位」使用）。调价时改 vendor_model 档位并同步该文件。

## 6. 改动文件清单

- `config/constant.py`：`LLMVendor.GLMCN`（+标签）、`LLMModel.GLM_5_3`
  （+标签）、`VENDOR_ICONS['glmcn']`、`MODEL_PREFIX_VENDOR_MAP`
  （`'glm-5.3-flash' → VOLCENGINE` 排前、`'glm' → GLMCN`）
- `llm/openai_glmcn.py`：新客户端（config 热更新 + GLM 思考强度映射覆写）
- `llm/llm_client_factory.py`：导入注册 `_VENDOR_CLIENT_MAP`、
  `vendor_config_map['glmcn']`（配置检查）
- `alembic/versions/no_140_20260921_add_glmcn_vendor.py`：vendor + model +
  vendor_model 计费档位
- `alembic/versions/no_141_20260921_link_glm_5_3_flash_glmcn.py`：glm-5.3-flash
  补 glmcn 关联（model 记录共用，note 去供应商化）
- `config/default_vendor_model_billing.py`：glmcn/glm-5.3 默认档位
- `config/model_catalog.py`：`MODEL_FAMILIES['glm-5.3'] = "GLM"`
- `config.example.yml` / `config_prod.base.yaml`：`llm.glmcn` 配置段
- `config/default_configs.py`：`llm.glmcn.api_key` / `llm.glmcn.base_url`
  热更新项（quick_config）
- `web/js/admin.js` + `web/i18n/locales/{zh-CN,en}/admin.json`：管理后台
  供应商卡片（API Key + Base URL）
- `tests/llm/test_glmcn_client.py`：思考映射与前缀路由测试

## 7. 注意事项

- glm-5.3-flash 为**双供应商模型**（no_141 起）：`/api/models` 按
  (model_id, vendor_id) 下发两条记录（volcengine / glmcn）。前端选择 glmcn
  条目时按 vendor_id 精确路由到智谱密钥；仅传模型名的历史调用路径按前缀
  回退到 volcengine（需配置 `volcengine.api_key`）。
- script_writer 模型选择器（LLM / 生图）已加供应商标识：下拉菜单每行右侧
  显示短名 pill 徽标（火山 / 智谱 / DeepSeek…，`VENDOR_SHORT_LABELS` 映射），
  闭合态显示「模型名 · 短名」，双供应商模型可直接区分。
- 回滚迁移会删除 glmcn vendor（本迁移新建，无其他模型共用）；
  删除 `model` 记录前会一并清理 vendor_model 关联。
- 若后续 BigModel 上架 glm-5.3 的新版本（如带日期后缀的 API ID），在
  `GlmcnOpenAIClient` 增加 `_MODEL_NAME_MAP` 覆写即可，model 表友好名不变。
- glmcn 与 volcengine 的 GLM 模型在 `/api/models` 中按 (model_id, vendor_id)
  数值对区分，前端选择后按 vendor_id 精确路由，不受前缀通配影响。
