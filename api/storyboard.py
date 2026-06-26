"""
Storyboard API - 故事板后端接口

路由前缀: /api/storyboard
所有 DB 操作均为同步 pymysql，在异步路由中必须用 asyncio.to_thread() 包装。
"""
import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse
from perseids_server.utils.permission import require_permission
from perseids_server.client import async_make_perseids_request

from config.constant import (
    Edition, Action,
    TASK_TYPE_GENERATE_VIDEO, TASK_TYPE_GENERATE_AUDIO,
    TASK_STATUS_QUEUED, AI_TOOL_STATUS_PENDING, AI_AUDIO_STATUS_PENDING,
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
from utils.resource_access import (
    get_user_id_from_header,
    ensure_resource_access,
    ensure_world_access,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/storyboard", tags=["storyboard"])

# update_scene 允许前端直接修改的字段（选中指针由 asset/select 接口管理，不在此处）
ALLOWED_SCENE_UPDATE_FIELDS = {
    'title', 'duration', 'prompt_json', 'video_prompt', 'video_type', 'video_config_json',
}
ALLOWED_DIALOGUE_UPDATE_FIELDS = {
    'character_id', 'text', 'speed', 'volume',
}
VALID_ASSET_TYPES = ('first_frame', 'last_frame', 'video')


# ==================== Helpers ====================

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
            if tool.result_url:
                info['result_url'] = tool.result_url
    return info


async def _attach_dialogues(scenes: list) -> list:
    """为每个分镜附加其对话列表（供前端直接渲染）"""
    for sc in scenes:
        sc['dialogues'] = await asyncio.to_thread(
            StoryboardDialogueModel.list_by_scene, sc['id']
        )
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
        title: str             可选
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

    # 如果关联了剧本，尝试自动拆分分镜
    auto_split_scenes = []
    if script_id:
        script = await asyncio.to_thread(ScriptModel.get_by_id, script_id)
        if script and script.content:
            # 简单拆分：按段落分割（后续可替换为 LLM 智能拆分）
            paragraphs = [p.strip() for p in script.content.split('\n') if p.strip()]
            for i, para in enumerate(paragraphs[:20]):  # 最多 20 个分镜
                auto_split_scenes.append({
                    'title': f'分镜{i + 1}',
                    'duration': 5,
                    'video_type': SceneVideoType.VIDEO,
                    # 每段先作为一句旁白对话，后续可由 LLM 解析出角色台词
                    'dialogues': [
                        {'character_id': None, 'text': para[:200], 'speed': 1.0, 'volume': 100}
                    ],
                })

    # 不存在 → 事务创建（同步函数，asyncio.to_thread 会把同步函数放进线程执行）
    def _create():
        return StoryboardModel.create_with_scenes(
            user_id=user_id,
            world_id=world_id,
            episode_number=episode_number,
            scenes=auto_split_scenes,
            workflow_id=data.get('workflow_id'),
            script_id=script_id,
            title=data.get('title', ''),
            style=defaults['style'],
            style_reference_image=defaults['style_reference_image'],
            workflow_ratio=defaults['workflow_ratio'],
            composition_preference=defaults['composition_preference'],
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


@router.get('/{storyboard_id}')
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
    return JSONResponse({
        'success': True,
        'storyboard': sb.to_dict(),
        'scenes': scenes,
    })


@router.put('/{storyboard_id}')
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


@router.delete('/{storyboard_id}')
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

@router.post('/{storyboard_id}/scene')
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


@router.put('/{storyboard_id}/scene/reorder')
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

    task_type = int(data.get('task_type') or TaskTypeId.GPT_IMAGE_2_EDIT)
    prompt = data.get('prompt') or _compose_image_prompt(scene)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, scene.storyboard_id)
    ratio = data.get('ratio') or (sb.workflow_ratio if sb else None)
    image_size = data.get('image_size')

    # 算力预扣（失败 scheduler 会按 transaction_id 退还）
    config = UnifiedConfigRegistry.get_by_id(task_type)
    computing_power = config.get_computing_power() if config else 0
    transaction_id = str(uuid.uuid4())
    ok, msg = await _deduct_computing_power(request, computing_power, transaction_id)
    if not ok:
        return JSONResponse(status_code=400, content={'error': msg or '算力不足或扣费失败'})

    # 创建 ai_tools + TasksModel（scheduler 的 generate_video 统一处理所有 ai_tools，含图片）
    ai_tool_id = await asyncio.to_thread(
        AIToolsModel.create,
        prompt=prompt, user_id=user_id, type=task_type, ratio=ratio,
        transaction_id=transaction_id, status=AI_TOOL_STATUS_PENDING, image_size=image_size,
    )
    await asyncio.to_thread(
        TasksModel.create,
        task_type=TASK_TYPE_GENERATE_VIDEO, task_id=ai_tool_id, status=TASK_STATUS_QUEUED,
    )

    # 插入资产候选并设为当前选中
    asset_id = await asyncio.to_thread(
        StoryboardSceneAssetModel.create,
        scene_id=scene_id, asset_type=asset_type, ai_tool_id=ai_tool_id,
    )
    await asyncio.to_thread(StoryboardSceneAssetModel.set_selected, scene_id, asset_type, asset_id)
    await asyncio.to_thread(StoryboardSceneModel.update, scene_id, last_modified_user_id=user_id)

    return JSONResponse({
        'success': True,
        'ai_tool_id': ai_tool_id,
        'asset_id': asset_id,
        'asset_type': asset_type,
        'computing_power': computing_power,
        'status': 'submitted',
    })


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
    duration = data.get('duration') or scene.duration
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, scene.storyboard_id)
    ratio = data.get('ratio') or (sb.workflow_ratio if sb else None)

    config = UnifiedConfigRegistry.get_by_id(task_type)
    computing_power = config.get_computing_power(duration=duration) if config else 0
    transaction_id = str(uuid.uuid4())
    ok, msg = await _deduct_computing_power(request, computing_power, transaction_id)
    if not ok:
        return JSONResponse(status_code=400, content={'error': msg or '算力不足或扣费失败'})

    extra_config = json.dumps({'video_type': video_type, 'source': 'storyboard'})
    ai_tool_id = await asyncio.to_thread(
        AIToolsModel.create,
        prompt=prompt, user_id=user_id, type=task_type,
        image_path=image_path, audio_path=audio_path,
        duration=duration, ratio=ratio,
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

    text = data.get('text') or dialogue.text
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
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """AI 对话改图（占位 — 后续接入 LLM SSE 流）"""
    user_id = get_user_id_from_header(user_id)
    scene, err = await _ensure_scene_access(scene_id, user_id, Action.EDIT)
    if err:
        return err

    # TODO: 接入 LLM 对话改图 SSE 流
    return JSONResponse({'success': False, 'error': 'AI 对话功能尚未实现'})


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
        voice_items.append(item)

    return JSONResponse({
        'success': True,
        'first_frame': first_frame,
        'last_frame': last_frame,
        'video': video,
        'dialogues': voice_items,
    })


@router.get('/models')
@require_permission("storyboard:view")
async def get_storyboard_models(
    request: Request,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """
    返回图片 / 图生视频 / 数字人模型列表，供前端模型选择。
    生成接口接收 task_type（= 此处的 task_id）覆盖默认模型。
    """
    user_id = get_user_id_from_header(user_id)

    def _list(category):
        configs = UnifiedConfigRegistry.get_by_category(category)
        return [
            {
                'task_id': c.id,
                'key': c.key,
                'name': c.name,
                'computing_power': c.get_computing_power() if c.computing_power else 0,
                'supported_durations': c.supported_durations or [],
                'default_duration': c.default_duration,
                'supported_ratios': c.supported_ratios or [],
            }
            for c in configs if c.enabled and not c.hidden
        ]

    return JSONResponse({
        'success': True,
        'image_models': _list(TaskCategory.TEXT_TO_IMAGE),
        'video_models': _list(TaskCategory.IMAGE_TO_VIDEO),
        'digital_human_models': _list(TaskCategory.DIGITAL_HUMAN),
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
    return JSONResponse({'success': True, 'selected_audio_id': dialogue_audio_id})


# ==================== 导出操作（占位） ====================

@router.post('/{storyboard_id}/export-full-video')
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


@router.post('/{storyboard_id}/export-all-scenes')
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
