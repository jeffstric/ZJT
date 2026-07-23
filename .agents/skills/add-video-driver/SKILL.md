---
name: add-video-driver
description: 新增视频驱动专家，指导如何在本项目中添加新的视频生成模型驱动（如 Happy Horse、Sora、Kling 等）。当需要接入新的视频生成 API 时使用。
allowed-tools: Read, Write, Terminal
---

# 新增视频驱动专家

## 角色定位

你是一位视频驱动集成专家，负责在本项目中添加新的视频生成模型驱动（如 Happy Horse、Sora、Kling 等）。

## 项目结构

```
项目根目录/
├── task/visual_drivers/           # 视频驱动目录
│   ├── base_video_driver.py       # 抽象基类
│   ├── driver_factory.py          # 驱动工厂（注册中心）
│   ├── vidu_default_driver.py     # Vidu 驱动示例
│   └── ...
├── config/
│   ├── unified_config.py          # 统一配置（任务类型、驱动实现常量）
│   └── default_configs.py         # 热更新配置定义
├── alembic/versions/              # 数据库迁移脚本
└── tests/base/                    # 驱动单元测试
```

## 核心概念

### 三层映射架构

```
任务类型(ID) → 业务驱动名称 → 实现驱动名称 → 驱动类实例
     ↓              ↓                ↓              ↓
    14    →  vidu_i2v  →  vidu_default  →  ViduDefaultDriver()
```

**配置位置**：`config/unified_config.py` 的 `ALL_TASK_CONFIGS` 列表

### 任务分类

- `TEXT_TO_VIDEO` - 文生视频（t2v）
- `IMAGE_TO_VIDEO` - 图生视频（i2v）
- `TEXT_TO_IMAGE` - 文生图
- `IMAGE_EDIT` - 图片编辑
- `DIGITAL_HUMAN` - 数字人

## 新增视频驱动完整流程

### 第一步：定义驱动常量和任务配置

**文件**：`config/unified_config.py`

#### 1.1 添加驱动实现常量

在 `DriverImplementation` 类中添加新驱动的实现名称：

```python
class DriverImplementation:
    """驱动实现类名常量"""
    # ... 已有驱动
    
    # Happy Horse (阿里云百炼)
    HAPPY_HORSE_BAILIAN_I2V_V1 = 'happy_horse_bailian_i2v_v1'  # 图生视频
    HAPPY_HORSE_BAILIAN_R2V_V1 = 'happy_horse_bailian_r2v_v1'  # 参考生视频
    HAPPY_HORSE_BAILIAN_T2V_V1 = 'happy_horse_bailian_t2v_v1'  # 文生视频
```

#### 1.2 添加驱动实现 ID

在 `DriverImplementationId` 类中添加对应的数字 ID（用于数据库存储）：

```python
class DriverImplementationId:
    """驱动实现 ID 常量"""
    # ... 已有 ID
    
    HAPPY_HORSE_BAILIAN_I2V_V1 = 50  # 选择未使用的 ID
    HAPPY_HORSE_BAILIAN_R2V_V1 = 51
    HAPPY_HORSE_BAILIAN_T2V_V1 = 52
```

#### 1.3 注册任务配置

在 `ALL_TASK_CONFIGS` 列表中添加新任务配置：

