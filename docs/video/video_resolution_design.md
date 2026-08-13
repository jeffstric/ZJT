# 视频分辨率选择与算力联动方案（v3）

> **v3 变更**：根据代码评审修订，修正了 P0 级硬伤（方法名、字段名、驱动类名、配置示例）、P1 级设计缺陷（implementation 存储策略、build_context 回退逻辑、退款调用链）、P2 级清单遗漏。

## 一、背景与问题

1. **视频生成无法指定分辨率**：三个前端页面（`index.html`、`video_workflow.html`、`marketing_agent.html`）在视频生成场景下均未提供分辨率选项。
2. **后端已具备基础设施**：`ai_tools` 表有 `extra_config` 字段；`Happy Horse` 驱动已通过 `extra_config.resolution` 支持 720P/1080P；`PowerModifier` 算力修饰符机制已支持按属性（包括 `resolution`）动态调整算力。
3. **算力与分辨率脱节**：用户选择更高分辨率时，算力消耗不会相应增加。

## 二、设计目标

1. 用户可以在所有视频生成入口选择分辨率
2. 分辨率变更时，算力显示实时联动更新
3. 分辨率算力乘数**统一由 `PowerModifier` 机制承载**，不引入第二套乘数体系
4. 前端预估算力、后端扣费、驱动请求、失败退款四方对齐，使用**同一个 resolved implementation**
5. 后端校验分辨率合法性，防止客户端伪造
6. implementation 写入 `ai_tools.implementation` 表字段（int），确保退款时可还原
7. 向下兼容，不影响现有功能和默认行为

## 三、核心设计决策

### 3.1 算力乘数：统一使用 PowerModifier，不引入双重来源

**决策**：分辨率的算力乘数**只通过 `PowerModifier(attribute='resolution')` 配置**，不在 `ImplementationConfig` 上另建乘数字段。

**理由**：
- `PowerModifier` 已明确支持 `resolution` 属性（见 `config/unified_config.py:134` 注释）
- 前后端已有完整的 `power_modifiers` 计算链路（`UnifiedTaskConfig.get_computing_power()` → `task_config.js:getComputingPower()`）
- 双重乘数来源会导致同一分辨率被重复计费，或前后端口径不一致

**配置方式**：在需要分辨率计费的 `UnifiedTaskConfig` 上添加 `PowerModifier`（具体示例见第四章）。

### 3.2 implementation 全链路贯通：先解析、后使用

**决策**：在 `server.py` 接收到请求后，第一步解析实际使用的 implementation，后续所有步骤基于此 implementation 执行。

**复用现有方法**：`VideoDriverFactory.get_implementation_for_user(task_type, user_id)`（`driver_factory.py:202`），该方法内部调用 `_get_implementation_for_user()`（L265-318），已包含完整的用户偏好 + 可用性检查 + 回退逻辑。

> ⚠️ **注意**：`utils/computing_power.py:190` 也有一个同名的 `get_implementation_for_user(task_type, user_id)` 包装函数，两者功能一致。server.py 中可直接用 `VideoDriverFactory.get_implementation_for_user` 或 `utils.computing_power.get_implementation_for_user`。

**链路**：

```
请求进入 server.py
  │
  ├─ 1. actual_impl = VideoDriverFactory.get_implementation_for_user(task_id, user_id)
  │
  ├─ 2. 从 actual_impl 获取分辨率配置
  │     → impl_config.supported_video_resolutions
  │     → impl_config.default_video_resolution
  │
  ├─ 3. 校验请求中的 resolution 参数
  │     → 不在支持列表 → 拒绝或降级到默认值
  │
  ├─ 4. 计算算力（带 resolution context）
  │     → task_config.get_computing_power(
  │           duration, implementation=actual_impl,
  │           context={'resolution': resolution})
  │
  ├─ 5. 扣费
  │
  ├─ 6. 落库
  │     → ai_tools.implementation = IMPLEMENTATION_TO_ID[actual_impl]  (int)
  │     → extra_config = {"image_mode": ..., "video_resolution": resolution}
  │
  └─ 7. 驱动构建请求时，从 extra_config.video_resolution 读取
```

### 3.3 默认值策略：来自 resolved implementation

**决策**：默认分辨率**必须来自解析出的实际 implementation 的配置**，禁止硬编码。

```python
# 错误 ❌
resolution = form.get('resolution', '720P')

# 正确 ✅
impl_config = UnifiedConfigRegistry.get_implementation(actual_impl)
default_resolution = impl_config.default_video_resolution if impl_config else '720P'
resolution = form.get('resolution') or default_resolution
```

### 3.4 implementation 存储策略：写入表字段（方案 A）

**决策**：将解析出的 implementation 通过 `IMPLEMENTATION_TO_ID` 转换为 int ID，写入 `ai_tools.implementation` 表字段。**不在 `extra_config` 中重复存储实现方名称**。

**理由**：
- `ai_tools` 表已有 `implementation` 字段（`int unsigned`，默认 0），语义正确
- `IMPLEMENTATION_TO_ID` / `get_implementation_name()` 双向映射已存在（`config/unified_config.py:985-1041`）
- `AIToolsModel.create()` 签名已支持 `implementation` 参数（`model/ai_tools.py:100`）
- `visual_task.py:142-144` 退款时已正确读取 `ai_tool.implementation` 并调用 `get_implementation_name()`
- `AITool.to_dict()` 已通过 `get_implementation_name(self.implementation)` 暴露名称

**当前问题**：现有视频入口（`ai_app_run` / `ai_app_run_image`）`create()` 时**未传 implementation**，导致存量记录 `implementation=0`。

**改造方式**：在 `create()` 调用时传入 implementation ID：

```python
from config.unified_config import IMPLEMENTATION_TO_ID

impl_id = IMPLEMENTATION_TO_ID.get(actual_impl, 0)
id = AIToolsModel.create(
    ...,
    implementation=impl_id,    # 新增
    extra_config=extra_config_json,
)
```

**存量数据兼容**：退款时 `impl_id=0` 会走到 `get_implementation_name(0)` 返回 `None`/`'unknown'`，`visual_task.py:144` 已有回退到 `get_implementation_for_user()` 的逻辑，行为可接受。

