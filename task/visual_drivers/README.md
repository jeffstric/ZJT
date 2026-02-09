# 视频生成驱动架构

## 概述

此模块提供了一个基于抽象基类的视频生成驱动架构，所有视频生成驱动都继承自 `BaseVideoDriver`，通过工厂模式和三层配置映射实现灵活的供应商切换和统一管理。

**核心特性：**
- 三层配置映射：任务类型 → 业务驱动 → 实现驱动
- 多供应商支持：多米（Duomi）、RunningHub
- 统一的错误处理和报警机制
- 完整的响应格式验证
- 网络异常自动重试

## 架构优势

1. **统一接口**：所有驱动都实现相同的接口，便于统一调用
2. **灵活配置**：通过三层映射轻松切换供应商和版本
3. **易于扩展**：新增驱动只需继承基类并实现抽象方法
4. **代码解耦**：每个驱动独立实现，互不影响
5. **易于维护**：驱动逻辑集中在各自的类中，便于定位和修改问题
6. **类型安全**：通过工厂模式统一创建，避免类型错误
7. **错误追踪**：集成 Sentry 报警，自动上报系统级错误
8. **用户友好**：区分用户错误和系统错误，提供针对性提示

## 三层映射架构

```
任务类型(type) → 业务驱动名称 → 实现驱动名称 → 驱动类实例
     ↓              ↓                ↓              ↓
     3    →  sora2_image_to_video → sora2_duomi_v1 → Sora2DuomiV1Driver()
```

**配置文件：** `config/constant.py`

1. **VIDEO_DRIVER_MAPPING**: 任务类型 → 业务驱动名称
2. **DRIVER_IMPLEMENTATION_MAPPING**: 业务驱动名称 → 实现驱动名称

**优势：** 只需修改配置文件即可切换供应商或版本，无需修改业务代码。

## 目录结构

```
task/visual_drivers/
├── __init__.py                          # 模块导出
├── README.md                            # 本文档
├── base_video_driver.py                 # 抽象基类
├── driver_factory.py                    # 驱动工厂类
│
├── 多米供应商驱动 (Duomi)
├── sora2_duomi_v1_driver.py            # Sora2 图生视频 ✅
├── kling_duomi_v1_driver.py            # Kling 图生视频 ✅
├── gemini_duomi_v1_driver.py           # Gemini 图片编辑（标准版）✅
├── gemini_pro_duomi_v1_driver.py       # Gemini 图片编辑（加强版）✅
├── veo3_duomi_v1_driver.py             # VEO3 图生视频 ✅
│
├── RunningHub 驱动
├── ltx2_runninghub_v1_driver.py        # LTX2 图生视频 ✅
├── wan22_runninghub_v1_driver.py       # Wan22 图生视频 ✅
└── digital_human_runninghub_v1_driver.py # 数字人生成 ✅
```

## 核心类说明

### 1. BaseVideoDriver（抽象基类）

所有视频生成驱动的基类，定义了统一的接口。

**必须实现的抽象方法：**

- `submit_task(ai_tool)`: 提交任务到外部API
- `check_status(project_id)`: 检查任务状态

**可选重写的方法：**

- `validate_parameters(ai_tool)`: 验证任务参数

### 2. VideoDriverFactory（工厂类）

负责创建和管理所有驱动实例，通过三层映射实现灵活的驱动选择。

**主要方法：**

- `register_driver(driver_name, driver_class)`: 注册驱动类
- `create_driver_by_type(driver_type)`: 根据类型创建驱动（三层映射）
- `get_supported_types()`: 获取支持的类型列表
- `get_supported_drivers()`: 获取已注册的驱动列表
- `is_type_supported(driver_type)`: 检查类型是否支持
- `is_driver_registered(driver_name)`: 检查驱动是否已注册

**三层映射流程：**

```python
def create_driver_by_type(driver_type):
    # 第一层：任务类型 → 业务驱动名称
    business_driver_name = VIDEO_DRIVER_MAPPING.get(driver_type)
    
    # 第二层：业务驱动名称 → 实现驱动名称
    implementation_driver_name = DRIVER_IMPLEMENTATION_MAPPING.get(business_driver_name)
    
    # 第三层：实现驱动名称 → 驱动类实例
    driver_class = _registered_drivers.get(implementation_driver_name)
    return driver_class()
```

## 使用方法

### 1. 应用启动时注册所有模型

```python
from task.visual_drivers import register_all_drivers

# 在应用启动时调用
register_all_drivers()
```

### 2. 在任务处理中使用

