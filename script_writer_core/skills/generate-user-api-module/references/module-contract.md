# 用户媒体模块契约

## Manifest

```json
{
  "manifest_schema_version": 1,
  "module_id": "vendor.service",
  "name": "Service name",
  "entrypoint": "src.driver:Driver",
  "rpc_protocol": "user-module-rpc/v1",
  "driver_protocol": "media-driver/v1",
  "sdk_version": "1.0.0",
  "execution_model": "native_async",
  "capabilities": [{
    "operation": "text_to_image",
    "media_kind": "image",
    "completion_modes": ["immediate"]
  }],
  "permissions": {
    "network_hosts": ["api.example.com"],
    "secret_names": ["EXAMPLE_API_KEY"],
    "asset_read": false,
    "asset_write": true
  }
}
```

生成草稿时省略 `version`、`core_compat` 和 `code_digest`：服务端从项目
`pyproject.toml` 读取唯一的智剧通版本，自动生成内部发布标识与兼容范围，并根据文件内容写入摘要。
管理员页面不要求手工维护模块版本号。
MVP 的 `execution_model` 只能是 `native_async`。`resource_limits.max_request_bytes`、
`operation_timeout_seconds`、`max_concurrency` 会由运行时强制执行，不能只当作说明字段。

## Driver

```python
from module_runtime.protocol import Completed, HealthResult, MediaRef


class Driver:
    async def initialize(self, ctx):
        return None

    async def health(self, ctx):
        return HealthResult(healthy=True)

    async def submit(self, ctx, request):
        return Completed(outputs=[MediaRef(media_kind=request.media_kind, asset_id="...")])

    async def poll(self, ctx, handle):
        raise NotImplementedError

    async def cancel(self, ctx, handle):
        raise NotImplementedError

    async def handle_callback(self, ctx, handle, event):
        raise NotImplementedError
```

**import 限制**：driver 只能 `from module_runtime.protocol import ...` 引用协议类型，以及
本地 ComfyUI 任务可以 `from module_runtime.comfyui import ...`。禁止 import
`module_runtime` 的其它子模块（runner/supervisor/generation 等，它们顶层挂
os/subprocess，是代码安全红线）。也禁止对象内省逃逸（`__class__`/`__bases__`/`__subclasses__`
等）。静态校验会拦截这两类。

允许的额外写法：`from __future__ import annotations`（类型注解兼容）；模块自带的
`tests/test_driver.py` 可以 `import pytest`、`from unittest.mock import ...`，并通过
`from src.driver import Driver` 取得被测驱动（entrypoint 约定即 `src.driver:Driver`）。
除上述与标准库/httpx/pydantic 外的第三方库一律不得出现。

局域网 ComfyUI 默认没有 API Key。地址写在模块自己的 `src/settings.py`
（`COMFYUI_BASE_URL`），`secret_names` 为空；换机器对该模块重新生成即可。禁止把地址写进
全局 `system_config`。工作流 API JSON 生成时转为 Python 字面量，运行时不得 `open()` 读盘。

Manifest 声明的密钥由 Supervisor 在每次 RPC 时解析，并以当次 `ctx.secrets` 字典注入，例如
`ctx.secrets["RUNNINGHUB_API_KEY"]`。`secret_names` 只能取任务描述附带「平台可授权密钥
清单」中的名称（静态校验会拒绝清单外名称）；清单由后台 `user_module_grantable=True` 的
动态配置自动生成规范名（`config_key` 大写并把 `.` 换成 `_`，如 `runninghub.api_key →
RUNNINGHUB_API_KEY`），并附各配置的后台描述。模块不得读取任意环境变量，也不得访问
`system_config`；未声明或宿主未配置的密钥不会出现。后台更新密钥后无需重启 Runner。同名
OS 环境变量（Supervisor 进程）优先；Manifest 不能拼接或读取任意系统配置键。

密钥槽位选择规则：清单中存在与当前供应商一一对应的名称时直接选用（此时禁止改选
`api_aggregator.site_N` 等编号/共用槽位，也不得再就密钥来源 ask_user）；供应商是聚合站/
中转站，或其凭据只能对应 `api_aggregator.site_N` 这类编号/共用槽位时，槽位与供应商的
实际对应关系只有管理员知道，**必须 `ask_user` 请管理员确认密钥配在哪个槽位**（选项逐个
列出候选槽位的后台配置名与描述，外加「都不在，需要平台新增配置」），禁止按编号顺序或
描述相似度猜测选定；清单中完全没有可承载当前供应商凭据的名称时 `secret_names` 留空，
并在任务总结中说明需要平台扩展可授权配置。

