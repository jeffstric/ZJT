# 🛠️ 开发者指南

> 如果你需要修改代码或参与开发，请阅读本文档。

## 环境要求

- Python 3.9+（建议 3.10.12）
- MySQL 8.0.45+
- uv 包管理器
- FFmpeg（视频处理）

## 安装依赖

```bash
# 方式 1：使用 conda
conda create --name zjt python=3.10
conda activate zjt
pip install -r requirements.txt

# 方式 2：使用 uv（推荐）
uv sync
```

如使用国内镜像，追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

---

## 启动方式

### Windows 批处理启动

**📌 详细说明：[Windows启动开发说明.md](Windows启动开发说明.md)**

```powershell
# 开发环境
$env:comfyui_env="dev"
uv run scripts/launchers/start_windows.py

# 生产环境（默认）
uv run scripts/launchers/start_windows.py
```

或直接双击 `start.bat`（显示日志，适合调试）。

`scripts/launchers/start_windows.py` 会自动：
1. 检查 Python 和 uv 环境
2. 启动本地 MySQL 服务（首次自动初始化）
3. 执行数据库迁移
4. 启动 Web 服务和定时任务
5. 监控服务状态，异常时自动重启

### Linux/macOS 启动

```bash
# 1. 复制配置文件（首次运行）
cp config.example.yml config_prod.yml

# 2. 修改数据库配置（重要！）
# 编辑 config_prod.yml，修改以下配置项：
#   - database.host: 数据库地址
#   - database.port: 数据库端口（默认 3306）
#   - database.user: 数据库用户名
#   - database.password: 数据库密码
#   - database.name: 数据库名称

# 3. 导入数据库基线（首次运行）
mysql -u root -p your_database < model/sql/baseline.sql

# 4. 启动服务
# 生产环境
python3 scripts/running/run_prod.py

# 或开发环境
python3 scripts/running/run_dev.py
```

### run_prod.py 与 run_dev.py 的区别

| 启动方式 | 配置文件 | 日志级别 | 用途 |
|----------|----------|----------|------|
| `scripts/running/run_prod.py` | `config_prod.yml` | WARNING | 生产环境，日志精简 |
| `scripts/running/run_dev.py` | `config_dev.yml` | DEBUG | 开发环境，日志详细 |

---

## 配置说明

配置文件位于项目根目录：
- `config.yml` - 生产环境配置
- `config_dev.yml` - 开发环境配置
- `config.example.yml` - 配置模板

### 核心配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `server.host` | 服务地址 | `http://localhost:9003` |
| `server.port` | 服务端口 | `9003` |
| `server.is_local` | 是否本地环境 | `true` |
| `database.*` | MySQL 连接配置 | - |

### 外部服务配置

| 配置项 | 说明 |
|--------|------|
| `runninghub.*` | RunningHub 视频生成 API |
| `llm.baidu.*` | 百度千帆大模型 |
| `llm.qwen.*` | 阿里通义千问 |
| `llm.google.*` | Google Gemini |
| `tts.*` | TTS 语音合成服务 |
| `duomi.*` | 多米 API（图生视频） |
| `vidu.*` | Vidu API（视频生成） |

### 功能配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `task_queue.max_retry_count` | 任务最大重试次数 | `30` |
| `task_queue.task_expire_days` | 任务过期天数 | `7` |
| `upload.max_image_size_mb` | 图片上传大小限制 | `10` MB |
| `workflow.poll_status_interval` | 工作流状态轮询间隔 | `30` 秒 |
| `alembic.auto_migrate` | 启动时自动迁移 | `true` |
| `edition.mode` | 版本模式 | `community` |

### 文件存储配置

支持七牛云存储，配置 `file_storage.qiniu.*`：
- `access_key` / `secret_key` - 七牛云密钥
- `bucket_name` - 存储空间名称
- `cdn_domain` - CDN 加速域名

---

## 数据库迁移

本项目使用 Alembic 进行数据库迁移管理。

**📌 详细说明：[database_migration.md](database_migration.md)**

### 常用命令

```bash
# 查看迁移历史
alembic history

# 查看当前版本
alembic current

# 升级到最新版本
alembic upgrade head

# 回滚一个版本
alembic downgrade -1

# 创建新迁移
alembic revision -m "描述信息"
```

### 初始化新数据库

1. 执行 `model/sql/baseline.sql` 创建基础表
2. 执行 `alembic stamp head` 标记为最新版本

---

## 测试模式

测试模式用于在不调用真实 API 的情况下测试业务流程。

**📌 详细说明：[test_mode_guide.md](test_mode_guide.md)**

```yaml
# config.yml
test_mode:
  enabled: true
  mock_videos:
    image_to_video: "http://example.com/test.mp4"
    text_to_video: "http://example.com/test.mp4"
  mock_images:
    image_edit: "http://example.com/test.png"
    text_to_image: "http://example.com/test.png"
```

---

## Debug 模式

前端 Debug 模式用于查看节点的完整数据结构。

**📌 详细说明：[debug_mode.md](debug_mode.md)**

1. 配置密码：`frontend.debug_password`
2. 点击页面顶部 **Debug** 按钮
3. 节点标题栏出现 🐛 按钮，点击查看控制台输出

