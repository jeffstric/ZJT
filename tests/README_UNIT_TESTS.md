# 单元测试详细设计方案

基于项目现有架构的完整单元测试实现方案，包含配置、SQL建表、CRUD测试、驱动Mock测试及数据库验证的详细实现。

## 当前测试架构现状

```
tests/
├── db_test_config.py              # 已存在 - 测试数据库配置
├── base_db_test.py                # 已存在 - 数据库测试基类
├── base_visual_driver_test.py      # 已存在 - 视觉驱动测试基类
├── test_db_connection.py          # 已存在 - 连接测试
├── test_*_crud.py                 # 已存在 - 11个表的CRUD测试
│   ├── test_ai_tools_crud.py
│   ├── test_ai_audio_crud.py
│   ├── test_character_crud.py
│   ├── test_location_crud.py
│   ├── test_payment_orders_crud.py
│   ├── test_props_crud.py
│   ├── test_runninghub_slots_crud.py
│   ├── test_script_crud.py
│   ├── test_tasks_crud.py
│   ├── test_visual_workflow_crud.py
│   └── test_world_crud.py
├── driver_integration/            # 驱动集成测试目录
│   ├── test_digital_human_driver_with_db.py   # 已存在
│   ├── test_gemini_driver_with_db.py
│   ├── test_kling_driver_with_db.py
│   ├── test_ltx2_driver_with_db.py
│   ├── test_sora2_driver_with_db.py
│   ├── test_veo3_driver_with_db.py
│   ├── test_vidu_driver_with_db.py
│   └── test_wan22_driver_with_db.py
├── README_database_tests.md       # 已存在 - 使用文档
├── SETUP_GUIDE.md                 # 已存在 - 环境搭建
└── VISUAL_DRIVER_TESTS.md          # 已存在 - 驱动测试文档
```

## 1. 测试配置文件 (config_unit.yml)

### 1.1 独立配置文件设计

**新建文件**: `config_unit.yml`（测试专用配置，与生产配置完全隔离）

```yaml
# config_unit.yml - 单元测试专用配置文件
# 此文件独立于 config.yml，确保测试与生产环境完全隔离

# 测试数据库配置（强制使用独立测试库）
database:
  host: "192.168.10.212"
  port: 3306
  user: "unittest_user"
  password: "o33RLd4GKXsz"
  database: "voice_replace_unittest"  # 必须以 _test 或 _unittest 结尾
  charset: "utf8mb4"

# 测试服务配置
server:
  host: "http://localhost:9000"
  port: 9000

# 测试超时设置（可缩短以加快测试）
timeout:
  request_timeout: 5000
  status_check_timeout: 60
  status_check_interval: 2

# 测试日志级别
logging:
  level: "DEBUG"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# 测试标记
unit_test:
  enabled: true
  cleanup_after_test: true  # 测试后是否清理数据
  mock_external_apis: true  # 是否Mock所有外部API
```

### 1.2 配置加载逻辑更新

**修改文件**: `tests/db_test_config.py`

