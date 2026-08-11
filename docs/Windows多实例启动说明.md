# Windows 多实例启动说明

## 目标

同一台 Windows 电脑可以从不同项目目录启动多个智剧通实例。每个实例必须拥有独立的 Web 端口、MySQL 端口和 MySQL 数据目录；启动、监控或停止其中一个实例不得操作另一个实例的进程。

## 实例边界

项目目录是默认实例边界。`comfyui_server` 与 `comfyui_server2` 的 `data/mysql`、`data/runtime/launcher_pids.json`、`scheduler.lock`、日志及配置彼此独立。

每个实例必须在自己的 `config_prod.yml` 中配置不同端口：

```yaml
database:
  port: 13306

server:
  host: http://localhost:19003
  port: 19003
```

第二个实例应使用另外一组端口，例如 MySQL `3307`、Web `11000`。如果设置了 `PORT` 环境变量，它会覆盖 `server.port`，启动器的端口预检和就绪检查也使用这个实际端口。

## 安全行为

- MySQL 启动按端口获取机器级进程锁，避免两个目录同时检查到空闲端口后一起启动。
- 端口已被占用时启动失败并提示修改配置，不再把端口上的其他 MySQL 当作当前实例所有。
- 只有启动器亲自创建且仍然存活的 MySQL 进程才允许进入关闭流程。
- PID 文件保存在各项目自己的 `data/runtime` 下；`stop.bat` 只处理当前项目记录的 PID。
- 缺少内置 Python、uv 或 PID 停止脚本时，`stop.bat` 会安全失败，不再按 `mysqld.exe` 进程名全局终止。
- 托盘启动器互斥锁包含项目目录摘要，因此不同目录的托盘实例可以并存。

## 不支持的方式

不要从同一个项目目录启动两个完整实例。它们仍会共享配置、MySQL 数据目录、日志和调度器锁。如果需要第二个实例，请复制到独立目录并配置独立端口。

## 验证

同时启动两个目录后，应分别检查：

1. 两个 Web 地址均可访问。
2. 两个 MySQL 端口分别由对应目录下的 `mysqld.exe` 监听。
3. 两个目录各自生成 `data/runtime/launcher_pids.json`。
4. 停止任意一个目录后，另一个目录的 Web 和 MySQL 端口仍保持监听并可访问。
