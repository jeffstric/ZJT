"""
Storyboard API - 故事板后端接口

路由前缀: /api/storyboard
所有 DB 操作均为同步 pymysql，在异步路由中必须用 asyncio.to_thread() 包装。
"""
import asyncio
import json
import logging
import math
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse, StreamingResponse
from perseids_server.utils.permission import require_permission
from perseids_server.client import async_make_perseids_request

from config.constant import (
    Edition, Action,
    TASK_TYPE_GENERATE_VIDEO, TASK_TYPE_GENERATE_AUDIO,
    TASK_STATUS_QUEUED, AI_TOOL_STATUS_PENDING, AI_AUDIO_STATUS_PENDING,
    StoryboardAutoGenerateConstants,
    StoryboardAudioGenerateConstants,
    SceneDifficulty,
)
from config.unified_config import SceneVideoType, UnifiedConfigRegistry, TaskTypeId, TaskCategory
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
from utils.resource_access import (
    get_user_id_from_header,
    ensure_resource_access,
    ensure_world_access,
)
from services.storyboard_agent_cli_service import StoryboardCliError
from services.storyboard_agent_command_service import StoryboardAgentCommandService
from services.storyboard_reference_prompt_service import build_reference_legend
from task.audio_task import recalc_scene_duration_if_all_completed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/storyboard", tags=["storyboard"])

# update_scene 允许前端直接修改的字段（选中指针由 asset/select 接口管理，不在此处）
ALLOWED_SCENE_UPDATE_FIELDS = {
    'title', 'duration', 'prompt_json', 'video_prompt', 'video_type', 'video_config_json',
    'difficulty', 'act_name',
}
ALLOWED_DIALOGUE_UPDATE_FIELDS = {
    'character_id', 'text', 'speed', 'volume',
}
VALID_ASSET_TYPES = ('first_frame', 'last_frame', 'video')


# ==================== Helpers ====================

