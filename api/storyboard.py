"""
Storyboard API - 故事板后端接口

路由前缀: /api/storyboard
所有 DB 操作均为同步 pymysql，在异步路由中必须用 asyncio.to_thread() 包装。
"""
import asyncio
import json
import logging
import math
import os
import re
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Header, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from perseids_server.utils.permission import require_permission
from perseids_server.client import async_make_perseids_request

from api.auth_identity import (
    normalize_authorization_token as _auth_header_token,
    resolve_authorization_user_id as _resolve_auth_user_id,
)

from config.constant import (
    Edition, Action,
    TASK_TYPE_GENERATE_VIDEO, TASK_TYPE_GENERATE_AUDIO,
    TASK_STATUS_QUEUED, AI_TOOL_STATUS_PENDING, AI_AUDIO_STATUS_PENDING,
    AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
    StoryboardAutoGenerateConstants,
    StoryboardAudioGenerateConstants,
    StoryboardDigitalHumanConstants,
    StoryboardAgentCommandConstants,
    SceneDifficulty,
    MediaConstants,
    MediaGenerationMode,
    MediaGenerationSurface,
    MediaGenerationType,
)
from config.config_util import get_config, get_dynamic_config_value
from config.unified_config import (
    SceneVideoType,
    UnifiedConfigRegistry,
    TaskTypeId,
    TaskCategory,
    SEEDANCE_FACE_MASK_DRIVER_KEYS,
)
from utils.project_path import (
    get_upload_subdir,
    generate_upload_filename,
    build_upload_url,
    resolve_upload_url_to_local_path,
)
from utils.video_compressor import get_video_info
from model.storyboard import (
    StoryboardModel, StoryboardSceneModel,
    StoryboardDialogueModel, StoryboardDialogueAudioModel,
    StoryboardSceneAssetModel,
    compute_sort_between, is_precision_exhausted,
)
from model.ai_tools import AIToolsModel
from model.ai_audio import AIAudioModel
from model.tasks import TasksModel
from model.character import CharacterModel
from model.world import WorldModel
from model.script import ScriptModel
from model.user_tokens import UserTokensModel
from model.user_preferences import UserPreferencesModel
from utils.resource_access import (
    get_user_id_from_header,
    ensure_resource_access,
    ensure_world_access,
)
from services.storyboard_agent_cli_service import StoryboardCliError
from services.storyboard_agent_command_service import StoryboardAgentCommandService
from services.storyboard_batch_operation_service import (
    StoryboardBatchOperationError,
    batch_delete_storyboard_scenes,
)
from services.storyboard_asset_service import (
    StoryboardAssetDeleteError,
    StoryboardAssetSelectError,
    delete_storyboard_scene_asset,
    select_storyboard_scene_asset,
)
from services.storyboard_voiceover_bootstrap_service import (
    StoryboardVoiceoverBootstrapService,
)
from services.storyboard_reference_prompt_service import build_reference_legend, reference_urls
from services.storyboard_spatial import build_spatial_prompt_context
from services.media_generation_preference_service import (
    MediaGenerationPreferenceError,
    MediaGenerationPreferenceService,
)
from task.audio_task import recalc_scene_duration_if_all_completed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/storyboard", tags=["storyboard"])

# update_scene 允许前端直接修改的字段（选中指针由 asset/select 接口管理，不在此处）
ALLOWED_SCENE_UPDATE_FIELDS = {
    'title', 'duration', 'prompt_json', 'video_prompt', 'video_type', 'video_config_json',
    'audio_embedded', 'difficulty', 'act_name',
}
ALLOWED_DIALOGUE_UPDATE_FIELDS = {
    'character_id', 'text', 'speed', 'volume',
}
VALID_ASSET_TYPES = ('first_frame', 'last_frame', 'video')


def _storyboard_media_preferences_sync(storyboard) -> Dict[str, Dict[str, Any]]:
    config_json = storyboard.to_dict().get('config_json') or {}
    if not isinstance(config_json, dict):
        config_json = {}
    result: Dict[str, Dict[str, Any]] = {}
    config_updates: Dict[str, int] = {}
    for media_type, modes in (
        (MediaGenerationType.IMAGE, MediaGenerationMode.IMAGE_MODES),
        (MediaGenerationType.VIDEO, MediaGenerationMode.VIDEO_MODES),
    ):
        for mode in modes:
            field = MediaGenerationPreferenceService.storyboard_config_field(media_type, mode)
            raw_task_id = config_json.get(field)
            is_new_field = raw_task_id not in (None, "")
            if not is_new_field:
                legacy_field = (
                    'selectedImageTaskId'
                    if media_type == MediaGenerationType.IMAGE
                    else 'selectedVideoTaskId'
                )
                raw_task_id = config_json.get(legacy_field)

            # 先读 media_pref（含 enable_face_mask 等扩展字段），再按 config_json 的 task_id 覆盖模型
            pref_profile = MediaGenerationPreferenceService.get_profile(
                storyboard.user_id,
                storyboard.world_id,
                MediaGenerationSurface.STORYBOARD_UI,
                media_type,
                mode,
            )
            profile = dict(pref_profile) if isinstance(pref_profile, dict) else None
            if raw_task_id not in (None, ""):
                try:
                    task_config = MediaGenerationPreferenceService.validate_model(
                        raw_task_id,
                        media_type,
                        mode,
                        image_mode=(
                            'multi_reference'
                            if mode == MediaGenerationMode.REFERENCE_TO_VIDEO
                            else None
                        ),
                    )
                    if profile is None:
                        profile = {}
                    profile.update({
                        'schema_version': 1,
                        'task_id': int(task_config.id),
                        'model_key': task_config.key,
                        'model_name': task_config.name,
                    })
                    # 非 Seedance 2.0 系列强制关闭人脸遮盖，避免脏字段回显
                    if (
                        media_type == MediaGenerationType.VIDEO
                        and mode == MediaGenerationMode.IMAGE_TO_VIDEO
                        and getattr(task_config, 'key', None) not in SEEDANCE_FACE_MASK_DRIVER_KEYS
                    ):
                        profile['enable_face_mask'] = False
                except MediaGenerationPreferenceError:
                    # config_json 中的 task_id 失效时回退 pref
                    pass
            if profile is None:
                profile = MediaGenerationPreferenceService.get_profile(
                    storyboard.user_id,
                    storyboard.world_id,
                    MediaGenerationSurface.STORYBOARD_UI,
                    media_type,
                    mode,
                )
            # config_json 级 enableFaceMask 兜底（偏好槽未写过时）
            if (
                media_type == MediaGenerationType.VIDEO
                and mode == MediaGenerationMode.IMAGE_TO_VIDEO
                and isinstance(profile, dict)
                and 'enable_face_mask' not in profile
                and isinstance(config_json.get('enableFaceMask'), bool)
            ):
                profile['enable_face_mask'] = bool(config_json.get('enableFaceMask'))
            result[MediaGenerationPreferenceService.slot_key(media_type, mode)] = profile
            config_updates[field] = int(profile['task_id'])
    if config_updates:
        StoryboardModel.patch_config_json(int(storyboard.id), config_updates)
    return result


def _storyboard_generation_snapshots_sync(storyboard) -> Dict[str, Dict[str, Any]]:
    """在 Agent 提交时一次性冻结 Storyboard 的全部五个媒体槽位。"""
    profiles = _storyboard_media_preferences_sync(storyboard)
    storyboard_ratio = (
        normalize_storyboard_workflow_ratio(getattr(storyboard, 'workflow_ratio', None))
        or str(getattr(storyboard, 'workflow_ratio', None) or '').strip()
        or '16:9'
    )
    snapshots: Dict[str, Dict[str, Any]] = {}
    for slot, profile in profiles.items():
        media_type, mode = slot.split('.', 1)
        snapshot = MediaGenerationPreferenceService.build_snapshot(
            profile,
            MediaGenerationSurface.STORYBOARD_UI,
            media_type,
            mode,
            model_source='storyboard_config',
        )
        # 图片槽锁定故事板画幅，供 edit_image / generate_text_to_image 系统注入
        if media_type == MediaGenerationType.IMAGE:
            snapshot['ratio'] = storyboard_ratio
        elif media_type == MediaGenerationType.VIDEO and not snapshot.get('ratio'):
            snapshot['ratio'] = storyboard_ratio
        snapshots[slot] = snapshot
    return snapshots


def _resolve_storyboard_generation_snapshot_sync(
    storyboard,
    *,
    user_id: int,
    media_type: str,
    mode: str,
    explicit_task_id: Optional[int],
    profile_values: Optional[Dict[str, Any]] = None,
    has_reference_audio_video: bool = False,
) -> Dict[str, Any]:
    source = 'storyboard_config'
    if explicit_task_id not in (None, ''):
        source = 'request'
        profile = dict(profile_values or {})
        profile['task_id'] = int(explicit_task_id)
        profile = MediaGenerationPreferenceService.save_profile(
            user_id,
            storyboard.world_id,
            MediaGenerationSurface.STORYBOARD_UI,
            media_type,
            mode,
            profile,
        )
        field = MediaGenerationPreferenceService.storyboard_config_field(media_type, mode)
        StoryboardModel.patch_config_json(int(storyboard.id), {field: profile['task_id']})
    else:
        profiles = _storyboard_media_preferences_sync(storyboard)
        profile = dict(
            profiles[MediaGenerationPreferenceService.slot_key(media_type, mode)] or {}
        )
        # 合并本轮 profile_values（如 workflow_ratio），不覆盖已解析的 task_id
        for key, value in dict(profile_values or {}).items():
            if value in (None, ''):
                continue
            if key == 'task_id' and profile.get('task_id') not in (None, ''):
                continue
            profile[key] = value
    return MediaGenerationPreferenceService.build_snapshot(
        profile,
        MediaGenerationSurface.STORYBOARD_UI,
        media_type,
        mode,
        model_source=source,
        has_reference_audio_video=has_reference_audio_video,
    )


class StoryboardAssetUploadTooLarge(ValueError):
    """分镜资产上传超过配置的文件大小限制。"""


def _store_storyboard_asset_file(
    source_file,
    asset_type: str,
    extension: str,
    max_bytes: int,
) -> Dict[str, Any]:
    """在线程中限额分块复制上传文件，返回落盘信息。"""
    subdir_parts = ("storyboard", asset_type)
    abs_dir = get_upload_subdir(*subdir_parts, ensure=True)
    name_info = generate_upload_filename(prefix=f"sb_{asset_type}", extension=extension)
    abs_path = os.path.join(abs_dir, name_info.filename)
    total_bytes = 0

    try:
        source_file.seek(0)
        with open(abs_path, "wb") as target_file:
            while True:
                chunk = source_file.read(MediaConstants.STORYBOARD_ASSET_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise StoryboardAssetUploadTooLarge()
                target_file.write(chunk)
    except Exception:
        try:
            if os.path.exists(abs_path):
                os.remove(abs_path)
        except OSError:
            logger.warning("清理未完成的分镜上传文件失败: %s", abs_path, exc_info=True)
        raise

    return {
        "abs_path": abs_path,
        "subdir_parts": subdir_parts,
        "filename": name_info.filename,
        "size_bytes": total_bytes,
    }


def _remove_file_if_exists(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        logger.warning("清理分镜上传文件失败: %s", path, exc_info=True)


def _remove_deleted_storyboard_asset_file(result_url: str, asset_type: str) -> bool:
    """仅删除当前服务 storyboard 目录内的普通文件，拒绝外部 URL 与越界路径。"""
    text = str(result_url or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    if parsed.scheme and parsed.hostname not in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return False
    path = parsed.path or text.split("?", 1)[0]
    if not path.startswith(f"/upload/storyboard/{asset_type}/"):
        return False

    abs_path = os.path.realpath(resolve_upload_url_to_local_path(path))
    allowed_dir = os.path.realpath(get_upload_subdir("storyboard", asset_type, ensure=False))
    try:
        if os.path.commonpath([abs_path, allowed_dir]) != allowed_dir:
            return False
    except ValueError:
        return False
    if not os.path.isfile(abs_path):
        return False
    os.remove(abs_path)
    return True


# ==================== Helpers ====================

async def _read_json_object_body(request: Request):
    raw_body = await request.body()
    if not raw_body or not raw_body.strip():
        return {}, None
    try:
        data = json.loads(raw_body)
    except Exception:
        return None, JSONResponse(
            status_code=400,
            content={'success': False, 'error_code': 'invalid_body', 'error': 'JSON body is invalid'},
        )
    if not isinstance(data, dict):
        return None, JSONResponse(
            status_code=400,
            content={'success': False, 'error_code': 'invalid_body', 'error': 'JSON body must be an object'},
        )
    return data, None


async def _sync_script_split_model_preference(
    user_id: int,
    world_id: int,
    config_json: Any,
):
    """把故事板拆分模型选择同步为当前用户在该世界的默认偏好。"""
    if not isinstance(config_json, dict):
        return None, None
    selection = config_json.get("selectedScriptSplitLlmModel")
    if isinstance(selection, str):
        selection = selection.strip()
    if not selection:
        return None, None
    try:
        await asyncio.to_thread(
            UserPreferencesModel.upsert,
            str(user_id),
            str(world_id),
            StoryboardAgentCommandConstants.SCRIPT_SPLIT_MODEL_PREFERENCE_TYPE,
            selection,
        )
        return True, None
    except Exception as exc:
        logger.error(
            "同步用户 %s 世界 %s 的拆分模型偏好失败: %s",
            user_id,
            world_id,
            exc,
        )
        return False, "故事板已保存，但世界级拆分模型偏好同步失败"


def _json_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return default

def resolve_storyboard_script_id(
    script_id: Optional[int],
    world_id: int,
    episode_number: int,
) -> Optional[int]:
    """Return explicit script_id, or fall back to the script for world/episode."""
    if script_id:
        return script_id

    script = ScriptModel.get_by_episode(world_id, episode_number)
    return script.id if script else None


def resolve_storyboard_create_title(
    title: Optional[str],
    script_id: Optional[int],
    episode_number: int,
) -> str:
    """
    新建故事板时的标题：
    1) body 显式非空 title
    2) 关联剧本 script.title
    3) 兜底「第{N}集故事板」（与前端 buildStoryboardTitle 一致）
    """
    explicit = str(title or '').strip()
    if explicit:
        return explicit[:255]

    if script_id:
        try:
            script = ScriptModel.get_by_id(int(script_id))
            script_title = str(getattr(script, 'title', None) or '').strip() if script else ''
            if script_title:
                return script_title[:255]
        except Exception as e:
            logger.warning(f"resolve_storyboard_create_title script_id={script_id}: {e}")

    ep = episode_number if isinstance(episode_number, int) else 1
    try:
        ep = int(episode_number) if episode_number is not None else 1
    except (TypeError, ValueError):
        ep = 1
    if ep < 1:
        ep = 1
    return f'第{ep}集故事板'


# 创建/继承允许的画幅比例（兼容 header 历史选项）
STORYBOARD_WORKFLOW_RATIOS = frozenset({'16:9', '9:16', '3:4', '1:1', '4:3'})
DEFAULT_STORYBOARD_WORKFLOW_RATIO = '16:9'


def normalize_storyboard_workflow_ratio(value: Any) -> Optional[str]:
    """校验并规范化 workflow_ratio；非法或空返回 None。"""
    ratio = str(value or '').strip()
    if not ratio:
        return None
    if ratio not in STORYBOARD_WORKFLOW_RATIOS:
        return None
    return ratio


def _coerce_enable_face_mask(value: Any) -> bool:
    """Normalize enable_face_mask from request body / config JSON."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return False


def _storyboard_needs_face_mask_pipeline(
    *,
    task_type: int,
    enable_face_mask: bool,
    has_image_input: bool = True,
    user_id: Optional[int] = None,
) -> bool:
    """Whether storyboard direct generate-video should create face_mask param_prepare steps.

    Aligns with server.py image-to-video gate (Seedance 2.0 + enterprise + RunningHub).
    """
    if not enable_face_mask or not has_image_input or Edition.is_community():
        return False
    try:
        from task.pipeline_processor import PipelineProcessor
        if not PipelineProcessor.is_seedance_face_mask_type(int(task_type)):
            return False
    except Exception as e:
        logger.warning(f"Failed to check seedance face mask type for task {task_type}: {e}")
        return False

    # 实现方若自带 human_review（如 huimengi），跳过 RunningHub 遮盖预处理
    try:
        from task.visual_drivers import VideoDriverFactory
        actual_impl = VideoDriverFactory.get_implementation_for_user(
            int(task_type), user_id
        ) if user_id is not None else None
        impl_config = (
            UnifiedConfigRegistry.get_implementation(actual_impl) if actual_impl else None
        )
        if impl_config and getattr(impl_config, 'supports_auto_face', False):
            return False
    except Exception as e:
        logger.warning(
            f"Failed to resolve impl auto-face for storyboard face mask gate: {e}"
        )

    runninghub_api_key = get_dynamic_config_value("runninghub", "api_key", default=None)
    seedance_face_mask_enabled = get_dynamic_config_value(
        "pipeline", "seedance_face_mask_enabled", default=True
    )
    return bool(runninghub_api_key) and bool(seedance_face_mask_enabled)


async def _build_storyboard_agent_video_preferences(
    *,
    user_id: int,
    world_id: int,
    storyboard,
    image_mode: str,
    duration_seconds: int,
    video_resolution: Optional[str],
    video_task_id: Optional[int] = None,
    enable_face_mask: bool = False,
) -> Dict[str, Any]:
    """Build an immutable task snapshot without mutating shared user preferences.

    对齐 marketing_agent：每次 Agent 请求把当前界面选中的视频模型
    （task_id / model_name）打进任务级快照，工具层强制使用该 task_type，
    从而：
    1) 避免 Agent 经 list_video_models 自选模型覆盖齿轮选择；
    2) 用户中途改模型后，下一次发送使用新模型；进行中任务仍用发送时快照。

    enable_face_mask 必须由 Storyboard 界面显式传入，禁止读取 Marketing 共享偏好。
    """
    ratio = (
        normalize_storyboard_workflow_ratio(getattr(storyboard, 'workflow_ratio', None))
        or DEFAULT_STORYBOARD_WORKFLOW_RATIO
    )
    # Storyboard 参数只来自当前 Storyboard 界面和任务快照，禁止读取 Marketing
    # 的历史共享偏好，否则两个入口会在比例、分辨率等字段上发生串扰。
    effective_face_mask = bool(enable_face_mask) and not Edition.is_community()
    preferences = {
        'ratio': ratio,
        'image_mode': image_mode,
        'duration': int(duration_seconds),
        'enable_face_mask': effective_face_mask,
    }
    if video_resolution:
        preferences['resolution'] = str(video_resolution)

    resolved_task_id = None
    if video_task_id is not None and str(video_task_id).strip() != '':
        try:
            resolved_task_id = int(video_task_id)
        except (TypeError, ValueError):
            resolved_task_id = None
    if resolved_task_id is not None:
        preferences['task_id'] = resolved_task_id
        try:
            cfg = UnifiedConfigRegistry.get_by_id(resolved_task_id)
            if cfg and getattr(cfg, 'name', None):
                preferences['model_name'] = cfg.name
            # 非 Seedance 2.0 系列强制关闭，避免脏偏好进入快照
            if cfg and getattr(cfg, 'key', None) not in SEEDANCE_FACE_MASK_DRIVER_KEYS:
                preferences['enable_face_mask'] = False
        except Exception as e:
            logger.warning(
                f"Failed to resolve storyboard video model name for task_id={resolved_task_id}: {e}"
            )
    return preferences


def resolve_storyboard_create_ratio(user_id: int, world_id: int, data: dict) -> str:
    """
    新建故事板时解析 workflow_ratio：
    1) body 显式合法值
    2) 同世界已有故事板：优先第 1 集，否则最小集号
    3) 兜底 16:9（API/Agent 无 UI；Web 首建应先弹窗再显式传入）
    """
    explicit = normalize_storyboard_workflow_ratio(data.get('workflow_ratio') if data else None)
    if explicit:
        return explicit

    inherited = StoryboardModel.resolve_inherited_workflow_ratio(user_id, world_id)
    if inherited:
        ratio = normalize_storyboard_workflow_ratio(inherited.get('workflow_ratio'))
        if ratio:
            return ratio
        # 有故事板但 ratio 全空：仍用默认
        return DEFAULT_STORYBOARD_WORKFLOW_RATIO

    return DEFAULT_STORYBOARD_WORKFLOW_RATIO


def build_storyboard_defaults(world, data: dict, *, workflow_ratio: Optional[str] = None) -> dict:
    """Build inherited storyboard defaults without assuming optional world fields."""
    style = getattr(world, 'visual_style', None) if world else None
    ratio = normalize_storyboard_workflow_ratio(workflow_ratio)
    if not ratio:
        ratio = normalize_storyboard_workflow_ratio(data.get('workflow_ratio') if data else None)
    if not ratio:
        ratio = DEFAULT_STORYBOARD_WORKFLOW_RATIO
    return {
        'style': data.get('style', style) if data else style,
        'workflow_ratio': ratio,
        'style_reference_image': getattr(world, 'style_reference_image', None) if world else None,
        'composition_preference': (data.get('composition_preference') if data else None) or (
            getattr(world, 'composition_preference', None) if world else None
        ),
    }


def _compact_join(parts: List[Optional[str]], sep: str = "\n") -> str:
    return sep.join(str(part).strip() for part in parts if str(part or '').strip())


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    """将 LLM / 前端传来的值安全转为 float（保留小数，配合 DECIMAL(10,3)）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_character_db_map(parsed_data: dict) -> Dict[str, Optional[int]]:
    character_map: Dict[str, Optional[int]] = {}
    for character in parsed_data.get('characters') or []:
        character_id = character.get('id')
        if character_id:
            character_map[str(character_id)] = character.get('character_db_id')
    return character_map


def _build_character_name_map(parsed_data: dict) -> Dict[str, str]:
    return {
        str(character.get('id')): character.get('name') or ''
        for character in (parsed_data.get('characters') or [])
        if character.get('id')
    }


def _build_location_map(parsed_data: dict) -> Dict[str, dict]:
    return {
        str(location.get('id')): location
        for location in (parsed_data.get('locations') or [])
        if location.get('id')
    }


def _build_prop_map(parsed_data: dict) -> Dict[str, dict]:
    return {
        str(prop.get('id')): prop
        for prop in (parsed_data.get('props') or [])
        if prop.get('id')
    }