```python
ALL_TASK_CONFIGS = [
    # ... 已有任务
    
    # Happy Horse 图生视频
    UnifiedTaskConfig(
        id=30,  # 任务类型 ID（对应 ai_tools 表的 type 字段）
        name="happy_horse_i2v",
        display_name="Happy Horse 图生视频",
        category=TaskCategory.IMAGE_TO_VIDEO,
        driver_name="happy_horse_i2v",  # 业务驱动名称
        provider=TaskProvider.BAILIAN,  # 供应商（需在 TaskProvider 中定义）
        enabled=True,
        description="阿里云百炼 Happy Horse 图生视频",
        computing_power=0, #为0 可以根据 实现方的算力决定，不为0 会直接根据这个算力值计算
        
        # 实现方配置
        implementations=[
            ImplementationConfig(
                name=DriverImplementation.HAPPY_HORSE_BAILIAN_I2V_V1,
                display_name="阿里云百炼",
                driver_class="HappyHorseBailianI2vV1Driver",
                default_computing_power={5: 10, 10: 20},  # {时长: 算力}
                enabled=True,
                description="阿里云百炼官方 API",
                sort_order=1.0,
                required_config_keys=["bailian.api_key"]  # 依赖的配置键
            ),
        ],
        
        # 支持的参数
        supported_params={
            "prompt": {"required": True, "type": "string"},
            "image_path": {"required": True, "type": "string"},
            "duration": {"required": True, "type": "int", "values": [5, 10]},
            "ratio": {"required": False, "type": "string", "values": ["16:9", "9:16", "1:1"]},
        },
        
        # 默认参数
        default_params={
            "duration": 5,
            "ratio": "16:9",
        },
    ),
]
```

**关键字段说明**：
- `id` - 任务类型 ID，对应数据库 `ai_tools.type` 字段
- `driver_name` - 业务驱动名称，用于第一层映射
- `implementations` - 实现方列表，每个实现方对应一个具体的驱动类
- `default_computing_power` - 算力配置，可以是固定值或按时长的字典
- `required_config_keys` - 依赖的配置键，用于检查配置是否完整

### 第二步：实现驱动类

**文件**：`task/visual_drivers/{driver_name}_driver.py`

#### 2.1 创建驱动文件

创建 `task/visual_drivers/happy_horse_bailian_i2v_v1_driver.py`：

