---
name: generate-user-api-module
description: 在智剧通用户模块系统中生成、修改和迁移图片、视频、音频 API 对接代码。需要根据需求检索当前项目公开 SDK/协议、把代码写入受限 staging、执行校验并提交管理员审批时使用；不得修改核心驱动、active Release 或读取真实密钥。
allowed-tools: ["user_module_generation_create", "user_module_project_search", "user_module_project_read", "user_module_generation_get", "user_module_generation_read", "user_module_generation_write", "user_module_generation_validate", "ask_user"]
---

# 生成用户 API 模块

## 强制流程

1. 读取 [module-contract.md](references/module-contract.md)。
2. 使用 `user_module_project_search` 和 `user_module_project_read` 查询 `module_runtime/`、`docs/backend/user_modules.md` 和公开示例；只读当前核心代码。
3. 确认能力覆盖：先把**本份供应商文档里实际出现的接口**映射到平台 operation，再决定要不要问。
   名称对照（同一件事只算一种能力，禁止拆成两个选项）：
   - 文生图 / 无参考图 → `text_to_image`
   - 图生图 / 参考图 / `params.image` / 以图生图 → `image_edit`（这就是图生图，不是额外的「局部编辑」）
   - 文生视频 → `text_to_video`
   - 图生视频 → `image_to_video`
   `ask_user` 只问：供应商文档里**另有独立接口**、且需求尚未覆盖的能力。候选必须带来源
   （路径、model 名或文档小节）。HTTP 供应商每任务最多 15 问，选项用管理员能看懂的业务名，需要时再括号
   标注 operation。禁止把已覆盖的图生图再问成「是否接入 image_edit」；禁止臆造文档没有的
   能力（如本次文档没有的 upscale、视频、局部重绘）。文档只有文生图+参考图时，直接实现
   `text_to_image` 与 `image_edit`，不要为了「问满」而提问。管理员确认后必须拿到对应接口
   文档再实现。不得 silently 收窄文档已有的接口，也不得凭猜测实现文档之外的接口。
   若提问超时、达上限或返回失败，停止生成，把待确认事项列入结束总结，不要空转重试。
   **完成模式一律轮询**：异步供应商 `completion_modes` 只写 `["polling"]`。文档即使提供
   `webhook_url` / callback / 回调，也不得实现 webhook、不得向供应商下发 `webhook_url`，
   **禁止用 `ask_user` 询问回调 payload、回调字段或是否走 webhook**。仅当 submit 同步返回
   最终媒体、没有任务 ID、无需再查时才用 `immediate`。轮询模块的 `handle_callback` 直接
   `raise NotImplementedError`。
   HTTP 供应商每任务最多 15 问。**本地 ComfyUI** 任务（staging 已有 `vendor/workflow.json` 与
   `vendor/comfyui.json`）走下方 Comfy 分支，最多 15 问，只确认节点映射，**禁止再问 ComfyUI
   地址或 webhook**。
4. 提取供应商参数规格表：从需求提供的供应商文档（或用户提供的文档链接/文本）整理每个关键
   参数（`resolution`/`ratio`/`duration`/尺寸等）的枚举值、默认值与计费差异。驱动内的
   白名单必须与文档取值逐字一致（含大小写），关键枚举参数声明进 capability 的
   `request_schema`，供应商默认档位写入 README。文档缺失或模糊时用 `ask_user` 向管理员
   确认（界面回答），只问缺的那一项枚举/默认值，不得猜测，也不得顺带问无关能力。
5. 如果任务上下文已经提供 `generation_id`，直接使用该草稿；否则调用
   `user_module_generation_create`。不得在已有 `generation_id` 时另建重复草稿。
6. 只通过 `user_module_generation_read`/`user_module_generation_write` 读写 staging；不得写项目根目录、`modules/*/releases` 或数据库。
7. 生成 `manifest.json`、`src/__init__.py`、`src/driver.py`、测试和 `README.md`。
   `manifest.version` 与 `core_compat` 由服务端根据 `pyproject.toml` 中的智剧通版本自动写入；
   草稿可省略这两个字段，不得自行发明智剧通版本号。
