# 智剧通 AI短剧制作平台


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

### 方式 1：Windows 双击启动（推荐）

**📌 详细说明请查看：[Windows启动说明.md](Windows启动说明.md)**

项目提供了英文版启动脚本（推荐使用，无编码问题）：

#### 1. start.bat - 启动服务（显示日志）
- ✅ 显示详细的启动日志和运行状态
- ✅ 适合首次启动和问题排查
- ✅ 纯英文界面，无乱码问题
- 📝 双击即可运行

#### 2. start_silent.vbs - 静默启动
- ✅ 后台运行，无控制台窗口
- ✅ 界面简洁，不占用桌面空间
- 📝 双击即可运行

#### 3. stop.bat - 停止服务
- ✅ 一键停止所有服务
- 📝 双击即可运行

**快速开始**：
1. 确保已安装 Python 3.10+
2. 将 MySQL 解压到 `bin/mysql` 目录
3. 复制 `config.example.yml` 为 `config_prod.yml` 并配置
4. 双击 `start.bat` 即可启动
5. （可选）双击 `create_shortcuts.vbs` 创建桌面快捷方式

**注意**：项目中也有中文版本的启动脚本（启动.bat等），但由于Windows批处理文件编码问题，可能会出现乱码。建议使用英文版本。详见 `Windows启动文件说明.txt`

`start_windows.py` 会自动：
1. 检查 Python 和 uv 环境
2. 启动本地 MySQL 服务（首次启动时自动初始化）
3. 设置数据库密码并导入表结构
4. 启动 Web 服务和定时任务
5. 监控服务状态，异常时自动重启

### 方式 2：使用 uv 启动（命令行）

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

### 方式 3：手动启动（Linux/macOS）

```bash
# 激活虚拟环境后
python3 server.py
```

默认监听 `http://0.0.0.0:5173`，并以静态站点形式提供 `web/` 目录。你的浏览器可直接访问：
- 前端首页：`http://127.0.0.1:5173/`
- API：`POST http://127.0.0.1:5173/api/qwen-image-edit`

## 前端使用说明
1. 打开首页后点击“图片AI编辑功能”。
2. 选择图片文件，输入提示词。
3. 可选：设置 ComfyUI 服务地址（例如 `http://192.168.1.100:8188/`），并点击“保存”。为空时使用后端默认值（环境变量 `COMFYUI_SERVER` 或 `http://127.0.0.1:8188/`）。
4. 点击“提交任务”，等待生成结果，结果图片会在页面下方展示。

## 配置项
- 环境变量 `COMFYUI_SERVER`：不在前端传 `server` 字段时，后端默认的 ComfyUI 地址。
- 表单字段 `timeout`：后端轮询历史的超时时间（秒），默认 180。

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
├─ server.py                  # FastAPI 后端
├─ requirements.txt           # Python 依赖
├─ README.md                  # 使用说明
├─ alembic.ini                # Alembic 数据库迁移配置
├─ alembic/                   # Alembic 迁移脚本目录
│  ├─ env.py                  # 迁移环境配置
│  ├─ script.py.mako          # 迁移脚本模板
│  └─ versions/               # 迁移版本目录
└─ web/
│  └─ index.html              # 前端（Vue + Router + Axios）
files/
├─ tmp/                    # 临时文件（可定期清理）
│  ├─ tts/                 # TTS音频临时文件
│  ├─ jianying_export/     # 剪映导出临时文件
│  └─ pic/                 # 图片临时文件
└─ script_writer/                    # 剧本创作系统数据根目录
   └─ {user_id}/                     # 用户ID目录
      └─ {world_id}/                 # 世界ID目录（每个用户可以有多个世界）
         ├─ characters/              # 角色卡目录
         │  └─ character_*.json      # 角色JSON文件
         ├─ locations/               # 场景目录
         │  └─ location_*.json       # 场景JSON文件
         ├─ props/                   # 道具目录
         │  └─ prop_*.json           # 道具JSON文件
         ├─ scripts/                 # 剧本目录
         │  └─ script_*.json         # 剧本JSON文件
         ├─ worlds/                  # 世界信息目录
         │  └─ world_*.json          # 世界设定JSON文件
         ├─ task_status/             # 任务状态目录
         │  └─ task_status.json      # 任务状态跟踪文件
         ├─ user_long_input/         # 长文本输入目录
         │  └─ HH:mm:ss.txt          # 超过5000字的用户输入文件
         └─ script_problem.json      # 剧本问题/审核报告文件
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
- 若前端长时间无结果，请检查：
  - ComfyUI 是否在运行，且地址正确（端口、协议、是否可达）。
  - 模板中的节点编号与类型是否与当前 ComfyUI 工作流一致（本示例使用 `78` 与 `108`）。
  - 后端日志中是否出现 `Failed to upload image` 或 `Timed out waiting for ComfyUI result`。
- 若需调试底层 ComfyUI 调用流程，可参考 `comfyui_参考代码.py`。
