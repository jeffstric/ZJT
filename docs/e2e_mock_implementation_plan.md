# E2E 测试挡板（Mock）完整实施方案

> 本文档**自包含**，无需参考 `e2e_mock_design.md` / `e2e_mock_design_revision_notes.md` 即可直接据此实施。所有文件路径、函数签名、行号、响应结构均已对照当前代码库（分支 `develop_427`）核实。实施时若发现行号漂移，以**函数名/关键字**为准重新定位。

---

## 0. 一句话目标

开启 `test_mode.enabled` 后，端到端链路（**剧本生成 → 分镜 → 图片/音频/视频生成 → 四宫格/多角度 → 人脸遮盖 → 时间轴合成**）中除 LLM 外的所有外部付费**生成 API** 调用与外部下载都被挡板拦截，返回预设本地媒体资源。算力扣费、CDN 上传等副作用**保留真实执行**（靠独立隔离环境 + 测试前重置账户算力，见 §6），不绕过以保证测试完整性；测试数据采用幂等播种、不做清理（见 §14）。

**关键约束（来自 `.claude/CLAUDE.md`）**：
1. web 接口与内部函数必须**非阻塞**；禁止在异步函数中调用同步阻塞 IO（如 `requests`）。
2. 功能改动同步 `docs/`。
3. 兼容 Windows / Linux / macOS（路径与编码）。
4. 改表结构需同步 `alembic/versions` 与 model SQL。

---

## 1. 背景与现状基线

### 1.1 现有 test_mode（已落地，但仅覆盖两处）

`config/default_configs.py:148-183` 定义了 `test_mode.enabled` 及 4 个 mock URL 配置。实际代码中只有：

- `task/visual_task.py:231`、`:480` —— **仅打日志**，无任何 mock 短路。
- `api/clients/duomi_client.py` —— 图/视频 mock（与主链路无关）。
- 前端 `web/js/state.js:181` —— `TEST_MODE` 由 URL `?test=1` 决定，独立于后端。

**结论：`task/mock_interceptor.py` 尚不存在；除 duomi 外，主链路 mock 完全未实现。本方案从零搭建。**

### 1.2 任务通道全景（必须全部覆盖）

E2E 链路涉及 **10 条通道**：其中 **8 条需 mock 拦截**（视觉异步/同步、TTS、RunningHub 音频+遮盖、ComfyUI 工具直调、四宫格、多角度、人脸遮盖 pipeline），**2 条无需 mock**（时间轴合成 §5.9、世界导入导出 §5.10——靠上游本地路径/纯本地处理跑真实代码）。各通道由不同入口调度，互不经过同一拦截点：

| # | 通道 | 调度入口 | 外部依赖 | 是否经 `VideoDriverFactory` |
|---|------|----------|----------|------------------------------|
| 1 | 视觉异步 Driver | `task/visual_task._submit_new_task` / `_check_task_status` | 各厂商 API（火山/Seedance/Vidu/Kling…） | 是 |
| 2 | 视觉同步 Driver（13 个实现） | `task/sync_task_executor._execute_sync_task`（子进程池） | 火山/GPT/Gemini 同步 API | 是，但在子进程 |
| 3 | Index TTS 音频 | `task/audio_task._submit_new_task` → `utils/index_tts_util.generate_audio` | TTS 服务 `/tts_url`、`/upload_reference` | 否 |
| 4 | RunningHub 音频 + 人脸遮盖 | `task/runninghub_async_task` / `task/async_task_submission` | RunningHub v2 API + 文件上传 | 否（经 `BaseAsyncDriver`） |
| 5 | ComfyUI 工具直调（Agent 工具） | `script_writer_core/mcp_tool.text_to_image` / `image_edit` | 本机 ComfyUI `/api/text-to-image`、`/api/image-edit` | 否 |
| 6 | 四宫格图 | `task/grid_image_task.process_grid_image_tasks` | 本机 ComfyUI `/api/get-status`、`/api/text-to-image` | 否 |
| 7 | 多角度图 | `task/location_multi_angle_task` | 本机 ComfyUI `/api/image-edit`（**轮询走 DB，不走 get-status**） | 否 |
| 8 | 人脸遮盖 Pipeline（param_prepare） | `task/pipeline_drivers/face_mask_driver` → 通道 4 | RunningHub（产物作为下游视频输入） | 否 |
| 9 | 时间轴合成（**E2E 终点**） | `server.py:8190 export_timeline_draft` | 上游本地路径时仅本地 `ffprobe/ffmpeg`（**无需 mock**） | 否 |
| 10 | 世界导入/导出 | `api/script_writer.py:4563/4599` | 导出=图床上传(保留)；导入=纯本地(**无需 mock**) | 否 |

**此外有 4 类副作用需隔离/可控**：RunningHub 槽位由 mock 短路天然不占用；算力扣费（媒体）、LLM token 计费、CDN/七牛上传在**独立测试环境真实执行（不绕过，见 §6）**，靠测试前重置账户算力与环境隔离保证可控。

---

## 2. 总体架构

```
                         ┌──────────────────────────────────────────┐
                         │   task/mock_interceptor.py  （纯逻辑层）   │
                         │  · is_mock_enabled / mock_task_id 生成     │
                         │  · 按 category 解析 mock URL               │
                         │  · 构造各通道响应结构 / 命中计数            │
                         └───────────────┬──────────────────────────┘
                                         │ 被以下 8 条需拦截通道调用（时间轴/世界导入导出无需 mock）
        ┌────────────┬────────────┬──────┴───────┬────────────┬──────────────┐
        ▼            ▼            ▼              ▼            ▼              ▼
   visual_task  sync_task_exec  audio_task   base_async   mcp_tool/      export_
   (异步)        (同步子进程)    (TTS)        _driver      grid/multi    timeline
                                                       angle           (终点)
                                         │
                         ┌───────────────┴──────────────────────────┐
                         │  副作用策略（不绕过，靠隔离环境）          │
                         │  · 算力：扣费链路真实执行，测试前重置账户    │
                         │  · CDN：保留上传，由测试环境承载             │
                         │  · 槽位：mock 短路天然不 acquire             │
                         └──────────────────────────────────────────┘
```

### 2.1 三条铁律

1. **写库留在各通道调度器内，复用现有成功处理函数**；MockInterceptor 只负责"返回什么"，不直接写 DB。
2. **mock project_id 统一前缀 `mock_task_`**；`async_tasks.external_task_id` 同前缀。所有轮询/重试调度器据此识别并短路。
3. **mock 资源一律本地 `/upload/mock/...` 真实文件**（绝不远程 URL），避免触发外网下载与远程生成 API（CDN 上传在隔离环境中保留，见 §6）。

---

## 3. 核心模块：`task/mock_interceptor.py`（新建）

**仅含纯逻辑，无 DB 写入。** 完整代码如下：

