# 数据库单元测试使用指南

## 概述

本测试框架提供基于真实数据库的单元测试能力，支持自动建表、事务隔离和测试数据管理。

## 特性

- **自动建表**：测试启动时自动执行 SQL 文件创建表结构
- **事务隔离**：每个测试在独立事务中运行，测试后自动回滚
- **环境隔离**：强制使用测试数据库，防止误操作生产库
- **依赖处理**：按正确顺序加载 SQL 文件（先父表后子表）

## 准备工作

### 1. 创建测试数据库

```sql
CREATE DATABASE comfyui_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON comfyui_test.* TO 'your_user'@'localhost';
```

### 2. 配置环境变量（可选）

```bash
export TEST_DB_HOST=localhost
export TEST_DB_PORT=3306
export TEST_DB_USER=root
export TEST_DB_PASSWORD=your_password
export TEST_DB_NAME=comfyui_test
```

如果不设置环境变量，将使用 `config.yml` 中的配置，数据库名称自动添加 `_test` 后缀。

## 运行测试

### 使用 unittest

```bash
# 运行所有数据库测试
python -m unittest discover tests -p "test_*_db.py"

# 运行单个测试文件
python -m unittest tests.test_character_db

# 运行单个测试类
python -m unittest tests.test_character_db.TestCharacterDatabase

# 运行单个测试方法
python -m unittest tests.test_character_db.TestCharacterDatabase.test_insert_character
```

### 使用 pytest

```bash
# 运行所有测试
pytest tests/

# 运行数据库测试
pytest tests/test_character_db.py

# 运行单个测试
pytest tests/test_character_db.py::TestCharacterDatabase::test_insert_character

# 显示详细输出
pytest tests/ -v

# 显示打印信息
pytest tests/ -s
```

## 编写测试用例

### 基本示例

```python
from tests.base_db_test import DatabaseTestCase

class TestMyModel(DatabaseTestCase):
    """我的模型测试"""
    
    def setUp(self):
        """每个测试前的准备"""
        super().setUp()
        
        # 插入测试数据
        self.test_world_id = self.insert_fixture('world', {
            'name': '测试世界',
            'user_id': 1
        })
    
    def test_create_record(self):
        """测试创建记录"""
        # 插入数据
        record_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '测试角色',
            'user_id': 1
        })
        
        # 验证插入成功
        self.assertIsNotNone(record_id)
        
        # 查询验证
        result = self.execute_query(
            "SELECT * FROM `character` WHERE id = %s",
            (record_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], '测试角色')
```

### 可用的辅助方法

#### `execute_query(sql, params=None)`
执行查询语句，返回结果列表。

```python
results = self.execute_query(
    "SELECT * FROM `character` WHERE world_id = %s",
    (world_id,)
)
```

#### `execute_update(sql, params=None)`
执行更新语句（INSERT/UPDATE/DELETE），返回影响的行数。

```python
affected_rows = self.execute_update(
    "UPDATE `character` SET name = %s WHERE id = %s",
    ('新名字', character_id)
)
```

#### `execute_insert(sql, params=None)`
执行插入语句，返回插入的 ID。

```python
new_id = self.execute_insert(
    "INSERT INTO `character` (name, world_id, user_id) VALUES (%s, %s, %s)",
    ('角色名', world_id, user_id)
)
```

#### `insert_fixture(table, data)`
快速插入测试数据，返回插入的 ID。

```python
character_id = self.insert_fixture('character', {
    'name': '张三',
    'world_id': 1,
    'user_id': 1
})
```

#### `clear_table(table)`
清空表数据。

```python
self.clear_table('character')
```

#### `count_rows(table, where=None, params=None)`
统计表行数。

```python
count = self.count_rows('character', 'world_id = %s', (world_id,))
```

## 注意事项

1. **数据库名称检查**：测试数据库名称必须以 `_test` 结尾，否则测试会失败
2. **事务隔离**：每个测试结束后会自动回滚，无需手动清理数据
3. **外键约束**：测试框架会按正确顺序创建表，避免外键约束问题
4. **并发测试**：由于使用事务隔离，测试可以并发运行

## 故障排查

### 连接失败

检查数据库配置和权限：

```bash
mysql -h localhost -u root -p -e "SHOW DATABASES LIKE '%test%';"
```

### 表不存在

确保 SQL 文件存在于 `model/sql/` 目录：

```bash
ls -la model/sql/*.sql
```

### 外键约束错误

检查 `base_db_test.py` 中的表创建顺序是否正确。

## 示例测试用例

参考 `tests/test_character_db.py` 查看完整的测试示例。