```python
"""
测试数据库配置模块 - 支持独立 config_unit.yml 配置文件
"""
import os
import sys
import yaml
import logging

logger = logging.getLogger(__name__)
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)


def get_unit_test_config_path():
    """
    获取单元测试配置文件路径
    
    优先级：
    1. 环境变量 UNIT_TEST_CONFIG
    2. 默认 config_unit.yml
    
    Returns:
        str: 配置文件路径
    """
    return os.environ.get('UNIT_TEST_CONFIG', 'config_unit.yml')


def get_test_db_config():
    """
    获取测试数据库配置
    
    配置优先级：
    1. 环境变量 (TEST_DB_HOST, TEST_DB_PORT, TEST_DB_USER, TEST_DB_PASSWORD, TEST_DB_NAME)
    2. config_unit.yml 中的 database 配置节
    3. 默认值
    
    安全机制：
    - 数据库名必须以 _test 或 _unittest 结尾
    - 配置文件必须存在
    
    Returns:
        dict: 数据库配置字典
    """
    config_file = os.path.join(APP_DIR, get_unit_test_config_path())
    db_config = {}
    
    # 1. 加载 config_unit.yml
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                if config and 'database' in config:
                    db_config = config['database'].copy()
                    logger.info(f"使用 {get_unit_test_config_path()} 中的 database 配置")
        except Exception as e:
            logger.error(f"加载测试配置文件失败: {e}")
            raise RuntimeError(f"无法加载测试配置文件: {config_file}")
    else:
        logger.warning(f"测试配置文件不存在: {config_file}，使用环境变量或默认值")
    
    # 2. 环境变量覆盖（优先级最高）
    db_config['host'] = os.environ.get('TEST_DB_HOST', db_config.get('host', 'localhost'))
    db_config['port'] = int(os.environ.get('TEST_DB_PORT', db_config.get('port', 3306)))
    db_config['user'] = os.environ.get('TEST_DB_USER', db_config.get('user', 'root'))
    db_config['password'] = os.environ.get('TEST_DB_PASSWORD', db_config.get('password', ''))
    db_config['database'] = os.environ.get('TEST_DB_NAME', db_config.get('database', 'comfyui_test'))
    db_config['charset'] = db_config.get('charset', 'utf8mb4')
    
    # 3. 安全校验：数据库名必须以 _test 或 _unittest 结尾
    db_name = db_config['database']
    if not (db_name.endswith('_test') or db_name.endswith('_unittest')):
        raise ValueError(
            f"测试数据库名称 '{db_name}' 必须以 '_test' 或 '_unittest' 结尾，"
            f"以防止误操作生产数据库"
        )
    
    logger.info(f"测试数据库配置: host={db_config['host']}, database={db_config['database']}")
    return db_config


# 全局配置常量
TEST_DB_CONFIG = get_test_db_config()


def get_unit_test_setting(key, default=None):
    """
    获取单元测试专用配置项
    
    Args:
        key: 配置键名（如 'unit_test.mock_external_apis'）
        default: 默认值
        
    Returns:
        配置值或默认值
    """
    config_file = os.path.join(APP_DIR, get_unit_test_config_path())
    
    if not os.path.exists(config_file):
        return default
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            
        # 支持嵌套键（如 'unit_test.mock_external_apis'）
        keys = key.split('.')
        value = config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    except Exception:
        return default


def get_test_db_connection():
    """获取测试数据库连接上下文管理器"""
    import pymysql
    from pymysql.cursors import DictCursor
    from contextlib import contextmanager
    
    @contextmanager
    def _connection():
        connection = None
        try:
            connection = pymysql.connect(
                host=TEST_DB_CONFIG['host'],
                port=TEST_DB_CONFIG['port'],
                user=TEST_DB_CONFIG['user'],
                password=TEST_DB_CONFIG['password'],
                database=TEST_DB_CONFIG['database'],
                charset=TEST_DB_CONFIG['charset'],
                cursorclass=DictCursor,
                autocommit=False
            )
            yield connection
        except Exception as e:
            logger.error(f"测试数据库连接错误: {e}")
            raise
        finally:
            if connection:
                connection.close()
    
    return _connection()
```

### 1.3 配置文件安全机制

| 检查项 | 说明 | 失败处理 |
|--------|------|----------|
| 数据库名后缀 | 必须以 `_test` 或 `_unittest` 结尾 | 抛出 `ValueError` |
| 配置文件存在 | 优先加载 `config_unit.yml` | 警告并回退到环境变量 |
| 环境变量覆盖 | `TEST_DB_*` 优先级最高 | 允许动态修改 |
| 独立配置节 | 使用 `database` 节，不与生产配置混合 | 明确隔离 |

## 2. SQL建表与CRUD测试

### 2.1 数据库测试基类

**文件**: `tests/base_db_test.py`

**核心功能**:
- `setUpClass`: 连接测试数据库，按依赖顺序执行 SQL 文件建表
- `setUp`: 每个测试用例开始前开启事务
- `tearDown`: 每个测试用例结束后回滚事务（保持数据库干净）
- `tearDownClass`: 清理连接

**SQL文件加载顺序**（已配置在基类中）:
1. world.sql
2. character.sql
3. location.sql
4. props.sql
5. script.sql
6. visual_workflow.sql
7. ai_tools.sql
8. runninghub_slots.sql
9. ai_audio.sql
10. payment_orders.sql
11. tasks.sql

### 2.2 辅助方法

