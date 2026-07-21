# 分镜候选区本地上传

## 功能范围

`storyboard.html` 右侧候选区支持从本地补充分镜图和视频：

- “分镜图候选”底部提供“上传分镜图”，支持 JPG、JPEG、PNG、GIF、WebP。
- “视频候选”底部提供“上传视频”，支持 MP4、WebM。
- 上传成功后，新资产会进入原分镜对应的候选列表并自动选中，主预览与时间轴同步更新。
- 视频候选使用视频自身约 0.1 秒处的画面作为缩略图；仅当资产明确返回该视频对应的
  `poster_url`/`thumbnail_url` 时才使用封面，禁止用当前分镜首帧代替视频缩略图。
- 上传状态按“分镜 ID + 资产类型”隔离；上传过程中切换分镜不会把结果写到其他分镜。
- 图片和视频生成任务运行期间仍可手工上传，最后一次明确选择的资产作为当前选中项。

## 接口

复用 `POST /api/storyboard/scene/{scene_id}/asset/upload`，表单字段如下：

| 字段 | 说明 |
| --- | --- |
| `file` | 本地图片或视频文件 |
| `asset_type` | `first_frame`、`last_frame` 或 `video` |
| `set_selected` | 是否在创建资产后设为选中，候选区上传传 `true` |

上传文件保存在 `upload/storyboard/{asset_type}/`，并创建无 `ai_tool_id` 的
`storyboard_scene_asset` 记录，因此无需修改数据库表结构。

接口保存并返回 `/upload/storyboard/...` 同源相对地址，不能拼接配置中的
`server.host`。这样用户通过域名、局域网地址或反向代理打开故事板时，浏览器仍会从
当前服务加载候选媒体，而不会错误访问用户本机的 `localhost`。候选列表读取时也会把
历史手工上传记录中的 `localhost`、`127.0.0.1`、`0.0.0.0` 地址转换为同源地址。

## 校验与配置

- 图片大小读取动态配置 `upload.max_image_size_mb`，默认 20 MB。
- 视频大小读取动态配置 `upload.max_video_size_mb`，默认 50 MB。
- 视频时长读取动态配置 `upload.max_video_duration_seconds`，默认 15 秒；配置为不大于 0 时不限制时长。
- 上传采用 1 MB 分块限额复制，不会把整个视频一次性读入接口进程内存。
- 视频落盘后通过媒体探测确认宽高和时长；无效视频、超限文件或数据库登记失败时会清理已写入的文件。
- 文件系统和数据库同步操作均通过工作线程执行，视频媒体探测使用异步子进程，不阻塞 Web 事件循环。

## 删除候选

分镜图和视频候选卡片右上角提供删除按钮。按钮点击会阻止候选选中和视频播放事件，
确认后调用：

```text
DELETE /api/storyboard/scene/{scene_id}/asset/{asset_id}
```

删除规则：

- 非当前选中候选删除后，当前选中项保持不变。
- 删除当前选中候选时，后端在同一短事务内选择该类型最新的可用完成候选作为回退项。
- 没有可用回退项时，对应的 `selected_first_frame_id`、`selected_last_frame_id` 或
  `selected_video_id` 置空；删除最后一个选中视频后，前端预览回到分镜图。
- 生成中的候选返回 `409 asset_task_running`，避免任务完成回写已删除关联。
- 删除资产关联不删除 `ai_tools` 任务记录，也不触发算力退款；宫格生成等共享任务不会被破坏。
- 仅手工上传、无 CDN mapping、没有其他资产引用且位于
  `upload/storyboard/{asset_type}/` 目录内的本地文件会在事务提交后清理。
- 文件清理属于 best-effort：清理失败记录日志，但不回滚已经成功的数据库删除。
- 候选选中接口与删除接口统一采用“先锁分镜、再校验资产、再更新”的锁顺序，避免并发
  选择在删除提交后把已删除 asset id 写回 `selected_*_id`。
