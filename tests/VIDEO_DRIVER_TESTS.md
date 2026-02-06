# 视频驱动数据库集成测试文档

## 概述

视频驱动数据库集成测试使用真实的测试数据库来验证驱动的功能，替代了之前使用 Mock 对象的单元测试方式。这种方式可以更真实地测试驱动与数据库的交互。

## 测试架构

### 测试基类

- **`base_db_test.py`** - 数据库测试基础类，提供事务隔离和数据库操作
- **`base_video_driver_test.py`** - 视频驱动测试基类，提供驱动测试的通用方法

### 核心特性

1. **真实数据库测试** - 使用测试数据库 `voice_replace_unittest` 进行测试
2. **事务隔离** - 每个测试在独立事务中运行，测试结束后自动回滚
3. **Mock 外部 API** - 使用 Mock 模拟外部 API 调用，避免真实网络请求
4. **完整工作流测试** - 测试从创建任务到更新数据库的完整流程

## 文件结构

所有驱动集成测试都位于 `tests/driver_integration/` 目录下：

```
tests/
├── driver_integration/
│   ├── __init__.py
│   ├── test_vidu_driver_with_db.py
│   ├── test_ltx2_driver_with_db.py
│   └── test_kling_driver_with_db.py
├── base_db_test.py
├── base_video_driver_test.py
└── ...
```

## 已实现的驱动测试

### 1. Vidu 驱动测试 (`driver_integration/test_vidu_driver_with_db.py`)

**测试用例：**
- ✅ 成功提交任务
- ✅ API 返回错误
- ✅ 提交双图任务（首尾图生视频）
- ✅ 检查任务状态 - 成功/处理中/失败
- ✅ 完整工作流测试
- ✅ 按状态查询 AI 工具
- ✅ 更新任务结果

**总计：9 个测试用例**

### 2. LTX2 驱动测试 (`driver_integration/test_ltx2_driver_with_db.py`)

**测试用例：**
- ✅ 成功提交 LTX2 任务
- ✅ 队列已满的情况
- ✅ 检查任务状态 - 成功/运行中/失败
- ✅ 创建和查询 LTX2 任务

**总计：6 个测试用例**

### 3. Kling 驱动测试 (`driver_integration/test_kling_driver_with_db.py`)

**测试用例：**
- ✅ 成功提交 Kling 任务
- ✅ API 返回错误
- ✅ 检查任务状态 - 成功/处理中/失败
- ✅ 更新 Kling 任务的 project_id

**总计：6 个测试用例**

### 4. Digital Human 驱动测试 (`driver_integration/test_digital_human_driver_with_db.py`)

**测试用例：**
- ✅ 驱动初始化
- ✅ 创建数字人任务记录

**总计：2 个测试用例**

### 5. Gemini 驱动测试 (`driver_integration/test_gemini_driver_with_db.py`)

**测试用例：**
- ✅ 驱动初始化
- ✅ 更新 Gemini 任务

**总计：2 个测试用例**

### 6. Gemini Pro 驱动测试 (`driver_integration/test_gemini_pro_driver_with_db.py`)

**测试用例：**
- ✅ 驱动初始化
- ✅ 更新 Gemini Pro 任务

**总计：2 个测试用例**

### 7. Sora2 驱动测试 (`driver_integration/test_sora2_driver_with_db.py`)

**测试用例：**
- ✅ 驱动初始化
- ✅ 创建 Sora2 任务记录

**总计：2 个测试用例**

### 8. VEO3 驱动测试 (`driver_integration/test_veo3_driver_with_db.py`)

**测试用例：**
- ✅ 驱动初始化
- ✅ 创建 VEO3 任务记录

**总计：2 个测试用例**

### 9. Wan2.2 驱动测试 (`driver_integration/test_wan22_driver_with_db.py`)

**测试用例：**
- ✅ 驱动初始化
- ✅ 创建 Wan2.2 任务记录

**总计：2 个测试用例**

## 运行测试

### 运行所有驱动测试

```bash
./run_driver_tests.sh
```

### 运行单个驱动测试

```bash
# Vidu 驱动测试
python3 -m unittest tests.driver_integration.test_vidu_driver_with_db -v

# LTX2 驱动测试
python3 -m unittest tests.driver_integration.test_ltx2_driver_with_db -v

# Kling 驱动测试
python3 -m unittest tests.driver_integration.test_kling_driver_with_db -v
```

### 运行单个测试用例

```bash
python3 -m unittest tests.driver_integration.test_vidu_driver_with_db.TestViduDriverWithDB.test_submit_task_success -v
```

## 编写新的驱动测试

### 步骤 1：在 driver_integration 目录创建测试文件

在 `tests/driver_integration/` 目录下创建新的测试文件：

```python
"""
新驱动数据库集成测试
"""
import sys
from unittest.mock import patch, MagicMock

# Mock 外部依赖
sys.modules['your_api_module'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.your_driver import YourDriver


class TestYourDriverWithDB(BaseVideoDriverTest):
    """你的驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = YourDriver()
        
        # 创建测试用的 AI 工具记录
        self.test_ai_tool_id = self.create_test_ai_tool(
            ai_tool_type=15,  # 你的驱动类型
            prompt='测试提示词',
            image_path='https://example.com/test.jpg',
            duration=5
        )
```

### 步骤 2：编写测试用例

