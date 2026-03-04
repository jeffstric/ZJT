# Windows 启动脚本使用指南

本文档介绍如何使用 `start_windows.py` 启动和管理本地服务。

## 概述

`start_windows.py` 是一个 Windows 服务启动脚本，提供以下功能：

1. **MySQL 自动初始化** - 首次启动时自动执行 `--initialize-insecure`
2. **密码配置** - 从配置文件读取并设置 MySQL root 密码
3. **SQL 导入** - 首次初始化时自动导入 `baseline.sql`
4. **应用服务启动** - 通过 uv 启动 `run_{env}.py`（Web 服务 + 定时任务）
5. **服务监控** - 监控 MySQL 和应用服务状态，异常时自动重启

## 目录结构

```
comfyui_server/
├── bin/mysql/
│   ├── bin/
│   │   ├── mysqld.exe      # MySQL 服务端
│   │   └── mysql.exe       # MySQL 客户端
│   └── my.ini              # MySQL 配置文件
├── data/mysql/             # MySQL 数据目录
├── model/sql/
│   └── baseline.sql        # 初始化 SQL 文件
├── config_prod.yml         # 生产环境配置（默认）
├── config_dev.yml          # 开发环境配置
├── run_dev.py              # 开发环境启动器
├── run_prod.py             # 生产环境启动器
└── start_windows.py        # Windows 启动脚本
```

## 配置要求

### 1. MySQL 配置文件 (`bin/mysql/my.ini`)

```ini
[mysqld]
basedir=G:/code/comfyui_server/bin/mysql
datadir=G:/code/comfyui_server/data/mysql
port=3306
character-set-server=utf8mb4
collation-server=utf8mb4_0900_ai_ci
default-time-zone='+08:00'

[client]
default-character-set=utf8mb4
```

### 2. 应用配置文件 (`config_{env}.yml`)

```yaml
database:
  host: "localhost"
  port: 3306
  user: "root"
  password: "your_secure_password"
  database: "zjt"
  charset: "utf8mb4"
```

## 使用方法

### 基本启动

```bash
# 使用 uv 运行（推荐）
uv run start_windows.py
```

### 指定环境

通过环境变量 `comfyui_env` 指定配置环境：

```powershell
# Windows PowerShell - 开发环境
$env:comfyui_env="dev"
uv run start_windows.py

# Windows PowerShell - 生产环境（默认）
$env:comfyui_env="prod"
uv run start_windows.py
```

```cmd
# Windows CMD
set comfyui_env=dev
uv run start_windows.py
```

默认使用 `prod` 环境（`config_prod.yml`，启动 `run_prod.py`）。

## 启动流程

```
启动脚本
    │
    ├─ 加载配置文件 (config_{env}.yml)
    │
    ├─ 检查 MySQL 路径
    │   └─ bin/mysql/bin/mysqld.exe, mysql.exe, my.ini
    │
    ├─ 检查数据目录 (data/mysql)
    │   │
    │   ├─ 目录为空/不存在 → 首次初始化
    │   │   ├─ 执行 mysqld --initialize-insecure
    │   │   ├─ 启动 MySQL 服务
    │   │   ├─ 用空密码连接，设置新密码
    │   │   └─ 导入 baseline.sql
    │   │
    │   └─ 目录有数据 → 非首次启动
    │       └─ 直接启动 MySQL 服务
    │
    ├─ 启动应用服务
    │   └─ uv run run_{env}.py
    │
    └─ 进入服务监控模式
        └─ 检测 MySQL 和应用服务异常退出并自动重启（最多5次）
```

## 服务监控

脚本启动后会进入监控模式：

- **检测间隔**: 5 秒
- **最大重启次数**: 5 次
- **重启失败等待**: 10 秒

## 退出服务

使用 `Ctrl+C` 发送中断信号，脚本会：

1. 停止监控循环
2. 发送终止信号给 MySQL 进程
3. 等待进程退出（最多 10 秒）
4. 强制结束（如超时）

## 故障排查

### 常见问题

1. **配置文件不存在**
   ```
   配置文件不存在: config_prod.yml
   ```
   解决：创建对应的配置文件，参考 `config.example.yml`

2. **MySQL 路径检查失败**
   ```
   mysqld.exe不存在
   ```
   解决：确保 `bin/mysql/bin/mysqld.exe` 存在

3. **端口被占用**
   ```
   MySQL服务已经在端口 3306 运行
   ```
   解决：已有 MySQL 实例运行，无需重复启动

4. **密码连接失败**
   ```
   无法连接MySQL
   ```
   解决：检查 `config_{env}.yml` 中的密码配置

### 日志输出

脚本使用标准日志格式输出：

```
2026-02-25 17:45:00 - INFO - MySQL路径检查成功
2026-02-25 17:45:01 - INFO - 正在启动MySQL服务...
2026-02-25 17:45:05 - INFO - MySQL服务已启动，端口: 3306
```

## 相关文件

| 文件 | 说明 |
|------|------|
| `start_windows.py` | Windows 启动脚本 |
| `run_dev.py` | 开发环境启动器（uvicorn + scheduler） |
| `run_prod.py` | 生产环境启动器（gunicorn + scheduler） |
| `bin/mysql/my.ini` | MySQL 配置文件 |
| `model/sql/baseline.sql` | 初始化 SQL 文件 |
| `config_{env}.yml` | 应用配置文件 |
