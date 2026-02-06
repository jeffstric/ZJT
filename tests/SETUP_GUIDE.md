# 数据库单元测试框架 - 快速开始指南

## 已完成的工作

✅ 测试数据库配置模块 (`tests/db_test_config.py`)
✅ 数据库测试基类 (`tests/base_db_test.py`)
✅ 示例测试用例 (`tests/test_character_db.py`, `tests/test_simple_db.py`)
✅ pytest 配置 (`tests/conftest.py`)
✅ SQL 执行逻辑修复（正确处理注释行）
✅ props.sql 文件修复（添加 IF NOT EXISTS）

## 配置说明

### 1. 数据库配置

测试数据库配置已添加到 `config.yml`：

```yaml
test_database:
  host: "192.168.10.212"
  port: 3306
  user: "unittest_user"
  password: "o33RLd4GKXsz"
  database: "voice_replace_unittest"
  charset: "utf8mb4"
```

### 2. 运行测试

#### 方式一：使用 unittest

```bash
# 激活 conda 环境
source /home/appuser/miniconda3/etc/profile.d/conda.sh
conda activate comfyui_server

# 运行所有测试
python3 -m unittest discover tests -p "test_*_db.py" -v

# 运行单个测试文件
python3 -m unittest tests.test_simple_db -v
python3 -m unittest tests.test_character_db -v

# 运行单个测试方法
python3 -m unittest tests.test_simple_db.TestSimpleDatabase.test_insert_world -v
```

#### 方式二：使用测试脚本

```bash
chmod +x run_tests.sh
./run_tests.sh
```

#### 方式三：使用 pytest

```bash
pytest tests/test_simple_db.py -v
pytest tests/test_character_db.py -v
```

### 3. 测试数据库初始化

测试框架会自动：
1. 连接到 `voice_replace_unittest` 数据库
2. 按依赖顺序执行 SQL 文件创建表结构
3. 每个测试在独立事务中运行
4. 测试结束后自动回滚，保持数据库干净

数据库表结构会在首次运行测试时自动初始化。

## 测试框架特性

### 事务隔离
每个测试用例在独立事务中运行，测试结束后自动回滚，确保：
- 测试之间互不干扰
- 数据库始终保持干净状态
- 可以并发运行测试

### 自动建表
测试类初始化时自动执行建表 SQL，按以下顺序：
1. world.sql
2. character.sql
3. location.sql
4. props.sql
5. script.sql
6. video_workflow.sql
7. ai_tools.sql
8. runninghub_slots.sql

### 辅助方法

```python
# 插入测试数据
world_id = self.insert_fixture('world', {
    'name': '测试世界',
    'user_id': 1
})

# 执行查询
results = self.execute_query("SELECT * FROM world WHERE id = %s", (world_id,))

# 执行更新
affected = self.execute_update("UPDATE world SET name = %s WHERE id = %s", ('新名字', world_id))

# 统计行数
count = self.count_rows('world', 'user_id = %s', (1,))

# 清空表
self.clear_table('world')
```

## 编写新测试

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
    
    def test_something(self):
        """测试某个功能"""
        # 测试代码
        result = self.execute_query("SELECT * FROM world WHERE id = %s", (self.test_world_id,))
        self.assertEqual(len(result), 1)
```

## 故障排查

### 连接失败
检查数据库配置和网络连接：
```bash
mysql -h 192.168.10.212 -u unittest_user -p voice_replace_unittest
```

### 表已存在错误
已修复 `props.sql`，所有表创建语句都使用 `CREATE TABLE IF NOT EXISTS`

### SQL 执行失败
检查 SQL 文件语法，确保没有语法错误

## 文件结构

```
tests/
├── __init__.py                    # 模块初始化
├── db_test_config.py              # 数据库配置
├── base_db_test.py                # 测试基类
├── conftest.py                    # pytest 配置
├── test_simple_db.py              # 简单测试示例
├── test_character_db.py           # 角色表测试示例
├── README_database_tests.md       # 详细文档
└── SETUP_GUIDE.md                 # 本文件
```

## 下一步

1. 确保测试数据库 `voice_replace_unittest` 已创建
2. 运行 `./run_tests.sh` 验证框架是否正常工作
3. 根据需要编写更多测试用例

## 注意事项

- 测试数据库名称必须包含 `_test` 或 `_unittest` 后缀（安全检查）
- 每个测试结束后会自动回滚，无需手动清理数据
- 使用 `super().setUp()` 确保正确初始化数据库连接
- 避免在测试中使用 `commit()`，这会破坏事务隔离
