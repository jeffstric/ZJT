# develop 相对 master 的测试缺口分析与补充（develop_test_1029，2026-10-29）

## 背景

`origin/develop`（dbaeb090，2026-10-28）领先 `origin/master`（821d599f，2026-10-22 合并）
155 个提交、269 个文件（+31257 行），覆盖资产库、导演台、视频高清修复、算力预算、
相机对话、营销轮询修复等六大功能。develop 已自带大量测试（tests/ 新增 13 个文件、
web/tests/ 新增 19 个文件），本次对剩余缺口做了系统性排查并补充。

**总范围**：除 10-22→10-28 这一周外，还回溯检查了再前 3 周（70bcc0a9..821d599f，
2026-09-30→10-22，314 commits、512 文件、+4.2 万行）的合并改动——数字人 H3 分段、
音色指纹 voice_desc、故事板↔画布互转、@ 提及胶囊化、KFRef 台词语义、SSE 假死修复、
worker 进程池 fork→spawn、槽位对账回收、admin 每日统计等。

**总体结论**：测试纪律良好——两大窗口内大部分功能与 bugfix 自带测试（后一窗口
自带 57 个新测试文件）。真正的缺口集中在：路由层接线、调度/状态机语义、数字人
服务本体、SSE 断点续传、时间轴导出链路，本次已补齐。

## 本次补充清单

### 第二批：前 3 周窗口（70bcc0a9..821d599f）的缺口

#### 后端单元测试（pytest，5 个文件，94 用例）

| 文件 | 守护点 |
|---|---|
| `tests/services/test_storyboard_digital_human_service.py`（26 例） | 数字人服务本体（此前工具执行器层全 mock，本体零测试）：TTS 时长聚合、clamp 4-10s 计费口径、分辨率→max_edge、build_plan 时长优先级（TTS 总时长→scene.duration）、orchestrate 错误码链（404/invalid_video_type/audio_required）、plan_digital_human_ready 五态映射、deduct_computing_power_sync 跳过/失败/进参、prepare 多段音频合并失败不扣费 |
| `tests/api/test_character_voice_endpoints.py`（13 例） | 角色音色三端点（4dcec8daa/9092d102b）：登录身份 401、claimed 403、DB 行属主为他人时忽略该行不泄露数据（str 对比回归）、analysis_failed→502 不吐兜底指纹、voice_description 字段回退、参考音频任务落库参数、预置音色 style/gender 三级指纹推导 |
| `tests/drivers/test_digital_human_minimax_h3_runninghub_v1_driver.py`（扩展 11 例） | H3 驱动 submit/check_status 状态机（c5d637f85 421 拥堵回队、13347a6fc 断点续跑依赖）：拥堵→retry=True/UPSTREAM_CONGESTED、普通错误 USER 不重试、网络异常保持 RUNNING、SUCCESS 从 outputs 选 mp4、响应格式异常 SYSTEM+告警 |
| `tests/services/test_window_topics_930_1022.py`（22 例） | 五个零测试改动面合集：抖音笔记解析器（TikHub 响应形状）、微信抓取 VL 识图并发化（**信号量峰值=4 断言**——串行识图曾拖爆整体超时）、sign-pay 400/503 透传不被 500 吞掉（a3dd5af7b）、剧本提取任务 TTL 判定（is_expired 边界）、admin 每日算力统计（按日分组/备注优先/日期校验/空数据） |

#### 前端测试（vitest，6 个新文件，83 用例）

| 文件 | 守护点 |
|---|---|
| `web/tests/sse_client_resume.test.js`（12 例） | SSE 断点续传（ce1b6d110 假死修复）：data:/id: 解析、done/error 收尾不重连、**空闲超时→带最新 Last-Event-ID 重连**、连接成功清零 attempts 与连接失败累计的语义区分、耗尽 throw→onError、close() 不触发 onError、Bearer 头 |
| `web/tests/timeline_export_assets.test.js`（15 例） | 时间轴柱子归属链（682f89a3e：video/image_to_video/text_to_speech/audio 五类节点沿连线/产出线/ttsNodeId/sourceNodeId 向上追溯）+ 导出素材包（94ab321c6）：blob: 片段回退节点地址、order 排序、endTime 兜底、download_url 协议校验防 open redirect、downloadWithAuth 契约 |
| `web/tests/marketing_agent_pending_card.test.js`（10 例） | 生成中进度卡片（038e05131）：i18n 模板动态正则、数字进度 width:pct 上限 100、'?' 不定进度、提交气泡后缀归类、locale 变化重建、300 字截断、裸音频 URL 内联播放器与保守前瞻（0163a57a1） |
| `web/tests/storyboard_workflow_conversion.test.js`（7 例） | 画布↔故事板互转前端侧（d957af0ed）：无 id 拦截、flushAutoSave 先行、Bearer 补全、成功跳转、失败恢复按钮、故事板侧防重入守卫 |
| `web/tests/subscription_agree_auto_qr.test.js`（12 例） | 勾选协议自动出微信二维码（85798489）：勾选即下单、五类不自动下单条件（无套餐/loading/已有码/已有单/微信内）、取消勾选仅清错误、防重复下单、recharge_center 同款守卫 |
| `web/tests/admin_daily_power_stats.test.js`（8 例） | admin 每日统计（47192efe7/27c5598e4/8f00f3d1d）：跨日按用户聚合降序、display_name 备注优先、空数据 avgPerDay=0 非 NaN、start>end 回退、days 封顶 30 |
| `web/tests/html_version_stamp.test.js`（9 例） | __VERSION__ 缓存戳守卫（e73286c1a）：机制在用 + 全部 HTML 无硬编码历史版本戳 |
| `web/tests/shot_frame_last_frame_mode.test.js`（7 例） | 尾帧档位联动（f0101b875）：首尾帧齐备→first_last_with_tail 算力档、**提交 image_mode 保持 first_last_frame 不外泄**（服务端不识别 with_tail） |

