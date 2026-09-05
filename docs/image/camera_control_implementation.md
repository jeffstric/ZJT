# 相机控制功能实现文档

## 功能概述

实现了独立的**相机控制节点**，支持水平角度、垂直角度、缩放距离三个维度的相机参数控制，并将参数转换为自然语言提示词，通过 runninghub 的 ComfyUI-qwenmultiangle 工作流生成多角度视角图片。

## 实现的功能

### 1. 相机参数控制
- **水平角度 (horizontal_angle)**: 0° ~ 360°，默认 0°（正面）
  - 0° / 360°：正面 (Front View)
  - 45°：右前四分之三侧面 (Front-right Quarter View)
  - 90°：右侧 (Right Side View)
  - 135°：右后四分之三侧面 (Back-right Quarter View)
  - 180°：背面 (Back View)
  - 225°：左后四分之三侧面 (Back-left Quarter View)
  - 270°：左侧 (Left Side View)
  - 315°：左前四分之三侧面 (Front-left Quarter View)
- **垂直角度 (vertical_angle)**: -30° ~ +60°，默认 0°（平视）
  - < -15°：低角度仰视 (Low-angle Shot)
  - -15° ~ 15°：水平视线 (Eye-level Shot)
  - 15° ~ 45°：抬高视角 (Elevated Shot)
  - ≥ 45°：高角度俯视 (High-angle Shot)
- **缩放距离 (zoom)**: 0 ~ 10，默认 5.0
  - < 2：远景 (Wide Shot)
  - 2 ~ 6：中景 (Medium Shot)
  - ≥ 6：特写 (Close-up)

### 2. UI 组件
- **独立节点**：相机控制作为独立节点类型 `camera_control`，通过输入端口连接图片节点获取源图
- 每个参数包含：标签、数值输入框、滑块、重置按钮
- 3D 预览 Canvas：实时显示相机位置和视角方向（中文标签："水平"和"垂直"）
- 滑块与数值输入框双向同步
- **批量生成**：支持 X1/X2/X3 抽卡次数选择
- **源图预览**：连接图片节点后自动显示源图缩略图

### 3. 提示词转换

#### 水平角度映射（0° ~ 360° 环绕视角）

- **0° ~ 22.5° 或 337.5° ~ 360°**: "front view"
- **22.5° ~ 67.5°**: "front-right quarter view"
- **67.5° ~ 112.5°**: "right side view"
- **112.5° ~ 157.5°**: "back-right quarter view"
- **157.5° ~ 202.5°**: "back view"
- **202.5° ~ 247.5°**: "back-left quarter view"
- **247.5° ~ 292.5°**: "left side view"
- **292.5° ~ 337.5°**: "front-left quarter view"

#### 垂直角度映射

- **< -15°**: "low-angle shot"
- **-15° ~ 15°**: "eye-level shot"
- **15° ~ 45°**: "elevated shot"
- **≥ 45°**: "high-angle shot"

#### 缩放距离映射

- **< 2**: "wide shot"
- **2 ~ 6**: "medium shot"
- **≥ 6**: "close-up"

#### 提示词格式

最终提示词格式为：`<sks> {水平方向} {垂直角度} {距离}`

示例：`<sks> front-right quarter view eye-level shot medium shot`

## 修改的文件

1. **新建**: `web/js/camera_control_node.js` - 相机控制节点主体（使用 `createNodeBase` 基类工厂）
2. **新建**: `web/js/camera_3d_preview.js` - 3D 预览模块（中文标签："水平"、"垂直"）
3. **修改**: `web/css/video_workflow.css` - 相机控制样式
4. **修改**: `web/video_workflow.html` - 引入相关 JS 文件

## 数据结构

相机控制节点的 data 对象：

```javascript
{
  type: 'camera_control',
  data: {
    camera: {
      horizontal_angle: 0,     // 水平角度，0~360°
      vertical_angle: 0,       // 垂直角度，-30°~60°
      zoom: 5.0,               // 缩放距离，0~10
      modified: {              // 跟踪哪些参数被用户修改过
        horizontal_angle: false,
        vertical_angle: false,
        zoom: false
      }
    },
    drawCount: 1               // 抽卡次数（1~3）
  }
}
```

## 使用方法

1. 创建图片节点并上传/生成一张图片
2. 创建相机控制节点
3. 将图片节点的**输出端口**连接到相机控制节点的**输入端口**（仅接受 `image` 类型）
4. 在相机控制节点中调整水平角度、垂直角度、缩放距离参数，实时查看 3D 预览
5. 选择抽卡次数（X1/X2/X3）
6. 点击"生成图片"按钮
7. 系统自动在相机控制节点右侧创建对应数量的新图片节点，并自动连接
8. 等待生成完成，结果图片自动填充到新图片节点中

## 生成流程

1. **验证源图片**：检查输入端口是否连接了有效的图片节点
2. **检查参数修改**：至少需要修改过一个相机参数
3. **获取任务配置**：从 TaskConfig 获取 `qwen-multi-angle` 任务的 task_id
4. **算力检查**：每个任务消耗 4 算力（QWEN_MULTI_ANGLE_IMAGE），乘以抽卡次数
5. **提交任务**：调用 `/api/image-edit` 接口，传递源图URL、提示词、相机参数、抽卡次数、比例等
6. **创建图片节点**：为每个 project_id 创建新的图片节点并建立连接
7. **轮询结果**：通过 `pollVideoStatus` 轮询任务状态，完成后更新图片节点

## API接口

- **生成接口**：`POST /api/image-edit`
  - 参数：
    - `task_id`: 多角度任务ID
    - `ref_image_urls`: 源图片URL
    - `prompt`: 生成的视角提示词
    - `extra_config`: 相机参数JSON
    - `count`: 生成数量
    - `ratio`: 图片比例
    - `user_id`: 用户ID
    - `auth_token`: 认证令牌

## 状态轮询

使用通用的 `pollTaskStatus` 函数轮询任务状态，支持以下回调：
- `onSuccess`: 生成成功，提取结果URL并更新图片节点
- `onFailed`: 生成失败，显示错误信息
- `onTimeout`: 轮询超时

## 注意事项

1. **相机控制是独立节点**，通过连接线从图片节点获取源图
2. 相机参数会自动保存到工作流中，重新加载时正确复原
3. **多角度编辑（qwen-multi-angle）的唯一提交入口是相机控制节点自身的"生成图片"按钮**（单图输入，仅作用于该节点连接的源图）。分镜节点"生成分镜图"始终使用分镜面板所选图片模型，不读取任何相机参数——即使分镜连出的图片节点上挂有相机控制节点，也不会影响分镜图生成的模型选择与 API 分支
3. 3D 预览使用中文标签（"水平"、"垂直"），仅用于理解方向，不保证几何精确
4. **只有被用户修改过的参数才会生成提示词**：系统通过 `modified` 标记跟踪
5. **重置按钮会清除 modified 标记**：点击重置按钮将参数恢复默认值并清除修改标记
6. **依赖 runninghub 配置**：需要在系统设置中配置 runninghub 密钥才能使用
7. **算力消耗**：每张图片消耗 4 算力，批量生成时按数量累加
8. 使用 `createNodeBase` 基类工厂创建，支持 `createCameraControlNodeWithData` 恢复
9. 已注册到节点注册表，支持工作流保存/加载/撤销功能
