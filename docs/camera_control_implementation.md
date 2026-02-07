# 相机控制功能实现文档

## 功能概述

为**图片节点**添加了 Yaw/Dolly/Pitch 三维相机参数控制，并将参数转换为自然语言提示词，用于控制 Gemini (Nano Banana) 图片生成时的视角构图。

## 实现的功能

### 1. 相机参数控制
- **Yaw (左右旋转)**: -90° ~ +90°，默认 0°（正面）
  - 负值：相机在左侧拍摄
  - 0°：正面拍摄
  - 正值：相机在右侧拍摄
- **Dolly (镜头距离)**: 0 ~ 10，默认 0
- **Pitch (垂直角度)**: -60° ~ +60°，默认 0°（平视）

### 2. UI 组件
- **折叠式设计**: 默认隐藏详细参数，点击"展开"按钮显示，节省节点空间
- 每个参数包含：标签、实时数值显示、滑块、数值输入框、重置按钮
- 3D 预览 Canvas：实时显示相机位置和视角方向
- 滑块与数值输入框双向同步

### 3. 提示词转换

#### Yaw 映射（环绕视角 - Subject-Centric）
*注：系统采用环绕相机逻辑。相机向右移动 (+Yaw) 意味着看到主体的左侧面（即主体面向左）；相机向左移动 (-Yaw) 意味着看到主体的右侧面（即主体面向右）。*

- **> 75° (极右)**: "正侧面轮廓视图，人物面朝左 (Profile View, Facing Left)"
- **45° ~ 75° (右侧)**: "侧面视图，人物面朝左 (Side View, Facing Left)"
- **5° ~ 45° (微右)**: "四分之三侧面视图，人物面朝左 (3/4 View, Facing Left)"
- **-5° ~ 5° (正面)**: "正面视图 (Front View)"
- **-5° ~ -45° (微左)**: "四分之三侧面视图，人物面朝右 (3/4 View, Facing Right)"
- **-45° ~ -75° (左侧)**: "侧面视图，人物面朝右 (Side View, Facing Right)"
- **< -75° (极左)**: "正侧面轮廓视图，人物面朝右 (Profile View, Facing Right)"

#### Dolly 映射（景别）
- **0 ~ 2**: "极远景 (Extreme Long Shot)"
- **2 ~ 4**: "远景 (Long Shot)"
- **4 ~ 6**: "中景 (Medium Shot)"
- **6 ~ 8**: "近景 (Close-up)"
- **8 ~ 10**: "特写 (Extreme Close-up)"

#### Pitch 映射（拍摄角度）
- **≤ -45°**: "极低角度仰视，蚂蚁视角 (Extreme Low Angle, Worm's-eye view, Looking up)"
- **-45° ~ -25°**: "低角度仰视，从下方拍摄 (Low Angle, Looking up from below)"
- **-25° ~ -10°**: "略微仰视 (Slight Low Angle, Camera slightly below eye level)"
- **-10° ~ 10°**: "水平视线 (Eye Level Shot)"
- **10° ~ 25°**: "略微俯视 (Slight High Angle, Camera slightly above eye level)"
- **25° ~ 45°**: "高角度俯视，从上方拍摄 (High Angle, Looking down from above)"
- **≥ 45°**: "极高角度俯视，上帝视角 (Extreme High Angle, Overhead View, Bird's-eye view)"

## 修改的文件

1. **新建**: `web/js/camera_3d_preview.js` - 3D 预览模块（中文标签）
2. **修改**: `web/js/nodes.js` - 在图片节点添加相机控制 UI、事件绑定、数据保存
3. **修改**: `web/js/shot_frame_generator.js` - 提示词转换和集成（从连接的图片节点读取相机参数）
4. **修改**: `web/css/video_workflow.css` - 相机控制样式
5. **修改**: `web/video_workflow.html` - 引入 camera_3d_preview.js

## 数据结构

在**图片节点**的 data 对象中新增 camera 字段：

```javascript
{
  type: 'image',
  data: {
    url: '...',
    prompt: '...',
    // ... 其他字段
    camera: {
      yaw: 0,      // 默认正面
      dolly: 0,    // 默认极远景(0) -> 实际逻辑中建议根据需求调整默认值
      pitch: 0,    // 默认水平视线
      modified: {  // 跟踪哪些参数被用户修改过
        yaw: false,
        dolly: false,
        pitch: false
      }
    }
  }
}
```

## 使用方法

1. 创建分镜节点和图片节点
2. 将分镜节点连接到图片节点（分镜 → 图片）
3. 在**图片节点**中找到"相机控制"区域（在"图片比例"字段下方）
4. 调整 Yaw/Dolly/Pitch 参数，实时查看 3D 预览（显示中文标签："左右"和"俯仰"）
5. 点击分镜节点的"生成分镜"按钮，系统会自动读取连接的图片节点的相机参数并转换为提示词

## 提示词示例

**输入参数**: Yaw=-60°, Dolly=0, Pitch=0°  
**生成提示词**: "视角描述：侧面视图，人物面朝右 (Side View, Facing Right)，极远景 (Extreme Long Shot)，水平视线 (Eye Level)"

**输入参数**: Yaw=0°, Dolly=8, Pitch=0°  
**生成提示词**: "视角描述：正面视图 (Front View)，特写 (Extreme Close-up)，水平视线 (Eye Level)"

**输入参数**: Yaw=45°, Dolly=5, Pitch=-40°  
**生成提示词**: "视角描述：四分之三侧面视图，人物面朝左 (3/4 View, Facing Left)，中景 (Medium Shot)，高角度俯视 (High Angle)"

## 注意事项

1. **相机控制在图片节点中**，而非分镜组节点
2. 相机参数会自动保存到工作流中
3. 重新加载工作流时会正确复原参数
4. 3D 预览使用中文标签（"左右"、"俯仰"），仅用于理解方向，不保证几何精确
5. 提示词会附加在图片提示词末尾，格式为 `\n\n视角描述：...`
6. **Yaw 逻辑已修正为环绕模式**：正值=相机右移=人物面左，负值=相机左移=人物面右
7. 默认值全部为 0
8. **只有被用户修改过的参数才会生成提示词**：系统通过 `modified` 标记跟踪用户是否调整过某个参数
9. **重置按钮会清除 modified 标记**：点击参数旁的重置按钮不仅会将参数值恢复为 0，还会清除该参数的修改标记，使其不再生成提示词
10. **即使没有填写提示词，只要有相机参数修改也可以点击"编辑图片"按钮**：系统会自动使用相机参数生成视角描述作为提示词