| 方法 | 功能 | 示例 |
|------|------|------|
| `execute_query(sql, params)` | 执行查询，返回结果列表 | `self.execute_query("SELECT * FROM ai_tools WHERE id = %s", (id,))` |
| `execute_update(sql, params)` | 执行UPDATE/DELETE，返回影响行数 | `self.execute_update("UPDATE ai_tools SET status = %s", (1,))` |
| `execute_insert(sql, params)` | 执行INSERT，返回插入ID | `self.execute_insert("INSERT INTO ai_tools ...", params)` |
| `insert_fixture(table, data)` | 快速插入测试数据 | `self.insert_fixture('ai_tools', {'prompt': 'test', 'type': 2})` |
| `count_rows(table, where, params)` | 统计行数 | `self.count_rows('ai_tools', 'status = %s', (1,))` |
| `clear_table(table)` | 清空表数据 | `self.clear_table('ai_tools')` |

### 2.3 CRUD测试示例

**文件**: `tests/test_ai_tools_crud.py`

```python
from tests.base_db_test import DatabaseTestCase

class TestAIToolsCRUD(DatabaseTestCase):
    """AITools 表增删改查测试"""
    
    def test_create_ai_tool(self):
        """测试创建 AI 工具记录"""
        tool_id = self.insert_fixture('ai_tools', {
            'prompt': '生成一个科幻场景',
            'user_id': 1,
            'type': 2,
            'status': 0
        })
        self.assertIsNotNone(tool_id)
        self.assertGreater(tool_id, 0)
    
    def test_read_ai_tool(self):
        """测试查询 AI 工具记录"""
        tool_id = self.insert_fixture('ai_tools', {
            'prompt': '生成魔法效果',
            'type': 3,
            'status': 1
        })
        result = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s", (tool_id,)
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['prompt'], '生成魔法效果')
    
    def test_update_ai_tool(self):
        """测试更新 AI 工具记录"""
        tool_id = self.insert_fixture('ai_tools', {...})
        affected_rows = self.execute_update(
            "UPDATE `ai_tools` SET status = %s WHERE id = %s",
            (2, tool_id)
        )
        self.assertEqual(affected_rows, 1)
        # 查询验证更新结果
        result = self.execute_query("SELECT * FROM `ai_tools` WHERE id = %s", (tool_id,))
        self.assertEqual(result[0]['status'], 2)
    
    def test_delete_ai_tool(self):
        """测试删除 AI 工具记录"""
        tool_id = self.insert_fixture('ai_tools', {...})
        count_before = self.count_rows('ai_tools', 'id = %s', (tool_id,))
        self.assertEqual(count_before, 1)
        
        affected_rows = self.execute_update(
            "DELETE FROM `ai_tools` WHERE id = %s", (tool_id,)
        )
        self.assertEqual(affected_rows, 1)
        
        count_after = self.count_rows('ai_tools', 'id = %s', (tool_id,))
        self.assertEqual(count_after, 0)
```

## 3. 驱动测试（Mock第三方请求）

### 3.1 驱动测试基类

**文件**: `tests/base_visual_driver_test.py`

**核心功能**:
- 继承 `DatabaseTestCase`，拥有所有数据库测试能力
- 提供 AI 工具相关辅助方法：
  - `create_test_ai_tool(ai_tool_type, **kwargs)` - 创建测试AI工具记录
  - `get_ai_tool_from_db(ai_tool_id)` - 从数据库获取AI工具对象
  - `update_ai_tool_status(ai_tool_id, status, **kwargs)` - 更新状态
  - `create_test_task(task_type, task_id, **kwargs)` - 创建测试任务
  - `assert_ai_tool_status(ai_tool_id, expected_status)` - 断言状态
  - `assert_ai_tool_has_project_id(ai_tool_id)` - 断言有project_id
  - `assert_ai_tool_has_result(ai_tool_id)` - 断言有结果URL

### 3.2 Mock第三方请求

**方式1: 使用 `unittest.mock.patch`**

