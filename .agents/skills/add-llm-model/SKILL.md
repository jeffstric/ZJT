---
name: add-llm-model
description: 新增 LLM 模型专家，指导如何在本项目中添加新的 LLM 供应商和模型。当需要接入新的大语言模型（如 OpenAI、Codex、DeepSeek 等）时使用。
allowed-tools: Read, Write, Terminal
---

# 新增 LLM 模型专家

## 角色定位

你是一位 LLM 集成专家，负责在本项目中添加新的大语言模型供应商和模型。

## 项目结构

```
项目根目录/
├── llm/                           # LLM 客户端目录
│   ├── openai_base_client.py      # OpenAI 兼容格式基类
│   ├── llm_client_factory.py      # 客户端工厂（路由）
│   ├── openai_deepseek.py         # DeepSeek 客户端示例
│   └── ...
├── config/
│   └── constant.py                # 常量定义（LLMVendor, LLMModel）
└── alembic/versions/              # 数据库迁移脚本
```

## 新增 LLM 模型完整流程

### 第一步：检查常量是否已存在

**先检查 `config/constant.py`**，确认供应商和模型常量是否已存在：

1. 检查 `LLMVendor` 类中是否已有该供应商
2. 检查 `LLMModel` 类中是否已有该模型
3. 检查 `MODEL_PREFIX_VENDOR_MAP` 是否已有映射

**判断逻辑**：
- ✅ **常量已存在** → 说明供应商客户端可能已存在，检查 `llm/` 目录下是否有对应文件，如有则复用
- ❌ **常量不存在** → 需要新建客户端文件，继续第二步

**添加常量**（如不存在）：

修改 `config/constant.py`，添加供应商和模型常量。

**1. 添加供应商常量**（`LLMVendor` 类）：

```python
class LLMVendor:
    # ... 已有供应商
    {VENDOR} = '{vendor}'  # {Vendor} 供应商（{Model} 模型）
```

**2. 添加模型常量**（`LLMModel` 类）：

```python
class LLMModel:
    # ... 已有模型
    # {Vendor} 模型
    {MODEL_CONST} = '{model-name}'
```

**3. 添加前缀映射**（`MODEL_PREFIX_VENDOR_MAP`）：

```python
MODEL_PREFIX_VENDOR_MAP = {
    # ... 已有映射
    '{model-prefix}': LLMVendor.{VENDOR},
}
```

### 第二步：新建客户端文件（如不存在）

**先检查 `llm/` 目录下是否已有对应供应商的客户端文件**：
- 如果已存在（如 `openai_{vendor}.py`），可复用，跳过本步
- 如果不存在，则新建客户端文件

**文件命名**：`openai_{vendor}.py`（如 `openai_deepseek.py`）

**模板代码**：

```python
"""
{Vendor} OpenAI 兼容格式 LLM 客户端
支持 {model-list} 系列模型
"""
import logging
from .openai_base_client import OpenAIBaseClient
from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)


class {Vendor}OpenAIClient(OpenAIBaseClient):
    """{Vendor} OpenAI 兼容格式 LLM 客户端"""

    # model 表友好名称 -> 实际 API endpoint model ID 映射
    _MODEL_NAME_MAP = {
        'model-name-in-db': 'actual-api-model-id',
        # 可添加更多映射
    }

    def _refresh_config(self):
        """刷新配置"""
        self.api_key = get_dynamic_config_value('llm', '{vendor}', 'api_key', default='')
        self.base_url = get_dynamic_config_value(
            'llm', '{vendor}', 'base_url',
            default='https://api.{vendor}.com'
        )
        self.vendor_name = '{vendor}'
        # 如果支持思考模式，设置 thinking_mode
        # self.thinking_mode = 'enable_thinking'

        if self.api_key:
            logger.info(f"{Vendor}OpenAIClient config loaded: base_url={self.base_url}")
        else:
            logger.warning("{Vendor}OpenAIClient: API Key 未配置")

    def _resolve_model_name(self, model: str) -> str:
        """将 model 表中的友好名称映射为实际 API model ID"""
        actual = self._MODEL_NAME_MAP.get(model, model)
        if actual != model:
            logger.debug(f"{Vendor}OpenAIClient model mapping: {model} -> {actual}")
        return actual


_{vendor}_client = None


def get_{vendor}_openai_client() -> {Vendor}OpenAIClient:
    """获取客户端单例"""
    global _{vendor}_client
    if _{vendor}_client is None:
        _{vendor}_client = {Vendor}OpenAIClient()
    else:
        _{vendor}_client._refresh_config()
    return _{vendor}_client
```