### 3.5 存储策略：extra_config.video_resolution 为视频分辨率权威来源

**决策**：
- **`extra_config.video_resolution`**：视频分辨率的权威来源（如 `"720P"`、`"1080P"`）
- **`ai_tools.image_size`**：保持原语义（图片尺寸：1K/2K/4K），视频任务时**不写入**此字段
- **`ai_tools.implementation`**：int ID，记录实际使用的实现方（方案 A）

**`build_context_from_task_record()` 改造**：

```python
def build_context_from_task_record(task_record) -> Dict[str, Any]:
    context = {}
    if task_record and hasattr(task_record, 'extra_config') and task_record.extra_config:
        extra = json.loads(task_record.extra_config) if isinstance(task_record.extra_config, str) else task_record.extra_config

        # image_mode（现有逻辑不变）
        if 'image_mode' in extra:
            # ... 现有尾帧判断逻辑 ...
            pass

        # 视频分辨率：仅从 extra_config.video_resolution 读取，不读 image_size
        # （image_size 是图片尺寸 1K/2K/4K，与视频分辨率 720P/1080P 语义不同）
        if 'video_resolution' in extra:
            context['resolution'] = extra['video_resolution']

    # 图片任务的 resolution 仍从 image_size 读取（现有逻辑保持不变）
    # 视频任务的 image_size 为空，不会进入此分支，因此不会误把图片尺寸当视频分辨率
    if 'resolution' not in context:
        if task_record and hasattr(task_record, 'image_size') and task_record.image_size:
            context['resolution'] = task_record.image_size

    return context
```

> **安全边界说明**：图片任务的 `PowerModifier.values` 只有 `1K/2K/4K`，视频任务只有 `720P/1080P`，两者值不重叠，即使 key 名都是 `resolution` 也不会匹配错误。但上述代码通过来源区分避免了隐含依赖。

### 3.6 分辨率选项结构化：支持驱动参数格式差异

**决策**：`ImplementationConfig` 中的分辨率选项使用**结构化字典列表**，包含前端展示值和驱动实际值的映射。

```python
@dataclass
class ImplementationConfig:
    # ... 现有字段（name, display_name, driver_class, default_computing_power 等）...

    # 新增：视频分辨率选项列表（结构化）
    # 空列表 = 不支持分辨率选择
    supported_video_resolutions: List[Dict[str, Any]] = field(default_factory=list)
    # 示例：
    # [
    #     {'value': '720P', 'label': '720P', 'driver_value': '720P'},   # Happy Horse
    #     {'value': '720P', 'label': '720P', 'driver_value': '720p'},   # Vidu（小写）
    #     {'value': '1080P', 'label': '1080P', 'driver_value': '1080P'},
    # ]

    # 新增：默认分辨率 value
    default_video_resolution: str = ''  # 空字符串 = 无默认，取列表第一项
```

> ⚠️ **大小写约束（重要）**：`value` 是系统内部统一标识，**必须在所有环节保持大小写完全一致**：
> - `PowerModifier.values` 的 key（如 `'720P': 1.0`）
> - 前端传参（`form.append('resolution', '720P')`）
> - 数据库存储（`extra_config.video_resolution = '720P'`）
> - `context['resolution']` 的值
>
> **仅传给驱动 API 时**才通过 `driver_value` 转换格式（如 Vidu 需要小写 `720p`）。
> 前端 `modifier.values[attrValue]` 和后端 `modifier.values[attr_value]` 均为**精确匹配、区分大小写**。

**字段说明**：
- `value`：系统内部统一标识（如 `'720P'`），用于 `PowerModifier` 匹配、前端传参、数据库存储
- `label`：前端展示文本
- `driver_value`：传递给具体驱动 API 的实际值（解决 Happy Horse 用大写 `720P`、Vidu 用小写 `720p` 的差异）

### 3.7 后端校验：拒绝不合法分辨率

**决策**：`server.py` 在解析 implementation 后，必须校验 `resolution` 参数。

```python
def validate_resolution(resolution: Optional[str], impl_name: str) -> Optional[str]:
    """
    校验分辨率参数，返回合法值或 None。
    - 实现方不支持分辨率选择 → 返回 None
    - 未传入 → 返回默认值
    - 传入不合法值 → 降级到默认值并记录日志
    """
    if not impl_name:
        return resolution

    impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
    if not impl_config or not impl_config.supported_video_resolutions:
        return None

    valid_values = [r['value'] for r in impl_config.supported_video_resolutions]
    default = impl_config.default_video_resolution or valid_values[0]

    if not resolution:
        return default
    if resolution not in valid_values:
        logger.warning(
            f"Unsupported resolution '{resolution}' for impl '{impl_name}'. "
            f"Valid: {valid_values}. Falling back to '{default}'."
        )
        return default
    return resolution
```

## 四、配置层变更

### 4.1 ImplementationConfig 新增字段

```python
@dataclass
class ImplementationConfig:
    # ... 现有字段 ...
    # name, display_name, driver_class, default_computing_power,
    # enabled, description, driver_params, sort_order, site_number,
    # sync_mode, required_config_keys

    # === 视频分辨率支持（新增）===
    supported_video_resolutions: List[Dict[str, Any]] = field(default_factory=list)
    default_video_resolution: str = ''
```

### 4.2 配置示例

#### Happy Horse 图生视频（3 个实现方都需要配置）

