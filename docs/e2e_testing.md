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
│   ├── test_workflow.py       # 工作流 CRUD（5 个 P0）
│   ├── test_workflow_page.py  # 工作流前端页面（3 个 P0）
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
pip install playwright pytest-html pytest-timeout pytest-asyncio
playwright install chromium
```

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

# 生成 HTML 报告
python -m pytest -v --html=reports/report.html --self-contained-html
```

建议第一次不要直接跑全量，先跑无生成链路和小范围生成链路：

```powershell
cd auto_test/e2e
python -m pytest test_auth.py test_world.py -v
python -m pytest test_audio.py test_grid_image.py -v
```

## E2E 运行前检查清单

### 认证会话约束

`auto_test/e2e/conftest.py` 的 `auth_token` 和 `user_id` 均为 session 级 fixture。测试账户的登录接口会使同一用户此前签发的 token 失效，因此单次 pytest 运行中不得调用 `refresh_login`；需要独立浏览器上下文的用例应复用这两个 fixture 注入认证信息。

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
├── auth_token (session) ─── API 登录获取 token
├── user_id (session) ─── 登录返回的 user_id
├── auth_headers (session) ─── Authorization + X-User-Id
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