```python
"""
Happy Horse 阿里云百炼图生视频驱动
"""
from typing import Dict, Any, Optional
import requests
import traceback
from .base_video_driver import BaseVideoDriver, ImageMode
from config.config_util import get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import upload_local_images_to_cdn_sync


class HappyHorseBailianI2vV1Driver(BaseVideoDriver):
    """
    Happy Horse 阿里云百炼图生视频驱动
    支持图生视频（i2v）模式
    """

    def __init__(self):
        super().__init__(driver_name="happy_horse_bailian_i2v", driver_type=30)

        # 加载配置
        self._api_key = get_dynamic_config_value("bailian", "api_key", default="")
        self._base_url = get_dynamic_config_value(
            "bailian", "base_url", 
            default="https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/generation"
        )
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 验证必需配置
        self._validate_required({
            "阿里云百炼 API Key": self._api_key,
        })

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交图生视频任务到阿里云百炼 API
        
        Args:
            ai_tool: AITool 对象，包含任务参数
                - prompt: 提示词
                - image_path: 图片路径
                - duration: 视频时长（5 或 10 秒）
                - ratio: 视频比例（可选）
                
        Returns:
            Dict[str, Any]: 包含 task_id 和状态的字典
        """
        try:
            # 1. 上传图片到 CDN
            image_url = self._upload_image_to_cdn(ai_tool.image_path)
            
            # 2. 构建请求参数
            request_data = {
                "model": "happy-horse-v1",
                "input": {
                    "prompt": ai_tool.prompt,
                    "image_url": image_url,
                },
                "parameters": {
                    "duration": ai_tool.duration,
                }
            }
            
            # 添加可选参数
            if hasattr(ai_tool, 'ratio') and ai_tool.ratio:
                request_data["parameters"]["aspect_ratio"] = ai_tool.ratio
            
            # 3. 发送请求
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
            
            self.logger.info(f"[{self.driver_name}] 提交任务: {request_data}")
            
            response = requests.post(
                self._base_url,
                json=request_data,
                headers=headers,
                timeout=self._timeout
            )
            
            # 4. 解析响应
            result = response.json()
            
            # 5. 验证响应格式
            is_valid, error_msg = self._validate_submit_response(result)
            if not is_valid:
                self._send_alert(
                    "INVALID_RESPONSE_FORMAT",
                    f"API 响应格式异常: {error_msg}",
                    {"response": result}
                )
                return {
                    "success": False,
                    "error": f"API 响应格式异常: {error_msg}",
                    "user_message": "视频生成服务响应异常，请稍后重试"
                }
            
            # 6. 检查业务错误
            if "error" in result:
                error_code = result["error"].get("code", "UNKNOWN")
                error_msg = result["error"].get("message", "未知错误")
                return {
                    "success": False,
                    "error": f"API 错误: {error_code} - {error_msg}",
                    "user_message": error_msg
                }
            
            # 7. 返回成功结果
            return {
                "success": True,
                "task_id": result["output"]["task_id"],
                "status": result["output"]["task_status"],
            }
            
        except requests.exceptions.Timeout:
            return self._handle_timeout_error()
        except requests.exceptions.RequestException as e:
            return self._handle_network_error(e)
        except Exception as e:
            return self._handle_unexpected_error(e, traceback.format_exc())

    def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        检查任务状态
        
        Args:
            project_id: 任务 ID
            
        Returns:
            Dict[str, Any]: 包含任务状态和结果的字典
        """
        try:
            # 1. 构建查询 URL
            query_url = f"{self._base_url}/{project_id}"
            
            headers = {
                "Authorization": f"Bearer {self._api_key}",
            }
            
            # 2. 发送查询请求
            response = requests.get(
                query_url,
                headers=headers,
                timeout=self._timeout
            )
            
            result = response.json()
            
            # 3. 验证响应格式
            is_valid, error_msg = self._validate_status_response(result)
            if not is_valid:
                self._send_alert(
                    "INVALID_STATUS_RESPONSE",
                    f"状态查询响应格式异常: {error_msg}",
                    {"response": result}
                )
                return {
                    "success": False,
                    "error": f"状态查询响应异常: {error_msg}"
                }
            
            # 4. 解析状态
            status = result["output"]["task_status"]
            
            # 状态映射：PENDING/RUNNING -> processing, SUCCEEDED -> success, FAILED -> failed
            if status in ["PENDING", "RUNNING"]:
                return {"success": True, "status": "processing"}
            elif status == "SUCCEEDED":
                return {
                    "success": True,
                    "status": "success",
                    "video_url": result["output"]["video_url"],
                }
            elif status == "FAILED":
                error_msg = result["output"].get("message", "任务失败")
                return {
                    "success": True,
                    "status": "failed",
                    "error": error_msg,
                }
            else:
                return {
                    "success": False,
                    "error": f"未知状态: {status}"
                }
                
        except Exception as e:
            return self._handle_unexpected_error(e, traceback.format_exc())

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """验证提交任务响应格式"""
        if not isinstance(result, dict):
            return False, f"响应不是字典类型: {type(result)}"
        
        if "error" in result:
            return True, None  # 有错误字段，格式有效但业务失败
        
        if "output" not in result:
            return False, f"缺少 output 字段: {list(result.keys())}"
        
        output = result["output"]
        if "task_id" not in output:
            return False, f"output 缺少 task_id: {list(output.keys())}"
        
        return True, None

    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """验证状态查询响应格式"""
        if not isinstance(result, dict):
            return False, f"响应不是字典类型: {type(result)}"
        
        if "output" not in result:
            return False, f"缺少 output 字段: {list(result.keys())}"
        
        output = result["output"]
        if "task_status" not in output:
            return False, f"output 缺少 task_status: {list(output.keys())}"
        
        return True, None

    def _upload_image_to_cdn(self, image_path: str) -> str:
        """上传图片到 CDN 并返回 URL"""
        cdn_urls = upload_local_images_to_cdn_sync([image_path])
        if not cdn_urls or not cdn_urls[0]:
            raise ValueError(f"图片上传失败: {image_path}")
        return cdn_urls[0]

    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        """发送 Sentry 报警"""
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context
        )
```