```python
# happy_horse_dashscope_v1 - 图生视频
ImplementationConfig(
    name='happy_horse_dashscope_v1',
    display_name='阿里云百炼',
    driver_class='HappyHorseDashscopeV1Driver',    # 注意：Dashscope（全小写 scope）
    default_computing_power={3: 69, 5: 115, 8: 184, 10: 230, 15: 345},
    enabled=True,
    description='阿里云百炼 Happy Horse 图生视频接口',
    sort_order=10800.0,
    required_config_keys=['llm.qwen.api_key'],
    # 新增
    supported_video_resolutions=[
        {'value': '720P', 'label': '720P', 'driver_value': '720P'},
        {'value': '1080P', 'label': '1080P', 'driver_value': '1080P'},
    ],
    default_video_resolution='720P',
),

# happy_horse_dashscope_r2v_v1 - 参考生视频
ImplementationConfig(
    name='happy_horse_dashscope_r2v_v1',
    display_name='阿里云百炼',
    driver_class='HappyHorseDashscopeR2VV1Driver',
    default_computing_power={3: 69, 5: 115, 8: 184, 10: 230, 15: 345},
    # ... 同样添加分辨率配置 ...
),

# happy_horse_dashscope_t2v_v1 - 文生视频
ImplementationConfig(
    name='happy_horse_dashscope_t2v_v1',
    display_name='阿里云百炼',
    driver_class='HappyHorseDashscopeT2VV1Driver',
    default_computing_power={3: 69, 5: 115, 8: 184, 10: 230, 15: 345},
    # ... 同样添加分辨率配置 ...
),
```

#### Vidu（前提：驱动需先实现 resolution 支持）

> ⚠️ **前置依赖**：当前 `vidu_q2_driver.py` **完全没有解析 resolution**（无 `_parse_extra_params`，无 resolution 参数传递）；而 `vidu_default_driver.py` 则**硬编码** `"resolution": "720p"`（不可配置）。要给 Vidu 配置可选择的分辨率，**必须先在驱动代码中实现从 `extra_config.video_resolution` 读取并传递到 Vidu API**。在此之前，不要配置 `supported_video_resolutions`。

```python
# vidu_default - Vidu 默认
ImplementationConfig(
    name='vidu_default',
    display_name='Vidu',
    driver_class='ViduDefaultDriver',         # 注意：不是 ViduVideoDriver
    default_computing_power={5: 16, 8: 22},
    # 待驱动实现后再添加分辨率配置
),

# vidu_q2 - Vidu Q2
ImplementationConfig(
    name='vidu_q2',
    display_name='Vidu Q2',
    driver_class='ViduQ2Driver',              # 注意：不是 ViduQ2VideoDriver
    default_computing_power={5: 45, 8: 60},
    # 待驱动实现后再添加分辨率配置
),
```

#### 不支持分辨率的实现方（无需改动）

```python
# sora2_duomi_v1 等 - 不配置 supported_video_resolutions → 前端不显示选择器
ImplementationConfig(
    name='sora2_duomi_v1',
    display_name='多米',
    driver_class='Sora2DuomiV1Driver',
    default_computing_power={5: 15, 10: 25, 15: 35},
    # supported_video_resolutions 默认空列表 → 前端隐藏分辨率选择器
),
```

### 4.3 UnifiedTaskConfig 配套变更（PowerModifier）

Happy Horse 有 **3 个任务类型**，当前均**没有任何 `power_modifiers`**。若都需要分辨率计费，需逐个添加：

```python
# 1. Happy Horse 图生视频（TASK_ID: HAPPY_HORSE_IMAGE_TO_VIDEO）
UnifiedTaskConfig(
    id=TaskTypeId.HAPPY_HORSE_IMAGE_TO_VIDEO,
    key='happy_horse_image_to_video',
    short_key='happy_horse',
    # ... 现有字段（无 power_modifiers）...
    supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 仅首帧，不支持尾帧
    supports_last_frame=False,
    # 新增：仅 resolution 修饰符（无 image_mode 修饰符，因 Happy Horse 不支持尾帧）
    power_modifiers=[
        PowerModifier(
            attribute='resolution',
            values={'720P': 1.0, '1080P': 1.5},
            default=1.0
        )
    ],
),

# 2. Happy Horse 多参考（TASK_ID: HAPPY_HORSE_REFERENCE_TO_VIDEO）
UnifiedTaskConfig(
    id=TaskTypeId.HAPPY_HORSE_REFERENCE_TO_VIDEO,
    key='happy_horse_reference_to_video',
    short_key='happy_horse_r2v',
    # ... 同样添加 resolution PowerModifier ...
),

# 3. Happy Horse 文生视频（TASK_ID: HAPPY_HORSE_TEXT_TO_VIDEO）
UnifiedTaskConfig(
    id=TaskTypeId.HAPPY_HORSE_TEXT_TO_VIDEO,
    key='happy_horse_text_to_video',
    short_key='happy_horse_t2v',
    # ... 同样添加 resolution PowerModifier ...
),
```

> ⚠️ **对比 Kling**：Kling 图生视频（`unified_config.py:1499-1508`）已有 `image_mode` PowerModifier（`first_last_with_tail: 1.66`），因为 Kling 支持尾帧。Happy Horse 不支持尾帧，**不要给它加 image_mode 修饰符**。

## 五、后端 server.py 改造（核心入口）

### 5.1 公共校验函数

在 `server.py` 顶部新增（或提取到 `utils/` 模块）：

```python
from config.unified_config import UnifiedConfigRegistry, IMPLEMENTATION_TO_ID

def validate_resolution(resolution: Optional[str], impl_name: str) -> Optional[str]:
    """校验分辨率参数（见 3.7 节完整实现）"""
    # ... 见 3.7 节 ...
```

### 5.2 `/api/ai-app-run`（文生视频，server.py:1748）

**当前问题**：
- 无 `resolution` 参数
- `create()` 无 `extra_config`，无 `implementation`（L1833 只传基本字段）
- 算力计算不带 implementation 和 resolution context（L1775：`task_config.get_computing_power(duration=duration_seconds)`）

**改造**：