def _dialogue_character_id(dialogue: dict, character_db_map: Dict[str, Optional[int]]) -> Optional[int]:
    raw_character_id = dialogue.get('character_id')
    if raw_character_id is None:
        return None
    db_character_id = character_db_map.get(str(raw_character_id))
    if db_character_id is None:
        return None
    return _safe_int(db_character_id, None)


# reorganize_shot_groups 按时长拆组时，会把 group_name 改成 "xxx - 片段N"。
# 提取 act_name（幕名）时需剥掉这个后缀，避免 act_name 被污染。
_ACT_NAME_FRAGMENT_SUFFIX_RE = re.compile(r"\s*-\s*片段\d+$")


def _extract_act_name(raw_group_name: str) -> Optional[str]:
    """从 group_name 提取幕名，去掉时长拆组产生的 ' - 片段N' 后缀。"""
    if not raw_group_name:
        return None
    cleaned = _ACT_NAME_FRAGMENT_SUFFIX_RE.sub('', str(raw_group_name)).strip()
    return cleaned or None


def build_storyboard_scenes_from_parsed_script(parsed_data: dict, style: str = '') -> List[dict]:
    """
    Convert llm.script_parser output into StoryboardModel.create_scenes payload.

    One parsed shot becomes one storyboard_scene; dialogue entries under the shot
    become storyboard_dialogue rows.
    """
    character_db_map = _build_character_db_map(parsed_data)
    character_name_map = _build_character_name_map(parsed_data)
    location_map = _build_location_map(parsed_data)
    prop_map = _build_prop_map(parsed_data)
    spatial_world = parsed_data.get('spatial_world') if isinstance(parsed_data.get('spatial_world'), dict) else None
    scenes: List[dict] = []

    for group in parsed_data.get('shot_groups') or []:
        group_name = group.get('group_name') or ''
        group_type = group.get('group_type') or ''
        # 幕名：优先用 group.act_title（LLM 显式输出的幕名），其次从 group_name 剥掉 " - 片段N" 后缀
        raw_act = group.get('act_title') or group.get('act')
        act_name = (str(raw_act).strip() or None) if raw_act else _extract_act_name(group_name)
        for shot in group.get('shots') or []:
            scene_index = len(scenes) + 1
            location = location_map.get(str(shot.get('location_id'))) or {}
            location_name = shot.get('location_name') or location.get('name') or ''
            location_db_id = shot.get('db_location_id', location.get('location_db_id'))
            camera_angle = shot.get('camera_angle') or ''
            shot_type = shot.get('shot_type') or ''

            # 提取当前分镜的道具
            props_present = shot.get('props_present') or []
            shot_props = []
            for pid in props_present:
                p = prop_map.get(str(pid)) or {}
                shot_props.append({
                    'id': p.get('id') or pid,
                    'name': p.get('name') or '',
                    'db_id': p.get('db_id') or p.get('props_db_id'),
                })
            perspective = _compact_join([camera_angle, shot_type], ' / ')
            scene_desc = _compact_join([
                shot.get('opening_frame_description'),
                shot.get('scene_detail'),
            ])
            character_names = []
            for raw_character_id in shot.get('characters_present') or []:
                name = character_name_map.get(str(raw_character_id))
                if name:
                    character_names.append(name)
            character_desc = '、'.join(dict.fromkeys(character_names))

            video_prompt = _compact_join([
                shot.get('description'),
                shot.get('scene_detail'),
                shot.get('action'),
                f"镜头运动：{shot.get('camera_movement')}" if shot.get('camera_movement') else None,
                f"叙事目的：{shot.get('narrative_purpose')}" if shot.get('narrative_purpose') else None,
            ])

            dialogues = []
            for dialogue in shot.get('dialogue') or []:
                text = str(dialogue.get('text') or '').strip()
                if not text:
                    continue
                dialogues.append({
                    'character_id': _dialogue_character_id(dialogue, character_db_map),
                    'text': text,
                    'speed': 1.0,
                    'volume': 100,
                })

            from services.storyboard_scene_type import resolve_scene_video_type
            resolved_video_type, presentation_meta = resolve_scene_video_type(shot, dialogues)

            prompt_payload = {
                'perspective': perspective,
                'style': style or parsed_data.get('style') or '',
                'scene_desc': scene_desc,
                'character_desc': character_desc,
                'location': {
                    'id': location_db_id,
                    'name': location_name,
                },
                'props': shot_props,
                'source': {
                    'group_id': group.get('group_id'),
                    'group_name': group_name,
                    'group_type': group_type,
                    'shot_id': shot.get('shot_id'),
                    'shot_number': shot.get('shot_number'),
                    'location_id': shot.get('location_id'),
                    'location_name': location_name,
                    'location_db_id': location_db_id,
                    'narrative_purpose': shot.get('narrative_purpose'),
                    'difficulty_reason': shot.get('difficulty_reason'),
                },
            }
            if spatial_world:
                prompt_payload['spatial_world'] = spatial_world
            if isinstance(shot.get('spatial_layout'), dict):
                prompt_payload['spatial_layout'] = shot.get('spatial_layout')

            scenes.append({
                'title': f"分镜{scene_index}",
                'duration': max(1, _safe_float(shot.get('duration'), 5.0)),
                'difficulty': SceneDifficulty.normalize(shot.get('difficulty')),
                'act_name': act_name,
                'prompt': prompt_payload,
                'video_prompt': video_prompt,
                'video_type': resolved_video_type,
                # 声音同出：数字人分镜 MiniMax 产物已内嵌口型音轨，导出时保留原音轨、跳过 TTS 混音
                'audio_embedded': resolved_video_type == SceneVideoType.DIGITAL_HUMAN,
                # 发布幂等：用稳定 shot_id 做去重 key（见设计文档 §15）
                'source_shot_key': shot.get('shot_id') or f'scene_{scene_index}',
                'video_config': {
                    'shot_type': shot_type,
                    'camera_angle': camera_angle,
                    'camera_movement': shot.get('camera_movement') or '',
                    **presentation_meta,
                },
                'dialogues': dialogues,
            })

    return scenes


def _storyboard_folder_key(item: dict) -> str:
    return f"{item.get('world_id')}:{item.get('episode_number') or 1}"


def _to_iso(value):
    return value.isoformat() if hasattr(value, 'isoformat') else value


def build_storyboard_folders(scripts: list, storyboards: list, world_names: dict) -> list:
    folders = {}

    for script in scripts:
        episode_number = script.get('episode_number') or 1
        item = {
            'folder_key': f"{script.get('world_id')}:{episode_number}",
            'world_id': script.get('world_id'),
            'world_name': world_names.get(script.get('world_id'), ''),
            'episode_number': episode_number,
            'script_id': script.get('id'),
            'script_title': script.get('title') or f"Episode {episode_number}",
            'storyboard_id': None,
            'storyboard_title': None,
            'scene_count': 0,
            'status': 'not_created',
            'update_at': _to_iso(script.get('update_time') or script.get('create_time')),
        }
        folders[item['folder_key']] = item

    for storyboard in storyboards:
        key = _storyboard_folder_key(storyboard)
        episode_number = storyboard.get('episode_number') or 1
        if key not in folders:
            title = storyboard.get('title') or f"Episode {episode_number}"
            folders[key] = {
                'folder_key': key,
                'world_id': storyboard.get('world_id'),
                'world_name': world_names.get(storyboard.get('world_id'), ''),
                'episode_number': episode_number,
                'script_id': storyboard.get('script_id'),
                'script_title': title,
                'storyboard_id': storyboard.get('id'),
                'storyboard_title': title,
                'scene_count': int(storyboard.get('scene_count') or 0),
                'status': 'orphan',
                'update_at': _to_iso(storyboard.get('update_at') or storyboard.get('create_at')),
            }
            continue

        folder = folders[key]
        folder['storyboard_id'] = storyboard.get('id')
        folder['storyboard_title'] = storyboard.get('title')
        folder['scene_count'] = int(storyboard.get('scene_count') or 0)
        folder['status'] = 'created'
        folder['update_at'] = _to_iso(storyboard.get('update_at') or folder.get('update_at'))
        if not folder.get('script_id') and storyboard.get('script_id'):
            folder['script_id'] = storyboard.get('script_id')

    return sorted(
        folders.values(),
        key=lambda item: (
            item.get('world_name') or '',
            item.get('world_id') or 0,
            item.get('episode_number') or 0,
        ),
    )


def collect_storyboard_folder_data(user_id: int, world_id: Optional[int]) -> list:
    scripts_result = ScriptModel.list_by_user(
        user_id=user_id,
        page=1,
        page_size=100,
        order_by='episode_number',
        order_direction='ASC',
        world_id=world_id,
    )
    scripts = scripts_result.get('data', [])
    storyboards = StoryboardModel.list_folders_by_user(user_id=user_id, world_id=world_id)
    worlds_result = WorldModel.list_by_user(user_id=user_id, page=1, page_size=100)
    worlds = worlds_result.get('data', [])
    world_names = {world.get('id'): world.get('name') for world in worlds}
    return build_storyboard_folders(scripts, storyboards, world_names)


async def _ensure_scene_access(scene_id: int, user_id: int, action: str):
    """校验分镜所属故事板的访问权限"""
    scene = await asyncio.to_thread(StoryboardSceneModel.get_by_id, scene_id)
    if not scene:
        return None, JSONResponse(status_code=404, content={'error': '分镜不存在'})
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, scene.storyboard_id)
    if not sb:
        return None, JSONResponse(status_code=404, content={'error': '所属故事板不存在'})
    ensure_resource_access(sb, user_id, action, "故事板")
    return scene, None


async def _ensure_dialogue_access(dialogue_id: int, user_id: int, action: str):
    """校验对话所属分镜→故事板的访问权限"""
    dialogue = await asyncio.to_thread(StoryboardDialogueModel.get_by_id, dialogue_id)
    if not dialogue:
        return None, None, JSONResponse(status_code=404, content={'error': '对话不存在'})
    scene, err = await _ensure_scene_access(dialogue.scene_id, user_id, action)
    if err:
        return None, None, err
    return dialogue, scene, None