#### 端到端测试（Playwright，3 个文件扩展 + 1 个新建，8 用例）

| 文件 | 守护点 |
|---|---|
| `tests/storyboard/test_script_split_preconditions.py`（12 例，后端单测） | 前置校验（889bd923a）：短剧本/空串 script_content_insufficient、world_no_scene / world_no_scene_image、world_id 缺失跳过、create_split_task 创建前拦截（不触达 create_or_get_active）、契约快照在幂等键后注入。曾误放 auto_test/e2e（parse-script 端点流程中前置校验位于外部算力检查之后，e2e 容器内认证不可用时永远到不了该分支，CI 必失败），已移除并迁移到单元层 |
| `auto_test/e2e/test_storyboard.py`（新建 3 例，ci_smoke p0） | 互转端点守卫（d957af0ed 落库行为此前零自动化）：空/不存在画布 4xx、不存在 storyboard 404、未登录 401 |
| `auto_test/e2e/test_audio.py`（+2 例，p1） | 预置音色 ≥100 且 voice_desc 回填率>90%（no_152）、mock TTS 产物 /upload/ 下载可达（25f67a9a1 302 签名/代理） |
| `auto_test/e2e/test_script_writer_api.py`（+2 例） | 会话列表跨用户枚举不泄露（34e987ce6）、未知任务 404 自愈契约 |

### 第一批：本周窗口（821d599f..dbaeb090）的缺口

### 后端单元测试（pytest，5 个文件，55 用例）

| 文件 | 守护点 |
|---|---|
| `tests/api/test_user_power_budget_api.py` | `/api/user/power-budget` GET/PUT/DELETE 路由（796d6db2 曾在商业版漏挂的热修复回归点）：非法 limit 400 不落库、PUT/DELETE 落库与 payload 组装、未登录 401 |
| `tests/task/test_process_task_with_retry_contract.py` | 调度循环 `process_task_with_retry` 五态契约（fix 36b927be「失败任务被统计为成功」）：SUCCESS/True 计成功、FAILED 不虚增 try_count 不打假重试日志、IN_FLIGHT 不动状态、False/None 退避+try_count+1 且区分「轮询中/处理失败」文案、异常退避不崩循环 |
| `tests/storyboard/test_storyboard_camera_chat_auth_token.py`（扩展） | `scene_camera_chat` 路由 400/502 校验分支：空指令/缺机位/缺模型 400、LLM 解析失败 502、model_id/vendor_id 经 normalize 归一 |
| `tests/services/test_storyboard_agent_video_tool_count.py` | 会话级视频偏好 count（clamp 1-4）wrapper 注入（不走 DB 路径必须在此注入）+ task_id 快照强制覆盖 task_type |
| `tests/api/test_asset_library_routes.py` | 资产库用户侧 13 条路由：`_feature_guard` Depends 内业务异常转 HTTP（feature_disabled→403/未登录 401）、not_found/group_not_found 统一 404 防枚举、quota_exceeded→403、group_scope=ungrouped 传字符串、/status 三元判定、list_groups can_manage 注入 |

### 前端测试（vitest，5 个新文件 + 1 个扩展，77 用例）

| 文件 | 守护点 |
|---|---|
| `web/tests/marketing_agent_poll_error_backoff.test.js` | 直连生成轮询 3 连错降频不判死（fix 53a8f69c 线上事故）：不清任务、气泡转 generating_placeholder、30s 降频重建、成功清零计数、旧图片路径分流直连 |
| `web/tests/task_config.test.js`（扩展 +9） | legacy_keys 迁移：旧 key 命中、canonicalModelKey 改写 short_key、精确 key 优先不被 legacy 劫持、未知 key 原样返回 |
| `web/tests/extract_frame_source_readback.test.js` | 提取帧源视频实时回读（fix 81686538）：isTemporaryVideoUrl blob:/data: 判定、findConnectedVideoNode 连线查找、提交前空地址/临时地址拦截、URL 变化覆盖+自动保存 |
| `web/tests/marketing_clipboard_media.test.js` | 剪贴板媒体提取：files+items 双来源去重、无名媒体按 MIME 重建 clipboard_*.png、纯文本/非媒体不提取、含媒体才 preventDefault |
| `web/tests/script_writer_power_budget.test.js` | 算力上限前端行为（fix 796d6db2「保存失败前端可见」）：非负整数校验回显旧值、清空=DELETE、PUT 500/code!=0 回显旧值并展示 detail、is_custom 控制恢复默认按钮 |
| `web/tests/video_enhance_status_polling.test.js` | 高清修复轮询契约（refactor 7634a6aa）：/api/get-status/{id} + tasks[0] 形状、SUCCESS/FAILED/RUNNING 收尾、空 tasks 与网络异常不抛错 |

