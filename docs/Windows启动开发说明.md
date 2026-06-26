# 智剧通 Windows 启动说明

## 📋 前置要求

在启动项目之前，请确保已完成以下准备工作：

### 1. 安装 Python
- 版本要求：Python 3.10 或更高版本
- 下载地址：https://www.python.org/downloads/
- **重要**：安装时请勾选 "Add Python to PATH"

### 2. 配置 MySQL
- 将 MySQL 解压到项目的 `bin/mysql` 目录
- 确保 `bin/mysql/bin/mysqld.exe` 存在
- 确保 `bin/mysql/my.ini` 配置文件存在
- **注意**：启动脚本会自动更新 `my.ini` 中的路径，无需手动修改

### 3. 配置 FFmpeg
- 将 FFmpeg 解压到项目的 `bin/ffmpeg` 目录
- 确保 `bin/ffmpeg/ffmpeg.exe` 和 `bin/ffmpeg/ffprobe.exe` 存在
- **注意**：启动脚本会自动更新配置文件中的 ffmpeg 路径

### 4. 配置文件（可选）
- 首次启动时会自动从 `config.example.yml` 创建 `config_prod.yml`
- 如需自定义配置，可手动修改：
  - `database.password`：数据库密码
  - `server.port`：服务端口（默认 9003）
  - 其他 API 密钥等配置

## 🚀 启动方式

项目提供了多种启动方式，可根据需要选择：

### 方式一：点我启动.bat / launcher_me.bat（推荐·免打包·零误报·中外通用）

提供两个等价入口（逻辑相同，`点我启动.bat` 转发到 `launcher_me.bat`），按习惯选用：
- `点我启动.bat` —— 中文名，国内用户首选
- `launcher_me.bat` —— 英文名，海外用户首选

- ✅ 双击即可启动（通过项目自带的 uv 运行 `launcher.py`）
- ✅ 在系统托盘显示启动状态图标，体验与 `.exe` 完全一致
- ✅ **纯文本脚本 + 官方 python.exe，无 PyInstaller 打包特征，杀毒软件不会误报**
- ✅ 即便 `点我启动.exe` 被杀毒删除，双击任一 `.bat` 仍可正常启动
- ✅ **自动网络检测**：国内自动走阿里云镜像、海外自动走官方 PyPI，中外用户都快
- 📝 首次启动需由 uv 准备 Python 环境与依赖（约 1~3 分钟），之后秒开

**使用场景**：
- 日常使用（**首选**）
- 遇到 `.exe` 被杀毒误报/删除时的兜底启动方式

### 方式二：点我启动.exe / launcher_me.exe（原生·零误报·中外双名）

由 `scripts/build/launcher_exe.cs` 编译的两个等价极简 .NET 程序（各 ~80KB），双击后都调用
`launcher_me.bat` 启动托盘：
- `点我启动.exe` —— 中文名，国内用户
- `launcher_me.exe` —— 英文名，海外用户

**无 PyInstaller bootloader 特征，杀毒软件不会按 PyInstaller 特征误报删除。**
（编译方式见 `scripts/build/README.md` 方式一）

- ✅ 双击即可启动（带应用图标，体验接近原生应用）
- ✅ 在系统托盘显示启动状态图标
- ✅ 启动过程中显示气泡提示（正在启动MySQL...等）
- ✅ 服务就绪后自动打开浏览器
- ✅ 右键托盘图标可查看日志或退出
- 📝 仍是未签名 exe，SmartScreen 首次可能提示「未知发布者」，点「仍要运行」即可（但不会被 AV 静态删除）
- 📝 首次启动仍需 uv 准备 Python 环境（约 1~3 分钟）

**托盘图标颜色含义**：
- 🟠 橙色：启动中
- 🟢 绿色：服务运行中
- 🔴 红色：启动失败

**使用场景**：
- 习惯双击 exe 启动的用户
- 希望有应用图标入口

### 方式三：start_silent.vbs（静默启动）

- ✅ VBS 脚本，静默启动（备用方案）
- ✅ 不显示托盘图标
- 📝 双击即可运行

### 方式四：start.bat（显示日志）

- ✅ 显示详细的启动日志
- ✅ 可以看到运行状态和错误信息
- ✅ 适合调试和排查问题
- 📝 控制台窗口会保持打开

**使用场景**：
- 首次启动
- 需要查看日志
- 排查问题

**命令行使用**：
```batch
# 默认使用生产环境（prod）
start.bat

# 或设置开发环境
set comfyui_env=dev
start.bat
```

## 🔧 环境切换

项目支持多环境配置，通过环境变量 `comfyui_env` 控制：

### 生产环境（默认）
```batch
set comfyui_env=prod
```
使用配置文件：`config_prod.yml`

### 开发环境
```batch
set comfyui_env=dev
```
使用配置文件：`config_dev.yml`

