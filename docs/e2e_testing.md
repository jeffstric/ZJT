# 端到端浏览器自动化测试

本项目提供两种端到端测试方案：AI 智能体驱动（JSON 测试用例）和编程式自动化（pytest + Playwright）。

## 目录结构

```
auto_test/
├── test_modules/              # JSON 测试用例（AI 智能体驱动）
│   ├── index.json             # 模块索引（含依赖关系）
│   └── *.json                 # 15 个模块的测试用例
├── e2e/                       # 编程式 E2E 测试（pytest + Playwright）
│   ├── conftest.py            # 核心 fixtures
│   ├── pytest.ini             # pytest 配置
│   ├── helpers/
│   │   ├── api_client.py      # httpx 异步 API 客户端
│   │   └── page_objects.py    # Page Object 基类
│   ├── test_auth.py           # 认证模块（3 个 P0）
│   ├── test_session.py        # 会话管理（5 个 P0）
│   ├── test_world.py          # 世界 CRUD（5 个 P0）
│   ├── test_character.py      # 角色 CRUD（4 个 P0）
│   ├── test_location.py       # 场景 CRUD（5 个 P0）
│   ├── test_workflow.py       # 工作流 CRUD（5 个 P0）+ 保存 CAS 乐观锁 409（4 个 P1）
│   ├── test_workflow_page.py  # 工作流前端页面（3 个 P0）
│   ├── test_announcements.py  # 本站公告：用户侧已读/未读 + 管理侧生命周期/图片上传（10 个 P1）
│   ├── test_audio.py          # 音频模块（2 个 P0）
│   ├── test_script_writer.py  # 剧本编辑器页面（2 个 P0）
│   ├── test_marketing_agent.py# 营销智能体页面（3 个 P0）
│   └── test_admin.py          # 管理后台（1 个 P0）
├── test_assets/               # 测试资源文件
├── test_config.json           # 测试配置文件
└── test_sessions/             # 测试会话记录
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements_e2e.txt
playwright install chromium
```

若本机已有 Chromium 内核浏览器但未下载 Playwright Chromium，可显式指定其可执行文件；
CI 不设置此变量，仍使用 Playwright 管理的 Chromium：

```powershell
$env:E2E_BROWSER_EXECUTABLE = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
```

## GitLab CI 分支触发

仓库的 `e2e_smoke` job 会在分支 push 或 Merge Request Pipeline 中自动运行。已有 Merge Request 的源分支只创建 MR Pipeline，避免同一次 push 重复执行 branch 与 MR 两条流水线。

每个 job 以 `e2e-${CI_PIPELINE_ID}-${CI_JOB_ID}` 作为 Docker Compose project 名，启动一套临时环境：

| 服务 | 职责 | 隔离方式 |
|------|------|----------|
| `mysql` | 当前 Pipeline 的 E2E 数据库 | 独立数据卷，结束后删除 |
| `prepare` | 执行 Alembic 迁移、创建两个一次性账号、开启测试挡板 | 一次性容器，执行后退出 |
| `app` | 运行当前 commit 的 FastAPI 服务 | 不暴露宿主机端口，只加入 Compose 网络 |
| `e2e` | 运行 pytest、Playwright 和 Chromium | 通过 `http://app:9003` 访问被测服务 |

当前自动门禁是 `ci_smoke and p0`，覆盖认证、会话、世界、工作流 API 和工作流页面。需要媒体样本或外部模型的全量 E2E 暂不在每次 push 中执行，后续可作为定时或手动 job 接入。

流水线结束时，无论成功或失败都会：

1. 将 JUnit、HTML 报告以及失败测试的截图和 Playwright Trace 复制到 `e2e-results/`。
2. 将 MySQL 与应用日志写入 `e2e-results/services.log`。
3. 删除本次 Pipeline 创建的容器、网络及数据卷。

CI 使用临时数据库中的固定一次性凭据，不依赖生产账号或 GitLab Secret。可通过同名 CI/CD Variables 覆盖 `E2E_TEST_PHONE`、`E2E_TEST_PASSWORD`、`E2E_SECONDARY_PHONE` 和 `E2E_SECONDARY_PASSWORD`，但不得配置生产凭据。

E2E Runner 默认通过 DaoCloud 公共镜像代理拉取 Playwright 基础镜像，避免国内 Runner 直连 `mcr.microsoft.com` 时因约 800 MB 浏览器镜像下载过慢而耗尽 Job 时间。

