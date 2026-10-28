# 资产库（Asset Library）

> 分支：`develop_f1086` · 迁移：`no_156_20261024_add_asset_library_tables` · 前端公共模块：`web/js/asset_library.js` + `web/css/asset_library.css`

## 1. 功能概述

资产库让用户把 **marketing_agent / video_workflow / storyboard** 三个页面中生成的图片（首期仅图片，表结构已预留 video/audio）收藏为可复用资产：

> **功能开关**（system_config，admin「资产管理」配置，默认关闭）：`asset_library.enabled` 总开关（关闭时所有用户侧接口 403）、`asset_library.allow_all_users` 全员可用（关闭时按 `asset_library_quota.enabled` 逐用户放行，用户管理「资产库容量」弹窗内开关）、`asset_library.total_quota_gb` 全站总磁盘上限（0=不限，超限新资产拒绝加入；入库时 SUM(file_size) 校验，软限制）。前端 `window.AssetLibrary` 的 promptAdd/openModal 经 `GET /api/asset-library/status` 前置拦截（缓存探测）。

- **入库**：各页面生成图片卡片上的「入库」按钮 → 弹窗设置名称/分组/权限 → 服务端把源文件**复制/下载到本地永久目录**（`upload/asset_library/<user_id>/`），资产文件不受媒体缓存清理策略影响（`utils/media_cache.py` 不扫描该目录）；删除限属主/管理员。测试不得直写该目录（单测经 fixture 重定向到临时目录；历史上 `_cleanup_asset_dir` glob 清理曾误删生产资产文件）。
- **权限**：每个资产独立的「查看」与「编辑」权限，各自支持 `private`（仅自己）/ `specified`（指定成员）/ `public`（所有人）；编辑权限隐含查看权限。
- **分组**：入库/编辑弹窗分组下拉含「＋ 新建分组…」（选中后输入组名即时创建并选中）；`asset_group` 分组目录**全局共享**（所有登录用户可见同一套目录、均可创建；重命名/删除限创建者或管理员，组内有资产时拒绝删除）。
- **@ 引用**：三个页面通过 @ 提及引用资产库内容（见 §5）。
- **容量**：资产文件不受存储容量限制，但按用户记录已用容量（`asset_library_quota`），管理员逐人设置上限（admin 用户管理 →「资产库容量」，`0=不限`，默认 2GB）；删除资产（属主或管理员）后自动扣减该属主容量记录。

## 2. 数据表（4 张）

| 表 | 说明 | 关键字段 |
|---|---|---|
| `asset_group` | 分组（目录），全局共享 | `name`(unique), `creator_user_id` |
| `asset_library` | 资产记录 | `user_id`(属主=容量计入者), `group_id`, `asset_type`(image/预留), `name`, `source_url`(溯源), `file_path`(相对 upload), `file_size`, `view_permission`, `edit_permission` |
| `asset_permission_member` | 指定成员 | `asset_id`, `user_id`, `perm_type`(view/edit)，uk(asset,user,perm) |
| `asset_library_quota` | 用户容量 | `user_id`(unique), `quota_bytes`(0=不限), `used_bytes` |

模型文件：`model/asset_group.py` / `model/asset_library.py` / `model/asset_permission_member.py` / `model/asset_library_quota.py`（末尾附 CREATE_TABLE_SQL，与迁移一致）。

## 3. 可见性与权限规则（services/asset_library_service.py）

可见 = `user_id = 自己` ∪ `view|edit_permission = 'public'` ∪ `(view|edit = 'specified' 且在 asset_permission_member 中被指定 view 或 edit)`。

列表 SQL 的可见性片段（`_visible_where`）与分组计数共用同一语义；`can_edit` = 属主 ∪ `edit=public` ∪ 被指定 edit ∪ 管理员；`can_delete` = 属主 ∪ 管理员（删除是管理操作，不受 public/specified 编辑权限影响）。列表/详情接口均返回 `can_edit`/`can_delete`/`file_missing`，前端据其渲染「编辑」「删除」按钮与「文件缺失」徽标。

**文件完整性**：`file_missing` = 磁盘上资产文件已不存在（外部误删/迁移缺失）。服务启动时 `verify_asset_files()`（server 启动钩子，只读）扫描全部记录并在有缺失时日志告警（含资产 id），便于第一时间发现——应用内删除路径均有审计日志，文件缺失基本来自外部。

**删除规则**：`DELETE /api/asset-library/assets/{id}` 属主可删自己的资产，管理员可删任意资产（`purge_asset`：删文件 + 删记录 + 删成员 + `quota.release` 扣减属主容量记录，幂等）。非属主非管理员（即便 `edit=public` 或被指定 edit）不可删除。

## 4. 后端接口