8. 网络调用只使用异步 `httpx.AsyncClient` 并显式设置 timeout；不得在异步方法中使用 `requests`、`urllib.request`、`time.sleep` 或同步 SDK。
9. 不导入 `server`、`api`、`model`、`task`、`services`、`tools`、`enterprise`。模块只能依赖 Python 标准库、`httpx`、`pydantic`、`module_runtime.protocol`；本地 ComfyUI 还可导入 `module_runtime.comfyui`。
10. 调用 `user_module_generation_validate`；修复全部静态校验 error。该调用还会自动运行独立提示词的
   AI 安全审核；必须检查 `review` 与 `review_gate`，只有 `review_gate.publishable=true` 才能声称
   草稿已完成并可交付审批。审核跳过、超时、格式异常或高风险时应停止并如实报告，不得绕过。
11. 展示代码变更、外部域名、密钥名称、能力、参数规格表和测试结果，等待管理员批准。
12. Agent 没有审批或激活工具。只有后台管理员审批接口可以将 staging 发布为不可变 Release；审批过程还会在唯一 Supervisor 中启动候选 Runner 并调用真实 `health` 契约；禁止自行复制到 active 目录。

## 本地 ComfyUI 分支

任务上下文或 staging 出现 `vendor/workflow.json` + `vendor/comfyui.json` 时，不要把需求
当成普通 REST 文档解析。

1. 用 `user_module_generation_read` 读取这两份文件。`comfyui.json.base_url` 写入
   `src/settings.py` 的 `COMFYUI_BASE_URL`；不要声明 `secret_names`，不要读 `ctx.secrets`
   来拿地址。
2. 把工作流转成 `src/workflow_graph.py` 的 `WORKFLOW = {...}`（模块运行时禁止 `open()`）。
3. 必须 `from module_runtime.comfyui import LocalComfyUIClient, apply_mapping, infer_mapping,
   outputs_from_history, view_url, history_failed`。禁止手写同步 `requests` 或复制一套 HTTP。
4. `infer_mapping(WORKFLOW)` 得到节点映射，写入 `src/mapping.py`。有歧义（多张 LoadImage、
   多个非空 prompt、多种输出节点）时用 `ask_user` 让管理员确认，最多 15 问。
5. `submit`：下载 `request.inputs` 的 URL（`LocalComfyUIClient(allowed_input_urls=...)`）→
   `/upload/image` → `apply_mapping` → `/prompt` → `Accepted`，`opaque_data` 保存 mapping。
   `poll`：`/history/{prompt_id}`，完成则把 `view_url` 填进 `MediaRef.url`。
6. `completion_modes` 只写 `["polling"]`。`resource_limits.operation_timeout_seconds` 为 900。
7. `permissions.network_hosts` 只声明 `comfyui.json` 的 host:port（如 `localhost:8188`）。
   输入图 URL 由核心提供，不要把 CDN 域名写进 network_hosts。
8. 剥掉 `JWImageSaveToPath` 等写远端磁盘的节点。随机化 seed。

## 代码要求

- 实现 `initialize`、`health`、`submit`、`poll`、`cancel`、`handle_callback` 六个异步方法。
- `health` 只检查代码、协议和本地客户端是否就绪，禁止访问供应商网络。密钥尚未配置时应返回
  `healthy=True` 并在 `details.missing_secrets` 中列出名称；真正的 `submit`/`poll` 仍必须返回
  `MISSING_SECRET` 等结构化错误，不能带着空密钥调用上游。
- 图片、视频、音频统一使用 `MediaRequest`、`MediaRef`、`Completed`、`Accepted`、`PollResult`。
- 即时供应商（submit 同步返回最终媒体）返回 `Completed`，`completion_modes` 为 `["immediate"]`。
  外部异步供应商返回 `Accepted`，`completion_modes` 只声明 `["polling"]`，并把轮询所需数据
  保存到 `TaskHandle.opaque_data`。不要声明 `webhook`，不要提交 `webhook_url`。
- 不保存全局用户状态，不接收数据库 Session、宿主机路径或核心密钥。
- 所有 provider 调用支持 deadline、幂等键和结构化错误。
- HTTP 调用只接受 httpx 标准关键字参数（`url`/`params`/`json`/`headers`/`data`/`auth`/
  `timeout` 等）；幂等键、回调地址、模型名等业务字段必须放进 `json=` 请求体或 `headers=`，
  绝不能写成 `client.post(..., idempotency_key=...)` 这类调用参数（运行时 TypeError，静态
  校验按 `HTTP_CALL_INVALID_KWARG` 拦截）。详见 module-contract.md「HTTP 调用关键字参数」。