应用镜像先复制依赖清单并安装依赖，再复制源码，支持在具有 Docker layer cache 的环境中复用依赖层。镜像内使用 `uv` 并发解析和下载 Python 包；在 jeffNas1 Runner 的全新 `python:3.10-slim` 容器中，完整解析、下载及安装实测约 1 分钟，而原先的 pip 串行下载在慢速连接下会持续数十分钟。

`mcp` 固定为与 `fastapi==0.111.0` / Starlette 0.37.x 兼容的 `1.12.4`，避免 pip 在 CI 中从 2.x 向下尝试大量历史版本。`e2e_smoke` 声明了 90 分钟 job timeout，但 GitLab 实例或项目的最大超时仍可能将其限制为 60 分钟；依赖安装加速用于确保正常构建不依赖放宽该上限。

需要切换其他镜像仓库时，可覆盖 Dockerfile 的构建参数：

```bash
docker build \
  --build-arg PLAYWRIGHT_BASE_IMAGE=<registry>/playwright/python:v1.60.0-noble \
  -f docker/Dockerfile.e2e \
  -t zjt-e2e-runner:local \
  .
```

### 本地复现 CI 冒烟测试

```bash
docker compose -p zjt-e2e-local -f docker/docker-compose-e2e.yml build app e2e
docker compose -p zjt-e2e-local -f docker/docker-compose-e2e.yml up -d mysql
docker compose -p zjt-e2e-local -f docker/docker-compose-e2e.yml run --rm prepare
docker compose -p zjt-e2e-local -f docker/docker-compose-e2e.yml up -d app
docker compose -p zjt-e2e-local -f docker/docker-compose-e2e.yml run --name zjt-e2e-result e2e
docker cp zjt-e2e-result:/results/. e2e-results/
docker compose -p zjt-e2e-local -f docker/docker-compose-e2e.yml down -v --remove-orphans
```

本地中断后再次执行前，应先运行最后一条 `down` 命令清理该固定 project 名对应的临时资源。

### 2. 配置

复制 `test_config.example.json` 为 `test_config.json`，填写：
- `base_url`: 服务器地址（当前默认 http://localhost:9003）
- `credentials.primary`: 测试账号手机号和密码
- `test_assets`: 测试资源文件路径

### 3. 准备测试资产

E2E 需要两类资产，作用不同，不能混用：

| 资产类别 | 位置 | 谁使用 | 用途 |
|----------|------|--------|------|
| 输入资产 | `auto_test/test_assets/`，由 `auto_test/test_config.json` 引用 | 测试用例 | 上传图片、视频、音频作为用户输入 |
| Mock 输出资产 | `auto_test/samples/` -> `upload/mock/` | 后端挡板 | 伪造外部生成 API 的返回结果 |

#### 3.1 输入资产

`auto_test/test_config.json` 默认需要：

| 配置项 | 默认路径 | 要求 |
|--------|----------|------|
| `test_assets.test_image` | `auto_test/test_assets/test_image.jpg` | 普通 jpg/png 图片 |
| `test_assets.test_video` | `auto_test/test_assets/test.mp4` | 可播放 mp4 |
| `test_assets.test_voice` | `auto_test/test_assets/test.wav` | 可读 wav 音频 |

这些文件是“测试上传用”的输入素材。例如测试图片上传、视频上传、声音上传时会读取它们。

#### 3.2 Mock 输出资产

当需要跑带媒体生成链路的 E2E 时，外部付费生成 API 会被 mock 挡板替换成本地文件。先把样本文件放到 `auto_test/samples/`，再执行：

```powershell
python scripts/prepare_mock_assets.py
```

脚本会复制到 `upload/mock/`。必需文件如下：