```python
from unittest.mock import patch, MagicMock
from tests.base_visual_driver_test import BaseVisualDriverTest
from task.visual_drivers.sora2_duomi_v1_driver import Sora2DuomiV1Driver

class TestSora2DriverWithDB(BaseVisualDriverTest):
    def setUp(self):
        super().setUp()
        self.driver = Sora2DuomiV1Driver()
        self.test_ai_tool_id = self.create_test_ai_tool(
            ai_tool_type=2, prompt='测试视频生成'
        )
    
    @patch('task.visual_drivers.sora2_duomi_v1_driver.requests.post')
    def test_submit_task_success(self, mock_post):
        """测试提交任务成功"""
        # Mock 第三方API响应
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'code': 200,
            'data': {'taskId': 'task_12345'}
        }
        mock_post.return_value = mock_response
        
        # 获取测试AI工具
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        
        # 执行驱动方法
        result = self.driver.submit_task(ai_tool)
        
        # 验证结果
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'task_12345')
        
        # 验证数据库状态
        self.assert_ai_tool_has_project_id(self.test_ai_tool_id)
    
    @patch('task.visual_drivers.sora2_duomi_v1_driver.requests.get')
    def test_check_status_success(self, mock_get):
        """测试检查状态成功"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'code': 200,
            'data': {
                'status': 'SUCCESS',
                'visualUrl': 'https://example.com/visual.mp4'
            }
        }
        mock_get.return_value = mock_response
        
        result = self.driver.check_status('task_12345')
        
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/visual.mp4')
```

**方式2: 使用 `sys.modules` 预Mock（避免循环导入问题）**

```python
import sys
from unittest.mock import MagicMock

# 在导入驱动之前Mock模块
sys.modules['runninghub_request'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from task.visual_drivers.digital_human_runninghub_v1_driver import DigitalHumanRunninghubV1Driver
```

### 3.3 驱动集成测试示例

**文件**: `tests/driver_integration/test_sora2_driver_with_db.py`

```python
"""
Sora2 驱动数据库集成测试
包含完整的Mock第三方请求和数据库验证
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_visual_driver_test import BaseVisualDriverTest
from task.visual_drivers.sora2_duomi_v1_driver import Sora2DuomiV1Driver


class TestSora2DriverWithDB(BaseVisualDriverTest):
    """Sora2 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = Sora2DuomiV1Driver()
        
        # 创建测试AI工具记录
        self.test_ai_tool_id = self.create_test_ai_tool(
            ai_tool_type=2,
            prompt='生成科幻场景',
            ratio='16:9',
            duration=5
        )
    
    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'sora2')
        self.assertEqual(self.driver.driver_type, 2)
    
    @patch('duomi_api_requset.DuomiAPI.submit_visual_gen_task')
    def test_submit_task_success(self, mock_submit):
        """测试提交任务成功 - Mock第三方请求 + 数据库验证"""
        # Mock 第三方API返回成功
        mock_submit.return_value = {
            'code': 200,
            'data': {'taskId': 'sora_task_12345'}
        }
        
        # 获取测试AI工具
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        
        # 执行提交任务
        result = self.driver.submit_task(ai_tool)
        
        # 验证返回结果
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'sora_task_12345')
        
        # 验证数据库状态 - 关键字段已更新
        db_record = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s",
            (self.test_ai_tool_id,)
        )[0]
        self.assertEqual(db_record['status'], 1)  # 状态变为处理中
        self.assertEqual(db_record['project_id'], 'sora_task_12345')
    
    @patch('duomi_api_requset.DuomiAPI.query_visual_task_status')
    def test_check_status_success(self, mock_query):
        """测试检查状态成功 - Mock第三方请求 + 数据库验证"""
        # Mock 第三方API返回完成状态
        mock_query.return_value = {
            'code': 200,
            'data': {
                'status': 'SUCCESS',
                'visualUrl': 'https://example.com/result.mp4'
            }
        }
        
        # 执行检查状态
        result = self.driver.check_status('sora_task_12345')
        
        # 验证返回结果
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result.mp4')
    
    @patch('duomi_api_requset.DuomiAPI.submit_visual_gen_task')
    def test_submit_task_api_error(self, mock_submit):
        """测试第三方API返回错误"""
        # Mock 第三方API返回错误
        mock_submit.return_value = {
            'code': 500,
            'message': '服务器内部错误'
        }
        
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        result = self.driver.submit_task(ai_tool)
        
        # 验证返回错误信息
        self.assertFalse(result['success'])
        self.assertIn('error', result)
        
        # 验证数据库状态 - 状态应为失败
        self.assert_ai_tool_status(self.test_ai_tool_id, -1)


if __name__ == '__main__':
    import unittest
    unittest.main()
```

## 4. 执行后数据库验证

### 4.1 断言方法

**基类提供的数据库验证方法**:

