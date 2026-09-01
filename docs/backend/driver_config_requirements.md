# Driver 配置参数要求

本文档说明各视频生成驱动所需的配置参数。

## 配置验证机制

系统在创建 driver 实例时会自动验证必要配置是否存在：
- 如果配置缺失，driver 创建失败，返回 `None`
- 日志中会记录缺失的配置项
- 用户无法使用未配置的 driver

## 配置参数汇总

### Duomi 供应商驱动

**必需配置**: `duomi.token`

适用驱动：
- `sora2_duomi_v1` - Sora2 文生视频/图生视频（任务类型 2, 3）
- `kling_duomi_v1` - 可灵图生视频（任务类型 12）
- `gemini_duomi_v1` - Gemini 图片编辑（任务类型 1, 7, 17）
- `veo3_duomi_v1` - VEO3 图生视频（任务类型 15）

配置示例：
```yaml
duomi:
  token: "your_duomi_api_token_here"
```

### RunningHub 供应商驱动

**必需配置**: 
- `runninghub.api_key`
- `runninghub.host`

适用驱动：
- `ltx2_runninghub_v1` - LTX2.0 图生视频（任务类型 10，**已关闭**）
- `wan22_runninghub_v1` - Wan2.2 图生视频（任务类型 11，**已关闭**）
- `ltx2.3_runninghub_v1` - LTX2.3 图生视频
- `digital_human_runninghub_v1` - 数字人生成（任务类型 13）
- `ltx2_3_with_voice_runninghub_v1` - LTX2.3 数字人（任务类型 32）
- `minimax_h3_runninghub_v1` - MiniMax H3 首尾帧图生视频（任务类型 34）
- `minimax_h3_reference_runninghub_v1` - MiniMax H3 参考生视频（任务类型 37，最多 9 张参考图）
- `digital_human_minimax_h3_runninghub_v1` - MiniMax H3 数字人（任务类型 35）

配置示例：
```yaml
runninghub:
  api_key: "your_runninghub_api_key"
  host: "https://api.runninghub.com"
```

### Vidu 驱动

**必需配置**: `vidu.token`

适用驱动：
- `vidu_default` - Vidu 图生视频（任务类型 14）
- `vidu_q3_i2v_turbo_v1` / `vidu_q3_i2v_pro_v1` - Vidu Q3 图生视频（首尾帧，任务类型 43）
- `vidu_q3_r2v_turbo_v1` / `vidu_q3_r2v_pro_v1` - Vidu Q3 参考生视频（任务类型 44，1-7 张参考图）
- `vidu_q3_t2v_turbo_v1` / `vidu_q3_t2v_pro_v1` - Vidu Q3 文生视频（任务类型 42）

Vidu Q3 复用 `vidu.token`，turbo 档模型为 `viduq3-turbo`，pro 档为 `viduq3-pro`（reference2video 端点的 pro 档模型名为 `viduq3`）。支持 540P/720P/1080P 分辨率（默认 720P），时长 3-16 秒。

配置示例：
```yaml
vidu:
  token: "your_vidu_api_token"
```

### 火山引擎驱动

**必需配置**: `volcengine.api_key`

适用驱动：
- `seedream5_volcengine_v1` - Seedream 文生图/图片编辑
  - Seedream 5.0（任务类型 16）
  - Seedream 4.5（任务类型 18）

配置示例：
```yaml
volcengine:
  api_key: "your_volcengine_api_key"
```

**注意**:
- Seedream 是同步 API，一次请求直接返回图片 URL，无需轮询
- 支持的图片尺寸：2K、3K、4K
- **图片大小限制**: 输入图片不能超过 10 MB，系统会自动压缩超过限制的图片

### 阿里云百炼驱动 (Happy Horse)

**必需配置**: `llm.qwen.api_key`

**可选配置**: `llm.qwen.base_url`（与 Qwen 大模型共用同一个基础地址配置；多媒体接口自动追加 `/api/v1`，未配置时默认 `https://dashscope.aliyuncs.com/api/v1`。base_url 规范化逻辑见 `config/config_util.py` 的 `normalize_aliyun_bailian_base_url()`）

适用驱动：
- `happy_horse_dashscope_v1` - Happy Horse 图生视频（任务类型 28）
  - 模型: `happyhorse-1.0-i2v`
  - 仅支持单张首帧图片
  - 支持可选驱动音频和视频
  - 异步 API，创建任务后需轮询查询结果
- `happy_horse_dashscope_r2v_v1` - Happy Horse 参考生视频（任务类型 29）
  - 模型: `happyhorse-1.0-r2v`
  - 支持 1-9 张参考图像
  - prompt 中通过 `[Image 1]`、`[Image 2]` 指代参考图像
  - 异步 API，创建任务后需轮询查询结果