`health` 是发布时的本地加载与协议握手，不是供应商连通性测试：不得在其中发起网络请求。缺少业务
密钥时返回 `HealthResult(healthy=True, message="尚未配置密钥", details={"configured": False,
"missing_secrets": ["EXAMPLE_API_KEY"]})`；实际 `submit`/`poll` 必须继续以结构化
`MISSING_SECRET` 错误拒绝调用。这样管理员可以先审查和发布代码，再补齐凭据，同时不会误发计费请求。

**submit 返回协议（静态校验强制）**：`submit` 必须返回 `Completed` / `Accepted` / `Rejected`
三者之一，禁止直接 `return DriverError(...)`（会让 Runner 端协议校验崩溃，管理员只能看到
笼统的"模块调用失败"）。失败路径的规范写法：

```python
async def submit(self, ctx, request):
    api_key = ctx.secrets.get("RUNNINGHUB_API_KEY")
    if not api_key:
        return Rejected(error=DriverError(
            code="MISSING_SECRET",
            message="未配置 RUNNINGHUB_API_KEY",
            retryable=False,
        ))
    ...
    return Accepted(handle=..., next_poll_after_seconds=10.0)
```

`poll` 的失败封装在 `PollResult(status=JobStatus.FAILED, error=DriverError(...))` 中，同样
不得把 DriverError 作为顶层返回值。

## 参数规格（必须对齐供应商文档）

写驱动之前，必须先从供应商**当前线上文档**提取参数规格表，再按表实现：

- 对每个关键可选参数（`resolution`/`ratio`/`duration`/尺寸等），记录：名称、类型、
  枚举值、默认值、是否必填、计费差异。
- 驱动内的参数白名单/枚举必须与文档取值**逐字一致**（包括大小写与格式，如 `2K`、`768P`、
  `720p` 按文档原样）。禁止凭记忆或猜测补枚举值；文档未提到的取值一律不得出现在白名单。
- 供应商有默认档位时（如未传 `resolution` 默认 `2K`），在 README 标注该默认行为与计费影响；
  平台侧不会自动传分辨率，漏声明意味着用户永远使用供应商默认（可能更贵）。
- 把关键枚举参数声明进对应 capability 的 `request_schema`（JSON Schema 的 `enum`/`default`），
  供平台按渠道渲染选项；`request_schema` 为空等于声明"本模块没有规格化参数"，平台无法
  为它提供分辨率选择。示例：

```json
{
  "operation": "image_to_video",
  "media_kind": "video",
  "completion_modes": ["polling"],
  "request_schema": {
    "type": "object",
    "properties": {
      "resolution": {"type": "string", "enum": ["720p", "2K"], "default": "2K"},
      "duration": {"type": "integer", "minimum": 4, "maximum": 15}
    }
  }
}
```

- 文档与既有代码不一致时以文档为准修订，并在 README 记录文档来源与检索日期。

## 端点 URL 必须与需求文档逐字一致

需求文档 / curl 示例中出现的完整端点 URL（**含路径中的 appId、工作流 ID、模型名等
路径段**）必须逐字复制进代码常量，禁止截断、重组、省略或"规范化"路径段。供应商
网关对错误路径常返回 HTTP 200 + 无任务 ID 的错误体，任务会以「提交响应缺少
taskId」失败且极难定位（真实事故：runninghub.qwenimageeditv3 把需求文档中的
`POST /openapi/v2/run/ai-app/2003817929298853889` 写成 `POST /openapi/v2/run/ai-app`，
丢失末尾 appId 路径段，RunningHub 返回 200 无 taskId，任务直接失败）。

- 端点常量写成单一完整字符串（可拆 host 与路径常量再拼接，但路径段必须完整）。
- README 中列出「端点清单」表：每个端点的完整 URL、用途、文档来源小节。
- 提交自检：对照需求文档里的每个 URL 逐字核对代码常量，特别是路径末尾的数字 ID。
- 文档只有链接、没有相对路径的端点，先判断是否真的需要：非 RunningHub 且文档未说明
  上传方式时，图片上传接口**不需要实现，禁止为它 ask_user**（走系统默认图床，见
  「图片输入与图床」）；确需实现的端点（如轮询状态接口）缺路径时才向管理员确认。

## 图片输入与图床：供应商图床按文档，其余默认系统图床