**关键实现要点**：
1. **继承 `BaseVideoDriver`** - 必须实现 `submit_task` 和 `check_status` 方法
2. **配置加载** - 使用 `get_dynamic_config_value` 支持热更新
3. **参数验证** - 使用 `_validate_required` 检查必需配置
4. **响应验证** - 实现 `_validate_submit_response` 和 `_validate_status_response`
5. **错误处理** - 区分网络错误、超时错误、业务错误和系统错误
6. **日志记录** - 使用 `self.logger` 记录关键操作
7. **报警机制** - 使用 `SentryUtil` 上报系统级错误

### 第三步：注册驱动到工厂

**文件**：`task/visual_drivers/driver_factory.py`

在文件末尾的注册区域添加新驱动的注册代码：

```python
# 在 driver_factory.py 的注册区域（约 600 行之后）

try:
    from .happy_horse_bailian_i2v_v1_driver import HappyHorseBailianI2vV1Driver
    # 注册 Happy Horse 图生视频驱动
    VideoDriverFactory.register_driver(
        DriverImplementation.HAPPY_HORSE_BAILIAN_I2V_V1, 
        HappyHorseBailianI2vV1Driver
    )
except ImportError as e:
    logger.warning(f"Failed to import HappyHorseBailianI2vV1Driver: {e}")
```

**注意事项**：
- 使用 try-except 包裹，避免单个驱动导入失败影响整个系统
- 驱动名称必须与 `DriverImplementation` 中定义的常量一致
- 按供应商或功能分组注册，便于维护

### 第四步：配置文件与热更新

新增视频驱动后，需要在配置文件和热更新定义中添加对应的配置项，以便管理员通过后台配置 API Key 等参数。

#### 4.1 添加示例配置

**文件**：`config.example.yml` 和 `config_prod.base.yaml`

在配置文件中添加新供应商的配置段：

```yaml
# 阿里云百炼配置
bailian:
  api_key: ""                    # 必填，阿里云百炼 API Key
  base_url: "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/generation"  # 可选
```

#### 4.2 添加热更新配置

**文件**：`config/default_configs.py`

在 `DEFAULT_CONFIGS` 列表中添加热更新配置项：

```python
# ==================== 阿里云百炼配置 ====================
{
    'key': 'bailian.api_key',
    'value_type': 'string',
    'description': '阿里云百炼 API Key',
    'editable': True,
    'is_sensitive': True,
    'quick_config': True
},
{
    'key': 'bailian.base_url',
    'value_type': 'string',
    'description': '阿里云百炼 API 基础URL（默认 https://dashscope.aliyuncs.com/...）',
    'editable': True,
    'is_sensitive': False,
    'quick_config': False
},
```

**配置说明**：
- `quick_config: True` - 配置项出现在管理后台的快速配置弹窗中
- `is_sensitive: True` - 敏感信息，日志中会脱敏显示
- `editable: True` - 允许管理员修改

#### 4.3 添加供应商常量（如需要）

**文件**：`config/unified_config.py`

如果是新供应商，需要在 `TaskProvider` 类中添加常量：

```python
class TaskProvider:
    """任务供应商常量"""
    DUOMI = 'duomi'
    RUNNINGHUB = 'runninghub'
    VIDU = 'vidu'
    VOLCENGINE = 'volcengine'
    BAILIAN = 'bailian'  # 新增：阿里云百炼
    # ...
```

### 第五步：编写单元测试

**文件**：`tests/base/test_{driver_name}_driver.py`

创建驱动的单元测试文件：