---

## 打包工具

### Windows 托盘启动器打包

**📌 详细说明：[scripts/build/README.md](../scripts/build/README.md)**

本项目提供自动化打包工具，用于生成带托盘功能的 Windows 可执行文件：

```bash
# 方法一：使用批处理脚本（推荐）
scripts\build\build.bat

# 方法二：直接运行 Python 脚本
python scripts\build\build_launcher.py
```

打包工具会自动：
- 检查并安装必需的依赖（pystray、PIL、PyInstaller）
- 清理之前的构建文件
- 使用正确的参数打包
- 验证输出文件

**输出文件**：`点我启动.exe` - 包含完整托盘功能的可执行程序

**托盘功能**：
- 系统托盘图标显示启动状态
- 右键菜单（打开浏览器、查看日志、退出）
- 自动打开浏览器
- 单实例检测防止重复启动

---

## 目录结构

```
comfyui_server/
├─ 点我启动.exe               # Windows 托盘启动器（推荐）
├─ start.bat                  # Windows 启动脚本（显示日志）
├─ stop.bat                   # Windows 停止脚本
├─ start.command              # macOS 启动脚本
├─ stop.command               # macOS 停止脚本
├─ scripts/                   # 脚本目录
│  ├─ build/                  # 打包工具目录
│  │  ├─ build_launcher.py    # 主打包脚本
│  │  ├─ build.bat            # 批处理打包脚本
│  │  └─ README.md            # 打包工具说明
│  ├─ launchers/              # 启动器脚本
│  │  ├─ launcher.py          # Windows 托盘启动器源码
│  │  ├─ launcher_mac.py      # macOS 托盘启动器源码
│  │  ├─ start_windows.py     # Windows 启动逻辑
│  │  └─ start_mac.py         # macOS 启动逻辑
│  ├─ running/                # 运行脚本
│  │  ├─ run_prod.py          # 生产环境启动器
│  │  ├─ run_dev.py           # 开发环境启动器
│  │  ├─ run_scheduler.py     # 定时任务启动器
│  │  └─ run_unit_tests.py    # 单元测试启动器
│  ├─ testing/                # 测试脚本
│  │  ├─ run_driver_tests.sh  # 驱动测试脚本
│  │  └─ run_tests.sh         # 测试脚本
│  ├─ tools/                  # 工具脚本
│  │  ├─ create_mac_app.sh    # macOS 应用创建脚本
│  │  ├─ create_shortcuts.vbs # Windows 快捷方式创建脚本
│  │  ├─ start_silent.vbs     # Windows 静默启动脚本
│  │  └─ obfuscate.sh         # 混淆脚本
│  └─ startup/                # 启动脚本
│     └─ linux_start_prod.sh  # Linux 生产启动脚本
├─ server.py                  # FastAPI 后端主入口
│
├─ api/                       # API 路由模块
├─ model/                     # 数据模型 & ORM
├─ task/                      # 后台任务（视频、音频、图片）
├─ llm/                       # LLM 集成（百度、阿里、Google）
├─ utils/                     # 工具函数
├─ script_writer_core/        # 剧本创作核心逻辑
├─ config/                    # 配置管理模块
│
├─ web/                       # 前端静态文件
├─ static/                    # 静态资源
├─ templates/                 # Jinja2 模板
│
├─ alembic/                   # 数据库迁移脚本
├─ bin/                       # 二进制工具（MySQL、FFmpeg）
├─ files/                     # 用户上传文件存储
├─ logs/                      # 日志目录
├─ tests/                     # 单元测试
├─ auto_test/                 # 自动化测试
└─ docs/                      # 文档
```

---

## 相关文档

| 文档 | 说明 |
|------|------|
| [scripts/build/README.md](../scripts/build/README.md) | Windows 托盘启动器打包工具使用指南 |
| [Windows启动开发说明.md](Windows启动开发说明.md) | Windows 启动流程详解 |
| [database_migration.md](database_migration.md) | 数据库迁移指南 |
| [test_mode_guide.md](test_mode_guide.md) | 测试模式使用指南 |
| [debug_mode.md](debug_mode.md) | Debug 模式说明 |
| [mysql_startup.md](mysql_startup.md) | MySQL 启动说明 |
| [bin_path_config.md](bin_path_config.md) | 二进制路径配置 |
| [常量使用示例.md](常量使用示例.md) | 常量定义与使用 |
| [短信驱动架构说明.md](短信驱动架构说明.md) | 短信服务架构 |

---

## 常见问题

- **数据库迁移失败** - 检查迁移文件编码是否为 UTF-8，确保 `PYTHONUTF8=1` 环境变量已设置
- **MySQL 启动失败** - 确保 `bin/mysql` 目录存在且完整，检查端口 3306 是否被占用
- **ComfyUI 调用失败** - 检查 ComfyUI 服务是否运行，配置文件中地址是否正确
- **前端无法访问** - 检查端口是否被占用，查看 `logs/` 目录下的日志
- **视频生成失败** - 检查 RunningHub/Duomi/Vidu API 配置是否正确
- **TTS 合成失败** - 检查 `tts.api_url` 配置
