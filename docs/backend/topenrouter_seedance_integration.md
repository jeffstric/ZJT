# TopenRouter 供应商接入与 Seedance 素材 Action 接口对接

> 变更日期：2026-09-28
> 相关文档：《对外接口文档-Seedance素材Action接口.md》（仓库根目录）、
> https://topenrouter.chinadatapay.com/docs?section=video

## 1. 背景

TopenRouter（topenrouter.chinadatapay.com）是支持 Seedance 2.x 系列模型的第三方 API
平台，视频任务接口与素材接口共用 `https://tp-api.chinadatapay.com:8000`。
本次接入包含两部分：

1. **TopenRouter 视频供应商**：作为 Seedance 2.0 Fast / 2.0 / 2.0 Mini / 2.5 四个任务
   的新实现方（`seedance_*_topenrouter_v1`）
2. **Seedance 素材 Action 接口客户端**：火山方舟真人库标准接口的平台形态
   （`/v1/api/assets/?Action=...`，Bearer 鉴权），用于真人素材上传加白

## 2. 接口调查结论：TopenRouter vs 火山引擎

**协议同构**，因此驱动直接继承火山国内版驱动，改动量极小：

| 维度 | 火山方舟 | TopenRouter | 结论 |
|---|---|---|---|
| 创建任务 | `POST {base}/api/v3/contents/generations/tasks` | `POST {base}/v1/video/tasks` | 路径不同 |
| 查询任务 | `GET {base}/api/v3/contents/generations/tasks/{id}` | `GET {base}/v1/video/tasks/{id}` | 路径不同 |
| 请求体 | `model` + `content[]`（type/role）+ `ratio`/`duration`/`resolution`/`seed`/`watermark`/`generate_audio` 等 | 完全一致（另有 `execution_expires_after` 等扩展字段） | 一致 |
| 创建响应 | `{"id": "cgt-..."}` | `{"id": "task_..."}` | 一致 |
| 查询响应 | `status` + `content.video_url` + `usage.completion_tokens` | 一致 | 一致 |
| 状态枚举 | queued / running / succeeded / failed | 多 `cancelled` / `expired` | 扩展（驱动映射为 failed） |
| 鉴权 | Bearer（API Key） | Bearer（sk- 开头） | 一致 |
| 模型名 | `doubao-seedance-2-0-260128` 等带日期 | 同火山原名（2026-10-29 实测 `/v1/models`：`doubao-seedance-2-0-260128`/`-fast-260128`/`-mini-260615`/`2-5-260628` 均在列） | 无需映射 |
| 素材引用 | 素材库 asset | `asset://<asset_id>`（真人素材优先，避免敏感风控） | 支持 |

## 3. 新增/修改文件

### 3.1 素材 Action 客户端（新增）

`utils/seedance_asset_client.py` — `SeedanceAssetClient`（同步 requests，供驱动在
同步任务执行器内调用；web 路由如需调用须 `asyncio.to_thread` 包装）：

- 封装全部 12 个 Action：素材 CRUD（CreateAsset/GetAsset/ListAssets/UpdateAsset/
  DeleteAsset）、素材组 CRUD、真人活体认证（CreateVisualValidateSession/
  GetVisualValidateResult，**已封装未接前端路由**）
- `wait_asset_active()`：轮询 GetAsset 直到 Active（官方建议间隔 ≥1s），Failed/超时抛
  `SeedanceAssetError`
- 错误统一为 `SeedanceAssetError(code, message, http_status)`：平台信封
  `{code, message}` 与官方 `ResponseMetadata.Error`（如 `NotFound.asset_id`）两类结构
- **鉴权双形态**（工厂按供应商组凭据自动分派）：网关 Bearer（`<group>.asset_api_key`
  回落 `<group>.api_key`）；直连火山 AK/SK 签名（`<group>.access_key` + `<group>.secret_key`，
  HMAC-SHA256 V4 实现见 `utils/volcengine_signer.py`，火山直连驱动已挂 `volcengine`
  组接入，见 docs/drivers/seedance_volcengine_v1_driver.md「真人素材三模式」）

### 3.2 TopenRouter 驱动（新增）

`task/visual_drivers/seedance_topenrouter_v1_driver.py` — 基类
`SeedanceTopenrouterV1Driver(SeedanceVolcengineV1Driver)` + 4 个子类：