```python
# 断言AI工具状态
def assert_ai_tool_status(self, ai_tool_id, expected_status):
    result = self.execute_query(
        "SELECT status FROM `ai_tools` WHERE id = %s", (ai_tool_id,)
    )
    self.assertEqual(len(result), 1)
    self.assertEqual(result[0]['status'], expected_status)

# 断言AI工具有project_id
def assert_ai_tool_has_project_id(self, ai_tool_id):
    result = self.execute_query(
        "SELECT project_id FROM `ai_tools` WHERE id = %s", (ai_tool_id,)
    )
    self.assertEqual(len(result), 1)
    self.assertIsNotNone(result[0]['project_id'])
    return result[0]['project_id']

# 断言AI工具有结果URL
def assert_ai_tool_has_result(self, ai_tool_id):
    result = self.execute_query(
        "SELECT result_url FROM `ai_tools` WHERE id = %s", (ai_tool_id,)
    )
    self.assertEqual(len(result), 1)
    self.assertIsNotNone(result[0]['result_url'])
    return result[0]['result_url']
```

### 4.2 自定义验证模式

```python
def test_custom_db_validation(self):
    """自定义数据库验证示例"""
    # 执行操作...
    
    # 1. 验证记录存在且字段正确
    result = self.execute_query(
        "SELECT status, project_id, result_url FROM `ai_tools` WHERE id = %s",
        (self.test_ai_tool_id,)
    )
    self.assertEqual(len(result), 1, "记录应存在")
    record = result[0]
    
    # 2. 多字段验证
    self.assertEqual(record['status'], 2, "状态应为完成")
    self.assertIsNotNone(record['project_id'], "应有project_id")
    self.assertTrue(
        record['result_url'].startswith('http'),
        "result_url应为有效URL"
    )
    
    # 3. 验证关联表数据
    related = self.execute_query(
        "SELECT * FROM `tasks` WHERE task_id = %s",
        (record['project_id'],)
    )
    self.assertGreater(len(related), 0, "tasks表应有关联记录")
    
    # 4. 统计数据验证
    count = self.count_rows('ai_tools', 'status = %s AND user_id = %s', (2, 1))
    self.assertEqual(count, expected_count, "完成状态记录数应正确")
```

## 5. 运行测试

### 5.1 运行所有测试

```bash
# 使用unittest
python -m unittest discover tests -p "test_*.py" -v

# 使用pytest
pytest tests/ -v
```

### 5.2 运行特定测试

```bash
# 运行单个CRUD测试文件
python -m unittest tests.test_ai_tools_crud -v

# 运行单个驱动集成测试
python -m unittest tests.driver_integration.test_sora2_driver_with_db -v

# 运行单个测试类
python -m unittest tests.test_ai_tools_crud.TestAIToolsCRUD -v

# 运行单个测试方法
python -m unittest tests.test_ai_tools_crud.TestAIToolsCRUD.test_create_ai_tool -v
```

### 5.3 使用pytest（推荐）

```bash
# 显示详细输出
pytest tests/ -v

# 显示打印信息
pytest tests/ -s

# 运行特定测试类
pytest tests/test_ai_tools_crud.py::TestAIToolsCRUD -v

# 运行特定测试方法
pytest tests/test_ai_tools_crud.py::TestAIToolsCRUD::test_create_ai_tool -v

# 失败时立即停止
pytest tests/ -x

# 重新运行上次失败的测试
pytest tests/ --lf
```

## 6. 扩展指南

### 6.1 添加新的CRUD测试

1. 创建文件 `tests/test_<表名>_crud.py`
2. 继承 `DatabaseTestCase`
3. 实现 `test_create_xxx`, `test_read_xxx`, `test_update_xxx`, `test_delete_xxx` 方法
4. 使用 `self.insert_fixture()` 插入测试数据
5. 使用 `self.execute_query()` 查询验证

### 6.2 添加新的驱动测试

1. 在 `tests/driver_integration/` 创建 `test_<驱动名>_driver_with_db.py`
2. 继承 `BaseVisualDriverTest`
3. 在 `setUp()` 中初始化驱动并创建测试AI工具
4. 使用 `@patch` 装饰器Mock第三方请求
5. 调用驱动方法
6. 使用基类断言方法或自定义查询验证数据库状态

### 6.3 添加新的SQL表

1. 在 `model/sql/` 创建 `<表名>.sql`
2. 在 `base_db_test.py` 的 `_get_sql_files_in_order()` 中添加文件（注意依赖顺序）

## 9. 一键执行所有测试