用户侧 `api/asset_library.py`（prefix `/api/asset-library`，`@require_permission` 登录即可，DB/IO 全部 `asyncio.to_thread`/线程池，不阻塞事件循环）。`POST /assets` 的 `svc.add_asset` 是唯一的 async 入口：HTTP 下载走 aiohttp，pymysql / `os.makedirs` / 配额预留与落库收拢进 `asyncio.to_thread`；落库后写成员失败会删除已插入行并释放配额，避免客户端看到失败后重试重复扣配额。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/assets?page&page_size&group_id&group_scope=ungrouped&asset_type&keyword&scope=all\|mine\|shared` | 资产列表（只返回可见资产，附 `owner_name/can_edit/can_delete/file_missing/view_members/edit_members`） |
| POST | `/assets` | 入库：`{source_url, name, group_id, asset_type, view_permission, edit_permission, view_members, edit_members}` |
| GET | `/assets/{id}` | 详情（需查看权限；管理员可查看任意资产） |
| PUT | `/assets/{id}` | 编辑元信息（需编辑权限） |
| DELETE | `/assets/{id}` | 删除资产并扣减属主容量记录（**属主或管理员**） |
| GET | `/groups` | 共享分组目录 + 每组可见资产计数 + 未分组计数 |
| POST | `/groups` / PUT `/groups/{id}` / DELETE `/groups/{id}` | 分组管理（改名/删除限创建者或管理员） |
| GET | `/quota` | 我的容量 `{quota_bytes, used_bytes}` |
| GET | `/users?account=` | **完整账号精确查找**（指定成员添加）：手机号 / 邮箱 / 昵称全等，不做模糊联想；命中返回 `data.user={user_id, display_name}`，未命中 `null`（前端提示「用户共享成功 / 没有查找到这个用户」） |

管理员侧 `api/admin.py`：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/users/{id}/asset-quota` | 查询配额与用量、资产数 |
| PUT | `/api/admin/users/{id}/asset-quota` | 设置 `quota_bytes`（0=不限） |
| GET | `/api/admin/asset-library/assets?user_id=` | 按用户列资产（清除入口数据源） |
| GET/PUT | `/api/admin/asset-library/config` | 读取/保存功能配置（enabled / allow_all_users / total_quota_gb，写 system_config 热生效，value_type 用 float——枚举无 number） |
| PUT | `/api/admin/users/{id}/asset-permission` | 逐用户开启/关闭使用权限（quota.enabled；allow_all_users 关闭时生效） |

### 入库流程与配额并发安全（`svc.add_asset`）

1. 校验参数（类型/权限枚举/分组存在/成员数 ≤50）；随后 `ensure_user_allowed`（开关+逐用户权限，管理员跳过 allow_all 但不跳过总开关）；
2. 源文件持久化：`/upload/` 本站路径直接复制，外链走 aiohttp 下载（超时常量 `AssetLibraryConstants.DOWNLOAD_*`；写盘丢 `utils/download_io_pool` 长寿线程池）；
2.5. **全站总容量校验**：`check_global_capacity`（total_quota_gb>0 时 SUM+size≤limit，SUM 与 INSERT 间有并发窗口属软限制）；
3. **原子预留**：`quota.try_reserve` 用条件 UPDATE（`used_bytes + size <= quota_bytes OR quota_bytes = 0`）无锁防超卖；失败返回 `quota_exceeded`；
4. `os.replace` 转正文件名 → `_persist_added_asset`（容量校验 + `try_reserve` + 插入 `asset_library` + 写指定成员，同一线程）。成员/落库失败会 `delete` 已插入行并 `quota.release`，避免重试重复扣配额；
5. `finally` 兜底：未提交成功时清理临时/已转正文件（配额回滚由 `_persist_added_asset` 在同一线程完成，避免双释放）。

单文件上限 `MAX_FILE_SIZE_BYTES=50MB`（下载流式统计，超限即中断）。

## 5. @ 引用（`@资产:{id}` token）

**统一 token 格式**：`@资产:{asset_library.id}`（常量 `AssetLibraryConstants.MENTION_TOKEN_PREFIX`）。

- **marketing_agent**：@ 下拉合并资产条目（`mentionableItems`），选择插入 token；`handleSend` 提交前 `resolveMentionTokens` 还原为 `![名称](/upload/相对路径)` markdown 图片。
- **video_workflow**：图片节点/分镜节点提示词下拉（`nodes.js showCharacterDropdownForImagePrompt`，含提示词放大编辑窗口）与图生视频节点独立 @（`image_to_video_node.js`）均含资产条目；提交前还原覆盖四个通道：图片生成（`image_node.js`）、分镜图生成（`shot_frame_generator.js`，放大窗口可插 token 的对应消费点）、分镜视频（`shot_frame_video_generator.js`）、图生视频（`image_to_video_node.js`）。
- **storyboard**：@ 提及弹窗新增「资产库」tab（`renderMentionPopup`）；胶囊镜像层（`chat_mention_chips.js` + `frame_mention.js scanFrameMentionTokenRanges`）把 token 渲染为「缩略图+名称」胶囊（原子删除、悬停大图，与 @首帧图 同一套机制）；Agent 对话/直连生图/直连视频提交前还原。