| auto_test/samples 文件 | 输出路径 | 用途 | 备注 |
|--------------|----------|------|------|
| `e2e_text_to_image.png` | `/upload/mock/e2e_text_to_image.png` | 文生图/普通视觉图片结果 | 可复用普通图片 |
| `e2e_image_edit.png` | `/upload/mock/e2e_image_edit.png` | 图编结果 | 可复用普通图片 |
| `e2e_comfyui_tti.png` | `/upload/mock/e2e_comfyui_tti.png` | Agent 工具直调文生图结果 | 可复用普通图片 |
| `e2e_comfyui_ie.png` | `/upload/mock/e2e_comfyui_ie.png` | Agent 工具直调图编结果 | 可复用普通图片 |
| `e2e_grid_2x2.png` | `/upload/mock/e2e_grid_2x2.png` | 四宫格结果 | 必须是真实 2x2 拼图，方便拆成 4 张 |
| `e2e_ma_front.png` | `/upload/mock/e2e_ma_front.png` | 多角度正面图 | 普通图片 |
| `e2e_ma_side.png` | `/upload/mock/e2e_ma_side.png` | 多角度侧面图 | 普通图片 |
| `e2e_ma_back.png` | `/upload/mock/e2e_ma_back.png` | 多角度背面图 | 普通图片 |
| `e2e_i2v.mp4` | `/upload/mock/e2e_i2v.mp4` | 图生视频结果 | 可播放 mp4 |
| `e2e_t2v.mp4` | `/upload/mock/e2e_t2v.mp4` | 文生视频结果 | 可播放 mp4 |
| `e2e_dh.mp4` | `/upload/mock/e2e_dh.mp4` | 数字人结果 | 可播放 mp4 |
| `e2e_face_mask.mp4` | `/upload/mock/e2e_face_mask.mp4` | 人脸遮盖结果 | 下游会校验真实文件存在 |
| `e2e_tts.mp3` | `/upload/mock/e2e_tts.mp3` | TTS 结果 | 可播放 mp3 |
| `e2e_char.mp3` | `/upload/mock/e2e_char.mp3` | RunningHub 角色音频结果 | 可播放 mp3 |
| `world_export_sample.zip` | `/upload/mock/world_export_sample.zip` | 世界导入样本 | 仅世界导入测试需要 |

临时本地验证时，普通图片类可以复用同一张图，视频类可以复用同一个短 mp4，音频类可以复用同一个 mp3。只有 `e2e_grid_2x2.png` 建议单独准备真实 2x2 拼图。

### 4. 启用 E2E Mock 挡板

媒体生成相关 E2E 建议使用全局开启方式：先写入动态配置，再重启服务。

```powershell
$env:comfyui_env="prod"  # 按实际测试环境设置；不设置时默认写入 dev
$env:E2E_TEST_USER_ID="<测试账号 user_id>"
python scripts/enable_test_mode.py
```

该脚本会：

1. 设置 `test_mode.enabled=True`
2. 写入 `test_mode.mock_images.*`、`test_mode.mock_videos.*`、`test_mode.mock_audio.*`
3. 将测试账号算力重置到高值，避免真实扣费链路扣穿

注意：

- 脚本写的是数据库动态配置，因此数据库必须可连。
- 动态配置按 `comfyui_env` 分环境写入；跑 prod 环境 E2E 前必须设置 `$env:comfyui_env="prod"`。
- 写完后建议重启后端服务，避免服务进程和 `SyncTaskExecutor` 子进程仍读到旧缓存。
- `auto_test/e2e/conftest.py` 也提供了 `mock_mode` fixture，但当前现有 E2E 用例尚未统一声明它；跑现有全量测试时仍推荐先执行上面的全局脚本。

### 5. 启动后端服务

`auto_test/test_config.json` 默认指向 `http://localhost:9003`。Windows 开发环境常用：

```powershell
uv run scripts/launchers/start_windows.py
```

或直接运行：

```powershell
start.bat
```

启动后可先检查：

```powershell
Invoke-WebRequest http://localhost:9003/api/config/upload
Invoke-WebRequest http://localhost:9003/upload/mock/e2e_text_to_image.png
```

### 6. 运行测试

```bash
cd auto_test/e2e

# 运行所有 P0 测试
python -m pytest -v -m p0

# 运行指定模块
python -m pytest -v -m auth
python -m pytest -v -m session
python -m pytest -v -m world

# 运行所有测试
python -m pytest -v

# 保留失败截图和 Playwright Trace，便于定位页面跳转或 UI 超时
$env:E2E_RESULTS_DIR = "e2e-results"
python -m pytest -v

# 生成 HTML 报告
python -m pytest -v --html=reports/report.html --self-contained-html
```

> 本地运行时需让 pytest 进程与被测服务读同一份配置：`comfyui_env` 未设置时
> 默认找 `config_dev.yml`（本机通常只有 `config_prod.yml`），`mock_mode` fixture
> 等需要直连数据库动态配置的步骤会失败（现为非致命告警，但挡板实际不生效）。
> 与被测服务保持一致，例如：`comfyui_env=prod python -m pytest -v`。

建议第一次不要直接跑全量，先跑无生成链路和小范围生成链路：

```powershell
cd auto_test/e2e
python -m pytest test_auth.py test_world.py -v
python -m pytest test_audio.py test_grid_image.py -v
```

## E2E 运行前检查清单

### 认证会话约束（单会话策略与 live_auth 自愈）

登录接口是**单会话策略**：同一用户任何一次新登录都会删除该用户全部旧 token
（`auth_service.py` `delete_by_user_id`）。因此：