### 9.1 主测试执行脚本

**新建文件**: `run_unit_tests.py`（项目根目录下的一键测试入口）

```python
#!/usr/bin/env python3
"""
单元测试一键执行脚本

功能：
1. 自动加载 config_unit.yml 配置
2. 执行数据库连接测试
3. 执行所有 CRUD 测试
4. 执行所有驱动集成测试
5. 生成测试报告
6. 输出执行摘要

用法：
    python run_unit_tests.py [选项]

选项：
    --crud-only     只执行 CRUD 测试
    --driver-only   只执行驱动测试
    --verbose       显示详细输出
    --failfast      遇到失败立即停止
    --coverage      生成覆盖率报告
"""
import sys
import os
import argparse
import unittest
import subprocess
from pathlib import Path

# 确保能导入 tests 模块
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from tests.db_test_config import get_test_db_config, get_unit_test_setting


class TestRunner:
    """测试执行器"""
    
    def __init__(self, args):
        self.args = args
        self.test_results = {
            'db_connection': {'passed': 0, 'failed': 0, 'errors': 0},
            'crud': {'passed': 0, 'failed': 0, 'errors': 0},
            'driver': {'passed': 0, 'failed': 0, 'errors': 0},
            'total': {'passed': 0, 'failed': 0, 'errors': 0}
        }
    
    def check_environment(self):
        """检查测试环境"""
        print("=" * 60)
        print("步骤 1: 检查测试环境")
        print("=" * 60)
        
        # 检查配置文件
        config_unit_path = os.path.join(APP_DIR, 'config_unit.yml')
        if not os.path.exists(config_unit_path):
            print(f"[WARNING] config_unit.yml 不存在，将使用环境变量或默认值")
        else:
            print(f"[OK] 配置文件: {config_unit_path}")
        
        # 检查数据库配置
        try:
            db_config = get_test_db_config()
            print(f"[OK] 测试数据库: {db_config['database']}@{db_config['host']}")
            
            # 验证数据库名安全
            if not (db_config['database'].endswith('_test') or 
                    db_config['database'].endswith('_unittest')):
                print(f"[ERROR] 数据库名 '{db_config['database']}' 不符合安全规范")
                return False
        except Exception as e:
            print(f"[ERROR] 数据库配置错误: {e}")
            return False
        
        print()
        return True
    
    def run_db_connection_test(self):
        """执行数据库连接测试"""
        print("=" * 60)
        print("步骤 2: 数据库连接测试")
        print("=" * 60)
        
        try:
            import unittest
            from tests.test_db_connection import TestDBConnection
            
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromTestCase(TestDBConnection)
            
            runner = unittest.TextTestRunner(verbosity=2 if self.args.verbose else 1)
            result = runner.run(suite)
            
            self.test_results['db_connection']['passed'] = result.testsRun - len(result.failures) - len(result.errors)
            self.test_results['db_connection']['failed'] = len(result.failures)
            self.test_results['db_connection']['errors'] = len(result.errors)
            
            if result.wasSuccessful():
                print("[OK] 数据库连接测试通过")
                return True
            else:
                print("[FAILED] 数据库连接测试失败")
                return False
                
        except Exception as e:
            print(f"[ERROR] 执行连接测试时出错: {e}")
            self.test_results['db_connection']['errors'] = 1
            return False
        finally:
            print()
    
    def run_crud_tests(self):
        """执行所有 CRUD 测试"""
        print("=" * 60)
        print("步骤 3: CRUD 测试")
        print("=" * 60)
        
        crud_test_files = [
            'tests.test_ai_tools_crud',
            'tests.test_ai_audio_crud',
            'tests.test_character_crud',
            'tests.test_location_crud',
            'tests.test_payment_orders_crud',
            'tests.test_props_crud',
            'tests.test_runninghub_slots_crud',
            'tests.test_script_crud',
            'tests.test_tasks_crud',
            'tests.test_visual_workflow_crud',
            'tests.test_world_crud',
        ]
        
        all_passed = True
        for test_module in crud_test_files:
            try:
                print(f"\n执行: {test_module}")
                suite = unittest.TestLoader().loadTestsFromName(test_module)
                runner = unittest.TextTestRunner(verbosity=1)
                result = runner.run(suite)
                
                self.test_results['crud']['passed'] += result.testsRun - len(result.failures) - len(result.errors)
                self.test_results['crud']['failed'] += len(result.failures)
                self.test_results['crud']['errors'] += len(result.errors)
                
                if not result.wasSuccessful():
                    all_passed = False
                    if self.args.failfast:
                        break
                        
            except Exception as e:
                print(f"[ERROR] 执行 {test_module} 失败: {e}")
                all_passed = False
        
        print()
        return all_passed
    
    def run_driver_tests(self):
        """执行所有驱动集成测试"""
        print("=" * 60)
        print("步骤 4: 驱动集成测试")
        print("=" * 60)
        
        driver_test_files = [
            'tests.driver_integration.test_digital_human_driver_with_db',
            'tests.driver_integration.test_sora2_driver_with_db',
            'tests.driver_integration.test_ltx2_driver_with_db',
            'tests.driver_integration.test_vidu_driver_with_db',
            'tests.driver_integration.test_wan22_driver_with_db',
            'tests.driver_integration.test_kling_driver_with_db',
            'tests.driver_integration.test_veo3_driver_with_db',
            'tests.driver_integration.test_gemini_driver_with_db',
        ]
        
        all_passed = True
        for test_module in driver_test_files:
            try:
                # 检查文件是否存在
                file_path = test_module.replace('.', '/') + '.py'
                full_path = os.path.join(APP_DIR, file_path)
                if not os.path.exists(full_path):
                    print(f"[SKIP] {test_module} (文件不存在)")
                    continue
                
                print(f"\n执行: {test_module}")
                suite = unittest.TestLoader().loadTestsFromName(test_module)
                runner = unittest.TextTestRunner(verbosity=1)
                result = runner.run(suite)
                
                self.test_results['driver']['passed'] += result.testsRun - len(result.failures) - len(result.errors)
                self.test_results['driver']['failed'] += len(result.failures)
                self.test_results['driver']['errors'] += len(result.errors)
                
                if not result.wasSuccessful():
                    all_passed = False
                    if self.args.failfast:
                        break
                        
            except Exception as e:
                print(f"[ERROR] 执行 {test_module} 失败: {e}")
                all_passed = False
        
        print()
        return all_passed
    
    def print_summary(self):
        """打印测试摘要"""
        print("=" * 60)
        print("测试执行摘要")
        print("=" * 60)
        
        # 计算总数
        for category in ['db_connection', 'crud', 'driver']:
            for key in ['passed', 'failed', 'errors']:
                self.test_results['total'][key] += self.test_results[category][key]
        
        print(f"数据库连接测试: "
              f"通过 {self.test_results['db_connection']['passed']}, "
              f"失败 {self.test_results['db_connection']['failed']}, "
              f"错误 {self.test_results['db_connection']['errors']}")
        
        print(f"CRUD 测试:       "
              f"通过 {self.test_results['crud']['passed']}, "
              f"失败 {self.test_results['crud']['failed']}, "
              f"错误 {self.test_results['crud']['errors']}")
        
        print(f"驱动集成测试:    "
              f"通过 {self.test_results['driver']['passed']}, "
              f"失败 {self.test_results['driver']['failed']}, "
              f"错误 {self.test_results['driver']['errors']}")
        
        print("-" * 60)
        print(f"总计:            "
              f"通过 {self.test_results['total']['passed']}, "
              f"失败 {self.test_results['total']['failed']}, "
              f"错误 {self.test_results['total']['errors']}")
        print("=" * 60)
        
        # 返回码
        if self.test_results['total']['failed'] > 0 or self.test_results['total']['errors'] > 0:
            return 1
        return 0
    
    def run(self):
        """执行完整测试流程"""
        print("\n" + "=" * 60)
        print("单元测试一键执行")
        print("=" * 60 + "\n")
        
        # 步骤 1: 检查环境
        if not self.check_environment():
            return 1
        
        # 步骤 2: 数据库连接测试
        if not self.args.crud_only and not self.args.driver_only:
            if not self.run_db_connection_test():
                if self.args.failfast:
                    return 1
        
        # 步骤 3: CRUD 测试
        if not self.args.driver_only:
            self.run_crud_tests()
        
        # 步骤 4: 驱动测试
        if not self.args.crud_only:
            self.run_driver_tests()
        
        # 步骤 5: 输出摘要
        return_code = self.print_summary()
        
        print("\n测试执行完成！")
        return return_code


def main():
    parser = argparse.ArgumentParser(description='单元测试一键执行脚本')
    parser.add_argument('--crud-only', action='store_true', help='只执行 CRUD 测试')
    parser.add_argument('--driver-only', action='store_true', help='只执行驱动测试')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细输出')
    parser.add_argument('--failfast', '-x', action='store_true', help='遇到失败立即停止')
    parser.add_argument('--coverage', action='store_true', help='生成覆盖率报告')
    
    args = parser.parse_args()
    
    runner = TestRunner(args)
    exit_code = runner.run()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
```

