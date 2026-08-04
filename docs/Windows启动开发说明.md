# 智剧通 Windows 启动说明

## 📋 前置要求

在启动项目之前，请确保已完成以下准备工作：

### 1. Python 与 uv
- Release 程序包必须包含 `bin/uv/uv.exe`，不要求用户安装系统 Python
- Release 程序包必须同时包含完整、可搬迁的 `bin/python/cpython-3.10.20-windows-x86_64-none/python.exe`
- `bin/python` 是 uv managed Python 的安装根目录，不能放普通虚拟环境；根目录出现 `pyvenv.cfg` 表示程序包制作错误
- 用户启动时固定设置 `UV_PYTHON_DOWNLOADS=never`，不会下载 Python，也不会使用系统 Python
- uv 下载缓存默认保存在项目内的 `bin/uv-cache`，不会依赖用户目录中的 uv 环境
- 源码开发仍建议使用 Python 3.10 和项目 `.venv`

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

- ✅ 双击即可启动（项目自带 uv 创建并维护持久化 launcher 环境）
- ✅ 在系统托盘显示启动状态图标，体验与 `.exe` 完全一致
- ✅ **纯文本脚本 + 官方 python.exe，无 PyInstaller 打包特征，杀毒软件不会误报**
- ✅ 即便 `点我启动.exe` 被杀毒删除，双击任一 `.bat` 仍可正常启动
- ✅ **自动网络检测**：国内自动走阿里云镜像、海外自动走官方 PyPI，中外用户都快
- 📝 Python 已随包提供；首次启动只需由 uv 准备最小托盘依赖，之后复用 `bin/runtime/launcher-<hash>`

#### uv 持久化 launcher 运行机制

```text
点我启动.bat / launcher_me.bat
    ↓ 程序包内置 Python（bootstrap 仅使用标准库）
scripts/launchers/bootstrap.py
    ↓ 内置 uv + 内置 Python：uv venv --no-python-downloads + uv pip install
bin/runtime/launcher-<requirements-lock-hash>
    ↓ pythonw.exe（不再由 uv 临时环境二次拉起）
scripts/launchers/launcher.py
    ↓
系统托盘 + start.bat + MySQL/Web 服务
```

- `requirements-launcher.in` 是托盘直接依赖，`requirements-launcher.lock` 是 uv 生成的 Windows/Python 3.10 锁文件。
- bootstrap 只使用标准库；环境创建和依赖安装由 uv 完成，基础 Python 始终来自程序包的 `bin/python`。
- 用户侧禁止 Python 下载；`bin/python` 缺失、损坏或是普通虚拟环境时立即报“程序包不完整”。
- 锁文件内容变化时会创建新的哈希环境；新环境验证失败不会覆盖已有可用环境。
- 托盘常驻进程使用 uv 创建环境中的 `pythonw.exe`，不会引用 `uv run --with-requirements` 的 `.tmp*` 临时解释器。
- 正常启动禁止执行 `uv cache clean`。LiteLLM 版本通过 `requirements.txt` 的 `<1.92` 约束控制，避免与正在运行的 uv 进程争用缓存锁。
- bootstrap 日志：`logs/launcher_bootstrap.log`；托盘运行日志：`logs/launcher_runtime.log`；服务启动日志：`logs/startup.log`。
- 托盘使用 `GET /api/system/health` 判断服务身份与就绪状态；该接口只返回内存常量，不访问数据库或外部网络。
- `stop.bat` 同样通过内置 uv 运行 PID 停止器；现代 Windows 缺少 WMIC 时会自动改用 PowerShell CIM 查询，且只终止当前项目记录的进程树。

#### 发布包如何生成内置 Python

`scripts/package.py -p Windows` 在构建机上调用发布包内的 uv：

```powershell
bin\uv\uv.exe python install `
  --install-dir bin\python `
  --no-bin --no-registry `
  cpython-3.10.20-windows-x86_64-none
```

打包脚本随后直接运行该解释器并导入 `encodings` 做完整性检查。下载只发生在构建机，最终用户不下载 Python。

更新 launcher 依赖后必须重新生成锁文件：

```powershell
bin\uv\uv.exe pip compile requirements-launcher.in `
  --python-version 3.10 `
  --python-platform windows `
  --output-file requirements-launcher.lock
```

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
- 📝 Python 已包含在发布包中；首次启动仅准备依赖环境

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
点我启动.exe / 点我启动.bat
    ↓