```python
"""
E2E 测试挡板拦截器（纯逻辑层）。
当 test_mode.enabled=True 时，拦截所有外部媒体生成调用，返回预设本地媒体。
本模块只负责"判断与构造响应"，写库由各通道调度器复用现有成功处理函数完成。
"""
import logging
import threading
import uuid
from typing import Any, Dict, Optional

from config.config_util import get_dynamic_config_value
from config.unified_config import UnifiedConfigRegistry, TaskCategory

logger = logging.getLogger(__name__)

MOCK_PROJECT_PREFIX = "mock_task_"

# ============ 进程内命中计数（可观测性） ============
_counters_lock = threading.Lock()
_counters: Dict[str, int] = {}


def _bump(channel: str) -> None:
    with _counters_lock:
        _counters[channel] = _counters.get(channel, 0) + 1


def mock_hit_summary() -> Dict[str, int]:
    with _counters_lock:
        return dict(_counters)


# ============ 开关与 ID ============
def is_mock_enabled() -> bool:
    """挡板总开关。注意：受 _DYNAMIC_CACHE_TTL=30s 缓存影响，跨进程有传播延迟（见 §7）。"""
    return bool(get_dynamic_config_value("test_mode", "enabled", default=False))


def generate_mock_project_id() -> str:
    return f"{MOCK_PROJECT_PREFIX}{uuid.uuid4().hex[:16]}"


def is_mock_id(task_id: Optional[str]) -> bool:
    return isinstance(task_id, str) and task_id.startswith(MOCK_PROJECT_PREFIX)


# ============ 按 category 解析 mock URL ============
# TaskCategory 是字符串常量类（非 Enum），值如 'text_to_image'/'image_edit'/'image_to_video'/
# 'text_to_video'/'digital_human'/'audio'。见 config/unified_config.py:29-49。
def _img(key: str) -> Optional[str]:
    return get_dynamic_config_value("test_mode", "mock_images", key, default=None)


def _vid(key: str) -> Optional[str]:
    return get_dynamic_config_value("test_mode", "mock_videos", key, default=None)


def _aud(key: str) -> Optional[str]:
    return get_dynamic_config_value("test_mode", "mock_audio", key, default=None)


def resolve_mock_url_for_visual(ai_tool_type: int) -> Optional[str]:
    """
    根据 ai_tool.type 解析视觉任务的 mock URL。
    同时考虑主分类 category 与附加分类 categories（一个图编模型可能也支持文生图）。
    """
    try:
        cfg = UnifiedConfigRegistry.get_by_id(ai_tool_type)
        if not cfg:
            return None
        cats = [cfg.category] + list(cfg.categories or [])

        def pick(*candidates, getter):
            for c in candidates:
                if c in cats:
                    return getter(c)
            return None

        # 视频（数字人归视频桶）
        url = pick(TaskCategory.IMAGE_TO_VIDEO, TaskCategory.TEXT_TO_VIDEO,
                   TaskCategory.DIGITAL_HUMAN, getter=_vid)
        if url:
            return url
        # 图片：优先按主分类(cfg.category)精确映射，再用 categories 兜底。
        # 否则图编模型(category=IMAGE_EDIT, categories=[TEXT_TO_IMAGE])会被误判为文生图。
        primary = cfg.category
        if primary == TaskCategory.IMAGE_EDIT:
            url = _img("image_edit")
        elif primary == TaskCategory.TEXT_TO_IMAGE:
            url = _img("text_to_image")
        else:
            url = pick(TaskCategory.TEXT_TO_IMAGE, TaskCategory.IMAGE_EDIT, getter=_img)
        if url:
            return url
        # 兜底
        return _vid("image_to_video") or _img("text_to_image")
    except Exception as e:
        logger.warning(f"[MOCK] resolve_mock_url_for_visual({ai_tool_type}) failed: {e}")
        return None


def mock_image(subkey: str = "text_to_image") -> Optional[str]:
    return _img(subkey)


def mock_video(subkey: str = "image_to_video") -> Optional[str]:
    return _vid(subkey)


def mock_audio(subkey: str = "tts") -> Optional[str]:
    return _aud(subkey)


# ============ 各通道响应结构构造 ============
def visual_async_submit_result(ai_tool_type: int) -> Dict[str, Any]:
    """视觉异步：submit 返回 project_id，check_status 稍后返回 SUCCESS+url。"""
    _bump("visual_async_submit")
    pid = generate_mock_project_id()
    logger.info(f"[MOCK] channel=visual_async_submit type={ai_tool_type} project_id={pid}")
    return {"success": True, "project_id": pid}


def visual_async_status_result(ai_tool_type: int) -> Dict[str, Any]:
    """视觉异步：check_status 直接返回 SUCCESS。"""
    url = resolve_mock_url_for_visual(ai_tool_type)
    _bump("visual_async_poll")
    logger.info(f"[MOCK] channel=visual_async_poll type={ai_tool_type} url={url}")
    return {"status": "SUCCESS", "result_url": url}


def visual_sync_result(ai_tool_type: int) -> Dict[str, Any]:
    """视觉同步：返回 sync_mode 结果。"""
    url = resolve_mock_url_for_visual(ai_tool_type)
    _bump("visual_sync_submit")
    logger.info(f"[MOCK] channel=visual_sync_submit type={ai_tool_type} url={url}")
    return {"success": True, "sync_mode": True, "result_url": url}


def comfyui_submit_result(ai_tool_type: int) -> Dict[str, Any]:
    """ComfyUI 工具直调 submit：兼容 {project_ids, status} 结构。"""
    _bump("comfyui_submit")
    pid = generate_mock_project_id()
    logger.info(f"[MOCK] channel=comfyui_submit type={ai_tool_type} project_id={pid}")
    return {"status": "submitted", "project_ids": [pid]}


def comfyui_status_success(file_url: str) -> Dict[str, Any]:
    """ComfyUI 轮询成功：返回 tasks[0] 元素结构（含 results[0].file_url）。
    注意：grid_image_task._handle_task_success 接收的是 tasks[0] 元素本身，不是外层 envelope。"""
    _bump("comfyui_poll")
    logger.info(f"[MOCK] channel=comfyui_poll file_url={file_url}")
    return {
        "status": "SUCCESS",
        "results": [{"file_url": file_url, "result_url": file_url,
                     "cdn_status": "skip", "task_cost_time": 0}],
    }


def async_submit_result(impl_label: str) -> Dict[str, Any]:
    """RunningHub 异步（音频/人脸遮盖）：submit 返回 mock project_id。"""
    _bump(f"async_submit:{impl_label}")
    pid = generate_mock_project_id()
    logger.info(f"[MOCK] channel=async_submit impl={impl_label} project_id={pid}")
    return {"success": True, "project_id": pid}
```

---

## 4. 配置项定义

### 4.1 扩展 `config/default_configs.py`

在现有 `test_mode` 段（约 `:148-183`）后追加（保留原 5 项）：

```python
    # ---- test_mode 行为开关 ----
    {'key': 'test_mode.inject_failure_rate',     'value_type': 'int',    'description': '失败注入概率(0-100)，0=不注入', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.inject_failure_scenario', 'value_type': 'string', 'description': '失败注入场景，如 submit/poll/timeout', 'editable': True, 'is_sensitive': False},

    # ---- mock_images ----
    {'key': 'test_mode.mock_images.comfyui_text_to_image', 'value_type': 'string', 'description': 'ComfyUI 文生图预设URL', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_images.comfyui_image_edit',    'value_type': 'string', 'description': 'ComfyUI 图片编辑预设URL', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_images.grid_image',            'value_type': 'string', 'description': '四宫格整图预设URL(2x2)', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_images.grid_image_split_1',    'value_type': 'string', 'description': '四宫格拆分图1', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_images.grid_image_split_2',    'value_type': 'string', 'description': '四宫格拆分图2', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_images.grid_image_split_3',    'value_type': 'string', 'description': '四宫格拆分图3', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_images.grid_image_split_4',    'value_type': 'string', 'description': '四宫格拆分图4', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_images.multi_angle_front',     'value_type': 'string', 'description': '多角度-正面图', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_images.multi_angle_side',      'value_type': 'string', 'description': '多角度-侧面图', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_images.multi_angle_back',      'value_type': 'string', 'description': '多角度-背面图', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_images.face_mask_input',       'value_type': 'string', 'description': '人脸遮盖结果(下游视频输入)预设URL', 'editable': True, 'is_sensitive': False},

    # ---- mock_videos ----
    {'key': 'test_mode.mock_videos.digital_human', 'value_type': 'string', 'description': '数字人预设视频URL', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_videos.face_mask',     'value_type': 'string', 'description': '人脸遮盖预设视频URL(必须本地真实mp4)', 'editable': True, 'is_sensitive': False},

    # ---- mock_audio ----
    {'key': 'test_mode.mock_audio.tts',            'value_type': 'string', 'description': 'TTS 预设音频URL', 'editable': True, 'is_sensitive': False},
    {'key': 'test_mode.mock_audio.character_audio','value_type': 'string', 'description': 'RunningHub 角色音频预设URL', 'editable': True, 'is_sensitive': False},
```

> 说明：`get_dynamic_config_value` 支持 `("test_mode", "mock_images", "text_to_image")` 多级 key 拼接成 `test_mode.mock_images.text_to_image`（见 `config_util.py:294`）。原 5 项（`test_mode.mock_videos.image_to_video/text_to_video`、`mock_images.image_edit/text_to_image`）保留不动，继续被 `resolve_mock_url_for_visual` 使用。

### 4.2 预设资源约定（必须本地落盘）

| key | 文件 | 要求 |
|-----|------|------|
| `mock_images.text_to_image` | `upload/mock/e2e_text_to_image.png` | 9:16，≤1MB |
| `mock_images.image_edit` | `upload/mock/e2e_image_edit.png` | 同上 |
| `mock_images.comfyui_text_to_image` | `upload/mock/e2e_comfyui_tti.png` | 同上 |
| `mock_images.comfyui_image_edit` | `upload/mock/e2e_comfyui_ie.png` | 同上 |
| `mock_images.grid_image` | `upload/mock/e2e_grid_2x2.png` | **真实 2x2 拼图**，1024×1024 |
| `mock_images.grid_image_split_1..4` | `upload/mock/e2e_grid_{1..4}.png` | 4 张子图（若走"直接给拆分结果"分支） |
| `mock_images.multi_angle_front/side/back` | `upload/mock/e2e_ma_*.png` | 场景图 |
| `mock_videos.image_to_video` | `upload/mock/e2e_i2v.mp4` | 9:16，≤5MB，≤5s，**真实可播** |
| `mock_videos.text_to_video` | `upload/mock/e2e_t2v.mp4` | 同上 |
| `mock_videos.digital_human` | `upload/mock/e2e_dh.mp4` | 同上 |
| `mock_videos.face_mask` | `upload/mock/e2e_face_mask.mp4` | **真实 mp4**（下游 `os.path.exists` 校验，见 §7.8） |
| `mock_audio.tts` | `upload/mock/e2e_tts.mp3` | ≤10s |
| `mock_audio.character_audio` | `upload/mock/e2e_char.mp3` | ≤10s |
| （测试资产）世界导出包 | `upload/mock/world_export_sample.zip` | 由 §14 播种世界导出生成，结构见 §5.10，供导入测试用 |

**资源准备脚本**：见 §12。所有 mock 文件放 `upload/mock/`（该目录已由 `server.py:4832` 挂为 StaticFiles，`/upload/mock/x.png` 可直接 HTTP 访问）。

---

## 5. 逐通道实施

### 5.1 通道 1：视觉异步 Driver

**文件**：`task/visual_task.py`