```python
    @patch('task.video_drivers.your_driver.your_api_function')
    def test_submit_task_success(self, mock_api):
        """测试成功提交任务"""
        # 设置 Mock 返回值
        mock_api.return_value = {
            'task_id': 'test_task_123',
            'status': 'success'
        }
        
        # 从数据库获取 AI 工具对象
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        
        # 调用驱动提交任务
        result = self.driver.submit_task(ai_tool)
        
        # 断言结果
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'test_task_123')
        
        # 验证 API 调用
        mock_api.assert_called_once()
```

### 步骤 3：测试数据库操作

```python
    def test_update_task_status(self):
        """测试更新任务状态"""
        # 更新状态
        self.update_ai_tool_status(
            self.test_ai_tool_id,
            status=1,
            project_id='test_proj_123'
        )
        
        # 验证更新
        self.assert_ai_tool_status(self.test_ai_tool_id, 1)
        project_id = self.assert_ai_tool_has_project_id(self.test_ai_tool_id)
        self.assertEqual(project_id, 'test_proj_123')
```

## 基类提供的辅助方法

### BaseVideoDriverTest 方法

| 方法 | 说明 |
|------|------|
| `create_test_ai_tool(type, **kwargs)` | 创建测试用的 AI 工具记录 |
| `get_ai_tool_from_db(id)` | 从数据库获取 AI 工具对象 |
| `update_ai_tool_status(id, status, **kwargs)` | 更新 AI 工具状态 |
| `create_test_task(type, task_id, **kwargs)` | 创建测试任务记录 |
| `assert_ai_tool_status(id, expected_status)` | 断言 AI 工具状态 |
| `assert_ai_tool_has_project_id(id)` | 断言 AI 工具有 project_id |
| `assert_ai_tool_has_result(id)` | 断言 AI 工具有结果 URL |

### DatabaseTestCase 方法（继承自基类）

| 方法 | 说明 |
|------|------|
| `insert_fixture(table, data)` | 插入测试数据 |
| `execute_query(sql, params)` | 执行查询 |
| `execute_update(sql, params)` | 执行更新 |
| `count_rows(table, where, params)` | 统计行数 |
| `clear_table(table)` | 清空表 |

## 测试数据隔离

每个测试用例都在独立的事务中运行：

1. **setUp** - 开始事务，创建测试数据
2. **测试执行** - 在事务中进行数据库操作
3. **tearDown** - 回滚事务，清理测试数据

这确保了：
- 测试之间互不干扰
- 数据库始终保持干净状态
- 可以并发运行测试

## 与原有 Mock 测试的对比

### 原有测试方式（Mock）

```python
def setUp(self):
    self.driver = ViduDefaultDriver()
    self.mock_ai_tool = Mock()
    self.mock_ai_tool.id = "vidu_tool_001"
    self.mock_ai_tool.prompt = "测试提示词"
```

**优点：**
- 不需要数据库
- 运行速度快

**缺点：**
- 无法测试真实的数据库交互
- Mock 对象可能与真实对象不一致

### 新测试方式（数据库集成）

```python
def setUp(self):
    super().setUp()
    self.driver = ViduDefaultDriver()
    self.test_ai_tool_id = self.create_test_ai_tool(
        ai_tool_type=14,
        prompt='测试提示词'
    )
```

**优点：**
- 测试真实的数据库交互
- 更接近生产环境
- 可以测试完整的工作流

**缺点：**
- 需要测试数据库
- 运行速度稍慢（但仍然很快）

## 最佳实践

1. **使用事务隔离** - 所有测试都应该继承 `BaseVideoDriverTest`
2. **Mock 外部 API** - 使用 `@patch` 装饰器 Mock 外部 API 调用
3. **测试完整流程** - 不仅测试驱动逻辑，还要测试数据库操作
4. **清晰的测试名称** - 使用描述性的测试方法名
5. **独立的测试用例** - 每个测试应该独立运行，不依赖其他测试

## 扩展其他驱动测试

要为其他驱动（如 Wan2.2, Sora2, VEO3 等）创建数据库测试，只需：

1. 在 `tests/driver_integration/` 目录下复制现有的测试文件（如 `test_vidu_driver_with_db.py`）
2. 修改驱动类型和 Mock 的 API 模块
3. 调整测试用例以匹配该驱动的特性
4. 添加到 `run_driver_tests.sh` 脚本中

## 测试结果

**总计：33 个测试用例，全部通过！** ✅

- Vidu 驱动：9 个测试（完整的 API Mock 测试）
- LTX2 驱动：6 个测试（完整的 API Mock 测试）
- Kling 驱动：6 个测试（完整的 API Mock 测试）
- Digital Human 驱动：2 个测试（数据库操作测试）
- Gemini 驱动：2 个测试（数据库操作测试）
- Gemini Pro 驱动：2 个测试（数据库操作测试）
- Sora2 驱动：2 个测试（数据库操作测试）
- VEO3 驱动：2 个测试（数据库操作测试）
- Wan2.2 驱动：2 个测试（数据库操作测试）

所有测试都使用真实数据库，确保驱动与数据库的交互正确无误。

### 测试类型说明

**完整的 API Mock 测试**（Vidu、LTX2、Kling）：
- 包含驱动初始化测试
- 包含任务提交测试（成功和失败场景）
- 包含任务状态查询测试
- 包含完整工作流测试
- 包含数据库 CRUD 操作测试

**数据库操作测试**（其他驱动）：
- 驱动初始化验证
- 数据库记录创建和查询
- 任务状态更新

这种分层测试策略既保证了核心驱动的完整测试覆盖，又为所有驱动提供了基础的数据库集成测试。
