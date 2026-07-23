# 图片涂色编辑功能

## 功能概述

图片涂色编辑允许用户在原图上直接画笔涂色（非 AI 生图），适用于局部改色、标记、上色等场景。

支持页面：

| 页面 | 入口 | 结果落点 |
|------|------|----------|
| 视频工作流 `video_workflow.html` | 图片节点「涂色编辑」 | 上传后替换节点 `data.url` |
| 故事板 `storyboard.html` | 主预览区「涂色编辑」（hover 显示） | 上传并新建 `first_frame` 资产候选并选中 |

## 使用方法

### 视频工作流

1. 图片节点中上传或生成图片（须等待上传完成）
2. 点击「涂色编辑」
3. 调整画笔大小 / 颜色 / 透明度后绘制
4. 确认后上传并替换节点图片

### 故事板分镜图

1. 时间轴视图选中有首帧图的分镜（主预览为图，非视频）
2. 鼠标悬停主预览，点击右上角「涂色编辑」
3. 涂色确认后：
   - 上传到 `upload/storyboard/first_frame/`
   - 新建 `storyboard_scene_asset`（`asset_type=first_frame`，无 `ai_tool_id`）
   - 设为当前选中；右侧候选列表顶部出现「涂色」条目
4. 可在候选中切回旧图（涂色 = 新增版本，不原地覆盖）

门禁：

- 当前预览必须是首帧图（`choosePreviewMedia.kind === 'image'`）
- 播放中会先停播再打开编辑器
- 无合法单 URL 时禁用

## 技术实现

### 文件结构

| 文件 | 职责 |
|------|------|
| `web/js/image_coloring_editor.js` | 通用编辑器（自注入 modal，不绑业务） |
| `web/css/image_coloring_editor.css` | 编辑器 + modal 共享样式 |
| `web/js/image_node.js` | 工作流节点集成 |
| `web/js/storyboard/first_frame_coloring.js` | 故事板适配（门禁 / 上传 / 刷 UI） |
| `web/js/storyboard/api.js` | `uploadSceneAsset` |
| `api/storyboard.py` | `POST /api/storyboard/scene/{id}/asset/upload` |

### 编辑器 API

```js
window.imageColoringEditor.init();
window.imageColoringEditor.open(imageUrl, context, (result) => {
  // result.coloredImage: dataURL
  // result.context: 调用方传入的 context（节点 id 或 { type, sceneId, ... }）
  // result.nodeId: 兼容旧签名
});
window.imageColoringEditor.close();
```

- 页面无需预埋 modal HTML：首次 `init/open` 会自注入 `#coloringEditorModal`
- 通过 fetch→blob 加载远程图，避免 canvas 跨域污染

### 故事板上传接口

```http
POST /api/storyboard/scene/{scene_id}/asset/upload
Content-Type: multipart/form-data
Authorization: Bearer ...
X-User-Id: ...

file: <image>
asset_type: first_frame   # first_frame | last_frame
set_selected: true
```

成功响应：

```json
{
  "success": true,
  "asset_id": 123,
  "result_url": "https://host/upload/storyboard/first_frame/sb_first_frame_....png",
  "asset_type": "first_frame",
  "selected": true
}
```

### 工作流程（故事板）

1. `canColorFirstFrame` 门禁
2. `imageColoringEditor.open(url, { type:'storyboard_scene', sceneId })`
3. 确认 → `dataUrlToBlob` → `uploadSceneAsset`
4. `applyColoredAssetToScene` 更新 `firstFrameUrl` / 候选
5. 分区 `rerender([PREVIEW, CANDIDATES, TIMELINE_LIST, AGENT_PANEL])`

## 测试

- `web/tests/first_frame_coloring.test.js`：门禁、dataURL 转换、state 写入
- 工作流侧上传门禁见 `web/tests/image_node_upload_gate.test.js`

## 注意事项

1. 涂色不消耗生图算力，是本地 Canvas 绘制
2. 故事板涂色结果进入资产候选体系，与 AI 出图一致可回退
3. 编辑器与业务解耦：上传路径由宿主页面决定
4. 大图上传中途不可编辑（工作流侧 `canEditImageNode` 门禁）
