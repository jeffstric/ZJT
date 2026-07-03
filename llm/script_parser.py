"""
剧本解析模块

将文字剧本解析为结构化的分镜数据
"""

import json
import re
from typing import Dict, Any, Optional, List, Tuple
from llm.llm_client_factory import get_llm_client

# ============================================================
# 日志开关配置
# ============================================================
# 设置为 True 启用详细日志记录（保存所有LLM请求和响应到文件）
# 设置为 False 禁用文件日志记录（仅保留控制台日志）
ENABLE_SCRIPT_PARSER_LOGGING = True

def _save_log_file(log_dir, filename, content):
    """
    条件性保存日志文件的辅助函数
    仅在ENABLE_SCRIPT_PARSER_LOGGING为True时保存文件
    """
    if ENABLE_SCRIPT_PARSER_LOGGING and log_dir:
        with open(log_dir / filename, 'w', encoding='utf-8') as f:
            if isinstance(content, dict):
                json.dump(content, f, ensure_ascii=False, indent=2)
            else:
                f.write(content)

# 剧本解析的系统提示词
SCRIPT_PARSER_SYSTEM_PROMPT = """你是一个专业的影视剧本分析师和分镜师,擅长将剧本拆解为人物、场景和分镜。
你需要根据输入的剧本内容,输出结构化的JSON格式数据。

输出要求：
1. 必须严格按照指定的JSON格式输出
2. 分镜组默认每个15秒,可根据剧情需要调整
3. 人物信息要完整,包括角色定位和描述
4. **【重要警告】在分镜描述中严禁描写人物外貌特征**：系统的角色库中已有完整的外貌信息，在所有分镜相关字段（opening_frame_description、scene_detail、description、action等）中，只需要提及角色名称（用【【角色名】】格式），不要描述角色的外貌、服装、发型、身材等任何外观特征，否则可能与角色库的外貌信息冲突
5. 场景信息要详细,包括时间、天气、氛围、环境音、背景音乐等
5. **场景支持嵌套层级**：通过parent_id和level字段表示场景的层级关系
   - parent_id为null表示顶层场景（如"神明竞技场"）
   - parent_id指向父场景id表示子场景（如"竞技场看台"的parent_id指向"神明竞技场"的id）
   - level表示层级深度，顶层为0，每下一级加1
6. **场景与数据库关联**：每个location必须包含location_db_id字段
   - 如果剧本中的场景与数据库中已有场景匹配，则将location_db_id设置为数据库场景的ID（必须是数据库列表中实际存在的ID）
   - 如果是新场景，不在数据库中，则location_db_id必须设置为null，不能随意编造ID
   - 匹配时考虑场景名称和描述的相似性，不需要完全一致
   - **【警告】严禁编造不存在的location_db_id，如果不确定是否匹配，必须设置为null**
7. **道具与数据库关联**：每个props必须包含props_db_id字段
   - 如果剧本中的道具与数据库中已有道具匹配，则将props_db_id设置为数据库道具的ID（必须是数据库列表中实际存在的ID）
   - 如果是新道具，不在数据库中，则props_db_id必须设置为null，不能随意编造ID
   - 匹配时考虑道具名称和描述的相似性，不需要完全一致
   - **【警告】严禁编造不存在的props_db_id，如果不确定是否匹配，必须设置为null**
8. **角色与数据库关联**：每个character必须包含character_db_id字段
   - 如果剧本中的角色与数据库中已有角色匹配，则将character_db_id设置为数据库角色的ID（必须是数据库列表中实际存在的ID）
   - **【重要】当角色与数据库匹配时，name字段必须使用数据库中的角色名称（如"阿方索戴维斯_AlphonsoDavies"），而不是剧本中的名称（如"布冯"）**
   - 如果是新角色，不在数据库中，则character_db_id必须设置为null，name使用剧本中的名称
   - 匹配时考虑角色名称和描述的相似性，不需要完全一致
   - **【警告】严禁编造不存在的character_db_id，如果不确定是否匹配，必须设置为null**
9. **分镜中的道具关联**：每个shot必须包含props_present字段
   - props_present是一个数组，包含该镜头中出现的道具ID（对应props数组中的id字段）
   - 如果镜头中没有道具出现，设置为空数组[]
   - 只包含在该镜头画面中实际出现或被使用的道具
10. 分镜要包含镜头类型、运动方式、对话、动作等详细信息
11. opening_frame_description是最关键字段,用于AI生成首帧图像,必须非常详细描述镜头起始画面（包括人物位置、姿态、表情、场景布局、光线效果、构图信息等）
12. 确保所有ID引用关系正确（如shot中的location_id、character_id、props_present要对应）
13. 只输出纯JSON内容,不要添加```json```标记或任何解释性文字
14. **【重要】在shot节点的所有文本字段中,只要涉及角色名称,必须用【【角色名】】格式包裹,便于后续匹配角色库。注意：只对角色名称使用【【】】包裹,场景名称、地点名称和道具名称不要使用【【】】包裹**
15. **【重要】在shot节点的所有画面/视频提示文本字段中,只要涉及道具名称,道具名称必须用〖〖道具名〗〗格式包裹,便于后续匹配道具库；props_present字段仍使用道具ID。正确示例：〖〖公文包〗〗【【德保罗】】。**
16. 每个shot必须有明确的narrative_purpose，说明这个镜头为什么存在，且必须具体到视听手段

ID格式规范：
- shot_id: s001-s999（最多10位字符）
- character_id: char_001-char_999
- location_id: loc_001-loc_999
- group_id: grp_001-grp_999
"""

STORY_WRITER_SCENE_MARKER_RE = re.compile(
    r"(\[场景[^\]\n]*\]|场景编号\s*[:：]\s*[A-Z]\d+|^\s*#*\s*场景\s*[:：])",
    re.IGNORECASE | re.MULTILINE,
)
STORY_WRITER_ACT_MARKER_RE = re.compile(
    r"(\bact\s*\d+\b|第\s*[一二三四五六七八九十百千万\d]+\s*[幕场])",
    re.IGNORECASE,
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _shot_sort_key(shot: Dict[str, Any]) -> Tuple[int, Any]:
    raw_number = shot.get("shot_number", 0)
    try:
        return (0, int(raw_number))
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(raw_number))
        if match:
            return (0, int(match.group(0)))
        return (1, str(raw_number))


def _group_duration(group: Dict[str, Any]) -> float:
    return sum(_safe_float(shot.get("duration", 0)) for shot in group.get("shots", []))


