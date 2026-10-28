# develop 相对 master 的测试缺口分析与补充（develop_test_1029，2026-10-29）

## 背景

`origin/develop`（dbaeb090，2026-10-28）领先 `origin/master`（821d599f，2026-10-22 合并）
155 个提交、269 个文件（+31257 行），覆盖资产库、导演台、视频高清修复、算力预算、
相机对话、营销轮询修复等六大功能。develop 已自带大量测试（tests/ 新增 13 个文件、
web/tests/ 新增 19 个文件），本次对剩余缺口做了系统性排查并补充。

**总体结论**：测试纪律良好——power_budget/pending_reference_selections 全链路/
wechat fail-closed/cookie 续期/新驱动等均有覆盖。真正的缺口集中在**路由层接线**、
**调度循环返回值消费**与**若干 bugfix 的回归测试**，本次已补齐。

## 本次补充清单

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

- pytest（新增/修改 6 个文件 + tests/frontend）：66 passed, 1 xfailed
- vitest 全量：1068 passed（97 个文件）
- CI lint ×4（blocking_calls / migration_names / tool_executor_signature /
  frontend_xss）：全部通过（blocking_calls 仅存量 R5 advisory warning）
