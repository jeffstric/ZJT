# ComfyUI Qwen Image Edit Demo

一个最小可用的前后端示例：
- 前端：`web/index.html`（Vue 3 + Vue Router + Axios，CDN 版）
- 后端：`server.py`（FastAPI）
- 工作流模板：`qwen_image_edit_api.json`

前端首页为工具列表，第一项是“图片AI编辑功能”。进入后可上传图片、填写提示词，后端会据此修改模板中：
- `"78".inputs.image`（`LoadImage` 节点）
- `"108".inputs.prompt`（`TextEncodeQwenImageEdit` 节点）

随后由后端调用 ComfyUI 的 `/upload/image` 与 `/prompt` 接口，并轮询 `/history/{prompt_id}` 拿到结果图片 URL。

## 运行环境
- Python 3.9+（建议 3.10/3.11）
- 需有可访问的 ComfyUI 实例（默认 `http://127.0.0.1:8188/`），并启用上传与历史接口：
  - `POST /upload/image`
  - `POST /prompt`
  - `GET  /history/{prompt_id}`
  - `GET  /view?filename=...`

## 安装依赖
在项目根目录（与 `requirements.txt` 同级）执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如使用国内镜像，可在最后一行追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

## 启动后端
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
├─ qwen_image_edit_api.json   # 工作流模板（会被动态替换 78.image 与 108.prompt）
└─ web/
   └─ index.html              # 前端（Vue + Router + Axios）
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