def _semantic_marker_text(group: Dict[str, Any]) -> str:
    marker_keys = (
        "group_name",
        "scene_title",
        "scene_name",
        "scene_number",
        "scene_id",
        "source_scene_id",
        "act_title",
        "act",
    )
    parts: List[str] = []
    for key in marker_keys:
        value = group.get(key)
        if value:
            parts.append(str(value))
    for shot in group.get("shots", []):
        for key in marker_keys:
            value = shot.get(key)
            if value:
                parts.append(str(value))
    return "\n".join(parts)


def _detect_grouping_basis(shot_groups: List[Dict[str, Any]]) -> str:
    marker_texts = [_semantic_marker_text(group) for group in shot_groups]
    if any(STORY_WRITER_SCENE_MARKER_RE.search(text) for text in marker_texts):
        return "story_writer_scene_markers"
    if any(STORY_WRITER_ACT_MARKER_RE.search(text) for text in marker_texts):
        return "story_writer_act_markers"
    return "original_llm_groups"


def _append_shot_group(
    new_shot_groups: List[Dict[str, Any]],
    group_counter: int,
    shots: List[Dict[str, Any]],
    source_group_name: Optional[str],
    part_index: int,
    total_parts: int,
) -> int:
    if not shots:
        return group_counter

    group_name = source_group_name or f"分镜组{group_counter}"
    if total_parts > 1:
        group_name = f"{group_name} - 片段{part_index}"

    new_shot_groups.append({
        "group_id": f"grp_{group_counter:03d}",
        "group_name": group_name,
        "shots": shots,
    })
    return group_counter + 1


def _split_semantic_group_by_duration(
    group: Dict[str, Any],
    max_group_duration: int,
    group_counter: int,
    new_shot_groups: List[Dict[str, Any]],
) -> int:
    shots = sorted(group.get("shots", []), key=_shot_sort_key)
    if not shots:
        return group_counter

    chunks: List[List[Dict[str, Any]]] = []
    current_chunk: List[Dict[str, Any]] = []
    current_duration = 0.0

    for shot in shots:
        shot_duration = _safe_float(shot.get("duration", 0))
        if current_chunk and (current_duration + shot_duration) > max_group_duration:
            chunks.append(current_chunk)
            current_chunk = [shot]
            current_duration = shot_duration
        else:
            current_chunk.append(shot)
            current_duration += shot_duration

    if current_chunk:
        chunks.append(current_chunk)

    source_group_name = group.get("group_name")
    total_parts = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        group_counter = _append_shot_group(
            new_shot_groups,
            group_counter,
            chunk,
            source_group_name,
            index,
            total_parts,
        )
    return group_counter


# JSON格式示例模板
def reorganize_shot_groups(parsed_data: Dict[str, Any], max_group_duration: int, log_dir=None, timestamp=None) -> Dict[str, Any]:
    """
    重新组合分镜组，确保每个分镜组的总时长不超过max_group_duration秒
    
    策略：
    1. 优先保留story-writer预留的场景边界（如[场景 ...]、场景编号：A1）
    2. 如果没有场景标记，保留“第X幕/第X场”等幕/场边界
    3. 不为了填满max_group_duration跨场景、跨幕合并镜头
    4. 仅当单个语义分组超过max_group_duration时，在该分组内部按顺序拆分
    
    Args:
        parsed_data: 解析后的剧本数据
        max_group_duration: 每个分镜组的最大时长（秒）
        log_dir: 日志目录
        timestamp: 时间戳
    
    Returns:
        重新组合后的剧本数据
    """
    import logging
    logger = logging.getLogger(__name__)
    
    shot_groups = parsed_data.get("shot_groups", [])
    if not shot_groups:
        return parsed_data
    
    new_shot_groups = []
    group_counter = 1
    grouping_basis = _detect_grouping_basis(shot_groups)

    for group in shot_groups:
        group_counter = _split_semantic_group_by_duration(
            group,
            max_group_duration,
            group_counter,
            new_shot_groups,
        )
    
    # 统计重组信息
    original_group_count = len(shot_groups)
    new_group_count = len(new_shot_groups)
    
    # 检查是否有超过限制的分镜组
    over_limit_groups = []
    for group in new_shot_groups:
        group_duration = _group_duration(group)
        if group_duration > max_group_duration:
            over_limit_groups.append({
                "group_id": group.get("group_id"),
                "duration": group_duration,
                "shot_count": len(group.get("shots", []))
            })
    
    reorganize_info = f"""分镜组重组信息
{'='*80}

原始分镜组数量: {original_group_count}
重组后分镜组数量: {new_group_count}
最大时长限制: {max_group_duration}秒
分组依据: {grouping_basis}

重组后各分镜组时长:
"""
    
    for group in new_shot_groups:
        group_duration = _group_duration(group)
        shot_count = len(group.get("shots", []))
        status = "超限" if group_duration > max_group_duration else "正常"
        reorganize_info += f"  - {group.get('group_id')}: {group_duration:.1f}秒 ({shot_count}个镜头) [{status}]\n"
    
    if over_limit_groups:
        reorganize_info += f"\n警告: 仍有{len(over_limit_groups)}个分镜组超过时长限制:\n"
        for g in over_limit_groups:
            reorganize_info += f"  - {g['group_id']}: {g['duration']:.1f}秒 ({g['shot_count']}个镜头)\n"
        reorganize_info += "\n原因: 单个镜头时长超过限制，无法进一步拆分\n"
    else:
        reorganize_info += f"\n所有分镜组均符合{max_group_duration}秒时长限制\n"
    
    logger.info(f"分镜组重组完成: {original_group_count} -> {new_group_count}")
    
    # 保存重组信息到日志
    _save_log_file(log_dir, f"script_parser_{timestamp}_07_reorganize_info.txt", reorganize_info)
    
    # 更新parsed_data
    parsed_data["shot_groups"] = new_shot_groups
    
    return parsed_data