### 第三步：注册到工厂

修改 `llm/llm_client_factory.py`：

**1. 添加导入**：

```python
from .openai_{vendor} import {Vendor}OpenAIClient, get_{vendor}_openai_client
```

**2. 注册到 `_VENDOR_CLIENT_MAP`**：

```python
class LLMClientFactory:
    _VENDOR_CLIENT_MAP = {
        # ... 已有供应商
        LLMVendor.{VENDOR}: get_{vendor}_openai_client,
    }
```

**3. 添加配置检查**（`get_available_models` 函数内的 `vendor_config_map`）：

```python
vendor_config_map = {
    # ... 已有配置
    '{vendor}': ('llm', '{vendor}', 'api_key'),
}
```

### 第四步：创建数据库迁移脚本

**注意**：`model/vendor.py` 是数据库 vendor 表的 DAO 类，无需修改。供应商数据通过迁移脚本插入到数据库中。

在 `alembic/versions/` 目录下创建迁移脚本，添加供应商、模型和计费配置。

**文件命名**：`YYYYMMDD_add_{vendor}_models.py`

**迁移脚本模板**：

```python
"""Add {Vendor} vendor and models

Revision ID: YYYYMMDD_add_{vendor}
Revises: {上一个revision}
Create Date: YYYY-MM-DD
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

revision: str = 'YYYYMMDD_add_{vendor}'
down_revision: Union[str, None] = '{上一个revision}'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add {vendor} vendor, models, and billing config"""
    conn = op.get_bind()

    # 1. 添加供应商
    conn.execute(text("""
        INSERT INTO vendor (vendor_name, created_at, note)
        VALUES ('{vendor}', NOW(), '{Vendor} API')
        ON DUPLICATE KEY UPDATE vendor_name = VALUES(vendor_name)
    """))
    logger.info("[Migration] Inserted {vendor} vendor")

    # 2. 添加模型
    conn.execute(text("""
        INSERT INTO `model` (model_name, context_window, supports_tools, max_output_tokens, supports_thinking, created_at, note)
        VALUES ('{model-name}', {context_window}, {supports_tools}, {max_output_tokens}, {supports_thinking}, NOW(), '{note}')
        ON DUPLICATE KEY UPDATE model_name = VALUES(model_name)
    """))
    logger.info("[Migration] Inserted {model-name} model")

    # 3. 添加计费配置 (vendor_model)
    # threshold = 0.04 × 10^6 / 单价(元/百万token)
    # 1点算力 = 0.04元
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), {input_threshold}, {output_threshold}, {cache_threshold}, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = '{vendor}' AND m.model_name = '{model-name}'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Added {model-name} billing config")


def downgrade() -> None:
    """Revert: Remove vendor_model, models, and vendor"""
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联
    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE vendor_id = (SELECT id FROM vendor WHERE vendor_name = '{vendor}')
        AND model_id IN (SELECT id FROM `model` WHERE model_name IN ('{model-name}'))
    """))
    logger.info("[Migration] Deleted vendor_model records")

    # 2. 删除 model
    conn.execute(text("""
        DELETE FROM `model` WHERE model_name IN ('{model-name}')
    """))
    logger.info("[Migration] Deleted models")

    # 3. 删除 vendor
    conn.execute(text("""
        DELETE FROM vendor WHERE vendor_name = '{vendor}'
    """))
    logger.info("[Migration] Deleted vendor")
```

### 第五步：配置文件与热更新

新增供应商后，必须在配置文件和热更新定义中添加对应条目，否则管理后台无法配置该供应商。

