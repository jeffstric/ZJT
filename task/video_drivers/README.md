# 视频生成驱动架构

## 概述

此模块提供了一个基于抽象基类的视频生成驱动架构，所有视频生成驱动都继承自 `BaseVideoDriver`，通过工厂模式统一管理和调用。

## 架构优势

1. **统一接口**：所有模型都实现相同的接口，便于统一调用
2. **易于扩展**：新增模型只需继承基类并实现抽象方法
3. **代码解耦**：每个模型独立实现，互不影响
4. **易于维护**：模型逻辑集中在各自的类中，便于定位和修改问题
5. **类型安全**：通过工厂模式统一创建，避免类型错误

## 目录结构

```
task/video_drivers/
├── __init__.py                 # 模块导出
├── README.md                   # 本文档
├── base_video_model.py         # 抽象基类
├── model_factory.py            # 模型工厂类
├── sora2_model.py             # Sora2 模型实现（示例）
├── ltx2_model.py              # LTX2 模型实现（待实现）
├── wan22_model.py             # Wan2.2 模型实现（待实现）
├── kling_model.py             # 可灵模型实现（待实现）
├── vidu_model.py              # Vidu 模型实现（待实现）
├── veo3_model.py              # VEO3 模型实现（待实现）
├── digital_human_model.py     # 数字人模型实现（待实现）
└── gemini_image_edit_model.py # Gemini 图片编辑模型实现（待实现）
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

负责创建和管理所有驱动实例。

**主要方法：**

- `register_model(model_name, model_class)`: 注册驱动类
- `create_model_by_type(model_type)`: 根据类型创建模型
- `create_model_by_name(model_name)`: 根据名称创建模型
- `get_supported_types()`: 获取支持的类型列表
- `is_type_supported(model_type)`: 检查类型是否支持

## 使用方法

### 1. 应用启动时注册所有模型

```python
from task.video_drivers import register_all_drivers

# 在应用启动时调用
register_all_drivers()
```

### 2. 在任务处理中使用

```python
from task.video_drivers import VideoDriverFactory

def _submit_new_task(ai_tool):
    """提交新任务"""
    # 根据 ai_tool.type 创建对应的驱动实例
    model = VideoDriverFactory.create_model_by_type(ai_tool.type)
    
    if not model:
        logger.error(f"Unsupported model type: {ai_tool.type}")
        return False
    
    # 验证参数
    is_valid, error = model.validate_parameters(ai_tool)
    if not is_valid:
        logger.error(f"Invalid parameters: {error}")
        return False
    
    # 提交任务
    result = model.submit_task(ai_tool)
    
    if not result.get("success"):
        error = result.get("error", "Unknown error")
        
        # 处理需要重试的情况
        if result.get("retry"):
            delay_seconds = result.get("delay_seconds", 60)
            # 设置延迟重试
            return True
        
        logger.error(f"Task submission failed: {error}")
        return False
    
    # 更新数据库
    project_id = result.get("project_id")
    AIToolsModel.update(ai_tool.id, project_id=project_id, status=AI_TOOL_STATUS_PROCESSING)
    
    return True

def _check_task_status(ai_tool):
    """检查任务状态"""
    model = VideoDriverFactory.create_model_by_type(ai_tool.type)
    
    if not model:
        return False
    
    # 检查状态
    result = model.check_status(ai_tool.project_id)
    
    status = result.get("status")
    
    if status == "SUCCESS":
        result_url = result.get("result_url")
        AIToolsModel.update_by_project_id(
            project_id=ai_tool.project_id,
            result_url=result_url,
            status=AI_TOOL_STATUS_COMPLETED
        )
        return True
    elif status == "FAILED":
        error = result.get("error", "Unknown error")
        AIToolsModel.update_by_project_id(
            project_id=ai_tool.project_id,
            status=AI_TOOL_STATUS_FAILED,
            message=error
        )
        return True
    else:
        # 仍在处理中
        return True
```

## 如何添加新模型

### 步骤 1: 创建驱动类文件

在 `task/video_drivers/` 目录下创建新的模型文件，例如 `ltx2_model.py`：

```python
from typing import Dict, Any
from .base_video_model import BaseVideoDriver
from runninghub_request import create_ltx2_image_to_video, check_ltx2_task_status

class LTX2VideoModel(BaseVideoDriver):
    """LTX2.0 图生视频模型"""
    
    def __init__(self):
        super().__init__(model_name="ltx2", model_type=10)
    
    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """提交 LTX2 任务"""
        try:
            result = create_ltx2_image_to_video(
                image_url=ai_tool.image_path,
                prompt=ai_tool.prompt or "",
                duration=ai_tool.duration
            )
            
            if not result.get("taskId"):
                error_msg = result.get("errorMessage") or "API调用失败"
                
                # 处理队列满错误
                if error_msg == "TASK_QUEUE_MAXED":
                    return self.handle_queue_full_error()
                
                return {
                    "success": False,
                    "error": error_msg
                }
            
            return {
                "success": True,
                "project_id": result.get("taskId")
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"LTX2 API调用失败: {str(e)}"
            }
    
    def check_status(self, project_id: str) -> Dict[str, Any]:
        """检查 LTX2 任务状态"""
        try:
            result = check_ltx2_task_status(project_id)
            status = result.get("status")
            
            if status == "SUCCESS":
                results = result.get("results", [])
                if results:
                    return {
                        "status": "SUCCESS",
                        "result_url": results[0].file_url
                    }
                else:
                    return {
                        "status": "FAILED",
                        "error": "No results returned"
                    }
            elif status == "FAILED":
                return {
                    "status": "FAILED",
                    "error": "Task failed"
                }
            else:
                return {"status": "RUNNING"}
                
        except Exception as e:
            return {
                "status": "FAILED",
                "error": f"状态查询失败: {str(e)}"
            }
```

### 步骤 2: 在工厂类中注册模型

在 `model_factory.py` 的 `register_all_drivers()` 函数中添加：

```python
from .ltx2_model import LTX2VideoModel
VideoDriverFactory.register_model("ltx2", LTX2VideoModel)
```

### 步骤 3: 测试

```python
# 测试模型创建
model = VideoDriverFactory.create_model_by_type(10)
assert model is not None
assert model.model_name == "ltx2"
```

## 驱动类型映射

| 类型 | 驱动名称 | 说明 |
|------|---------|------|
| 1 | gemini_image_edit | 图片编辑（标准版） |
| 2 | sora2_text_to_video | Sora2 文生视频 |
| 3 | sora2_image_to_video | Sora2 图生视频 |
| 7 | gemini_image_edit_pro | 图片编辑（加强版） |
| 10 | ltx2 | LTX2.0 图生视频 |
| 11 | wan22 | Wan2.2 图生视频 |
| 12 | kling | 可灵图生视频 |
| 13 | digital_human | 数字人生成 |
| 14 | vidu | Vidu 图生视频 |
| 15 | veo3 | VEO3 图生视频 |

## 注意事项

1. 所有驱动类必须继承 `BaseVideoDriver`
2. 必须实现 `submit_task` 和 `check_status` 两个抽象方法
3. 返回值格式必须符合接口定义
4. 新增模型后需要在 `model_factory.py` 中注册
5. 建议为每个模型编写单元测试