class StoryboardVoiceoverSubmissionError(ValueError):
    """Expected voiceover submission validation error."""

    def __init__(self, reason: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.status_code = status_code


def _voiceover_skip(dialogue_id: int, scene_id: Optional[int], reason: str, message: str) -> dict:
    return {
        'dialogue_id': dialogue_id,
        'scene_id': scene_id,
        'reason': reason,
        'message': message,
    }


def submit_storyboard_dialogue_voiceover(
    dialogue_id: int,
    user_id: int,
    config: Optional[dict] = None,
    *,
    strict: bool = True,
) -> dict:
    """Submit one storyboard dialogue voiceover task without waiting for TTS completion."""
    config = config or {}
    constants = StoryboardAudioGenerateConstants
    dialogue = StoryboardDialogueModel.get_by_id(dialogue_id)
    if not dialogue:
        raise StoryboardVoiceoverSubmissionError(
            constants.SKIP_REASON_SUBMIT_FAILED,
            '对话不存在',
            status_code=404,
        )

    scene_id = getattr(dialogue, 'scene_id', None)
    text = str(config.get('text') or getattr(dialogue, 'text', '') or '').strip()
    if not text:
        message = '台词为空，无法生成配音'
        if strict:
            raise StoryboardVoiceoverSubmissionError(constants.SKIP_REASON_EMPTY_TEXT, message)
        return {'success': False, 'skipped': True, **_voiceover_skip(dialogue_id, scene_id, constants.SKIP_REASON_EMPTY_TEXT, message)}

    if config.get('skip_existing') and getattr(dialogue, 'selected_audio_id', None):
        message = '对话已存在选中配音'
        return {'success': False, 'skipped': True, **_voiceover_skip(dialogue_id, scene_id, constants.SKIP_REASON_ALREADY_HAS_SELECTED_AUDIO, message)}

    ref_path = config.get('ref_path')
    character_id = getattr(dialogue, 'character_id', None)
    if not ref_path and character_id:
        character = CharacterModel.get_by_id(character_id)
        ref_path = getattr(character, 'default_voice', None) if character else None

    if not ref_path:
        reason = constants.SKIP_REASON_MISSING_REFERENCE_AUDIO
        message = '角色缺少参考音频'
        if not character_id:
            reason = constants.SKIP_REASON_NARRATION_WITHOUT_VOICE
            message = '旁白缺少默认音色'
        if strict:
            raise StoryboardVoiceoverSubmissionError(reason, message)
        return {'success': False, 'skipped': True, **_voiceover_skip(dialogue_id, scene_id, reason, message)}

    # 四步写库（ai_audio/tasks/dialogue_audio/selected_audio_id）复用原子提交服务，
    # 保证事务内原子一致，不留孤儿记录。事务封闭在 service 内，conn 不外泄。
    # 见 services/storyboard_voiceover_bootstrap_service.py §事务边界与防腐化设计。
    from services.storyboard_voiceover_bootstrap_service import (
        StoryboardVoiceoverBootstrapService,
    )
    transaction_id = str(uuid.uuid4())
    result = StoryboardVoiceoverBootstrapService()._submit_dialogue_voiceover_atomically(
        dialogue_id,
        user_id,
        ref_path=ref_path,
        text=text,
        scene_id=scene_id,
        extra_audio_kwargs={
            'transaction_id': transaction_id,
            'emo_control_method': config.get('emo_control_method'),
            'emo_weight': config.get('emo_weight'),
            'emo_vec': config.get('emo_vec'),
            'emo_text': config.get('emo_text'),
        },
    )
    if result.get('decision') != 'submitted':
        # 已选中有效配音（reused）或失败：保持与原返回结构兼容
        if strict and result.get('decision') == 'failed':
            raise StoryboardVoiceoverSubmissionError(
                result.get('reason') or constants.SKIP_REASON_SUBMIT_FAILED,
                result.get('message') or 'submit failed',
            )
        return {
            'success': False,
            'skipped': True,
            **_voiceover_skip(
                dialogue_id, scene_id,
                result.get('reason') or constants.SKIP_REASON_ALREADY_HAS_SELECTED_AUDIO,
                result.get('message') or '对话已存在选中配音',
            ),
        }

    return {
        'success': True,
        'dialogue_id': dialogue_id,
        'scene_id': scene_id,
        'audio_id': result.get('audio_id'),
        'dialogue_audio_id': result.get('dialogue_audio_id'),
        'status': 'submitted',
    }


async def _auto_submit_storyboard_dialogue_voiceovers(scenes: list, user_id: int) -> dict:
    """Queue dialogue voiceover tasks after script split without blocking for generation.

    ⚠️ 已废弃：自动配音逻辑已迁移到 StoryboardVoiceoverBootstrapService.ensure_for_split_task，
    由 script_split_engine.step_publish 在 publishing 阶段调用（按 script_split_task_id 对账，
    支持崩溃恢复与原子提交）。本函数仅保留向后兼容，不应再被新代码调用。
    """
    constants = StoryboardAudioGenerateConstants
    result = {
        'enabled': bool(constants.ENABLE_AUTO_AFTER_SCRIPT_SPLIT),
        'submitted_count': 0,
        'skipped_count': 0,
        'submitted': [],
        'skipped': [],
    }
    if not result['enabled']:
        return result

    submitted_count = 0
    for scene in scenes or []:
        scene_id = scene.get('id') if isinstance(scene, dict) else None
        for dialogue in (scene.get('dialogues') or []):
            dialogue_id = dialogue.get('id')
            if not dialogue_id:
                continue
            if submitted_count >= constants.MAX_AUTO_SUBMIT_PER_SPLIT:
                result['skipped'].append(_voiceover_skip(
                    int(dialogue_id),
                    scene_id,
                    constants.SKIP_REASON_LIMIT_REACHED,
                    '达到自动提交数量上限',
                ))
                continue
            try:
                item = await asyncio.to_thread(
                    submit_storyboard_dialogue_voiceover,
                    int(dialogue_id),
                    user_id,
                    {'skip_existing': True},
                    strict=False,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to auto-submit storyboard dialogue voiceover dialogue_id=%s: %s",
                    dialogue_id,
                    exc,
                    exc_info=True,
                )
                item = {
                    'success': False,
                    'skipped': True,
                    **_voiceover_skip(
                        int(dialogue_id),
                        scene_id,
                        constants.SKIP_REASON_SUBMIT_FAILED,
                        str(exc),
                    ),
                }
            if item.get('success'):
                result['submitted'].append(item)
                submitted_count += 1
            else:
                result['skipped'].append({
                    'dialogue_id': item.get('dialogue_id', dialogue_id),
                    'scene_id': item.get('scene_id', scene_id),
                    'reason': item.get('reason') or constants.SKIP_REASON_SUBMIT_FAILED,
                    'message': item.get('message') or '',
                })

    result['submitted_count'] = len(result['submitted'])
    result['skipped_count'] = len(result['skipped'])
    return result


async def _resolve_sort_value(get_by_id_fn, entity_id: Optional[int]) -> Optional[float]:
    """取某记录的 sort_order；entity_id 为 None 返回 None（表示边界）"""
    if entity_id is None:
        return None
    entity = await asyncio.to_thread(get_by_id_fn, entity_id)
    return float(entity.sort_order) if entity else None


async def _compute_insert_sort(
    rebalance_fn,
    owner_id: int,
    get_by_id_fn,
    prev_id: Optional[int],
    next_id: Optional[int],
) -> float:
    """
    浮点二分：计算在 prev_id 与 next_id 之间插入的 sort_order。
    精度耗尽时自动 rebalance(owner_id) 后重查 prev/next 重算。
    """
    prev_sort = await _resolve_sort_value(get_by_id_fn, prev_id)
    next_sort = await _resolve_sort_value(get_by_id_fn, next_id)
    mid = compute_sort_between(prev_sort, next_sort)
    if is_precision_exhausted(mid, prev_sort, next_sort):
        await asyncio.to_thread(rebalance_fn, owner_id)
        prev_sort = await _resolve_sort_value(get_by_id_fn, prev_id)
        next_sort = await _resolve_sort_value(get_by_id_fn, next_id)
        mid = compute_sort_between(prev_sort, next_sort)
    return mid


async def _asset_task_info(scene, asset_type: str) -> Optional[dict]:
    """从 scene 的选中指针取 asset → ai_tools 的状态/结果"""
    ptr_map = {
        'first_frame': scene.selected_first_frame_id,
        'last_frame': scene.selected_last_frame_id,
        'video': scene.selected_video_id,
    }
    asset_id = ptr_map.get(asset_type)
    if not asset_id:
        return None
    asset = await asyncio.to_thread(StoryboardSceneAssetModel.get_by_id, asset_id)
    if not asset:
        return None
    info = {
        'asset_id': asset.id,
        'asset_type': asset.asset_type,
        'result_url': asset.result_url,
        'status': None,
        'error': None,
    }
    if asset.ai_tool_id:
        tool = await asyncio.to_thread(AIToolsModel.get_by_id, asset.ai_tool_id)
        if tool:
            info['status'] = tool.status
            info['error'] = tool.message
            # 仅在 asset 自身没有 result_url 时，才用 ai_tool.result_url 兜底。
            # 宫格拆分场景下，多个 asset 共享同一个 ai_tool，而 ai_tool.result_url
            # 存的是整张宫格图（如 upload/storyboard/temp/xxx.png），asset.result_url
            # 才是拆分后的单格图（upload/storyboard/first_frame/xxx.png）。
            # 无条件覆盖会导致前端轮询时把单格图回退成宫格图。
            if tool.result_url and not info.get('result_url'):
                info['result_url'] = tool.result_url
    return info


def _enrich_scene_asset_result_urls(assets: list) -> list:
    """为候选资产补全 ai_tools 中的任务结果 URL/状态。需在 asyncio.to_thread 中调用。"""
    enriched = []
    for asset in assets or []:
        item = asset.to_dict() if hasattr(asset, 'to_dict') else dict(asset)
        ai_tool_id = item.get('ai_tool_id')
        if not ai_tool_id:
            item['result_url'] = _normalize_storyboard_upload_browser_url(item.get('result_url'))
            enriched.append(item)
            continue

        try:
            tool = AIToolsModel.get_by_id(int(ai_tool_id))
        except Exception as exc:
            logger.warning(f"Failed to enrich storyboard scene asset {item.get('id')} from ai_tools {ai_tool_id}: {exc}")
            enriched.append(item)
            continue

        if not tool:
            enriched.append(item)
            continue

        tool_info = tool.to_dict() if hasattr(tool, 'to_dict') else {}
        # 仅补全真正的任务产出 URL。image_path / video_path 是输入参考图/视频路径
        # （图生图时多为逗号拼接的多张参考图），不能当作候选缩略图 result_url，
        # 否则生成中的资产会渲染出无法显示的破图。
        result_url = (
            tool_info.get('result_url')
            or getattr(tool, 'result_url', None)
        )
        if result_url and not item.get('result_url'):
            item['result_url'] = result_url

        for key in ('status', 'message', 'project_id'):
            value = tool_info.get(key, getattr(tool, key, None))
            if value is not None and item.get(key) in (None, ''):
                item[key] = value

        enriched.append(item)
    return enriched


def _normalize_storyboard_upload_browser_url(url: Any) -> Any:
    """把历史手工上传的本机绝对地址转换为浏览器可访问的同源地址。"""
    text = str(url or '').strip()
    if not text:
        return url
    parsed = urlparse(text)
    if (
        parsed.hostname in {'localhost', '127.0.0.1', '0.0.0.0', '::1'}
        and parsed.path.startswith('/upload/storyboard/')
    ):
        suffix = f'?{parsed.query}' if parsed.query else ''
        return f'{parsed.path}{suffix}'
    return text


async def _attach_dialogues(scenes: list) -> list:
    """为每个分镜附加其对话列表（供前端直接渲染）"""
    for sc in scenes:
        sc['dialogues'] = await asyncio.to_thread(
            StoryboardDialogueModel.list_by_scene, sc['id']
        )
    return scenes


def _enrich_scene_location_props(scenes: list) -> list:
    """后端返回补全：从 prompt_json 提取 location/props 到顶层，方便前端显示当前分镜的场景/道具（带头像）"""
    for sc in scenes:
        pj = sc.get('prompt_json') or {}
        if isinstance(pj, str):
            try:
                pj = json.loads(pj)
            except Exception:
                pj = {}
        if not sc.get('location'):
            loc = pj.get('location') or (pj.get('source') and {
                'id': pj['source'].get('location_db_id'),
                'name': pj['source'].get('location_name'),
            } or None)
            if loc:
                sc['location'] = loc
        if not sc.get('props'):
            pr = pj.get('props')
            if pr:
                sc['props'] = pr
    return scenes


def _compose_image_prompt(scene) -> str:
    """从 scene.prompt_json 组合图片提示词（视角/风格/场景/角色描述）"""
    prompt = scene.prompt_json
    if isinstance(prompt, str):
        try:
            prompt = json.loads(prompt)
        except Exception:
            prompt = {}
    if not isinstance(prompt, dict):
        return ''
    parts = [prompt.get('perspective'), prompt.get('style'),
             prompt.get('scene_desc'), prompt.get('character_desc')]
    return '，'.join([p for p in parts if p])


def _scene_prompt_dict(scene) -> Dict[str, Any]:
    prompt = scene.prompt_json
    if isinstance(prompt, str):
        try:
            prompt = json.loads(prompt)
        except Exception:
            prompt = {}
    return prompt if isinstance(prompt, dict) else {}


def _storyboard_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _normalize_storyboard_agent_reference_url(url: Any) -> str:
    """Return one HTTP(S) image URL suitable for Agent image inputs."""
    text = str(url or "").strip().replace("\\", "/")
    if not text or "," in text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    relative = text.lstrip("/")
    if not relative.startswith("upload/"):
        return ""
    try:
        host = str((get_config().get("server", {}) or {}).get("host") or "").strip()
    except Exception:
        host = ""
    return f"{host.rstrip('/')}/{relative}" if host else ""


def _build_storyboard_spatial_constraints(prompt_json: Any) -> Dict[str, Any]:
    """Extract the current shot's actionable spatial constraints for the Agent LLM."""
    if isinstance(prompt_json, str):
        try:
            prompt_json = json.loads(prompt_json)
        except Exception:
            prompt_json = {}
    if not isinstance(prompt_json, dict):
        return {}
    spatial = prompt_json.get("spatial_layout")
    if not isinstance(spatial, dict):
        return {}

    refs = spatial.get("space_unit_refs")
    refs = refs if isinstance(refs, list) else []
    ref_keys = {str(ref) for ref in refs if ref not in (None, "")}
    spatial_world = prompt_json.get("spatial_world")
    world_units = spatial_world.get("space_units") if isinstance(spatial_world, dict) else []
    active_units = []
    for unit in world_units if isinstance(world_units, list) else []:
        if not isinstance(unit, dict):
            continue
        unit_id = unit.get("space_unit_id") or unit.get("id")
        if not ref_keys or str(unit_id) in ref_keys:
            active_units.append(unit)

    spatial_context = build_spatial_prompt_context(
        spatial,
        spatial_world if isinstance(spatial_world, dict) else None,
    )
    camera_anchor = spatial.get("camera_anchor") if isinstance(spatial.get("camera_anchor"), dict) else {}
    raw_camera_pose = spatial.get("camera_pose")
    if not isinstance(raw_camera_pose, dict):
        raw_camera_pose = camera_anchor.get("camera_pose") if isinstance(camera_anchor.get("camera_pose"), dict) else {}

    continuity = spatial.get("continuity") if isinstance(spatial.get("continuity"), dict) else {}
    anchor_keys = (
        "description", "camera_position", "shooting_direction", "relative_to_character",
        "view_direction", "screen_axis_mapping", "screen_composition",
    )
    compact_anchor = {
        key: camera_anchor.get(key)
        for key in anchor_keys
        if camera_anchor.get(key) not in (None, "")
    }
    return {
        "schema_version": spatial.get("schema_version") or 1,
        "space_unit_refs": refs,
        "space_units": active_units,
        "camera_pose": spatial_context.get("camera_pose") or raw_camera_pose,
        "camera_anchor": compact_anchor,
        "visible_entities": spatial_context.get("visible_entities") or [],
        "continuity_only_entities": spatial_context.get("hidden_entities") or [],
        "continuity": continuity,
    }


def _scene_character_positions(scene: Any) -> Dict[int, Dict[str, str]]:
    """提取当前镜头可见角色的画面位置映射（供视频模式标注说话角色位置）。

    仅从 prompt_json.spatial_layout 解析 visible_entities，构建
    {character_db_id(int): {name, screen_position, slot}} 映射。
    关联键为 entity["db_id"]（=character_db_id），与 storyboard_dialogue.character_id 对应。
    解析失败或缺数据时返回空 dict，调用方按"静默降级"处理（只显示角色名）。
    不渲染原空间约束大 JSON 段，仅做轻量位置提取。
    """
    prompt_json = _scene_prompt_dict(scene)
    spatial = prompt_json.get("spatial_layout")
    if not isinstance(spatial, dict):
        return {}
    spatial_world = prompt_json.get("spatial_world")
    try:
        spatial_context = build_spatial_prompt_context(
            spatial,
            spatial_world if isinstance(spatial_world, dict) else None,
        )
    except Exception:
        return {}
    position_map: Dict[int, Dict[str, str]] = {}
    for entity in (spatial_context.get("visible_entities") or []):
        if not isinstance(entity, dict):
            continue
        # 仅关注角色实体（occupant_type 缺省视为角色）
        if str(entity.get("occupant_type") or "character").lower() not in ("character", ""):
            continue
        raw_db_id = entity.get("db_id") or entity.get("character_db_id")
        try:
            db_id = int(raw_db_id) if raw_db_id not in (None, "") else None
        except (TypeError, ValueError):
            db_id = None
        if db_id is None:
            continue
        # 屏幕位置优先用投影后的精确位置，回退原始位置
        screen_position = (
            entity.get("derived_screen_position")
            or entity.get("screen_position")
            or ""
        )
        position_map[db_id] = {
            "name": str(entity.get("name") or "").strip(),
            "screen_position": str(screen_position or "").strip(),
            "slot": str(entity.get("slot") or "").strip(),
        }
    return position_map


def _format_scene_dialogues(
    dialogues: Optional[List[Dict[str, Any]]],
    characters: Optional[List[Dict[str, Any]]],
    position_map: Optional[Dict[int, Dict[str, str]]] = None,
) -> str:
    """格式化分镜对话段落（供视频模式提示词）。

    逐条列出台词，标注说话角色名与画面位置；位置命中 position_map 才标注，
    未命中/缺数据静默省略（静默降级）。旁白（character_id NULL）单独处理。
    无对话返回占位文本。
    """
    characters = characters or []
    position_map = position_map or {}
    # 角色 id -> name 映射
    char_name_map: Dict[int, str] = {}
    for ch in characters:
        if not isinstance(ch, dict):
            continue
        ch_id = ch.get("id")
        try:
            ch_id_int = int(ch_id) if ch_id not in (None, "") else None
        except (TypeError, ValueError):
            ch_id_int = None
        if ch_id_int is not None and ch.get("name"):
            char_name_map[ch_id_int] = str(ch["name"]).strip()

    dialogues = dialogues or []
    if not dialogues:
        return "（无对话）"

    lines: List[str] = []
    for idx, d in enumerate(dialogues, start=1):
        if not isinstance(d, dict):
            continue
        text = (d.get("text") or "").strip()
        raw_char_id = d.get("character_id")
        try:
            char_id = int(raw_char_id) if raw_char_id not in (None, "") else None
        except (TypeError, ValueError):
            char_id = None
        if char_id is None:
            speaker = "旁白"
        else:
            speaker = char_name_map.get(char_id) or f"角色{char_id}"
            pos = position_map.get(char_id)
            if pos and pos.get("screen_position"):
                speaker = f"{speaker} · {pos['screen_position']}"
        lines.append(f"{idx}. [{speaker}] {text}")
    if not lines:
        return "（无对话）"
    return "\n".join(lines)


def _storyboard_neighbor_summary(scene: Any, direction: str) -> Dict[str, Any]:
    prompt = _storyboard_value(scene, "prompt_json", {}) or {}
    if isinstance(prompt, str):
        try:
            prompt = json.loads(prompt)
        except Exception:
            prompt = {}
    prompt = prompt if isinstance(prompt, dict) else {}
    prompt_parts = [
        prompt.get("scene_desc"),
        prompt.get("character_desc"),
    ]
    return {
        "scene_id": _storyboard_value(scene, "id"),
        "direction": direction,
        "title": _storyboard_value(scene, "title", "") or "",
        "first_frame_url": _normalize_storyboard_agent_reference_url(
            _storyboard_value(scene, "first_frame_url", "")
        ),
        "prompt_summary": "\n".join(str(part).strip() for part in prompt_parts if str(part or "").strip()),
        "spatial_constraints": _build_storyboard_spatial_constraints(prompt),
    }


def _load_storyboard_agent_neighbors(scene: Any) -> Dict[str, Optional[Dict[str, Any]]]:
    """Load only the immediate previous/next storyboard scenes in stable display order."""
    storyboard_id = _storyboard_value(scene, "storyboard_id")
    scene_id = _storyboard_value(scene, "id")
    if not storyboard_id or not scene_id:
        return {"previous": None, "next": None}
    scenes = StoryboardSceneModel.list_by_storyboard(int(storyboard_id)) or []
    scenes = sorted(
        scenes,
        key=lambda item: (
            float(_storyboard_value(item, "sort_order", 0) or 0),
            int(_storyboard_value(item, "id", 0) or 0),
        ),
    )
    index = next(
        (idx for idx, item in enumerate(scenes) if int(_storyboard_value(item, "id", 0) or 0) == int(scene_id)),
        None,
    )
    if index is None:
        return {"previous": None, "next": None}
    previous = scenes[index - 1] if index > 0 else None
    next_scene = scenes[index + 1] if index + 1 < len(scenes) else None
    return {
        "previous": _storyboard_neighbor_summary(previous, "previous") if previous else None,
        "next": _storyboard_neighbor_summary(next_scene, "next") if next_scene else None,
    }


def _append_storyboard_agent_frame_reference(
    items: List[Dict[str, Any]],
    url: Any,
    *,
    source_type: str,
    title: str = "",
) -> bool:
    """Append one current/neighbor frame to the ordered reference manifest."""
    normalized_url = _normalize_storyboard_agent_reference_url(url)
    if not normalized_url:
        return False
    existing_urls = {
        _normalize_storyboard_agent_reference_url(item.get("url"))
        for item in items
        if isinstance(item, dict)
    }
    if normalized_url in existing_urls:
        return False

    metadata = {
        "current_frame": ("当前分镜已有首帧", "当前分镜已有首帧，仅作为待修改画面"),
        "previous_frame": ("前一分镜首帧", "前一分镜首帧，仅用于上游连续性"),
        "next_frame": ("后一分镜首帧", "后一分镜首帧，仅用于下游连续性"),
    }
    item_type, label = metadata.get(source_type, ("分镜首帧", "分镜首帧连续性参考"))
    items.append({
        "url": normalized_url,
        "type": item_type,
        "name": str(title or "").strip(),
        "label": label,
        "source_type": source_type,
    })
    return True


def _append_storyboard_agent_neighbor_references(
    items: List[Dict[str, Any]],
    neighbors: Optional[Dict[str, Any]],
) -> None:
    neighbors = neighbors if isinstance(neighbors, dict) else {}
    for direction, source_type in (("previous", "previous_frame"), ("next", "next_frame")):
        neighbor = neighbors.get(direction)
        if not isinstance(neighbor, dict):
            continue
        _append_storyboard_agent_frame_reference(
            items,
            neighbor.get("first_frame_url"),
            source_type=source_type,
            title=str(neighbor.get("title") or ""),
        )


def _build_storyboard_agent_image_references(
    *,
    base_reference_images: Optional[List[str]],
    base_reference_items: Optional[List[Dict[str, Any]]],
    current_first_frame_url: Any,
    current_title: str,
    neighbors: Optional[Dict[str, Any]],
    user_reference_urls: Optional[List[str]],
) -> tuple[List[str], List[Dict[str, Any]]]:
    """Build one aligned image-reference manifest without mutating service output."""
    items: List[Dict[str, Any]] = []
    for source_item in base_reference_items or []:
        if not isinstance(source_item, dict):
            continue
        normalized_url = _normalize_storyboard_agent_reference_url(source_item.get("url"))
        if not normalized_url or normalized_url in reference_urls(items):
            continue
        item = dict(source_item)
        item["url"] = normalized_url
        items.append(item)

    for url in base_reference_images or []:
        normalized_url = _normalize_storyboard_agent_reference_url(url)
        if not normalized_url or normalized_url in reference_urls(items):
            continue
        items.append({
            "url": normalized_url,
            "type": "参考图",
            "name": "",
            "label": "当前分镜资产参考图",
        })

    _append_storyboard_agent_frame_reference(
        items,
        current_first_frame_url,
        source_type="current_frame",
        title=current_title,
    )
    _append_storyboard_agent_neighbor_references(items, neighbors)

    user_index = 0
    for url in user_reference_urls or []:
        normalized_url = _normalize_storyboard_agent_reference_url(url)
        if not normalized_url or normalized_url in reference_urls(items):
            continue
        user_index += 1
        items.append({
            "url": normalized_url,
            "label": f"用户上传参考图{user_index}",
            "type": "参考图",
            "name": "",
            "source_type": "user_reference",
        })
    return reference_urls(items), items


def _normalize_auth_token(token: Optional[str]) -> str:
    token = (token or '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    return token


def _storyboard_scene_chat_session_id(scene_id: int) -> str:
    return f"storyboard-scene-{scene_id}"


def _record_storyboard_agent_message(
    scene_id: int,
    role: str,
    content: Any,
    task_id: Optional[str] = None,
    message_type: str = "text",
    visibility: str = "both",
    source: str = "storyboard_agent",
) -> Optional[Dict[str, Any]]:
    from model.chat_messages import ChatMessagesModel

    message_id = str(uuid.uuid4())
    entity = ChatMessagesModel.create(
        message_id=message_id,
        session_id=_storyboard_scene_chat_session_id(scene_id),
        role=role,
        message_type=message_type,
        content=json.dumps(content if content is not None else "", ensure_ascii=False),
        idempotency_key=f"storyboard_scene:{scene_id}:{task_id or message_id}:{role}:{source}",
        source=source,
        agent_scope="storyboard_scene",
        context_state="active",
        task_id=task_id,
        agent_id="storyboard_image_agent",
        visibility=visibility,
    )
    return entity.to_frontend_dict() if entity else None


def _list_storyboard_agent_messages(scene_id: int, for_context: bool = False) -> List[Dict[str, Any]]:
    from model.chat_messages import ChatMessagesModel

    entities = ChatMessagesModel.list_for_session(
        _storyboard_scene_chat_session_id(scene_id),
        agent_scope="storyboard_scene",
        visibility=["both", "llm"] if for_context else ["both", "user", "llm"],
        exclude_context_state=["deleted"],
        exclude_message_types=["tool_definitions"],
        limit=100,
    )
    messages = []
    for entity in entities:
        data = entity.to_frontend_dict()
        content = data.get("content")
        if isinstance(content, dict):
            content = content.get("content") or content.get("message") or json.dumps(content, ensure_ascii=False)
        if for_context:
            if entity.role not in ("user", "assistant"):
                continue
            messages.append({"role": entity.role, "content": str(content or "")})
        else:
            data["content"] = content or ""
            messages.append(data)
    return messages


def _build_storyboard_agent_message(
    user_message: str,
    scene,
    storyboard,
    first_frame_url: Optional[str] = None,
    reference_images: Optional[List[str]] = None,
    reference_image_items: Optional[List[Dict[str, Any]]] = None,
    generation_target: str = "image",
    image_mode: Optional[str] = None,
    video_input_urls: Optional[List[str]] = None,
    video_duration_seconds: Optional[int] = None,
    video_resolution: Optional[str] = None,
    clip_to_audio_duration: Optional[bool] = None,
    video_model_name: Optional[str] = None,
    video_task_id: Optional[int] = None,
    spatial_constraints: Optional[Dict[str, Any]] = None,
    neighbor_contexts: Optional[Dict[str, Any]] = None,
    dialogues: Optional[List[Dict[str, Any]]] = None,
    characters: Optional[List[Dict[str, Any]]] = None,
) -> str:
    is_video = generation_target == "video"
    prompt = _scene_prompt_dict(scene)
    first_frame_line = first_frame_url or "无"
    reference_images = reference_images or []
    reference_image_items = reference_image_items or []
    # 以下段落仅 image 模式渲染，video 模式精简掉，故 video 模式无需序列化
    spatial_constraints = spatial_constraints or _build_storyboard_spatial_constraints(prompt)
    neighbor_contexts = neighbor_contexts if isinstance(neighbor_contexts, dict) else {}
    prompt_json = "" if is_video else json.dumps(prompt, ensure_ascii=False, indent=2)
    spatial_constraints_json = "" if is_video else json.dumps(spatial_constraints, ensure_ascii=False, indent=2)
    neighbor_contexts_json = "" if is_video else json.dumps(neighbor_contexts, ensure_ascii=False, indent=2)
    video_input_urls = [str(u).strip() for u in (video_input_urls or []) if str(u).strip()]
    image_mode = (image_mode or 'first_last_frame').strip().lower()
    if image_mode not in ('first_last_frame', 'multi_reference', 'first_last_with_ref'):
        image_mode = 'first_last_frame'
    reference_legend = build_reference_legend(reference_image_items)
    if reference_image_items:
        reference_lines = [
            f"- 图{idx}：{item.get('label') or (str(item.get('type') or '参考图') + ('：' + str(item.get('name')) if item.get('name') else '')) or item.get('url')}，URL：{item.get('url')}"
            for idx, item in enumerate(reference_image_items, start=1)
        ]
    else:
        reference_lines = [f"- 图{idx}：{url}" for idx, url in enumerate(reference_images, start=1)]
    reference_block = "\n".join(reference_lines) if reference_lines else "无"
    if generation_target == "video":
        is_digital_human = str(getattr(scene, 'video_type', '') or '') == SceneVideoType.DIGITAL_HUMAN
        duration_line = str(int(video_duration_seconds)) if video_duration_seconds else str(scene.duration or 5)
        resolution_line = video_resolution or '模型默认'
        clip_line = '开启（导出时裁到配音时长）' if clip_to_audio_duration else '关闭（导出使用完整视频）'
        if is_digital_human:
            target_intro = "请基于当前分镜视频提示词与用户要求，生成该分镜的 MiniMax H3 数字人对口型视频。"
            video_input_block = "系统会从当前分镜解析角色图和已完成的配音，无需也不得由模型传入 URL。"
            tool_instruction = (
                "本次目标是生成数字人对口型视频（MiniMax H3），必须调用 generate_digital_human。"
                "不得调用 image_to_video、generate_text_to_video 或任何图片生成工具。"
                "系统会从当前分镜解析角色图和已完成的配音，严禁捏造或传入图片、音频 URL。"
            )
        elif video_input_urls:
            target_intro = "请基于当前分镜画面提示词、视频提示词与用户要求，生成该分镜视频。"
            if image_mode == 'multi_reference':
                mode_desc = "全能参考模式（multi_reference）：【图生视频输入图】中的全部 URL 均为参考图，按顺序用英文逗号拼接为 image_urls，image_mode 必须传 multi_reference。"
                slot_labels = [f"- 图{idx}（参考）：{url}" for idx, url in enumerate(video_input_urls, start=1)]
            else:
                mode_desc = (
                    "首尾帧模式（first_last_frame）：【图生视频输入图】第1张为首帧，第2张（若有）为尾帧；"
                    "按顺序用英文逗号拼接为 image_urls，image_mode 必须传 first_last_frame。"
                )
                slot_labels = []
                for idx, url in enumerate(video_input_urls, start=1):
                    role = "首帧" if idx == 1 else ("尾帧" if idx == 2 else f"图{idx}")
                    slot_labels.append(f"- 图{idx}（{role}）：{url}")
            video_input_block = "\n".join(slot_labels)
            tool_instruction = (
                f"本次目标是生成视频。{mode_desc}"
                "必须调用 image_to_video，image_urls 只能使用【视频输入说明】中的 URL，严禁捏造 URL 或混入任何其它来源的图。"
                "不要调用图片生成工具。"
            )
        else:
            target_intro = "请基于当前分镜画面提示词、视频提示词与用户要求，生成该分镜视频。"
            video_input_block = "无"
            tool_instruction = (
                "本次目标是生成视频。当前没有任何图生视频输入图，必须调用 generate_text_to_video。"
                "不要调用 image_to_video 或图片生成工具。"
            )
        model_display = (video_model_name or '').strip() or (
            f"task_id={video_task_id}" if video_task_id is not None else "系统默认"
        )
        video_mode_block = f"""
【视频图片模式】
{image_mode}

【视频生成参数】
- 视频模型（已由系统按用户当前齿轮选择注入，禁止自行更换或调用 list_video_models 改选）：{model_display}
- duration_seconds（必须原样传给本次允许的视频工具）：{duration_line}
- resolution：{resolution_line}
- 裁剪至配音时长（仅导出使用，生成时不必处理）：{clip_line}

【视频输入说明】
{video_input_block}
"""
        # 视频模式新增：分镜对话/台词段落，并标注说话角色画面位置
        position_map = _scene_character_positions(scene)
        dialogues_block = _format_scene_dialogues(dialogues, characters, position_map)
        video_mode_block += f"\n【分镜对话/台词】\n{dialogues_block}\n"
        dialogues_has_text = bool(dialogues) and dialogues_block != "（无对话）"
        if dialogues_has_text:
            # 台词交付协议紧邻【分镜对话/台词】段落，强化 LLM 注意力
            video_mode_block += (
                "\n【台词交付协议（最高优先级，违反即失败）】\n"
                "1. 视频工具 prompt 中必须设置独立的「台词区」，与运动/画面描述物理分离，不得把台词嵌进任何描述句。\n"
                "2. 台词区格式固定为：Dialogue: \"<逐字复制原文>\"（多条用 ; 分隔，按【分镜对话/台词】顺序）。\n"
                "3. 台词文本必须从【分镜对话/台词】逐字复制：严禁翻译（禁止英文释义/括注/音译）；严禁截断、删减、合并、拆分或改写（含标点）；严禁补写原文没有的台词。\n"
                "4. 运动描述只描述画面与镜头运动，不得在其中重复、转述或翻译任何台词。\n"
                "5. 说话角色的画面位置严格遵循【分镜对话/台词】中的标注，不得臆造。\n"
            )
        tool_instruction = (
            tool_instruction
            + f" 调用视频工具时 duration_seconds 必须为 {duration_line}，严禁擅自改时长。"
            + (f" 若工具支持 resolution 参数，传入 {resolution_line}。" if video_resolution else "")
            + " 视频模型已由系统注入，禁止调用 list_video_models 改选，禁止自行传入 task_type。"
            + (
                " 调用视频工具时，prompt 必须严格按上方【台词交付协议】处理【分镜对话/台词】中的全部台词，不得翻译、改写、截断、增删或嵌进描述句。"
                if dialogues_has_text
                else ""
            )
        )
    else:
        video_mode_block = ""
        target_intro = "请基于当前分镜画面提示词，与用户对话并生成/编辑该分镜首帧。"
        tool_instruction = (
            "当前分镜有参考图，必须调用 edit_image，并把【参考图清单】中的 URL 按顺序用英文逗号拼接为 image_url；"
            "不要询问用户选择文生图还是图生图。"
            if reference_images
            else "当前分镜没有可用参考图，调用 generate_text_to_image。"
        )
    current_scene_block = f"""【当前分镜】
- 标题：{scene.title or ''}
- 时长：{scene.duration or 5} 秒
- 全局画风：{getattr(storyboard, 'style', '') or ''}
- 构图倾向：{getattr(storyboard, 'composition_preference', '') or ''}
- 画幅比例：{getattr(storyboard, 'workflow_ratio', '') or ''}
- 已有首帧 URL：{first_frame_line}"""

    if is_video:
        # 视频模式：精简提示词，仅保留用户要求、当前分镜、视频参数与对话台词。
        # 删除参考图清单/说明、空间硬约束、相邻分镜、prompt_json（画面提示词）等冗余段落。
        # 视频模式额外去掉「标题」子项（视频模型不需要标题）。
        video_scene_block = f"""【当前分镜】
- 时长：{scene.duration or 5} 秒
- 全局画风：{getattr(storyboard, 'style', '') or ''}
- 构图倾向：{getattr(storyboard, 'composition_preference', '') or ''}
- 画幅比例：{getattr(storyboard, 'workflow_ratio', '') or ''}
- 已有首帧 URL：{first_frame_line}"""
        return f"""{target_intro}

【用户要求】
{user_message}

{video_scene_block}
{video_mode_block}
请严格围绕当前分镜创作，保留角色、场景、道具一致性，并结合全局画风、构图倾向和画幅比例。{tool_instruction} 提交成功后返回包含 project_ids 的工作总结。"""

    # image 模式：保持原有全部段落与行为不变
    return f"""{target_intro}

【用户要求】
{user_message}

{current_scene_block}
{video_mode_block}
【参考图清单】
{reference_block}

【参考图说明】
{reference_legend or '无'}

【当前分镜空间硬约束】
```json
{spatial_constraints_json}
```

空间约束执行规则：物理锚点、容器槽位和三维位置优先于画面左右描述；机位或景别变化不代表角色发生了位移。只有 visible、partial 实体可以写成当前画面可见内容；offscreen、occluded 实体只能用于连续性推理，禁止写成当前画面可见主体。

【相邻分镜连续性上下文】
```json
{neighbor_contexts_json}
```

相邻分镜仅用于校验人物、服装、场景、道具状态和空间连续性。前一分镜提供上游状态，后一分镜只提供下游校验，禁止提前复制后一分镜才发生的动作或状态。相邻分镜不能覆盖当前镜头的动作、机位、物理位置和可见实体。

【当前分镜 prompt_json】
```json
{prompt_json}
```

请严格围绕当前分镜创作，保留角色、场景、道具一致性，并结合全局画风、构图倾向和画幅比例。{tool_instruction} 如果调用 edit_image，edit_image.prompt 末尾必须原样追加【参考图说明】内容，例如“参考图说明：图1是角色：布冯。图2是场景：布冯的房间。”普通视频分镜如果调用 image_to_video，也要在视频提示词末尾追加同样的参考图说明。不要加入未出现在当前画面提示词或视频提示词中的角色/道具参考图。提交成功后返回包含 project_ids 的工作总结。"""


class StoryboardImageAgentRunner:
    """Adapter so TaskManager can run storyboard-image ExpertAgent as a task."""

    agent_id = "storyboard_image_agent"

    def __init__(
        self,
        scene_id: int,
        scene_context: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        generation_target: str = "image",
        video_type: str = SceneVideoType.VIDEO,
        video_preferences: Optional[Dict[str, Any]] = None,
        style: str = "",
        composition_preference: str = "",
        generation_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self.scene_id = scene_id
        self.scene_context = scene_context
        self.conversation_history = conversation_history or []
        self.generation_target = generation_target if generation_target == "video" else "image"
        self.video_type = str(video_type or SceneVideoType.VIDEO)
        self.video_preferences = dict(video_preferences or {})
        self.style = style or ""
        self.composition_preference = composition_preference or ""
        self.generation_snapshots = dict(generation_snapshots or {})

    @staticmethod
    def _resolve_storyboard_agent_model(default_model: str, model_id: Optional[int]) -> str:
        if not model_id:
            return default_model
        try:
            from model.model import ModelModel
            task_model = ModelModel.get_by_id(int(model_id))
            if task_model and task_model.model_name:
                return task_model.model_name
        except Exception as e:
            logger.warning(f"Failed to resolve storyboard agent model name for model_id={model_id}: {e}")
        return default_model

    def execute(self, task, session_data: Dict[str, Any]) -> Dict[str, Any]:
        from api.script_writer import file_manager, tool_executor, agents_config, task_manager
        from script_writer_core.agents.expert_agent import ExpertAgent
        from services.storyboard_agent_image_tool import StoryboardAgentImageToolExecutor
        from services.storyboard_agent_video_tool import (
            StoryboardAgentVideoToolExecutor,
            resolve_storyboard_agent_allowed_tools,
        )

        config = dict(agents_config.get("expert_agents", {}).get("storyboard-image") or {})
        allowed_tools = config.get("allowed_tools") or [
            "generate_text_to_image",
            "edit_image",
            "get_text_to_image_model_info",
            "get_user_computing_power",
            "list_video_models",
            "ask_user",
        ]
        allowed_tools = resolve_storyboard_agent_allowed_tools(
            allowed_tools,
            generation_target=self.generation_target,
            video_type=self.video_type,
        )
        persisted_context = getattr(task, 'execution_context_json', None) or {}
        persisted_snapshots = persisted_context.get('generation_snapshots') or {}
        generation_snapshots = dict(persisted_snapshots or self.generation_snapshots)
        active_slot = persisted_context.get('active_generation_slot')
        active_snapshot = generation_snapshots.get(active_slot) if active_slot else None
        if not active_snapshot:
            expected_type = 'video.' if self.generation_target == 'video' else 'image.'
            active_snapshot = next(
                (value for key, value in generation_snapshots.items() if key.startswith(expected_type)),
                None,
            )
        agent_tool_executor = tool_executor
        if self.generation_target == "image":
            snapshot_ratio = (active_snapshot or {}).get('ratio') if active_snapshot else None
            # task.image_urls / execution_context.reference_image_items 在 ai-chat 创建时填入；
            # 工具层强制注入，避免 LLM 调用 edit_image 时漏传多角色参考 URL，并保持图例与 URL 对齐。
            exec_ctx = getattr(task, 'execution_context_json', None) or {}
            if isinstance(exec_ctx, str):
                try:
                    exec_ctx = json.loads(exec_ctx)
                except Exception:
                    exec_ctx = {}
            if not isinstance(exec_ctx, dict):
                exec_ctx = {}
            forced_reference_items = [
                dict(item)
                for item in (exec_ctx.get('reference_image_items') or [])
                if isinstance(item, dict) and str(item.get('url') or '').strip()
            ]
            forced_reference_urls = [
                str(url).strip()
                for url in (getattr(task, 'image_urls', None) or [])
                if str(url or '').strip()
            ]
            if not forced_reference_urls and forced_reference_items:
                forced_reference_urls = [
                    str(item.get('url')).strip()
                    for item in forced_reference_items
                    if str(item.get('url') or '').strip()
                ]
            agent_tool_executor = StoryboardAgentImageToolExecutor(
                tool_executor,
                style=self.style,
                composition_preference=self.composition_preference,
                generation_snapshot=active_snapshot,
                workflow_ratio=str(snapshot_ratio or '').strip(),
                forced_reference_urls=forced_reference_urls,
                forced_reference_items=forced_reference_items,
            )
        else:
            effective_video_preferences = dict(self.video_preferences)
            if active_snapshot:
                effective_video_preferences.update(active_snapshot)
            agent_tool_executor = StoryboardAgentVideoToolExecutor(
                tool_executor,
                scene_id=self.scene_id,
                video_preferences=effective_video_preferences,
            )
        model = self._resolve_storyboard_agent_model(
            config.get("model") or "gemini/gemini-3-flash-preview",
            task.model_id,
        )
        # 视频模式使用独立的 storyboard-video skill（剔除图片专属的 edit_image/空间约束/邻镜等冗余规则），
        # 图片模式继续使用 storyboard-image skill。
        skill_name = "storyboard-video" if self.generation_target == "video" else "storyboard-image"
        expert = ExpertAgent(
            skill_names=[skill_name],
            model=model,
            allowed_tools=allowed_tools,
            context_from_pm=self.scene_context,
            file_manager=file_manager,
            user_id=str(task.user_id),
            world_id=str(task.world_id),
            auth_token=task.auth_token,
            tool_executor=agent_tool_executor,
            vendor_id=task.vendor_id,
            model_id=task.model_id,
            enable_thinking=task.enable_thinking,
            thinking_effort=task.thinking_effort,
            task_manager=task_manager,
            task_id=task.task_id,
            max_iterations=int(config.get("max_iterations") or 20),
            language=task.language or "zh-CN",
        )

        result = expert.execute_task({
            "session_id": task.task_id,
            "pm_session_id": task.session_id,
            "pm_task_id": task.task_id,
            "description": task.user_message,
            "pm_context": self.scene_context,
            "conversation_history": self.conversation_history,
            "image_urls": task.image_urls or [],
            "video_urls": task.video_urls or [],
            "audio_urls": task.audio_urls or [],
        })

        project_ids = result.get("project_ids") or []
        if project_ids:
            is_video = self.generation_target == "video"
            already_bound = (
                agent_tool_executor.are_projects_already_bound(project_ids)
                if hasattr(agent_tool_executor, 'are_projects_already_bound')
                else False
            )
            task_manager.push_message(task.task_id, "video_task_submitted" if is_video else "image_task_submitted", {
                "scene_id": self.scene_id,
                "project_ids": project_ids,
                "asset_type": "video" if is_video else "first_frame",
                "already_bound": already_bound,
                "message": f"已提交 {len(project_ids)} 个分镜{'视频' if is_video else '图片'}生成任务",
            })

        content = result.get("result") or result.get("error") or "分镜图片智能体任务已结束"
        task_manager.push_message(task.task_id, "message", {
            "role": "assistant",
            "content": content,
        })
        try:
            _record_storyboard_agent_message(
                self.scene_id,
                "assistant",
                content,
                task_id=task.task_id,
                source="storyboard_agent_result",
            )
        except Exception as e:
            logger.warning(f"Failed to record storyboard agent assistant message: {e}")
        return result


async def _deduct_computing_power(request: Request, computing_power: int, transaction_id: str):
    """
    预扣算力。无 Authorization header（开源/测试）视为跳过（返回成功）。
    返回 (success, message)。
    """
    token = request.headers.get('Authorization')
    if not token or not computing_power:
        return True, None
    if not token.startswith('Bearer '):
        token = f'Bearer {token}'
    try:
        success, message, _ = await async_make_perseids_request(
            endpoint='user/calculate_computing_power',
            method='POST',
            headers={'Authorization': token},
            data={
                'computing_power': computing_power,
                'behavior': 'deduct',
                'transaction_id': transaction_id,
            },
        )
        return bool(success), message
    except Exception as e:
        logger.error(f"deduct computing power failed: {e}")
        return False, str(e)


async def _resolve_digital_human_audio(scene_id: int, character_id: Optional[int]):
    """
    为数字人取配音音频：优先指定角色，否则取该分镜第一个有选中配音的对话。
    返回 (character_id, audio_path)。audio_path 来自对话选中配音（dialogue_audio.audio_url，
    即用 character.default_voice 作参考生成的 TTS 结果）。
    """
    dialogues = await asyncio.to_thread(StoryboardDialogueModel.list_by_scene, scene_id)
    target = None
    if character_id:
        target = next((d for d in dialogues if d.get('character_id') == character_id and d.get('audio_url')), None)
    if not target:
        target = next((d for d in dialogues if d.get('audio_url')), None)
    if not target:
        return character_id, None
    return target.get('character_id'), target.get('audio_url')


# ==================== 故事板 CRUD ====================

@router.get('/create-defaults')
@require_permission("storyboard:create")
async def get_storyboard_create_defaults(
    request: Request,
    world_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    新建故事板前探测默认画幅比例。

    - needs_ratio_confirm=true：世界内尚无故事板，Web 应弹窗确认 16:9/9:16
    - needs_ratio_confirm=false：可继承已有集（优先第 1 集）的 workflow_ratio
    """
    user_id = get_user_id_from_header(user_id)
    if not world_id:
        return JSONResponse(status_code=400, content={'error': 'world_id is required'})

    ensure_world_access(world_id, user_id, Action.VIEW)

    inherited = await asyncio.to_thread(
        StoryboardModel.resolve_inherited_workflow_ratio,
        user_id,
        world_id,
    )
    if not inherited:
        return JSONResponse({
            'success': True,
            'needs_ratio_confirm': True,
            'workflow_ratio': None,
            'source_episode_number': None,
            'storyboard_count': 0,
        })

    ratio = normalize_storyboard_workflow_ratio(inherited.get('workflow_ratio'))
    # 有故事板但 ratio 全空：仍视为可继续创建（后端 create 会兜底 16:9），无需再弹窗
    return JSONResponse({
        'success': True,
        'needs_ratio_confirm': False,
        'workflow_ratio': ratio or DEFAULT_STORYBOARD_WORKFLOW_RATIO,
        'source_episode_number': inherited.get('source_episode_number'),
        'storyboard_count': int(inherited.get('storyboard_count') or 0),
    })


@router.post('/create')
@require_permission("storyboard:create")
async def create_storyboard(
    request: Request,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    幂等创建故事板（get-or-create）。

    Body:
        world_id: int          必填
        episode_number: int    默认 1
        script_id: int         可选，关联剧本
        workflow_id: int       可选，关联工作流
        title: str             可选；为空时继承关联剧本 script.title，再兜底「第N集故事板」
        workflow_ratio: str    可选；Web 首建应传 16:9/9:16；未传时继承同世界已有集（优先第1集）
    """
    user_id = get_user_id_from_header(user_id)
    data = await request.json()

    world_id = data.get('world_id')
    if not world_id:
        return JSONResponse(status_code=400, content={'error': 'world_id is required'})

    episode_number = data.get('episode_number', 1)
    script_id = await asyncio.to_thread(
        resolve_storyboard_script_id,
        data.get('script_id'),
        world_id,
        episode_number,
    )

    # 校验世界存在且有权访问
    ensure_world_access(world_id, user_id, Action.VIEW)

    # Get-or-Create: 按 user_id + world_id + episode_number 查询
    existing = await asyncio.to_thread(
        StoryboardModel.get_by_user_world_episode,
        user_id, world_id, episode_number
    )
    if existing:
        scenes = await asyncio.to_thread(
            StoryboardSceneModel.list_by_storyboard, existing.id
        )
        await _attach_dialogues(scenes)
        return JSONResponse({
            'success': True,
            'storyboard': existing.to_dict(),
            'scenes': scenes,
            'created': False,
        })

    # 画幅比例：显式传入 > 同世界继承（优先第1集）> 16:9
    workflow_ratio = await asyncio.to_thread(
        resolve_storyboard_create_ratio,
        user_id,
        world_id,
        data,
    )

    # 画风继承：从 World 获取
    world = await asyncio.to_thread(WorldModel.get_by_id, world_id)
    defaults = build_storyboard_defaults(world, data, workflow_ratio=workflow_ratio)

    # 标题：显式 title > 剧本 title > 第N集故事板（写入 storyboard.title）
    title = await asyncio.to_thread(
        resolve_storyboard_create_title,
        data.get('title'),
        script_id,
        episode_number,
    )

    # 不存在 → 事务创建（同步函数，asyncio.to_thread 会把同步函数放进线程执行）
    def _create():
        return StoryboardModel.create_with_scenes(
            user_id=user_id,
            world_id=world_id,
            episode_number=episode_number,
            scenes=[],
            workflow_id=data.get('workflow_id'),
            script_id=script_id,
            title=title,
            style=defaults['style'],
            style_reference_image=defaults['style_reference_image'],
            workflow_ratio=defaults['workflow_ratio'],
            composition_preference=defaults['composition_preference'],
            version=data.get('version', 1),
        )

    try:
        sb_id = await asyncio.to_thread(_create)
    except Exception as e:
        # 唯一键冲突 → 并发创建，返回已有
        if 'Duplicate' in str(e) or '1062' in str(e):
            existing = await asyncio.to_thread(
                StoryboardModel.get_by_user_world_episode,
                user_id, world_id, episode_number
            )
            if existing:
                scenes = await asyncio.to_thread(
                    StoryboardSceneModel.list_by_storyboard, existing.id
                )
                return JSONResponse({
                    'success': True,
                    'storyboard': existing.to_dict(),
                    'scenes': scenes,
                    'created': False,
                })
        logger.error(f"Failed to create storyboard: {e}")
        return JSONResponse(status_code=500, content={'error': f'创建失败: {str(e)}'})

    sb = await asyncio.to_thread(StoryboardModel.get_by_id, sb_id)
    scenes = await asyncio.to_thread(StoryboardSceneModel.list_by_storyboard, sb_id)
    await _attach_dialogues(scenes)
    return JSONResponse({
        'success': True,
        'storyboard': sb.to_dict(),
        'scenes': scenes,
        'created': True,
    })


@router.get('/list')
@require_permission("storyboard:list")
async def list_storyboards(
    request: Request,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    order_by: str = 'update_at',
    order_direction: str = 'DESC',
):
    """获取用户故事板列表（空间隔离：商业版按 user_id 过滤）"""
    user_id = get_user_id_from_header(user_id)
    result = await asyncio.to_thread(
        StoryboardModel.list_by_user,
        user_id, page, page_size, order_by, order_direction, keyword,
    )
    return JSONResponse({'success': True, **result})


@router.get('/folders')
@require_permission("storyboard:list")
async def list_storyboard_folders(
    request: Request,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
    world_id: Optional[int] = None,
):
    user_id = get_user_id_from_header(user_id)
    if world_id is not None:
        await asyncio.to_thread(ensure_world_access, world_id, user_id, Action.VIEW)
    folders = await asyncio.to_thread(collect_storyboard_folder_data, user_id, world_id)
    return JSONResponse({'success': True, 'total': len(folders), 'folders': folders})


def _computing_power_range(cp):
    """按时长计费的 dict 算力返回 [min, max]；固定计费（int）或空返回 None。

    供前端模型 option 内联展示「8-18算力」范围使用，避免把 dict 计费模型的最小档位值
    （如 Wan2.2 的 8）误显示为固定值。
    """
    if isinstance(cp, dict) and cp:
        try:
            vals = sorted(int(v) for v in cp.values())
            return [vals[0], vals[-1]]
        except (TypeError, ValueError):
            return None
    return None


def _resolve_effective_power_config(task_config):
    """返回最终生效的原始算力配置（任务层优先，空则实现方层 default_computing_power）。

    UnifiedTaskConfig.get_computing_power() 不传 duration 时对 dict 计费只返回首项，
    且当 task.computing_power=0 时需要从实现方层取值。这里统一解析出原始 int/dict，
    供 _list 计算 computing_power / mode / range 三个展示字段使用。

    Returns:
        int / dict / None：最终生效的算力配置；无配置返回 None。
    """
    cp = task_config.computing_power
    if cp:
        return cp
    impl_name = getattr(task_config, 'implementation', None)
    if not impl_name:
        return None
    impl = UnifiedConfigRegistry.get_implementation(impl_name) if hasattr(UnifiedConfigRegistry, 'get_implementation') else None
    if impl is None:
        impl = UnifiedConfigRegistry.get_all_implementations().get(impl_name) if hasattr(UnifiedConfigRegistry, 'get_all_implementations') else None
    return getattr(impl, 'default_computing_power', None) if impl else None


def _video_resolution_options_from_task(task_config) -> tuple:
    """从任务实现方配置提取视频分辨率选项。返回 (options, default_value)。"""
    try:
        impls = task_config._get_implementations_info() if hasattr(task_config, '_get_implementations_info') else []
    except Exception:
        impls = []
    if not impls:
        # 回退：直接读默认实现方
        impl_name = getattr(task_config, 'implementation', None)
        if impl_name:
            impl_cfg = UnifiedConfigRegistry.get_implementation(impl_name) if hasattr(UnifiedConfigRegistry, 'get_implementation') else None
            if impl_cfg is None:
                impl_cfg = UnifiedConfigRegistry.get_all_implementations().get(impl_name) if hasattr(UnifiedConfigRegistry, 'get_all_implementations') else None
            if impl_cfg:
                raw = list(getattr(impl_cfg, 'supported_video_resolutions', None) or [])
                default = getattr(impl_cfg, 'default_video_resolution', '') or ''
                opts = [
                    {'value': str(x.get('value') or x.get('label') or ''), 'label': str(x.get('label') or x.get('value') or '')}
                    for x in raw if isinstance(x, dict) and (x.get('value') or x.get('label'))
                ]
                opts = [o for o in opts if o['value']]
                if not default and opts:
                    default = opts[0]['value']
                return opts, default or None
        return [], None

    first = impls[0] if isinstance(impls, list) and impls else {}
    raw = list(first.get('supported_video_resolutions') or [])
    default = first.get('default_video_resolution') or ''
    opts = []
    for x in raw:
        if not isinstance(x, dict):
            continue
        val = str(x.get('value') or x.get('label') or '').strip()
        if not val:
            continue
        opts.append({'value': val, 'label': str(x.get('label') or val)})
    if not default and opts:
        default = opts[0]['value']
    return opts, (default or None)


def _resolve_storyboard_video_duration_seconds(
    scene_duration,
    supported_durations,
    duration_mode,
    explicit_duration=None,
) -> int:
    """
    解析视频生成时长（整数秒）。
    duration_mode='auto'：选 >= scene_duration 的最小支持时长；若无则取最大支持时长。
    手动模式：使用 explicit_duration / duration_mode 数字，并校正到支持列表。
    """
    options = sorted({
        int(d) for d in (supported_durations or [])
        if d is not None and str(d).strip() != '' and int(float(d)) > 0
    })
    if not options:
        # 无模型时长表时，ceil 分镜时长兜底
        try:
            target = float(scene_duration or 5)
        except (TypeError, ValueError):
            target = 5.0
        return max(1, int(math.ceil(target)))

    mode = duration_mode
    if mode is None or mode == '':
        mode = 'auto'
    if isinstance(mode, (int, float)) and not isinstance(mode, bool):
        mode = int(mode)

    if mode == 'auto' or str(mode).lower() == 'auto':
        try:
            target = float(scene_duration or 0)
        except (TypeError, ValueError):
            target = 0.0
        if target <= 0:
            return options[0]
        ge = [d for d in options if d >= target]
        return min(ge) if ge else max(options)

    # 手动秒数
    try:
        wanted = int(explicit_duration if explicit_duration is not None else mode)
    except (TypeError, ValueError):
        wanted = options[0]
    if wanted in options:
        return wanted
    # 校正：优先 >= wanted 的最小项，否则最大项
    ge = [d for d in options if d >= wanted]
    return min(ge) if ge else max(options)


def _merge_scene_video_config_json(existing, snapshot: dict) -> dict:
    base = existing if isinstance(existing, dict) else {}
    if isinstance(existing, str):
        try:
            base = json.loads(existing) or {}
        except Exception:
            base = {}
    if not isinstance(base, dict):
        base = {}
    merged = dict(base)
    merged.update(snapshot or {})
    return merged


@router.get('/models')
@require_permission("storyboard:view")
async def get_storyboard_models(
    request: Request,
):
    """
    返回图片/视频/数字人模型列表（按 TaskCategory 分类）。
    旧字段（image_models/video_models）保留向前兼容。
    新增 text_to_image_models / image_edit_models / text_to_video_models / image_to_video_models
    供未来 UI 按文生/图生动态显示使用（第一版前端保守仅使用已支持分类）。
    生成接口接收 task_type（= 此处的 task_id）覆盖默认模型。
    """
    # 手动从 header 获取，避免 FastAPI Header 解析失败导致 422
    # 模型列表本身是配置数据，不严格依赖 user_id
    # 模型列表不依赖具体用户（配置数据），但仍尝试提取以满足可能的权限中间件
    raw_user_id = request.headers.get("x-user-id") or request.headers.get("X-User-Id")
    if raw_user_id:
        try:
            get_user_id_from_header(raw_user_id)  # 只做校验，不赋值
        except Exception:
            pass

    def _list(category):
        configs = UnifiedConfigRegistry.get_by_category(category)
        # 与管理端/工作流一致：按 sort_order 升序，保证默认取「列表第一项」时语义稳定
        configs = sorted(
            configs,
            key=lambda c: (
                float(getattr(c, 'sort_order', 999999) or 999999),
                int(getattr(c, 'id', 0) or 0),
            ),
        )
        items = []
        for c in configs:
            if not c.enabled or c.hidden:
                continue
            # 算力展示元信息（前端 option 内联用）：统一解析最终生效配置，
            # 覆盖「算力定义在实现方层」的模型（如 LTX2.3/可灵/Seedance 1.5 Pro）
            eff_cp = _resolve_effective_power_config(c)
            item = {
                'task_id': c.id,
                'key': c.key,
                'short_key': getattr(c, 'short_key', None) or '',
                'name': c.name,
                'computing_power': (list(eff_cp.values())[0] if isinstance(eff_cp, dict) and eff_cp else (eff_cp or 0)),
                'computing_power_mode': 'by_duration' if isinstance(eff_cp, dict) else 'fixed',
                'computing_power_range': _computing_power_range(eff_cp),
                'supported_durations': c.supported_durations or [],
                'default_duration': c.default_duration,
                'supported_ratios': c.supported_ratios or [],
            }
            # 图生视频 / 文生视频 / 数字人：分辨率能力（数字人映射为 max_edge）
            if category in (
                TaskCategory.IMAGE_TO_VIDEO,
                TaskCategory.TEXT_TO_VIDEO,
                TaskCategory.DIGITAL_HUMAN,
            ):
                res_opts, default_res = _video_resolution_options_from_task(c)
                item['supported_video_resolutions'] = res_opts
                item['default_video_resolution'] = default_res
            if category == TaskCategory.IMAGE_TO_VIDEO:
                modes = list(getattr(c, 'supported_image_modes', None) or ['first_last_frame'])
                item['supported_image_modes'] = [str(m) for m in modes]
                item['supports_last_frame'] = bool(getattr(c, 'supports_last_frame', True))
                item['max_multi_ref_images'] = int(getattr(c, 'max_multi_ref_images', None) or 5)
                item['supports_ref_audio_video'] = bool(
                    getattr(c, 'supports_ref_audio_video', False)
                )
                # Seedance 2.0 系列：前端据此显隐「是否处理人脸」
                item['needs_face_mask'] = bool(
                    getattr(c, 'key', None) in SEEDANCE_FACE_MASK_DRIVER_KEYS
                )
            items.append(item)
        return items

    return JSONResponse({
        'success': True,
        # 旧字段保留向前兼容（当前 storyboard 前端主要使用）
        'image_models': _list(TaskCategory.TEXT_TO_IMAGE),
        'video_models': _list(TaskCategory.IMAGE_TO_VIDEO),
        'digital_human_models': _list(TaskCategory.DIGITAL_HUMAN),
        # 新增分类字段（为未来 UI 动态文生/图生支持做准备，第一版前端暂不使用切换）
        'text_to_image_models': _list(TaskCategory.TEXT_TO_IMAGE),
        'image_edit_models': _list(TaskCategory.IMAGE_EDIT),
        'text_to_video_models': _list(TaskCategory.TEXT_TO_VIDEO),
        'image_to_video_models': _list(TaskCategory.IMAGE_TO_VIDEO),
    })


@router.get('/media-preferences')
@require_permission("storyboard:view")
async def get_storyboard_media_preferences(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    user_id = get_user_id_from_header(user_id)
    storyboard = await asyncio.to_thread(StoryboardModel.get_by_id, int(storyboard_id))
    if not storyboard:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})
    ensure_resource_access(storyboard, user_id, Action.VIEW, "故事板")
    try:
        profiles = await asyncio.to_thread(_storyboard_media_preferences_sync, storyboard)
        return JSONResponse({'success': True, 'profiles': profiles})
    except MediaGenerationPreferenceError as exc:
        return JSONResponse(status_code=400, content={'success': False, 'error': exc.to_dict()})


@router.put('/media-preferences')
@require_permission("storyboard:update")
async def update_storyboard_media_preference(
    request: Request,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    user_id = get_user_id_from_header(user_id)
    data = await request.json()
    storyboard_id = data.get('storyboard_id')
    if storyboard_id in (None, ""):
        return JSONResponse(status_code=400, content={'success': False, 'error': 'storyboard_id 不能为空'})
    storyboard = await asyncio.to_thread(StoryboardModel.get_by_id, int(storyboard_id))
    if not storyboard:
        return JSONResponse(status_code=404, content={'success': False, 'error': '故事板不存在'})
    ensure_resource_access(storyboard, user_id, Action.EDIT, "故事板")
    media_type = data.get('media_type')
    mode = data.get('mode')
    profile = data.get('profile')

    def _save():
        saved = MediaGenerationPreferenceService.save_profile(
            user_id,
            storyboard.world_id,
            MediaGenerationSurface.STORYBOARD_UI,
            media_type,
            mode,
            profile,
        )
        field = MediaGenerationPreferenceService.storyboard_config_field(media_type, mode)
        StoryboardModel.patch_config_json(int(storyboard.id), {field: saved['task_id']})
        return saved

    try:
        saved = await asyncio.to_thread(_save)
        return JSONResponse({'success': True, 'profile': saved})
    except (MediaGenerationPreferenceError, ValueError) as exc:
        error = exc.to_dict() if isinstance(exc, MediaGenerationPreferenceError) else str(exc)
        return JSONResponse(status_code=400, content={'success': False, 'error': error})


def _cli_media_preferences_sync(user_id: int, world_id: int) -> Dict[str, Dict[str, Any]]:
    """读取 storyboard_cli 五槽位偏好（不读写 UI/项目配置）。"""
    profiles: Dict[str, Dict[str, Any]] = {}
    for media_type, modes in (
        (MediaGenerationType.IMAGE, MediaGenerationMode.IMAGE_MODES),
        (MediaGenerationType.VIDEO, MediaGenerationMode.VIDEO_MODES),
    ):
        for mode in modes:
            profile = MediaGenerationPreferenceService.get_profile(
                user_id,
                world_id,
                MediaGenerationSurface.STORYBOARD_CLI,
                media_type,
                mode,
            )
            profiles[MediaGenerationPreferenceService.slot_key(media_type, mode)] = profile
    return profiles


@router.get('/cli/media-preferences')
@require_permission("storyboard:view")
async def get_cli_media_preferences(
    request: Request,
    world_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """Web 配置 Storyboard CLI 独立媒体模型偏好（surface 固定为 storyboard_cli）。"""
    resolved_user_id = get_user_id_from_header(user_id)
    await asyncio.to_thread(ensure_world_access, int(world_id), resolved_user_id, Action.VIEW)
    try:
        profiles = await asyncio.to_thread(
            _cli_media_preferences_sync, int(resolved_user_id), int(world_id)
        )
        return JSONResponse({
            'success': True,
            'surface': MediaGenerationSurface.STORYBOARD_CLI,
            'world_id': int(world_id),
            'profiles': profiles,
        })
    except MediaGenerationPreferenceError as exc:
        return JSONResponse(status_code=400, content={'success': False, 'error': exc.to_dict()})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={'success': False, 'error': str(exc)})


@router.put('/cli/media-preferences')
@require_permission("storyboard:update")
async def update_cli_media_preference(
    request: Request,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """更新单个 storyboard_cli 槽位；一次 PUT 只写一个 mode。"""
    resolved_user_id = get_user_id_from_header(user_id)
    data = await request.json()
    world_id = data.get('world_id')
    if world_id in (None, ""):
        return JSONResponse(status_code=400, content={'success': False, 'error': 'world_id 不能为空'})
    await asyncio.to_thread(ensure_world_access, int(world_id), resolved_user_id, Action.EDIT)
    media_type = data.get('media_type')
    mode = data.get('mode')
    profile = data.get('profile')
    if not isinstance(profile, dict):
        profile = {'task_id': data.get('task_id')} if data.get('task_id') not in (None, "") else {}

    def _save():
        return MediaGenerationPreferenceService.save_profile(
            resolved_user_id,
            int(world_id),
            MediaGenerationSurface.STORYBOARD_CLI,
            media_type,
            mode,
            profile,
        )

    try:
        saved = await asyncio.to_thread(_save)
        return JSONResponse({
            'success': True,
            'surface': MediaGenerationSurface.STORYBOARD_CLI,
            'world_id': int(world_id),
            'slot': MediaGenerationPreferenceService.slot_key(media_type, mode),
            'profile': saved,
        })
    except (MediaGenerationPreferenceError, ValueError) as exc:
        error = exc.to_dict() if isinstance(exc, MediaGenerationPreferenceError) else str(exc)
        return JSONResponse(status_code=400, content={'success': False, 'error': error})


@router.get('/agent/schema')
async def get_storyboard_agent_schema(
    auth_token: Optional[str] = Header(None, alias="Authorization"),
):
    user_id, err = await _resolve_auth_user_id(auth_token)
    if err:
        return err
    result = await asyncio.to_thread(StoryboardAgentCommandService().schema)
    result['user_id'] = user_id
    return JSONResponse(result)

@router.post('/agent/commands/{command}')
async def execute_storyboard_agent_command(
    request: Request,
    command: str,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
):
    user_id, err = await _resolve_auth_user_id(auth_token)
    if err:
        return err

    data, body_err = await _read_json_object_body(request)
    if body_err:
        return body_err

    params = dict(data)
    params['user_id'] = user_id
    params['auth_token'] = _auth_header_token(auth_token)

    try:
        result = await asyncio.to_thread(
            StoryboardAgentCommandService().execute,
            command,
            params,
        )
    except StoryboardCliError as exc:
        return JSONResponse(status_code=400, content=exc.to_dict())

    return JSONResponse(result)


@router.post('/{storyboard_id:int}/auto-generate-missing-images')
async def auto_generate_missing_storyboard_images(
    request: Request,
    storyboard_id: int,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
):
    user_id, err = await _resolve_auth_user_id(auth_token)
    if err:
        return err

    data, body_err = await _read_json_object_body(request)
    if body_err:
        return body_err

    params = dict(data)
    params['storyboard_id'] = storyboard_id
    params['user_id'] = user_id
    params['auth_token'] = _auth_header_token(auth_token)

    try:
        result = await asyncio.to_thread(
            StoryboardAgentCommandService().execute,
            'auto-generate-missing-images',
            params,
        )
    except StoryboardCliError as exc:
        status_code = {
            "enterprise_only": 403,
            "active_batch_exists": 409,
            "quality_parent_reference_missing": 409,
            "location_reference_generation_failed": 409,
            "waiting_location_references": 202,
            "selection_stale": 409,
        }.get(exc.error_code, 400)
        return JSONResponse(status_code=status_code, content=exc.to_dict())

    return JSONResponse(result)


@router.post('/{storyboard_id:int}/auto-generate-missing-videos')
async def auto_generate_missing_storyboard_videos(
    request: Request,
    storyboard_id: int,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
):
    """批量生成缺失分镜视频（需已有首帧；复用 image-batches 编排与轮询）。"""
    user_id, err = await _resolve_auth_user_id(auth_token)
    if err:
        return err

    data, body_err = await _read_json_object_body(request)
    if body_err:
        return body_err

    params = dict(data)
    params['storyboard_id'] = storyboard_id
    params['user_id'] = user_id
    params['auth_token'] = _auth_header_token(auth_token)

    try:
        result = await asyncio.to_thread(
            StoryboardAgentCommandService().execute,
            'auto-generate-missing-videos',
            params,
        )
    except StoryboardCliError as exc:
        status_code = {
            "enterprise_only": 403,
            "active_batch_exists": 409,
            "selection_stale": 409,
        }.get(exc.error_code, 400)
        return JSONResponse(status_code=status_code, content=exc.to_dict())

    return JSONResponse(result)


@router.post('/{storyboard_id:int}/batch-generate-missing-voiceovers')
@require_permission("storyboard:generate")
async def batch_generate_missing_storyboard_voiceovers(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """Queue missing dialogue voiceovers for selected overview scenes."""
    user_id = get_user_id_from_header(user_id)
    storyboard = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not storyboard:
        return JSONResponse(status_code=404, content={'success': False, 'error': '故事板不存在'})
    ensure_resource_access(storyboard, user_id, Action.EDIT, "故事板")

    data, body_err = await _read_json_object_body(request)
    if body_err:
        return body_err
    scene_ids = data.get('scene_ids')
    if not isinstance(scene_ids, list):
        return JSONResponse(
            status_code=400,
            content={'success': False, 'error_code': 'invalid_scene_ids', 'error': 'scene_ids must be an array'},
        )
    try:
        result = await asyncio.to_thread(
            StoryboardVoiceoverBootstrapService().ensure_for_scenes,
            storyboard_id,
            scene_ids,
            user_id,
        )
    except ValueError as exc:
        message = str(exc)
        error_code = 'selection_stale' if 'do not belong' in message else 'invalid_scene_ids'
        return JSONResponse(
            status_code=409 if error_code == 'selection_stale' else 400,
            content={'success': False, 'error_code': error_code, 'error': message},
        )
    return JSONResponse(result)


@router.get('/{storyboard_id:int}/task-status')
async def get_storyboard_task_status(
    storyboard_id: int,
    asset_type: Optional[str] = StoryboardAutoGenerateConstants.DEFAULT_ASSET_TYPE,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
):
    user_id, err = await _resolve_auth_user_id(auth_token)
    if err:
        return err

    try:
        result = await asyncio.to_thread(
            StoryboardAgentCommandService().execute,
            'storyboard-task-status',
            {
                'storyboard_id': storyboard_id,
                'user_id': user_id,
                'asset_type': asset_type,
            },
        )
    except StoryboardCliError as exc:
        return JSONResponse(status_code=400, content=exc.to_dict())

    return JSONResponse(result)


@router.get('/image-batches/{batch_id:int}/status')
async def get_storyboard_image_batch_status(
    batch_id: int,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
):
    user_id, err = await _resolve_auth_user_id(auth_token)
    if err:
        return err

    try:
        result = await asyncio.to_thread(
            StoryboardAgentCommandService().execute,
            'storyboard-image-batch-status',
            {
                'batch_id': batch_id,
                'user_id': user_id,
            },
        )
    except StoryboardCliError as exc:
        return JSONResponse(status_code=400, content=exc.to_dict())

    return JSONResponse(result)


@router.get('/{storyboard_id:int}')
@require_permission("storyboard:view")
async def get_storyboard(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """获取故事板详情及所有分镜"""
    user_id = get_user_id_from_header(user_id)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not sb:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})

    ensure_resource_access(sb, user_id, Action.VIEW, "故事板")

    scenes = await asyncio.to_thread(StoryboardSceneModel.list_by_storyboard, storyboard_id)
    await _attach_dialogues(scenes)
    _enrich_scene_location_props(scenes)

    return JSONResponse({
        'success': True,
        'storyboard': sb.to_dict(),
        'scenes': scenes,
    })


@router.put('/{storyboard_id:int}')
@require_permission("storyboard:update")
async def update_storyboard(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """更新故事板信息（title/style/style_reference_image/workflow_ratio/config_json 等）"""
    user_id = get_user_id_from_header(user_id)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not sb:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})

    ensure_resource_access(sb, user_id, Action.EDIT, "故事板")

    data = await request.json()
    affected = await asyncio.to_thread(StoryboardModel.update, storyboard_id, **data)
    preference_saved, preference_warning = await _sync_script_split_model_preference(
        int(user_id or sb.user_id),
        int(sb.world_id),
        data.get("config_json") if isinstance(data, dict) else None,
    )
    response = {'success': True, 'affected': affected}
    if preference_saved is not None:
        response['preference_saved'] = preference_saved
    if preference_warning:
        response['warning'] = preference_warning
    return JSONResponse(response)


@router.post('/{storyboard_id:int}/generate-from-script')
@require_permission("storyboard:update")
async def generate_storyboard_from_script(
    request: Request,
    storyboard_id: int,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """Parse linked script and create storyboard scenes/dialogues in one backend flow."""
    user_id = get_user_id_from_header(user_id)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not sb:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})

    ensure_resource_access(sb, user_id, Action.EDIT, "故事板")

    # 硬门禁：无有效画幅比例时禁止拆分，避免整集分镜构图错误
    if not str(getattr(sb, 'workflow_ratio', None) or '').strip():
        return JSONResponse(status_code=400, content={'error': '请先设定视频比例'})

    existing_scenes = await asyncio.to_thread(StoryboardSceneModel.list_by_storyboard, storyboard_id)
    if existing_scenes:
        return JSONResponse(status_code=409, content={'error': '故事板已存在分镜，不能重复生成'})

    script_id = sb.script_id or await asyncio.to_thread(
        resolve_storyboard_script_id,
        None,
        sb.world_id,
        sb.episode_number,
    )
    if not script_id:
        return JSONResponse(status_code=400, content={'error': '未找到可用于生成分镜的剧本'})

    script = await asyncio.to_thread(ScriptModel.get_by_id, script_id)
    if not script or not str(script.content or '').strip():
        return JSONResponse(status_code=400, content={'error': '剧本内容为空，无法生成分镜'})

    data = await request.json()
    normalized_auth_token = _auth_header_token(auth_token)

    sequence_mode = str(data.get('sequence_mode') or 'speed').strip().lower()
    if sequence_mode not in {'speed', 'balanced', 'quality'}:
        return JSONResponse(
            status_code=400,
            content={'error': 'invalid_sequence_mode', 'message': f'不支持的分镜图生成模式: {sequence_mode}'},
        )
    if sequence_mode == 'quality' and Edition.is_community():
        return JSONResponse(
            status_code=403,
            content={'error': 'enterprise_only', 'message': '效果模式仅商业版支持'},
        )

    real_vendor_id = data.get('vendor_id')
    model_id = data.get('model_id')
    if not real_vendor_id and model_id:
        try:
            from model.vendor_model import VendorModelModel
            real_vendor_id = await asyncio.to_thread(
                VendorModelModel.get_vendor_id_by_model_id,
                int(model_id),
            )
        except Exception as e:
            logger.warning(f"Failed to resolve vendor for model {model_id}: {e}")

    from config.constant import ScriptSplitQcConstants
    from llm.script_split_qc_agent import run_script_split_qc

    enable_qc = _json_bool(data.get('enable_script_split_qc'), False)
    try:
        max_rounds = int(data.get('script_split_qc_max_rounds') or ScriptSplitQcConstants.DEFAULT_MAX_ROUNDS)
    except (TypeError, ValueError):
        max_rounds = ScriptSplitQcConstants.DEFAULT_MAX_ROUNDS
    max_rounds = max(
        ScriptSplitQcConstants.MIN_MAX_ROUNDS,
        min(ScriptSplitQcConstants.MAX_MAX_ROUNDS, max_rounds),
    )
    if not enable_qc:
        max_rounds = 1

    max_group_duration = data.get('max_group_duration', 15)
    dialogue_language = data.get('dialogue_language') or data.get('language') or ''
    prompt_language = data.get('prompt_language') or data.get('language') or ''
    enable_thinking = _json_bool(data.get('enable_thinking'), False)
    thinking_effort = data.get('thinking_effort', 'medium')

    # 改为异步任务：创建持久化拆分任务后立即返回 202，前端轮询真实进度。
    # 见 docs/script/script_parser_incremental_split_design.md §13.2 §15。
    # 原 QC 循环、parse_script_to_shots、资产化、create_scenes、配音/宫格提交
    # 全部由 worker 推进，发布阶段在 task/script_split_task.py 的 publishing 步骤完成。
    from api.script_split import create_split_task, ScriptSplitPreconditionError
    from config.constant import ScriptSplitConstants
    request_config = {
        'max_group_duration': max_group_duration,
        'world_id': sb.world_id,
        'model': data.get('model') or 'gemini-3-flash-preview',
        'temperature': 0.5,
        'force_medium_shot': _json_bool(data.get('force_medium_shot'), True),
        'no_bg_music': _json_bool(data.get('no_bg_music'), True),
        'split_multi_dialogue': _json_bool(data.get('split_multi_dialogue'), False),
        'language': data.get('language') or '',
        'dialogue_language': dialogue_language,
        'prompt_language': prompt_language,
        'vendor_id': real_vendor_id,
        'model_id': int(model_id) if model_id else 1,
        'enable_thinking': enable_thinking,
        'thinking_effort': thinking_effort,
        # 故事板发布专用配置
        'source': 'storyboard',
        'storyboard_id': storyboard_id,
        'enable_qc': enable_qc,
        'qc_max_rounds': max_rounds,
        'sequence_mode': sequence_mode,
    }
    try:
        task_id, is_new = await create_split_task(
            user_id=user_id,
            source_type=ScriptSplitConstants.SOURCE_TYPE_STORYBOARD,
            source_id=storyboard_id,
            source_node_key=None,
            script_content=script.content,
            request_config=request_config,
            auth_token=normalized_auth_token,
        )
    except ScriptSplitPreconditionError as e:
        return JSONResponse(
            status_code=400,
            content={'error': e.message, 'code': e.code},
        )
    except Exception as e:
        logger.error(f"create storyboard split task failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={'error': f'创建拆分任务失败: {str(e)}'},
        )
    return JSONResponse(
        status_code=202,
        content={
            'success': True,
            'message': '分镜生成任务已创建' if is_new else '已有进行中的生成任务',
            'data': {
                'task_id': task_id,
                'status': 'queued',
                'status_url': f'/api/script-split/tasks/{task_id}',
            },
        },
    )

    # 以下为原同步流程残留，已迁移到 worker（task/script_split_task.py publishing 阶段）。
    # 发布逻辑（资产化 → create_scenes → 配音/宫格）在 Step 9 于 publishing 步骤实现。

@router.delete('/{storyboard_id:int}')
@require_permission("storyboard:delete")
async def delete_storyboard(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """删除故事板及所有分镜（CASCADE）"""
    user_id = get_user_id_from_header(user_id)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not sb:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})

    ensure_resource_access(sb, user_id, Action.DELETE, "故事板")

    affected = await asyncio.to_thread(StoryboardModel.delete, storyboard_id)
    return JSONResponse({'success': True, 'affected': affected})


# ==================== 分镜 CRUD ====================

@router.post('/{storyboard_id:int}/scene')
@require_permission("storyboard:update")
async def add_scene(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """新增分镜（默认追加到末尾；可传 prev_id/next_id 指定插入位置）"""
    user_id = get_user_id_from_header(user_id)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not sb:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})

    ensure_resource_access(sb, user_id, Action.EDIT, "故事板")

    data = await request.json()

    # 计算插入位置（浮点二分）；未传 prev/next 则追加末尾
    prev_id = data.get('prev_id')
    next_id = data.get('next_id')
    if prev_id is not None or next_id is not None:
        sort_order = await _compute_insert_sort(
            StoryboardSceneModel.rebalance, storyboard_id,
            StoryboardSceneModel.get_by_id, prev_id, next_id,
        )
    else:
        existing_scenes = await asyncio.to_thread(
            StoryboardSceneModel.list_by_storyboard, storyboard_id
        )
        max_sort = max([s['sort_order'] for s in existing_scenes], default=-1.0)
        sort_order = max_sort + 1.0

    scene_id = await asyncio.to_thread(
        StoryboardSceneModel.create,
        storyboard_id=storyboard_id,
        sort_order=sort_order,
        title=data.get('title', ''),
        duration=data.get('duration', 5),
        prompt_json=data.get('prompt_json'),
        video_prompt=data.get('video_prompt'),
        video_type=data.get('video_type', SceneVideoType.VIDEO),
        video_config_json=data.get('video_config_json'),
        audio_embedded=data.get('audio_embedded'),
        difficulty=data.get('difficulty'),
        act_name=data.get('act_name'),
        last_modified_user_id=user_id,
    )
    scene = await asyncio.to_thread(StoryboardSceneModel.get_by_id, scene_id)
    return JSONResponse({'success': True, 'scene': scene.to_dict()})


@router.put('/scene/{scene_id}')
@require_permission("storyboard:update")
async def update_scene(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """更新分镜内容字段（选中指针由 asset/select 接口管理，不在此处）"""
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    data = await request.json()
    update_data = {k: v for k, v in data.items() if k in ALLOWED_SCENE_UPDATE_FIELDS}
    update_data['last_modified_user_id'] = user_id
    affected = await asyncio.to_thread(
        StoryboardSceneModel.update, scene_id, **update_data
    )
    return JSONResponse({'success': True, 'affected': affected})


@router.put('/scene/{scene_id}/video-type')
@require_permission("storyboard:update")
async def switch_scene_video_type(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """切换普通视频/对口型模式，并保留已有视频候选。"""
    from services.storyboard_video_type_service import (
        StoryboardVideoTypeConflict,
        StoryboardVideoTypeNotFound,
        StoryboardVideoTypeValidationError,
        switch_storyboard_scene_video_type,
    )

    user_id = get_user_id_from_header(user_id)
    _scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    try:
        data = await request.json()
    except Exception:
        data = {}

    target_type = str(data.get('video_type') or '')
    expected_type = str(data.get('expected_video_type') or '')
    try:
        result = await asyncio.to_thread(
            switch_storyboard_scene_video_type,
            scene_id,
            target_type,
            expected_type,
            user_id,
        )
    except StoryboardVideoTypeValidationError as exc:
        return JSONResponse(status_code=400, content={'error': str(exc)})
    except StoryboardVideoTypeConflict as exc:
        return JSONResponse(status_code=409, content={'error': str(exc)})
    except StoryboardVideoTypeNotFound as exc:
        return JSONResponse(status_code=404, content={'error': str(exc)})

    return JSONResponse({'success': True, **result})


@router.delete('/scene/{scene_id}')
@require_permission("storyboard:update")
async def delete_scene(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """删除分镜（CASCADE 删除其对话与资产）"""
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    affected = await asyncio.to_thread(StoryboardSceneModel.delete, scene_id)
    return JSONResponse({'success': True, 'affected': affected})


@router.post('/{storyboard_id:int}/scenes/batch-delete')
@require_permission("storyboard:update")
async def batch_delete_scenes(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """Atomically delete selected overview scenes."""
    user_id = get_user_id_from_header(user_id)
    storyboard = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not storyboard:
        return JSONResponse(status_code=404, content={'success': False, 'error': '故事板不存在'})
    ensure_resource_access(storyboard, user_id, Action.EDIT, "故事板")

    data, body_err = await _read_json_object_body(request)
    if body_err:
        return body_err
    try:
        result = await asyncio.to_thread(
            batch_delete_storyboard_scenes,
            storyboard_id,
            data.get('scene_ids'),
        )
    except StoryboardBatchOperationError as exc:
        return JSONResponse(
            status_code=409 if exc.error_code == 'selection_stale' else 400,
            content={
                'success': False,
                'error_code': exc.error_code,
                'error': exc.message,
                'payload': exc.payload,
            },
        )
    return JSONResponse(result)


@router.put('/{storyboard_id:int}/scene/reorder')
@require_permission("storyboard:update")
async def reorder_scenes(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    移动单个分镜到指定位置（浮点二分）。

    Body: {scene_id, prev_id, next_id}
        prev_id/next_id 为相邻分镜 id；均传 None 表示置顶；只传 prev_id 表示置底。
    """
    user_id = get_user_id_from_header(user_id)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not sb:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})

    ensure_resource_access(sb, user_id, Action.EDIT, "故事板")

    data = await request.json()
    scene_id = data.get('scene_id')
    if not scene_id:
        return JSONResponse(status_code=400, content={'error': 'scene_id is required'})

    target = await asyncio.to_thread(StoryboardSceneModel.get_by_id, scene_id)
    if not target or target.storyboard_id != storyboard_id:
        return JSONResponse(status_code=400, content={'error': '分镜不属于该故事板'})

    new_sort = await _compute_insert_sort(
        StoryboardSceneModel.rebalance, storyboard_id,
        StoryboardSceneModel.get_by_id,
        data.get('prev_id'), data.get('next_id'),
    )
    await asyncio.to_thread(StoryboardSceneModel.update, scene_id, sort_order=new_sort)
    return JSONResponse({'success': True, 'sort_order': new_sort})


@router.post('/scene/{scene_id}/duplicate')
@require_permission("storyboard:update")
async def duplicate_scene(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """复制分镜（含对话，不含生成资产）"""
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    new_id = await asyncio.to_thread(StoryboardSceneModel.duplicate, scene_id)
    if not new_id:
        return JSONResponse(status_code=500, content={'error': '复制失败'})

    new_scene = await asyncio.to_thread(StoryboardSceneModel.get_by_id, new_id)
    return JSONResponse({'success': True, 'scene': new_scene.to_dict()})


# ==================== 分镜内容操作 ====================

@router.put('/scene/{scene_id}/prompt')
@require_permission("storyboard:update")
async def update_scene_prompt(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """更新分镜画面提示词"""
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    data = await request.json()
    prompt_json = data.get('prompt_json')
    if not prompt_json:
        return JSONResponse(status_code=400, content={'error': 'prompt_json is required'})

    affected = await asyncio.to_thread(
        StoryboardSceneModel.update, scene_id,
        prompt_json=prompt_json, last_modified_user_id=user_id,
    )
    return JSONResponse({'success': True, 'affected': affected})


@router.post('/scene/{scene_id}/generate-image')
@require_permission("storyboard:generate")
async def generate_scene_image(
    request: Request,
    scene_id: int,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    生成分镜图片（首帧/尾帧）。

    数据链路：预扣算力 → 创建 ai_tools（文生图）+ TasksModel(GENERATE_VIDEO) 由 scheduler 处理
    → 插入 storyboard_scene_asset(first_frame/last_frame) → 设为当前选中 → 前端轮询 task-status。
    任务完成后 scheduler 回填 ai_tools.result_url（task-status 优先返回 ai_tools.result_url）。

    Body:
        asset_type: 'first_frame' | 'last_frame'（默认 first_frame）
        prompt: 可选，默认从 scene.prompt_json 组合
        task_type: 可选，ai_tools.type（默认 GPT_IMAGE_2_EDIT）
        ratio / image_size: 可选
    """
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    try:
        data = await request.json()
    except Exception:
        data = {}

    asset_type = data.get('asset_type', 'first_frame')
    if asset_type not in VALID_ASSET_TYPES:
        return JSONResponse(status_code=400, content={'error': 'asset_type 必须为 first_frame/last_frame/video'})

    sb = await asyncio.to_thread(StoryboardModel.get_by_id, scene.storyboard_id)
    task_type = data.get('task_type')

    try:
        from services.storyboard_agent_cli_service import StoryboardAgentCliService, StoryboardCliError

        result = await asyncio.to_thread(
            StoryboardAgentCliService().generate_image,
            scene_id,
            user_id,
            auth_token=_normalize_auth_token(auth_token),
            mode=data.get('mode') or 'auto',
            asset_type=asset_type,
            prompt=data.get('prompt') or None,
            source_image=data.get('source_image') or None,
            ratio=data.get('ratio') or (sb.workflow_ratio if sb else None),
            image_size=data.get('image_size') or None,
            count=_safe_int(data.get('count'), 1) or 1,
            task_type=(int(task_type) if task_type not in (None, '') else None),
            preference_surface=MediaGenerationSurface.STORYBOARD_UI,
        )
    except (StoryboardCliError, TypeError, ValueError) as exc:
        if not isinstance(exc, StoryboardCliError):
            return JSONResponse(status_code=400, content={'success': False, 'error': 'task_type 必须为整数'})
        return JSONResponse(status_code=400, content=exc.to_dict())

    return JSONResponse(result)

@router.post('/scene/{scene_id}/generate-video')
@require_permission("storyboard:generate")
async def generate_scene_video(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    生成分镜视频（按 scene.video_type：图生视频 / 对口型 MiniMax H3）。

    - 图生视频：需已选中首帧图片。
    - 对口型（digital_human）：**必须先有成片配音**；固定 MiniMax H3 数字人
      （image=选中首帧，audio=TTS 说话音频，prompt=动作描述，
      duration clamp 4–10s，resolution→max_edge）。

    Body:
        task_type: 可选；图生视频用；对口型固定 MiniMax H3（忽略其他）
        prompt / duration / ratio / character_id / resolution / clip_to_audio_duration
    """
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    try:
        data = await request.json()
    except Exception:
        data = {}

    video_type = scene.video_type or SceneVideoType.VIDEO
    is_digital_human = (video_type == SceneVideoType.DIGITAL_HUMAN)

    if is_digital_human:
        from services.storyboard_digital_human_service import (
            StoryboardDigitalHumanError,
            compute_digital_human_power,
            orchestrate_digital_human_generation,
            submit_digital_human_plan,
        )

        character_id = data.get('character_id')
        if character_id is not None:
            try:
                character_id = int(character_id)
            except (TypeError, ValueError):
                character_id = None

        resolution = data.get('resolution')
        # 统一编排：解析对白 → 加载 TTS → 探测时长 → MiniMax 计划 → 准备音频。
        # 忽略调用方传入的 prompt/duration/ratio（以服务端规划为准）；resolution 用于 max_edge。
        try:
            plan, _segments, _scene, _sb = await asyncio.to_thread(
                orchestrate_digital_human_generation,
                scene_id,
                character_id=character_id,
                resolution=resolution,
            )
        except StoryboardDigitalHumanError as exc:
            return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

        # 记录 video_config_json 快照
        config = UnifiedConfigRegistry.get_by_id(plan.task_type)
        clip_to_audio_duration = bool(data.get('clip_to_audio_duration', True))
        snapshot = {
            'task_id': plan.task_type,
            'model_key': getattr(config, 'key', None) if config else None,
            'digital_human_model': plan.model,
            'routing_reason': plan.routing_reason,
            'speech_duration': plan.speech_duration,
            'video_duration': int(plan.billable_duration),
            'duration_clamp_reason': plan.duration_clamp_reason,
            'ratio': plan.ratio,
            'resolution': plan.resolution,
            'max_edge': plan.max_edge,
            'clip_to_audio_duration': clip_to_audio_duration,
            'updated_at': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
        }
        existing_vcfg = getattr(scene, 'video_config_json', None)
        merged_vcfg = _merge_scene_video_config_json(existing_vcfg, snapshot)
        try:
            await asyncio.to_thread(
                StoryboardSceneModel.update,
                scene_id,
                video_config_json=merged_vcfg,
                last_modified_user_id=user_id,
            )
        except Exception as e:
            logger.warning(f"Failed to persist video_config_json on generate-video scene {scene_id}: {e}")

        # 先规划后扣费：按 MiniMax 时长档位计算算力
        computing_power = compute_digital_human_power(plan)
        transaction_id = str(uuid.uuid4())
        ok, msg = await _deduct_computing_power(request, computing_power, transaction_id)
        if not ok:
            return JSONResponse(status_code=400, content={'error': msg or '算力不足或扣费失败'})

        try:
            result = await asyncio.to_thread(
                submit_digital_human_plan,
                plan,
                scene_id=scene_id,
                user_id=user_id,
                transaction_id=transaction_id,
                computing_power=computing_power,
                clip_to_audio_duration=clip_to_audio_duration,
                resolution=resolution,
            )
        except StoryboardDigitalHumanError as exc:
            return JSONResponse(status_code=exc.status_code, content=exc.to_dict())
        return JSONResponse(result)

    # 图生视频：必须选中首帧
    requested_task_type = data.get('task_type')
    audio_path = None
    if not scene.selected_first_frame_id:
        return JSONResponse(status_code=400, content={'error': '请先生成并选中首帧图片'})
    ff = await asyncio.to_thread(StoryboardSceneAssetModel.get_by_id, scene.selected_first_frame_id)
    if not ff:
        return JSONResponse(status_code=400, content={'error': '首帧图片尚未生成完成'})
    # asset.result_url 是冗余字段，宫格拆分等场景下可能为 NULL；
    # 与 assets 接口一致，用 ai_tool.result_url 兜底（前端显示首帧也靠此兜底）。
    image_path = ff.result_url
    if not image_path and ff.ai_tool_id:
        ff_tool = await asyncio.to_thread(AIToolsModel.get_by_id, ff.ai_tool_id)
        if ff_tool and ff_tool.result_url:
            image_path = ff_tool.result_url
    if not image_path:
        return JSONResponse(status_code=400, content={'error': '首帧图片尚未生成完成'})

    prompt = data.get('prompt') or scene.video_prompt or ''
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, scene.storyboard_id)
    ratio = data.get('ratio') or (sb.workflow_ratio if sb else None)

    try:
        generation_snapshot = await asyncio.to_thread(
            _resolve_storyboard_generation_snapshot_sync,
            sb,
            user_id=user_id,
            media_type=MediaGenerationType.VIDEO,
            mode=MediaGenerationMode.IMAGE_TO_VIDEO,
            explicit_task_id=(
                int(requested_task_type)
                if requested_task_type not in (None, '')
                else None
            ),
            profile_values={
                'ratio': ratio,
                'image_mode': 'first_last_frame',
                'enable_face_mask': _coerce_enable_face_mask(data.get('enable_face_mask')),
            },
        )
    except (MediaGenerationPreferenceError, TypeError, ValueError) as exc:
        error = exc.to_dict() if isinstance(exc, MediaGenerationPreferenceError) else 'task_type 必须为整数'
        return JSONResponse(status_code=400, content={'success': False, 'error': error})
    task_type = int(generation_snapshot['task_id'])
    config = UnifiedConfigRegistry.get_by_id(task_type)
    supported_durations = list(getattr(config, 'supported_durations', None) or []) if config else []
    duration_mode = data.get('duration_mode', data.get('duration', 'auto'))
    video_duration = _resolve_storyboard_video_duration_seconds(
        scene.duration,
        supported_durations,
        duration_mode=duration_mode,
        explicit_duration=data.get('duration'),
    )
    res_opts, default_res = _video_resolution_options_from_task(config) if config else ([], None)
    allowed_res = {str(o.get('value')) for o in res_opts if o.get('value')}
    raw_res = data.get('resolution')
    if raw_res and str(raw_res) in allowed_res:
        video_resolution = str(raw_res)
    elif default_res:
        video_resolution = str(default_res)
    else:
        video_resolution = None
    # 有效人脸遮盖：商业版 + Seedance 2.0 系列 + 用户勾选
    requested_face_mask = _coerce_enable_face_mask(data.get('enable_face_mask'))
    effective_face_mask = bool(
        requested_face_mask
        and not Edition.is_community()
        and getattr(config, 'key', None) in SEEDANCE_FACE_MASK_DRIVER_KEYS
    )
    generation_snapshot.update({
        'ratio': ratio,
        'duration_seconds': video_duration,
        'resolution': video_resolution,
        'image_mode': 'first_last_frame',
        'enable_face_mask': effective_face_mask,
    })
    clip_to_audio_duration = bool(data.get('clip_to_audio_duration', True))
    try:
        audio_duration = float(scene.duration) if scene.duration is not None else None
    except (TypeError, ValueError):
        audio_duration = None
    snapshot = {
        'task_id': int(task_type) if task_type is not None else None,
        'model_key': getattr(config, 'key', None) if config else None,
        'duration_mode': 'auto' if str(duration_mode).lower() == 'auto' else duration_mode,
        'duration_seconds': video_duration,
        'resolution': video_resolution,
        'clip_to_audio_duration': clip_to_audio_duration,
        'audio_duration': audio_duration,
        'enable_face_mask': effective_face_mask,
        'updated_at': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
    }
    existing_vcfg = getattr(scene, 'video_config_json', None)
    merged_vcfg = _merge_scene_video_config_json(existing_vcfg, snapshot)
    try:
        await asyncio.to_thread(
            StoryboardSceneModel.update,
            scene_id,
            video_config_json=merged_vcfg,
            last_modified_user_id=user_id,
        )
    except Exception as e:
        logger.warning(f"Failed to persist video_config_json on generate-video scene {scene_id}: {e}")

    computing_power = config.get_computing_power(duration=video_duration) if config else 0
    transaction_id = str(uuid.uuid4())
    ok, msg = await _deduct_computing_power(request, computing_power, transaction_id)
    if not ok:
        return JSONResponse(status_code=400, content={'error': msg or '算力不足或扣费失败'})

    # 支持 auto-face 的实现方：注入 human_review，不走 RunningHub pipeline
    impl_id = 0
    human_review = False
    try:
        from task.visual_drivers import VideoDriverFactory
        from config.unified_config import IMPLEMENTATION_TO_ID
        actual_impl = VideoDriverFactory.get_implementation_for_user(task_type, user_id)
        if actual_impl:
            impl_id = IMPLEMENTATION_TO_ID.get(actual_impl, 0) or 0
            impl_config = UnifiedConfigRegistry.get_implementation(actual_impl)
            if (
                effective_face_mask
                and impl_config
                and getattr(impl_config, 'supports_auto_face', False)
            ):
                human_review = True
    except Exception as e:
        logger.warning(f"Failed to resolve video implementation for face mask: {e}")

    need_pipeline_steps = _storyboard_needs_face_mask_pipeline(
        task_type=task_type,
        enable_face_mask=effective_face_mask,
        has_image_input=bool(image_path),
        user_id=user_id,
    )

    extra_payload = {
        'video_type': video_type,
        'source': 'storyboard',
        'clip_to_audio_duration': clip_to_audio_duration,
        'generation_snapshot': generation_snapshot,
        'enable_face_mask': effective_face_mask,
    }
    if video_resolution:
        extra_payload['resolution'] = video_resolution
    if human_review:
        extra_payload['human_review'] = True
    extra_config = json.dumps(extra_payload, ensure_ascii=False)

    create_kwargs = dict(
        prompt=prompt,
        user_id=user_id,
        type=task_type,
        image_path=image_path,
        audio_path=audio_path,
        duration=video_duration,
        ratio=ratio,
        transaction_id=transaction_id,
        extra_config=extra_config,
        implementation=impl_id,
    )
    if need_pipeline_steps:
        ai_tool_id = await asyncio.to_thread(
            AIToolsModel.create_with_pipeline_steps,
            status=AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
            **create_kwargs,
        )
    else:
        ai_tool_id = await asyncio.to_thread(
            AIToolsModel.create,
            status=AI_TOOL_STATUS_PENDING,
            **create_kwargs,
        )
    await asyncio.to_thread(
        TasksModel.create,
        task_type=TASK_TYPE_GENERATE_VIDEO, task_id=ai_tool_id, status=TASK_STATUS_QUEUED,
    )

    asset_id = await asyncio.to_thread(
        StoryboardSceneAssetModel.create,
        scene_id=scene_id, asset_type='video', ai_tool_id=ai_tool_id,
    )
    await asyncio.to_thread(StoryboardSceneAssetModel.set_selected, scene_id, 'video', asset_id)
    await asyncio.to_thread(StoryboardSceneModel.update, scene_id, last_modified_user_id=user_id)

    return JSONResponse({
        'success': True,
        'ai_tool_id': ai_tool_id,
        'asset_id': asset_id,
        'video_type': video_type,
        'computing_power': computing_power,
        'status': 'submitted',
    })


@router.post('/dialogue/{dialogue_id}/generate-voiceover')
@require_permission("storyboard:generate")
async def generate_dialogue_voiceover(
    request: Request,
    dialogue_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    生成对话配音（TTS，不消耗算力）。

    数据链路：取 dialogue.character_id → character.default_voice 作参考音频
    → 创建 ai_audio(PENDING) + TasksModel(GENERATE_AUDIO) 由 scheduler 处理
    → 插入 storyboard_dialogue_audio → 设为 dialogue.selected_audio_id → 前端轮询。

    Body:
        text: 可选，默认 dialogue.text
        ref_path: 可选，参考音频（默认角色 default_voice）
        emo_control_method / emo_weight / emo_vec / emo_text: 可选情感参数
    """
    user_id = get_user_id_from_header(user_id)
    dialogue, scene, err = await _ensure_dialogue_access(dialogue_id, user_id, Action.EDIT)
    if err:
        return err

    try:
        data = await request.json()
    except Exception:
        data = {}

    try:
        result = await asyncio.to_thread(
            submit_storyboard_dialogue_voiceover,
            dialogue_id,
            user_id,
            data,
            strict=True,
        )
    except StoryboardVoiceoverSubmissionError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={'success': False, 'error': exc.message, 'reason': exc.reason},
        )

    return JSONResponse(result)

    if not text:
        return JSONResponse(status_code=400, content={'error': '台词为空，无法生成配音'})

    # 参考音频：body 覆盖 > 角色 default_voice（旁白无角色则为 None，用系统默认音色）
    ref_path = data.get('ref_path')
    if not ref_path and dialogue.character_id:
        character = await asyncio.to_thread(CharacterModel.get_by_id, dialogue.character_id)
        ref_path = character.default_voice if character else None

    transaction_id = str(uuid.uuid4())
    audio_id = await asyncio.to_thread(
        AIAudioModel.create,
        text=text, user_id=user_id, ref_path=ref_path,
        transaction_id=transaction_id,
        emo_control_method=data.get('emo_control_method'),
        emo_weight=data.get('emo_weight'),
        emo_vec=data.get('emo_vec'),
        emo_text=data.get('emo_text'),
        status=AI_AUDIO_STATUS_PENDING,
    )
    await asyncio.to_thread(
        TasksModel.create,
        task_type=TASK_TYPE_GENERATE_AUDIO, task_id=audio_id, status=TASK_STATUS_QUEUED,
    )

    dialogue_audio_id = await asyncio.to_thread(
        StoryboardDialogueAudioModel.create,
        dialogue_id=dialogue_id, ai_audio_id=audio_id,
    )
    await asyncio.to_thread(StoryboardDialogueAudioModel.set_selected, dialogue_id, dialogue_audio_id)

    return JSONResponse({
        'success': True,
        'audio_id': audio_id,
        'dialogue_audio_id': dialogue_audio_id,
        'status': 'submitted',
    })


@router.post('/scene/{scene_id}/ai-chat')
@require_permission("storyboard:generate")
async def scene_ai_chat(
    request: Request,
    scene_id: int,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """AI 对话改图：启动 storyboard-image 智能体任务。"""
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    try:
        data = await request.json()
    except Exception:
        data = {}

    message = str(data.get('message') or '').strip()
    if not message:
        return JSONResponse(status_code=400, content={'success': False, 'error': '消息不能为空'})
    generation_target = str(data.get('generation_target') or 'image').strip().lower()
    generation_target = 'video' if generation_target == 'video' else 'image'

    model = str(data.get('model') or '').strip()
    model_id = data.get('model_id')
    if not model or model_id in (None, ''):
        return JSONResponse(status_code=400, content={'success': False, 'error': '请先选择对话模型'})

    try:
        model_id = int(model_id)
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={'success': False, 'error': 'model_id 必须为数字'})

    vendor_id = data.get('vendor_id') or 1
    try:
        vendor_id = int(vendor_id)
    except (TypeError, ValueError):
        vendor_id = 1
    if vendor_id == 1:
        try:
            from model.vendor_model import VendorModelModel
            resolved_vendor_id = await asyncio.to_thread(
                VendorModelModel.get_vendor_id_by_model_id,
                model_id,
            )
            if resolved_vendor_id:
                vendor_id = int(resolved_vendor_id)
        except Exception as e:
            logger.warning(f"Failed to resolve vendor for storyboard agent model {model_id}: {e}")

    sb = await asyncio.to_thread(StoryboardModel.get_by_id, scene.storyboard_id)
    first_frame = await _asset_task_info(scene, 'first_frame')
    first_frame_url = (first_frame or {}).get('result_url')

    image_task_id = data.get('image_task_id')
    raw_video_task_id = data.get('video_task_id')
    video_task_id = None
    if raw_video_task_id is not None and str(raw_video_task_id).strip() != '':
        try:
            video_task_id = int(raw_video_task_id)
        except (TypeError, ValueError):
            logger.warning(f"Invalid storyboard video_task_id: {raw_video_task_id!r}")
            video_task_id = None
    try:
        from services.storyboard_agent_cli_service import StoryboardAgentCliService
        scene_generation_context = await asyncio.to_thread(
            StoryboardAgentCliService().scene_context,
            scene_id,
            user_id,
        )
    except Exception as e:
        logger.warning(f"Failed to build storyboard scene generation context: {e}")
        scene_generation_context = {}

    # 角色/场景等资产参考（仅用于生图或视频提示说明，视频模式下不强制进 image_to_video.image_urls）
    reference_images = list(scene_generation_context.get("reference_images") or [])
    reference_image_items = [
        dict(item)
        for item in (scene_generation_context.get("reference_image_items") or [])
        if isinstance(item, dict)
    ]
    selected_first_frame = (
        (scene_generation_context.get("selected_assets") or {}).get("first_frame") or {}
    )
    first_frame_url_for_prompt = selected_first_frame.get("result_url") or first_frame_url
    spatial_constraints = _build_storyboard_spatial_constraints(_scene_prompt_dict(scene))
    neighbor_contexts: Dict[str, Any] = {}
    if generation_target == 'image':
        neighbor_contexts = await asyncio.to_thread(_load_storyboard_agent_neighbors, scene)

    raw_user_refs = data.get('reference_image_urls') or []
    if isinstance(raw_user_refs, str):
        raw_user_refs = [u.strip() for u in raw_user_refs.split(',') if u.strip()]
    # 前端视频槽位有序 URL（首帧/尾帧/用户参考）；仅接受 http(s)
    slot_urls = [
        str(u).strip() for u in raw_user_refs
        if str(u).strip().startswith(('http://', 'https://'))
    ]
    # 去重但保序
    seen_slot = set()
    ordered_slot_urls = []
    for url in slot_urls:
        if url in seen_slot:
            continue
        seen_slot.add(url)
        ordered_slot_urls.append(url)

    image_mode = str(data.get('image_mode') or 'first_last_frame').strip().lower()
    if image_mode not in ('first_last_frame', 'multi_reference', 'first_last_with_ref'):
        image_mode = 'first_last_frame'

    video_duration_seconds = None
    video_resolution = None
    clip_to_audio_duration = None
    video_preferences = None
    try:
        generation_snapshots = await asyncio.to_thread(
            _storyboard_generation_snapshots_sync, sb
        )
    except MediaGenerationPreferenceError as exc:
        return JSONResponse(status_code=400, content={'success': False, 'error': exc.to_dict()})
    active_generation_slot = None
    if generation_target == 'video':
        # 视频：image_to_video 只使用前端槽位有序图；角色/场景参考仅作文案说明
        video_input_urls = ordered_slot_urls
        reference_images_for_msg = list(reference_images or ([first_frame_url_for_prompt] if first_frame_url_for_prompt else []))
        reference_image_items_for_msg = list(reference_image_items or [])
        task_image_urls = video_input_urls or None

        # 解析时长 / 分辨率 / 裁剪开关，并写入 scene.video_config_json 快照
        video_task_cfg = None
        if video_task_id:
            try:
                video_task_cfg = UnifiedConfigRegistry.get_by_id(int(video_task_id))
            except Exception:
                video_task_cfg = None
        supported_durations = list(getattr(video_task_cfg, 'supported_durations', None) or []) if video_task_cfg else []
        duration_mode = data.get('duration_mode', data.get('duration', 'auto'))
        video_duration_seconds = _resolve_storyboard_video_duration_seconds(
            scene.duration,
            supported_durations,
            duration_mode=duration_mode,
            explicit_duration=data.get('duration'),
        )
        res_opts, default_res = _video_resolution_options_from_task(video_task_cfg) if video_task_cfg else ([], None)
        allowed_res = {str(o.get('value')) for o in res_opts if o.get('value')}
        raw_res = data.get('resolution')
        if raw_res and str(raw_res) in allowed_res:
            video_resolution = str(raw_res)
        elif default_res:
            video_resolution = str(default_res)
        else:
            video_resolution = None
        clip_to_audio_duration = bool(data.get('clip_to_audio_duration', True))

        try:
            audio_duration = float(scene.duration) if scene.duration is not None else None
        except (TypeError, ValueError):
            audio_duration = None
        snapshot = {
            'task_id': int(video_task_id) if video_task_id else None,
            'model_key': getattr(video_task_cfg, 'key', None) if video_task_cfg else None,
            'duration_mode': 'auto' if str(duration_mode).lower() == 'auto' else (
                int(duration_mode) if str(duration_mode).isdigit() else duration_mode
            ),
            'duration_seconds': video_duration_seconds,
            'resolution': video_resolution,
            'clip_to_audio_duration': clip_to_audio_duration,
            'audio_duration': audio_duration,
            'updated_at': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
        }
        existing_vcfg = getattr(scene, 'video_config_json', None)
        if isinstance(existing_vcfg, str):
            try:
                existing_vcfg = json.loads(existing_vcfg)
            except Exception:
                existing_vcfg = {}
        merged_vcfg = _merge_scene_video_config_json(existing_vcfg, snapshot)
        try:
            await asyncio.to_thread(
                StoryboardSceneModel.update,
                scene_id,
                video_config_json=merged_vcfg,
                last_modified_user_id=user_id,
            )
        except Exception as e:
            logger.warning(f"Failed to persist scene video_config_json for scene {scene_id}: {e}")

        # 生成参数按任务快照传给工具执行器，不写 user_id + world_id 共享偏好，
        # 避免同一世界并发 Agent 互相覆盖比例或污染后续非故事板视频任务。
        if str(scene.video_type or '') != SceneVideoType.DIGITAL_HUMAN:
            video_preferences = await _build_storyboard_agent_video_preferences(
                user_id=user_id,
                world_id=sb.world_id if sb else scene.storyboard_id,
                storyboard=sb,
                image_mode=image_mode,
                duration_seconds=video_duration_seconds,
                video_resolution=video_resolution,
                video_task_id=video_task_id,
                enable_face_mask=_coerce_enable_face_mask(data.get('enable_face_mask')),
            )

            video_mode = MediaGenerationPreferenceService.determine_mode(
                MediaGenerationType.VIDEO,
                image_urls=video_input_urls,
                image_mode=image_mode,
            )
            try:
                video_snapshot = await asyncio.to_thread(
                    _resolve_storyboard_generation_snapshot_sync,
                    sb,
                    user_id=user_id,
                    media_type=MediaGenerationType.VIDEO,
                    mode=video_mode,
                    explicit_task_id=video_task_id,
                    profile_values={
                        'ratio': video_preferences.get('ratio'),
                        'resolution': video_resolution,
                        'duration_seconds': video_duration_seconds,
                        'image_mode': image_mode,
                        'enable_face_mask': bool(video_preferences.get('enable_face_mask', False)),
                    },
                )
            except MediaGenerationPreferenceError as exc:
                return JSONResponse(status_code=400, content={'success': False, 'error': exc.to_dict()})
            slot_key = MediaGenerationPreferenceService.slot_key(
                MediaGenerationType.VIDEO, video_mode
            )
            generation_snapshots[slot_key] = video_snapshot
            active_generation_slot = slot_key
            video_preferences.update(video_snapshot)
    else:
        # 图片：资产参考之后依次追加当前首帧、前后首帧和用户补充图，并保持 URL/说明严格对齐。
        reference_images_for_msg, reference_image_items_for_msg = (
            _build_storyboard_agent_image_references(
                base_reference_images=reference_images,
                base_reference_items=reference_image_items,
                current_first_frame_url=first_frame_url_for_prompt,
                current_title=str(scene.title or ""),
                neighbors=neighbor_contexts,
                user_reference_urls=ordered_slot_urls,
            )
        )
        video_input_urls = None
        task_image_urls = reference_images_for_msg or None
        image_mode_name = MediaGenerationPreferenceService.determine_mode(
            MediaGenerationType.IMAGE,
            image_urls=task_image_urls,
        )
        # 对话改图必须锁定故事板画幅；工具 schema 写「无需传入」时 Agent 会省略 aspect_ratio，
        # 若 snapshot 无 ratio，mcp_tool 会落到默认 16:9。
        storyboard_ratio = (
            normalize_storyboard_workflow_ratio(getattr(sb, 'workflow_ratio', None))
            if sb else None
        ) or str(getattr(sb, 'workflow_ratio', None) or '').strip() or '16:9'
        try:
            image_snapshot = await asyncio.to_thread(
                _resolve_storyboard_generation_snapshot_sync,
                sb,
                user_id=user_id,
                media_type=MediaGenerationType.IMAGE,
                mode=image_mode_name,
                explicit_task_id=(int(image_task_id) if image_task_id not in (None, '') else None),
                profile_values={'ratio': storyboard_ratio},
            )
        except (MediaGenerationPreferenceError, TypeError, ValueError) as exc:
            error = exc.to_dict() if isinstance(exc, MediaGenerationPreferenceError) else str(exc)
            return JSONResponse(status_code=400, content={'success': False, 'error': error})
        image_snapshot['ratio'] = storyboard_ratio
        active_generation_slot = MediaGenerationPreferenceService.slot_key(
            MediaGenerationType.IMAGE, image_mode_name
        )
        generation_snapshots[active_generation_slot] = image_snapshot

    video_model_name_for_msg = None
    if generation_target == 'video' and video_preferences:
        video_model_name_for_msg = video_preferences.get('model_name')
    agent_message = _build_storyboard_agent_message(
        message,
        scene,
        sb,
        first_frame_url=first_frame_url_for_prompt,
        reference_images=reference_images_for_msg,
        reference_image_items=reference_image_items_for_msg,
        generation_target=generation_target,
        image_mode=image_mode if generation_target == 'video' else None,
        video_input_urls=video_input_urls if generation_target == 'video' else None,
        video_duration_seconds=video_duration_seconds if generation_target == 'video' else None,
        video_resolution=video_resolution if generation_target == 'video' else None,
        clip_to_audio_duration=clip_to_audio_duration if generation_target == 'video' else None,
        video_model_name=video_model_name_for_msg if generation_target == 'video' else None,
        video_task_id=video_task_id if generation_target == 'video' else None,
        spatial_constraints=spatial_constraints,
        neighbor_contexts=neighbor_contexts,
        dialogues=scene_generation_context.get("dialogues") or [],
        characters=scene_generation_context.get("characters") or [],
    )
    conversation_history = await asyncio.to_thread(_list_storyboard_agent_messages, scene_id, True)
    await asyncio.to_thread(
        _record_storyboard_agent_message,
        scene_id,
        "user",
        message,
        None,
        "text",
        "both",
        "storyboard_agent_user",
    )
    session_id = _storyboard_scene_chat_session_id(scene_id)
    token = _normalize_auth_token(auth_token)

    enable_thinking = _json_bool(data.get('enable_thinking'), False)
    thinking_effort = data.get('thinking_effort') or 'medium'
    if thinking_effort not in ('low', 'medium', 'high'):
        thinking_effort = 'medium'

    from api.script_writer import task_manager
    execution_context_json = {
        'schema_version': 1,
        'surface': MediaGenerationSurface.STORYBOARD_UI,
        'storyboard_id': int(scene.storyboard_id),
        'scene_id': int(scene_id),
        'active_generation_slot': active_generation_slot,
        'generation_snapshots': generation_snapshots,
    }
    # 图片模式：把参考图条目写入执行上下文，供工具层强制注入 URL + 对齐图例。
    if generation_target == 'image' and reference_image_items_for_msg:
        execution_context_json['reference_image_items'] = [
            {
                'url': item.get('url'),
                'type': item.get('type'),
                'name': item.get('name'),
                'label': item.get('label'),
                'variant_label': item.get('variant_label'),
                'source_type': item.get('source_type'),
            }
            for item in reference_image_items_for_msg
            if isinstance(item, dict) and item.get('url')
        ]
    task_id = await asyncio.to_thread(
        task_manager.create_task,
        session_id=session_id,
        user_message=agent_message,
        user_id=str(user_id),
        world_id=str(sb.world_id if sb else scene.storyboard_id),
        auth_token=token,
        vendor_id=vendor_id,
        model_id=model_id,
        enable_thinking=enable_thinking,
        thinking_effort=thinking_effort,
        image_urls=task_image_urls,
        language=data.get('language') or 'zh-CN',
        execution_context_json=execution_context_json,
    )
    task = await asyncio.to_thread(task_manager.get_task, task_id)
    if not task:
        return JSONResponse(status_code=500, content={'success': False, 'error': '智能体任务创建失败'})

    runner = StoryboardImageAgentRunner(
        scene_id=scene_id,
        scene_context=agent_message,
        conversation_history=conversation_history,
        generation_target=generation_target,
        video_type=scene.video_type,
        video_preferences=video_preferences,
        style=getattr(sb, 'style', '') if sb else '',
        composition_preference=getattr(sb, 'composition_preference', '') if sb else '',
        generation_snapshots=generation_snapshots,
    )
    task_manager.start_task(task, runner, {
        'user_id': str(user_id),
        'world_id': str(sb.world_id if sb else scene.storyboard_id),
        'session_id': session_id,
    })

    return JSONResponse({
        'success': True,
        'task_id': task_id,
        'session_id': session_id,
        'stream_url': f'/api/storyboard/agent-task/{task_id}/stream',
    })


@router.get('/scene/{scene_id}/ai-chat/history')
@require_permission("storyboard:view")
async def get_scene_ai_chat_history(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """Return persisted storyboard agent chat messages for the current scene."""
    user_id = get_user_id_from_header(user_id)
    _scene, err = await _ensure_scene_access(scene_id, user_id, Action.VIEW)
    if err:
        return err

    messages = await asyncio.to_thread(_list_storyboard_agent_messages, scene_id, False)
    return JSONResponse({'success': True, 'messages': messages})


def _format_sse_event(data: dict, event_id: Optional[int] = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


@router.get('/agent-task/{task_id}/stream')
@require_permission("agent_task:stream")
async def stream_storyboard_agent_task(request: Request, task_id: str):
    """SSE stream for storyboard image agent task."""
    from model.agent_task_messages import AgentTaskMessagesModel
    from model.agent_tasks import AgentTasksModel

    async def event_generator():
        last_message_id = 0
        try:
            raw_last_id = request.headers.get("last-event-id") or request.query_params.get("last_id")
            if raw_last_id:
                last_message_id = int(raw_last_id)
        except (TypeError, ValueError):
            last_message_id = 0

        yield _format_sse_event({'type': 'connected', 'task_id': task_id})

        while True:
            messages = []
            try:
                messages = await asyncio.to_thread(
                    AgentTaskMessagesModel.get_messages_after,
                    task_id,
                    last_message_id,
                    50,
                )
            except Exception as e:
                logger.error(f"Failed to load storyboard agent messages: {e}")

            for msg in messages:
                item = msg.to_dict()
                last_message_id = max(last_message_id, int(item.get('id') or 0))
                yield _format_sse_event(item, event_id=item.get('id'))
                if item.get('type') in ('done', 'error'):
                    return

            if not messages:
                try:
                    db_task = await asyncio.to_thread(AgentTasksModel.get_by_task_id, task_id)
                    if db_task and db_task.status in ['completed', 'failed', 'cancelled']:
                        yield _format_sse_event({'type': 'done', 'status': db_task.status})
                        return
                except Exception as e:
                    logger.error(f"Failed to check storyboard agent task status: {e}")
                await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post('/scene/{scene_id}/bind-agent-image-task')
@require_permission("storyboard:generate")
async def bind_agent_image_task(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """Bind agent-submitted ai_tools project_ids to current storyboard scene assets."""
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    try:
        data = await request.json()
    except Exception:
        data = {}
    project_ids = data.get('project_ids') or []
    asset_type = data.get('asset_type') or 'first_frame'
    if asset_type not in VALID_ASSET_TYPES:
        return JSONResponse(status_code=400, content={'success': False, 'error': 'asset_type 必须为 first_frame/last_frame/video'})
    if not isinstance(project_ids, list):
        project_ids = [project_ids]

    asset_ids = []
    for project_id in project_ids:
        try:
            ai_tool_id = int(project_id)
        except (TypeError, ValueError):
            continue
        asset_id = await asyncio.to_thread(
            StoryboardSceneAssetModel.create,
            scene_id=scene_id,
            asset_type=asset_type,
            ai_tool_id=ai_tool_id,
        )
        asset_ids.append(asset_id)

    if not asset_ids:
        return JSONResponse(status_code=400, content={'success': False, 'error': '未提供有效 project_ids'})

    await asyncio.to_thread(
        StoryboardSceneAssetModel.set_selected,
        scene_id,
        asset_type,
        asset_ids[0],
    )
    await asyncio.to_thread(StoryboardSceneModel.update, scene_id, last_modified_user_id=user_id)

    return JSONResponse({
        'success': True,
        'asset_type': asset_type,
        'asset_ids': asset_ids,
        'selected_asset_id': asset_ids[0],
    })


@router.get('/scene/{scene_id}/task-status')
@require_permission("storyboard:view")
async def get_scene_task_status(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    轮询分镜生成任务状态。
    图片/视频状态来自当前选中 asset 关联的 ai_tools；配音状态来自各对话选中配音关联的 ai_audio。
    """
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.VIEW)
    if err:
        return err

    first_frame = await _asset_task_info(scene, 'first_frame')
    last_frame = await _asset_task_info(scene, 'last_frame')
    video = await _asset_task_info(scene, 'video')

    # 对话配音状态
    dialogues = await asyncio.to_thread(StoryboardDialogueModel.list_by_scene, scene_id)
    voice_items = []
    for d in dialogues:
        item = {
            'dialogue_id': d.get('id'),
            'selected_audio_id': d.get('selected_audio_id'),
            'audio_url': None,
            'status': None,
            'error': None,
        }
        selected = d.get('selected_audio_id')
        if selected:
            da = await asyncio.to_thread(StoryboardDialogueAudioModel.get_by_id, selected)
            if da:
                item['audio_url'] = da.audio_url
                if da.ai_audio_id:
                    aa = await asyncio.to_thread(AIAudioModel.get_by_id, da.ai_audio_id)
                    if aa:
                        item['status'] = aa.status
                        item['error'] = aa.message
                        if not item['audio_url'] and aa.result_url:
                            item['audio_url'] = aa.result_url
        voice_items.append(item)

    return JSONResponse({
        'success': True,
        'first_frame': first_frame,
        'last_frame': last_frame,
        'video': video,
        'dialogues': voice_items,
        # 分镜当前时长（音频全部完成时由后端自动同步为选中配音求和，浮点秒）。
        # 前端轮询据此即时刷新时间线/MM:SS 标签与进度行总时长。
        'scene_duration': float(scene.duration) if scene and scene.duration is not None else None,
    })


# ==================== 对话（Dialogue）CRUD ====================

@router.get('/scene/{scene_id}/dialogues')
@require_permission("storyboard:view")
async def list_dialogues(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """列出分镜下所有对话（按 sort_order）"""
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.VIEW)
    if err:
        return err

    dialogues = await asyncio.to_thread(StoryboardDialogueModel.list_by_scene, scene_id)
    return JSONResponse({'success': True, 'dialogues': dialogues})


@router.post('/scene/{scene_id}/dialogue')
@require_permission("storyboard:update")
async def add_dialogue(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """新增对话（默认追加末尾；可传 prev_id/next_id 指定位置）"""
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    data = await request.json()

    prev_id = data.get('prev_id')
    next_id = data.get('next_id')
    if prev_id is not None or next_id is not None:
        sort_order = await _compute_insert_sort(
            StoryboardDialogueModel.rebalance, scene_id,
            StoryboardDialogueModel.get_by_id, prev_id, next_id,
        )
    else:
        existing = await asyncio.to_thread(StoryboardDialogueModel.list_by_scene, scene_id)
        max_sort = max([d['sort_order'] for d in existing], default=-1.0)
        sort_order = max_sort + 1.0

    dialogue_id = await asyncio.to_thread(
        StoryboardDialogueModel.create,
        scene_id=scene_id,
        sort_order=sort_order,
        character_id=data.get('character_id'),
        text=data.get('text'),
        speed=data.get('speed', 1.0),
        volume=data.get('volume', 100),
        last_modified_user_id=user_id,
    )
    dialogue = await asyncio.to_thread(StoryboardDialogueModel.get_by_id, dialogue_id)
    return JSONResponse({'success': True, 'dialogue': dialogue.to_dict()})


@router.put('/dialogue/{dialogue_id}')
@require_permission("storyboard:update")
async def update_dialogue(
    request: Request,
    dialogue_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """更新对话（角色/台词/语速/音量）"""
    user_id = get_user_id_from_header(user_id)
    dialogue, scene, err = await _ensure_dialogue_access(dialogue_id, user_id, Action.EDIT)
    if err:
        return err

    data = await request.json()
    update_data = {k: v for k, v in data.items() if k in ALLOWED_DIALOGUE_UPDATE_FIELDS}
    update_data['last_modified_user_id'] = user_id
    affected = await asyncio.to_thread(
        StoryboardDialogueModel.update, dialogue_id, **update_data
    )
    return JSONResponse({'success': True, 'affected': affected})


@router.delete('/dialogue/{dialogue_id}')
@require_permission("storyboard:update")
async def delete_dialogue(
    request: Request,
    dialogue_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """删除对话（CASCADE 删除其配音历史）"""
    user_id = get_user_id_from_header(user_id)
    dialogue, scene, err = await _ensure_dialogue_access(dialogue_id, user_id, Action.EDIT)
    if err:
        return err

    affected = await asyncio.to_thread(StoryboardDialogueModel.delete, dialogue_id)
    return JSONResponse({'success': True, 'affected': affected})


@router.put('/scene/{scene_id}/dialogue/reorder')
@require_permission("storyboard:update")
async def reorder_dialogues(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    移动单个对话到指定位置（浮点二分）。
    Body: {dialogue_id, prev_id, next_id}
    """
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    data = await request.json()
    dialogue_id = data.get('dialogue_id')
    if not dialogue_id:
        return JSONResponse(status_code=400, content={'error': 'dialogue_id is required'})

    target = await asyncio.to_thread(StoryboardDialogueModel.get_by_id, dialogue_id)
    if not target or target.scene_id != scene_id:
        return JSONResponse(status_code=400, content={'error': '对话不属于该分镜'})

    new_sort = await _compute_insert_sort(
        StoryboardDialogueModel.rebalance, scene_id,
        StoryboardDialogueModel.get_by_id,
        data.get('prev_id'), data.get('next_id'),
    )
    await asyncio.to_thread(StoryboardDialogueModel.update, dialogue_id, sort_order=new_sort)
    return JSONResponse({'success': True, 'sort_order': new_sort})


# ==================== 资产（Asset）/ 配音选中 ====================

@router.get('/scene/{scene_id}/assets')
@require_permission("storyboard:view")
async def list_scene_assets(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
    asset_type: Optional[str] = None,
):
    """列出分镜的图片/视频资产候选（可选 asset_type 过滤）"""
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.VIEW)
    if err:
        return err

    if asset_type is not None and asset_type not in VALID_ASSET_TYPES:
        return JSONResponse(status_code=400, content={'error': f'asset_type 必须为 {VALID_ASSET_TYPES}'})

    assets = await asyncio.to_thread(
        StoryboardSceneAssetModel.list_by_scene, scene_id, asset_type
    )
    assets = await asyncio.to_thread(_enrich_scene_asset_result_urls, assets)
    return JSONResponse({
        'success': True,
        'selected': {
            'first_frame': scene.selected_first_frame_id,
            'last_frame': scene.selected_last_frame_id,
            'video': scene.selected_video_id,
        },
        'assets': assets,
    })


@router.post('/scene/{scene_id}/asset/select')
@require_permission("storyboard:update")
async def select_scene_asset(
    request: Request,
    scene_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """设置分镜某类型的当前选中资产。Body: {asset_type, asset_id}"""
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    data = await request.json()
    asset_type = data.get('asset_type')
    asset_id = data.get('asset_id')
    if asset_type not in VALID_ASSET_TYPES:
        return JSONResponse(status_code=400, content={'error': f'asset_type 必须为 {VALID_ASSET_TYPES}'})
    if not asset_id:
        return JSONResponse(status_code=400, content={'error': 'asset_id is required'})
    try:
        asset_id = int(asset_id)
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={'error': 'asset_id 必须为整数'})

    try:
        result = await asyncio.to_thread(
            select_storyboard_scene_asset,
            scene_id,
            asset_id,
            asset_type,
            user_id,
        )
    except StoryboardAssetSelectError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                'success': False,
                'error_code': exc.error_code,
                'error': exc.message,
            },
        )
    return JSONResponse(result)


@router.post('/scene/{scene_id}/asset/upload')
@require_permission("storyboard:update")
async def upload_scene_asset(
    request: Request,
    scene_id: int,
    file: UploadFile = File(...),
    asset_type: str = Form("first_frame"),
    set_selected: str = Form("true"),
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    上传本地图片或视频并登记为分镜资产。

    - 文件落盘到 upload/storyboard/{asset_type}/
    - 创建 storyboard_scene_asset（无 ai_tool_id，result_url 直写）
    - 默认设为当前选中（set_selected=true）
    """
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    asset_type = (asset_type or "first_frame").strip().lower()
    if asset_type not in VALID_ASSET_TYPES:
        return JSONResponse(
            status_code=400,
            content={'success': False, 'error': 'asset_type 必须为 first_frame/last_frame/video'},
        )

    content_type = (file.content_type or "").lower()
    is_video = asset_type == "video"
    filename = file.filename or ("storyboard.mp4" if is_video else "storyboard.png")
    ext = os.path.splitext(filename)[1].lower()

    if is_video:
        if ext not in MediaConstants.STORYBOARD_VIDEO_UPLOAD_EXTENSIONS:
            return JSONResponse(
                status_code=400,
                content={'success': False, 'error': '视频仅支持 MP4、WebM 格式'},
            )
        size_config_key = 'max_video_size_mb'
        max_size_default = MediaConstants.STORYBOARD_VIDEO_MAX_SIZE_MB_DEFAULT
    else:
        if ext not in MediaConstants.STORYBOARD_IMAGE_UPLOAD_EXTENSIONS:
            if not content_type.startswith("image/"):
                return JSONResponse(
                    status_code=400,
                    content={'success': False, 'error': '仅支持 JPG、PNG、GIF、WebP 图片'},
                )
            # 兼容浏览器上传 image/* 但文件名没有有效扩展名的 Blob。
            ext = ".png"
        size_config_key = 'max_image_size_mb'
        max_size_default = MediaConstants.STORYBOARD_IMAGE_MAX_SIZE_MB_DEFAULT

    max_size_mb = await asyncio.to_thread(
        get_dynamic_config_value,
        'upload',
        size_config_key,
        default=max_size_default,
    )
    try:
        max_size_mb = float(max_size_mb)
    except (TypeError, ValueError):
        max_size_mb = max_size_default
    max_bytes = int(max_size_mb * 1024 * 1024)
    should_select = str(set_selected or "true").strip().lower() not in ("0", "false", "no")

    try:
        stored = await asyncio.to_thread(
            _store_storyboard_asset_file,
            file.file,
            asset_type,
            ext,
            max_bytes,
        )
    except StoryboardAssetUploadTooLarge:
        media_label = "视频" if is_video else "图片"
        return JSONResponse(
            status_code=400,
            content={'success': False, 'error': f'{media_label}大小不能超过 {max_size_mb:g}MB'},
        )
    except Exception as exc:
        logger.error("保存分镜上传文件失败 scene=%s: %s", scene_id, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': f'上传失败: {exc}'},
        )

    abs_path = stored["abs_path"]
    if stored["size_bytes"] <= 0:
        await asyncio.to_thread(_remove_file_if_exists, abs_path)
        return JSONResponse(
            status_code=400,
            content={'success': False, 'error': '文件内容为空'},
        )

    video_info = None
    if is_video:
        video_info = await get_video_info(abs_path)
        if not video_info or not video_info.get("width") or not video_info.get("height"):
            await asyncio.to_thread(_remove_file_if_exists, abs_path)
            return JSONResponse(
                status_code=400,
                content={'success': False, 'error': '无法识别该视频，请上传有效的 MP4 或 WebM 文件'},
            )

        max_duration = await asyncio.to_thread(
            get_dynamic_config_value,
            'upload',
            'max_video_duration_seconds',
            default=MediaConstants.STORYBOARD_VIDEO_MAX_DURATION_SECONDS_DEFAULT,
        )
        try:
            max_duration = float(max_duration)
        except (TypeError, ValueError):
            max_duration = MediaConstants.STORYBOARD_VIDEO_MAX_DURATION_SECONDS_DEFAULT
        duration = float(video_info.get("duration") or 0)
        if max_duration > 0 and duration > max_duration:
            await asyncio.to_thread(_remove_file_if_exists, abs_path)
            return JSONResponse(
                status_code=400,
                content={'success': False, 'error': f'视频时长不能超过 {max_duration:g} 秒'},
            )

    try:
        # 手工上传文件由当前 Web 服务提供，必须使用同源相对 URL。
        # 若拼接配置中的 server.host（常为 localhost），通过域名或反向代理访问时
        # 浏览器会请求用户本机，导致数据库已有视频但候选区加载失败。
        result_url = build_upload_url(
            *stored["subdir_parts"],
            stored["filename"],
        )

        def _create_asset() -> int:
            asset_id = StoryboardSceneAssetModel.create(
                scene_id=scene_id,
                asset_type=asset_type,
                ai_tool_id=None,
                result_url=result_url,
            )
            if should_select:
                StoryboardSceneAssetModel.set_selected(scene_id, asset_type, asset_id)
            StoryboardSceneModel.update(scene_id, last_modified_user_id=user_id)
            return asset_id

        asset_id = await asyncio.to_thread(_create_asset)
    except Exception as exc:
        await asyncio.to_thread(_remove_file_if_exists, abs_path)
        logger.error("登记分镜上传资产失败 scene=%s: %s", scene_id, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': f'上传失败: {exc}'},
        )

    payload: Dict[str, Any] = {
        "asset_id": asset_id,
        "result_url": result_url,
        "asset_type": asset_type,
        "selected": should_select,
        "size_bytes": stored["size_bytes"],
    }
    if video_info:
        payload["video"] = {
            "width": video_info.get("width"),
            "height": video_info.get("height"),
            "duration": video_info.get("duration"),
        }
    return JSONResponse({'success': True, **payload})


@router.delete('/scene/{scene_id}/asset/{asset_id}')
@require_permission("storyboard:update")
async def delete_scene_asset(
    request: Request,
    scene_id: int,
    asset_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """删除分镜图片/视频候选，并原子维护该类型的选中指针。"""
    user_id = get_user_id_from_header(user_id)
    _, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    try:
        result = await asyncio.to_thread(
            delete_storyboard_scene_asset,
            scene_id,
            asset_id,
            user_id,
        )
    except StoryboardAssetDeleteError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                'success': False,
                'error_code': exc.error_code,
                'error': exc.message,
            },
        )
    except Exception as exc:
        logger.error(
            "删除分镜候选失败 scene=%s asset=%s: %s",
            scene_id,
            asset_id,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': '删除候选失败，请稍后重试'},
        )

    file_removed = False
    if result.get("should_remove_local_file"):
        try:
            file_removed = await asyncio.to_thread(
                _remove_deleted_storyboard_asset_file,
                result.get("result_url") or "",
                result.get("asset_type") or "",
            )
        except Exception:
            # 数据库删除已提交，文件清理只能 best-effort，不能把成功操作伪装成失败。
            logger.warning(
                "清理已删除分镜候选文件失败 scene=%s asset=%s",
                scene_id,
                asset_id,
                exc_info=True,
            )

    result.pop("result_url", None)
    result.pop("should_remove_local_file", None)
    result["file_removed"] = file_removed
    return JSONResponse(result)


@router.post('/dialogue/{dialogue_id}/audio/select')
@require_permission("storyboard:update")
async def select_dialogue_audio(
    request: Request,
    dialogue_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """设置对话当前选中的配音。Body: {dialogue_audio_id}"""
    user_id = get_user_id_from_header(user_id)
    dialogue, scene, err = await _ensure_dialogue_access(dialogue_id, user_id, Action.EDIT)
    if err:
        return err

    data = await request.json()
    dialogue_audio_id = data.get('dialogue_audio_id')
    if not dialogue_audio_id:
        return JSONResponse(status_code=400, content={'error': 'dialogue_audio_id is required'})

    da = await asyncio.to_thread(StoryboardDialogueAudioModel.get_by_id, dialogue_audio_id)
    if not da or da.dialogue_id != dialogue_id:
        return JSONResponse(status_code=400, content={'error': '配音记录不属于该对话'})

    await asyncio.to_thread(
        StoryboardDialogueAudioModel.set_selected, dialogue_id, dialogue_audio_id
    )

    # 切换选中配音后，联动重算分镜时长（覆盖"用户手动选另一条已完成配音"的场景）。
    # best-effort，失败仅记日志，不阻塞选中操作本身。
    try:
        await recalc_scene_duration_if_all_completed(scene.id)
    except Exception as e:
        logger.warning(f"[select_dialogue_audio] scene={scene.id} 联动重算分镜时长失败: {e}")

    return JSONResponse({'success': True, 'selected_audio_id': dialogue_audio_id})


# ==================== 导出操作 ====================

@router.get('/export-job/{job_id}')
@require_permission("storyboard:export")
async def get_export_job(
    request: Request,
    job_id: str,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """查询导出任务状态（完整视频异步 job）。"""
    user_id = get_user_id_from_header(user_id)
    from services.storyboard_export_service import get_job

    job = await asyncio.to_thread(get_job, job_id)
    if not job:
        return JSONResponse(status_code=404, content={'error': '导出任务不存在'})
    if int(job.get('user_id') or 0) != int(user_id):
        return JSONResponse(status_code=403, content={'error': '无权查看该导出任务'})
    # 不回传内部本地路径
    public = {k: v for k, v in job.items() if not str(k).startswith('_')}
    return JSONResponse({'success': True, **public})


@router.post('/{storyboard_id:int}/export-full-video')
@require_permission("storyboard:export")
async def export_full_video(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    导出完整视频：后台合成后上传 CDN，立即返回 job_id。
    前端轮询 GET /api/storyboard/export-job/{job_id} 获取 download_url。

    Body 可选:
        include_subtitles: bool  默认 true，硬烧对白字幕（ASS，超长分页）
    """
    user_id = get_user_id_from_header(user_id)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not sb:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})

    ensure_resource_access(sb, user_id, Action.VIEW, "故事板")

    include_subtitles = True
    try:
        body = await request.json()
        if isinstance(body, dict) and 'include_subtitles' in body:
            include_subtitles = bool(body.get('include_subtitles'))
    except Exception:
        pass

    from services.storyboard_export_service import (
        create_job,
        update_job,
        make_work_dir,
        cleanup_dir,
        collect_export_plan,
        materialize_package_files,
        build_merged_video,
        upload_local_file_to_cdn,
    )
    import os

    job = await asyncio.to_thread(create_job, storyboard_id, "full_video", user_id)
    job_id = job["job_id"]

    async def _run():
        work = None
        local_path = None
        try:
            await asyncio.to_thread(update_job, job_id, status="running", progress=5)

            def _compose():
                nonlocal work, local_path
                work = make_work_dir(storyboard_id)
                plan = collect_export_plan(storyboard_id)
                if not plan.scenes:
                    raise RuntimeError("故事板没有分镜，无法导出")
                update_job(job_id, progress=15)
                materialize_package_files(plan, os.path.join(work, "package"))
                update_job(job_id, progress=45)
                local_path = build_merged_video(
                    plan, work, burn_subtitles=include_subtitles
                )
                update_job(job_id, progress=80, filename=os.path.basename(local_path))
                return local_path

            local_path = await asyncio.to_thread(_compose)
            update_job(job_id, status="uploading", progress=85)
            download_url, filename = await upload_local_file_to_cdn(
                local_path, content_type="video/mp4"
            )
            await asyncio.to_thread(
                update_job,
                job_id,
                status="completed",
                progress=100,
                download_url=download_url,
                filename=filename,
                error=None,
            )
        except Exception as e:
            logger.exception(f"export-full-video job={job_id} failed: {e}")
            await asyncio.to_thread(
                update_job, job_id, status="failed", progress=100, error=str(e)
            )
        finally:
            if work:
                await asyncio.to_thread(cleanup_dir, work)

    # 后台跑，不阻塞请求
    asyncio.create_task(_run())

    return JSONResponse({
        'success': True,
        'job_id': job_id,
        'status': 'pending',
        'message': '完整视频导出任务已提交，请轮询导出进度',
    })


@router.post('/{storyboard_id:int}/export-all-scenes')
@require_permission("storyboard:export")
async def export_all_scenes(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    导出素材包 zip（分镜N 视频/图 + 分镜N_M.wav），上传 CDN 后返回 download_url。
    流程对齐剧本世界导出 export-world。
    """
    user_id = get_user_id_from_header(user_id)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not sb:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})

    ensure_resource_access(sb, user_id, Action.VIEW, "故事板")

    from services.storyboard_export_service import (
        make_work_dir,
        cleanup_dir,
        collect_export_plan,
        build_package_zip,
        upload_local_file_to_cdn,
    )
    import os

    work = None
    zip_path = None
    try:
        def _pack():
            nonlocal work, zip_path
            work = make_work_dir(storyboard_id)
            plan = collect_export_plan(storyboard_id)
            if not plan.scenes:
                raise RuntimeError("故事板没有分镜，无法导出")
            zip_path = build_package_zip(plan, work)
            return zip_path

        zip_path = await asyncio.to_thread(_pack)
        download_url, filename = await upload_local_file_to_cdn(
            zip_path, content_type="application/zip"
        )
        return JSONResponse({
            'success': True,
            'download_url': download_url,
            'filename': filename,
        })
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={'success': False, 'error': str(e)})
    except Exception as e:
        logger.exception(f"export-all-scenes storyboard={storyboard_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e) or '导出素材包失败'},
        )
    finally:
        if work:
            await asyncio.to_thread(cleanup_dir, work)