- 可选输入节点必须显式置空：供应商接口按「传哪个节点改哪个」语义工作时（如 RunningHub
  AI-App 的 `nodeInfoList`），未传节点会保留上次/默认值。尾帧等可选图片节点要始终传，
  本次没有值时 `fieldValue` 传空字符串 `""`，绝不能「没值就不传该节点」；首帧等必填输入
  为空则返回 `Rejected`。详见 module-contract.md「可选输入节点必须显式置空」。
- 外部供应商的图片输入，图床二选一：①供应商是 RunningHub，或需求文档已详细说明
  其图片上传方式（接口路径、请求格式、返回字段可落地）→ **继续用该供应商的图床**：
  先用 httpx 下载输入图字节再上传（RunningHub：`POST /openapi/v2/media/upload/binary`，
  用返回的 `fileName`/`download_url` 作字段值），禁止把平台 URL 原样透传给只收文件
  上传的字段（真实事故：runninghub.qweniamgeeidtv2 把局域网地址写进 fieldValue 导致
  拉图失败）；文档缺该上传接口路径时才允许 ask_user 问这一个路径且选项必须带文档
  来源。②其余情况**默认用系统自带图床**：核心桥接层已把四类输入图统一上传平台图床
  并公网化（第三方外链重签名刷新），模块读到的 `inputs[].url`、
  `parameters.image_url`/`reference_images` 已是公网 URL，直接透传即可——**禁止
  ask_user 问供应商上传接口路径，也不要自己实现图床上传**（平台核心驱动对接 kling
  等外部 API 即此模式）。本地 ComfyUI 模块例外。
  测试仍必须覆盖「parameters 图片键为局域网地址」用例，断言发往供应商的请求不含内网地址。
  详见 module-contract.md「图片输入与图床：供应商图床按文档，其余默认系统图床」。
- 端点 URL 与需求文档逐字一致：需求文档/curl 示例中的完整 URL（含路径中的 appId、
  工作流 ID）必须逐字复制进常量，禁止截断或省略路径段——错误路径常返回 HTTP 200 且
  无 taskId，任务以「提交响应缺少 taskId」失败（真实事故：runninghub.qwenimageeditv3
  把 `/run/ai-app/2003817929298853889` 写成 `/run/ai-app`）。README 需列出全部端点
  清单及文档来源。详见 module-contract.md「端点 URL 必须与需求文档逐字一致」。
- 取参先读平台标准键：平台固定传 `ratio`（简式 "16:9"，并冗余 `aspect_ratio` 同值）、
  `duration`（秒）、`resolution`（含文生图 `image_size` 档位）。映射到供应商枚举用
  前缀+大小写不敏感匹配（"16:9" → "16:9 (Widescreen)"、"1K" → "1k"）；比例/分辨率/时长
  缺失或非法必须 `Rejected`，**禁止静默回落默认值**。详见 module-contract.md
  「平台标准参数键与取参规则」。
- 不在模块中创建 FastAPI 路由；HTTP 路由由核心固定网关提供。
- `secret_names` 只能从任务描述附带的「平台可授权密钥清单」中选取名称（静态校验会拒绝
  清单外的名称）。清单由后台 `user_module_grantable=True` 的动态配置自动生成规范名
  （如 `runninghub.api_key → RUNNINGHUB_API_KEY`、`huimengi.api_key → HUIMENGI_API_KEY`）。
  选取规则：清单中存在与当前供应商一一对应的名称时直接选用（此时禁止改选编号/共用
  槽位，也不得再就密钥来源提问）；供应商是聚合站/中转站，
  或其凭据只能对应 `api_aggregator.site_N` 这类编号/共用槽位时，槽位与供应商的实际
  对应关系只有管理员知道，**必须用 `ask_user` 请管理员确认密钥配在哪个槽位**（选项
  逐个列出候选槽位的后台配置名与描述，外加「都不在，需要平台新增配置」），禁止按
  编号顺序或描述相似度猜测；清单中完全没有可承载的名称时 `secret_names` 留空并在
  总结中说明需要平台扩展配置。Supervisor
  每次 RPC 会把对应后台配置值写入 `ctx.secrets`；模块仍只能从 `ctx.secrets` 获取值，
  不得 import 配置模块、读 `system_config` 或读取环境变量。

## 停止条件

遇到以下情况停止发布并报告：

- 需求必须修改核心 ABI 才能实现。
- 需要未批准的第三方依赖或外部可执行文件。
- 需要直接数据库访问、任意文件访问或核心进程环境变量。
- 校验、Runner 健康检查或契约测试不通过。
- 生成基线的核心 revision 已变化且尚未重新校验。