### 单元测试环境
```batch
set comfyui_env=unit
```
使用配置文件：`config_unit.yml`

## 📊 启动流程

启动脚本会自动完成以下步骤：

```
点我启动.exe / start_silent.vbs / start.bat
    ↓
start_windows.py（Windows 启动管理器）
    ↓
1. ✓ 检查 Python 环境
2. ✓ 检查/安装 uv 包管理器
3. ✓ 检查配置文件（不存在则自动创建）
4. ✓ 检查并更新 ffmpeg/ffprobe 路径
5. ✓ 检查 MySQL 目录
6. ✓ 自动更新 my.ini 中的路径
7. ✓ 启动 MySQL 服务（首次会自动初始化）
8. ✓ 设置数据库密码（首次启动）
9. ✓ 导入数据库表结构（首次启动）
10. ✓ 执行数据库迁移（Alembic）
11. ✓ 启动 Web 服务和定时任务
12. ✓ 自动打开浏览器（http://localhost:9003）
13. ✓ 监控服务状态，异常时自动重启
```

## ❓ 常见问题

### 1. 提示找不到 Python
**解决方法**：
- 安装 Python 3.10+
- 确保安装时勾选了 "Add Python to PATH"
- 或手动将 Python 添加到系统环境变量

### 2. MySQL 启动失败
**可能原因**：
- `bin/mysql` 目录不存在或不完整
- 端口被占用（默认 3306）
- `my.ini` 配置文件有误

**解决方法**：
- 检查 MySQL 文件是否完整
- 修改 `my.ini` 中的端口配置
- 查看日志文件排查具体错误

### 3. 配置文件不存在
**解决方法**：
- 首次启动时会自动从 `config.example.yml` 创建
- 或手动复制：`copy config.example.yml config_prod.yml`

### 4. uv 安装失败
**解决方法**：
```batch
# 手动安装 uv
python -m pip install uv

# 或使用国内镜像
python -m pip install uv -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 5. 服务启动后无法访问
**检查项**：
- 查看控制台日志，确认服务是否成功启动
- 检查 `config_prod.yml` 中的 `server.port` 配置
- 确认防火墙是否允许该端口
- 浏览器访问：`http://localhost:端口号`

### 6. 杀毒软件误报 点我启动.exe / 文件被隔离删除

**背景**：`点我启动.exe` 由 PyInstaller 打包，其自解压机制与全网共享的 bootloader 特征，容易被部分杀毒软件（如 Windows Defender）误报为病毒并自动隔离删除。

**推荐解决方案（首选）**：改用 `点我启动.bat` / `launcher_me.bat` 启动（见「方式一」），它们是纯文本脚本，不会触发误报。

**若仍想使用 `.exe`，可按以下方式让杀毒软件放行（仅对本机生效）**：

1. **添加 Defender 排除项**（推荐）
   - 图形界面：Windows 安全中心 → 病毒和威胁防护 → 管理设置 → 排除项 → 添加排除项 → 选择「文件夹」，选中程序所在目录
   - 或以管理员身份运行 PowerShell 执行：
     ```powershell
     Add-MpPreference -ExclusionPath "C:\程序所在目录"
     ```
     > ⚠️ 请使用 `Add-MpPreference`（追加），**不要**用 `Set-MpPreference`（会覆盖整个排除列表）

2. **恢复被隔离的文件**
   - Windows 安全中心 → 病毒和威胁防护 → 保护历史记录 → 找到被隔离项 → 「操作」→「还原」
   - 还原后请立即添加排除项，避免再次被隔离

3. **绕过 SmartScreen 蓝色警告窗**
   - 点击「更多信息」→「仍要运行」
   - 或右键 `.exe` → 属性 → 勾选「解除阻止」→ 确定（清除下载标记）

## 🛑 停止服务

### 方式一：控制台窗口
如果使用 `start.bat`：
- 按 `Ctrl + C` 停止服务
- 脚本会自动优雅关闭 MySQL 和应用服务

### 方式二：任务管理器
如果使用静默模式（`点我启动.exe` 或 `start_silent.vbs`）：
1. 打开任务管理器（Ctrl + Shift + Esc）
2. 找到 `python.exe` 和 `mysqld.exe` 进程
3. 结束这些进程

## 📝 日志查看

- 应用日志：控制台输出或 `logs/` 目录
- MySQL 日志：`data/mysql/` 目录下的错误日志文件

## 🔄 更新项目

```batch
# 1. 停止服务
# 2. 拉取最新代码
git pull

# 3. 重新启动服务（依赖会自动安装）
双击 点我启动.exe 或 start.bat
```

## 📞 技术支持

如遇到问题，请：
1. 查看控制台日志
2. 检查 `logs/` 目录下的日志文件
3. 参考本文档的常见问题部分
4. 联系技术支持团队

---

**祝使用愉快！** 🎉