**1. `config.example.yml` 和 `config_prod.base.yaml`** — 在 `llm` 节点下新增供应商配置段（两个文件格式一致）：

```yaml
llm:
  # ... 已有供应商
  {vendor}:
    api_key: ""                    # 必填，空字符串表示未配置
    base_url: "https://api.{vendor}.com"  # 可选，有默认值时填写
```

**2. `config/default_configs.py`** — 在 `DEFAULT_CONFIGS` 列表中添加热更新配置项：

```python
# ==================== {Vendor} 配置 ====================
{
    'key': 'llm.{vendor}.api_key',
    'value_type': 'string',
    'description': '{Vendor} API Key',
    'editable': True,
    'is_sensitive': True,
    'quick_config': True
},
{
    'key': 'llm.{vendor}.base_url',
    'value_type': 'string',
    'description': '{Vendor} API 基础URL（默认 https://api.{vendor}.com）',
    'editable': True,
    'is_sensitive': False,
    'quick_config': True
},
```

> **注意**：`quick_config: True` 使配置项出现在管理后台的快速配置弹窗中，方便用户快速填入 API Key。

## 计费阈值计算公式

**核心公式**：`threshold = 0.04 × 10^6 / 单价(元/百万token)`

- 1 点算力 = 0.04 元
- threshold 表示消耗 1 点算力可处理的 token 数量

**示例**（DeepSeek V4 Flash）：
- 输入 1 元/百万 → `threshold = 0.04 × 10^6 / 1 = 40000`
- 输出 2 元/百万 → `threshold = 0.04 × 10^6 / 2 = 20000`
- 缓存 0.02 元/百万 → `threshold = 0.04 × 10^6 / 0.02 = 2000000`

## 配置文件

新增供应商需要在配置文件中添加对应配置项：

```yaml
llm:
  {vendor}:
    api_key: "your-api-key"
    base_url: "https://api.{vendor}.com"  # 可选，有默认值
```

## 检查清单

完成新增 LLM 模型后，按顺序确认以下事项：

**第一步：常量检查与添加**
- [ ] `config/constant.py` - 已检查/添加 `LLMVendor.{VENDOR}` 常量
- [ ] `config/constant.py` - 已检查/添加 `LLMModel.{MODEL}` 常量
- [ ] `config/constant.py` - 已检查/添加 `MODEL_PREFIX_VENDOR_MAP` 映射

**第二步：客户端文件**
- [ ] `llm/openai_{vendor}.py` - 已检查是否存在，如不存在则创建

**第三步：工厂注册**
- [ ] `llm/llm_client_factory.py` - 已导入新客户端
- [ ] `llm/llm_client_factory.py` - 已注册到 `_VENDOR_CLIENT_MAP`
- [ ] `llm/llm_client_factory.py` - 已添加配置检查

**第四步：数据库迁移**
- [ ] `alembic/versions/` - 已创建迁移脚本（vendor + model + vendor_model 计费）
- [ ] 计费阈值计算正确
- [ ] 迁移脚本 revision ≤ 32 字符

**第五步：配置文件与热更新**
- [ ] `config.example.yml` - 已在 `llm` 节点下新增 `{vendor}` 配置段（api_key + base_url）
- [ ] `config_prod.base.yaml` - 已在 `llm` 节点下新增 `{vendor}` 配置段（与 config.example.yml 一致）
- [ ] `config/default_configs.py` - 已在 `DEFAULT_CONFIGS` 中新增 `llm.{vendor}.api_key` 和 `llm.{vendor}.base_url` 热更新项

## 常见问题

### Q: 如何确定 model 表的字段值？
A: 参考模型官方文档：
- `context_window`: 上下文窗口大小（token 数）
- `max_output_tokens`: 最大输出 token 数
- `supports_tools`: 是否支持函数调用（1/0）
- `supports_thinking`: 是否支持思考模式（1/0）

### Q: 模型名称映射什么时候需要？
A: 当数据库存储的友好名称与 API 实际 model ID 不同时需要映射。

### Q: 如何测试新增的模型？
A: 
1. 执行数据库迁移：`alembic upgrade head`
2. 配置 API Key
3. 调用接口测试