**平台有系统默认的图床上传能力，模块必须直接复用**：任务进入模块前，核心桥接层
（`task/user_module_driver.py`）已把 first/last/reference/direct 四类输入图
统一经平台图床上传/重签名公网化（`utils/image_upload_utils.upload_local_images_to_cdn`，
七牛存储；本地/局域网地址上传换成 CDN URL，第三方外链刷新签名后透传）。模块读到的
`request.inputs[].url` 与 `parameters` 中的图片键**已经是公网可访问 URL**——需要
「把图变成公网地址」时用这个默认能力，不要自己再造上传，也不要为拿图床路径向管理员提问。

历史背景：桥接层公网化上线前，平台传入的图片引用可能是内网/局域网地址（如
`http://192.168.10.101:9003/...`），外部供应商从公网访问不到：提交接口本身能成功，
但供应商节点拉图失败，任务以「工作流运行失败」收场，且错误信息不含任何 URL 线索
（真实事故：runninghub.qweniamgeeidtv2，nodeInfoList 的 image fieldValue 直接用了
平台传入的局域网地址，RunningHub 拉图失败）。该问题已由核心桥接层统一解决，
模块侧只需按下方规则选择图床：

规则（图床选择按序判断，只分两支）：

1. **供应商是 RunningHub，或需求文档已详细说明其图片上传方式**（有可落地的
   接口路径、请求格式与返回字段）→ **继续使用该供应商的图床**：先用 httpx 下载
   `request.inputs[].url` 的字节，再上传其图床接口，用返回的文件名或 download_url
   作为图片字段值；**禁止把平台 URL 原样透传**给这类只收文件上传的字段（如
   RunningHub AI-App `nodeInfoList` 的 image 节点要 fileName）。RunningHub 图床：
   `POST /openapi/v2/media/upload/binary`（multipart 字段 `file`），响应
   `data.fileName`（节点 fieldValue 用它）与 `data.download_url`。需求文档缺该
   上传接口的相对路径时，才允许 `ask_user` 问这一个路径，选项必须带文档来源。
2. **否则默认使用系统自带图床**：平台桥接层已把输入图统一上传平台图床并公网化，
   模块直接透传 `request.inputs[].url`（或 `parameters` 同名图片键）即可。**禁止
   ask_user 询问供应商上传接口路径，也不得自行实现图床上传**——平台核心驱动
   对接 kling 等外部 API 用的正是这一模式。
3. 取图优先 `request.inputs[].url`（桥接层保证已公网化）；`parameters` 里的图片
   键是兼容冗余（已按同一映射公网化）。只有第 1 条场景才涉及再次上传。
4. `tests/test_driver.py` 必须覆盖「`parameters` 图片键为局域网地址（如
   `http://192.168.x.x/a.png`）」的用例：断言最终发往供应商的请求体/表单中
   不出现内网地址字符串（`192.168.`、`10.` 内网段、`localhost` 等）。
5. 本地 ComfyUI 模块例外：内网地址就是设备地址，直接使用，无需图床。

## 可选输入节点必须显式置空（节点状态残留）

部分供应商接口按「传哪个节点/字段就更新哪个」的语义工作，**未传入的节点会保留上一次
运行的值或工作流默认值**，服务端不会自动清空。典型是 RunningHub AI-App 的
`nodeInfoList`：本次任务没有尾帧图时若整个不传尾帧节点，服务端会沿用上次的尾帧，
生成结果带上不该存在的尾帧。

规则：驱动构建请求时，此类**可选输入节点必须始终传**，本次没有值就显式传空字符串，
绝不能「没值就不追加该节点」：

```python
# RunningHub 尾帧节点：始终追加，无尾帧时 fieldValue 为空字符串
node_info_list.append({
    "nodeId": "146",
    "fieldName": "image",
    "fieldValue": last_image_url or "",
    "description": "image尾图",
})
```

判断标准：读供应商文档时，凡接口以「节点/字段更新」方式提交（如 `nodeInfoList`、
`inputs` 按名更新），就要假设未传字段有残留值；对可选图片/可选参数一律显式置空。
首帧等必填输入为空时按参数校验错误返回 `Rejected`，不要静默提交。

## HTTP 调用关键字参数

httpx 的请求方法（`client.post/get/put/patch/delete/request/stream`）只接受固定关键字参数：
`url`、`params`、`content`、`data`、`files`、`json`、`headers`、`cookies`、`auth`、
`follow_redirects`、`timeout`、`extensions`、`stream`。