```python
"""
Happy Horse 阿里云百炼驱动单元测试
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from task.visual_drivers.happy_horse_bailian_i2v_v1_driver import HappyHorseBailianI2vV1Driver


class TestHappyHorseBailianI2vV1Driver:
    """Happy Horse 图生视频驱动测试"""

    @pytest.fixture
    def driver(self):
        """创建驱动实例"""
        with patch('task.visual_drivers.happy_horse_bailian_i2v_v1_driver.get_dynamic_config_value') as mock_config:
            # Mock 配置值
            def config_side_effect(section, key, default=None):
                config_map = {
                    ('bailian', 'api_key'): 'test_api_key_123',
                    ('bailian', 'base_url'): 'https://test.api.com',
                    ('timeout', 'request_timeout'): 30,
                }
                return config_map.get((section, key), default)
            
            mock_config.side_effect = config_side_effect
            driver = HappyHorseBailianI2vV1Driver()
            return driver

    @pytest.fixture
    def mock_ai_tool(self):
        """创建 Mock AITool 对象"""
        ai_tool = Mock()
        ai_tool.prompt = "一只可爱的猫咪在草地上奔跑"
        ai_tool.image_path = "/path/to/image.jpg"
        ai_tool.duration = 5
        ai_tool.ratio = "16:9"
        return ai_tool

    def test_submit_task_success(self, driver, mock_ai_tool):
        """测试成功提交任务"""
        with patch('task.visual_drivers.happy_horse_bailian_i2v_v1_driver.upload_local_images_to_cdn_sync') as mock_upload, \
             patch('task.visual_drivers.happy_horse_bailian_i2v_v1_driver.requests.post') as mock_post:
            
            # Mock CDN 上传
            mock_upload.return_value = ['https://cdn.example.com/image.jpg']
            
            # Mock API 响应
            mock_response = Mock()
            mock_response.json.return_value = {
                "output": {
                    "task_id": "task_123456",
                    "task_status": "PENDING"
                }
            }
            mock_post.return_value = mock_response
            
            # 执行测试
            result = driver.submit_task(mock_ai_tool)
            
            # 验证结果
            assert result["success"] is True
            assert result["task_id"] == "task_123456"
            assert result["status"] == "PENDING"
            
            # 验证 API 调用
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[1]["json"]["model"] == "happy-horse-v1"
            assert call_args[1]["json"]["input"]["prompt"] == mock_ai_tool.prompt

    def test_submit_task_api_error(self, driver, mock_ai_tool):
        """测试 API 返回错误"""
        with patch('task.visual_drivers.happy_horse_bailian_i2v_v1_driver.upload_local_images_to_cdn_sync') as mock_upload, \
             patch('task.visual_drivers.happy_horse_bailian_i2v_v1_driver.requests.post') as mock_post:
            
            mock_upload.return_value = ['https://cdn.example.com/image.jpg']
            
            # Mock API 错误响应
            mock_response = Mock()
            mock_response.json.return_value = {
                "error": {
                    "code": "InvalidParameter",
                    "message": "参数错误"
                }
            }
            mock_post.return_value = mock_response
            
            result = driver.submit_task(mock_ai_tool)
            
            assert result["success"] is False
            assert "参数错误" in result["user_message"]

    def test_check_status_success(self, driver):
        """测试查询任务状态 - 成功"""
        with patch('task.visual_drivers.happy_horse_bailian_i2v_v1_driver.requests.get') as mock_get:
            # Mock 成功响应
            mock_response = Mock()
            mock_response.json.return_value = {
                "output": {
                    "task_status": "SUCCEEDED",
                    "video_url": "https://cdn.example.com/video.mp4"
                }
            }
            mock_get.return_value = mock_response
            
            result = driver.check_status("task_123456")
            
            assert result["success"] is True
            assert result["status"] == "success"
            assert result["video_url"] == "https://cdn.example.com/video.mp4"

    def test_check_status_processing(self, driver):
        """测试查询任务状态 - 处理中"""
        with patch('task.visual_drivers.happy_horse_bailian_i2v_v1_driver.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "output": {
                    "task_status": "RUNNING"
                }
            }
            mock_get.return_value = mock_response
            
            result = driver.check_status("task_123456")
            
            assert result["success"] is True
            assert result["status"] == "processing"

    def test_check_status_failed(self, driver):
        """测试查询任务状态 - 失败"""
        with patch('task.visual_drivers.happy_horse_bailian_i2v_v1_driver.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "output": {
                    "task_status": "FAILED",
                    "message": "生成失败"
                }
            }
            mock_get.return_value = mock_response
            
            result = driver.check_status("task_123456")
            
            assert result["success"] is True
            assert result["status"] == "failed"
            assert "生成失败" in result["error"]

    def test_validate_submit_response(self, driver):
        """测试响应格式验证"""
        # 正确格式
        valid_response = {
            "output": {
                "task_id": "123",
                "task_status": "PENDING"
            }
        }
        is_valid, error = driver._validate_submit_response(valid_response)
        assert is_valid is True
        assert error is None
        
        # 错误格式 - 缺少 output
        invalid_response = {"task_id": "123"}
        is_valid, error = driver._validate_submit_response(invalid_response)
        assert is_valid is False
        assert "output" in error
        
        # 业务错误（格式有效）
        error_response = {
            "error": {
                "code": "InvalidParameter",
                "message": "参数错误"
            }
        }
        is_valid, error = driver._validate_submit_response(error_response)
        assert is_valid is True  # 格式有效，但业务失败
```