- `happy_horse_dashscope_t2v_v1` - Happy Horse 文生视频（任务类型 30）
  - 模型: `happyhorse-1.0-t2v`
  - 仅需文本提示词，无需图片
  - 异步 API，创建任务后需轮询查询结果

配置示例：
```yaml
llm:
  qwen:
    api_key: "sk-your-dashscope-api-key"
```

**注意**:
- Happy Horse 复用 LLM 配置中的阿里云 Qwen API Key，无需单独配置
- Happy Horse 是异步 API，提交后返回 task_id，需轮询查询结果

**图生视频（i2v）限制**:
- 首帧图片限制：JPEG/JPG/PNG/WEBP，宽高不小于300像素，1:2.5 ~ 2.5:1，不超过10MB
- 支持时长：3-15秒，默认5秒
- 支持分辨率：720P、1080P（默认）
- 支持驱动音频（可选）：wav/mp3，2～30秒，不超过15MB，通过 `ai_tool.audio_path` 传入
- 支持驱动视频（可选）：通过 `ai_tool.video_path` 传入
- 可选参数：`resolution` (720P/1080P)、`watermark` (true/false)、`seed` (0-2147483647)、`prompt_extend` (true/false)

**参考生视频（r2v）限制**:
- 参考图像：1-9张，JPEG/JPG/PNG/WEBP，短边不低于400像素，不超过10MB
- 支持时长：3-15秒，默认5秒
- 支持分辨率：720P、1080P（默认）
- 支持比例：16:9(默认)、9:16、3:4、4:3、1:1
- prompt 中通过 `[Image N]` 指代参考图像，需指明参考图中的具体对象
- 不支持驱动音频和视频
- 可选参数：`resolution` (720P/1080P)、`watermark` (true/false)、`seed` (0-2147483647)

**文生视频（t2v）限制**:
- 仅需文本提示词，无需上传任何图片
- prompt 长度不超过5000个非中文字符或2500个中文字符
- 支持时长：3-15秒，默认5秒
- 支持分辨率：720P、1080P（默认）
- 支持比例：16:9(默认)、9:16、1:1、4:3、3:4
- 不支持驱动音频和视频
- 可选参数：`resolution` (720P/1080P)、`watermark` (true/false)、`seed` (0-2147483647)

**通用**:
- 所有驱动在提交任务前，会自动将本地图片/媒体文件上传到CDN图床，确保外部API可访问
- 视频 URL 有效期24小时，获取后会自动下载保存

> **注意**: 图片上传不再受 `server.is_local` 配置影响，所有环境都会自动上传。

### 阿里云百炼驱动 (Wan3.0)

**必需配置**:
- `llm.qwen.api_key`（与 Happy Horse / Qwen LLM 复用同一个 DashScope API Key）
- 业务空间来源（二选一）：
  - `llm.qwen.base_url` 填密钥弹窗中的 API Host（如 `https://llm-xxx.cn-beijing.maas.aliyuncs.com`）——驱动自动解析出业务空间 ID 和地域，**推荐，用户零额外配置**
  - 或显式配置 `wan3.workspace_id`（取 API Host 第一个点号前的部分）

**配置入口**：admin「系统配置 → 快速配置」弹窗的「阿里云百炼（Qwen）」服务商卡片，除 API Key / Base URL 外还有「业务空间 ID」（一般留空）和「业务空间地域」两个字段；保存时若 DB 中尚无该配置项会自动创建。配置完整后，「实现方管理」页面才会显示 wan3.0 的实现方（页面会实例化驱动校验配置完整性）。

**可选配置**:
- `wan3.workspace_id`（业务空间 ID，优先级高于 base_url 解析，可留空）
- `wan3.endpoint_region`（业务空间地域，默认 `cn-beijing` 或从 base_url 解析，可选 `ap-southeast-1` / `ap-northeast-1` / `eu-central-1` / `us-east-1`）

适用驱动：
- `wan3_video_dashscope_v1` - 万相3.0 图生视频，标准版（任务类型 40），模型 `wan3.0-video`
- `wan3_video_prime_dashscope_v1` - 万相3.0 图生视频，高速版（任务类型 40），模型 `wan3.0-video-prime`
- `wan3_video_dashscope_r2v_v1` - 万相3.0 参考生视频，标准版（任务类型 41），模型 `wan3.0-video`
- `wan3_video_prime_dashscope_r2v_v1` - 万相3.0 参考生视频，高速版（任务类型 41），模型 `wan3.0-video-prime`
- `wan3_video_dashscope_t2v_v1` - 万相3.0 文生视频，标准版（任务类型 39），模型 `wan3.0-video`
- `wan3_video_prime_dashscope_t2v_v1` - 万相3.0 文生视频，高速版（任务类型 39），模型 `wan3.0-video-prime`