JSON_FORMAT_EXAMPLE = """{
  "script_title": "剧本标题",
  "total_duration": 总时长（秒）,
  "characters": [
    {
      "id": "char_001",
      "name": "人物名称",
      "character_db_id": 123,
      "role": "主角/配角/群演",
      "description": "外貌和特征描述",
      "gender": "男/女",
      "age_range": "年龄范围"
    }
  ],
  "locations": [
    {
      "id": "loc_001",
      "name": "场景名称",
      "parent_id": null,
      "location_db_id": 123,
      "type": "室内/室外",
      "description": "场景详细描述（必须非常详细，包括环境布局、物品摆设、光线、色调等）",
      "atmosphere": "氛围",
      "environment_sound": "环境音描述（如'街道车辆声、行人脚步声'）",
      "background_music": "背景音乐描述（如'轻快的爵士乐'）",
      "level": 0
    },
    {
      "id": "loc_002",
      "name": "子场景名称",
      "parent_id": "loc_001",
      "location_db_id": null,
      "type": "室内/室外",
      "description": "子场景详细描述",
      "atmosphere": "氛围",
      "environment_sound": "环境音描述",
      "background_music": "背景音乐描述",
      "level": 1
    }
  ],
  "props": [
    {
      "id": "prop_001",
      "name": "道具名称",
      "props_db_id": 456,
      "description": "道具详细描述（包括外观、材质、用途等）",
      "category": "道具类别（如'武器'、'工具'、'饰品'等）"
    },
    {
      "id": "prop_002",
      "name": "新道具名称",
      "props_db_id": null,
      "description": "新道具详细描述",
      "category": "道具类别"
    }
  ],
  "shot_groups": [
    {
      "group_id": "grp_001",
      "group_name": "开场镜头",
      "group_type": "蒙太奇组/递进组/因果组/对比组",
      "shots": [
        {
          "shot_id": "s001",
          "shot_number": 1,
          "duration": 5.0,
          "location_id": "loc_001",
          "time_of_day": "具体时间段（如'下午3点左右'、'傍晚日落时分'）",
          "weather": "天气（室外必填，室内填null）",
          "camera_angle": "平视/俯拍/仰拍/微俯拍/荷兰角",
          "shot_type": "远景/中景/近景/特写",
          "camera_movement": "固定/推进/拉远/跟随/摇移/升降",
          "description": "镜头简要描述（涉及角色时用【【角色名】】格式，涉及道具时用〖〖道具名〗〗格式）",
          "opening_frame_description": "镜头起始画面的详细描述（用于AI生成首帧图像,必须详细到能让AI准确还原画面,包括：人物位置、姿态、表情、服装；场景布局、物品摆放、光线方向和强度；构图信息如三分法、景深、视角等。涉及角色时用【【角色名】】格式，涉及道具时用〖〖道具名〗〗格式）",
          "scene_detail": "场景详细描述（描述整个镜头过程中的画面变化,涉及角色时用【【角色名】】格式，涉及道具时用〖〖道具名〗〗格式）",
          "characters_present": ["char_001"],
          "props_present": ["prop_001"],
          "dialogue": [
            {
              "character_id": "char_001",
              "character_name": "【【人物名称】】",
              "text": "对话内容"
            }
          ],
          "action": "动作描述（涉及角色时用【【角色名】】格式，涉及道具时用〖〖道具名〗〗格式）",
          "mood": "情绪氛围",
          "environment_sound": "环境音（场景中的自然声音，如脚步声、车辆声等）",
          "background_music": "背景音乐（配乐，如钢琴曲、爵士乐等）",
          "narrative_purpose": "建立/推进/揭示/强调/过渡/情绪/反射：具体说明该镜头通过什么可见动作、构图、声音或转场完成叙事功能",
          "audio_notes": "音频备注"
        },
        {
          "shot_id": "s002",
          "shot_number": 2,
          "duration": 4.0,
          "location_id": "loc_001",
          "time_of_day": "具体时间段",
          "weather": "天气",
          "camera_angle": "平视",
          "shot_type": "中景",
          "camera_movement": "推进",
          "description": "第二个镜头描述",
          "opening_frame_description": "第二个镜头起始画面详细描述",
          "scene_detail": "第二个镜头场景详细描述",
          "characters_present": ["char_001"],
          "dialogue": [],
          "action": "动作描述",
          "mood": "情绪氛围",
          "environment_sound": "环境音",
          "background_music": "背景音乐",
          "narrative_purpose": "推进：通过角色递出关键道具的可见动作，让观众获得下一步信息",
          "audio_notes": "音频备注"
        }
      ]
    }
  ],
  "metadata": {
    "created_at": "创建时间",
    "default_shot_duration": 15,
    "total_shots": 分镜总数,
    "total_characters": 人物总数,
    "total_locations": 场景总数,
    "genre": "类型",
    "style": "风格"
  }
}"""