**测试要点**：
1. **Mock 配置** - 使用 `patch` Mock 配置读取
2. **Mock 外部依赖** - Mock HTTP 请求、CDN 上传等
3. **覆盖关键场景** - 成功、失败、超时、异常等
4. **验证响应格式** - 测试响应验证逻辑
5. **验证 API 调用** - 检查请求参数是否正确

**运行测试**：
```bash
pytest tests/base/test_happy_horse_bailian_i2v_v1_driver.py -v
```

### 第六步：更新文档（可选）

如果驱动有特殊说明或使用注意事项，可以更新 `task/visual_drivers/README.md`：

```markdown
## 支持的驱动列表

### 阿里云百炼
- **happy_horse_bailian_i2v_v1** - Happy Horse 图生视频 ✅
- **happy_horse_bailian_r2v_v1** - Happy Horse 参考生视频 ✅
- **happy_horse_bailian_t2v_v1** - Happy Horse 文生视频 ✅

**配置要求**：
- `bailian.api_key` - 必填，阿里云百炼 API Key
- `bailian.base_url` - 可选，默认使用官方 API 地址

**获取 API Key**：访问 [阿里云百炼控制台](https://bailian.console.aliyun.com/)
```

## 检查清单

完成新增视频驱动后，按顺序确认以下事项：

### 第一步：常量和配置
- [ ] `config/unified_config.py` - 已在 `DriverImplementation` 中添加驱动实现常量
- [ ] `config/unified_config.py` - 已在 `DriverImplementationId` 中添加对应 ID
- [ ] `config/unified_config.py` - 已在 `ALL_TASK_CONFIGS` 中添加任务配置
- [ ] `config/unified_config.py` - 已在 `TaskProvider` 中添加供应商常量（如需要）

### 第二步：驱动实现
- [ ] `task/visual_drivers/{driver}_driver.py` - 已创建驱动文件
- [ ] 驱动类已继承 `BaseVideoDriver`
- [ ] 已实现 `submit_task` 方法
- [ ] 已实现 `check_status` 方法
- [ ] 已实现 `_validate_submit_response` 方法
- [ ] 已实现 `_validate_status_response` 方法
- [ ] 已添加完整的错误处理（超时、网络、业务、系统错误）
- [ ] 已添加 Sentry 报警机制

