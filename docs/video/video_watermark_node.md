# 去水印节点

## 功能

视频工作流画布「视频 → 去水印」：

1. 把一个视频节点连到去水印节点左侧输入口。
2. 时长只支持 4、5、6、7、8、9、10 秒，算力与 MiniMax H3 720P 相同（4 秒 5 算力，5 秒 6，6 秒 8，7 秒 9，8 秒 10，9 秒 11，10 秒 13）。
3. 读到源视频时长且四舍五入后落在这 7 档里时，自动选中并显示算力，仍可改。读不到时手动选。超出范围时不能提交。
4. 提示词可留空。帧率固定 24。
5. 提交成功后，右侧出现一个新的视频节点，成片地址由工作流轮询填上。

任务在模型下拉里保持隐藏。节点直接请求 `POST /api/video-watermark-remove`。

## 重载

节点类型 `video_watermark` 注册在节点表里。工作流 JSON 保存输入地址、时长、提示词和状态。刷新后节点、连线和未完成的结果视频（带 `project_id`、尚无 `url`）会按原样回来。

## 关键文件

- `web/js/video_watermark_node.js`
- `web/css/video_watermark_node.css`
- `web/video_workflow.html`：菜单项和脚本
- `web/js/events.js`：菜单、视频拖线吸附
- `docs/drivers/video_watermark_runninghub_v1_driver.md`：接口与算力