还原语义：`resolveMentionTokens(text)` 把 token 替换为 `![name](/upload/相对路径)`（不带 host），使资产图片以 URL 形式进入生成上下文（文生图参考图提取、LLM、VL 均可消费）；**用相对路径**是为了落库（分镜/消息）后不随 host/端口失效，且服务端消费链（`extract_local_path_from_url` 等）域名无关解析、相对/绝对两种格式均认（存量绝对 URL 无需迁移）；alt 中的 markdown 语法字符（`[]()`）会被清洗，资产名含括号不破坏图片语法；无权访问/已清除的 token 保留原文不阻断提交。storyboard 的 agent 消息面板为纯文本渲染，`![..](..)` 由渲染层折叠为 `[图片:名]` 占位（renderAgentMessages），本地会话显示保留原始 token。资产库弹窗内展示（卡片/预览/提及缩略图）同样全部使用相对路径，由浏览器按当前站点解析。

## 6. 前端集成点

| 页面 | 入库按钮 | 资产库入口 | @ 引用 |
|---|---|---|---|
| marketing_agent | 生成图片卡 `.generated-result-actions`「入库」（`data-asset-add-src` 委托）；**历史存量消息**回放时由 `marketing_agent.js augmentGeneratedImageCards` 扫描缺按钮的生成图卡自动补齐（MutationObserver 挂聊天容器，template ref 重建后重挂；源地址从卡片 img src 反解：`/api/proxy-image?url=ENC` 还原原始外链，`/upload/...` 原样） | 左侧 nav「资产库」 | @ 下拉**目录两级懒加载**（见下） |
| video_workflow | 图片节点「上传图片」行「入库」（`image-add-asset-lib-btn`） | 顶栏 `#assetLibraryBtn` + 画布加号菜单「添加素材 → 资产库」（`menuAddAssetLibrary` → `openModal({assetType:'all', onPick})`，选中图片落图片节点 `data.url/preview`，视频资产提示暂不支持；浏览弹窗 `opts.assetType` 支持全类型，视频卡片用 `<video>` 缩略图） | 提示词下拉 + 图生视频节点 @ |
| storyboard | 主预览 hover 工具条「入库」（`data-action="add-scene-image-to-asset-library"`） | —（顶栏 nav 入口已移除；浏览经由入库弹窗/@ 引用） | @ 弹窗「资产库」tab **目录两级懒加载**（`render.js renderAssetMentionList`：分组目录 → 组内资产滚动翻页，`events.js ensureAssetMentionData`/`loadAssetMentionPage`/`bindMentionListScroll`；浏览条目渐进合并 `state.assetMentionItems` 供胶囊层/提交还原，历史 token 由 `chat_mention_chips.js ensureAssetMentionItemsByIds` 按详情接口兜底入池） + 胶囊 |
| script_writer | 图片预览弹窗「加入资产库」（`addPreviewImageToAssetLibrary`，角色/道具显示，将当前大图 URL 交给 `AssetLibrary.promptAdd`；主图、多服装图、历史形象图均随缩略图选择变化） | 角色/道具编辑表单参考图行「📚 资产库」（`pickImageFromAssetLibrary`，选择器模式回填 `#char-image`/`#prop-image` + 预览，保存链路复用原有 `reference_image` 字段）；图片预览弹窗「历史形象图」后「资产库」按钮（`pickPreviewImageFromAssetLibrary`，角色/道具显示，选中资产写 `reference_image` 后走各自 `POST /api/{characters\|props}-files/{name}` 保存并 `notifyAgentAssetUpdated` 通知 AI；「重新生成/历史形象图」按钮仍仅角色显示） | —（仅图片参考图引用） |
| marketing_inspiration | —（无生成能力，不设入库按钮） | 左侧 nav「资产库」（`#sharedAssetLibraryNav`，点击 `AssetLibrary.openModal()`） | — |

**引用权限红线**：所有引用入口（@ 数据源、选择器）共用 `GET /assets` 列表，服务端 `_visible_where` 只返回「自己的 ∪ public ∪ 被指派 view/edit 的」资产——需求要求的三类可见性在数据源层强制，前端拿不到不可见资产。