### 第三步：驱动注册
- [ ] `task/visual_drivers/driver_factory.py` - 已导入驱动类
- [ ] `task/visual_drivers/driver_factory.py` - 已调用 `register_driver` 注册
- [ ] 使用 try-except 包裹导入和注册代码

### 第四步：配置文件
- [ ] `config.example.yml` - 已添加供应商配置段
- [ ] `config_prod.base.yaml` - 已添加供应商配置段（与 example 一致）
- [ ] `config/default_configs.py` - 已添加热更新配置项（api_key 等）

### 第五步：单元测试
- [ ] `tests/base/test_{driver}_driver.py` - 已创建测试文件
- [ ] 已测试 `submit_task` 成功场景
- [ ] 已测试 `submit_task` 失败场景（API 错误、网络错误）
- [ ] 已测试 `check_status` 各种状态（processing、success、failed）
- [ ] 已测试响应格式验证逻辑
- [ ] 所有测试通过

### 第六步：文档更新（可选）
- [ ] `task/visual_drivers/README.md` - 已添加驱动说明
- [ ] 已说明配置要求和获取方式

## 常见问题

### Q1: 如何确定任务类型 ID（driver_type）？

**A**: 任务类型 ID 对应数据库 `ai_tools` 表的 `type` 字段。查询现有 ID：

```sql
SELECT type, name FROM ai_tools ORDER BY type;
```

选择一个未使用的 ID（建议从 30 开始递增）。

### Q2: 算力配置如何计算？

**A**: 算力配置基于成本和时长：

- **固定算力**：不区分时长，如 `default_computing_power=10`
- **按时长计费**：字典格式，如 `{5: 10, 10: 20}` 表示 5 秒消耗 10 点算力，10 秒消耗 20 点

**计算公式**：
```
算力 = (API 成本 / 0.04元) × 利润率 (一般1.1)
```

例如：API 成本 0.4 元，利润率 1.1，则算力 = ceil(0.4 / 0.04 * 1.1) = 11 点

### Q3: 如何区分用户错误和系统错误？

**A**: 错误分类原则：

- **用户错误**：参数错误、余额不足、内容违规等 → 返回 `user_message`，不发送 Sentry 报警
- **系统错误**：API 格式异常、网络超时、未预期异常等 → 发送 Sentry 报警

示例：
```python
# 用户错误
if "InvalidParameter" in error_code:
    return {
        "success": False,
        "error": f"参数错误: {error_msg}",
        "user_message": "请检查输入参数是否正确"
    }

# 系统错误
if not is_valid_format:
    self._send_alert("INVALID_RESPONSE", "API 响应格式异常", {"response": result})
    return {
        "success": False,
        "error": "API 响应格式异常",
        "user_message": "服务暂时不可用，请稍后重试"
    }
```

### Q4: 如何支持多种图片输入模式？

**A**: 在任务配置中指定 `image_modes`：

```python
UnifiedTaskConfig(
    # ...
    image_modes=[
        ImageMode.FIRST_LAST_FRAME,      # 首尾帧模式
        ImageMode.MULTI_REFERENCE,       # 多参考图模式
        ImageMode.FIRST_LAST_WITH_REF,   # 首尾帧+参考图模式
    ],
)
```

驱动实现中根据 `ai_tool.image_mode` 判断：

```python
def submit_task(self, ai_tool):
    if ai_tool.image_mode == ImageMode.FIRST_LAST_FRAME:
        # 处理首尾帧模式
        first_frame = ai_tool.image_path
        last_frame = ai_tool.image_path_2
    elif ai_tool.image_mode == ImageMode.MULTI_REFERENCE:
        # 处理多参考图模式
        reference_images = [ai_tool.image_path, ai_tool.image_path_2, ...]
```

### Q5: 如何实现同步 API 驱动？

**A**: 对于同步阻塞的 API（如某些本地模型），需要：

1. 在 `ImplementationConfig` 中设置 `sync_mode=True`
2. 系统会自动将同步驱动放入独立进程池处理，避免阻塞异步事件循环

