# 故事板分镜间插入设计

更新时间：2026-07-02

## 背景

`storyboard.html` 原本只支持在时间轴或网格末尾添加分镜。实际剪辑时，用户经常需要在两个已有分镜之间补一个过渡镜头、反应镜头或空镜，因此新增“分镜间插入”交互。

## 交互规则

- 时间轴视图：在每两个 `.scene-timeline-item` 之间渲染一个窄的插入槽，默认低存在感，鼠标悬停或键盘聚焦时显示加号。
- 网格视图：不把插入槽作为独立 grid item，避免打乱卡片排列；插入控件挂在每张卡片右侧边缘，表示“在此分镜后、下一分镜前添加”。
- 末尾仍保留原有“添加分镜”按钮。
- 点击插入槽后，新分镜自动成为当前选中分镜。

## 数据流

前端插入槽携带相邻分镜 ID：

```json
{
  "prev_id": 12,
  "next_id": 13
}
```

调用现有接口：

```text
POST /api/storyboard/{storyboard_id}/scene
```

后端按 `prev_id` / `next_id` 计算新分镜的 `sort_order`：

- 同时存在：取两个相邻 sort_order 的中点。
- 只有 `prev_id`：插到该分镜后。
- 只有 `next_id`：插到该分镜前。
- 都不存在：空故事板的第一条。

如果浮点中点精度耗尽，后端先 rebalance，再重新计算。

## 涉及文件

- `web/js/storyboard/render.js`：渲染 `renderInsertSceneSlot()`。
- `web/js/storyboard/events.js`：处理 `insert-scene`，传递 `prev_id` / `next_id`。
- `web/css/storyboard.css`：时间轴和网格插入槽样式。
- `api/storyboard.py`：`add_scene` 支持插入参数。
- `model/storyboard_scene.py`：`compute_sort_between()` 与 `rebalance()` 维护顺序。

## 验证

- `pytest tests/storyboard/test_storyboard_insert_scene_slots.py -q`
- `node --check web/js/storyboard/render.js`
- `node --check web/js/storyboard/events.js`