launcher_me.bat → bootstrap.py → 持久化 launcher pythonw.exe
    ↓
launcher.py（系统托盘）→ start.bat
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

## 🐍 发布包内置 Python

Windows 发布包在构建阶段通过 uv 准备完整的 CPython 3.10.20。用户启动时固定使用包内解释器，并设置 `UV_PYTHON_DOWNLOADS=never`：

| 项 | 默认值 |
|----|--------|
| 安装根目录 | `<项目根>\bin\python` |
| 固定解释器 | `bin\python\cpython-3.10.20-windows-x86_64-none\python.exe` |
| 用户侧策略 | 禁止下载 Python，不回退到系统 Python 或 `%APPDATA%\uv\python` |

**预装 / 离线拷贝示例**（在有网络的机器上）：

```batch
cd /d <项目根目录>
bin\uv\uv.exe python install `
  --install-dir bin\python --no-bin --no-registry `
  cpython-3.10.20-windows-x86_64-none
```

然后把整个 `bin\python` 目录随项目一起拷贝到目标机；目标机执行 `start.bat` 时只使用该解释器。

涉及入口：`start.bat`、`launcher_me.bat` / `点我启动.bat`，以及 `scripts/launchers/start_windows.py`、`launcher.py`（子进程会继承该环境变量）。

**发布打包**：`scripts/package.py` 会把 uv 托管的 CPython 3.10 一并打入包内 `bin/python`，新用户解压即用。物料来源优先级：NAS `bin/python-windows` → 开发机本地仓库 `bin/python` →（仅 Windows）打包时用 uv 现场安装；三者在 Windows 下都缺失会直接报错中止打包。macOS 已预留配置位（NAS 目录 `python-macos-x86` / `python-macos-arm`，需放 uv 托管布局的 `cpython-3.10.x-macos-*-none` 目录），物料未就绪时告警跳过、不影响打包。

## ❓ 常见问题

### 1. 提示找不到内置 Python
**解决方法**：
- 确认程序包同时包含 `bin/uv/uv.exe` 和 `bin/python/cpython-3.10.20-windows-x86_64-none/python.exe`
- 确认 `bin/python` 根目录没有 `pyvenv.cfg`、`Lib`、`Scripts`；这些是误打包普通虚拟环境的特征
- 重新下载并完整解压发布包；启动器不会临时下载 Python，也不会回退到系统 Python
- 查看 `logs/launcher_bootstrap.log` 中的内置 Python 或 launcher 依赖错误
- 系统自带的 3.11/3.12 不能替代上述内置 Python 3.10.20

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
- Release 包不使用系统安装的 uv，请确认 `bin/uv/uv.exe` 未被删除或隔离。
- 查看 `logs/launcher_bootstrap.log`，确认是内置 Python 损坏还是 launcher 依赖同步失败。
- 不要在智剧通运行期间手动执行 `uv cache clean`；如需维护缓存，请先通过托盘退出。

### 5. 服务启动后无法访问
**检查项**：
- 查看控制台日志，确认服务是否成功启动
- 检查 `config_prod.yml` 中的 `server.port` 配置
- 确认防火墙是否允许该端口
- 浏览器访问：`http://localhost:端口号`

### 6. 托盘入口（点我启动.bat）启动失败排查

托盘链路无控制台窗口，start.bat 全程输出写入日志文件，失败时托盘气泡会给出路径：

| 日志 | 内容 |
|------|------|
| `logs/launcher_bootstrap.log` | 内置 Python 校验、uv launcher 环境创建和复用记录 |
| `logs/launcher_runtime.log` | 持久化托盘进程自身输出 |
| `logs/startup.log` | start.bat 全程输出（更新检查、依赖安装、MySQL、服务启动），每轮启动重建 |

**常见结论**：
- 托盘报「启动脚本已退出（码 N）」→ 看 `logs/startup.log` 末尾即为失败原因
- 托盘报「端口 9003 被其他程序占用」→ 有非智剧通程序占用了端口（托盘通过 `/api/system/health` 校验服务身份），关闭占用程序或改 `server.port`
- 托盘报「服务启动超时」（超过 60 分钟硬超时）→ 启动进程树已被自动终止，按日志排查后重试
- 启动超过 30 分钟仍在继续 → 托盘会提醒「启动耗时较长」，属慢网络下的正常等待，可继续等或经托盘「退出」取消

### 7. 杀毒软件误报 点我启动.exe / 文件被隔离删除

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
