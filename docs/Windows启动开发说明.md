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

项目提供了三种启动方式，可根据需要选择：

### 方式一：点我启动.exe（推荐）

- ✅ 双击即可启动
- ✅ 在系统托盘显示启动状态图标
- ✅ 启动过程中显示气泡提示（正在启动MySQL...等）
- ✅ 服务就绪后自动打开浏览器
- ✅ 右键托盘图标可查看日志或退出

**托盘图标颜色含义**：
- 🟠 橙色：启动中
- 🟢 绿色：服务运行中
- 🔴 红色：启动失败

**使用场景**：
- 日常使用
- 希望实时了解启动状态

### 方式二：start_silent.vbs（静默启动）

- ✅ VBS 脚本，静默启动（备用方案）
- ✅ 不显示托盘图标
- 📝 双击即可运行

### 方式三：start.bat（显示日志）

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