```python
from task.visual_drivers import VideoDriverFactory

def _submit_new_task(ai_tool):
    """提交新任务"""
    # 根据 ai_tool.type 创建对应的驱动实例
    driver = VideoDriverFactory.create_driver_by_type(ai_tool.type)
    
    if not driver:
        logger.error(f"Unsupported driver type: {ai_tool.type}")
        return False
    
    # 提交任务
    result = driver.submit_task(ai_tool)
    
    if not result.get("success"):
        error = result.get("error", "Unknown error")
        error_type = result.get("error_type", "SYSTEM")  # USER 或 SYSTEM
        
        # 处理需要重试的情况（通常是网络异常）
        if result.get("retry"):
            # 设置延迟重试
            return True
        
        # 根据错误类型处理
        if error_type == "USER":
            # 用户错误，直接返回给用户
            AIToolsModel.update(ai_tool.id, status=AI_TOOL_STATUS_FAILED, message=error)
        else:
            # 系统错误，已通过 Sentry 报警
            error_detail = result.get("error_detail", "")
            logger.error(f"System error: {error}, detail: {error_detail}")
            AIToolsModel.update(ai_tool.id, status=AI_TOOL_STATUS_FAILED, message=error)
        
        return False
    
    # 更新数据库
    project_id = result.get("project_id")
    AIToolsModel.update(ai_tool.id, project_id=project_id, status=AI_TOOL_STATUS_PROCESSING)
    
    return True

def _check_task_status(ai_tool):
    """检查任务状态"""
    driver = VideoDriverFactory.create_driver_by_type(ai_tool.type)
    
    if not driver:
        return False
    
    # 检查状态
    result = driver.check_status(ai_tool.project_id)
    
    status = result.get("status")
    
    if status == "SUCCESS":
        # 根据任务类型获取对应的 URL 字段
        video_url = result.get("video_url")
        image_url = result.get("image_url")
        result_url = video_url or image_url
        
        AIToolsModel.update_by_project_id(
            project_id=ai_tool.project_id,
            result_url=result_url,
            status=AI_TOOL_STATUS_COMPLETED,
            completed_time=datetime.now()
        )
        return True
    elif status == "FAILED":
        error = result.get("error", "Unknown error")
        error_type = result.get("error_type", "SYSTEM")
        
        AIToolsModel.update_by_project_id(
            project_id=ai_tool.project_id,
            status=AI_TOOL_STATUS_FAILED,
            message=error
        )
        return True
    else:
        # 仍在处理中 (RUNNING)
        return True
```

## 如何添加新驱动

### 步骤 1: 创建驱动类文件

在 `task/visual_drivers/` 目录下创建新的驱动文件，例如 `vidu_vendor_v1_driver.py`：

```python
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver
from vidu_api import create_vidu_video, get_vidu_status
from utils.sentry_util import SentryUtil, AlertLevel

class ViduVendorV1Driver(BaseVideoDriver):
    """Vidu 供应商 v1 版本驱动"""
    
    def __init__(self):
        super().__init__(driver_name="vidu_vendor_v1", driver_type=14)
    
    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        """发送报警信息"""
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context
        )
    
    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """验证提交响应格式"""
        # 实现响应格式验证逻辑
        if not isinstance(result, dict):
            return False, f"响应不是字典类型"
        if "task_id" not in result:
            return False, f"响应缺少 task_id 字段"
        return True, None
    
    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """验证状态响应格式"""
        # 实现响应格式验证逻辑
        return True, None
    
    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """提交 Vidu 任务"""
        try:
            # 调用外部 API
            try:
                result = create_vidu_video(
                    image_url=ai_tool.image_path,
                    prompt=ai_tool.prompt,
                    duration=ai_tool.duration
                )
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }
            
            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Vidu submit_task 响应格式错误: {validation_error}",
                    context={"api": "create_vidu_video", "response": result}
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}",
                    "retry": False
                }
            
            return {
                "success": True,
                "project_id": result.get("task_id")
            }
            
        except Exception as e:
            # 非网络异常，发送报警
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Vidu submit_task 发生未预期异常: {str(e)}",
                context={"exception": str(e), "traceback": traceback.format_exc()}
            )
            return {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}",
                "retry": False
            }
    
    def check_status(self, project_id: str) -> Dict[str, Any]:
        """检查 Vidu 任务状态"""
        try:
            # 调用外部 API
            try:
                result = get_vidu_status(task_id=project_id)
            except (ConnectionError, TimeoutError):
                return {"status": "RUNNING", "message": "网络连接异常，稍后将重试"}
            
            # 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Vidu check_status 响应格式错误: {validation_error}",
                    context={"response": result}
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM"
                }
            
            # 映射状态
            task_status = result.get("status")
            if task_status == "SUCCESS":
                return {"status": "SUCCESS", "video_url": result.get("video_url")}
            elif task_status == "FAILED":
                return {"status": "FAILED", "error": result.get("error"), "error_type": "USER"}
            else:
                return {"status": "RUNNING", "message": "任务处理中..."}
                
        except Exception as e:
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Vidu check_status 发生未预期异常: {str(e)}",
                context={"exception": str(e)}
            )
            return {"status": "FAILED", "error": "服务异常，请联系技术支持", "error_type": "SYSTEM"}
```

### 步骤 2: 更新配置文件

在 `config/constant.py` 中添加映射配置：

```python
# 在 VIDEO_DRIVER_MAPPING 中添加
VIDEO_DRIVER_MAPPING = {
    ...
    14: "vidu_image_to_video",  # 业务驱动名称
}

# 在 DRIVER_IMPLEMENTATION_MAPPING 中添加
DRIVER_IMPLEMENTATION_MAPPING = {
    ...
    "vidu_image_to_video": "vidu_vendor_v1",  # 实现驱动名称
}
```

