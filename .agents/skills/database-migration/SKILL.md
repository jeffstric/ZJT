---
name: database-migration
description: 数据库迁移专家，指导如何在本项目中创建 Alembic 迁移脚本，以及同步修改 model 目录下的模型定义。当需要新建表、修改表结构、添加/修改字段时使用。
allowed-tools: Read, Write, Terminal
---

# 数据库迁移专家

## 角色定位

你是一位数据库迁移专家，负责指导和执行本项目的数据库结构变更。本项目使用 **Alembic** 进行数据库迁移管理。

## 项目结构

```
项目根目录/
├── alembic/
│   └── versions/          # 迁移脚本目录
│       ├── 20260421_xxx.py
│       └── ...
├── model/                 # SQLAlchemy 模型定义
│   ├── __init__.py
│   ├── users.py
│   ├── ai_audio.py
│   └── ...
└── alembic.ini            # Alembic 配置文件
```

## 迁移脚本创建流程

### 第一步：确定迁移类型

询问或分析需求，确定迁移类型：
1. **新建表** - 创建全新的数据库表
2. **修改表结构** - 添加/删除/修改字段、索引、约束
3. **数据迁移** - 插入/更新/删除数据记录
4. **混合操作** - 以上多种操作的组合

### 第二步：创建迁移脚本

**文件命名规范**：`YYYYMMDD_简短描述.py`

示例：
- `20260421_add_claude_haiku.py`
- `20260228_create_sys_config.py`
- `20260325_add_user_avatar.py`

**⚠️ 重要**：`revision` ID **必须 ≤ 32 字符**（数据库 `alembic_version.version_num` 为 `varchar(32)`）

**文件位置**：`alembic/versions/` 目录下

### 第三步：编写迁移脚本

#### 脚本模板

```python
"""简要描述本次迁移内容

Revision ID: YYYYMMDD_short_id  (必须 ≤ 32 字符!)
Revises: 上一个迁移的revision_id
Create Date: YYYY-MM-DD
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = 'YYYYMMDD_short_id'
down_revision: Union[str, None] = '上一个revision'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库：描述具体操作"""
    conn = op.get_bind()
    
    # 执行迁移操作
    conn.execute(text("""
        -- SQL语句
    """))
    logger.info("[Migration] 操作描述")


def downgrade() -> None:
    """回滚数据库：描述回滚操作"""
    conn = op.get_bind()
    
    # 执行回滚操作
    conn.execute(text("""
        -- 回滚SQL语句
    """))
    logger.info("[Migration] 回滚描述")
```

#### 常见操作示例

**1. 创建新表**

```python
def upgrade() -> None:
    op.execute("""
        CREATE TABLE `table_name` (
            `id` INT PRIMARY KEY AUTO_INCREMENT,
            `name` VARCHAR(256) NOT NULL COMMENT '名称',
            `status` TINYINT DEFAULT 0 COMMENT '状态',
            `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
            `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX `idx_name` (`name`),
            UNIQUE KEY `uk_name` (`name`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='表注释'
    """)

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `table_name`")
```

**2. 添加字段**

```python
def upgrade() -> None:
    op.execute("""
        ALTER TABLE `table_name` 
        ADD COLUMN `new_field` VARCHAR(256) DEFAULT NULL COMMENT '新字段' 
        AFTER `existing_field`
    """)

def downgrade() -> None:
    op.execute("ALTER TABLE `table_name` DROP COLUMN `new_field`")
```

**3. 插入数据（带幂等性）**

```python
def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        INSERT INTO `table_name` (field1, field2)
        VALUES ('value1', 'value2')
        ON DUPLICATE KEY UPDATE field1 = VALUES(field1)
    """))
    logger.info("[Migration] Inserted record")

def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        DELETE FROM `table_name` WHERE field1 = 'value1'
    """))
```

**4. 添加索引**

```python
def upgrade() -> None:
    op.execute("CREATE INDEX `idx_field_name` ON `table_name` (`field_name`)")

def downgrade() -> None:
    op.execute("DROP INDEX `idx_field_name` ON `table_name`")
```

### 第四步：同步修改 Model 文件（重要！）

**如果涉及表结构变更，必须同步修改 `model/` 目录下对应的模型文件！**

#### Model 文件位置

- 查看 `model/` 目录，找到对应的模型文件
- 如果是新表，需要新建模型文件

#### Model 文件示例

```python
# model/example_model.py
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func
from model import Base

class ExampleModel(Base):
    __tablename__ = 'example_table'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False, comment='名称')
    description = Column(Text, comment='描述')
    status = Column(Integer, default=0, comment='状态')
    is_active = Column(Boolean, default=True, comment='是否激活')
    created_at = Column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'status': self.status,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
```

#### 新建 Model 后，需要在 `model/__init__.py` 中导入

```python
from model.example_model import ExampleModel
```

### 第五步：获取上一个迁移的 revision_id

在创建迁移脚本前，需要查看 `alembic/versions/` 目录下最新的迁移脚本，获取其 `revision` 值作为新脚本的 `down_revision`。

**查看方法**：
```bash
ls -lt alembic/versions/ | head -5
```

然后读取最新文件中的 `revision` 值。

### 第六步：执行迁移

迁移脚本创建完成后，告知用户执行以下命令：

```bash
# 查看当前迁移状态
alembic current

# 执行迁移到最新版本
alembic upgrade head

# 回滚一个版本（如需要）
alembic downgrade -1
```

## 重要注意事项

### 1. 幂等性原则
- 使用 `ON DUPLICATE KEY UPDATE` 或 `INSERT IGNORE` 确保数据插入的幂等性
- 使用 `IF NOT EXISTS` / `IF EXISTS` 确保表/索引操作的幂等性

### 2. 回滚能力
- **每个 upgrade 都必须有对应的 downgrade**
- downgrade 应该能完全回滚 upgrade 的操作

### 3. 日志记录
- 使用 `logger.info("[Migration] 描述")` 记录关键操作
- 便于追踪迁移执行情况

### 4. 字符集
- 表和字段统一使用 `utf8mb4` 字符集
- COLLATE 使用 `utf8mb4_unicode_ci`

### 5. Model 同步
- **表结构变更后，必须同步更新 model 文件**
- 确保 SQLAlchemy 模型与数据库表结构一致

### 6. 跨平台兼容
- 本系统需兼容 Windows/Linux/macOS
- 避免使用平台特定的 SQL 语法

## 检查清单

在完成迁移脚本后，确认以下事项：

- [ ] 迁移脚本文件名符合规范 `YYYYMMDD_描述.py`
- [ ] `revision` 和 `down_revision` 正确设置
- [ ] `upgrade()` 函数实现完整
- [ ] `downgrade()` 函数能完全回滚
- [ ] 如涉及表结构变更，已同步修改 `model/` 下的模型文件
- [ ] 如新建模型，已在 `model/__init__.py` 中导入
- [ ] 使用了适当的日志记录
- [ ] SQL 语句具有幂等性

## 常见问题

### Q: 如何处理已存在的表/字段？
A: 使用条件判断或 `ON DUPLICATE KEY UPDATE`

### Q: down_revision 应该填什么？
A: 查看 `alembic/versions/` 目录，找到时间最新的迁移脚本，使用其 `revision` 值

### Q: 迁移失败如何处理？
A: 
1. 查看错误信息
2. 手动修复数据库状态
3. 修改迁移脚本
4. 重新执行迁移
