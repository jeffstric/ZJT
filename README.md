# 智剧通 AI短剧制作平台

智剧通是一个基于 AI 的短剧制作平台，提供剧本创作、角色管理、视频生成、音频合成等一站式短剧制作解决方案。

## 主要功能

- **剧本创作** - AI 辅助剧本编写、角色设计、场景规划
- **视频生成** - 支持图生视频、文生视频、视频编辑
- **音频合成** - TTS 语音合成、背景音乐生成
- **工作流编排** - 可视化工作流编辑器，支持节点拖拽连接
- **任务管理** - 后台任务队列、进度跟踪、定时任务

## 运行环境
- Python 3.9+（建议 3.10.12）

## 数据库

mysql 8.0.45+

## 安装依赖
在项目根目录（与 `requirements.txt` 同级）执行：

```bash
conda create --name zjt python=3.10
conda activate zjt
pip install -r requirements.txt
```

如使用国内镜像，可在最后一行追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

## 启动后端

### 方式 1：点我启动.exe（推荐）

**最简单的启动方式**，双击 `点我启动.exe` 即可：

- ✅ 系统托盘图标显示启动状态
- ✅ 服务就绪后自动打开浏览器
- ✅ 右键菜单支持：打开浏览器、查看日志、退出
- ✅ 退出时自动停止所有服务（包括 MySQL）
- ✅ 单实例检测，防止重复启动

**快速开始**：
1. 确保已安装 Python 3.10+ 和 uv
2. 将 MySQL 解压到 `bin/mysql` 目录
3. 复制 `config.example.yml` 为 `config.yml` 并配置（首次启动会自动创建）
4. 双击 `点我启动.exe` 即可

### 方式 2：批处理脚本启动

**📌 详细说明请查看：[Windows启动开发说明.md](docs/Windows启动开发说明.md)**

#### start.bat - 启动服务（显示日志）
- ✅ 显示详细的启动日志和运行状态
- ✅ 适合首次启动和问题排查
- 📝 双击即可运行

#### stop.bat - 停止服务
- ✅ 一键停止所有服务（MySQL + Python）
- 📝 双击即可运行

`start_windows.py` 会自动：
1. 检查 Python 和 uv 环境
2. 启动本地 MySQL 服务（首次启动时自动初始化）
3. 设置数据库密码并导入表结构
4. 启动 Web 服务和定时任务
5. 监控服务状态，异常时自动重启

### 方式 3：使用 uv 启动（命令行）