- 套件内所有会真正登录主账号的用例都必须避免。`test_auth.py` 的
  `test_login_success` / `test_logout_success` 已改用**次账号**（`credentials.secondary`）
  做登录/登出验证，主账号的登录负向用例（错误密码、空手机号等）不会真正登录、不会顶号。
- 单次 pytest 运行中不得调用 `refresh_login`；需要独立浏览器上下文的用例应复用
  `auth_token`/`user_id`/`live_auth` fixture 注入认证信息。
- 若 token 仍被套件外的新登录顶掉（手动 UI 登录、另一个 e2e/脚本并发登录主账号），
  `conftest.py` 的 `live_auth`（session 级"活凭证"）会在每个用例创建请求/浏览器
  上下文前 `ensure()` 校验一次：失效则自动重登主账号，并原地更新共享的
  `auth_headers` dict（已创建的 api_client 自动用上新 token）。`auth_token`/`user_id`
  两个 fixture 已改为 function 级、返回 `live_auth` 的当前值，用例里直接放
  body/URL 的 token 也随之自愈。实际登录仍只发生在 `_login_data`（session 级）一次，
  自愈重登只顶掉已失效的旧 token。
  注意：探活接口仅 **401 或响应体 `error_code=invalid_auth_token`** 才判定 token 失效
  触发重登；其余非 200（400/500 等）视为接口自身问题，不重登——避免接口回归被
  反复重登掩盖成假绿。

- [ ] `auto_test/test_config.json` 的 `base_url` 指向当前后端服务。
- [ ] `auto_test/test_assets/test_image.jpg` 存在。
- [ ] `auto_test/test_assets/test.mp4` 存在。
- [ ] `auto_test/test_assets/test.wav` 存在。
- [ ] `auto_test/samples/` 下已准备 mock 样本文件。
- [ ] 已运行 `python scripts/prepare_mock_assets.py`，`upload/mock/` 下文件存在。
- [ ] 已运行 `python scripts/enable_test_mode.py` 写入动态配置。
- [ ] 执行 `enable_test_mode.py` 后已重启后端服务，或至少等待动态配置缓存过期。
- [ ] 测试账号可登录，且 `E2E_TEST_USER_ID` 与该账号一致。
- [ ] Playwright Chromium 已安装。
- [ ] 时间轴相关测试所需 `ffmpeg`/`ffprobe` 可用。

## 常见问题

### `mock_mode` 和 `enable_test_mode.py` 的区别

- `mock_mode` 是 pytest fixture，适合新写的 E2E 用例显式声明依赖。
- `enable_test_mode.py` 是全局准备脚本，适合跑现有 E2E 或手工调试。

当前现有 E2E 用例没有统一声明 `mock_mode`，所以跑现有用例时优先使用 `enable_test_mode.py`。

### `test_config.json` 里为什么只有图片、视频、音频 3 个资产？

因为它们是测试输入资产，由测试用例主动上传。

`e2e_text_to_image.png`、`e2e_i2v.mp4`、`e2e_tts.mp3` 等是 mock 输出资产，由后端挡板通过动态配置读取，不写在 `test_config.json` 里。

### 媒体任务仍然访问真实外部服务

通常是以下原因：

1. 没有执行 `enable_test_mode.py`
2. 执行后没有重启后端服务，进程缓存仍是旧值
3. mock URL 没写入动态配置
4. E2E 用例没有声明 `mock_mode`，又没有使用全局脚本

### 四宫格任务完成但角色/场景/道具没有参考图

检查 `upload/mock/e2e_grid_2x2.png` 是否是真实 2x2 拼图。四宫格 mock 会强制落盘并拆图，如果文件不是有效图片或不是 2x2 布局，下游效果会不可靠。

### 登录失败或算力重置失败

确认：

1. 后端服务和数据库可用。
2. `auto_test/test_config.json` 中账号密码正确。
3. `E2E_TEST_USER_ID` 是同一个测试账号的 user_id。

## Fixture 架构

```
e2e_config (session) ─── 读取 test_config.json
├── _login_data (session) ─── 主账号只登录一次
├── live_auth (session) ─── 活凭证：token 失效时自动重登（ensure()）
├── auth_token (function) ─── 返回 live_auth 当前 token
├── user_id (function) ─── 返回 live_auth 当前 user_id
├── auth_headers (session) ─── Authorization + X-User-Id（dict 被 live_auth 原地更新）
├── browser (session) ─── Playwright chromium 实例
│   └── browser_context (function) ─── 注入 localStorage 认证
│       └── page (function) ─── 独立页面实例
└── api_client (function) ─── httpx.Client
    ├── test_world (function) ─── 创建测试世界，yield 后清理
    │   ├── test_character (function) ─── 创建测试角色
    │   └── test_location (function) ─── 创建测试场景
    ├── test_workflow (function) ─── 创建测试工作流
    └── test_session_id (function) ─── 创建测试会话
```