### 步骤 3: 在工厂类中注册驱动

在 `driver_factory.py` 的 `register_all_drivers()` 函数中添加：

```python
try:
    from .vidu_vendor_v1_driver import ViduVendorV1Driver
    VideoDriverFactory.register_driver("vidu_vendor_v1", ViduVendorV1Driver)
except ImportError as e:
    logger.warning(f"Failed to import ViduVendorV1Driver: {e}")
```

### 步骤 4: 测试

```python
# 测试驱动创建
driver = VideoDriverFactory.create_driver_by_type(14)
assert driver is not None
assert driver.driver_name == "vidu_vendor_v1"
assert driver.driver_type == 14

# 测试切换供应商（只需修改配置）
# 将 DRIVER_IMPLEMENTATION_MAPPING 中的映射改为：
# "vidu_image_to_video": "vidu_vendor_v2"
# 无需修改业务代码
```

## 已实现的驱动

### 多米供应商（Duomi）

| 类型 | 业务驱动 | 实现驱动 | 驱动类 | 功能 |
|------|---------|---------|--------|------|
| 3 | sora2_image_to_video | sora2_duomi_v1 | Sora2DuomiV1Driver | 图生视频 |
| 12 | kling_image_to_video | kling_duomi_v1 | KlingDuomiV1Driver | 图生视频 |
| 1 | gemini_image_edit | gemini_duomi_v1 | GeminiDuomiV1Driver | 图片编辑（标准）|
| 7 | gemini_image_edit_pro | gemini_pro_duomi_v1 | GeminiProDuomiV1Driver | 图片编辑（加强）|
| 15 | veo3_image_to_video | veo3_duomi_v1 | Veo3DuomiV1Driver | 图生视频（8秒）|

### RunningHub

| 类型 | 业务驱动 | 实现驱动 | 驱动类 | 功能 |
|------|---------|---------|--------|------|
| 10 | ltx2_image_to_video | ltx2_runninghub_v1 | Ltx2RunninghubV1Driver | 图生视频 |
| 11 | wan22_image_to_video | wan22_runninghub_v1 | Wan22RunninghubV1Driver | 图生视频 |
| 13 | digital_human | digital_human_runninghub_v1 | DigitalHumanRunninghubV1Driver | 数字人生成 |

### 待实现

| 类型 | 业务驱动 | 说明 |
|------|---------|------|
| 14 | vidu_image_to_video | Vidu 图生视频 |
| 2 | sora2_text_to_video | Sora2 文生视频（可复用 sora2_duomi_v1）|

## 错误处理规范

### 错误类型

- **USER**: 用户错误（如参数错误、配额不足等），直接展示给用户
- **SYSTEM**: 系统错误（如 API 格式错误、未预期异常等），需要技术支持介入

### 返回值格式

**submit_task 成功：**
```python
{"success": True, "project_id": "task_123"}
```

**submit_task 失败（用户错误）：**
```python
{"success": False, "error": "图片包含真人", "error_type": "USER", "retry": False}
```

**submit_task 失败（系统错误）：**
```python
{"success": False, "error": "服务异常", "error_type": "SYSTEM", "error_detail": "API响应格式错误", "retry": False}
```

**submit_task 网络异常（需重试）：**
```python
{"success": False, "error": "网络连接异常", "error_type": "USER", "retry": True}
```

**check_status 成功：**
```python
{"status": "SUCCESS", "video_url": "https://..."}
```

**check_status 失败：**
```python
{"status": "FAILED", "error": "任务失败", "error_type": "USER"}
```

**check_status 处理中：**
```python
{"status": "RUNNING", "message": "任务处理中..."}
```

## 注意事项

1. 所有驱动类必须继承 `BaseVideoDriver`
2. 必须实现 `submit_task` 和 `check_status` 两个抽象方法
3. 必须实现 `_validate_submit_response` 和 `_validate_status_response` 验证方法
4. 返回值格式必须符合接口定义
5. 系统级错误必须通过 `_send_alert` 发送 Sentry 报警
6. 区分用户错误和系统错误，设置正确的 `error_type`
7. 网络异常应设置 `retry: True` 允许重试
8. 新增驱动后需要：
   - 更新 `config/constant.py` 配置
   - 在 `driver_factory.py` 中注册
   - 建议编写单元测试

## 切换供应商示例

假设要将 Sora2 从多米切换到其他供应商：

1. 实现新的驱动类：`sora2_vendor_b_v1_driver.py`
2. 注册驱动：`VideoDriverFactory.register_driver("sora2_vendor_b_v1", Sora2VendorBV1Driver)`
3. 修改配置：
```python
DRIVER_IMPLEMENTATION_MAPPING = {
    "sora2_image_to_video": "sora2_vendor_b_v1",  # 从 sora2_duomi_v1 改为 sora2_vendor_b_v1
}
```

**无需修改任何业务代码！**