**关键：mock 短路必须插在 `_submit_new_task` 最开头**，在以下三者**之前**，否则会触发 §10/§11 的问题：
- `param_prepare` 检查（`:235-242`）—— 否则带 face_mask 的任务类型死锁
- `implementation` 记录（`:256-275`）
- `sync_mode` 分流（`:282-289`）—— 否则同步实现进了子进程就拦不住

**改动 A：`_submit_new_task` 开头（紧跟 `ai_tool_type = ai_tool.type` 之后，约 `:227`）**：

```python
    ai_tool_type = ai_tool.type
    task_id = ai_tool.id

    # ===== E2E Mock 短路（必须在 param_prepare / implementation / sync 分流之前）=====
    from task.mock_interceptor import is_mock_enabled, visual_async_submit_result
    if is_mock_enabled():
        from task.mock_interceptor import visual_async_status_result  # 仅示意
        mock = visual_async_submit_result(ai_tool_type)
        project_id = mock["project_id"]
        AIToolsModel.update(task_id, project_id=project_id, status=AI_TOOL_STATUS_PROCESSING)
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_PROCESSING)
        logger.info(f"[MOCK] visual async submit short-circuit task={task_id} pid={project_id}")
        return True
    # =====================================================================

    if _is_test_mode_enabled():   # 原有日志，可保留
        logger.info(f"[TEST MODE] [DRIVER] Submitting task {task_id} (type: {ai_tool_type})")
```

**改动 B：`_check_task_status`（`:445` 起）**，在拿到 `project_id` 之后、创建 driver 之前（约 `:483` `try:` 之后第一行）：

```python
    from task.mock_interceptor import is_mock_enabled, is_mock_id, visual_async_status_result
    if is_mock_enabled() and is_mock_id(project_id):
        mock = visual_async_status_result(ai_tool_type)
        result_url = mock.get("result_url")
        if result_url:
            return await _handle_task_success(project_id, task_id, result_url)
        # 无 URL 时按失败处理
        return _handle_task_failure(task_id, ai_tool_type, "mock 未配置 result_url", ai_tool.user_id, project_id=project_id)
```

**改动 C：给异步成功路径补 `is_local_path` 短路**（**必须**，否则 mock 本地路径进 `download_and_cache` 必失败）。

`_handle_task_success`（`:659` 起），在 `download_and_cache` 调用前（`:682` 之前）：

```python
        # mock 本地路径短路（与 sync 分支 :366 保持一致）
        is_local_path = media_url and media_url.startswith("/upload/")
        if is_local_path:
            final_url = media_url
            logger.info(f"[MOCK] local path, skip download_and_cache: {media_url}")
        else:
            cached_url = await download_and_cache(media_url, task_id, media_type)
            final_url = cached_url if cached_url else media_url
```

> **重要事实**：`utils/media_cache.py:192-253` 的 `download_and_cache` **不识别** `/upload/` 本地路径（唯一短路是 `if not self.enabled`），对相对路径会 `aiohttp.get()` 抛 `InvalidURL`。所以调用方必须自己做 `is_local_path` 判断。sync 分支（`sync_task_executor.py:133`、`visual_task.py:366`）已有此判断，异步分支此前缺失。

---

### 5.2 通道 2：视觉同步 Driver（SyncTaskExecutor 子进程，13 个实现）

**文件**：`task/sync_task_executor.py`

**13 个 `sync_mode=True` 实现**（`config/unified_config.py` 中）：`seedream5_volcengine_v1`、`seedream5_volcengine_oversea_v1`、`gpt_image_common_site0..5_v1`（6）、`gemini_image_preview_site0..4_v1`（5）。`_execute_sync_task` 在 `ProcessPoolExecutor` 子进程内执行，**不继承主进程状态**，但 `test_mode.enabled` 来自 DB，子进程首次读取即可命中（注意 §9 缓存延迟）。

**改动**：`_execute_sync_task`（`:38` 起），在 `AIToolsModel.update(...PROCESSING)` 之后、创建 driver 之前（约 `:81` `# 调用驱动提交任务` 注释处）插入：

```python
        # ===== E2E Mock 短路（同步子进程）=====
        from task.mock_interceptor import is_mock_enabled, visual_sync_result
        if is_mock_enabled():
            mock = visual_sync_result(ai_tool_type)
            url = mock.get("result_url")
            if url:
                logger.info(f"[MOCK] visual sync short-circuit task={task_id} url={url}")
                return SyncTaskResult(
                    task_id=task_id, ai_tool_type=ai_tool_type,
                    success=True, result_url=url,
                )
        # =====================================
```

> 返回 `SyncTaskResult(success=True, result_url=本地路径)` 后，`SyncTaskExecutor._handle_task_result`（`:344`）会走 `update_with_cdn_sync`（CDN 上传在隔离环境保留，见 §6）。`result_url` 以 `/upload/` 开头时，`:133` 的 `is_local_path` 判断会跳过 `download_and_cache`。

---

### 5.3 通道 3：Index TTS 音频

**文件**：`task/audio_task.py`，函数 `_submit_new_task`（`:45`）。

**拦截点必须在 `generate_audio` 调用（`:116`）之前**，直接写 mock result_url（**不要**放 `utils/index_tts_util.py`——因为 `:136-137` 的 `result_url = f"{upload_url}{audio_filename}"` 会覆盖任何返回值，导致 URL 指向不存在的文件）。

**改动**：`_submit_new_task` 开头 `task_id = ai_audio.id` 之后（约 `:56`）：

```python
    task_id = ai_audio.id

    # ===== E2E Mock 短路 =====
    from task.mock_interceptor import is_mock_enabled, mock_audio
    if is_mock_enabled():
        url = mock_audio("tts")
        if url:
            AIAudioModel.update(task_id, status=AI_AUDIO_STATUS_COMPLETED,
                                result_url=url, message="[MOCK] 音频生成成功")
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_COMPLETED)
            logger.info(f"[MOCK] audio tts short-circuit task={task_id} url={url}")
            return True
    # =========================
```

> 音频通道**当前不扣费**（`audio_task.py` 全文无 `perseids/computing_power` 调用，`/api/audio-generate` 也只建记录）。因此音频侧无需任何扣费处理。`generate_audio` 内部挡板可作为兜底但非主路径。

---

### 5.4 通道 4：RunningHub 音频 + 人脸遮盖（统一拦截点）

**文件**：`task/async_drivers/base_async_driver.py`，方法 `submit_with_slot_management`（`:60`）。

audio 与 face_mask 两条 RunningHub 异步链路都汇聚到此方法（`face_mask_driver.py:54`、`runninghub_audio_driver.py:60`），是**唯一统一拦截点**。

**改动**：`submit_with_slot_management` 中，在 `AsyncTasksModel.create`（`:84`）**之后**、槽位获取 `if config.need_runninghub_slot`（`:91`）**之前**插入：

```python
        # 1. 创建 async_task 记录
        async_task_id = AsyncTasksModel.create(
            implementation=self.impl_id, user_id=user_id, params=params
        )

        # ===== E2E Mock 短路：跳过槽位与文件上传，直接写 mock external_task_id =====
        from task.mock_interceptor import is_mock_enabled, generate_mock_project_id
        if is_mock_enabled():
            mock_pid = generate_mock_project_id()
            AsyncTasksModel.update_external_task_id(async_task_id, mock_pid)
            logger.info(f"[MOCK] async submit short-circuit impl={self.impl_id} "
                        f"async_task_id={async_task_id} pid={mock_pid}")
            return {"success": True, "project_id": mock_pid, "async_task_id": async_task_id}
        # =========================================================================
```

> 本短路在 `try_acquire_slot`（`:92`）之前 return，故 mock 任务天然不占用 RunningHub 槽位，无需额外处理。

**主路径只需处理 (b) 轮询调度器**。先澄清两者差异（已核实 `model/async_tasks.py`）：

- **(a) `task/async_task_submission.py::process_pending_async_task_submissions`**（`:152`）用 `get_ready_to_retry_tasks()`（`async_tasks.py:361`），过滤条件为 `status=QUEUED AND next_retry_at IS NOT NULL AND next_retry_at <= NOW()`。而 BaseAsyncDriver mock 分支用 `AsyncTasksModel.create()`（`:136`）建记录时**不设 `next_retry_at`**（默认 NULL），且 mock 分支在槽位逻辑之前 return、不会触发 `schedule_retry`。**因此普通 mock async task 根本不会进入此流程**，主路径无需在此拦截。仅在 `_submit_task_with_retry`（`:60`）内做**防御**：若 `task.external_task_id` 是 mock_id（理论上不出现），跳过真实 submit 直接标记完成。
- **(b) `task/runninghub_async_task.py::process_runninghub_async_tasks`**（`:243`）用 `get_pending_tasks()`（`:208`，取 QUEUED/PROCESSING）**会**取到 mock task（status=QUEUED），是 mock 完成的**唯一主路径**。在 `if not task.external_task_id: continue`（`:275`）之后增加短路：