async def parse_script_to_shots(
    script_content: str,
    max_group_duration: int = 15,
    world_id: Optional[int] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    force_medium_shot: bool = False,
    no_bg_music: bool = False,
    split_multi_dialogue: bool = False,
    language: Optional[str] = None,
    dialogue_language: Optional[str] = None,
    prompt_language: Optional[str] = None,
    auth_token: Optional[str] = None,
    vendor_id: Optional[int] = None,
    model_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    将剧本内容解析为结构化的人物、场景和分镜数据
    
    Args:
        script_content: 剧本文本内容
        max_group_duration: 每个镜头组的最大时长（秒），默认15秒
        world_id: 世界ID，用于获取数据库中的场景列表进行关联匹配
        model: 使用的LLM模型，默认使用配置文件中的模型
        temperature: 温度参数，控制创意性，默认0.7
        force_medium_shot: 是否强制对话内容使用中景(半身像)，默认False
        no_bg_music: 是否不生成背景音乐，默认False
        split_multi_dialogue: 是否将多人对话镜头拆分为单人对话镜头，默认False
        language: 解析结果输出语言（如'中文'、'English'、'Deutsch'等），为空则默认中文（兼容旧版，新版优先使用dialogue_language和prompt_language）
        dialogue_language: 对话文本输出语言（dialogue.text等），为空则回退到language
        prompt_language: 描述性文本输出语言（description、action等），为空则回退到language
        auth_token: 认证token
        vendor_id: 商家ID
        model_id: 模型ID
    
    Returns:
        包含characters、locations、shots的结构化数据字典
    
    Raises:
        Exception: 当API调用失败或JSON解析失败时
    """
    try:
        # 创建日志目录（仅在启用日志时）
        from pathlib import Path
        from datetime import datetime
        import logging
        
        logger = logging.getLogger(__name__)
        
        if ENABLE_SCRIPT_PARSER_LOGGING:
            log_dir = Path("logs/script_parser")
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        else:
            log_dir = None
            timestamp = None

        # 获取数据库中的场景列表（如果提供了world_id）
        db_locations_text = ""
        if world_id is not None:
            try:
                from model.location import LocationModel
                logger.info(f"Attempting to load locations for world_id: {world_id}")
                db_locations = LocationModel.get_tree_by_world(world_id=world_id, limit=20)
                logger.info(f"Loaded {len(db_locations) if db_locations else 0} top-level locations from database")

                if db_locations:
                    # 将场景列表格式化为文本
                    def format_location_tree(locations, indent=0):
                        result = []
                        for loc in locations:
                            prefix = "  " * indent
                            result.append(f"{prefix}- ID: {loc['id']}, 名称: {loc['name']}, 描述: {loc.get('description', '无')}")
                            if loc.get('children'):
                                result.extend(format_location_tree(loc['children'], indent + 1))
                        return result
                    
                    location_lines = format_location_tree(db_locations)
                    db_locations_text = f"""

**【数据库已有场景列表】**
以下是数据库中已存在的场景（最多20个），如果剧本中的场景与数据库中的场景相同或相似，请在返回的location对象中设置location_db_id字段为对应的数据库场景ID：

{chr(10).join(location_lines)}

**【重要警告】关于location_db_id字段：**
- 如果剧本中的场景与上述数据库场景匹配，请设置location_db_id为数据库场景的ID（必须是上面列表中实际存在的ID）
- 如果剧本中的场景是新场景，不在数据库中，则location_db_id必须设置为null
- 匹配时要考虑场景名称和描述的相似性，不需要完全一致
- **严禁编造或随意填写不存在的location_db_id！如果不确定是否匹配，必须设置为null**
- **只能使用上面列表中显示的ID，不能使用其他任何数字**
"""
                    logger.info(f"Generated db_locations_text with {len(location_lines)} location entries")
                else:
                    logger.warning(f"No locations found for world_id: {world_id}")
            except Exception as e:
                logger.error(f"Failed to load database locations: {e}", exc_info=True)
        
        # 获取数据库中的道具列表（如果提供了world_id）
        db_props_text = ""
        if world_id is not None:
            try:
                from model.props import PropsModel
                logger.info(f"Attempting to load props for world_id: {world_id}")
                props_result = PropsModel.list_by_world(world_id=world_id, page=1, page_size=50)
                db_props = props_result.get('data', []) if props_result else []
                logger.info(f"Loaded {len(db_props)} props from database")

                if db_props:
                    # 将道具列表格式化为文本
                    props_lines = []
                    for prop in db_props:
                        props_lines.append(f"- ID: {prop['id']}, 名称: {prop['name']}, 描述: {prop.get('content', '无')}")
                    
                    db_props_text = f"""

**【数据库已有道具列表】**
以下是数据库中已存在的道具（最多50个），如果剧本中的道具与数据库中的道具相同或相似，请在返回的props对象中设置props_db_id字段为对应的数据库道具ID：

{chr(10).join(props_lines)}

**【重要警告】关于props_db_id字段：**
- 如果剧本中的道具与上述数据库道具匹配，请设置props_db_id为数据库道具的ID（必须是上面列表中实际存在的ID）
- 如果剧本中的道具是新道具，不在数据库中，则props_db_id必须设置为null
- 匹配时要考虑道具名称和描述的相似性，不需要完全一致
- **严禁编造或随意填写不存在的props_db_id！如果不确定是否匹配，必须设置为null**
- **只能使用上面列表中显示的ID，不能使用其他任何数字**
"""
                    logger.info(f"Generated db_props_text with {len(props_lines)} props entries")
                else:
                    logger.warning(f"No props found for world_id: {world_id}")
            except Exception as e:
                logger.error(f"Failed to load database props: {e}", exc_info=True)

        # 获取数据库中的角色列表（如果提供了world_id）
        db_characters_text = ""
        if world_id is not None:
            try:
                from model.character import CharacterModel
                logger.info(f"Attempting to load characters for world_id: {world_id}")
                characters_result = CharacterModel.list_by_world(world_id=world_id, page=1, page_size=50)
                db_characters = characters_result.get('data', []) if characters_result else []
                logger.info(f"Loaded {len(db_characters)} characters from database")

                if db_characters:
                    # 将角色列表格式化为文本
                    char_lines = []
                    for char in db_characters:
                        char_desc = char.get('identity', '') or char.get('appearance', '') or char.get('personality', '无')
                        char_lines.append(f"- ID: {char['id']}, 名称: {char['name']}, 描述: {char_desc}")

                    db_characters_text = f"""

**【数据库已有角色列表】**
以下是数据库中已存在的角色（最多50个），如果剧本中的角色与数据库中的角色相同或相似，请在返回的character对象中设置character_db_id字段为对应的数据库角色ID：

{chr(10).join(char_lines)}

**【重要警告】关于character_db_id字段：**
- 如果剧本中的角色与上述数据库角色匹配，请设置character_db_id为数据库角色的ID（必须是上面列表中实际存在的ID）
- 如果剧本中的角色是新角色，不在数据库中，则character_db_id必须设置为null
- 匹配时要考虑角色名称和描述的相似性，不需要完全一致
- **严禁编造或随意填写不存在的character_db_id！如果不确定是否匹配，必须设置为null**
- **只能使用上面列表中显示的ID，不能使用其他任何数字**
"""
                    logger.info(f"Generated db_characters_text with {len(char_lines)} character entries")
                else:
                    logger.warning(f"No characters found for world_id: {world_id}")
            except Exception as e:
                logger.error(f"Failed to load database characters: {e}", exc_info=True)

        # 构建特殊要求文本
        special_requirements = ""
        logger.info(f"Script parser parameters - force_medium_shot: {force_medium_shot}, no_bg_music: {no_bg_music}, split_multi_dialogue: {split_multi_dialogue}, language: {language}, dialogue_language: {dialogue_language}, prompt_language: {prompt_language}")
        
        if force_medium_shot:
            special_requirements += """
**【对话镜头特殊要求】**
- **所有包含对话(dialogue)的镜头，shot_type禁止使用"全景"或"远景"**
- 对话镜头应该使用"近景"或"中景"，由你根据场景需要自动选择最合适的景别
- 近景：适合表现人物细腻的面部表情和情绪变化
- 中景：适合表现人物的肢体语言和半身动作，能够清楚看到人物的面部表情和上半身
- 这是为了避免sora在全景对话场景中效果不佳的问题
- **【关键】对话镜头的opening_frame_description必须在开头明确标注"近景："或"中景："，例如："中景：【【张三】】站在..."，不要使用"全景："或"远景："开头**

"""
        
        if no_bg_music:
            special_requirements += """
**【背景音乐特殊要求】**
- **所有shot节点的background_music字段必须设置为null或空字符串**
- 不要生成任何背景音乐描述
- 这是为了方便后期调音处理

"""
        
        if split_multi_dialogue:
            special_requirements += """
**【多人对话镜头拆分要求 - 极其重要】**
- **当一个镜头中有多个角色对话时（dialogue数组包含2个或以上角色），必须将该镜头拆分为多个单人对话镜头**

- **【核心规则 - 必须严格遵守】：**
  * **每个拆分后的镜头只能包含一个角色的对话**
  * **【禁止行为】在拆分后的单人镜头中，opening_frame_description、scene_detail、description、action等所有画面描述字段中，严禁同时出现两个或多个角色**
  * **【正确做法】每个镜头的画面描述只能聚焦于一个说话的角色，只描述这一个角色的动作、表情、位置**
  * 按照对话顺序依次拆分，保持对话的连贯性
  * 每个拆分镜头的shot_type应该使用"近景"或"中景"，展现说话角色的面部表情
  * 每个拆分镜头的duration根据该角色台词长度合理分配（通常3-6秒）
  * characters_present数组也只能包含一个角色ID（说话的角色）
  
- **【关键】遵守180度轴线原则，避免画面越轴：**
  * 假设两个角色A和B对话，建立一条虚拟的轴线连接两人
  * 摄像机必须始终保持在轴线的同一侧拍摄
  * 正确示例：角色A在画面左侧面向右，角色B在画面右侧面向左（正反打）
  * 错误示例：角色A和B都面向同一方向，或者位置关系突然颠倒
  * 在opening_frame_description中明确描述角色在画面中的位置和朝向（但只描述一个角色）
  
- **【拆分示例 - 正确做法】：**
  * 原镜头：中景，A和B在咖啡厅对话
    - dialogue: [{"character_id": "A", "text": "你好吗？"}, {"character_id": "B", "text": "我很好，谢谢"}]
    - opening_frame_description: "中景：【【A】】和【【B】】坐在咖啡厅..." ❌ 错误！
    
  * 拆分后（正确）：
    - 镜头1：中景，A说话
      - dialogue: [{"character_id": "A", "text": "你好吗？"}]
      - characters_present: ["char_001"]  // 只有A
      - description: "【【A】】说话"  // 只提A
      - opening_frame_description: "中景：【【A】】坐在咖啡厅的座位上，身体微微前倾，双手放在桌上，面带微笑，眼神看向画面右侧（镜头外），嘴唇微动正在说话"  ✓ 正确！只描述A
      - scene_detail: "【【A】】在咖啡厅中说话，表情友好"  ✓ 正确！只描述A
      - action: "【【A】】微笑着询问对方"  ✓ 正确！只描述A
      
    - 镜头2：中景，B回应
      - dialogue: [{"character_id": "B", "text": "我很好，谢谢"}]
      - characters_present: ["char_002"]  // 只有B
      - description: "【【B】】回应"  // 只提B
      - opening_frame_description: "中景：【【B】】坐在咖啡厅的另一侧座位，身体放松靠在椅背上，双手交叉放在胸前，面带笑容，眼神看向画面左侧（镜头外），点头回应"  ✓ 正确！只描述B
      - scene_detail: "【【B】】在咖啡厅中回应，表情轻松愉快"  ✓ 正确！只描述B
      - action: "【【B】】点头微笑着回答"  ✓ 正确！只描述B

- **【错误示例 - 严禁这样做】：**
  * ❌ 错误1：opening_frame_description: "中景：【【A】】和【【B】】坐在咖啡厅，【【A】】正在说话..."
    - 问题：同时出现了A和B两个角色
  * ❌ 错误2：scene_detail: "【【A】】对【【B】】说话，【【B】】在认真倾听"
    - 问题：同时描述了A和B的动作
  * ❌ 错误3：description: "【【A】】和【【B】】在对话"
    - 问题：同时提到了两个角色
  * ❌ 错误4：characters_present: ["char_001", "char_002"]
    - 问题：包含了两个角色ID
  
- **【正确示例 - 应该这样做】：**
  * ✓ 正确1：opening_frame_description: "中景：【【A】】坐在咖啡厅，身体前倾，面带微笑看向镜头外右侧，正在说话"
    - 只描述A，通过"看向镜头外"暗示对方存在
  * ✓ 正确2：scene_detail: "【【B】】在咖啡厅中回应，表情轻松"
    - 只描述B的状态
  * ✓ 正确3：description: "【【A】】说话"
    - 只提一个角色
  * ✓ 正确4：characters_present: ["char_001"]
    - 只包含一个角色ID

- **注意事项：**
  * 拆分后的镜头仍然属于同一个shot_group（如果总时长不超限）
  * 保持场景的连续性，location_id、time_of_day、weather等保持一致
  * 通过"看向镜头外"、"看向右侧/左侧"等描述暗示对话对象的存在，但不要直接描述对方
  * 确保拆分后的镜头在视觉上能够自然衔接（通过轴线原则）

"""
        
        # 语言设置
        LANGUAGE_MAP = {
            'English': 'English',
            'Deutsch': 'Deutsch（德语）',
            'Français': 'Français（法语）',
            'Русский': 'Русский（俄语）',
        }

        # 兼容旧版：如果新参数为空，回退到 language
        effective_dialogue_lang = (dialogue_language or '').strip() or (language or '').strip()
        effective_prompt_lang = (prompt_language or '').strip() or (language or '').strip()

        def _lang_display(name: str) -> str:
            return LANGUAGE_MAP.get(name, name) if name else ''

        dlg_display = _lang_display(effective_dialogue_lang)
        prmpt_display = _lang_display(effective_prompt_lang)

        if dlg_display and prmpt_display:
            if effective_dialogue_lang == effective_prompt_lang:
                # 两种语言相同，合并输出
                special_requirements += f"""
**【输出语言要求 - 极其重要】**
- **所有文本字段（description、opening_frame_description、scene_detail、action、dialogue.text、mood、environment_sound、background_music、audio_notes、characters的description等）必须使用{dlg_display}输出**
- JSON的key（字段名）保持英文不变，只翻译value中的文本内容
- 确保翻译自然流畅，符合{dlg_display}的表达习惯

"""
            else:
                # 两种语言不同，分别指定
                special_requirements += f"""
**【输出语言要求 - 极其重要】**
- **对话字段**（dialogue.text）必须使用 **{dlg_display}** 输出
- **描述性字段**（description、opening_frame_description、scene_detail、action、mood、environment_sound、background_music、audio_notes、characters的description等）必须使用 **{prmpt_display}** 输出
- JSON的key（字段名）保持英文不变，只翻译value中的文本内容
- 确保各语言翻译自然流畅，符合对应语言的表达习惯

"""
        elif dlg_display:
            special_requirements += f"""
**【对话语言要求】**
- **对话字段**（dialogue.text）必须使用 **{dlg_display}** 输出
- 描述性字段保持原文语言

"""
        elif prmpt_display:
            special_requirements += f"""
**【提示词语言要求】**
- **描述性字段**（description、opening_frame_description、scene_detail、action、mood、environment_sound、background_music、audio_notes、characters的description等）必须使用 **{prmpt_display}** 输出
- 对话字段保持原文语言

"""

        # 构建用户提示词
        user_prompt = f"""请将以下剧本内容解析为结构化的JSON数据。

剧本内容：
```{script_content} ```

数据库中的场景列表：
```{db_locations_text} ```

数据库中的道具列表：
```{db_props_text} ```

数据库中的角色列表：
```{db_characters_text} ```

**【核心要求 - 必须严格遵守】**

1. **镜头组时长限制与分组规则（最重要）**：
   - **【硬性规则】每个shot_group内所有shots的duration总和绝对不能超过{max_group_duration}秒**
   - **【场景优先规则】如果剧本包含story-writer标准场景标记（如`[场景 地点 时间段]`、`场景编号：A1`），必须优先按这些场景边界划分shot_group**
   - **【幕/场兜底规则】如果没有识别到标准场景标记，但有“第一幕/第二幕/第X场”等结构标记，必须按幕/场边界划分shot_group**
   - **【禁止行为】不要为了让shot_group接近{max_group_duration}秒，跨不同场景、不同幕或不同场强行合并镜头**
   - 只有当同一个场景、同一幕或同一场内部的镜头总时长超过{max_group_duration}秒时，才允许在该语义分组内部拆成多个shot_group
   
   **正确示例：**
   - 示例1：A1场景镜头1(6秒)，B1场景镜头2(6秒)，总计未超过{max_group_duration}秒 → 仍然必须分成两个shot_group ✓
   - 示例2：A1场景镜头1(8秒) + A1场景镜头2(8秒)超过{max_group_duration}秒 → 只能在A1内部拆成两个shot_group ✓
   - 示例3：同一幕内连续镜头总时长未超过{max_group_duration}秒 → 可以放在同一个shot_group，但不能跨到下一幕 ✓
   
   **错误示例（严禁）：**
   - 错误1：A1场景镜头1(6秒) + B1场景镜头2(6秒)合并成一组 → 跨场景合并 ✗
   - 错误2：第一幕镜头和第二幕镜头合并成一组 → 跨幕合并 ✗
   - 错误3：A1场景超长拆分后，把B1场景第一个镜头拉进A1的最后一组补时长 → 跨场景填充 ✗

2. **镜头时长必须合理**：
   - 禁止每个镜头都是{max_group_duration}秒，这不切实际
   - 镜头时长应根据内容合理分配：
     * 特写/近景：通常2-5秒
     * 中景/全景：通常3-8秒
     * 远景：通常5-10秒
     * 对话镜头：根据台词长度，通常3-8秒
     * 动作镜头：根据动作复杂度，通常5-12秒
   - 每个shot_group内的镜头时长应该有变化，不要都一样
   - 短镜优先并入同一场景或同一幕内的相邻镜头（短镜通常为1-3秒），形成更稳定的shot_group；但不得为了合并短镜跨场景、跨幕或超过{max_group_duration}秒
   - 每个shot_group可尽量接近4秒以上，但这是软目标；场景/幕边界和{max_group_duration}硬上限优先

3. **分镜设计质量要求（非常重要）**：
   - **九列分镜表映射**：镜号对应shot_number，时长对应duration，摄影角度对应camera_angle，景别对应shot_type，画面内容对应description/scene_detail/action，场景对应location_id，声音对应dialogue/environment_sound/background_music/audio_notes，备注对应camera_movement/audio_notes，叙事目的对应narrative_purpose
   - **画面内容必须写可见动作**：只写观众能看到或听到的动作、环境、效果和关键道具；不要写心理活动、抽象判断或无法被画面表现的内容
   - **关键道具必须点名**：如果道具推动剧情或承载意象，必须在description、opening_frame_description、scene_detail或action中使用真实道具名称
   - **叙事目的必须从以下七类中选择**：建立、推进、揭示、强调、过渡、情绪、反射
   - narrative_purpose不能写“推进剧情”“烘托气氛”这类空话，必须写成“类别：通过具体视听手段达成的功能”，例如“揭示：通过特写展示桌面上的断裂钥匙，让观众发现角色隐瞒的证据”
   - **镜头组类型**：每个shot_group的group_type从蒙太奇组、递进组、因果组、对比组中选择；对话和动作优先使用动作-反应结构（动作→反应、反应前置、声画分离、反应链、反应省略等）
   - **镜头技巧选择**：根据剧情选择构图、运动、衔接和转场，例如视线匹配、过肩镜头、反应镜头、插入镜头、动作匹配、声音桥接、J切/L切、跳切、慢动作、定格、主观POV等；不要为了炫技牺牲清晰叙事
   - **景别与运动含义**：特写用于强调表情/道具/压力，中景用于对话和社会距离，全景/远景用于交代空间；推近用于逼近/揭秘，拉远用于抽离/揭示环境，固定镜头用于压抑或等待

4. **结构要求（非常重要）**：
   - 【必须】使用 "shot_groups" 数组结构，不能直接返回 "shots" 数组
   - 每个shot_group包含 "group_id"、"group_name" 和 "shots" 数组
   - 每个shot必须嵌套在某个shot_group的shots数组中
   
   正确示例：
   "shot_groups": [
     {{
       "group_id": "grp_001",
       "group_name": "开场镜头",
       "shots": [{{"shot_id": "s001", ...}}, {{"shot_id": "s002", ...}}]
     }}
   ]
   
   错误示例（禁止）：
   "shots": [{{"shot_id": "s001", ...}}]

5. **时长要求（非常重要）**：
   - 每个shot必须包含duration字段，单位为秒，类型为float
   - 每个shot_group的总时长不得超过max_group_duration秒

6. **opening_frame_description要求（最关键）**：
   - 这是用于AI生成首帧图像的最关键字段
   - 必须详细描述镜头开始时的静态画面
   - 必须包含：人物位置、姿态、表情、服装
   - 必须包含：场景布局、物品摆放、光线方向和强度
   - 必须包含：构图信息（如三分法、景深、视角等）
   - 描述要具体到能让AI准确还原画面
   - **涉及角色名称时必须用【【角色名】】格式包裹（注意：只对角色名称使用，场景名称不要使用）**

7. **角色名称格式要求（非常重要）**：
   - 在shot节点的所有文本字段中（description、opening_frame_description、scene_detail、action、dialogue.character_name等）
   - **只要涉及角色名称，必须用【【角色名】】格式包裹**
   - **重要：只对角色名称使用【【】】，场景名称、地点名称、物品名称等其他内容都不要使用【【】】**
   - 正确示例："【【小李】】走进房间"、"【【张医生】】在医院正在看病历"
   - 错误示例："【【小李】】走进【【房间】】"（房间不是角色，不要用【【】】）
   - **【极其重要】当角色与数据库匹配时（character_db_id不为null），【【角色名】】必须使用数据库中的角色名称**
   - 例如：如果数据库中角色名称是"阿方索戴维斯_AlphonsoDavies"，则使用"【【阿方索戴维斯_AlphonsoDavies】】"，而不是"【【布冯】】"
   - 这样便于后续系统匹配角色库

8. **道具名称格式要求（极其重要 - 严禁违反）**：
   - **严禁在 opening_frame_description、scene_detail、description、action 等所有画面描述文本字段中使用 prop_001、prop_002 等道具ID来替代道具的实际名称**
   - 道具在画面描述中必须使用其真实名称（如"百元大钞"、"手机"、"钥匙"等），而不是其ID（如"prop_002"）
   - **道具名称必须用〖〖道具名〗〗格式包裹**，例如"〖〖百元大钞〗〗"、"〖〖手机〗〗"、"〖〖钥匙〗〗"
   - props_present 字段使用道具ID引用，但所有画面描述文本字段中必须使用带 〖〖〗〗 标记的道具真实名称
   - 正确示例："【【服务员】】将一张〖〖百元大钞〗〗拍在桌上"、"〖〖公文包〗〗【【德保罗】】站在门口"
   - 错误示例："【【服务员】】将一张【【prop_002】】拍在桌上" ❌ 严禁这样做
   - 错误示例："【【服务员】】将一张【【百元大钞】】拍在桌上" ❌ 道具不能使用角色标记
   - **【关键】角色名称必须用【【角色名】】格式包裹，道具名称必须用〖〖道具名〗〗格式包裹，不能混用**

{special_requirements}9. **输出格式**：
   - 必须严格按照以下JSON格式输出
   - 确保所有ID引用关系正确
   - 只输出纯JSON内容
   - 不要添加```json```标记
   - 不要添加任何解释性文字

JSON格式示例：
```
{JSON_FORMAT_EXAMPLE}
```
下面请开始解析："""

        # 保存提示词和输入内容（仅在启用日志时）
        _save_log_file(log_dir, f"script_parser_{timestamp}_01_system_prompt.txt", SCRIPT_PARSER_SYSTEM_PROMPT)
        _save_log_file(log_dir, f"script_parser_{timestamp}_02_user_prompt.txt", user_prompt)

        if ENABLE_SCRIPT_PARSER_LOGGING:
            logger.info(f"剧本解析日志保存到: {log_dir}/script_parser_{timestamp}_*.txt")

        # 构建消息列表
        messages = [
            {"role": "system", "content": SCRIPT_PARSER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        
        # 调用LLM API（增加max_tokens以避免输出被截断）
        logger.info(f"调用Gemini API，temperature={temperature}")
        
        # 获取 LLM 客户端（传入 vendor_id 确保正确路由）
        llm_client = get_llm_client(model, vendor_id=vendor_id)

        # 使用默认模型或指定模型
        if not model:
            model = "gemini-3-flash-preview"

        # 使用 asyncio.to_thread 包装同步调用
        import asyncio
        response = await asyncio.to_thread(
            llm_client.call_api,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=65536,
            auth_token=auth_token,
            vendor_id=vendor_id,
            model_id=model_id
        )
        
        # 提取响应内容
        response_content = response.choices[0].message.content if response.choices else ""
        
        logger.info(f"LLM响应长度: {len(response_content)} 字符")
        
        # 保存原始响应
        _save_log_file(log_dir, f"script_parser_{timestamp}_04_raw_response.txt", response_content)
        
        # 清理响应内容（移除可能的markdown代码块标记）
        cleaned_content = response_content.strip()
        if cleaned_content.startswith("```json"):
            cleaned_content = cleaned_content[7:]
        if cleaned_content.startswith("```"):
            cleaned_content = cleaned_content[3:]
        if cleaned_content.endswith("```"):
            cleaned_content = cleaned_content[:-3]
        cleaned_content = cleaned_content.strip()
        
        logger.info(f"清理后内容长度: {len(cleaned_content)} 字符")
        
        # 保存清理后的内容
        _save_log_file(log_dir, f"script_parser_{timestamp}_05_cleaned_content.txt", cleaned_content)
        
        # 解析JSON
        try:
            parsed_data = json.loads(cleaned_content)
            
            # 保存解析成功的JSON
            _save_log_file(log_dir, f"script_parser_{timestamp}_06_parsed_success.json", parsed_data)
            
            logger.info("JSON解析成功")
            
        except json.JSONDecodeError as e:
            # 保存解析错误信息
            error_info = f"""JSON解析失败
错误类型: {type(e).__name__}
错误信息: {str(e)}
错误位置: 第{e.lineno}行, 第{e.colno}列 (字符位置: {e.pos})
完整内容长度: {len(cleaned_content)} 字符

错误位置前后100字符:
{cleaned_content[max(0, e.pos-100):min(len(cleaned_content), e.pos+100)]}

内容末尾500字符:
...{cleaned_content[-500:]}
"""
            _save_log_file(log_dir, f"script_parser_{timestamp}_ERROR_parse_failed.txt", error_info)
            
            logger.error(f"JSON解析失败，完整内容长度: {len(cleaned_content)}")
            logger.error(f"错误位置: {e.lineno}行, {e.colno}列")
            logger.error(f"内容末尾500字符: ...{cleaned_content[-500:]}")
            
            # 尝试修复常见的JSON问题
            # 1. 如果JSON被截断，尝试找到最后一个完整的对象
            if not cleaned_content.endswith('}'):
                logger.warning("检测到JSON可能被截断，尝试修复...")
                # 找到最后一个完整的shot_groups数组结束位置
                last_bracket = cleaned_content.rfind(']')
                if last_bracket > 0:
                    # 尝试补全JSON
                    fixed_content = cleaned_content[:last_bracket+1] + '\n}'
                    
                    # 保存修复尝试
                    _save_log_file(log_dir, f"script_parser_{timestamp}_07_fixed_attempt.txt", fixed_content)
                    
                    try:
                        parsed_data = json.loads(fixed_content)
                        
                        # 保存修复成功的JSON
                        _save_log_file(log_dir, f"script_parser_{timestamp}_08_fixed_success.json", parsed_data)
                        
                        logger.info("JSON修复成功")
                        return parsed_data
                    except Exception as fix_error:
                        logger.error(f"JSON修复失败: {str(fix_error)}")
            
            raise Exception(f"JSON解析失败: {str(e)}\n响应长度: {len(cleaned_content)} 字符\n错误位置: 第{e.lineno}行, 第{e.colno}列\n建议: 剧本内容可能过长，请尝试缩短剧本或分段处理\n详细日志已保存到: {log_dir}/script_parser_{timestamp}_*.txt")
        
        # 验证必需字段
        required_keys = ["characters", "locations", "shot_groups"]
        missing_keys = [key for key in required_keys if key not in parsed_data]
        if missing_keys:
            raise Exception(f"返回的JSON缺少必需字段: {', '.join(missing_keys)}")
        
        # 重新组合分镜组，确保每组不超过max_group_duration秒
        parsed_data = reorganize_shot_groups(parsed_data, max_group_duration, log_dir, timestamp)
        
        # 计算总分镜数
        total_shots = sum(len(group.get("shots", [])) for group in parsed_data.get("shot_groups", []))
        
        # 添加默认metadata（如果不存在）
        if "metadata" not in parsed_data:
            from datetime import datetime
            parsed_data["metadata"] = {
                "created_at": datetime.now().isoformat(),
                "max_group_duration": max_group_duration,
                "total_shots": total_shots,
                "total_shot_groups": len(parsed_data.get("shot_groups", [])),
                "total_characters": len(parsed_data.get("characters", [])),
                "total_locations": len(parsed_data.get("locations", []))
            }
        
        # 保存解析总结
        summary = f"""剧本解析总结
{'='*80}

解析时间: {timestamp}
状态: 成功

输入统计:
  - 剧本内容长度: {len(script_content)} 字符
  - 系统提示词长度: {len(SCRIPT_PARSER_SYSTEM_PROMPT)} 字符
  - 用户提示词长度: {len(user_prompt)} 字符

LLM响应:
  - 原始响应长度: {len(response_content)} 字符
  - 清理后内容长度: {len(cleaned_content)} 字符
  - 模型: {model or '默认'}
  - 温度: {temperature}
  - Max Tokens: 16000

解析结果:
  - 剧本标题: {parsed_data.get('script_title', 'N/A')}
  - 总时长: {parsed_data.get('total_duration', 0)} 秒
  - 画风: {parsed_data.get('style', 'N/A')}
  - 人物数量: {len(parsed_data.get('characters', []))}
  - 场景数量: {len(parsed_data.get('locations', []))}
  - 分镜组数量: {len(parsed_data.get('shot_groups', []))}
  - 分镜总数: {total_shots}

日志文件:
  - script_parser_{timestamp}_01_system_prompt.txt
  - script_parser_{timestamp}_02_user_prompt.txt
  - script_parser_{timestamp}_04_raw_response.txt
  - script_parser_{timestamp}_05_cleaned_content.txt
  - script_parser_{timestamp}_06_parsed_success.json

所有日志文件已保存到: {log_dir.absolute() if log_dir else 'N/A'}
"""
        _save_log_file(log_dir, f"script_parser_{timestamp}_00_SUMMARY.txt", summary)

        if ENABLE_SCRIPT_PARSER_LOGGING:
            logger.info(f"解析成功，详细日志已保存到: {log_dir}/script_parser_{timestamp}_*.txt")
        else:
            logger.info("解析成功")
        
        return parsed_data
        
    except Exception as e:
        raise Exception(f"剧本解析失败: {str(e)}")


def validate_parsed_script(data: Dict[str, Any]) -> tuple[bool, str]:
    """
    验证解析后的剧本数据结构是否正确
    
    Args:
        data: 解析后的剧本数据
    
    Returns:
        (是否有效, 错误信息)
    """
    try:
        # 检查必需字段
        required_keys = ["characters", "locations", "shots"]
        for key in required_keys:
            if key not in data:
                return False, f"缺少必需字段: {key}"
        
        # 验证characters
        if not isinstance(data["characters"], list):
            return False, "characters必须是数组"
        
        character_ids = set()
        for idx, char in enumerate(data["characters"]):
            if "id" not in char:
                return False, f"characters[{idx}]缺少id字段"
            if "name" not in char:
                return False, f"characters[{idx}]缺少name字段"
            character_ids.add(char["id"])
        
        # 验证locations
        if not isinstance(data["locations"], list):
            return False, "locations必须是数组"
        
        location_ids = set()
        for idx, loc in enumerate(data["locations"]):
            if "id" not in loc:
                return False, f"locations[{idx}]缺少id字段"
            if "name" not in loc:
                return False, f"locations[{idx}]缺少name字段"
            location_ids.add(loc["id"])
        
        # 验证shots
        if not isinstance(data["shots"], list):
            return False, "shots必须是数组"
        
        for idx, shot in enumerate(data["shots"]):
            if "shot_id" not in shot:
                return False, f"shots[{idx}]缺少shot_id字段"
            if "duration" not in shot:
                return False, f"shots[{idx}]缺少duration字段"
            
            # 验证location_id引用
            if "location_id" in shot and shot["location_id"] not in location_ids:
                return False, f"shots[{idx}]的location_id '{shot['location_id']}'不存在"
            
            # 验证characters_present引用
            if "characters_present" in shot:
                for char_id in shot["characters_present"]:
                    if char_id not in character_ids:
                        return False, f"shots[{idx}]的characters_present包含不存在的character_id '{char_id}'"
        
        return True, ""
        
    except Exception as e:
        return False, f"验证过程出错: {str(e)}"


# 便捷函数：直接从剧本文件解析
async def parse_script_file(
    script_file_path: str,
    max_group_duration: int = 15,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    从剧本文件解析为结构化数据
    
    Args:
        script_file_path: 剧本文件路径
        max_group_duration: 每个镜头组的最大时长（秒）
        model: 使用的LLM模型
    
    Returns:
        解析后的结构化数据
    """
    with open(script_file_path, 'r', encoding='utf-8') as f:
        script_content = f.read()
    
    return await parse_script_to_shots(
        script_content=script_content,
        max_group_duration=max_group_duration,
        model=model,
        temperature=0.2
    )