def _auth_header_token(token: Optional[str]) -> str:
    token = (token or '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    return token


async def _resolve_auth_user_id(auth_token: Optional[str]):
    token = _auth_header_token(auth_token)
    if not token:
        return None, JSONResponse(
            status_code=401,
            content={'success': False, 'error_code': 'missing_auth_token', 'error': 'Authorization is required'},
        )
    user_id = await asyncio.to_thread(UserTokensModel.get_user_id_by_token, token)
    if not user_id:
        return None, JSONResponse(
            status_code=401,
            content={'success': False, 'error_code': 'invalid_auth_token', 'error': 'Authorization is invalid or expired'},
        )
    return int(user_id), None


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


def build_storyboard_defaults(world, data: dict) -> dict:
    """Build inherited storyboard defaults without assuming optional world fields."""
    style = getattr(world, 'visual_style', None) if world else None
    return {
        'style': data.get('style', style),
        'workflow_ratio': data.get('workflow_ratio') or '16:9',
        'style_reference_image': getattr(world, 'style_reference_image', None) if world else None,
        'composition_preference': data.get('composition_preference') or (
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
                'video_type': SceneVideoType.VIDEO,
                'video_config': {
                    'shot_type': shot_type,
                    'camera_angle': camera_angle,
                    'camera_movement': shot.get('camera_movement') or '',
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

    transaction_id = str(uuid.uuid4())
    audio_id = AIAudioModel.create(
        text=text,
        user_id=user_id,
        ref_path=ref_path,
        transaction_id=transaction_id,
        emo_control_method=config.get('emo_control_method'),
        emo_weight=config.get('emo_weight'),
        emo_vec=config.get('emo_vec'),
        emo_text=config.get('emo_text'),
        status=AI_AUDIO_STATUS_PENDING,
    )
    TasksModel.create(
        task_type=TASK_TYPE_GENERATE_AUDIO,
        task_id=audio_id,
        status=TASK_STATUS_QUEUED,
    )
    dialogue_audio_id = StoryboardDialogueAudioModel.create(
        dialogue_id=dialogue_id,
        ai_audio_id=audio_id,
    )
    StoryboardDialogueAudioModel.set_selected(dialogue_id, dialogue_audio_id)

    return {
        'success': True,
        'dialogue_id': dialogue_id,
        'scene_id': scene_id,
        'audio_id': audio_id,
        'dialogue_audio_id': dialogue_audio_id,
        'status': 'submitted',
    }


async def _auto_submit_storyboard_dialogue_voiceovers(scenes: list, user_id: int) -> dict:
    """Queue dialogue voiceover tasks after script split without blocking for generation."""
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
) -> str:
    prompt = _scene_prompt_dict(scene)
    prompt_json = json.dumps(prompt, ensure_ascii=False, indent=2)
    first_frame_line = first_frame_url or "无"
    reference_images = reference_images or []
    reference_image_items = reference_image_items or []
    video_input_urls = [str(u).strip() for u in (video_input_urls or []) if str(u).strip()]
    image_mode = (image_mode or 'first_last_frame').strip().lower()
    if image_mode not in ('first_last_frame', 'multi_reference'):
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
        target_intro = "请基于当前分镜画面提示词、视频提示词与用户要求，生成该分镜视频。"
        if video_input_urls:
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
                "必须调用 image_to_video，image_urls 只能使用【图生视频输入图】中的 URL，严禁混入【角色/场景参考说明】中的图，严禁捏造 URL。"
                "不要调用图片生成工具。"
            )
        else:
            video_input_block = "无"
            tool_instruction = (
                "本次目标是生成视频。当前没有任何图生视频输入图，必须调用 generate_text_to_video。"
                "不要调用 image_to_video 或图片生成工具。"
            )
        duration_line = str(int(video_duration_seconds)) if video_duration_seconds else str(scene.duration or 5)
        resolution_line = video_resolution or '模型默认'
        clip_line = '开启（导出时裁到配音时长）' if clip_to_audio_duration else '关闭（导出使用完整视频）'
        video_mode_block = f"""
【视频图片模式】
{image_mode}

【视频生成参数】
- duration_seconds（必须原样传给 image_to_video / generate_text_to_video）：{duration_line}
- resolution：{resolution_line}
- 裁剪至配音时长（仅导出使用，生成时不必处理）：{clip_line}

【图生视频输入图】（image_to_video.image_urls 唯一来源，按顺序）
{video_input_block}
"""
        tool_instruction = (
            tool_instruction
            + f" 调用视频工具时 duration_seconds 必须为 {duration_line}，严禁擅自改时长。"
            + (f" 若工具支持 resolution 参数，传入 {resolution_line}。" if video_resolution else "")
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
    return f"""{target_intro}

【用户要求】
{user_message}

【当前分镜】
- 标题：{scene.title or ''}
- 时长：{scene.duration or 5} 秒
- 全局画风：{getattr(storyboard, 'style', '') or ''}
- 构图倾向：{getattr(storyboard, 'composition_preference', '') or ''}
- 画幅比例：{getattr(storyboard, 'workflow_ratio', '') or ''}
- 已有首帧 URL：{first_frame_line}
{video_mode_block}
【参考图清单】
{reference_block}

【参考图说明】
{reference_legend or '无'}

【当前分镜 prompt_json】
```json
{prompt_json}
```

请严格围绕当前分镜创作，保留角色、场景、道具一致性，并结合全局画风、构图倾向和画幅比例。{tool_instruction} 如果调用 edit_image，edit_image.prompt 末尾必须原样追加【参考图说明】内容，例如“参考图说明：图1是角色：布冯。图2是场景：布冯的房间。”如果调用 image_to_video，也要在视频提示词末尾追加同样的参考图说明。不要加入未出现在当前画面提示词或视频提示词中的角色/道具参考图。提交成功后返回包含 project_ids 的工作总结。"""


class StoryboardImageAgentRunner:
    """Adapter so TaskManager can run storyboard-image ExpertAgent as a task."""

    agent_id = "storyboard_image_agent"

    def __init__(
        self,
        scene_id: int,
        scene_context: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        generation_target: str = "image",
    ):
        self.scene_id = scene_id
        self.scene_context = scene_context
        self.conversation_history = conversation_history or []
        self.generation_target = generation_target if generation_target == "video" else "image"

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

        config = dict(agents_config.get("expert_agents", {}).get("storyboard-image") or {})
        allowed_tools = config.get("allowed_tools") or [
            "generate_text_to_image",
            "edit_image",
            "get_text_to_image_model_info",
            "get_user_computing_power",
            "ask_user",
        ]
        model = self._resolve_storyboard_agent_model(
            config.get("model") or "gemini/gemini-3-flash-preview",
            task.model_id,
        )
        expert = ExpertAgent(
            skill_names=["storyboard-image"],
            model=model,
            allowed_tools=allowed_tools,
            context_from_pm=self.scene_context,
            file_manager=file_manager,
            user_id=str(task.user_id),
            world_id=str(task.world_id),
            auth_token=task.auth_token,
            tool_executor=tool_executor,
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
            task_manager.push_message(task.task_id, "video_task_submitted" if is_video else "image_task_submitted", {
                "scene_id": self.scene_id,
                "project_ids": project_ids,
                "asset_type": "video" if is_video else "first_frame",
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

    # 画风继承：从 World 获取
    world = await asyncio.to_thread(WorldModel.get_by_id, world_id)
    defaults = build_storyboard_defaults(world, data)

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
        items = []
        for c in configs:
            if not c.enabled or c.hidden:
                continue
            item = {
                'task_id': c.id,
                'key': c.key,
                'name': c.name,
                'computing_power': c.get_computing_power() if c.computing_power else 0,
                'supported_durations': c.supported_durations or [],
                'default_duration': c.default_duration,
                'supported_ratios': c.supported_ratios or [],
            }
            # 图生视频 / 文生视频：分辨率 + 图模式能力
            if category in (TaskCategory.IMAGE_TO_VIDEO, TaskCategory.TEXT_TO_VIDEO):
                res_opts, default_res = _video_resolution_options_from_task(c)
                item['supported_video_resolutions'] = res_opts
                item['default_video_resolution'] = default_res
            if category == TaskCategory.IMAGE_TO_VIDEO:
                modes = list(getattr(c, 'supported_image_modes', None) or ['first_last_frame'])
                item['supported_image_modes'] = [str(m) for m in modes]
                item['supports_last_frame'] = bool(getattr(c, 'supports_last_frame', True))
                item['max_multi_ref_images'] = int(getattr(c, 'max_multi_ref_images', None) or 5)
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
        }.get(exc.error_code, 400)
        return JSONResponse(status_code=status_code, content=exc.to_dict())

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
    return JSONResponse({'success': True, 'affected': affected})


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

    try:
        from llm.script_parser import parse_script_to_shots

        parsed_data = await parse_script_to_shots(
            script_content=script.content,
            max_group_duration=data.get('max_group_duration', 15),
            world_id=sb.world_id,
            model=data.get('model') or 'gemini-3-flash-preview',
            temperature=0.5,
            force_medium_shot=bool(data.get('force_medium_shot', False)),
            no_bg_music=bool(data.get('no_bg_music', False)),
            split_multi_dialogue=bool(data.get('split_multi_dialogue', False)),
            language=data.get('language') or '',
            dialogue_language=data.get('dialogue_language') or data.get('language') or '',
            prompt_language=data.get('prompt_language') or data.get('language') or '',
            auth_token=normalized_auth_token,
            vendor_id=int(real_vendor_id) if real_vendor_id else None,
            model_id=int(model_id) if model_id else None,
            enable_thinking=_json_bool(data.get('enable_thinking'), False),
            thinking_effort=data.get('thinking_effort', 'medium'),
        )
    except Exception as e:
        logger.error(f"Failed to parse script for storyboard {storyboard_id}: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={'error': f'剧本解析失败: {str(e)}'})

    if not parsed_data or not parsed_data.get('shot_groups'):
        return JSONResponse(status_code=500, content={'error': '剧本解析未返回可用分镜'})

    # location 资产化：新场景 / 子场景落库并回填真实 DB id，
    # 必须在 build_storyboard_scenes_from_parsed_script 之前执行。
    from services.storyboard_location_bootstrap_service import StoryboardLocationBootstrapService
    location_bootstrap = await asyncio.to_thread(
        StoryboardLocationBootstrapService().bootstrap,
        parsed_data,
        sb.world_id,
        user_id,
    )

    scenes_payload = build_storyboard_scenes_from_parsed_script(
        parsed_data,
        style=sb.style or '',
    )
    if not scenes_payload:
        return JSONResponse(status_code=500, content={'error': '未能从解析结果生成故事板分镜'})

    existing_scenes = await asyncio.to_thread(StoryboardSceneModel.list_by_storyboard, storyboard_id)
    if existing_scenes:
        return JSONResponse(status_code=409, content={'error': '故事板已存在分镜，不能重复生成'})

    try:
        generated_count = await asyncio.to_thread(
            StoryboardModel.create_scenes,
            storyboard_id,
            user_id,
            scenes_payload,
        )
    except Exception as e:
        logger.error(f"Failed to create storyboard scenes from script: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={'error': f'生成分镜失败: {str(e)}'})

    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    scenes = await asyncio.to_thread(StoryboardSceneModel.list_by_storyboard, storyboard_id)
    await _attach_dialogues(scenes)
    _enrich_scene_location_props(scenes)
    audio_auto_generate = await _auto_submit_storyboard_dialogue_voiceovers(scenes, user_id)

    # 子场景九宫格 i2i：按父场景分批提交，父场景图作为输入生成子场景参考图。
    # 非阻塞：异常不影响分镜主流程，子场景首帧生图会等待/降级。
    # 门禁：只要有 auth_token 就尝试（submit_subscene_grids 内部会精确跳过
    # 已有图 / 有运行中任务的子场景，支持补偿重跑）。
    # 兼容旧请求读取 force_overwrite_subscene_grids，但该字段已废弃，不再覆盖已有参考图。
    _legacy_force_overwrite_subscene_grids = bool(data.get('force_overwrite_subscene_grids', False))
    del _legacy_force_overwrite_subscene_grids
    subscene_grid = {'enabled': False, 'submitted_batches': 0, 'warnings': []}
    if normalized_auth_token:
        try:
            from services.storyboard_location_bootstrap_service import StoryboardLocationBootstrapService
            subscene_grid_result = await asyncio.to_thread(
                StoryboardLocationBootstrapService().submit_subscene_grids,
                parsed_data,
                location_bootstrap,
                sb.world_id,
                user_id,
                normalized_auth_token,
                force_overwrite=False,
            )
            subscene_grid = {
                'enabled': True,
                'submitted_batches': subscene_grid_result.get('submitted_batches', 0),
                'submitted_subscene_count': subscene_grid_result.get('submitted_subscene_count', 0),
                'skipped_no_parent_image': subscene_grid_result.get('skipped_no_parent_image', 0),
                'warnings': subscene_grid_result.get('warnings', []),
            }
        except Exception as e:
            logger.warning(f"子场景九宫格提交失败(非阻塞): {e}", exc_info=True)
            subscene_grid = {'enabled': True, 'submitted_batches': 0, 'warnings': [str(e)]}

    if script_id != sb.script_id:
        await asyncio.to_thread(StoryboardModel.update, storyboard_id, script_id=script_id)
        sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)

    return JSONResponse({
        'success': True,
        'storyboard': sb.to_dict(),
        'scenes': scenes,
        'generated_count': generated_count,
        'audio_auto_generate': audio_auto_generate,
        'location_bootstrap': {
            'created_location_count': location_bootstrap.get('created_location_count', 0),
            'reused_location_count': location_bootstrap.get('reused_location_count', 0),
            'warnings': location_bootstrap.get('warnings', []),
        },
        'subscene_grid': subscene_grid,
    })


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
    if task_type:
        try:
            from api.script_writer import set_text_to_image_model_id
            await asyncio.to_thread(
                set_text_to_image_model_id,
                str(user_id),
                str(sb.world_id if sb else scene.storyboard_id),
                int(task_type),
            )
        except Exception as e:
            logger.warning(f"Failed to sync storyboard image model preference: {e}")

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
        )
    except StoryboardCliError as exc:
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
    生成分镜视频（按 scene.video_type：图生视频 / 数字人）。

    - 图生视频：需已选中首帧图片（image_path）。
    - 数字人：音频自动取「当前说话角色」的配音（用 `character.default_voice` 作参考生成的 TTS 结果），
      形象图取该角色 `reference_image`（无则用选中首帧兜底）。

    数据链路：预扣算力 → 创建 ai_tools → TasksModel(GENERATE_VIDEO) → scene_asset(video) + 设选中。

    Body:
        task_type: 可选；图生视频默认 SEEDANCE_2_0，数字人默认 DIGITAL_HUMAN
        prompt: 可选，默认 scene.video_prompt
        duration / ratio: 可选
        character_id: 数字人可选，指定说话角色（不传则取第一个有配音的对话所属角色）
        audio_path: 数字人可选，显式指定音频（默认自动取该角色配音）
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
        task_type = int(data.get('task_type') or TaskTypeId.DIGITAL_HUMAN)
        # 音频：显式 audio_path > 当前说话角色的配音（character.default_voice 生成的 TTS）
        audio_path = data.get('audio_path')
        character_id = data.get('character_id')
        if character_id is not None:
            character_id = int(character_id)
        if not audio_path:
            character_id, audio_path = await _resolve_digital_human_audio(scene_id, character_id)
        if not audio_path:
            return JSONResponse(status_code=400, content={'error': '数字人需要配音：请先生成当前说话角色的配音'})
        # 形象图：角色 reference_image 优先，选中首帧兜底
        image_path = None
        if character_id:
            character = await asyncio.to_thread(CharacterModel.get_by_id, character_id)
            if character and character.reference_image:
                image_path = character.reference_image
        if not image_path:
            if not scene.selected_first_frame_id:
                return JSONResponse(status_code=400, content={'error': '数字人需要角色形象图或选中首帧图片'})
            ff = await asyncio.to_thread(StoryboardSceneAssetModel.get_by_id, scene.selected_first_frame_id)
            if not ff or not ff.result_url:
                return JSONResponse(status_code=400, content={'error': '首帧图片尚未生成完成'})
            image_path = ff.result_url
    else:
        # 图生视频：必须选中首帧
        task_type = int(data.get('task_type') or TaskTypeId.SEEDANCE_2_0_IMAGE_TO_VIDEO)
        audio_path = None
        if not scene.selected_first_frame_id:
            return JSONResponse(status_code=400, content={'error': '请先生成并选中首帧图片'})
        ff = await asyncio.to_thread(StoryboardSceneAssetModel.get_by_id, scene.selected_first_frame_id)
        if not ff or not ff.result_url:
            return JSONResponse(status_code=400, content={'error': '首帧图片尚未生成完成'})
        image_path = ff.result_url

    prompt = data.get('prompt') or scene.video_prompt or ''
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, scene.storyboard_id)
    ratio = data.get('ratio') or (sb.workflow_ratio if sb else None)

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

    extra_payload = {
        'video_type': video_type,
        'source': 'storyboard',
        'clip_to_audio_duration': clip_to_audio_duration,
    }
    if video_resolution:
        extra_payload['resolution'] = video_resolution
    extra_config = json.dumps(extra_payload, ensure_ascii=False)
    ai_tool_id = await asyncio.to_thread(
        AIToolsModel.create,
        prompt=prompt, user_id=user_id, type=task_type,
        image_path=image_path, audio_path=audio_path,
        duration=video_duration, ratio=ratio,
        transaction_id=transaction_id, status=AI_TOOL_STATUS_PENDING,
        extra_config=extra_config,
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
    if image_task_id:
        try:
            from api.script_writer import set_text_to_image_model_id
            await asyncio.to_thread(
                set_text_to_image_model_id,
                str(user_id),
                str(sb.world_id if sb else scene.storyboard_id),
                int(image_task_id),
            )
        except Exception as e:
            logger.warning(f"Failed to sync storyboard image model preference: {e}")
    video_task_id = data.get('video_task_id')
    if video_task_id:
        try:
            from api.script_writer import set_image_to_video_model_id
            await asyncio.to_thread(
                set_image_to_video_model_id,
                str(user_id),
                str(sb.world_id if sb else scene.storyboard_id),
                int(video_task_id),
            )
        except Exception as e:
            logger.warning(f"Failed to sync storyboard video model preference: {e}")

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
    reference_images = scene_generation_context.get("reference_images") or ([first_frame_url] if first_frame_url else [])
    reference_image_items = scene_generation_context.get("reference_image_items") or []

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
    if image_mode not in ('first_last_frame', 'multi_reference'):
        image_mode = 'first_last_frame'

    video_duration_seconds = None
    video_resolution = None
    clip_to_audio_duration = None
    if generation_target == 'video':
        # 视频：image_to_video 只使用前端槽位有序图；角色/场景参考仅作文案说明
        video_input_urls = ordered_slot_urls
        reference_images_for_msg = list(reference_images or [])
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
    else:
        # 图片：兼容旧逻辑——合并用户补充参考图到资产参考
        user_reference_urls = [
            str(u) for u in ordered_slot_urls
            if str(u) not in reference_images
        ]
        if user_reference_urls:
            reference_images = list(reference_images) + user_reference_urls
            existing_item_urls = {it.get('url') for it in reference_image_items if isinstance(it, dict)}
            for idx, url in enumerate(user_reference_urls, start=1):
                if url not in existing_item_urls:
                    reference_image_items.append({
                        'url': url,
                        'label': f'用户上传参考图{idx}',
                        'type': '参考图',
                        'name': '',
                    })
        reference_images_for_msg = reference_images
        reference_image_items_for_msg = reference_image_items
        video_input_urls = None
        task_image_urls = reference_images or None

    selected_first_frame = (
        (scene_generation_context.get("selected_assets") or {}).get("first_frame") or {}
    )
    first_frame_url_for_prompt = selected_first_frame.get("result_url") or first_frame_url

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
    session_id = f"storyboard-{scene_id}-{uuid.uuid4()}"
    token = _normalize_auth_token(auth_token)

    from api.script_writer import task_manager
    task_id = await asyncio.to_thread(
        task_manager.create_task,
        session_id=session_id,
        user_message=agent_message,
        user_id=str(user_id),
        world_id=str(sb.world_id if sb else scene.storyboard_id),
        auth_token=token,
        vendor_id=vendor_id,
        model_id=model_id,
        image_urls=task_image_urls,
        language=data.get('language') or 'zh-CN',
    )
    task = await asyncio.to_thread(task_manager.get_task, task_id)
    if not task:
        return JSONResponse(status_code=500, content={'success': False, 'error': '智能体任务创建失败'})

    runner = StoryboardImageAgentRunner(
        scene_id=scene_id,
        scene_context=agent_message,
        conversation_history=conversation_history,
        generation_target=generation_target,
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

    # 校验 asset 属于该 scene
    asset = await asyncio.to_thread(StoryboardSceneAssetModel.get_by_id, asset_id)
    if not asset or asset.scene_id != scene_id:
        return JSONResponse(status_code=400, content={'error': '资产不属于该分镜'})

    await asyncio.to_thread(
        StoryboardSceneAssetModel.set_selected, scene_id, asset_type, asset_id
    )
    await asyncio.to_thread(
        StoryboardSceneModel.update, scene_id, last_modified_user_id=user_id
    )
    return JSONResponse({'success': True, 'asset_type': asset_type, 'asset_id': asset_id})


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


# ==================== 导出操作（占位） ====================

@router.post('/{storyboard_id:int}/export-full-video')
@require_permission("storyboard:export")
async def export_full_video(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """导出完整视频（占位）"""
    user_id = get_user_id_from_header(user_id)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not sb:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})

    ensure_resource_access(sb, user_id, Action.VIEW, "故事板")

    # TODO: 接入视频导出任务流
    return JSONResponse({'success': False, 'error': '完整视频导出功能尚未实现'})


@router.post('/{storyboard_id:int}/export-all-scenes')
@require_permission("storyboard:export")
async def export_all_scenes(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """导出全部分镜（占位）"""
    user_id = get_user_id_from_header(user_id)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not sb:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})

    ensure_resource_access(sb, user_id, Action.VIEW, "故事板")

    # TODO: 接入分镜批量导出任务流
    return JSONResponse({'success': False, 'error': '分镜导出功能尚未实现'})