### 9.2 Shell 脚本入口

**新建文件**: `run_tests.sh`（Shell 快捷入口）

```bash
#!/bin/bash
# 单元测试一键执行脚本 (Shell 版本)

cd "$(dirname "$0")"

echo "=================================="
echo "单元测试一键执行"
echo "=================================="

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 未安装"
    exit 1
fi

# 执行测试
python3 run_unit_tests.py "$@"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo "[OK] 所有测试通过"
else
    echo ""
    echo "[FAILED] 部分测试失败"
fi

exit $exit_code
```

### 9.3 使用方式

```bash
# 一键执行所有测试
python run_unit_tests.py

# 或
./run_tests.sh

# 只执行 CRUD 测试
python run_unit_tests.py --crud-only

# 只执行驱动测试（含 Mock）
python run_unit_tests.py --driver-only

# 详细输出 + 失败立即停止
python run_unit_tests.py --verbose --failfast

# 生成覆盖率报告
python run_unit_tests.py --coverage
```

### 9.4 执行流程图

```
run_unit_tests.py
├── 1. 检查环境
│   ├── 检查 config_unit.yml
│   ├── 验证数据库配置
│   └── 数据库名安全校验 (_test/_unittest)
│
├── 2. 数据库连接测试 (test_db_connection.py)
│   └── 测试是否能连接到测试库
│
├── 3. CRUD 测试 (11个测试文件)
│   ├── test_ai_tools_crud.py
│   ├── test_ai_audio_crud.py
│   ├── test_character_crud.py
│   ├── test_location_crud.py
│   ├── test_payment_orders_crud.py
│   ├── test_props_crud.py
│   ├── test_runninghub_slots_crud.py
│   ├── test_script_crud.py
│   ├── test_tasks_crud.py
│   ├── test_visual_workflow_crud.py
│   └── test_world_crud.py
│
├── 4. 驱动集成测试 (8个驱动)
│   ├── test_digital_human_driver_with_db.py
│   ├── test_sora2_driver_with_db.py
│   ├── test_ltx2_driver_with_db.py
│   ├── test_vidu_driver_with_db.py
│   ├── test_wan22_driver_with_db.py
│   ├── test_kling_driver_with_db.py
│   ├── test_veo3_driver_with_db.py
│   └── test_gemini_driver_with_db.py
│
└── 5. 输出测试摘要
    ├── 各分类通过/失败/错误统计
    └── 总计结果
```