[uv](https://docs.astral.sh/uv/) 是一个快速的 Python 包管理器，会自动管理依赖和虚拟环境。

**安装 uv**（首次使用）：
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**启动服务**：
```powershell
# 开发环境
$env:comfyui_env="dev"
uv run start_windows.py

# 生产环境（默认）
uv run start_windows.py
```

### 方式 4：手动启动（Linux/macOS）

```bash
# 激活虚拟环境后
python3 server.py
```

默认监听端口为配置文件中的 `server.port`（默认 9003）。浏览器访问：
- 前端首页：`http://localhost:9003/`
- API 文档：`http://localhost:9003/docs`

## 配置说明

配置文件位于项目根目录，按环境区分：
- `config.yml` - 生产环境配置
- `config_dev.yml` - 开发环境配置
- `config.example.yml` - 配置模板

主要配置项：
- `server.port` - 服务监听端口（默认 9003）
- `database.*` - MySQL 数据库连接配置
- `comfyui.server` - ComfyUI 服务地址
- `llm.*` - 大语言模型 API 配置
- `tts.*` - 语音合成服务配置

### 测试模式配置

项目支持测试模式，用于在不调用真实外部 API 的情况下测试完整业务流程。详细说明请参考 `docs/test_mode_guide.md`。

快速启用测试模式：

1. 在 `config.yml` 中配置：
```yaml
test_mode:
  enabled: true  # 启用测试模式
  mock_videos:
    image_to_video: "http://localhost:5178/upload/test_video.mp4"
    text_to_video: "http://localhost:5178/upload/test_video.mp4"
  mock_images:
    image_edit: "http://localhost:5178/upload/test_image.png"
    text_to_image: "http://localhost:5178/upload/test_image.png"
```

2. 准备测试资源文件并放置在 `upload/` 目录下

3. 重启服务即可使用测试模式

## 目录结构
```
comfyui_server/
├─ 点我启动.exe               # Windows 托盘启动器（推荐）
├─ start.bat                  # Windows 启动脚本
├─ stop.bat                   # Windows 停止脚本
├─ launcher.py                # 启动器源码
├─ start_windows.py           # Windows 启动逻辑
├─ server.py                  # FastAPI 后端主入口
├─ run_prod.py                # 生产环境启动器
├─ run_dev.py                 # 开发环境启动器
├─ requirements.txt           # Python 依赖
├─ config.example.yml         # 配置模板
├─ LICENSE                    # 开源协议
├─ alembic/                   # 数据库迁移脚本
├─ api/                       # API 路由模块
├─ model/                     # 数据模型
├─ task/                      # 后台任务
├─ llm/                       # LLM 集成
├─ utils/                     # 工具函数
├─ script_writer_core/        # 剧本创作核心
├─ web/                       # 前端静态文件
├─ static/                    # 静态资源
├─ templates/                 # 模板文件
├─ bin/                       # 二进制工具（MySQL、ffmpeg）
├─ files/                     # 用户文件存储
├─ logs/                      # 日志目录
└─ docs/                      # 文档
```

## 数据库迁移

本项目使用 Alembic 进行数据库迁移管理。

### 常用命令

```bash
# 查看迁移历史
alembic history

# 查看当前版本
alembic current

# 生成 SQL 脚本（线下预览）
alembic upgrade head --sql > migration.sql

# 执行迁移（线上执行）
alembic upgrade head

# 回滚一个版本
alembic downgrade -1
```

### 如何新建迁移文件

1. 使用 alembic 命令创建迁移脚本：
```bash
alembic revision -m "迁移描述"
```

2. 在生成的脚本中编写 SQL：
```python
# alembic/versions/xxxx_xxx_xxx.py

def upgrade() -> None:
    """升级数据库"""
    op.execute("ALTER TABLE xxx ADD COLUMN yyy VARCHAR(255)")

def downgrade() -> None:
    """回滚数据库"""
    op.execute("ALTER TABLE xxx DROP COLUMN yyy")
```

3. 执行迁移：
```bash
alembic upgrade head
```

### 线下迁移（生成 SQL 脚本）

线下迁移用于预览即将执行的 SQL，或生成脚本供 DBA 审核：

```bash
# 生成 SQL 文件
alembic upgrade head --sql > migration.sql

# 查看 SQL（不保存文件）
alembic upgrade head --sql
```

### 线上迁移注意事项

1. **备份数据库**：执行迁移前务必备份生产数据库
2. **权限检查**：确保数据库用户有 CREATE/ALTER/DROP 权限
3. **低峰期执行**：避免在业务高峰期执行迁移
4. **测试环境验证**：先在测试环境验证迁移脚本
5. **回滚准备**：确认 downgrade 脚本正确，便于紧急回滚

### 初始化新数据库

对于全新的数据库：

1. 先执行 `model/sql/baseline.sql` 创建基础表结构
2. 然后标记为最新版本：
```bash
alembic stamp head
```

## 自动化测试

本项目包含基于 Claude Code + Playwright MCP  + Claude Code Router 的自动化测试框架。

### 环境准备

详细配置请参考 `auto_test/SETUP.md`，主要步骤：


### 运行测试

```powershell
cd auto_test
```

**方式 1：交互式运行**

# 通过claude code router运行智能体测试

cd auto_test

```
ccr code
```

**方式 2：使用调度器**
```
ccr code
/orchestrator
```


### 测试模式

启动时会询问是否使用测试模式（URL 带 `?test=1` 参数）：
- **测试模式**：使用模拟接口，速度快，无成本
- **真实模式**：使用真实接口，速度慢，有成本

### 查看测试进度

```
/check-status
```

## 常见问题

### 启动相关
- **点我启动.exe 提示已在运行** - 检查系统托盘是否已有图标，或在任务管理器中结束相关进程
- **服务启动失败** - 检查 `logs/` 目录下的日志文件
- **MySQL 启动失败** - 确保 `bin/mysql` 目录存在且完整

### 服务相关
- **前端无法访问** - 检查配置文件中的端口是否被占用
- **数据库连接失败** - 检查 MySQL 是否正常运行，配置是否正确
- **ComfyUI 调用失败** - 检查 ComfyUI 服务是否运行，地址配置是否正确

## 开源协议

本项目采用修改版 Apache License 2.0 协议，详见 [LICENSE](LICENSE)。

主要条款：
- ✅ 允许商业使用
- ✅ 允许修改和分发
- ❌ 未经授权不能运营多空间服务
- ❌ 不能移除前端 LOGO 和版权信息

© 2025 智剧通. All rights reserved.