| 子类 | driver_type | 发送的模型名（= 火山原名，网关原生支持） |
|---|---|---|
| `Seedance20FastTopenrouterV1Driver` | 22 (2.0 Fast) | `doubao-seedance-2-0-fast-260128` |
| `Seedance20TopenrouterV1Driver` | 23 (2.0) | `doubao-seedance-2-0-260128` |
| `Seedance20MiniTopenrouterV1Driver` | 31 (2.0 Mini) | `doubao-seedance-2-0-mini-260615` |
| `Seedance25TopenrouterV1Driver` | 36 (2.5) | `doubao-seedance-2-5-260628` |

要点：

- 覆盖类属性 `_create_task_path`/`_query_task_path = "/v1/video/tasks"`、
  `_valid_task_statuses`（加 cancelled/expired）、`_map_task_status`（cancelled/
  expired → failed，避免 expired 被当 RUNNING 死轮询）
- `topenrouter.model_aliases` 动态配置可覆盖模型名（JSON，驱动名 → 网关名）；
  默认别名表已清空——2026-10-29 实测网关按火山原名路由，此前的简化名推测
  （`doubao-seedance-2.0-mini` 等）会被 400 `model_not_found`（事故：任务 244）
- **真人素材三模式**（`_human_asset_config_group = "topenrouter"`，默认
  `asset_library`）：用户勾选"处理人脸"后由 `SeedanceHumanAssetMixin` 分派——
  素材库模式把 content 中的图片/视频/音频 URL 经 `SeedanceAssetClient` 上传真人库
  并替换为 `asset://<id>`；上传失败返回 SYSTEM 错误（retry=True），**不静默降级
  直传**（真人素材直传会触发上游敏感风控）。决策输入只有「enable_face_mask
  （用户勾选）+ 组模式」，`extra_config.human_review` 不再参与（每次提交现场重算，
  跨实现方重试无残留）

### 3.3 火山基类小重构（行为不变）

`task/visual_drivers/seedance_volcengine_v1_driver.py`：

- 硬编码的任务 URL 路径抽为类属性 `_create_task_path`/`_query_task_path`
- 状态枚举抽为类属性 `_valid_task_statuses`；新增 `_map_task_status()` 恒等钩子

火山国内版/海外版行为零变化（已有回归测试覆盖）。

### 3.4 注册与配置

| 文件 | 改动 |
|---|---|
| `config/unified_config.py` | `DriverImplementation` 4 常量；`DriverImplementationId` 102–105（rebase 最新 develop 时原 99–102 与视频去水印/H3 首帧参考/qwenimage2.1 让位顺延，实现方未上线落库无兼容包袱）；`IMPLEMENTATION_TO_ID`；4 个任务 `implementations` 追加（排 huimengi 后）；`ALL_IMPLEMENTATIONS` 4 条 `ImplementationConfig`（`required_config_keys=['topenrouter.api_key']`、算力对齐同任务火山档；`supports_auto_face` 字段已随三模式改造移除） |
| `config/constant.py` | `DRIVER_IMPLEMENTATION_MAPPING` 4 个 DriverKey 追加；真人素材三模式枚举（`SEEDANCE_HUMAN_ASSET_MODES`）；素材接口协议级常量（`SEEDANCE_ASSET_*`、`SEEDANCE_ASSET_URL_SCHEME`）；`TOPENROUTER_API_BASE_URL` 与 `TOPENROUTER_SEEDANCE_MODEL_ALIASES` |
| `task/visual_drivers/driver_factory.py` | try/except 注册 4 个驱动 |
| `config/default_configs.py` | `topenrouter.api_key`（敏感/快速配置）、`topenrouter.base_url`、`topenrouter.model_aliases`、`topenrouter.asset_api_key` |
| `config.example.yml` / `config_prod.base.yaml` | topenrouter 配置段 |

### 3.5 真人素材三模式（中转站级策略，后续改造沉淀）

「处理人脸」勾选后按实现方所属供应商组的 `<group>.human_asset_mode` 三选一
（模式唯一的供应商可写死，见下）：

| 模式 | 行为 | 适用 |
|---|---|---|
| `face_mask`（默认） | 本地人脸遮盖预处理（RunningHub pipeline），驱动不介入 | 直连火山/无真人库网关 |
| `asset_library` | 原图上传真人库 → `asset://` 引用，任务终态后删素材 | 官方真人库透传网关（TopenRouter/贵州本地宝类） |
| `param_pass` | payload 注入 `human_review=true` | 网关内置真人审核（huimengi） |