```python
@app.post("/api/ai-app-run")
async def ai_app_run(
    ...,
    resolution: str = Form(None, description="视频分辨率，如 720P、1080P（可选）")  # 新增
):
    task_config = UnifiedConfigRegistry.get_by_id(task_id)
    # ... 现有验证逻辑 ...

    # ★ 1. 解析实际 implementation
    from task.visual_drivers.driver_factory import VideoDriverFactory
    actual_impl = VideoDriverFactory.get_implementation_for_user(task_id, user_id)

    # ★ 2. 校验 resolution
    resolution = validate_resolution(resolution, actual_impl)

    # ★ 3. 构建 context 并计算算力
    context = {}
    if resolution:
        context['resolution'] = resolution

    computing_power = task_config.get_computing_power(
        duration=duration_seconds,
        implementation=actual_impl,   # 新增
        context=context                # 新增
    )

    # ... 现有余额检查和扣费逻辑 ...

    # ★ 4. 创建记录：extra_config 只存 video_resolution；implementation 写入表字段（遵循 3.4 决策）
    #    不在 extra_config 重复存储实现方名称（退款时用 ai_tools.implementation int ID 还原）
    extra_config_data = {}
    if resolution:
        extra_config_data['video_resolution'] = resolution
    extra_config_json = json.dumps(extra_config_data) if extra_config_data else None

    impl_id = IMPLEMENTATION_TO_ID.get(actual_impl, 0) if actual_impl else 0

    id = AIToolsModel.create(
        prompt=prompt,
        user_id=user_id,
        type=text_to_video_type,
        ratio=ratio,
        transaction_id=transaction_id,
        duration=duration_seconds,
        status=AI_TOOL_STATUS_PENDING,
        extra_config=extra_config_json,  # 新增
        implementation=impl_id,          # 新增（int ID）
        # image_size 不写入（保持图片尺寸语义）
    )
```

### 5.3 `/api/ai-app-run-image`（图生视频，server.py:1869）

**当前问题**：
- 无 `resolution` 参数
- `extra_config` 只写 `{'image_mode': image_mode}`（L2097）
- 算力计算不带 implementation（L2032）

**改造**：

```python
@app.post("/api/ai-app-run-image")
async def ai_app_run_image(
    ...,
    resolution: str = Form(None, description="视频分辨率，如 720P、1080P（可选）")  # 新增
):
    task_config = UnifiedConfigRegistry.get_by_id(task_id)
    # ... 现有验证逻辑 ...

    # ★ 1. 解析实际 implementation
    from task.visual_drivers.driver_factory import VideoDriverFactory
    actual_impl = VideoDriverFactory.get_implementation_for_user(task_id, user_id)

    # ★ 2. 校验 resolution
    resolution = validate_resolution(resolution, actual_impl)

    # ★ 3. 构建 context（现有 image_mode + 新增 resolution）
    context = {}
    if image_mode == 'first_last_frame' and main_image_list and len(main_image_list) > 1:
        context['image_mode'] = 'first_last_with_tail'
    elif image_mode:
        context['image_mode'] = image_mode
    if resolution:
        context['resolution'] = resolution

    computing_power = task_config.get_computing_power(
        duration=duration_seconds,
        implementation=actual_impl,  # 新增
        context=context               # 已包含 resolution
    )

    # ... 现有余额检查和扣费逻辑 ...

    # ★ 4. extra_config 增加 video_resolution（不存 implementation，遵循 3.4 决策）
    extra_config_data = {'image_mode': image_mode}
    if resolution:
        extra_config_data['video_resolution'] = resolution
    extra_config_json = json.dumps(extra_config_data)

    impl_id = IMPLEMENTATION_TO_ID.get(actual_impl, 0) if actual_impl else 0

    # AIToolsModel.create() 调用处新增 implementation 参数
    id = AIToolsModel.create(
        ...,
        extra_config=extra_config_json,
        implementation=impl_id,       # 新增
    )
```

## 六、退款调用链验证与修复

### 6.1 `visual_task.py` 退款（L140-152）—— ✅ 已正确实现

```python
# visual_task.py:140-152
context = build_context_from_task_record(ai_tool)
impl_id = getattr(ai_tool, 'implementation', None)
impl_name = get_implementation_name(impl_id) if impl_id else None
implementation = impl_name if impl_name and impl_name != 'unknown' else get_implementation_for_user(ai_tool_type, user_id)

computing_power = get_computing_power_for_task(
    task_type=ai_tool_type,
    duration=getattr(ai_tool, 'duration', 5),
    user_id=user_id,
    implementation=implementation,
    context=context
)
```

此链路已正确传递 `implementation` 和 `context`。新数据（`implementation` 正确写入 int ID）可直接还原；旧数据（`implementation=0`）回退到用户当前偏好，行为可接受。

### 6.2 `server.py:1605-1606` 退款（RunningHub 状态检查回调）—— ❌ 需修复

```python
# 当前代码（BUG）：
context = build_context_from_task_record(task_record)
computing_power = task_config.get_computing_power(
    duration=task_record.duration, context=context
) if task_config else 0
# 缺少 implementation 参数！
```

**修复**：

```python
# 修复后：
context = build_context_from_task_record(task_record)
from config.unified_config import get_implementation_name
impl_id = getattr(task_record, 'implementation', None)
impl_name = get_implementation_name(impl_id) if impl_id else None
# ⚠️ 旧数据 implementation=0 → impl_name=None。为与 visual_task.py:140-144 口径一致
# （退款算力对齐"用户当前偏好实现方"而非"默认实现方"），建议此处同样回退：
#   implementation = impl_name if impl_name and impl_name != 'unknown' else get_implementation_for_user(task_type, user_id)
# 并把下方 implementation=impl_name 改为 implementation=implementation。
computing_power = task_config.get_computing_power(
    duration=task_record.duration,
    implementation=impl_name,  # 新增（建议改为带回退的变量，见上方注释）
    context=context
) if task_config else 0
```

> 这本身是既有 bug（image_mode 修饰符在此链路也未生效），本方案顺带修复。

## 七、前端 task_config.js 改造

### 7.1 新增函数

```javascript
/**
 * 获取指定实现方支持的视频分辨率选项
 * @param {string} modelKey 模型标识符（short_key）
 * @param {string} [implName] 实现方名称（可选，默认使用实现方列表第一项）
 * @returns {Array<{value: string, label: string, driverValue: string}>}
 */
function getVideoResolutionOptions(modelKey, implName) {
    const task = getTaskByKey(modelKey);
    if (!task || !task.implementations || task.implementations.length === 0) {
        return [];
    }

    const impl = implName
        ? task.implementations.find(i => i.name === implName)
        : task.implementations[0];

    if (!impl || !impl.supported_video_resolutions || impl.supported_video_resolutions.length === 0) {
        return [];
    }

    return impl.supported_video_resolutions.map(r => ({
        value: r.value,
        label: r.label || r.value,
        driverValue: r.driver_value || r.value
    }));
}

/**
 * 获取默认视频分辨率
 */
function getDefaultVideoResolution(modelKey, implName) {
    const task = getTaskByKey(modelKey);
    if (!task || !task.implementations) return null;

    const impl = implName
        ? task.implementations.find(i => i.name === implName)
        : task.implementations[0];

    if (impl && impl.default_video_resolution) return impl.default_video_resolution;

    const options = getVideoResolutionOptions(modelKey, implName);
    return options.length > 0 ? options[0].value : null;
}
```