---

## 10. 总结

### 测试架构完整清单

| 组件 | 文件 | 说明 |
|------|------|------|
| 独立配置文件 | `config_unit.yml` | 测试专用配置，与生产隔离 |
| 配置加载器 | `tests/db_test_config.py` | 加载 config_unit.yml，安全校验 |
| 数据库基类 | `tests/base_db_test.py` | 自动建表、事务隔离 |
| 驱动基类 | `tests/base_visual_driver_test.py` | Mock 测试基础设施 |
| CRUD测试 | `tests/test_*_crud.py` | 11个表的增删改查测试 |
| 驱动测试 | `tests/driver_integration/test_*_driver_with_db.py` | 8个驱动的 Mock 测试 |
| 一键执行 | `run_unit_tests.py` + `run_tests.sh` | 完整测试流程入口 |

### 安全机制汇总

1. **数据库名校验**: 必须以 `_test` 或 `_unittest` 结尾
2. **配置隔离**: `config_unit.yml` 独立于生产配置
3. **事务隔离**: 每个测试后自动回滚
4. **Mock机制**: 所有第三方请求均被 Mock
5. **环境变量**: `TEST_DB_*` 可动态覆盖配置

### 执行命令速查

```bash
# 一键执行
python run_unit_tests.py

# 分类执行
python run_unit_tests.py --crud-only
python run_unit_tests.py --driver-only

# 调试模式
python run_unit_tests.py --verbose --failfast
```
