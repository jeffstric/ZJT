"""
Storyboard ↔ Video Workflow 互转 API - 故事板与工作流画布内容互转

路由前缀: /api/storyboard（与 api/storyboard.py 同前缀的独立 router）

转换语义（一次性）：只支持「对方不存在」时的转换。
- POST /from-workflow                工作流画布 → 故事板：按 workflow_id 查找，
  已有关联故事板时直接返回该故事板（不做场景同步）；否则创建故事板并一次性迁移
  分镜帧的首帧图 / 尾帧图 / 视频节点产物。
- POST /{storyboard_id}/to-workflow  故事板 → 工作流画布：已关联画布时直接返回
  该画布（不覆盖）；否则创建画布并一次性带入选中首帧/尾帧/视频资产。

所有 DB 操作均为同步 pymysql，在异步路由中必须用 asyncio.to_thread() 包装。
"""
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse
from perseids_server.utils.auth_identity import check_claimed_user_id, get_auth_user_id
from perseids_server.utils.permission import require_permission

from api.storyboard import (
    build_storyboard_scenes_from_parsed_script,
    build_storyboard_defaults,
    resolve_storyboard_create_ratio,
    _compact_join,
)
from config.constant import Edition, Action
from config.unified_config import SceneVideoType
from model.storyboard import (
    StoryboardModel,
    StoryboardSceneModel,
    StoryboardDialogueModel,
    StoryboardSceneAssetModel,
)
from model.database import (
    execute_query_in_transaction,
    execute_update_in_transaction,
    transaction,
)
from model.video_workflow import VideoWorkflowModel
from model.character import CharacterModel
from model.world import WorldModel
from model.script import ScriptModel
from utils.resource_access import (
    ensure_resource_access,
    ensure_world_access,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/storyboard", tags=["storyboard"])


def _resolve_login_user_id(request: Request, claimed_user_id: Optional[int]):
    """登录身份为属主。X-User-Id 可省略；携带时必须与登录用户一致。"""
    auth_user_id = get_auth_user_id(request)
    if auth_user_id is None:
        return None, JSONResponse(status_code=401, content={'error': '未获取到登录身份，请重新登录'})
    mismatch = check_claimed_user_id(claimed_user_id, auth_user_id)
    if mismatch is not None:
        return None, mismatch
    return auth_user_id, None


class StoryboardConversionError(Exception):
    """转换过程中的业务错误（消息直接透出给前端）。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ============================================================
# 工作流画布 → 故事板
# ============================================================

def _extract_script_meta(nodes: List[Dict]) -> Dict:
    """取第一个剧本节点的元信息（scriptId/原文/解析数据），无剧本节点时返回空骨架。"""
    for node in nodes:
        if node.get('type') != 'script':
            continue
        data = node.get('data') or {}
        parsed = data.get('parsedData')
        return {
            'node_id': node.get('id'),
            'script_id': data.get('scriptId'),
            'script_content': data.get('scriptContent') or '',
            'name': data.get('name') or '',
            'parsed_data': parsed if isinstance(parsed, dict) else {},
        }
    return {'node_id': None, 'script_id': None, 'script_content': '', 'name': '', 'parsed_data': {}}


def _frame_sort_key(node: Dict) -> Tuple:
    """分镜帧排序：优先 shot_number（数值），缺失时按画布位置（y, x）。"""
    shot = (node.get('data') or {}).get('shotJson') or {}
    try:
        shot_number = float(shot.get('shot_number'))
        return (0, shot_number, float(node.get('y') or 0), float(node.get('x') or 0))
    except (TypeError, ValueError):
        return (1, 0.0, float(node.get('y') or 0), float(node.get('x') or 0))


def _usable_asset_url(url: Any) -> str:
    """资产 URL 有效性：http(s) 绝对地址或站内 /upload 相对路径。

    blob:/data: 是本地临时产物，不迁移；站内相对路径交给前端
    normalizeImageUrl 在恢复时补全 origin。
    """
    text = str(url or '').strip()
    if text.startswith(('http://', 'https://', '/')):
        return text
    return ''


_LOCAL_ABS_URL_RE = re.compile(r'^https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(/.+)$')


def _relativize_asset_url(url: Any) -> str:
    """本机绝对 URL（127.0.0.1/localhost 任意端口）转为站内相对路径。

    生成链路写入的资产 URL 可能带生成时的服务地址（如
    http://127.0.0.1:13010/upload/...），换端口打开画布就会裂图；
    相对路径由前端 normalizeImageUrl 按当前页面 origin 补全，天然可移植。
    """
    text = str(url or '').strip()
    m = _LOCAL_ABS_URL_RE.match(text)
    return m.group(1) if m else text


def _collect_frames_from_workflow(workflow_data: Dict) -> Tuple[List[Dict], Dict, Dict[Any, List[str]], Dict[Any, List[str]]]:
    """
    收集画布分镜帧及其产物：
    - 按 shot_group 归组（组间按画布位置，组内按 shot_number，未连线帧归入「未分组」）；
    - frame_videos: {frame_node_id: [视频URL...]}，视频来自普通连线下挂的
      video 类型节点（分镜/幕视频生成产物，见 shot_frame_video_generator.js）；
    - frame_images: {frame_node_id: [图片URL...]}，图片来自普通连线下挂的
      image 类型节点（分镜图生成产物，见 shot_frame_generator.js；抽卡多张时
      全部收集，首张作为选中首帧）。
    """
    nodes = workflow_data.get('nodes') or []
    script_meta = _extract_script_meta(nodes)
    group_nodes: Dict[Any, Dict] = {}
    frame_nodes: Dict[Any, Dict] = {}
    video_nodes: Dict[Any, Dict] = {}
    image_nodes: Dict[Any, Dict] = {}
    for node in nodes:
        node_type = node.get('type')
        if node_type == 'shot_group':
            group_nodes[node.get('id')] = node
        elif node_type == 'shot_frame':
            frame_nodes[node.get('id')] = node
        elif node_type == 'video':
            video_nodes[node.get('id')] = node
        elif node_type == 'image':
            image_nodes[node.get('id')] = node

    frame_to_group: Dict[Any, Any] = {}
    frame_videos: Dict[Any, List[str]] = {}
    frame_images: Dict[Any, List[str]] = {}
    for conn in workflow_data.get('connections') or []:
        to_id, from_id = conn.get('to'), conn.get('from')
        if to_id in frame_nodes and from_id in group_nodes:
            frame_to_group[to_id] = from_id
        # 分镜帧 → 视频节点：分镜生成的视频产物
        if from_id in frame_nodes and to_id in video_nodes:
            url = _relativize_asset_url(_usable_asset_url((video_nodes[to_id].get('data') or {}).get('url')))
            if url:
                frame_videos.setdefault(from_id, []).append(url)
        # 分镜帧 → 图片节点：分镜生成的图片产物（抽卡多张时全部收集，按连线顺序去重）
        if from_id in frame_nodes and to_id in image_nodes:
            url = _relativize_asset_url(_usable_asset_url((image_nodes[to_id].get('data') or {}).get('url')))
            if url:
                urls = frame_images.setdefault(from_id, [])
                if url not in urls:
                    urls.append(url)

    ordered_group_ids = sorted(
        group_nodes,
        key=lambda nid: (float(group_nodes[nid].get('x') or 0), float(group_nodes[nid].get('y') or 0)),
    )
    groups: List[Dict] = []
    assigned = set()
    for gid in ordered_group_ids:
        gnode = group_nodes[gid]
        gdata = gnode.get('data') or {}
        members = sorted(
            [frame_nodes[fid] for fid, owner in frame_to_group.items() if owner == gid],
            key=_frame_sort_key,
        )
        if not members:
            continue
        assigned.update(node.get('id') for node in members)
        groups.append({
            'group_id': gdata.get('groupId') or gdata.get('group_id') or '',
            'group_name': gnode.get('title') or gdata.get('groupName') or '',
            # 组上的轻量剧本引用（故事板转来的画布用它携带角色/道具名册）
            'script_data': gdata.get('scriptData') if isinstance(gdata.get('scriptData'), dict) else {},
            'frames': members,
        })

    orphans = sorted(
        [fnode for fid, fnode in frame_nodes.items() if fid not in assigned],
        key=_frame_sort_key,
    )
    if orphans:
        groups.append({'group_id': 'ungrouped', 'group_name': '未分组', 'frames': orphans})
    return groups, script_meta, frame_videos, frame_images


def _scene_source_key(shot: Dict, scene_index: int) -> str:
    """与 build_storyboard_scenes_from_parsed_script 的 source_shot_key 规则保持一致。"""
    return str(shot.get('shot_id') or f'scene_{scene_index}')


def _build_parsed_data_from_frames(
    groups: List[Dict],
    script_meta: Dict,
    style: str,
    frame_videos: Dict[Any, List[str]],
    frame_images: Optional[Dict[Any, List[str]]] = None,
) -> Tuple[Dict, Dict]:
    """
    把画布分镜帧重建为 parse_script_to_shots 同构的 parsed_data，并收集每帧产物：

        {source_shot_key: {'first_frame': url|'', 'last_frame': url|'',
                           'videos': [url...], 'image_candidates': [url...]}}

    首帧图来源优先级：分镜帧自带 imageUrl > 连线 image 节点（原生"生成分镜图"
    产物只写图片节点）；连线全部图片作为候选（抽卡多张时首张选中）。

    角色名解析优先级：剧本节点 parsedData.characters（parsed id 保真）>
    shot.db_character_info（db id 兜底追加）。台词缺 character_id 时按名回填。
    """
    parsed = script_meta.get('parsed_data') or {}
    # 剧本节点缺失（或其解析数据为空）时，回退用分镜组 scriptData 携带的角色/道具名册
    # （故事板转画布时写入；见 _build_workflow_data_from_storyboard）
    group_script_characters: List[Dict] = []
    group_script_props: List[Dict] = []
    seen_group_char_ids = set()
    seen_group_prop_ids = set()
    for group in groups:
        script_data = group.get('script_data') or {}
        for c in script_data.get('characters') or []:
            if not isinstance(c, dict) or c.get('id') is None:
                continue
            key = str(c.get('id'))
            if key not in seen_group_char_ids:
                seen_group_char_ids.add(key)
                group_script_characters.append(dict(c))
        for p in script_data.get('props') or []:
            if not isinstance(p, dict) or p.get('id') is None:
                continue
            key = str(p.get('id'))
            if key not in seen_group_prop_ids:
                seen_group_prop_ids.add(key)
                group_script_props.append(dict(p))

    characters: List[Dict] = [dict(c) for c in (parsed.get('characters') or []) if isinstance(c, dict)]
    if not characters:
        characters = group_script_characters
    raw_props = parsed.get('props') if parsed.get('props') else group_script_props
    known_names = {str(c.get('name') or '') for c in characters}

    # 先扫一遍所有 shot，补齐 db_character_info 兜底角色
    all_shots = []
    for group in groups:
        for fnode in group['frames']:
            shot = (fnode.get('data') or {}).get('shotJson')
            if isinstance(shot, dict):
                all_shots.append(shot)
    for shot in all_shots:
        for info in shot.get('db_character_info') or []:
            if not isinstance(info, dict):
                continue
            db_id, name = info.get('db_character_id'), str(info.get('db_character_name') or '').strip()
            if db_id is None or not name or name in known_names:
                continue
            characters.append({'id': str(db_id), 'character_db_id': db_id, 'name': name})
            known_names.add(name)

    # name → parsed id 映射（供台词 character_id 回填）
    name_to_pid = {
        str(c.get('name') or ''): str(c.get('id'))
        for c in characters if c.get('id') is not None
    }
    resolvable_pids = set(name_to_pid.values())

    shot_groups: List[Dict] = []
    assets: Dict[str, Dict] = {}
    scene_index = 0
    for group in groups:
        shots = []
        for fnode in group['frames']:
            data = fnode.get('data') or {}
            raw_shot = data.get('shotJson')
            if not isinstance(raw_shot, dict):
                continue
            # 深拷贝，避免污染调用方数据
            shot = json.loads(json.dumps(raw_shot, ensure_ascii=False))
            scene_index += 1
            # 台词缺 character_id（工作流 shotJson 常见只有 character_name）时按名回填
            for dialogue in shot.get('dialogue') or []:
                if not isinstance(dialogue, dict) or dialogue.get('character_id') is not None:
                    continue
                pid = name_to_pid.get(str(dialogue.get('character_name') or '').strip())
                if pid is not None:
                    dialogue['character_id'] = pid
            # characters_present 含无法解析的 parsed id 时，退化为 db_character_info 的 db id
            present = [str(p) for p in (shot.get('characters_present') or [])]
            if not all(p in resolvable_pids for p in present):
                fallback_ids = [
                    str(info.get('db_character_id'))
                    for info in (shot.get('db_character_info') or [])
                    if isinstance(info, dict) and info.get('db_character_id') is not None
                    and str(info.get('db_character_id')) in resolvable_pids
                ]
                if fallback_ids:
                    shot['characters_present'] = fallback_ids
            shots.append(shot)
            key = _scene_source_key(shot, scene_index)
            # 候选首帧：分镜帧自带图优先，连线 image 节点按连线顺序追加（去重）
            candidates: List[str] = []
            own_image = _relativize_asset_url(_usable_asset_url(data.get('imageUrl')))
            if own_image:
                candidates.append(own_image)
            for url in (frame_images or {}).get(fnode.get('id')) or []:
                if url not in candidates:
                    candidates.append(url)
            frame_assets: Dict = {
                'first_frame': candidates[0] if candidates else '',
                'last_frame': _relativize_asset_url(_usable_asset_url(data.get('lastFrameUrl'))),
                'videos': [],
                'image_candidates': candidates,
            }
            for vid in (fnode.get('id'),):
                for url in (frame_videos.get(vid) or []):
                    if url not in frame_assets['videos']:
                        frame_assets['videos'].append(url)
            assets[key] = frame_assets
        if shots:
            shot_groups.append({
                'group_id': group.get('group_id') or '',
                'group_name': group.get('group_name') or '',
                'shots': shots,
            })

    parsed_data = {
        'characters': characters,
        'locations': parsed.get('locations') or [],
        'props': raw_props or [],
        'style': parsed.get('style') or style or '',
        'shot_groups': shot_groups,
    }
    return parsed_data, assets


def _create_scenes_with_assets(
    storyboard_id: int,
    user_id: int,
    payloads: List[Dict],
    assets: Dict[str, Dict],
) -> int:
    """创建场景 + 台词 + 资产（一次性转换，无 upsert）。

    资产按 source_shot_key 关联：
    - first_frame（分镜帧自带图 + 连线图片节点，抽卡多张全收）→ 逐个建资产，选中第一张；
    - last_frame（视频尾帧 lastFrameUrl）→ 建资产并选中；
    - videos（连线下挂 video 节点产物）→ 逐个建资产，选中第一个。
    """
    created = 0
    for i, payload in enumerate(payloads):
        key = str(payload.get('source_shot_key') or '')
        scene_id = StoryboardSceneModel.create(
            storyboard_id,
            sort_order=float(i),
            title=payload.get('title') or '分镜',
            duration=payload.get('duration') or 5,
            prompt_json=payload.get('prompt') or {},
            video_prompt=payload.get('video_prompt'),
            video_type=payload.get('video_type') or SceneVideoType.VIDEO,
            audio_embedded=payload.get('audio_embedded'),
            video_config_json=payload.get('video_config') or {},
            difficulty=payload.get('difficulty'),
            act_name=payload.get('act_name'),
            last_modified_user_id=user_id,
            source_shot_key=key or None,
        )
        for j, d in enumerate(payload.get('dialogues') or []):
            StoryboardDialogueModel.create(
                scene_id,
                sort_order=float(j),
                character_id=d.get('character_id'),
                text=d.get('text'),
                speed=d.get('speed', 1.0),
                volume=d.get('volume', 100),
                emo_vec=d.get('emo_vec'),
                last_modified_user_id=user_id,
            )

        frame_assets = assets.get(key) or {}
        for fi, image_url in enumerate(frame_assets.get('image_candidates') or []):
            asset_id = StoryboardSceneAssetModel.create(scene_id, 'first_frame', result_url=image_url)
            if fi == 0:
                StoryboardSceneAssetModel.set_selected(scene_id, 'first_frame', asset_id)
        last_frame = frame_assets.get('last_frame') or ''
        if last_frame:
            asset_id = StoryboardSceneAssetModel.create(scene_id, 'last_frame', result_url=last_frame)
            StoryboardSceneAssetModel.set_selected(scene_id, 'last_frame', asset_id)
        for vi, video_url in enumerate(frame_assets.get('videos') or []):
            asset_id = StoryboardSceneAssetModel.create(scene_id, 'video', result_url=video_url)
            if vi == 0:
                StoryboardSceneAssetModel.set_selected(scene_id, 'video', asset_id)
        created += 1

    StoryboardModel.recalc_total_duration(storyboard_id)
    return created


def _parse_workflow_data(workflow) -> Dict:
    data = workflow.workflow_data
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (TypeError, ValueError):
            data = {}
    return data if isinstance(data, dict) else {}


def _resolve_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _convert_workflow_to_storyboard(workflow, user_id: int) -> Dict:
    """同步转换主体（运行在线程池）：一次性创建故事板 + 场景 + 资产迁移。

    以 video_workflow 行锁串行化同一画布的并发转换：锁内复查
    get_by_workflow_id，第二个并发请求会看到第一个已建好的故事板并直接返回，
    避免同一画布转换出多个故事板。
    """
    with transaction() as conn:
        execute_query_in_transaction(
            conn,
            "SELECT id FROM video_workflow WHERE id = %s FOR UPDATE",
            (workflow.id,),
            fetch_one=True,
        )
        storyboard = StoryboardModel.get_by_workflow_id(user_id, workflow.id)
        if storyboard:
            # 一次性转换语义：目标已存在时不做任何同步，前端直接打开
            return {'storyboard_id': storyboard.id, 'created': False}

        workflow_data = _parse_workflow_data(workflow)
        groups, script_meta, frame_videos, frame_images = _collect_frames_from_workflow(workflow_data)
        parsed_data, assets = _build_parsed_data_from_frames(
            groups, script_meta, workflow.style or '', frame_videos, frame_images)
        payloads = build_storyboard_scenes_from_parsed_script(parsed_data, style=workflow.style or '')

        world_id = _resolve_int(workflow.default_world_id)
        if not world_id:
            raise StoryboardConversionError('画布尚未关联世界，请先在画布顶部选择世界后再转换故事板')
        if not payloads:
            raise StoryboardConversionError('画布上没有可转换的分镜节点，请先拆分剧本生成分镜')
        ensure_world_access(world_id, user_id, Action.VIEW)

        episode_number = StoryboardModel.max_episode_number(user_id, world_id) + 1
        script_id = _resolve_int(script_meta.get('script_id'))
        workflow_ratio = (
            str(workflow.workflow_ratio or '').strip()
            or resolve_storyboard_create_ratio(user_id, world_id, {})
        )
        world = WorldModel.get_by_id(world_id)
        defaults = build_storyboard_defaults(world, {}, workflow_ratio=workflow_ratio)
        sb_id = StoryboardModel.create_with_scenes(
            user_id=user_id,
            world_id=world_id,
            episode_number=episode_number,
            scenes=[],
            workflow_id=workflow.id,
            script_id=script_id,
            title=f"{workflow.name or '工作流'}故事板",
            style=workflow.style or defaults['style'],
            style_reference_image=workflow.style_reference_image or defaults['style_reference_image'],
            workflow_ratio=workflow_ratio,
            composition_preference=defaults['composition_preference'],
        )
        scene_count = _create_scenes_with_assets(sb_id, user_id, payloads, assets)
    return {'storyboard_id': sb_id, 'created': True, 'scene_count': scene_count}


@router.post('/from-workflow')
@require_permission("storyboard:update")
async def storyboard_from_workflow(
    request: Request,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """工作流画布 → 故事板（一次性：已有关联故事板时直接返回，不重复转换）。"""
    user_id, auth_error = _resolve_login_user_id(request, user_id)
    if auth_error is not None:
        return auth_error
    data = await request.json()

    workflow_id = _resolve_int(data.get('workflow_id'))
    if not workflow_id:
        return JSONResponse(status_code=400, content={'error': 'workflow_id is required'})

    workflow = await asyncio.to_thread(VideoWorkflowModel.get_by_id, workflow_id)
    if not workflow:
        return JSONResponse(status_code=404, content={'error': '工作流不存在'})
    # 独立空间模式才检查属主，共享空间所有人可访问（与 GET /api/video-workflow/{id} 一致）
    if Edition.is_space_isolated() and getattr(workflow, 'user_id', None) != user_id:
        return JSONResponse(status_code=403, content={'error': '无权限访问该工作流'})

    try:
        result = await asyncio.to_thread(_convert_workflow_to_storyboard, workflow, user_id)
    except StoryboardConversionError as e:
        return JSONResponse(status_code=e.status_code, content={'error': e.message})
    except Exception as e:
        logger.error(f"[storyboard-conversion] from-workflow {workflow_id} failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={'error': f'转换失败: {str(e)}'})

    return JSONResponse({'success': True, **result})


# ============================================================
# 故事板 → 工作流画布
# ============================================================

def _load_json_field(value) -> Dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def _scene_to_shot(scene: Dict, shot_number: int, characters: Dict[int, str]) -> Tuple[Dict, List[Dict], List[Dict]]:
    """故事板场景 → 工作流 shotJson。返回 (shot, script_props, db_character_info)。"""
    prompt_json = _load_json_field(scene.get('prompt_json'))
    video_config = _load_json_field(scene.get('video_config_json'))
    location = prompt_json.get('location') or {}

    # 角色引用：台词角色 + character_desc 中的世界角色名（db id 精确匹配）
    db_character_info: List[Dict] = []
    seen_db: set = set()

    def _add_character(db_id: int, name: str):
        if db_id in seen_db:
            return
        seen_db.add(db_id)
        db_character_info.append({
            'character_id': str(db_id),
            'db_character_id': db_id,
            'db_character_name': name,
        })

    dialogue_entries = []
    for d in scene.get('dialogues') or []:
        if not isinstance(d, dict):
            continue
        text = str(d.get('text') or '').strip()
        if not text:
            continue
        char_db_id = _resolve_int(d.get('character_id'))
        char_name = characters.get(char_db_id) if char_db_id else None
        if char_db_id and char_name:
            _add_character(char_db_id, char_name)
        entry = {'character_name': char_name or '旁白', 'text': text}
        if char_db_id:
            entry['character_id'] = str(char_db_id)
        dialogue_entries.append(entry)

    world_name_to_id = {name: cid for cid, name in characters.items()}
    for raw_name in str(prompt_json.get('character_desc') or '').split('、'):
        name = raw_name.strip()
        db_id = world_name_to_id.get(name)
        if name and db_id:
            _add_character(db_id, name)

    script_props: List[Dict] = []
    for p in (prompt_json.get('props') or []):
        if not isinstance(p, dict):
            continue
        prop_id = p.get('id') if p.get('id') is not None else p.get('db_id')
        script_props.append({
            'id': prop_id,
            'name': p.get('name') or '',
            'props_db_id': p.get('db_id') or p.get('props_db_id') or prop_id,
        })

    scene_desc = str(prompt_json.get('scene_desc') or '').strip()
    shot = {
        # 沿用场景原 source_shot_key（拆分/工作流来源）保证键稳定可追溯；
        # 手工场景无 key 时用 sb_{scene_id}（sb_ 前缀避免与拆分 shot_id 冲突）
        'shot_id': str(scene.get('source_shot_key') or f"sb_{scene['id']}"),
        'shot_number': shot_number,
        'duration': _safe_duration(scene.get('duration')),
        'location_name': location.get('name') or '',
        'db_location_id': location.get('id'),
        'shot_type': video_config.get('shot_type') or '',
        'camera_angle': video_config.get('camera_angle') or '',
        'camera_movement': video_config.get('camera_movement') or '',
        'description': scene.get('video_prompt') or scene_desc or scene.get('title') or '',
        'scene_detail': scene_desc,
        # 携带场景显式类型（含用户手动切换的数字人/视频选择）：
        # 反向转换时 resolve_scene_video_type 经 _llm_presentation 优先采信，
        # 避免手动选择在往返中被规则重新推导覆盖
        'video_type': scene.get('video_type') or '',
        # 生图提示词与故事板组词规则对齐（perspective + scene_desc + character_desc）
        'opening_frame_description': _compact_join(
            [prompt_json.get('perspective'), scene_desc, prompt_json.get('character_desc')], '，'),
        'dialogue': dialogue_entries,
        'props_present': [str(p['id']) for p in script_props if p['id'] is not None],
        'characters_present': [str(info['db_character_id']) for info in db_character_info],
        'db_character_info': db_character_info,
    }
    return shot, script_props, db_character_info


def _build_workflow_data_from_storyboard(
    storyboard,
    scenes: List[Dict],
    characters: Dict[int, str],
    script,
) -> Dict:
    """故事板 → serializeWorkflow 同构的 workflow_data（剧本/分镜组/分镜帧/视频节点）。"""
    script_content = str(getattr(script, 'content', '') or '') if script else ''
    script_title = str(getattr(script, 'title', '') or '') if script else ''

    # 按 act_name 分桶（保持场景顺序）
    group_order: List[str] = []
    group_map: Dict[str, List[Dict]] = {}
    for scene in scenes:
        act = str(scene.get('act_name') or '').strip() or '分镜组'
        if act not in group_map:
            group_map[act] = []
            group_order.append(act)
        group_map[act].append(scene)

    nodes: List[Dict] = []
    connections: List[Dict] = []
    first_frame_connections: List[Dict] = []
    next_node_id = 1
    next_conn_id = 1
    next_first_frame_conn_id = 1

    # 剧本节点（有关联剧本且能取到内容时创建）
    script_node_id = None
    if script_content:
        script_node_id = next_node_id
        next_node_id += 1
        nodes.append({
            'id': script_node_id,
            'type': 'script',
            'title': f"剧本：{script_title or storyboard.title or '未命名'}",
            'x': 120,
            'y': 160,
            'data': {
                'scriptId': getattr(script, 'id', None),
                'scriptContent': script_content,
                'name': script_title,
            },
        })

    all_props: List[Dict] = []
    all_characters: List[Dict] = []
    seen_prop_ids = set()
    shot_number = 0
    # 分镜帧节点高度远超 900px（三列布局），间距必须大于节点实际高度，
    # 否则节点互相叠压——拖动图片节点整理布局时会误触到邻近分镜帧的
    # 首帧/尾帧端口（applyLastFrameFromImage），把图片误设为尾帧。
    # 组间距按组内帧数动态累进（游标布局），保证任意分组下节点都不重叠。
    frame_gap_y = 960
    group_gap_extra_y = 140
    cursor_y = 160

    for gi, act in enumerate(group_order):
        act_scenes = group_map[act]
        group_node_id = next_node_id
        next_node_id += 1
        group_y = cursor_y

        group_shots = []
        frame_entries = []
        for scene in act_scenes:
            shot_number += 1
            shot, script_props, db_character_info = _scene_to_shot(scene, shot_number, characters)
            group_shots.append(shot)
            for prop in script_props:
                prop_key = str(prop.get('id'))
                if prop_key not in seen_prop_ids:
                    seen_prop_ids.add(prop_key)
                    all_props.append(prop)
            for info in db_character_info:
                if not any(c.get('id') == str(info['db_character_id']) for c in all_characters):
                    all_characters.append({
                        'id': str(info['db_character_id']),
                        'name': info['db_character_name'],
                        'character_db_id': info['db_character_id'],
                    })
            frame_entries.append((shot, scene))

        # 轻量 scriptData：与前端 buildSlimScriptData 保留的引用字段对齐
        slim_script_data = {
            'title': script_title or storyboard.title or '',
            'props': all_props,
            'characters': all_characters,
        }
        nodes.append({
            'id': group_node_id,
            'type': 'shot_group',
            'title': act,
            'x': 760,
            'y': group_y,
            'data': {
                'groupId': f'sb_g_{gi + 1}',
                'group_id': f'sb_g_{gi + 1}',
                'groupName': act,
                'shots': group_shots,
                'scriptData': slim_script_data,
                'scriptNodeId': script_node_id if script_node_id is not None else '',
                'scriptContent': script_content,
                'gridPreview': {},
            },
        })
        if script_node_id is not None:
            connections.append({'id': next_conn_id, 'from': script_node_id, 'to': group_node_id})
            next_conn_id += 1

        for fj, (shot, scene) in enumerate(frame_entries):
            frame_node_id = next_node_id
            next_node_id += 1
            frame_y = group_y + fj * frame_gap_y
            # 首帧进 previewImageUrl（分镜「视频首帧」槽）。
            # 不要写入 imageUrl：该字段会在「视频尾帧」控件下方再画一张无标题图，
            # 打开画布时看起来就像把首帧当成了尾帧。
            first_frame_url = _relativize_asset_url(str(scene.get('first_frame_url') or '').strip())
            last_frame_url = _relativize_asset_url(str(scene.get('last_frame_url') or '').strip())
            nodes.append({
                'id': frame_node_id,
                'type': 'shot_frame',
                'title': f"分镜{shot['shot_number']}",
                'x': 1420,
                'y': frame_y,
                'data': {
                    'shotJson': shot,
                    'imageUrl': '',
                    'previewImageUrl': first_frame_url,
                    'lastFrameUrl': last_frame_url,
                },
            })
            connections.append({'id': next_conn_id, 'from': group_node_id, 'to': frame_node_id})
            next_conn_id += 1

            # 选中首帧 → 独立 image 节点并普通连线（与画布原生分镜图产物形态一致）
            if first_frame_url:
                image_node_id = next_node_id
                next_node_id += 1
                image_name = f"分镜{shot['shot_number']}图"
                nodes.append({
                    'id': image_node_id,
                    'type': 'image',
                    'title': image_name,
                    'x': 2320,
                    'y': frame_y,
                    'data': {
                        'url': first_frame_url,
                        'preview': first_frame_url,
                        'name': image_name,
                    },
                })
                connections.append({'id': next_conn_id, 'from': frame_node_id, 'to': image_node_id})
                next_conn_id += 1
                # 首帧连线画到分镜节点「视频首帧」端口（.first-frame-port）。
                # 视频节点没有该端口，连到视频上线画不出来。
                first_frame_connections.append(
                    {'id': next_first_frame_conn_id, 'from': image_node_id, 'to': frame_node_id})
                next_first_frame_conn_id += 1

            # 选中视频 → 独立 video 节点并普通连线（与画布上分镜生成视频的产物形态一致）
            video_url = _relativize_asset_url(str(scene.get('video_url') or '').strip())
            if video_url:
                video_node_id = next_node_id
                next_node_id += 1
                nodes.append({
                    'id': video_node_id,
                    'type': 'video',
                    'title': '分镜视频',
                    'x': 2760,
                    'y': frame_y,
                    'data': {
                        'url': video_url,
                        'name': f"分镜{shot['shot_number']}视频",
                        'project_id': None,
                    },
                })
                connections.append({'id': next_conn_id, 'from': frame_node_id, 'to': video_node_id})
                next_conn_id += 1

        # 游标推进：下一组从本组最后一帧之下留出间隔开始
        cursor_y = group_y + len(act_scenes) * frame_gap_y + group_gap_extra_y

    return {
        'version': '1.0',
        'ratio': str(storyboard.workflow_ratio or '16:9'),
        'defaultWorldId': storyboard.world_id,
        'viewport': {'panX': 0, 'panY': 0, 'zoom': 1},
        'nextNodeId': next_node_id,
        'nextConnId': next_conn_id,
        'nextImgConnId': 1,
        'nextFirstFrameConnId': next_first_frame_conn_id,
        'nextLastFrameConnId': 1,
        'nextVideoConnId': 1,
        'nextReferenceConnId': 1,
        'nextAudioConnId': 1,
        'nextScriptId': 2 if script_node_id is not None else 1,
        'groups': [],
        'nextGroupId': 1,
        'nodes': nodes,
        'connections': connections,
        'imageConnections': [],
        'firstFrameConnections': first_frame_connections,
        'lastFrameConnections': [],
        'videoConnections': [],
        'referenceConnections': [],
        'audioConnections': [],
        'timeline': {
            'clips': [],
            'audioClips': [],
            'pillars': [],
            'nextClipId': 1,
            'nextAudioClipId': 1,
        },
        'style': {
            'name': storyboard.style or '',
            'referenceImageUrl': storyboard.style_reference_image or '',
            'compositionPreference': storyboard.composition_preference or '',
        },
    }


def _safe_duration(value, default: float = 5.0) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return default
    return duration if duration > 0 else default


def _load_world_characters(world_id) -> Dict[int, str]:
    """世界角色 db id → 名称映射（台词/角色描述解析用）。"""
    characters: Dict[int, str] = {}
    if not world_id:
        return characters
    result = CharacterModel.list_by_world(world_id, page=1, page_size=500) or {}
    for c in result.get('data') or []:
        cid = _resolve_int(c.get('id'))
        if cid is not None and c.get('name'):
            characters[cid] = str(c.get('name'))
    return characters


def _convert_storyboard_to_workflow(storyboard, user_id: int) -> Dict:
    """同步转换主体（运行在线程池）：构建画布 JSON、创建画布并回写关联。

    以 storyboard 行锁串行化同一故事板的并发转换：锁内复查 workflow_id 关联
    （画布存在 → 直接返回；画布被删 → 锁内重建回写，悬空引用就此收敛），
    避免并发请求为同一故事板创建出多个画布。
    """
    with transaction() as conn:
        row = execute_query_in_transaction(
            conn,
            "SELECT workflow_id FROM storyboard WHERE id = %s FOR UPDATE",
            (storyboard.id,),
            fetch_one=True,
        )
        linked_id = _resolve_int((row or {}).get('workflow_id'))
        if linked_id:
            linked = VideoWorkflowModel.get_by_id(linked_id)
            if linked and (not Edition.is_space_isolated() or linked.user_id == user_id):
                return {'workflow_id': linked.id, 'created': False}
            # 悬空引用（画布已删除）：继续走重建，最后回写覆盖

        scenes = StoryboardSceneModel.list_by_storyboard(storyboard.id)
        if not scenes:
            raise StoryboardConversionError('故事板上没有可转换的分镜，请先生成分镜')
        for scene in scenes:
            scene['dialogues'] = StoryboardDialogueModel.list_by_scene(scene['id'])

        script = None
        if storyboard.script_id:
            script = ScriptModel.get_by_id(storyboard.script_id)
        characters = _load_world_characters(storyboard.world_id)

        workflow_data = _build_workflow_data_from_storyboard(storyboard, scenes, characters, script)
        workflow_id = VideoWorkflowModel.create(
            name=f"{storyboard.title or '故事板'}画布",
            user_id=user_id,
            description='由故事板转换生成',
            workflow_data=workflow_data,
            style=storyboard.style,
            style_reference_image=storyboard.style_reference_image,
            default_world_id=storyboard.world_id,
            workflow_ratio=storyboard.workflow_ratio,
        )
        execute_update_in_transaction(
            conn,
            "UPDATE storyboard SET workflow_id = %s WHERE id = %s",
            (workflow_id, storyboard.id),
        )
    return {'workflow_id': workflow_id, 'created': True}


@router.post('/{storyboard_id:int}/to-workflow')
@require_permission("video_workflow:create")
async def storyboard_to_workflow(
    request: Request,
    storyboard_id: int,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """故事板 → 工作流画布（一次性：已关联画布时直接返回，不覆盖画布内容）。"""
    user_id, auth_error = _resolve_login_user_id(request, user_id)
    if auth_error is not None:
        return auth_error
    storyboard = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not storyboard:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})
    ensure_resource_access(storyboard, user_id, Action.EDIT, "故事板")

    # 一次性转换语义：已关联画布 → 直接返回该画布（画布上可能已有手工内容，不覆盖）
    linked_workflow_id = _resolve_int(storyboard.workflow_id)
    if linked_workflow_id:
        linked = await asyncio.to_thread(VideoWorkflowModel.get_by_id, linked_workflow_id)
        if linked and (not Edition.is_space_isolated() or linked.user_id == user_id):
            return JSONResponse({
                'success': True,
                'workflow_id': linked.id,
                'created': False,
            })

    try:
        result = await asyncio.to_thread(_convert_storyboard_to_workflow, storyboard, user_id)
    except StoryboardConversionError as e:
        return JSONResponse(status_code=e.status_code, content={'error': e.message})
    except Exception as e:
        logger.error(f"[storyboard-conversion] to-workflow {storyboard_id} failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={'error': f'转换失败: {str(e)}'})

    return JSONResponse({'success': True, **result})