```python
                        # mock 任务短路：跳过 success_handler（其内部 download 不识别本地路径，见 §5.8）
                        from task.mock_interceptor import is_mock_id, mock_audio, mock_video
                        if is_mock_id(task.external_task_id):
                            params = task.get_params_dict()
                            if impl_id == AsyncTaskImplementationId.RUNNINGHUB_AUDIO:
                                result_url = mock_audio("character_audio") or "/upload/mock/e2e_char.mp3"
                                # 替代 _handle_audio_task_success 的副作用：直接写角色 default_voice
                                character_id = params.get('character_id')
                                if character_id:
                                    try:
                                        from model.character import CharacterModel
                                        CharacterModel.update(character_id, default_voice=result_url)
                                    except Exception as e:
                                        logger.warning(f"[MOCK] set default_voice failed: {e}")
                                async_result_url = result_url
                            else:  # FACE_MASK：直接写 completed，跳过 overlay（见 §5.8）
                                async_result_url = mock_video("face_mask") or "/upload/mock/e2e_face_mask.mp4"
                            AsyncTasksModel.update_status(record_id=task.id,
                                status=AsyncTaskStatus.COMPLETED, result_url=async_result_url)
                            RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_ASYNC)
                            logger.info(f"[MOCK] async poll short-circuit task={task.id} url={async_result_url}")
                            continue
```

> **为何跳过 `success_handler`**：`_handle_face_mask_task_success`（`:132`）与 `_handle_audio_task_success`（`:51`）内部都调下载函数（`download_and_cache` `:168`、`download_and_save_character_voice` `:74`），这些函数**不识别** `/upload/mock/` 本地路径会失败。故 mock 分支直接写 `async_tasks.result_url` 并自行补关键副作用（音频的 `default_voice`）。face_mask 的 `result_url` 经 `pipeline_processor.apply_results`（`:226`）写回 `ai_tool.video_path` 供下游使用——详见 §5.8。

---

### 5.5 通道 5：ComfyUI 工具直调（Agent 工具）

**文件**：`script_writer_core/mcp_tool.py`

两个方法直接 `httpx.post` ComfyUI，**完全绕开 driver**：
- `image_edit`：`:580` 构造 `api_url=/api/image-edit`，`:596` `httpx.post`
- `text_to_image`：`:3684` 构造 `api_url=/api/text-to-image`，`:3689` `httpx.post`

二者成功响应均含 `project_ids`（服务端 `server.py:1401/1524`）。

**改动**：在两个方法的 `try: response = httpx.post(...)` **之前**插入短路。以 `text_to_image` 为例（`image_edit` 同理，用对应 mock key）：

**关键：只替换"获取 project_ids"那一步，保留后续创建 `grid_image_tasks` 记录的逻辑。** 否则 §5.6 轮询扫描 `grid_image_tasks` 表时无记录，item 参考图永远不会更新，Agent 工具调用无法完成。

原结构是 `response = httpx.post(...)` → `result_data = response.json()` → `project_ids = result_data.get('project_ids')` → 创建 `grid_image_tasks` → return。mock 改法是把 HTTP 调用包进 `if/else`，**其余代码原样不动**：

```python
        # ===== E2E Mock 短路：仅替换 project_ids 的获取，保留后续创建逻辑 =====
        from task.mock_interceptor import is_mock_enabled, generate_mock_project_id
        if is_mock_enabled():
            project_id = generate_mock_project_id()
            result_data = {'project_ids': [project_id]}
            logger.info(f"[MOCK] mcp_tool text_to_image short-circuit pid={project_id}")
        else:
            response = httpx.post(api_url, data=request_data, timeout=30, verify=False)
            response.raise_for_status()
            result_data = response.json()
        # =================================================================
        project_ids = result_data.get('project_ids', [])   # 原有代码，保持不变
        if not project_ids: ...                            # 原有错误分支
        # 后续 task_manager.create_image_task / GridImageTasksModel.create 原样保留
```

> `image_edit` 方法同理：mock 分支用 `generate_mock_project_id()` 构造 `project_ids`，保留其原有的 `GridImageTasksModel.create(item_type=0)` 调用。

> **死代码澄清**：`script_writer_core/cron_task_manager.py:322` 的 `requests.get(/api/get-status)` 是**死代码**（`:258` 注释：轮询已迁移到 scheduler 进程）。**不要**在它上面加拦截。真实轮询在 `grid_image_task.py`（见 5.6）。

---

### 5.6 通道 6：四宫格图

**文件**：`task/grid_image_task.py`

两处需拦截：
1. `process_grid_image_tasks`（`:372`）：轮询 ComfyUI `GET /api/get-status/{project_id}`（`:417`）。
2. `_resubmit_image_request`（`:131`）：失败重试时 `httpx.post /api/text-to-image`（`:159`）。

**改动 A：`process_grid_image_tasks`，在 `requests.get(status_url)`（`:417`）之前**，识别 mock project_id 直接构造成功数据：

```python
                # ===== E2E Mock 短路 =====
                from task.mock_interceptor import is_mock_enabled, is_mock_id, comfyui_status_success, _img
                if is_mock_enabled() and is_mock_id(task.project_id):
                    file_url = (_img("grid_image") if task.item_type in (4, 5, 6)
                                else _img("comfyui_text_to_image")) or "/upload/mock/e2e_grid_2x2.png"
                    comfyui_task = comfyui_status_success(file_url)
                    _handle_task_success(task, comfyui_task)   # 复用现有成功处理
                    continue
                # =========================

                status_url = f"{task.comfyui_base_url.rstrip('/')}/api/get-status/{task.project_id}"
                response = requests.get(...)
```

> `_handle_task_success`（`:177`）读取 `comfyui_task_data['results'][0]['file_url']`（`:190`），调用处传入的是 `tasks[0]` 元素。`comfyui_status_success` 已构造该结构。
>
> **四宫格特殊性**：item_type 4/5/6 会触发 `ImageGridSplitter.split_2x2_grid`（`:238`）拆分，要求 `enable_image_download=True` 且 `local_file_path` 是**真实 2x2 图**。E2E fixture 须：① 准备真实 2x2 的 `e2e_grid_2x2.png`；② 或直接提供 4 张拆分图并通过 item 更新写回（绕过 split）。

**改动 B：`_resubmit_image_request`（`:131`）开头**：

```python
    from task.mock_interceptor import is_mock_enabled, generate_mock_project_id
    if is_mock_enabled():
        return generate_mock_project_id()
```

---

### 5.7 通道 7：多角度图（**走 DB 轮询，非 get-status**）

**文件**：`task/location_multi_angle_task.py`

**重要差异**：本任务**不调** `/api/get-status`。完成判定走数据库 `AIToolsModel.get_by_id(task.ai_tool_task_id)`（`:241`），读 `ai_tool.status == COMPLETED` 与 `ai_tool.result_url`（`:244-246`）。提交走 `POST /api/image-edit`（`:382`）。远程图下载在 `:70` `requests.get(file_url)`。

**改动 A：提交函数（`process_location_multi_angle_task` 内 `:381` `requests.post` 之前）**：

```python
            from task.mock_interceptor import is_mock_enabled
            if is_mock_enabled():
                # mock 模式：每个调度 tick 推进一个角度（与真实"一次一个角度"状态机一致）。
                # _apply_mock_angle 内部递增 current_angle_index，最后一个角度置 COMPLETED。
                _apply_mock_angle(task_key, comfyui_base_url)
                return {'success': True, 'submitted': True, 'project_id': 'mock_task_multi_angle'}
            response = requests.post(...)
```

**改动 B：新增 mock 完成辅助 `_apply_mock_angle`**——复用现有状态机字段（`current_angle_index` / `generated_images` / `angles` / status），每个 tick 处理当前角度，最后一个角度置 `COMPLETED`：

```python
def _apply_mock_angle(task_key: str, comfyui_base_url: str):
    """mock 模式推进一个角度：选图→落盘→写 staging→递增 index，末角度置 COMPLETED。"""
    from task.mock_interceptor import _img
    task = LocationMultiAngleTasksModel.get_by_task_key(task_key)   # 取最新状态
    angles = task.get_angles_list()
    idx = task.current_angle_index or 0
    generated = task.get_generated_images_list() or []
    if idx >= len(angles):
        LocationMultiAngleTasksModel.update_status(
            task_key, LocationMultiAngleTaskStatus.COMPLETED, generated_images=generated)
        return

    angle = angles[idx].get('angle', 0)
    angle_key = angles[idx].get('angleKey', 'unknown')
    label = angles[idx].get('label', f'{angle}°')

    # 角度→mock 图映射（front≈0°，back≈180°，其余 side）
    if angle >= 337.5 or angle < 22.5:
        file_url = _img('multi_angle_front') or '/upload/mock/e2e_ma_front.png'
    elif 157.5 <= angle < 202.5:
        file_url = _img('multi_angle_back') or '/upload/mock/e2e_ma_back.png'
    else:
        file_url = _img('multi_angle_side') or '/upload/mock/e2e_ma_side.png'

    # 复用现有下载+存储（改动 C 已让 /upload/mock/ 走本地拷贝，不外网）
    local_image_url, local_file_path = _download_and_store_image(file_url, comfyui_base_url)

    new_image = {'angle': angle_key, 'label': label,
                 'url': local_image_url, 'local_file_path': local_file_path}
    generated.append(new_image)
    _update_reference_images_to_staging(task, [new_image])          # 写入场景 JSON reference_images

    next_idx = idx + 1
    if next_idx >= len(angles):
        LocationMultiAngleTasksModel.update_status(
            task_key, LocationMultiAngleTaskStatus.COMPLETED, generated_images=generated)
    else:
        LocationMultiAngleTasksModel.update_status(
            task_key, LocationMultiAngleTaskStatus.PROCESSING,
            current_angle_index=next_idx, generated_images=generated, ai_tool_task_id=0)
```