### 关键设计

- **认证跳过 UI**：通过 API 登录获取 token，注入 localStorage，避免反复 UI 登录
- **API 客户端**：使用 httpx.Client（同步），不阻塞服务端事件循环
- **测试数据工厂**：`test_world`、`test_workflow` 等 fixture 自动创建和清理测试数据

## 测试标记

| 标记 | 说明 |
|------|------|
| `p0` | P0 核心功能（必须通过） |
| `p1` | P1 重要功能（应该通过） |
| `p2` | P2 次要功能（可选通过） |
| `auth` | 认证模块 |
| `session` | 会话管理模块 |
| `world` | 世界管理模块 |
| `character` | 角色管理模块 |
| `location` | 场景管理模块 |
| `workflow` | 工作流 CRUD 模块 |
| `workflow_page` | 工作流前端页面模块 |
| `audio` | 音频模块 |
| `script_writer` | 剧本编辑器模块 |
| `marketing_agent` | 营销智能体模块 |
| `admin` | 管理后台模块 |

## 模块依赖关系

```
auth (无依赖)
├── workflow_list
├── world_management
│   ├── location_management
│   └── character_management
├── workflow_editor
│   ├── node_operations
│   │   ├── shot_frame_video
│   │   ├── shot_group_video
│   │   └── camera_control
│   ├── timeline
│   ├── grid_image_generation
│   └── audio
├── error_handling
└── marketing_agent
```

## 近期功能 e2e 覆盖补充（2026-09，develop_f804）

针对近一个月功能提交补齐的端到端用例：

| 功能 | 提交 | 覆盖位置 | 说明 |
|------|------|----------|------|
| 本站公告（用户侧铃铛 + 管理侧配置） | ee890760 / 6a3c0400 | `test_announcements.py`（10 个 P1） | 用户侧列表/未读数/单条已读/read-all；管理侧创建-发布-下线-删除全生命周期、编辑、非法 publish_at 拒绝、非管理员权限负向、图片上传与拒非图片 |
| 工作流保存 CAS 乐观锁（409） | 719e0032 / 2ff48436 | `test_workflow.py::TestWorkflowSaveCAS`（4 个 P1） | 详情返回 `content_hash`；正确 `X-Base-Hash` 保存成功；过期基线被 409 拒绝并回传当前哈希且内容不被覆盖；不带基线的强制写路径兼容 |
| 推荐模型档位管理员可配 | d6e57884 | `test_admin_api.py`（admin_api_019/020） | GET 各场景 value/quality 双档 + 候选；PUT reset 回退与未知场景 400 |
| `/api/models` id 数值化 | 1619353a / e4d54994 | `test_script_writer_api.py::test_api_get_models` 增强 | 断言 id 为数值库 ID 字符串（无 `vendor:` 复合串），且条目含 `name`/`vendor_id`（前端模型记忆契约） |

注意：CAS 内容哈希只覆盖 `workflow_data`/`style`/`style_reference_image`/`default_world_id`/`workflow_ratio`（`name` 与 `viewport` 不参与），测试中推进哈希需用参与哈希的字段。

不建议 e2e 覆盖（依赖外部服务/真实触发条件，本测试环境不可达）：内容审核违规原文透出（4db4491c）、TTS 语速滑杆（93224407）、MiniMax H3 文生视频驱动（c28003b2）、小米 MiMo 供应商（432f9cb5）——相关行为由 `tests/` 单测与前端 vitest 覆盖。

## 两种测试方案对比

| 维度 | JSON 测试 (AI 智能体) | pytest E2E (编程式) |
|------|----------------------|-------------------|
| 驱动方式 | AI 解读 JSON，调用 MCP 工具 | 编程式 Playwright API |
| 执行速度 | 慢（AI 推理 + MCP 通信） | 快（直接 API 调用） |
| 稳定性 | 受 AI 理解准确性影响 | 确定性高 |
| 适合场景 | 探索性测试、新功能验证 | 回归测试、CI/CD |
| 维护方式 | JSON 文件编辑 | Python 代码 |

## 添加新测试

1. 在 `e2e/` 目录创建 `test_<模块名>.py`
2. 使用 `conftest.py` 中的 fixtures
3. 添加 pytest markers：`@pytest.mark.<模块名>` 和 `@pytest.mark.p0`
4. 使用 Page Object 模式操作浏览器页面
5. 更新本文档