幂等键、回调地址、模型名、API 版本号等**业务字段属于请求体或 header**，写成调用关键字
参数会直接 `TypeError: post() got an unexpected keyword argument '...'`，Runner 端只会
回报笼统的「模块调用失败」（真实事故：runninghub.image2video_v6 首版把
`idempotency_key=request.idempotency_key[:50]` 写成 `client.post(...)` 的第 4 个关键字
参数）。静态校验按 `HTTP_CALL_INVALID_KWARG` 拦截：

```python
# 错误：idempotency_key 不是 httpx 参数，submit 一执行就 TypeError
resp = await client.post(
    SUBMIT_URL, headers=headers, json=payload,
    idempotency_key=request.idempotency_key[:50],
)

# 正确：供应商文档声明支持时放进请求体；未声明就忽略（平台侧已有任务级幂等）
payload["idempotencyKey"] = request.idempotency_key[:50]
resp = await client.post(SUBMIT_URL, headers=headers, json=payload)
```

供应商文档未声明的请求体字段同样不要发明（按「参数规格」小节以文档为准）。

`httpx.AsyncClient` 是**异步**上下文管理器：一律 `async with httpx.AsyncClient(...) as client:`
打开；写成同步 `with` 会在运行时抛 `AttributeError: __enter__`（静态校验按
`SYNC_WITH_ASYNC_CLIENT` 拦截）。

## 平台标准参数键与取参规则

平台桥接层固定向 `request.parameters` 下发以下标准键（此外 extra_config 原样透传）：

- `ratio`：画面比例，简式文本（如 `"16:9"`、`"9:16"`、`"1:1"`）
- `aspect_ratio`：`ratio` 的冗余键，值同 `ratio`（简式），供声明了该契约名的模块直接读取
- `duration`：时长（秒，整数）
- `resolution`：分辨率档位（视频来自用户分辨率选择，文生图来自 `image_size`，
  值如 `"1K"`、`"720p"`、`"2K"`；`image_size` 原键也会保留）
- 图片引用通用键：`first_frame_image` / `last_frame_image` / `reference_images` / `image_url`

驱动取参规则：

1. **先读平台标准键**（`ratio` / `duration` / `resolution`），再做供应商自有字段名映射；
   同时支持两者时标准键优先。
2. 映射到供应商枚举时用**前缀 + 大小写不敏感匹配**：如 `"16:9"` 匹配
   `"16:9 (Widescreen)"`、`"1K"` 匹配 `"1k"`。禁止把简式入参与完整枚举文本做全等比较。
3. **关键格式参数（比例/分辨率/时长）缺失或非法时必须返回 `Rejected` 并说明支持的
   取值，禁止静默回落默认值**——静默默认会让用户拿到比例或分辨率错误的成品且毫无
   提示（真实事故：模块拿不到比例参数静默用 "1:1 (Square)"，16:9 的源图被压成正方形）。
4. 宽松匹配只用于「入参 → 枚举」的映射；驱动内的白名单/枚举值本身仍须与供应商文档
   逐字一致，并声明进 capability 的 `request_schema`（`request_schema` 为空等于前端
   无法为该模块渲染比例/分辨率选项，用户只能吃默认值）。

声明 `webhook` 时，核心会在 submit 前把公网回调地址放入
`request.parameters["callback"]["url"]`。模块必须把该地址原样提交给供应商；回调到达后核心会把
headers/payload 转为 `CallbackEvent` 并调用任务钉住版本的 `handle_callback`。

生成草稿默认不使用 webhook：异步接口只声明 `polling`，不要向供应商下发 `webhook_url`，
也不要向管理员询问回调 payload。供应商文档里的 webhook/callback 视为可选网关字段，忽略即可。
仅当 submit 同步返回最终媒体时声明 `immediate`。轮询模块的 `handle_callback` 应
`raise NotImplementedError`。HTTP 供应商与本地 ComfyUI 每任务统一最多 15 次 `ask_user`，
只确认节点映射，禁止再问已在表单里的 ComfyUI 地址。

即使能力只声明 immediate 或 polling，仍必须实现六个方法。不适用的方法应返回结构化结果或明确抛出
`NotImplementedError`，不能缺失。

## 发布和调用

草稿通过校验和管理员审批后成为不可变 Release。核心为每个任务保存 release id、版本和摘要，
再通过 Supervisor RPC 路由到对应 Runner。模块代码不能依赖“当前激活版本”或核心数字 implementation ID。