> 每个调度 tick `process_pending_location_multi_angle_tasks` 调一次 `process_location_multi_angle_task` → 命中 mock 分支 → `_apply_mock_angle` 推进一个角度；多次 tick 后走完所有角度置 `COMPLETED`，与真实"一次一个角度"语义一致。

**改动 C：`_download_and_store_image`（`:70`）`requests.get(file_url)` 之前**加本地路径短路：

```python
        from task.mock_interceptor import is_mock_enabled
        if is_mock_enabled() and file_url.startswith("/upload/mock/"):
            # 本地 mock 文件，直接复制，不下载
            ...
```

---

### 5.8 通道 8：人脸遮盖 Pipeline（param_prepare 产物）

**链路**：`pipeline_drivers/face_mask_driver.py` → `BaseAsyncDriver.submit_with_slot_management`（已在 5.4 拦截）→ `runninghub_async_task.process_runninghub_async_tasks`（已在 5.4(b) 拦截）→ `_handle_face_mask_task_success`（`runninghub_async_task.py:132`）。

**关键约束（critical）**：
- face_mask 的 `result_url` 经 `pipeline_processor.apply_results`（`:226`）写回 `ai_tool.video_path`，**作为下游视频生成的输入**。
- 下游 `seedance_volcengine_v1_driver.py:92`、`happy_horse_dashscope_v1_driver.py:291`、`face_mask_util.py:70` 均做 `os.path.exists` 校验，文件不存在则回退/失败。
- `POST_PROCESSING_REQUIRED`（`runninghub_async_task.py:238`）要求 `_handle_face_mask_task_success` 返回非 None，否则判 FAILED。

**因此**：`test_mode.mock_videos.face_mask` 必须指向**本地真实存在的 mp4**（`/upload/mock/e2e_face_mask.mp4` 预置）。

**推荐策略：跳过 overlay，直接写 completed（§5.4(b) 已采用）**

原因：`_handle_face_mask_task_success`（`runninghub_async_task.py:132`）内部对 `result_url` 调 `download_and_cache()`（`:168`）下载遮罩视频，而 `download_and_cache` **不识别** `/upload/mock/` 本地路径（aiohttp 失败返回 None）→ handler 返回 None → `POST_PROCESSING_REQUIRED`（`:238`）判 FAILED。故**不要**在 mock 分支调用该 handler。

正确做法（见 §5.4(b)）：mock 轮询短路时直接 `update_status(COMPLETED, result_url="/upload/mock/e2e_face_mask.mp4")`。该 `result_url` 经 `pipeline_processor._process_single_step`（`:347`）写入 `step.result_url`，再经 `apply_results`（`:226`）写回 `ai_tool.video_path`，供下游视频生成使用（格式与生产一致：生产 handler 返回相对路径后被包成 `/{path}`，mock 同样用 `/upload/mock/...`）。

**硬性要求**：`/upload/mock/e2e_face_mask.mp4` 必须是**本地真实存在的可播 mp4**——下游 `seedance_volcengine_v1_driver.py:92`、`happy_horse_dashscope_v1_driver.py:291` 做 `os.path.exists` 校验，不存在则回退/失败。

**备选（不推荐）**：若 E2E 必须验证 overlay 合成本身，则需先给 `_handle_face_mask_task_success` 的 `download_and_cache` 调用补 `/upload/` 本地短路（同 §5.1 改动 C），且 mock mp4 需与原视频尺寸/编码兼容能被 `overlay_face_mask` 处理。工作量大，建议用单独的集成测试覆盖 overlay，E2E 主链路用上面的跳过策略。

---

### 5.9 通道 9：时间轴合成（**E2E 终点**）—— 无需 mock

**文件**：`server.py:8190 export_timeline_draft`

**结论：本通道不做任何 mock 拦截。** 原因：该接口对每个 clip 先调 `_get_local_upload_file(video_url, origin)`（`:8264`），只要 `video_url` 以 `/upload/` 开头且文件存在（`server.py:875`），就走 `shutil.copy2` 本地拷贝分支，**天然跳过**远程 `httpx` 下载与 `CDNUtil.refresh_cdn_signed_url`（外网），只剩本地 `ffprobe/ffmpeg`（本地二进制，非外网调用）。

由于上游所有通道（§5.1–5.7）产出的 `result_url` 都是 `/upload/mock/...` 本地路径，传到时间轴的 clip url 自然满足本地条件 → 整个导出链路用**真实代码**跑在本地 mock 素材上，无需任何改动。

**收益**：E2E 终点覆盖了真实的草稿生成逻辑（jianying 库、`DraftGenerator`、多轨拼接、打 zip），是这套方案里覆盖真实代码最多的环节，应保留而非绕过。

**环境前提**（非 mock 关注点，仅记录）：
- 测试环境需安装 `ffmpeg/ffprobe`（`jianying/src/media_utils.py:50` 调用）。
- `/upload/mock/` 下的视频/音频样本必须真实可播（`ffprobe` 能读出时长/轨道），否则 `probe_safe` 失败导致导出报错。
- 无需关闭 `auto_upload_to_cdn`：导出阶段只读本地素材，不涉及 CDN 上传。

---

### 5.10 通道 10：世界导入 / 导出（真实代码，无需 mock）

**接口**：
- 导出 `GET /api/export-world`（`api/script_writer.py:4563`）→ `file_manager.export_world`（`script_writer_core/file_manager.py:1226`）：把世界目录（`characters/locations/props/scripts/worlds` 的 JSON + `images/` + `audios/`）打成 zip，经 `storage.upload_file` 上传图床，返回 `download_url`。
- 导入 `POST /api/import-world`（`api/script_writer.py:4599`）→ `file_manager.import_world`（`:1376`）：接收 zip，读 `metadata.json`/`image_mapping.json`/`audio_mapping.json`，还原图片到 `upload/{type}/pic/`、音频到角色 voice 目录、JSON 到世界目录。

**结论：本通道不做任何 mock 拦截，两端都用真实代码。**
- **导出**：唯一外部依赖是 `storage.upload_file`（图床上传）。按 §6.2 决策图床/CDN 上传保留真实执行，上传落到测试环境 bucket 即可，**无需 mock**。测试环境需配置好 file_storage（与生产隔离的 bucket）。
- **导入**：**零外部依赖**——纯本地 zip 解压 + 文件复制 + JSON 写入。**无需 mock**，只需提供一份合法的测试 zip 资产。

**测试资产：预置世界导出 zip**

E2E 导入测试需要一份合法的 `world_export_sample.zip`，结构须与 `export_world` 产出一致：

```
world_export_sample.zip
├── metadata.json              # {export_version:"1.0", world_id, user_id, image_count, audio_count, subdirs:[...]}
├── image_mapping.json         # {filename: "/upload/{type}/pic/{filename}"}   （有图片时）
├── audio_mapping.json         # {filename: "/upload/character/voice/{filename}"} （有音频时）
├── characters/<name>.json     # 角色 JSON（reference_image 用 images/<file> 相对路径）
├── locations/<name>.json
├── props/<name>.json
├── scripts/<name>.json
├── worlds/<name>.json
├── images/<file>.png          # 与 image_mapping 对应的真实图片（可复用 §4.2 的 mock 图）
└── audios/<file>.mp3          # 与 audio_mapping 对应（可复用 mock 音频）
```

**生成方式（二选一，推荐 1）**：
1. 先按 §14 幂等播种一个已知世界（含若干角色/场景/道具 + mock 图片），调一次真实 `GET /api/export-world` 得到 zip，固化为测试资产 `upload/mock/world_export_sample.zip`（或放 `auto_test/samples/`）。格式天然与代码一致，最稳。
2. 手工按上面结构打包（适合最小用例）。

> 导入测试建议指向**专用测试 world_id**，避免覆盖其它测试数据：`import_world` 会覆盖目标世界目录下的同名 JSON；图片在 `dest_file.exists()` 时跳过（天然幂等）。

**E2E 用例要点**：
- 导出：导出已播种世界 → 拿 `download_url` → 下载 zip → 校验含 `metadata.json` 且 `image_count` 与播种一致。
- 导入：上传 `world_export_sample.zip` 到 `import-world` → 校验返回的 `scripts/characters/locations/props/images` 计数 → 校验目标世界目录下 JSON 与图片落盘。

---

## 6. 副作用处理策略（不绕过，靠隔离环境）

**决策（按用户要求）**：算力扣减与 CDN 上传**均不绕过**——它们是必须覆盖的重要链路，绕过会导致大量测试不完整。E2E 在**独立隔离环境**运行，副作用影响可控：