配置示例：
```yaml
llm:
  qwen:
    api_key: "sk-your-dashscope-api-key"
wan3:
  workspace_id: "your-bailian-workspace-id"
  endpoint_region: "cn-beijing"
```

**注意**:
- API 域名为 `https://{workspace_id}.{region}.maas.aliyuncs.com/api/v1`，创建任务必须带 `X-DashScope-Async: enable` 头
- 异步 API，提交后返回 task_id，需轮询查询结果（PENDING/RUNNING/SUCCEEDED/FAILED/CANCELED/UNKNOWN）
- prompt 与 media 必填其一

**图生视频（i2v）限制**:
- 首帧图片必选（最多1张），尾帧可选（最多1张），与参考生模式互斥
- 支持时长：2-30秒，默认5秒
- 支持分辨率：480P、720P、1080P（默认）
- 支持比例：adaptive(默认)、16:9、4:3、1:1、3:4、9:16
- 可选参数：`resolution`、`ratio`、`duration`、`audio`（默认true）、`watermark`（默认false）、`prompt_extend`（默认true）、`seed` (0-2147483647)

**参考生视频（r2v）限制**:
- 参考图像：最多10张；参考视频：最多5段且总时长≤15秒；参考音频：最多5段且总时长≤15秒
- 有视频输入时校验：输入视频总时长 + 输出时长 ≤ 30秒，超限返回用户错误
- 分辨率/比例/时长同上

**文生视频（t2v）限制**:
- 仅需文本提示词，无需任何图片/音频/视频
- 分辨率/比例/时长同上

## 配置检查

### 启动时检查

应用启动时，系统会尝试创建所有 driver 实例：
- 配置完整的 driver 会成功创建
- 配置缺失的 driver 会记录警告日志，但不影响其他 driver

### 运行时检查

当用户提交任务时：
- 如果对应的 driver 未配置，`VideoDriverFactory.create_driver_by_type()` 返回 `None`
- 任务队列处理器应检查返回值，向用户返回友好错误提示

## 实现细节

### 验证逻辑

每个 driver 在 `__init__` 方法末尾调用 `_validate_required()` 验证配置：

```python
# 示例：Duomi 驱动（使用动态配置，数据库优先 + YAML 兜底）
self._token = get_dynamic_config_value("duomi", "token", default="")
self._validate_required({
    "Duomi API Token": self._token,
})

# 示例：RunningHub 驱动
self._api_key = get_config_value("runninghub", "api_key", default="")
self._host = get_config_value("runninghub", "host", default="")
self._validate_required({
    "RunningHub API Key": self._api_key,
    "RunningHub Host": self._host,
})
```

### 异常处理

`VideoDriverFactory` 捕获 `DriverConfigError` 异常：

```python
try:
    return driver_class()
except DriverConfigError as e:
    logger.warning(f"Driver {implementation_driver_name} 配置不完整: {e.message}")
    logger.info(f"缺少配置: {', '.join(e.missing_configs)}")
    return None
```

## 前端界面提示

系统会自动在前端界面中禁用未配置的功能选项：

### 视频模型选择器

未配置的视频模型会显示灰色并标记 "(未配置)"：
```
[Sora2 ▼]
[LTX2.0 (未配置)]  ← 灰色禁用
[Wan2.2 (未配置)]  ← 灰色禁用
[可灵]
```

### 图片模型选择器

未配置的图片模型同样会禁用：
```
[标准版 (未配置)]  ← 灰色禁用
[加强版 (未配置)]  ← 灰色禁用
```

### 受影响的页面

- **index.html**: 图片编辑、文生图、图生视频页面
- **video_workflow.html**: 图生视频节点、图片节点、分镜组节点、剧本节点

## 首次安装配置指南

1. **确定需要使用的功能**
   - 查看 `config/constant.py` 中的 `VIDEO_DRIVER_MAPPING` 了解任务类型
   - 查看 `DRIVER_IMPLEMENTATION_MAPPING` 了解对应的 driver 实现

2. **配置必要参数**
   - 根据上述配置参数汇总，在配置文件中添加对应的 API Token/Key
   - 确保配置值非空

3. **验证配置**
   - 启动应用，查看日志确认 driver 是否成功创建
   - 如有配置缺失，日志会显示具体缺少哪些配置
   - 前端界面中未配置的选项会显示为灰色禁用状态

4. **测试功能**
   - 提交测试任务，验证 driver 是否正常工作
