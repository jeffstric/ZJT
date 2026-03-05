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
- `gemini_duomi_v1` - Gemini 图片编辑（任务类型 1）
- `gemini_pro_duomi_v1` - Gemini Pro 图片编辑（任务类型 7）
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
- `ltx2_runninghub_v1` - LTX2.0 图生视频（任务类型 10）
- `wan22_runninghub_v1` - Wan2.2 图生视频（任务类型 11）
- `digital_human_runninghub_v1` - 数字人生成（任务类型 13）

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

配置示例：
```yaml
vidu:
  token: "your_vidu_api_token"
```

### 火山引擎驱动

**必需配置**: `volcengine.api_key`

适用驱动：
- `seedream5_volcengine_v1` - Seedream 5.0 文生图（任务类型 16）

配置示例：
```yaml
volcengine:
  api_key: "your_volcengine_api_key"
```

**注意**: Seedream 5.0 是同步 API，一次请求直接返回图片 URL，无需轮询。支持的图片尺寸：2K、3K。

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
