"""
剧本解析模块

将文字剧本解析为结构化的分镜数据
"""

import json
import os
import yaml
from typing import Dict, Any, Optional
from llm.gemini_client import get_gemini_client
from config_util import get_config_path

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

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_file = get_config_path()
with open(os.path.join(APP_DIR, config_file), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

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
8. **分镜中的道具关联**：每个shot必须包含props_present字段
   - props_present是一个数组，包含该镜头中出现的道具ID（对应props数组中的id字段）
   - 如果镜头中没有道具出现，设置为空数组[]
   - 只包含在该镜头画面中实际出现或被使用的道具
9. 分镜要包含镜头类型、运动方式、对话、动作等详细信息
10. opening_frame_description是最关键字段,用于AI生成首帧图像,必须非常详细描述镜头起始画面（包括人物位置、姿态、表情、场景布局、光线效果、构图信息等）
11. 确保所有ID引用关系正确（如shot中的location_id、character_id、props_present要对应）
12. 只输出纯JSON内容,不要添加```json```标记或任何解释性文字
13. **【重要】在shot节点的所有文本字段中,只要涉及角色名称,必须用【【角色名】】格式包裹,便于后续匹配角色库。注意：只对角色名称使用【【】】包裹,场景名称、物品名称等其他内容不要使用【【】】包裹**

ID格式规范：
- shot_id: s001-s999（最多10位字符）
- character_id: char_001-char_999
- location_id: loc_001-loc_999
- group_id: grp_001-grp_999
"""

# JSON格式示例模板
def reorganize_shot_groups(parsed_data: Dict[str, Any], max_group_duration: int, log_dir=None, timestamp=None) -> Dict[str, Any]:
    """
    重新组合分镜组，确保每个分镜组的总时长不超过max_group_duration秒
    
    策略：
    1. 提取所有shots并按shot_number排序（保持全局顺序）
    2. 按顺序遍历shots，根据时长限制进行分组
    3. 尽量让每个分镜组接近max_group_duration秒（贪心算法）
    4. 保证输出的分镜组中shots的shot_number是递增的
    
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
    
    # 提取所有shots并按shot_number排序（保持全局顺序）
    all_shots = []
    for group in shot_groups:
        shots = group.get("shots", [])
        all_shots.extend(shots)
    
    # 按shot_number排序，确保顺序正确
    all_shots.sort(key=lambda s: s.get("shot_number", 0))
    
    # 重新组合分镜组
    new_shot_groups = []
    group_counter = 1
    current_group_shots = []
    current_group_duration = 0.0
    
    for shot in all_shots:
        shot_duration = float(shot.get("duration", 0))
        
        # 如果加入当前镜头会超过限制，则创建新组
        if current_group_shots and (current_group_duration + shot_duration) > max_group_duration:
            # 保存当前组
            group_name = f"分镜组{group_counter}"
            new_shot_groups.append({
                "group_id": f"grp_{group_counter:03d}",
                "group_name": group_name,
                "shots": current_group_shots
            })
            group_counter += 1
            
            # 开始新组
            current_group_shots = [shot]
            current_group_duration = shot_duration
        else:
            # 加入当前组
            current_group_shots.append(shot)
            current_group_duration += shot_duration
    
    # 保存最后一组
    if current_group_shots:
        group_name = f"分镜组{group_counter}"
        new_shot_groups.append({
            "group_id": f"grp_{group_counter:03d}",
            "group_name": group_name,
            "shots": current_group_shots
        })
        group_counter += 1
    
    # 统计重组信息
    original_group_count = len(shot_groups)
    new_group_count = len(new_shot_groups)
    
    # 检查是否有超过限制的分镜组
    over_limit_groups = []
    for group in new_shot_groups:
        group_duration = sum(float(s.get("duration", 0)) for s in group.get("shots", []))
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

重组后各分镜组时长:
"""
    
    for group in new_shot_groups:
        group_duration = sum(float(s.get("duration", 0)) for s in group.get("shots", []))
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
    _save_log_file(log_dir, f"{timestamp}_07_reorganize_info.txt", reorganize_info)
    
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
      "shots": [
        {
          "shot_id": "s001",
          "shot_number": 1,
          "duration": 5.0,
          "location_id": "loc_001",
          "time_of_day": "具体时间段（如'下午3点左右'、'傍晚日落时分'）",
          "weather": "天气（室外必填，室内填null）",
          "shot_type": "远景/中景/近景/特写",
          "camera_movement": "固定/推进/拉远/跟随/摇移/升降",
          "description": "镜头简要描述（涉及角色时用【【角色名】】格式）",
          "opening_frame_description": "镜头起始画面的详细描述（用于AI生成首帧图像,必须详细到能让AI准确还原画面,包括：人物位置、姿态、表情、服装；场景布局、物品摆放、光线方向和强度；构图信息如三分法、景深、视角等。涉及角色时用【【角色名】】格式）",
          "scene_detail": "场景详细描述（描述整个镜头过程中的画面变化,涉及角色时用【【角色名】】格式）",
          "characters_present": ["char_001"],
          "props_present": ["prop_001"],
          "dialogue": [
            {
              "character_id": "char_001",
              "character_name": "【【人物名称】】",
              "text": "对话内容"
            }
          ],
          "action": "动作描述（涉及角色时用【【角色名】】格式）",
          "mood": "情绪氛围",
          "environment_sound": "环境音（场景中的自然声音，如脚步声、车辆声等）",
          "background_music": "背景音乐（配乐，如钢琴曲、爵士乐等）",
          "audio_notes": "音频备注"
        },
        {
          "shot_id": "s002",
          "shot_number": 2,
          "duration": 4.0,
          "location_id": "loc_001",
          "time_of_day": "具体时间段",
          "weather": "天气",
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
            log_dir = Path("script_parser_logs")
            log_dir.mkdir(exist_ok=True)
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
        
        # 构建特殊要求文本
        special_requirements = ""
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
        
        # 构建用户提示词
        user_prompt = f"""请将以下剧本内容解析为结构化的JSON数据。

剧本内容：
```{script_content} ```

数据库中的场景列表：
```{db_locations_text} ```

数据库中的道具列表：
```{db_props_text} ```

**【核心要求 - 必须严格遵守】**

1. **镜头组时长限制与分组规则（最重要 - 违反此规则将导致严重成本浪费）**：
   - **【硬性规则】每个shot_group内所有shots的duration总和绝对不能超过{max_group_duration}秒**
   - **【强制分组规则】相同地点(location_id相同)的连续镜头，只要总时长不超过{max_group_duration}秒，必须强制放在同一个shot_group中，禁止拆分**
   - **【成本优化要求】每个shot_group的总时长应该尽可能接近{max_group_duration}秒（建议≥12秒），避免浪费**
   - **【禁止行为】严禁将相同地点、总时长未超限的镜头拆分到不同的shot_group中**
   - 只有当一个地点的镜头总时长超过{max_group_duration}秒时，才允许拆分成多个shot_group
   
   **正确示例：**
   - 示例1：镜头1(地点A, 8秒) + 镜头2(地点A, 7秒) = 15秒 → 必须放在同一个shot_group中 ✓
   - 示例2：镜头1(地点A, 5秒) + 镜头2(地点A, 6秒) + 镜头3(地点A, 4秒) = 15秒 → 必须放在同一个shot_group中 ✓
   - 示例3：镜头1(地点A, 8秒) + 镜头2(地点B, 7秒) = 15秒 → 因为地点不同，可以分成两个shot_group ✓
   
   **错误示例（严禁）：**
   - 错误1：镜头1(地点A, 8秒)单独一组，镜头2(地点A, 7秒)单独一组 → 违反规则，浪费成本 ✗
   - 错误2：镜头1(地点A, 5秒) + 镜头2(地点A, 6秒)一组，镜头3(地点A, 4秒)单独一组 → 违反规则，应该合并 ✗

2. **镜头时长必须合理**：
   - 禁止每个镜头都是{max_group_duration}秒，这不切实际
   - 镜头时长应根据内容合理分配：
     * 特写/近景：通常2-5秒
     * 中景/全景：通常3-8秒
     * 远景：通常5-10秒
     * 对话镜头：根据台词长度，通常3-8秒
     * 动作镜头：根据动作复杂度，通常5-12秒
   - 每个shot_group内的镜头时长应该有变化，不要都一样

3. **结构要求（非常重要）**：
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

4. **时长要求（非常重要）**：
   - 每个shot必须包含duration字段，单位为秒，类型为float
   - 每个shot_group的总时长不得超过max_group_duration秒

5. **opening_frame_description要求（最关键）**：
   - 这是用于AI生成首帧图像的最关键字段
   - 必须详细描述镜头开始时的静态画面
   - 必须包含：人物位置、姿态、表情、服装
   - 必须包含：场景布局、物品摆放、光线方向和强度
   - 必须包含：构图信息（如三分法、景深、视角等）
   - 描述要具体到能让AI准确还原画面
   - **涉及角色名称时必须用【【角色名】】格式包裹（注意：只对角色名称使用，场景名称不要使用）**

6. **角色名称格式要求（非常重要）**：
   - 在shot节点的所有文本字段中（description、opening_frame_description、scene_detail、action、dialogue.character_name等）
   - **只要涉及角色名称，必须用【【角色名】】格式包裹**
   - **重要：只对角色名称使用【【】】，场景名称、地点名称、物品名称等其他内容都不要使用【【】】**
   - 正确示例："【【小李】】走进房间"、"【【张医生】】在医院正在看病历"
   - 错误示例："【【小李】】走进【【房间】】"（房间不是角色，不要用【【】】）
   - 这样便于后续系统匹配角色库

{special_requirements}7. **输出格式**：
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
        _save_log_file(log_dir, f"{timestamp}_01_system_prompt.txt", SCRIPT_PARSER_SYSTEM_PROMPT)
        _save_log_file(log_dir, f"{timestamp}_02_user_prompt.txt", user_prompt)
        _save_log_file(log_dir, f"{timestamp}_03_input_script.txt", script_content)
        
        if ENABLE_SCRIPT_PARSER_LOGGING:
            logger.info(f"剧本解析日志保存到: {log_dir}/{timestamp}_*.txt")

        # 构建消息列表
        messages = [
            {"role": "system", "content": SCRIPT_PARSER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        
        # 调用LLM API（增加max_tokens以避免输出被截断）
        logger.info(f"调用Gemini API，temperature={temperature}")
        
        # 获取 Gemini 客户端
        gemini_client = get_gemini_client()
        
        # 使用默认模型或指定模型
        if not model:
            model = "gemini-3-flash-preview"
        
        # 使用 asyncio.to_thread 包装同步调用
        import asyncio
        response = await asyncio.to_thread(
            gemini_client.call_api,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=16000,
            auth_token=auth_token,
            vendor_id=vendor_id,
            model_id=model_id
        )
        
        # 提取响应内容
        response_content = response.choices[0].message.content if response.choices else ""
        
        logger.info(f"LLM响应长度: {len(response_content)} 字符")
        
        # 保存原始响应
        _save_log_file(log_dir, f"{timestamp}_04_raw_response.txt", response_content)
        
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
        _save_log_file(log_dir, f"{timestamp}_05_cleaned_content.txt", cleaned_content)
        
        # 解析JSON
        try:
            parsed_data = json.loads(cleaned_content)
            
            # 保存解析成功的JSON
            _save_log_file(log_dir, f"{timestamp}_06_parsed_success.json", parsed_data)
            
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
            _save_log_file(log_dir, f"{timestamp}_ERROR_parse_failed.txt", error_info)
            
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
                    _save_log_file(log_dir, f"{timestamp}_07_fixed_attempt.txt", fixed_content)
                    
                    try:
                        parsed_data = json.loads(fixed_content)
                        
                        # 保存修复成功的JSON
                        _save_log_file(log_dir, f"{timestamp}_08_fixed_success.json", parsed_data)
                        
                        logger.info("JSON修复成功")
                        return parsed_data
                    except Exception as fix_error:
                        logger.error(f"JSON修复失败: {str(fix_error)}")
            
            raise Exception(f"JSON解析失败: {str(e)}\n响应长度: {len(cleaned_content)} 字符\n错误位置: 第{e.lineno}行, 第{e.colno}列\n建议: 剧本内容可能过长，请尝试缩短剧本或分段处理\n详细日志已保存到: {log_dir}/{timestamp}_*.txt")
        
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
  - {timestamp}_01_system_prompt.txt
  - {timestamp}_02_user_prompt.txt
  - {timestamp}_03_input_script.txt
  - {timestamp}_04_raw_response.txt
  - {timestamp}_05_cleaned_content.txt
  - {timestamp}_06_parsed_success.json

所有日志文件已保存到: {log_dir.absolute() if log_dir else 'N/A'}
"""
        _save_log_file(log_dir, f"{timestamp}_00_SUMMARY.txt", summary)
        
        if ENABLE_SCRIPT_PARSER_LOGGING:
            logger.info(f"解析成功，详细日志已保存到: {log_dir}/{timestamp}_*.txt")
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