### 7.2 修改 getModelConfigs 输出

```javascript
function getModelConfigs() {
    const tasks = getAllTasks();
    const result = {};
    tasks.forEach(task => {
        const shortKey = task.short_key || task.key;
        result[shortKey] = {
            // ... 现有字段 ...
            ratios: task.supported_ratios || [],
            durations: task.supported_durations || [],
            // 新增
            video_resolutions: getVideoResolutionOptions(shortKey),
            default_video_resolution: getDefaultVideoResolution(shortKey),
        };
    });
    return result;
}
```

### 7.3 getComputingPower 无需改动

`getComputingPower()` 已支持 `power_modifiers` 中的 `resolution` 属性。前端只需在调用时传入 `context.resolution`，现有逻辑即可正确处理乘数计算：

```javascript
const context = { image_mode: 'first_last_frame', resolution: '1080P' };
const power = TaskConfig.getComputingPower(modelKey, duration, context);
// PowerModifier 自动匹配 '1080P' → 1.5 乘数
```

### 7.4 导出新增函数

```javascript
window.TaskConfig = {
    // ... 现有导出 ...
    getVideoResolutionOptions,
    getDefaultVideoResolution,
};
```

## 八、后端 to_frontend_dict 改造

在 `_get_implementations_info()` 中输出分辨率配置：

```python
def _get_implementations_info(self) -> List[Dict[str, Any]]:
    result = []
    for impl_name in impl_names:
        impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
        info = {
            'name': impl_name,
            'display_name': impl_config.display_name,
            'computing_power': impl_config.computing_power,
            # ... 现有字段 ...
            # 新增
            'supported_video_resolutions': impl_config.supported_video_resolutions,
            'default_video_resolution': impl_config.default_video_resolution,
        }
        result.append(info)
    return result
```

## 九、驱动层改造

### 9.1 从 extra_config 读取 video_resolution

各视频驱动在构建请求时，统一从 `extra_config.video_resolution` 读取分辨率。

**Happy Horse 驱动**（已有 `_parse_extra_params`，改动最小）：

```python
def _parse_extra_params(self, ai_tool) -> Dict[str, Any]:
    params = {"resolution": "720P"}  # 默认值

    if not ai_tool.extra_config:
        return params

    config = json.loads(ai_tool.extra_config) if isinstance(ai_tool.extra_config, str) else ai_tool.extra_config

    # 优先从 video_resolution 读取（兼容旧的 resolution 字段）
    resolution = config.get('video_resolution') or config.get('resolution')
    if resolution and resolution in ('720P', '1080P'):
        params['resolution'] = resolution

    return params
```

### 9.2 通用 driver_value 映射

对于需要不同大小写的驱动（如 Vidu），使用配置中的 `driver_value`：

```python
def get_driver_resolution(self, ai_tool) -> Optional[str]:
    """从 extra_config 读取分辨率并映射为驱动实际值"""
    if not ai_tool.extra_config:
        return None

    config = json.loads(ai_tool.extra_config) if isinstance(ai_tool.extra_config, str) else ai_tool.extra_config
    resolution = config.get('video_resolution')
    if not resolution:
        return None

    # 从实现方配置获取 driver_value 映射
    impl_id = getattr(ai_tool, 'implementation', None)
    if impl_id:
        from config.unified_config import get_implementation_name
        impl_name = get_implementation_name(impl_id)
        if impl_name:
            impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
            if impl_config:
                for r in (impl_config.supported_video_resolutions or []):
                    if r['value'] == resolution:
                        return r.get('driver_value', resolution)

    return resolution  # 回退：直接传原始值
```

## 十、前端各页面改造

### 10.1 前端公共调用模式

所有页面遵循统一模式：

```javascript
// 1. 获取分辨率选项
const resolutions = TaskConfig.getVideoResolutionOptions(modelKey);

// 2. 用户选择后，计算算力（自动联动）
const context = { image_mode: currentMode, resolution: selectedResolution };
const power = TaskConfig.getComputingPower(modelKey, duration, context);

// 3. 提交时 append resolution
form.append('resolution', selectedResolution);
```

### 10.2 video_workflow.html（制作工坊）

**改动位置**：图生视频节点（`image_to_video` 类型），在「视频比例」选择器旁新增「分辨率」选择器。

**涉及文件与调用点**：

| 文件 | 行号（参考） | API 端点 | 改动 |
|------|------------|---------|------|
| `web/js/nodes.js` | L11525-11530 | `/api/ai-app-run` | 画布文生视频 append resolution |
| `web/js/nodes.js` | L11543-11548 | `/api/ai-app-run-image` | 画布参考图生视频 append resolution |
| `web/js/nodes.js` | L11560-11565 | `/api/ai-app-run-image` | 画布首尾帧生视频 append resolution |

**算力显示联动（连带修复 image_mode 未传 context 的既有 bug）**：

| 文件 | 函数 | 改动 |
|------|------|------|
| `web/js/workflow.js:219` | `calculateVideoGenerationPower(videoModel, duration)` | 新增 context 参数，传入 image_mode + resolution |
| `web/js/workflow.js:227` | `updateAllImageToVideoNodesPower()` | 从 node.data 读取 image_mode 和 resolution，传入 context |

> ⚠️ **连带修复**：`calculateVideoGenerationPower` 当前只调 `getComputingPower(videoModel, duration)` 不传 context（`workflow.js:221`），意味着画布算力**连 image_mode 乘数都没生效**（Kling 尾帧模式 1.66x 在画布中未体现）。本次一并修复，将 image_mode 和 resolution 一起传入 context。

