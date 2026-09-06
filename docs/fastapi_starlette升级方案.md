# FastAPI + Starlette 升级方案（测试服务器验证 → 生产切换）

> 本文档是可在**测试服务器**上独立执行的操作手册。开发本机不修改任何代码/配置/依赖。
> 测试在另一台服务器进行，验证通过后才允许动生产。

## 1. 背景与目标

### 1.1 现状

- 生产环境：系统 Python 3.10 + `pip install --user`（非 conda、非 venv）
- 当前版本：`fastapi==0.111.0`，其依赖约束 `starlette>=0.37.2,<0.38.0`，实际安装 starlette 0.37.x
- `requirements.txt` 中 **没有** starlette 行，版本由 fastapi 隐式锁定

### 1.2 升级动机

| 动机 | 说明 | 来源 |
|---|---|---|
| FileResponse 支持 HTTP Range / 206 | **starlette 0.39.0** 引入（[#2697](https://github.com/Kludex/starlette/pull/2697)），视频拖动、断点续传依赖它。当前 0.37.x 对 Range 请求返回 200 全量 | [starlette release notes](https://starlette.dev/release-notes/) |
| multipart/form-data DoS 修复 | GHSA-f96h-pmfr-66vw，starlette **0.40.0** 修复 | [starlette 0.40.0](https://starlette.dev/release-notes/) |
| 避开 Range 解析 O(n²) DoS | GHSA-7f5h-v6xp-fcq8 / CVE-2025-62727：**影响 starlette ≥0.39.0 且 <0.49.1，修复于 0.49.1**。注意：0.41.x / 0.46.x 等所有中间版本都受影响 | [GHSA-7f5h-v6xp-fcq8](https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8) |

**关键结论：目标版本必须 starlette ≥ 0.49.1。** 只升到 0.41.x/0.46.x 会把"新开放的 Range 功能"和一个已知未授权 DoS 一起带上生产（`/upload` StaticFiles、`/api/download` 均公网可达）。

### 1.3 版本选型依据（PyPI requires_dist 实测）

| fastapi | starlette 约束 | 能否拿到 0.49.1+ |
|---|---|---|
| 0.115.x | `>=0.40.0,<0.47.0` | 不能 |
| 0.116–0.119 | `>=0.40.0,<0.49.0` | 不能 |
| **0.120.0 起** | `>=0.40.0,<0.50.0` | **能** |
| 最新（0.141.x） | `>=0.46.0`（无上限） | 危险，见 1.4 |

选定组合：**fastapi==0.121.0 + starlette==0.49.3 + python-multipart>=0.0.18**
（0.49.3 是 0.49.x 最后一版；fastapi 0.121.0 上限 <0.50.0，兼容。）

### 1.4 为什么必须显式 pin starlette

1. **可复现**：不显式声明时版本由 fastapi 隐式锁定，生产与测试环境可能解析出不同结果。
2. **防止装到 starlette 1.x**：starlette 1.0 **移除了 `@app.on_event` 和 `@app.middleware` 装饰器**（server.py:461、570、608 三处在用 `@app.on_event("startup")` / `@app.middleware("http")`）。fastapi 最新版对 starlette 无上限约束，pip 自由解析会装出 1.x 直接炸服。**requirements.txt 必须显式 pin `starlette==0.49.3`。**

### 1.5 不涉及

数据库迁移、frp、前端、Nginx 均无改动。业务代码零改动（server.py:5317/6910 的重复 `/upload` 挂载为已知问题，首个匹配生效、行为中性，**本次不动**，避免模糊回退边界；如需清理另开独立提交）。

## 2. requirements.txt 改动明细（精确 diff）

当前文件共 35 行，涉及 3 处（fastapi 第 1 行、python-multipart 第 5 行、新增 starlette 行）：

```diff
-fastapi==0.111.0
+fastapi==0.121.0
+starlette==0.49.3        # 新增显式 pin，原因见 1.4；严禁让 pip 自由解析（会装出 1.x）
 uvicorn[standard]==0.30.1
 gunicorn>=21.2.0
 requests==2.32.3
-python-multipart==0.0.9
+python-multipart>=0.0.18,<1.0.0   # 0.0.9 有 CVE-2024-53981 DoS；starlette 0.42.0 起最低要求 0.0.18
```

不动的行：`uvicorn[standard]==0.30.1`、`pydantic>=2.0.0,<3.0.0`（第 35 行）及其余全部。

## 3. 测试服务器准备

1. 环境：Linux + Python 3.10；`git clone` develop 分支，建独立 venv。
2. **先装当前 requirements.txt 复现基线**，记录升级前行为：
   - `curl -H 'Range: bytes=0-1023' http://127.0.0.1:9003/upload/cache/<样例.mp4>` → 预期 **200 全量**（旧版无 Range 支持），留作对照。
3. 配置 `config.yml`：测试库 + 真实七牛配置。
4. 拷贝 `/upload/cache` 样例文件（mp4 / jpg 各若干）。
5. 准备测试账号 `auth_token`。

## 4. 升级步骤（测试服务器）

```bash
# 1. 基线留底
pip freeze > freeze_before.txt

# 2. 应用第 2 节 diff 到 requirements.txt

# 3. venv 内升级
pip install -r requirements.txt

# 4. 确认 pip 输出无依赖冲突；确认实际解析版本
pip show fastapi starlette python-multipart | grep -E 'Name|Version'
# 预期：fastapi 0.121.0 / starlette 0.49.3 / python-multipart ≥0.0.18
# 若 starlette 解析出 1.x，立即停下检查 pin 是否生效

# 5. 跑项目现有测试（升级前后对照）
pytest tests/ -x -q

# 6. 测试端口起 gunicorn（不依赖 frp）
gunicorn server:app -k uvicorn.workers.UvicornWorker -b 127.0.0.1:9003
```

## 5. 冒烟验证清单（curl 命令级）

| # | 验证项 | 命令 / 方法 | 预期 |
|---|---|---|---|
| 1 | Range 206 — StaticFiles 直出 | `curl -v -H 'Range: bytes=0-1023' http://127.0.0.1:9003/upload/cache/x.mp4` | **206** + `Content-Range`（升级前为 200 全量） |
| 2 | Range 206 — /api/download 本地模式 | `curl -v -H 'Range: bytes=0-1023' 'http://127.0.0.1:9003/api/download?...&token=...'` | 206 + `Content-Range` |
| 3 | **畸形 Range 回归（CVE-2025-62727）** | `curl -H 'Range: bytes=0-0,0-0,0-0,...（数百个重叠区间）' <同上 URL>` | 正常返回/416，**CPU 不打满**，验证 0.49.3 修复生效 |
| 4 | SPA catch-all 静态资源 | `curl -v http://127.0.0.1:9003/<前端路由>` 及 js/css | 200 HTML / 正确静态资源 |
| 5 | cdn_redirect_middleware 302 | `curl -v http://127.0.0.1:9003/upload/<有 CDN 映射的媒体>` | 302 到七牛签名 URL（重点回归 `@app.middleware` 行为） |
| 6 | multipart 上传 | 走实际上传接口传文件 | 成功，无 5xx |
| 7 | /api/thumbnail | `curl -v 'http://127.0.0.1:9003/api/thumbnail?...'` | 200 图片 |
| 8 | CORS 头 | `curl -v -H 'Origin: http://example.com' ...` | `access-control-allow-*` 头正常 |
| 9 | 视频拖动人工确认 | 浏览器打开视频页拖动进度条 | 拖动流畅，Network 面板见 206 |
| 10 | datetime 序列化回归 | 对照升级前后含 UTC 时间的 API 响应 | 确认前端兼容 `Z` 后缀格式（见风险表 R5） |

## 6. 生产切换与回退

### 6.1 切换（低峰期）

```bash
# 1. 生产留底（必须，回退依据）
pip freeze > ~/freeze_prod_before_fastapi_upgrade.txt

# 2. 替换依赖
pip install --user "fastapi==0.121.0" "starlette==0.49.3" "python-multipart>=0.0.18,<1.0.0"
pip show fastapi starlette python-multipart | grep -E 'Name|Version'   # 确认解析结果

# 3. graceful 重启
# 当前生产 gunicorn 为 pts/16 前台进程：先找到 master PID
ps -ef | grep 'gunicorn.*master' | grep -v grep
kill -HUP <master_pid>   # HUP：master 依次拉起新 worker、停掉旧 worker
```

**切换完成判定**：
- `ps -ef | grep gunicorn` 中所有 worker 的启动时间晚于 HUP 时刻（无半升级残留旧 worker）
- 按第 5 节第 1/2/5 项 curl 生产地址复核（206 / 302 正常）
- 观察 5–10 分钟错误日志无异常

### 6.2 回退

```bash
pip install --user "fastapi==0.111.0" "starlette==0.37.2" "python-multipart==0.0.9"
# 还原 requirements.txt（git checkout requirements.txt）
kill -HUP <master_pid>
```

回退后按 6.1 的判定标准复核。

## 7. 风险对照表

| # | 风险 | 影响 | 应对 |
|---|---|---|---|
| R1 | starlette 1.x 移除 `@app.on_event` / `@app.middleware`（server.py:461/570/608 在用） | 装到 1.x 直接起不来 | requirements.txt 显式 pin `starlette==0.49.3`；pip install 后必须 `pip show starlette` 确认 |
| R2 | BaseHTTPMiddleware 行为变化（0.37→0.49 多次修复：异常传播、内存流、后台任务调度） | cdn_redirect_middleware 302 失效或异常 | 冒烟第 5 项重点回归 |
| R3 | SPA catch-all 路由与重复挂载 | 静态资源 404 | 冒烟第 4 项；重复挂载本次不动 |
| R4 | StaticFiles 304/ETag 行为微调（0.49.2：if-none-match 优先于 if-modified-since） | 缓存行为细微变化 | 低风险，浏览器验证第 9 项覆盖 |
| R5 | **fastapi ≥0.114.2 UTC datetime 序列化改为 `Z` 后缀**（原 `+00:00`） | 前端按字符串解析时间可能回归 | 冒烟第 10 项；前端若有问题需适配 |
| R6 | python-multipart 0.0.9→0.18+ 解析行为变化 | 上传失败 | 冒烟第 6 项；starlette 0.42.0 起本就要求 ≥0.0.18 |
| R7 | pip --user 原地升级期间服务仍在跑 | 新旧 worker 短暂混跑 | fastapi/starlette/python-multipart 均为纯 Python 包，HUP 后全量换 worker；以启动时间判定切换完成 |
| R8 | `@app.on_event` 在 0.49.x 为弃用警告 | 仅警告日志 | 本次不改代码，后续迁移 lifespan 另行处理 |

## 8. 参考链接

- starlette release notes：https://starlette.dev/release-notes/（0.39.0 Range、0.40.0 multipart DoS、0.49.1 CVE-2025-62727、1.0.0 移除装饰器 API）
- GHSA-7f5h-v6xp-fcq8：https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8
- GHSA-f96h-pmfr-66vw（multipart DoS，0.40.0 修复）
- CVE-2024-53981（python-multipart DoS，0.0.18 修复）
- fastapi release notes：https://fastapi.tiangolo.com/release-notes/