| 副作用 | 策略 | 说明 |
|--------|------|------|
| 媒体算力扣费/退款 | **保留真实执行** | `server.py:3487/3725` 的 `deduct`、`visual_task.py:190/837` 的 `increase` 正常跑，覆盖计费链路 |
| LLM token 计费 | **保留真实执行** | `token_task.py:117 process_token_logs` 正常扣减，覆盖 Agent 计费 |
| 测试账号算力 | **测试前重置** | 每次运行前把测试账户算力重置到固定高值（见 §12/§13），保证不被扣穿 |
| CDN/七牛上传 | **保留** | `auto_upload_to_cdn` 不动；上传由测试环境 CDN bucket 承载，不碰生产 |
| RunningHub 槽位 | **天然不占** | §5.4 mock 短路在 `try_acquire_slot` 之前 return，mock 任务不占槽位 |

### 6.1 算力扣费/退款：保留 + 测试前重置

扣费链路**保持原样，不拦截**：
- 媒体：`perseids_server/client.py` 的 `make_perseids_request` / `async_make_perseids_request`（endpoint=`user/calculate_computing_power`，behavior=`deduct`/`increase`）正常执行。扣费点 `server.py:3487-3496`、`:3725-3734`；退款 `task/visual_task.py:190-199`、`:837-866`。幂等键 `transaction_id`。
- token：`task/token_task.py:117 process_token_logs` 的 `ComputingPowerModel.update`（`:165`）正常执行。

**测试前重置测试账户算力**（保证不被扣穿、每次起点一致）。余额存于 `ComputingPowerModel`（perseids 服务与 token_task 共用此表）：

```python
# scripts/reset_test_balance.py 或 fixture setup 调用
from model.computing_power import ComputingPowerModel

def reset_test_balance(user_id: int, amount: int = 1_000_000) -> None:
    """把测试账户算力重置到固定高值。每次 E2E 运行前调用。"""
    cp = ComputingPowerModel.get_by_user_id(user_id)
    if cp:
        ComputingPowerModel.update(user_id, amount)   # 与 token_task.py:165 同款签名 (user_id, new_power)
    else:
        ComputingPowerModel.create(user_id=user_id, computing_power=amount)
    # 若 perseids 为独立服务且对媒体扣费具独立权威源，需额外通过其 admin/grant 接口置余额；
    # 当前实现看 perseids 与本服务共用 computing_power 表。
```

> 验收不再是"算力不变"，而是"扣费/退款链路被实际执行（日志可见 `calculate_computing_power` deduct/increase 与 token 扣减）+ 测试前余额被重置 + 不影响生产账户"。

### 6.2 CDN/七牛上传：保留，不改动

`server.auto_upload_to_cdn` **保持不动**（由测试环境 `config_*.yml` 决定，建议测试环境配置独立 CDN bucket 或本地 storage）。`update_with_cdn_sync`（`model/ai_tools.py:449`）与 `_handle_audio_task_success`（`runninghub_async_task.py:90`）的真实上传链路全部保留——CDN 上传也被 E2E 覆盖，且**无需任何代码改动**，降低本期复杂度与线上风险。

> mock 产出的 `/upload/mock/` 结果若被上传到测试 bucket 是预期行为；测试环境与生产 CDN 隔离即可。无需 save/restore `auto_upload_to_cdn`，无需给 CDN 入口加 test_mode 短路。

### 6.3 RunningHub 槽位：天然不占

§5.4 的 `submit_with_slot_management` mock 短路在 `try_acquire_slot`（`:92`）之前 return，mock 任务**根本不获取槽位**，`runninghub_slots` 表无 mock 记录。轮询调度器 mock 分支的 `release_slot` 仅作保险。无需任何 bypass 开关。

---

## 7. 配置缓存一致性（critical）

**事实**：`config/config_util.py:257` `_dynamic_config_cache` 是**进程级**内存字典，`_DYNAMIC_CACHE_TTL = 30`（`:259`）。`invalidate_dynamic_cache` / `POST /api/admin/config/reload`（`admin.py:900`）只清**当前进程**缓存。

**受影响**：
- `SyncTaskExecutor` 的 `ProcessPoolExecutor` worker（独立进程，独立缓存）。
- 任何已 fork 的 worker 在 30s 内可能读到旧 `test_mode.enabled`。

**应对（必须执行其一）**：
1. **主进程预判（推荐）**：视觉同步任务的 mock 判定放在**主进程** `visual_task._submit_new_task` 的 sync 分流之前（§5.1 改动 A 已在分流之前短路）。若 mock，则**不** `executor.submit()` 到子进程，直接在主进程写 mock 结果。这样子进程缓存不影响 mock 判定。
2. **fixture 操作时序**：开 test_mode 后调用 `POST /api/admin/config/reload`，并**重启 `SyncTaskExecutor` 进程池**（`shutdown()` + `start()`，让 worker 重新 fork），或**等待 >30s** 再提交任务。
3. **batch 接口注意**：`PUT /api/admin/config/batch` 会在每个成功新建/更新项提交后主动清除对应的当前进程缓存，无需再调 `/config/reload`。

> 主进程 `BackgroundScheduler` 是**线程**非进程，与主进程共享缓存，30s TTL 对其可接受；问题主要在 `SyncTaskExecutor` 子进程。故方案 1 优先。

---

## 8. 任务清理豁免（防止 mock 任务被误杀）

`task/visual_task.py` 的清理逻辑不区分 mock 任务：

| 逻辑 | 位置 | 对 mock 的影响 |
|------|------|----------------|
| 过期清理 | `_check_task_expiration`（`:904`，默认 7 天） | 历史残留 mock 任务可能过期失败 |
| 最大重试 | `_check_max_retry_exceeded`（`:928`，默认 30 次） | `inject_failure_rate` 会累加 `try_count`，30 次后强制 FAILED |
| 孤儿重置 | `scheduler.py:201`（`project_id IS NULL`）+ `visual_task.py:472` | mock 同步任务子进程异常会被重置回 PENDING，丢 attempt 一致性 |

**应对**：
1. E2E fixture 创建任务时刷新 `created_at` 为当前时间，避免误过期。
2. 在 `_check_task_expiration` 与 `_check_max_retry_exceeded` 开头加豁免：
   ```python
   from task.mock_interceptor import is_mock_id
   if is_mock_id(getattr(task, 'project_id', None)) or is_mock_id(getattr(ai_tool, 'project_id', None)):
       return False
   ```
3. `inject_failure_rate` 路径建议**不累加** `try_count`（mock 失败是受控注入，不应消耗重试额度）。

---

## 9. PARAM_PREPARE 死锁与 pipeline 时序（critical）

**事实**：`_submit_new_task` 最开头（`:235-242`）就检查 `get_pending_steps(PARAM_PREPARE)`，有则推进 `WAITING_PARAM_PREPARE` 并 `return True`——**在 §5.1 改动 A 的短路位置之后才安全**。

**因此 §5.1 改动 A 必须在 `param_prepare` 检查之前**。已满足（改动 A 插在 `:227`，早于 `:235`）。

**额外要求**：当任务类型带 face_mask（param_prepare）时，mock 主流程短路后直接成功，**不进 pipeline**，因此 face_mask step 不会创建。这是期望行为（E2E 不需要真实遮罩）。若 E2E 需测 face_mask 链路本身，则该任务类型的 mock 应**不**在 param_prepare 之前短路，而是让 face_mask step 走 §5.4/§5.8 的 mock，再让主任务 mock——此时需确保主任务在 `apply_results` 后回到 PENDING 时仍命中 §5.1 短路（基于 `test_mode` 判断，与 implementation 无关，满足）。

---

## 10. 企业版重试 / `implementation_attempts`

**链路**：`ImplementationRetryPipelineDriver`（`pipeline_drivers/implementation_retry_driver.py:32`）切换 `implementation` 并设回 PENDING 重新提交。

**要求**：
1. mock 短路**必须基于 `test_mode.enabled` 判断，不基于 implementation 名**——这样重试切换实现方后第二次 `_submit_new_task` 仍命中 §5.1 短路。已满足。
2. `implementation_attempts` 表在 submit/sync 成功/过期/max-retry/before_finish 多处读写。mock 任务**可创建 attempt 记录但不应影响判定**。建议 mock 成功时正常 `mark_active_attempt_completed(SUCCESS)`，保持表一致性；无需冻结。

---

## 11. 前端 / 后端开关同步

前端 `web/js/state.js:181` 的 `TEST_MODE`（URL `?test=1`）与后端 `test_mode.enabled` 是**两套独立机制**，且 mock project_id 前缀不同（前端 `mock_project_`、后端 `mock_task_`）。

**E2E fixture 要求**：**同时**开启——
- 后端：`test_mode.enabled=true`（PUT /api/admin/config）。
- 前端：访问 URL 带 `?test=1`。
- 明确职责：**后端为唯一真相源**；前端 `TEST_MODE` 仅做 UI 乐观渲染，不应在 `?test=1` 下向后端提交"真实"任务（否则前后端 mock 体系错位）。

---

## 12. 预设资源落地脚本

新建 `scripts/prepare_mock_assets.py`（或手动放置）：