- 决策入口：`SeedanceHumanAssetMixin._apply_human_asset_pipeline`（模板方法，
  宿主 `build_create_request` return 处调用；不覆盖同名方法避免 MRO 遮蔽）
- 模式解析：驱动 `_resolve_human_asset_mode` / 工厂
  `VideoDriverFactory.resolve_human_asset_mode(impl_name)`（server/storyboard
  闸门共用）——声明 `_human_asset_mode_fixed` 的供应商写死模式、不读组配置
  （**TopenRouter 恒为 `asset_library`**，模式唯一无需用户选择）；否则按
  `_human_asset_config_group` 读 `<group>.human_asset_mode`，
  无组/未配置/非法值一律回落 `face_mask`
- `human_review` 不再由 server 注入、不再随 extra_config 流转：重试切换实现方后
  按新实现方模式现场重算（修复跨实现方 human_review 固化错配的根源）
- **决策输入 `extra_config.enable_face_mask` 由建任务侧写入**（用户勾选意图随任务
  流转）：storyboard 链路一直有写；server 直提交入口（`/api/run/image`，index/
  video_workflow 等）在 b3656484 改造时漏写，导致勾选「处理人脸」对
  asset_library/param_pass 实现方失效——素材直传触发上游真人风控
  `upstream_InputImageSensitiveContentDetected.PrivacyInformation` 400（事故任务
  246，2026-10-29 修复：`base_extra_config['enable_face_mask'] = bool(enable_face_mask)`）
- 接入新网关 = 驱动类声明 `_human_asset_config_group` + build_create_request/
  check_status 两处插桩 + 后台配置组键（`asset_base_url`/`asset_api_key` 素材
  地址与 Token；模式可配置的加 `human_asset_mode`，模式唯一的用
  `_human_asset_mode_fixed` 写死）；素材客户端按组凭据自动分派 Bearer /
  火山 AK/SK 签名形态（见 docs/drivers/seedance_volcengine_v1_driver.md）

## 4. 配置说明

```yaml
topenrouter:
  api_key: ""                # 必填，视频 API 与素材接口共用（sk- 开头）
  base_url: "https://tp-api.chinadatapay.com:8000"
  asset_api_key: ""          # 真人库素材接口独立 Token（与 api_key 相同时无需配置）
  asset_base_url: ""         # 真人库素材接口地址（缺省回落 base_url，同址可不配）
  model_aliases: {}          # 模型名映射 JSON，覆盖默认映射
```

TopenRouter 真人素材模式写死 `asset_library`，无 `human_asset_mode` 配置键。
huimengi 组同款 `huimengi.human_asset_mode`（默认 `param_pass`）；kkidc 未挂组
恒为本地遮盖；火山直连已挂 `volcengine` 组（默认 `face_mask`，可选 asset_library
AK/SK 签名直连官方素材库），见 docs/drivers/seedance_volcengine_v1_driver.md
「真人素材三模式」。

## 5. 已知风险

1. ~~**模型 ID 推测**~~（已消除，2026-10-29）：网关 `/v1/models` 实测原生支持火山原名，
   驱动直发原名；网关渠道后续若改名，后台改 `topenrouter.model_aliases` 热修正即可，无需发版。
2. **素材 token 共用假设**：素材 Action 接口与视频 API 按同一 Token 设计
   （`asset_api_key` 可覆盖）。若实测不同，仅需后台配置。
3. **任务耗时**：真人模式素材上传需等待 Processing→Active（轮询 1.5s 间隔，上限 120s，
   常规数秒完成），仅影响勾选人脸处理的任务。
4. 活体认证（CreateVisualValidateSession H5 流程）已封装客户端方法，未接前端路由与
   认证状态存储，后续按需接入。

## 6. 测试

- `tests/utils/test_seedance_asset_client.py`（23 例）：Action 请求构造（query/大驼峰
  body/Bearer）、两类错误结构、工厂按组解析（地址/Token 回落与缺失报错）、
  wait_asset_active 三分支
- `tests/drivers/test_seedance_topenrouter_v1_driver.py`（29 例）：模型别名映射、
  任务路径、expired/cancelled 状态、三模式分派（勾选上传/残留 human_review 重算/
  face_mask 不介入/param_pass 注入/上传失败 SYSTEM 错误/终态素材回收）、
  模式解析回落语义、4 子类实例化
- 火山/海外版回归：`tests/drivers/test_seedance_volcengine_v1_driver.py` 等既有测试
