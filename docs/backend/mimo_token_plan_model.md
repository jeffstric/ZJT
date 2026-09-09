# 小米 MiMo（Token Plan）接入说明

> 接入时间：2026-09-05（迁移 no_127_20260905_add_mimo_models）
> 接入模式：**Token Plan 套餐**（包月买断 credits），区别于此前的按量计费 API

## 1. 供应商与端点

| 项目 | 值 |
|---|---|
| vendor_name | `mimo` |
| 协议 | OpenAI 兼容（项目统一走此协议，未使用 Anthropic 兼容端点） |
| Base URL | `https://token-plan-cn.xiaomimimo.com/v1`（`llm.mimo.base_url` 可覆盖） |
| API Key 配置键 | `llm.mimo.api_key`（热更新 + 快速配置弹窗） |
| 客户端 | `llm/openai_mimo.py` → `MimoOpenAIClient`（继承 `OpenAIBaseClient`） |
| 前缀路由 | `mimo` → `LLMVendor.MIMO`（`MODEL_PREFIX_VENDOR_MAP`） |

**Token Plan 与按量 API 的关系**：两者调用协议完全一致，差异仅在采购侧——
Token Plan 为包月套餐（月费买断 credits 额度），按量 API 为按 token 计费。
因此接入上只是新增一个供应商；**终端用户照常按量扣算力**，套餐成本作为
运营侧摊销，不改变计费链路。

## 2. 模型规格

| | mimo-v2.5 | mimo-v2.5-pro |
|---|---|---|
| 上下文窗口 | 1,000,000 | 1,000,000 |
| 最大输出 | 128,000 | 128,000 |
| 工具调用 / 思考 / 视觉 | 1 / 1 / 1 | 1 / 1 / **0**（Pro 为纯文本模型，官方页标明输入/输出模态均为文本；no_127 误标视觉=1，no_132_20260909_fix_mimo_v25_pro_vl_flag 已修正并清理指向它的 VL 偏好） |
| 思考参数格式 | `extra_body={"thinking": {"type": "enabled"/"disabled"}}`（与 DeepSeek 客户端同款） | 同左 |
| 限速 | RPM 100 / TPM 10M | RPM 100 / TPM 10M |

## 3. 计费档位（按官方按量价折算）

公式：`threshold = 0.04 × 10^6 / 单价(元/百万token)`（1 点算力 = 0.04 元），
normal 时段、不分段（`raw_token_threshold = NULL`）。

| 模型 | input（未命中） | out | cache_read（命中） |
|---|---|---|---|
| mimo-v2.5 | 40000（¥1/百万） | 20000（¥2/百万） | 2000000（¥0.02/百万） |
| mimo-v2.5-pro | 13333（¥3/百万） | 6667（¥6/百万） | 1600000（¥0.025/百万） |

代码默认档位目录同步维护于 `config/default_vendor_model_billing.py`（管理后台
「还原默认档位」使用）。套餐成本结构变化时直接调整 vendor_model 档位即可，无需改代码。

## 4. 改动文件清单

- `config/constant.py`：`LLMVendor.MIMO`、`LLMModel.MIMO_V2_5 / MIMO_V2_5_PRO`、
  `MODEL_PREFIX_VENDOR_MAP['mimo']`、`VENDOR_ICONS['mimo']`
- `llm/openai_mimo.py`：新增客户端（单例 `get_mimo_openai_client`）
- `llm/llm_client_factory.py`：`_VENDOR_CLIENT_MAP` + `vendor_config_map` 两处注册
- `alembic/versions/no_127_20260905_add_mimo_models.py`：vendor + model + vendor_model 计费档位
- `alembic/versions/no_132_20260909_fix_mimo_v25_pro_vl_flag.py`：修正 mimo-v2.5-pro
  `supports_vl` 误标（1→0）与 note，并删除 `user_preferences` 中指向它的 `vl_model` 偏好
- `config.example.yml` / `config_prod.base.yaml` / `config_dev.base.yml`：`llm.mimo` 配置段
  （dev.base 为本地开发兜底默认值，完整模板见 example，按项目约定三处同步维护）
- `config/default_configs.py`：`llm.mimo.api_key` / `llm.mimo.base_url` 热更新项
- `config/default_vendor_model_billing.py`：默认计费档位目录
- `web/js/admin.js`：`PROVIDER_DEFINITIONS` 新增 mimo 卡片（管理后台「大模型」分类，displayOrder 8）
- `web/i18n/locales/zh-CN/admin.json`、`web/i18n/locales/en/admin.json`：mimo 供应商名称/描述/场景/placeholder 文案
  （⚠️ 管理后台的供应商卡片为前端硬编码，新增供应商必须同步此处，否则后台看不到）

## 5. 验证步骤

1. `alembic upgrade head`（迁移后确认单 head：`python scripts/lint_migration_names.py`）
2. 管理后台快速配置弹窗填入 `llm.mimo.api_key`
3. 「可用模型列表」出现 mimo-v2.5 / mimo-v2.5-pro（`get_available_models` 按 vendor_model 过滤）
4. 小请求实测：基础对话、工具调用、thinking 开关（若小米 enabled 格式与文档有出入，
   只需调整 `llm/openai_mimo.py` 的 `_apply_thinking_params` 一处）
5. 调用后确认 `token_log` 落库、`task/token_task` 轮询按档位扣算力