```python
ImplementationConfig(
    name="local_model_v1",
    # ...
    sync_mode=True,  # 标记为同步模式
)
```

### Q6: 如何测试驱动是否正常工作？

**A**: 三种测试方法：

1. **单元测试**：
   ```bash
   pytest tests/base/test_{driver}_driver.py -v
   ```

2. **集成测试**：通过 API 提交真实任务
   ```bash
   curl -X POST http://localhost:8000/api/ai-tools/submit \
     -H "Content-Type: application/json" \
     -d '{"type": 30, "prompt": "测试", "image_path": "/path/to/image.jpg"}'
   ```

3. **工厂测试**：验证驱动是否正确注册
   ```python
   from task.visual_drivers.driver_factory import VideoDriverFactory
   driver = VideoDriverFactory.create_driver_by_type(30)
   assert driver is not None
   ```

## 注意事项

### 1. 配置键命名规范

- 使用小写字母和下划线：`bailian.api_key`
- 分层结构：`{vendor}.{key}`
- 避免使用中文或特殊字符

### 2. 驱动命名规范

- 格式：`{model}_{provider}_{version}_driver.py`
- 示例：`happy_horse_bailian_i2v_v1_driver.py`
- 类名：驼峰命名，如 `HappyHorseBailianI2vV1Driver`

### 3. 错误处理最佳实践

```python
try:
    # API 调用
    response = requests.post(url, json=data, timeout=self._timeout)
    result = response.json()
    
except requests.exceptions.Timeout:
    return self._handle_timeout_error()
    
except requests.exceptions.RequestException as e:
    return self._handle_network_error(e)
    
except Exception as e:
    return self._handle_unexpected_error(e, traceback.format_exc())
```

### 4. 响应格式验证

**必须验证**：
- 响应是否为字典类型
- 必需字段是否存在（task_id、status 等）
- 字段类型是否正确

**目的**：
- 及时发现 API 变更
- 通过 Sentry 报警通知开发者
- 避免下游代码异常

### 5. CDN 上传注意事项

```python
# 同步上传（阻塞）
cdn_urls = upload_local_images_to_cdn_sync([image_path])

# 异步上传（非阻塞）
cdn_urls = await upload_local_images_to_cdn_async([image_path])
```

**选择原则**：
- 驱动的 `submit_task` 方法是同步的 → 使用 `sync` 版本
- 如果驱动标记为 `sync_mode=True` → 可以使用阻塞调用

### 6. 日志记录规范

```python
# 关键操作
self.logger.info(f"[{self.driver_name}] 提交任务: task_id={task_id}")

# 调试信息
self.logger.debug(f"[{self.driver_name}] 请求参数: {request_data}")

# 错误信息
self.logger.error(f"[{self.driver_name}] API 错误: {error_msg}")
```

### 7. 兼容性考虑

- **向后兼容**：修改驱动时不要破坏现有 API 接口
- **版本管理**：重大变更时创建新版本驱动（如 `_v2`）
- **优雅降级**：配置缺失时提供友好提示，而非直接崩溃

## 总结

新增视频驱动的核心步骤：

1. **定义常量** → `unified_config.py` 中添加驱动实现和任务配置
2. **实现驱动** → 继承 `BaseVideoDriver`，实现 `submit_task` 和 `check_status`
3. **注册驱动** → 在 `driver_factory.py` 中注册
4. **配置文件** → 添加热更新配置和示例配置（如需要新配置键）
5. **单元测试** → 编写完整的测试用例
6. **文档更新** → 更新 README 和使用说明（可选）

**关键原则**：
- ✅ 统一接口，便于维护
- ✅ 完整错误处理，区分用户错误和系统错误
- ✅ 响应格式验证，及时发现 API 变更
- ✅ 单元测试覆盖，保证代码质量
- ✅ 配置热更新，无需重启服务