### 10.3 index.html（首页 AI 工具面板）

**涉及调用点**：

| 行号（参考） | API 端点 | 场景 |
|------------|---------|------|
| L4893 | `/api/ai-app-run-image` | 首页图生视频 |
| L5661 | `/api/ai-app-run` | 首页文生视频 |
| L6440 | `/api/ai-app-run-image` | 首页视频工作流 |
| L6749 | `/api/ai-app-run-image` | 首页另一处图生视频 |

### 10.4 marketing_agent.html（营销智能体）

**涉及调用点**：

| 行号（参考） | API 端点 | 场景 |
|------------|---------|------|
| L2869 | `/api/ai-app-run-image` | 营销智能体图生视频 |
| L2879 | `/api/ai-app-run` | 营销智能体文生视频 |

### 10.5 shot_frame_video_generator.js（分镜视频生成）

**涉及调用点**：

| 行号（参考） | API 端点 | 场景 |
|------------|---------|------|
| L182 | `/api/ai-app-run-image` | 分镜参考图生视频 |
| L196 | `/api/ai-app-run` | 分镜文生视频回退 |
| L207+ | `/api/ai-app-run-image` | 分镜首帧生视频 |

### 10.6 digital_human_node.js（数字人节点）

| 行号（参考） | API 端点 | 场景 |
|------------|---------|------|
| L393 | `/api/ai-app-run-image` | 数字人节点生成视频 |

> 数字人节点当前使用 `digital_human` 任务类型，如果其实现方（`digital_human_runninghub_v1`）不支持分辨率选择，前端不会显示选择器，此处 append 为空操作。但为统一模式仍需处理。

### 10.7 web/js/api.js（公共 API 封装）

`generateVideoFromImage()` 和 `generateVideoFromText()` 函数签名新增 `resolution` 参数：

```javascript
async function generateVideoFromImage(imageUrl, prompt, duration, count, ratio, videoModel, imageMode, referenceImages, audioUrls, videoUrls, mediaReferences, resolution) {
    if (resolution) form.append('resolution', resolution);
}

async function generateVideoFromText(prompt, duration, count, ratio, videoModel, resolution) {
    if (resolution) form.append('resolution', resolution);
}
```

## 十一、涉及修改的文件完整清单

| # | 文件 | 改动类型 | 说明 |
|---|------|---------|------|
| 1 | **`server.py`** | **修改** | 两个入口函数新增 `resolution` 参数、解析 implementation、校验分辨率、改造 extra_config 和算力计算、写入 implementation int ID；RunningHub 退款链路修复 implementation 传递 |
| 2 | `config/unified_config.py` | 修改 | `ImplementationConfig` 新增 2 字段；`_get_implementations_info()` 输出新字段；Happy Horse 3 个任务类型添加 `resolution` PowerModifier |
| 3 | `utils/computing_power.py` | 修改 | `build_context_from_task_record()` 优先从 `extra_config.video_resolution` 读取，视频不回退 `image_size` |
| 4 | `web/js/task_config.js` | 修改 | 新增 `getVideoResolutionOptions()`、`getDefaultVideoResolution()`；`getModelConfigs()` 补充分辨率信息 |
| 5 | `web/js/api.js` | 修改 | `generateVideoFromImage()`、`generateVideoFromText()` 新增 `resolution` 参数 |
| 6 | `web/js/nodes.js` | 修改 | 图生视频节点新增分辨率选择器 UI，3 处 FormData 调用点 append resolution |
| 7 | `web/js/workflow.js` | 修改 | `calculateVideoGenerationPower()` 新增 context 参数（连带修复 image_mode 未传的既有 bug） |
| 8 | `web/js/shot_frame_video_generator.js` | 修改 | 3 处 FormData 调用点 append resolution |
| 9 | `web/js/digital_human_node.js` | 修改 | 1 处 FormData 调用点 append resolution（若实现方不支持则为空操作） |
| 10 | `web/index.html` | 修改 | 视频生成面板新增分辨率 UI，4 处 FormData 调用点 append resolution |
| 11 | `web/marketing_agent.html` | 修改 | 视频模式新增分辨率 UI，2 处 FormData 调用点 append resolution |
| 12 | `task/visual_drivers/happy_horse_dashscope_v1_driver.py` | 修改 | `_parse_extra_params()` 优先从 `video_resolution` 读取（兼容旧 `resolution`） |
| 13 | Happy Horse r2v/t2v 驱动 | 无需单独改动 | r2v/t2v 是 `happy_horse_dashscope_v1_driver.py` 中 v1 的子类（继承 `_parse_extra_params`），改 v1 一处即全部生效 |
| 14 | Vidu 驱动（vidu_default、vidu_q2） | 待改造 | 需先实现 resolution 读取，再配置 `supported_video_resolutions` |
| 15 | `web/i18n/` | 修改 | 新增 `video_resolution`、`video_resolution_720p`、`video_resolution_1080p` 等国际化 key（中英两份 locale） |

## 十二、前端 FormData 调用点完整清单

**以下所有位置在提交视频生成任务时，均需要 `form.append('resolution', selectedResolution)`：**

> 行号为参考值，以实际代码为准。

| 文件 | 行号（参考） | API 端点 | 场景 |
|------|------------|---------|------|
| `web/js/api.js` | ~L89-124 | `/api/ai-app-run-image` | 图生视频（公共封装） |
| `web/js/api.js` | ~L162-170 | `/api/ai-app-run` | 文生视频（公共封装） |
| `web/js/nodes.js` | ~L11525-11530 | `/api/ai-app-run` | 画布文生视频 |
| `web/js/nodes.js` | ~L11543-11548 | `/api/ai-app-run-image` | 画布参考图生视频 |
| `web/js/nodes.js` | ~L11560-11565 | `/api/ai-app-run-image` | 画布首尾帧生视频 |
| `web/js/shot_frame_video_generator.js` | ~L177-182 | `/api/ai-app-run-image` | 分镜参考图生视频 |
| `web/js/shot_frame_video_generator.js` | ~L194-196 | `/api/ai-app-run` | 分镜文生视频回退 |
| `web/js/shot_frame_video_generator.js` | ~L205-207+ | `/api/ai-app-run-image` | 分镜首帧生视频 |
| `web/js/digital_human_node.js` | ~L393 | `/api/ai-app-run-image` | 数字人节点 |
| `web/index.html` | ~L4893 | `/api/ai-app-run-image` | 首页图生视频 |
| `web/index.html` | ~L5661 | `/api/ai-app-run` | 首页文生视频 |
| `web/index.html` | ~L6440 | `/api/ai-app-run-image` | 首页视频工作流 |
| `web/index.html` | ~L6749 | `/api/ai-app-run-image` | 首页另一处图生视频 |
| `web/marketing_agent.html` | ~L2869 | `/api/ai-app-run-image` | 营销智能体图生视频 |
| `web/marketing_agent.html` | ~L2879 | `/api/ai-app-run` | 营销智能体文生视频 |