**@ 下拉目录逐级懒加载（marketing_agent）**：资产多时不再一次性全量拉取——`marketing_agent.js` 的 @ 下拉一级固定两项：**「全部资产」**（点开即所有资产，lite 分页滚动加载）与**「资产目录」**（点开进入分组列表层：未分组/各分组，避免目录多时污染一级菜单）；点分组进入组内资产列表，滚动到近底部自动翻下一页（`AssetLibrary.fetchMentionItemsPaged` → `GET /assets?lite=1&group_id=..&page=..`，每页 30 条）；返回条按 `returnMode` 回到进入前的层级；@ 每次唤起都回到一级（不保留上次浏览层级）；@ 后输入关键字切为跨组搜索（300ms 防抖），清空关键字回一级。模式切换用快照比对丢弃过期分页响应（防竞态）。本地上传媒体条目始终在列表最前，选择资产仍插 `@资产:{id}` token，提交链路（`resolveMentionTokens`）不变。旧 `fetchMentionItems(keyword)`（单次 50 条）保留兼容 video_workflow/storyboard 调用方。storyboard 分镜助手 @ 弹窗的「资产库」tab 同构改造（无搜索模式，仅目录/组内两级），见 §6 前端集成点。

**lite 列表模式**（`GET /assets?lite=1`，`services.list_assets(lite=True)`）：跳过 `COUNT(*)`（`LIMIT page_size+1` 探测 `has_more`）与属主名/成员映射/权限标志/**文件存在性检查**（后者为每条一次磁盘 stat，是资产多时列表请求的主要额外开销），只返回 id/name/file_url/group_id。分页/浏览弹窗等完整模式不受影响。

**索引**：`asset_library` 现有 `idx_user_create(user_id,create_at)`（本人资产按时间翻页）、`idx_group(group_id)`、`idx_type(asset_type)`，新增 `idx_group_create(group_id,create_at)`（迁移 `no_158_20261027_add_asset_group_create_index`）——分组目录懒加载的组内 `ORDER BY create_at DESC` 分页走索引免 filesort；可见性 `EXISTS` 子查询走 `asset_permission_member.uk_asset_user_perm(asset_id,user_id,perm_type)`。`keyword` 为 `LIKE '%kw%'` 无法用普通 B-tree 索引，靠 lite 模式的小页size控制单次查询成本。

公共模块 `window.AssetLibrary`：`promptAdd`（入库弹窗）、`openModal`（浏览/分组/搜索/分页/权限编辑）、`fetchMentionItems`（单次 50 条兼容入口）、`fetchMentionGroups`/`fetchMentionItemsPaged`（目录两级分页，marketing_agent @ 下拉使用）、`buildMentionToken`、`resolveMentionTokens`、`toast`。所有动态 HTML 经 `window.escapeHtml` 转义（XSS 红线）；历史消息回放的新增 `data-asset-add-src` 已加入 `web/js/security.js` 白名单。

## 7. 相关常量与文档

- 常量：`config/constant.py` `AssetLibraryConstants`（权限枚举/类型/默认配额 2GB/单文件 50MB/下载超时/分页/token 前缀）、`UploadPathConstants.ASSET_LIBRARY_DIR`。
- 弹窗层级：`buildModal` 按 kind 互斥（浏览/入库=main 打开前清全部，编辑=sub 可叠于浏览之上），入口连点不会叠加多层 overlay；`asset_library.css` 尾部含 `html.theme-dark` 暗色主题适配（video_workflow 暗色模式）。
- admin 前端：用户管理操作列「资产库容量」弹窗（`web/js/admin.js assetQuotaModal`）：设置上限、查看用量/资产数，并内嵌该用户最近 50 条资产列表与「清除」操作（二次确认，走 `DELETE /api/asset-library/assets/{id}`，清除后自动刷新用量）。
- i18n：`marketing_agent.json`（`nav_shared_asset_library`/`add_to_asset_library`/`type_asset`）、`marketing_inspiration.json`（`nav_shared_asset_library`，灵感页不加载 marketing_agent 命名空间）、`video_workflow.json`（`image_node_add_asset_btn`/`asset_library_entry`）、`admin.json`（`btn_asset_quota` 等）；storyboard 侧 `i18nT(key, fallback)` 自带中文 fallback。
- 入口图标约定：资产库 nav 入口统一用 📚（彩色，与其他 nav emoji 风格一致；此前 🗂 在 Windows 渲染为深色剪影，已废弃）。

**指定成员交互**：完整账号精确查找（回车/添加按钮触发，无模糊下拉）——命中加入成员标签并提示「用户共享成功」（绿），未命中提示「没有查找到这个用户」（红），重复添加提示已在列表中。

## 8. 后续扩展（本期未做）

- 视频/音频资产：`asset_type` 已预留，入库白名单（`ASSET_TYPE_EXTENSIONS`）与前端 `accept` 需扩展。
- 资产库文件 CDN 化：可复用 `media_file_mapping`，但需保证清除策略不误删资产文件。
- 服务端 token 解析：当前由前端提交前还原；如需服务端兜底，可在对应生成链路按 `MENTION_TOKEN_PREFIX` 正则还原。