```python
"""
准备 E2E mock 预设资源到 upload/mock/。
需人工提供真实样本文件（视频/音频/2x2图），脚本仅做拷贝与校验。
"""
import os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "upload", "mock")

# (源文件, 目标相对路径) —— 源文件由实施者准备
ASSETS = [
    ("auto_test/samples/e2e_text_to_image.png", "e2e_text_to_image.png"),
    ("auto_test/samples/e2e_image_edit.png",    "e2e_image_edit.png"),
    ("auto_test/samples/e2e_grid_2x2.png",      "e2e_grid_2x2.png"),
    ("auto_test/samples/e2e_i2v.mp4",           "e2e_i2v.mp4"),
    ("auto_test/samples/e2e_t2v.mp4",           "e2e_t2v.mp4"),
    ("auto_test/samples/e2e_dh.mp4",            "e2e_dh.mp4"),
    ("auto_test/samples/e2e_face_mask.mp4",     "e2e_face_mask.mp4"),
    ("auto_test/samples/e2e_tts.mp3",           "e2e_tts.mp3"),
    ("auto_test/samples/e2e_char.mp3",          "e2e_char.mp3"),
    ("auto_test/samples/e2e_ma_front.png",      "e2e_ma_front.png"),
    ("auto_test/samples/e2e_ma_side.png",       "e2e_ma_side.png"),
    ("auto_test/samples/e2e_ma_back.png",       "e2e_ma_back.png"),
    # 世界导入测试资产（由 §5.10 方式 1 从已播种世界导出生成后放入 auto_test/samples/）
    ("auto_test/samples/world_export_sample.zip", "world_export_sample.zip"),
]

def main():
    os.makedirs(DST, exist_ok=True)
    missing = []
    for src, name in ASSETS:
        s = os.path.join(ROOT, src)
        d = os.path.join(DST, name)
        if not os.path.exists(s):
            missing.append(src); continue
        shutil.copy2(s, d)
        print(f"OK  {d}")
    if missing:
        print(f"\n缺失样本（请准备后重跑）: {missing}", file=sys.stderr); sys.exit(1)

if __name__ == "__main__":
    main()
```

**配置写入脚本** `scripts/enable_test_mode.py`：直接调 `config.config_util.set_dynamic_config_value`（`config_util.py:332`，用 `SystemConfigModel.upsert`，**可自动新建配置项**；而 `PUT /api/admin/config/{key}` 在配置不存在时 404）。

```python
import os
from config.config_util import set_dynamic_config_value, invalidate_dynamic_cache

# ⚠️ bool 值必须传 Python bool（True/False），不能传字符串 "false"——
# config_util.py:365 是 `'true' if value else 'false'`，非空字符串 "false" 会被当 True 写成 'true'。
KV = {
    ("test_mode", "enabled"): (True, "bool"),
    ("test_mode", "mock_images", "text_to_image"): ("/upload/mock/e2e_text_to_image.png", "string"),
    ("test_mode", "mock_images", "image_edit"):    ("/upload/mock/e2e_image_edit.png", "string"),
    ("test_mode", "mock_images", "comfyui_text_to_image"): ("/upload/mock/e2e_comfyui_tti.png", "string"),
    ("test_mode", "mock_images", "comfyui_image_edit"):    ("/upload/mock/e2e_comfyui_ie.png", "string"),
    ("test_mode", "mock_images", "grid_image"):    ("/upload/mock/e2e_grid_2x2.png", "string"),
    ("test_mode", "mock_videos", "image_to_video"):("/upload/mock/e2e_i2v.mp4", "string"),
    ("test_mode", "mock_videos", "text_to_video"): ("/upload/mock/e2e_t2v.mp4", "string"),
    ("test_mode", "mock_videos", "digital_human"): ("/upload/mock/e2e_dh.mp4", "string"),
    ("test_mode", "mock_videos", "face_mask"):     ("/upload/mock/e2e_face_mask.mp4", "string"),
    ("test_mode", "mock_audio", "tts"):            ("/upload/mock/e2e_tts.mp3", "string"),
    ("test_mode", "mock_audio", "character_audio"):("/upload/mock/e2e_char.mp3", "string"),
    # multi_angle / grid_image_split_* 按需补充
}

for keys, (val, vtype) in KV.items():
    set_dynamic_config_value(*keys, value=val, value_type=vtype)

invalidate_dynamic_cache()  # 清当前进程缓存；跨进程见 §7

# 测试前重置测试账户算力（§6.1），保证运行期间不被扣穿
TEST_USER_ID = int(os.environ.get("E2E_TEST_USER_ID", "0"))
if TEST_USER_ID:
    from model.computing_power import ComputingPowerModel
    cp = ComputingPowerModel.get_by_user_id(TEST_USER_ID)
    if cp:
        ComputingPowerModel.update(TEST_USER_ID, 1_000_000)
    else:
        ComputingPowerModel.create(user_id=TEST_USER_ID, computing_power=1_000_000)
    print(f"test balance reset for user {TEST_USER_ID}")

print("test_mode enabled & mock URLs written.")
```

---

## 13. E2E fixture 模板（conftest.py）

```python
import os
import pytest
from config.config_util import (
    set_dynamic_config_value,
    get_dynamic_config_value,
    invalidate_dynamic_cache,   # config_util.py:407，签名 invalidate_dynamic_cache(config_key: str = None)
)

# ⚠️ bool 必须传 Python True/False，不能传 "false" 字符串（config_util.py:365，见 §12）。
# ⚠️ 算力与 CDN 均不绕过（见 §6）：不关 auto_upload_to_cdn，不 bypass billing。
TEST_USER_ID = int(os.environ.get("E2E_TEST_USER_ID", "0"))


def _invalidate(k):
    """config_util 用点分字符串做缓存 key（config_util.py:296/421）。"""
    invalidate_dynamic_cache(".".join(k))


@pytest.fixture(scope="session", autouse=True)
def e2e_mock_setup():
    # 仅保存/恢复 test_mode.enabled（mock URL 留着无害）
    saved_enabled = get_dynamic_config_value("test_mode", "enabled", default=False)

    # 1) 开启挡板（传 Python bool）
    set_dynamic_config_value("test_mode", "enabled", value=True, value_type="bool")
    _invalidate(("test_mode", "enabled"))

    # 2) 测试前重置测试账户算力（§6.1）
    if TEST_USER_ID:
        from model.computing_power import ComputingPowerModel
        cp = ComputingPowerModel.get_by_user_id(TEST_USER_ID)
        if cp:
            ComputingPowerModel.update(TEST_USER_ID, 1_000_000)
        else:
            ComputingPowerModel.create(user_id=TEST_USER_ID, computing_power=1_000_000)

    # 3) 重启 SyncTaskExecutor 进程池，使子进程重新 fork 并读到新 test_mode（§7）
    from task.sync_task_executor import get_sync_task_executor
    exe = get_sync_task_executor()
    if exe.is_running():
        exe.shutdown(wait=False)
        exe.start()

    yield

    # teardown：仅恢复 test_mode.enabled（不清理数据，见 §14）
    set_dynamic_config_value("test_mode", "enabled",
                             value=bool(saved_enabled), value_type="bool")
    _invalidate(("test_mode", "enabled"))
```

> 说明：
> - 算力扣费、token 计费、CDN 上传**均保留真实执行**（§6），fixture 不再关闭 `auto_upload_to_cdn`、不设 bypass 开关。
> - 测试账户算力在 setup 阶段重置到固定高值（`ComputingPowerModel.update`，与 `token_task.py:165` 同款签名），保证运行期间不被扣穿。
> - **不做数据清理**（§14）：基础数据采用幂等播种，DELETE 会破坏关联性。
> - `invalidate_dynamic_cache(config_key: str)`（`config_util.py:407`）点分 key；fixture 直接在测试进程内调 `set_dynamic_config_value`（不经 HTTP，无需 admin）。

---

## 14. 测试数据：幂等播种，不做清理

**决策（按用户要求）**：**不做 DELETE 清理**——担心破坏外键/业务关联性。基础数据改为**幂等播种**：播种前先查存在性，存在则跳过、不存在才新建。E2E 在隔离环境运行，累积的测试数据可接受。

**原则**：
1. 所有"准备基础数据"的步骤（测试用户、world、character、location、workflow、session 等）都必须**先查后建**（create-if-not-exists）。
2. 业务任务数据（ai_tools/async_tasks/grid_image_tasks 等）由被测流程自然产生，无需预置、也不清理。
3. 若需识别某次运行的产物用于排查，创建时在 `extra_config`/`message` 打 `is_e2e_test=true` 标记（仅用于查询定位，**不用于删除**）。

**幂等播种示例**（伪代码，按各 model 实际 get/create 方法实现）：

```python
def ensure_world(user_id, world_name):
    world = WorldModel.get_by_name(user_id, world_name)
    if world:
        return world.id                 # 已存在，直接复用
    return WorldModel.create(user_id=user_id, name=world_name, ...)

def ensure_character(world_id, name, **fields):
    char = CharacterModel.get_by_name(world_id, name)
    if char:
        return char.id
    return CharacterModel.create(world_id=world_id, name=name, **fields)
```

> 若未来确需清理某次失败的脏数据，应**针对该次运行标记的记录定点删除**，并严格遵守依赖顺序（先删子表再删父表），且仅在隔离环境执行。本期默认**不提供**批量清理脚本。

---

## 15. 可观测性

`mock_interceptor.py` 已内置进程内计数（`mock_hit_summary()`）。E2E 结束时输出：

```python
from task.mock_interceptor import mock_hit_summary
print("[MOCK SUMMARY]", mock_hit_summary())
```

