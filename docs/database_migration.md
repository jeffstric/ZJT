# 数据库迁移指南

本项目使用 Alembic 进行数据库迁移管理。

## 目录结构

```
alembic/
├── env.py               # 环境配置（读取 config_{env}.yml）
├── script.py.mako       # 迁移脚本模板
└── versions/            # 迁移脚本目录
alembic.ini              # Alembic 主配置
model/
├── migration.py         # 迁移执行模块
└── sql/
    └── baseline.sql     # 基准 SQL（用于初始化新数据库）
```

## 配置

在 `config_{env}.yml` 中配置：

```yaml
alembic:
  auto_migrate: true      # 应用启动时是否自动执行迁移
  script_location: "alembic"  # 迁移脚本目录
```

## 常用命令

```bash
# 查看迁移历史
alembic history

# 查看当前版本
alembic current

# 升级到最新版本
alembic upgrade head

# 回滚一个版本
alembic downgrade -1

# 创建新迁移
alembic revision -m "描述信息"

# 标记数据库为最新版本（不执行迁移）
alembic stamp head
```

## 创建新迁移

1. 创建迁移脚本：
   ```bash
   alembic revision -m "add_new_column"
   ```

2. 编辑生成的脚本文件，在 `upgrade()` 和 `downgrade()` 中添加 SQL：
   ```python
   def upgrade() -> None:
       op.execute("ALTER TABLE xxx ADD COLUMN yyy VARCHAR(255)")
   
   def downgrade() -> None:
       op.execute("ALTER TABLE xxx DROP COLUMN yyy")
   ```

3. 执行迁移：
   ```bash
   alembic upgrade head
   ```

## 初始化新数据库

1. 使用 `model/sql/baseline.sql` 创建所有表
2. 执行 `alembic stamp head` 将数据库标记为最新版本

## 自动迁移

当 `config.alembic.auto_migrate = true` 时，应用启动会自动执行 `alembic upgrade head`。

## 数据库权限要求

Alembic 需要以下权限：
- `CREATE TABLE` - 创建 `alembic_version` 版本追踪表
- `ALTER TABLE` - 执行表结构变更
- `DROP TABLE` - 执行回滚操作（可选）
- `INSERT/UPDATE/DELETE` - 更新版本信息

## 注意事项

1. **生产环境建议**：关闭 `auto_migrate`，手动执行迁移
2. **多实例部署**：确保只有一个实例执行迁移，避免并发冲突
3. **备份**：执行迁移前务必备份数据库