## 十三、向下兼容策略

| 场景 | 处理方式 |
|------|---------|
| 实现方未配置 `supported_video_resolutions`（空列表） | 前端隐藏分辨率选择器；后端校验返回 None |
| 前端未传 `resolution` 参数 | 后端使用实现方的 `default_video_resolution` 或列表第一项 |
| 旧数据 `extra_config` 中无 `video_resolution` | `build_context_from_task_record()` 不设 `resolution` context，PowerModifier 走 default=1.0 |
| 旧数据 `ai_tools.implementation=0` | 退款时 `get_implementation_name(0)` 返回 None，`visual_task.py:144` 回退到用户当前偏好 |
| 旧驱动不识别 `video_resolution` | Happy Horse 同时兼容 `video_resolution` 和旧的 `resolution` 字段 |
| `UnifiedTaskConfig` 未添加 `resolution` PowerModifier | 算力计算中 resolution 属性匹配不到，使用 default=1.0，不额外扣费 |
| 数据库 | **无需迁移**，`extra_config` 和 `implementation` 字段已存在 |

## 十四、验证清单

- [ ] 前端选择 1080P 后，算力显示 × 1.5 倍
- [ ] 前端切换视频模型时，分辨率选项自动更新
- [ ] 前端切换实现方（用户偏好）时，分辨率选项自动更新
- [ ] 后端收到的 resolution 经校验后才落库
- [ ] 伪造 resolution=4K 提交 → 后端降级到默认值
- [ ] `ai_tools.implementation` 正确写入 int ID（非 0）
- [ ] `visual_task.py` 退款时能正确还原 implementation 和 resolution context
- [ ] `server.py:1605` RunningHub 退款链路传递 implementation（既有 bug 修复验证）
- [ ] 驱动构建请求时使用正确的 `driver_value`
- [ ] 未配置分辨率的实现方（如 Sora2），前端不显示选择器，后端不校验
- [ ] Kling 尾帧模式在画布中算力显示正确（连带修复 image_mode context 验证）

## 十五、前端剩余入口接入（补充实现）

> 第十章列出了前端各页面的 FormData 调用点。其中 `index.html`（图生/文生视频）、`video_workflow.html`「生视频」节点、`marketing_agent.html` 视频模式主体在 v3 落地时已完整实现分辨率 UI；本节记录随后补齐的**四个剩余入口**，使所有视频生成路径都可选择分辨率并正确送达后端。

### 15.1 设计原则（与已实现入口一致）

- **复用 `TaskConfig.getVideoResolutionOptions(modelKey)`** 判空：返回空数组表示该模型不支持分辨率 → 隐藏选择器并清空字段；否则渲染选项，缺省值取 `TaskConfig.getDefaultVideoResolution(modelKey)`。
- **提交统一走 `appendVideoResolutionToForm(form, videoModel, resolution)`**（`web/js/api.js`）：第三参非空时直接用，为空回退模型默认；模型不支持时 `getDefaultVideoResolution` 返回 null，不 append，后端不会收到非法值。
- **算力联动**：调用 `TaskConfig.getComputingPower(videoModel, duration, context)`，`context.resolution` 命中 `PowerModifier` 自动应用倍率。

### 15.2 video_workflow.html「分镜」节点（`web/js/shot_frame_node.js`）

照搬「生视频」节点（`createVideoNode` 的 `updateResolutionOptions`）模式：

- 数据字段 `videoResolution`：从 `opts.videoResolution` / `shotData.videoResolution` 继承（分镜组创建子分镜时传入）；工作流序列化由 `serializeWorkflow()` 自动保存。
- UI：`.shot-frame-video-resolution-field` + `.shot-frame-video-resolution-select`（默认隐藏）。
- `updateShotFrameResolutionOptions(videoModel)`：填充选项、判空隐藏、设默认、回显；挂在 `node.updateShotFrameResolutionOptions` 供外部刷新。
- 触发刷新：初始化、视频模型 change、生成方式切换（首尾帧↔全能参考会换模型列表）。
- 算力：`calculateVideoComputingPower` 构造 `context.resolution` 传入 `getComputingPower`。
- 提交：`shot_frame_video_generator.js` 的 `appendVideoResolutionToForm(form, videoModel, node.data.videoResolution)`（三处提交路径共用一行）。
- **复原**：`createShotFrameNodeWithData`（`workflow.js`）合并 `nodeData.data` 后，显式调用 `node.updateShotFrameResolutionOptions(node.data.videoModel)` 回显。

### 15.3 video_workflow.html「分镜组」节点（`web/js/shot_group_node.js` + `web/js/nodes.js`）

同 15.2 模式，另需注意：

- 数据字段 `videoResolution` 从 `shotGroupData.videoResolution` 读取；复原经 `createShotGroupNodeWithData` → `createShotGroupNode({ shotGroupData: nodeData.data })` 自动恢复。
- `updateShotGroupResolutionOptions(videoModel)` 挂到 `node`；模型 change 与 `populateShotGroupVideoModelOptions`（模式切换）均触发刷新。
- 算力函数 `calculateVideoComputingPower`（`web/js/shot_group_node.js`）构造 `context.resolution`。
- 提交：`generateShotGroupVideo`（`web/js/nodes.js`）三处 `appendVideoResolutionToForm(form, videoModel, shotGroupNode.data.videoResolution)`。
- **继承到子分镜**：`syncShotFramesToShots` 创建分镜节点时透传 `videoResolution: shotGroupNode.data.videoResolution`，使「逐个生成」沿用分镜组分辨率。