预期每个被测通道至少命中 1 次；若某通道计数为 0，说明该路径漏到真实外部服务。channel 维度：`visual_async_submit/poll`、`visual_sync_submit`、`comfyui_submit/poll`、`async_submit:<impl>`。

---

## 16. 验收清单（逐条可验证）

### Phase 1：不真实调用外部 API
- [ ] `seedream_volcengine_v1_driver.py`（及另 12 个 sync 实现）在 test_mode 下不请求火山/GPT/Gemini。
- [ ] `script_writer_core/mcp_tool.py` 不真实 POST ComfyUI（text-to-image / image-edit）。
- [ ] `task/grid_image_task.py` 不真实 POST/GET ComfyUI（含 `_resubmit_image_request`）。
- [ ] `task/location_multi_angle_task.py` 不真实 POST ComfyUI、不远程下载图片。
- [ ] `task/async_drivers/runninghub_*_driver.py` 不真实上传文件、不提交/轮询 RunningHub。
- [ ] `server.py:8190 export_timeline_draft` 不远程下载 clip、不调 `refresh_cdn_signed_url`。
- [ ] `task/audio_task.py` 最终 `ai_audio.result_url` 是 mock 本地路径（非 `tts.upload_url+audio_filename` 虚构路径）。
- [ ] 日志中所有 mock 命中均有 `[MOCK]`；`mock_hit_summary()` 覆盖所有被测通道。
- [ ] 世界导出 `GET /api/export-world` 返回 download_url，下载 zip 含 `metadata.json` 且计数正确（真实代码，图床上传保留）。
- [ ] 世界导入 `POST /api/import-world` 用预置 `world_export_sample.zip` 成功，返回计数与落盘文件一致（真实代码，零外部依赖）。
- [ ] 时间轴导出 `export_timeline_draft` 在本地 mock 素材上成功生成草稿 zip（真实代码）。

### Phase 2：副作用可控（不绕过，靠隔离环境）
- [ ] 媒体算力扣费/退款链路被**真实执行**（日志可见 `calculate_computing_power` deduct/increase）。
- [ ] LLM token 计费被**真实执行**（日志可见 token 扣减）。
- [ ] 测试前测试账户算力被重置到固定高值，运行期间余额 > 0 不被扣穿。
- [ ] CDN 上传在测试环境正常运行，不触及生产 CDN bucket（环境隔离）。
- [ ] `runninghub_slots` 表无 mock 占用残留（mock 短路天然不 acquire）。
- [ ] teardown 后 `test_mode.enabled` 恢复原值；基础数据幂等播种，无 DELETE。

### Phase 3（可选）：错误注入
- [ ] `inject_failure_rate>0` 时能稳定复现 submit/poll/timeout 失败与重试成功，且失败路径正确退款（deduct→increase 净额为零）。

---

## 17. 实施分阶段

**Phase 1（核心，防止真实外部调用）**
1. 新建 `task/mock_interceptor.py`（§3）
2. 扩展 `config/default_configs.py`（§4.1）
3. `task/visual_task.py`（§5.1：A/B/C 三处）
4. `task/sync_task_executor.py`（§5.2）
5. `task/audio_task.py`（§5.3）
6. `task/async_drivers/base_async_driver.py`（§5.4）
7. `task/runninghub_async_task.py` + `task/async_task_submission.py`（§5.4 a/b）
8. `script_writer_core/mcp_tool.py`（§5.5）
9. `task/grid_image_task.py`（§5.6）
10. `task/location_multi_angle_task.py`（§5.7）
11. `server.py export_timeline_draft`——**无需改动**（§5.9，上游产出 `/upload/mock/` 本地路径即可）
12. `scripts/prepare_mock_assets.py` + 落盘样本 + 预置 `world_export_sample.zip`（§5.10 方式 1：播种世界后真实导出固化）

**Phase 2（副作用可控：不绕过，靠隔离环境）**
13. `scripts/enable_test_mode.py` + 测试前重置账户算力（§6.1 + §12）
14. CDN/算力/token **不改动**，保留真实链路（§6.1/§6.2）
15. 任务清理豁免（§8，防 mock 任务被 scheduler 误杀）
16. 缓存一致性处理（§7：主进程预判 + 重启进程池）
17. fixture 模板（§13）+ 基础数据幂等播种（§14，无 DELETE）

**Phase 3（错误注入，可选）**
19. `inject_failure_rate/scenario` 状态机
20. 重试链路 E2E 用例

---

## 18. 附录 A：通道拦截矩阵速查

| 通道 | 文件:函数 | 插入点（相对位置） | 成功态写库 | 复用的现有函数 |
|------|-----------|--------------------|------------|----------------|
| 视觉异步 submit | `visual_task._submit_new_task:~227` | param_prepare/impl/sync 分流**之前** | `ai_tools`+`tasks` | — |
| 视觉异步 poll | `visual_task._check_task_status:~483` | 创建 driver 之前 | 经 `_handle_task_success` | `_handle_task_success` |
| 视觉异步成功 | `visual_task._handle_task_success:~682` | download_and_cache 之前加 is_local_path 短路 | — | — |
| 视觉同步 | `sync_task_executor._execute_sync_task:~81` | 创建 driver 之前 | `SyncTaskResult` | `_handle_task_result` |
| Index TTS | `audio_task._submit_new_task:~56` | generate_audio 之前 | `ai_audio`+`tasks` | — |
| RH 异步 submit | `base_async_driver.submit_with_slot_management:~88` | create 之后、acquire_slot 之前 | `async_tasks.external_task_id` | — |
| RH 异步 poll | `runninghub_async_task.process_runninghub_async_tasks:~276` | external_task_id 空检查之后 | `async_tasks` COMPLETED | success_handler |
| ComfyUI 工具 | `mcp_tool.text_to_image:~3686` / `image_edit:~594` | httpx.post 之前 | GridImageTasks 后台记录 | — |
| 四宫格 poll | `grid_image_task.process_grid_image_tasks:~416` | requests.get 之前 | `grid_image_tasks`+item | `_handle_task_success` |
| 四宫格 retry | `grid_image_task._resubmit_image_request:~142` | 函数开头 | 返回 mock pid | — |
| 多角度 submit | `location_multi_angle_task:~380` | requests.post 之前 | multi-angle 记录 | `_update_reference_images_to_staging` |
| 多角度 download | `location_multi_angle_task._download_and_store_image:~70` | requests.get 之前 | — | — |
| 时间轴 | `server.py export_timeline_draft` | **无需拦截**（上游 `/upload/mock/` 本地路径自动走本地拷贝） | — | `_get_local_upload_file` |
| 世界导入/导出 | `api/script_writer.py export-world/import-world` | **无需拦截**（导出走真实图床 §6.2；导入纯本地）；需预置 `world_export_sample.zip` | — | `export_world`/`import_world` |

## 19. 附录 B：关键事实速查（已核实）

- `TaskCategory`（`config/unified_config.py:29-49`）是**字符串常量类非 Enum**，值为 `text_to_image`/`image_edit`/`image_to_video`/`text_to_video`/`visual_enhance`/`audio`/`digital_human`/`other`。**无 `.name`**，映射 key 必须用小写字符串值或 `TaskCategory.XXX` 常量。
- `UnifiedTaskConfig.categories: List[str]`（`unified_config.py:315`）存在；多分类判断用 `[cfg.category] + cfg.categories`。
- `sync_mode=True` 实现**共 13 个**（见 §5.2）。
- `download_and_cache`（`media_cache.py:192`）**不识别**本地路径，调用方须自判 `is_local_path`。
- `location_multi_angle_task` 轮询走 **DB**（`AIToolsModel.get_by_id`），非 get-status。
- `cron_task_manager.py:322` 轮询是**死代码**，勿拦截。
- 音频通道**不扣费**；扣费在 perseids（媒体）与 `token_task`（LLM token）两套独立后端。
- `_DYNAMIC_CACHE_TTL=30`，跨进程缓存（§7）。
- `async_tasks.external_task_id varchar(100)`（`model/async_tasks.py:454`），`mock_task_`+16hex 远小于上限。
- admin 配置接口：`PUT /api/admin/config/batch`、`PUT /api/admin/config/{key}`、`POST /api/admin/config/reload`；单条与 batch 写入都会主动清除对应的当前进程缓存。
- `set_dynamic_config_value`（`config_util.py:332`）用 upsert 可新建配置；`PUT /api/admin/config/{key}` 不存在则 404。
- **bool 配置必须传 Python `True`/`False`**：`config_util.py:365` 为 `'true' if value else 'false'`，非空字符串 `"false"` 会被当真值写成 `'true'`。
- 世界导出/导入（`api/script_writer.py:4563/4599`）无需 mock：导出仅图床上传（§6.2 保留），导入纯本地 zip 处理；测试需预置合法 `world_export_sample.zip`（结构见 §5.10）。
- 算力/CDN/token **均不绕过**（用户决策）：靠独立隔离环境 + 测试前 `ComputingPowerModel.update` 重置测试账户算力；不做数据 DELETE，基础数据幂等播种（§6/§14）。

---

**实施完成后，运行 §16 验收清单逐条勾选；任一未通过即对应通道拦截未生效。**