### 端到端测试（Playwright，1 个文件，5 用例）

`auto_test/e2e/test_power_budget.py`：算力上限全链路。纯 API 用例（401/默认 payload/
非法 400/PUT-回读-DELETE 回退）挂 `ci_smoke`+`p0`——该路由的漏挂事故正是 API 级
e2e 能拦的形态，已具备进 CI push 门禁条件；UI 用例（script_writer 页输入框与服务端
同步）挂 `p1`。本机无 playwright，语法与 marker 已静态校验，首次运行在 CI e2e 容器。

### 基础设施

- `scripts/testing/test_discovery.py` / `run_unit_tests.py`：新增 `frontend` 分类
  （`--frontend-only`），使 `tests/frontend/` 6 个源码扫描回归进入 CI unit_tests
  ——此前它们不在发现列表中，只能手动跑，已出现 4 个用例因源码演进而静默过期。
- `tests/frontend/test_marketing_agent_duplicate_images.py`：扫描源由
  marketing_agent.html 内联脚本改为 marketing_agent.js（函数早已迁移）。
- `tests/frontend/test_marketing_inspiration_video_detail.py`：拆分灵感页断言（有效）
  与营销页 new_session 消费断言（strict xfail 留痕，见下）。

## 排查中发现的存量问题（未在本次修改功能，需产品/后续分支处理）

1. **灵感页「发送」强制新会话链路已断**（67c40fc55，2026-07-01「内联 JS 提取为
   独立文件」时丢失）：灵感页仍带 `new_session=1` 跳转，`marketing_agent.js` 不再
   读取该参数，落到后端会话列表恢复。已用 strict xfail 用例留痕
   （`test_marketing_agent_still_honors_new_session_param`），修复后自动转绿。
2. **`web/js/pages/video_enhance.js` checkStatus 仍把 auth_token 放进 query params**
   （`/api/get-status/{id}?auth_token=...`）：与 marketing_agent 轮询已改掉的
   X3 红线模式（token 进 URL 经 Referer/日志泄漏）不一致，同端点 cookie 翻译
   鉴权可用。建议后续分支统一改为 Authorization 头或纯 cookie。

## 评估后未补的项（低价值或需 DB/浏览器，供参考）

- `model/users.py find_id_by_exact_account` 的 SQL 语义（LOWER/多命中取最小 id）
  ——单测只能 mock execute_query 验形状，真实语义需 DB 集成测试。
- `model/agent_verifications.py list_approved_by_session` JOIN——同上，留 DB 层。
- `grid_image_task._settle_pending_character_variants` 的 variant_written 分支——
  需 mock `_handle_task_success` 全链路，成本高；回填核心已在 service 层覆盖。
- 营销页 @ 引用资产目录四级懒加载的行为级测试——深嵌 Vue setup 闭包，
  建议以 Playwright e2e 补（配合 mock_mode）。

## 验证记录（2026-10-29 本机）

- pytest（两批新增/修改文件 + tests/frontend）：94 passed, 1 xfailed（第二批）+ 66 passed, 1 xfailed（第一批）
- vitest 全量：**1151 passed**（113 个文件，两批合计新增 ~160 用例）
- CI lint ×4（blocking_calls / migration_names / tool_executor_signature /
  frontend_xss）：全部通过（blocking_calls 仅存量 R5 advisory warning）
- e2e：本机无 playwright，语法与 marker 静态校验；断言端点/请求形状已对照源码
  与 conftest fixture 核实，首跑在 CI e2e 容器

## 评估后未补的项（低价值或需重基建，供参考）

- 数字人分段服务（marketing 侧 submit_segments/check_status 聚合）端到端——
  mock 挡板已覆盖 H3 异步通道但 compose 拼接依赖真实 ffmpeg，且 param_prepare
  VL 阶段无 mock 短路；建议随 mock 通道扩展后再上 e2e（test_digital_human.py）。
- admin 每日统计 UI 渲染（Playwright route mock）——API 层已被单测+e2e 覆盖，
  UI 侧建议随 AdminPage page object 补每日统计导航后一起加（p2）。
- 画布级联清理/对话组删行重排/连线路由选择器（connection_base/dialogue_group/
  canvas 删除三段）——依赖画布 state stub 基建，行为级成本高；核心状态迁移已有
  readSource 守卫覆盖，建议在下次触碰这些文件时随改随补。