### 15.4 TaskConfig 异步加载的时序竞争修复

节点可能在 `TaskConfig.load()` 完成前创建（使用 hardcoded fallback）。`fetchComputingPowerConfig`（`workflow.js`）在配置加载后会调用 `refreshShotGroupNodesModels` / `refreshShotFrameNodesModels` 重填模型 select。本次在这两个刷新函数末尾追加调用 `node.updateShotGroupResolutionOptions` / `node.updateShotFrameResolutionOptions`，确保分辨率选择器在配置加载后正确显示（与模型 select 的修复同源）。

### 15.5 marketing_inspiration.html（灵感页）

灵感页不直连后端，而是把参数拼成 URL 跳转 `/marketing-agent?...`（`goToGenerate`）。

- **Agent 视频模式**：自定义设置面板新增 `#agentVideoResolutionGroup`（复用 `.agent-resolution-list` 样式）；`renderAgentVideoResolutionList()` 用 `TaskConfig.getVideoResolutionOptions(agentModelKey)` 动态渲染，按钮项使用 **`data-vres` 属性**（避免与图片分辨率的 `.mk-agent-res`/`data-resolution` 误命中）；媒体类型与模型切换时重渲染。
- **纯视频模式**：新增独立 `#videoResolutionDropdown`（不复用图片的 `#resolutionGroup`），`renderVideoResolutionMenu()` 动态渲染。
- 提交：Agent 视频分支与非 Agent 视频分支均写入 `opts.video_resolution`；`goToGenerate` 透传 `video_resolution` URL 参数。
- **URL key 命名**：视频用 `video_resolution`，与图片的 `resolution` 区分，避免相互覆盖。

### 15.6 marketing_agent.html / web/js/marketing_agent.js 视频分辨率

- 页面模板在 Agent 视频设置面板和底部视频比例面板渲染 `currentVideoResolutionOptions`；图片分辨率仍使用 `selectedResolution`，视频分辨率使用独立的 `selectedVideoResolution`。
- `ensureSelectedVideoResolution()` 基于当前视频模型调用 `TaskConfig.getVideoResolutionOptions()` / `getDefaultVideoResolution()`，模型切换时自动降级到合法默认值。
- 直接视频生成 `sendVideoRequest()` 在提交前调用 `ensureSelectedVideoResolution()`，并通过 `form.append('resolution', videoResolution)` 传给 `/api/ai-app-run` 或 `/api/ai-app-run-image`。
- Agent 视频对话任务在 `video_preferences.resolution` 写入同一分辨率，供后端工具层继续透传。

### 15.7 i18n

新增 key `video_resolution`（`web/i18n/locales/{zh-CN,en}/marketing_inspiration.json`）；`video_workflow.json`、`marketing_agent.json` 已存在该 key，分镜/分镜组节点直接复用。

### 15.8 智能体模式下分辨率作为 `video_preferences` 透传（修复 BUG）

营销智能体的直接视频生成入口（`marketing_agent.html` 非 Agent 视频模式）已在 10.4 / 12 节覆盖。但**智能体对话模式**（`selectedType === 'agent'`）下，视频由 MCP 工具函数 `enterprise/tools/video_tools.py` 代为提交，曾存在分辨率无法到达实际生成接口的 BUG，表现为：用户选择 480P，实际仍按驱动默认 720P 生成。

修复后的完整链路：

```
前端 web/js/marketing_agent.js
  sendMessageToApi()
    → video_preferences.resolution = ensureSelectedVideoResolution() || undefined
    → POST /api/session/{id}/task

后端 api/script_writer.py
    → set_video_preferences(user_id, world_id, v_prefs) 写入缓存
    → v_pref_parts 追加 "视频分辨率: {resolution}" 给 LLM

后端 enterprise/tools/video_tools.py
    → user_prefs = _get_video_preferences(user_id, world_id)
    → resolution = _resolve_video_resolution(user_prefs, config, actual_impl)
        （复用 validate_video_resolution，与 server.py 端点同一口径）
    → request_data['resolution'] = resolution
    → config.get_computing_power(..., implementation=actual_impl, context={'resolution': resolution})
    → POST /api/ai-app-run 或 /api/ai-app-run-image
```

关键实现点：
- `video_preferences` 新增 `resolution` 字段，空串转 `undefined`，避免空值覆盖缓存中的有效分辨率。
- `_resolve_video_resolution` 对 `auto` 或空偏好回退到实现方默认；非法值降级到默认；实现方不支持分辨率选择时返回 `None`。
- 算力估算补齐 `implementation` 与 `context.resolution`，与 `server.py` 端点扣费口径一致。

相关文件：
- `web/marketing_agent.html`
- `api/script_writer.py`
- `enterprise/tools/video_tools.py`
- `utils/video_resolution.py`（复用校验逻辑）
- `tests/js/test_marketing_agent_agent_video_preferences.js`（新增 resolution 断言）
- `tests/agents/test_video_tools_resolution.py`（新增后端透传测试）

### 15.9 页面拆分后的回归保护

后续 `index.html` 与 `video_workflow.html` 已将大量内联脚本拆到独立文件。分辨率相关回归测试需覆盖拆分后的真实文件：

- 首页工具页：`web/js/pages/ai_video_gen.js`、`web/js/pages/image_to_video.js` 持有 `videoResolution` 状态、选项、算力 context 与 `FormData resolution`。
- 工作流节点：`web/js/shot_frame_node.js`、`web/js/shot_group_node.js` 渲染选择器和计算算力；`web/js/nodes.js` 负责分镜组提交与分镜组分辨率继承。
- 营销智能体：`web/marketing_agent.html` 只负责模板显示，状态和提交逻辑位于 `web/js/marketing_agent.js`。
- `tests/js/test_video_resolution_frontend_wiring.js` 同时扫描上述拆分文件，防止后续合并再次丢失前端 wiring。


