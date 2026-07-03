# 生视频节点

## 功能概述

生视频节点（原"图生视频"节点）支持三种模式，通过"图片模式"选择器切换：

- **首尾帧模式（first_last_frame）**：上传首帧（和可选尾帧）图片生成视频
- **多参考图模式（multi_reference）**：上传多张参考图作为风格参考生成视频
- **文生视频（text_to_video）**：纯文本提示词生成视频，无需上传任何图片

## 模式切换

在节点左栏"图片模式"下拉框中切换。切换时自动更新：
- 图片上传区域的显示/隐藏
- 视频模型列表（根据模式过滤）
- 参考音频/视频区域的显示/隐藏

### 首尾帧模式

- 默认模式，向后兼容
- 需要上传首帧图片（或通过图片节点连接）
- 尾帧可选
- 调用 `/api/ai-app-run-image`，`image_mode=first_last_frame`
- 视频模型列表：所有 image_to_video 模型

### 多参考图模式

- 上传 1-5 张参考图作为风格参考
- 支持参考音频和参考视频
- 调用 `/api/ai-app-run-image`，`image_mode=multi_reference`
- 视频模型列表：仅支持 multi_reference 的模型

### 文生视频模式

- 无需上传任何图片，仅凭提示词生成视频
- 调用 `/api/ai-app-run`（text_to_video 端点）
- 视频模型列表：所有 text_to_video 类别的模型
- 不支持参考音频/视频

## API 调用

### 图生视频（首尾帧/多参考图）

```
POST /api/ai-app-run-image
FormData: prompt, ratio, duration_seconds, count, task_id, image_urls, image_mode, ...
```

可选字段 `resolution` 来自 `node.data.videoResolution`。未传入时后端按当前 implementation 的默认分辨率处理。

### 文生视频

```
POST /api/ai-app-run
FormData: prompt, ratio, duration_seconds, count, task_id, user_id, auth_token
```

task_id 通过 `TaskConfig.getTaskIdByKey(model, 'text_to_video')` 获取。
文生视频同样支持可选字段 `resolution`。

## 数据字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `node.data.imageMode` | `'first_last_frame'` / `'multi_reference'` / `'text_to_video'` | 图片模式 |
| `node.data.videoResolution` | `string` | 当前视频模型支持的分辨率选择值；工作流重新加载后恢复，并参与算力预估 |
| `node.data.videoUrls` | `Array<{name, url}>` | 通过上传或视频节点连线添加的参考视频列表 |

## 端口与国际化

- 生视频节点标题、图片模式标签和模式选项都通过 `video_workflow` i18n key 渲染；工作流重新加载早于 i18n 初始化时，节点 DOM 会在 `ZJTi18nDOM.scanDOM()` 后自动刷新为当前语言。
- 输出端口连接到视频节点，用于把生视频结果写入视频节点。
- 视频节点输出端口可连接到生视频节点的参考视频端口，连接成功后写入 `node.data.videoUrls`，并在重新加载工作流后恢复。

## 向后兼容

- 旧工作流无 `imageMode` 字段时，默认 `'first_last_frame'`
- 序列化/反序列化自动包含 `imageMode` 字段

## 相关文件

- `web/js/image_to_video_node.js` — createImageToVideoNode(): 节点创建、模式 UI、分辨率选择和生成逻辑
- `web/js/api.js` — generateVideoFromImage() / generateVideoFromText(): API 调用
- `web/js/workflow.js` — createImageToVideoNodeWithData(): 状态恢复
- `web/video_workflow.html` — 工具栏按钮
