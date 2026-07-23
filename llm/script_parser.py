"""
剧本解析模块

将文字剧本解析为结构化的分镜数据
"""

import asyncio
import json
import re
from typing import Dict, Any, Optional, List, Tuple
from config.constant import ScriptParserConstants
from llm.llm_client_factory import get_llm_client
from services.storyboard_spatial import repair_spatial_layout_continuity as _repair_spatial_layout_continuity_core

# ============================================================
# 日志开关配置
# ============================================================
# 正式配置见 config.constant.ScriptParserConstants.DIAGNOSTIC_LOGGING_ENABLED
# 模块级别名保留供测试 monkeypatch；日常请改 constant.py 中的常量。
ENABLE_SCRIPT_PARSER_LOGGING = ScriptParserConstants.DIAGNOSTIC_LOGGING_ENABLED


def _save_log_file(log_dir, filename, content):
    """
    条件性保存日志文件的辅助函数
    仅在 ENABLE_SCRIPT_PARSER_LOGGING 为 True 时保存文件
    """
    if ENABLE_SCRIPT_PARSER_LOGGING and log_dir:
        with open(log_dir / filename, 'w', encoding='utf-8') as f:
            if isinstance(content, dict):
                json.dump(content, f, ensure_ascii=False, indent=2)
            else:
                f.write(content)


async def _save_log_file_async(log_dir, filename, content):
    """在线程中写解析日志，避免阻塞调用方事件循环。"""
    await asyncio.to_thread(_save_log_file, log_dir, filename, content)

# 剧本解析的系统提示词
SCRIPT_PARSER_SYSTEM_PROMPT = """你是一个专业的影视剧本分析师和分镜师,擅长将剧本拆解为人物、场景和分镜。
你需要根据输入的剧本内容,输出结构化的JSON格式数据。

输出要求：
1. 必须严格按照指定的JSON格式输出
2. 分镜组默认每个15秒,可根据剧情需要调整
3. 人物信息要完整,包括角色定位和描述
4. **【重要警告】在分镜描述中必须区分角色的“固有档案”与“当前镜头动态”**：系统的角色库中已有完整的外貌档案，在所有分镜相关字段（opening_frame_description、scene_detail、description、action等）中：
   - **【严禁】描写角色的“固有档案”**：不要描述发型、肤色、体型、固定的标志性服装/饰品等，这些由角色库统一提供，重复描写会与之冲突
   - **【必须】描写角色的“当前镜头动态”**：必须写明角色在画面中的**位置、姿态、动作、表情、与其他角色/镜头的空间关系**，并提及角色名称（用【【角色名】】格式）
   - 简言之：固有外观交给角色库，当前画面动态必须由你来写——否则画面将丢失角色
5. 场景信息要详细,包括时间、天气、氛围、环境音、背景音乐等
5. **场景支持嵌套层级**：通过parent_id和level字段表示场景的层级关系
   - parent_id为null表示顶层场景（如"神明竞技场"）
   - parent_id指向父场景id表示子场景（如"竞技场看台"的parent_id指向"神明竞技场"的id）
   - level表示层级深度，顶层为0，每下一级加1
   - **已绑定 location_db_id 的场景：parent_id/level 必须以数据库列表中的真实父子关系为准，禁止按剧情猜测改写父级**
6. **场景与数据库关联**：每个location必须包含location_db_id字段
   - 如果剧本中的场景与数据库中已有场景匹配，则将location_db_id设置为数据库场景的ID（必须是数据库列表中实际存在的ID）
   - **一旦填写了真实 location_db_id：必须沿用该 ID 与数据库中的名称/层级；parent_id 只能指向“数据库中该场景真实父级”对应的内部 loc_xxx，若数据库该场景本身是顶层则 parent_id 必须为 null**
   - 如果是新场景，不在数据库中，则location_db_id必须设置为null，不能随意编造ID
   - 匹配时考虑场景名称和描述的相似性，不需要完全一致
   - **【警告】严禁编造不存在的location_db_id，如果不确定是否匹配，必须设置为null**
   - **【警告】严禁把数据库已有顶层场景写成子场景（或反过来）来“圆”剧情空间关系**
   - **【同一物理空间不因时间拆成多个场景】**：剧本写「场景3：前台 - 深夜十二点」与「大堂/前台 - 十一点」若地点相同，必须复用同一 location（同一内部 id + 同一 location_db_id）。**禁止**新建「前台区域（深夜版）」「大堂（午夜）」等按时间变体场景。时间、时段、光线变化只写在镜头的 `time_of_day`、`opening_frame_description`、`scene_detail`、`atmosphere` 等字段中
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
11. opening_frame_description是最关键字段,用于AI生成首帧图像,必须非常详细描述镜头起始画面（包括人物位置、姿态、表情、场景布局、光线效果、构图信息等）。**【重要】必须列出该镜头 characters_present 中的每一个角色（用【【角色名】】格式包裹），并分别写出其位置、姿态、表情或动作；不要只写其中一两个角色，每个在场角色都不可遗漏**
12. 确保所有ID引用关系正确（如shot中的location_id、character_id、props_present要对应）
13. 只输出纯JSON内容,不要添加```json```标记或任何解释性文字
14. **【重要】在shot节点的所有文本字段中,只要涉及角色名称,必须用【【角色名】】格式包裹,便于后续匹配角色库。注意：只对角色名称使用【【】】包裹,场景名称、地点名称和道具名称不要使用【【】】包裹**
15. **【重要】在shot节点的所有画面/视频提示文本字段中,只要涉及道具名称,道具名称必须用〖〖道具名〗〗格式包裹,便于后续匹配道具库；props_present字段仍使用道具ID。正确示例：〖〖公文包〗〗【【德保罗】】。**
16. **【重要】严禁幻想道具**：所有带〖〖〗〗标记的道具必须来自数据库已有道具列表，或原始剧本文本中明确出现的新道具；不要因为画面需要自行添加数据库和剧本都没有的道具。
17. 每个shot必须有明确的narrative_purpose，说明这个镜头为什么存在，且必须具体到视听手段
18. **【角色完整出场·硬性规则】每个shot的 characters_present 列出的角色，必须在该镜头的文本中全部出场，不可遗漏任何一个**：
    - **画面提示词侧**：characters_present 中的**每一个角色**都必须在 opening_frame_description 中点名（用【【角色名】】格式），并写出其位置、姿态、表情或动作
    - **视频提示词侧**：characters_present 中的**每一个角色**都至少在 description 或 action 中有可见动作或位置交代
    - 即使某角色在该镜头没有台词或处于静态（如操控载具、观察、等待），也必须写出其位置与姿态，不能因为"不显眼"就漏写
    - **【模式无关】本条以 characters_present 为准**：列出几个角色就写全几个。若启用了“多人对话拆分”规则，拆分后每个镜头只有一个 `focus_character_ids` 说话主体；但同一空间中仍可见或局部可见的非说话角色必须继续留在 characters_present，并在 spatial_layout 中标为 `secondary_continuity`。完全被裁切到画面外的非说话角色不放入 characters_present，但必须在 spatial_layout 中以 `offscreen_continuity` 保留位置。**严禁为了让多角色同框而拒绝拆分对话镜头，也严禁为了单人近景让角色凭空消失**
    - 错误示例：characters_present 含某角色，但 opening_frame_description/description/action 中完全没有提到该角色 ✗
19. **【分镜呈现类型 presentation】** 每个 shot 必须输出 presentation 字段，取值仅限：
    - `"digital_human"`：对口型/数字人镜头——**本镜只有一个角色在说话**（dialogue 中说话角色唯一），内容以对白表演为主，适合近景/特写固定镜头下的口型视频。
    - `"video"`：普通 AI 视频镜头——无对白、多人交替说话、旁白、或虽有单人对白但核心是动作/追逐/打斗/复杂调度。
    - **硬性约束**：dialogue 中出现 2 个及以上不同说话角色时，presentation **必须**为 `"video"`（不可标 digital_human）。
    - 画内可有听者/配角（characters_present 可多人），但以 **dialogue 说话角色数** 判定是否单人说话。
    - 可选附 `presentation_reason` 一句话说明。
20. **【分镜难易程度 difficulty】** 每个 shot 必须输出 difficulty 字段（取值仅限"易"/"中"/"难"三个汉字之一），并附 difficulty_reason 简述依据。综合权衡以下维度，取整体倾向：
    - **易**：单人或无角色、静态/轻微动作、短镜头（≤5秒）、无关键道具或仅普通道具、固定镜头/简单构图。例：一个角色静坐望向窗外的特写。
    - **中**：2-3 人有互动、有连续但常规的动作、中等时长（6-10秒）、1-2 个关键道具、简单镜头运动（推进/跟随）。例：两人对话递接一份文件的中景。
    - **难**：4 人以上群体调度、打斗/追逐/复杂连续动作、长镜头（>10秒）且动作密集、多个关键道具且强交互、复杂镜头运动（升降/摇移组合）/强透视/多层景深。例：多人混战追逐穿越复杂场景的长镜头。
    - difficulty_reason 控制在一句话内，简述判定依据（如"4人群战+长镜头+多个道具交互"）。
21. **【镜头空间布局 spatial_layout】每个 shot 必须输出 spatial_layout 对象**，用于后续首帧宫格生成保持同一幕内的位置连续性：
    - **整集级空间注册表 `spatial_world`**：全局不是一个坐标系，而是整集级空间注册表。必须在顶层输出 `spatial_world.space_units[]`，每个 `space_unit` 表示一个稳定局部空间（如载具驾驶室、糖浆陷阱区域、城堡大厅、桌面机关区），包含 `space_unit_id`、`owner_type`、`owner_id`、`location_ids`、`coordinate_frame` 和 `anchors`。一集可以有多个完全不同的 `space_units`，不能用单一大坐标系覆盖所有场景。
    - 每个 `space_unit.coordinate_frame` 必须写清 `frame_id`、`origin`、`axes.x_positive/y_positive/z_positive`、`scale`、`locked=true`。同一个 `space_unit_id` 的坐标轴一旦建立，后续分镜只能引用，不允许重写含义。
    - 每个稳定位置必须作为 `anchors[]` 登记，包含 `anchor_id`、`label`、`position_3d`。例如驾驶座、副驾驶座、车门、车窗、糖浆池中心、道路前方等。坐标使用 -1 到 1 的归一化语义坐标，不要求真实米制精度。
    - 每个 shot 的 `spatial_layout.space_unit_refs` 必须引用顶层 `spatial_world.space_units` 中真实存在的 `space_unit_id`。不能在 shot 内临时创造坐标系；如果剧情出现新空间，必须先加入顶层 `spatial_world.space_units`，再在 shot 中引用。
    - 每个 slot/loose_position 优先引用 `space_unit_id + anchor_id`，并可携带 `position_3d` 作兜底；没有 `changed_positions` 明确声明真实移动时，不得改变同一角色绑定的 `space_unit_id/anchor_id/position_3d`。
    - 每个 shot 必须输出 `camera_pose`（或 `camera_anchor.camera_pose`）：包含 `space_unit_id`、`eye`、`target`、`up`、`fov`。相机变化只改变 `camera_pose`，不能改变角色所在 anchor。
    - `location_path` 必须引用顶层 `locations` 中真实存在的场景，表达父场景到当前场景的路径；如果剧本出现新场景，必须先在顶层 `locations` 创建，再在这里引用，不能凭空写名称。
    - `containers` 表达角色或小道具位于某个真实道具、载具、房间区域、桌面等容器内；如果容器是道具，`prop_id` 必须引用顶层 `props` 中真实存在的道具。若剧本需要新道具，必须先在顶层 `props` 创建。
    - `loose_positions` 表达不属于某个容器的角色/道具位置，例如"角色站在桥头左侧"。
    - `slots[].character_id` 必须引用顶层 `characters`。`visibility=visible/partial` 的角色必须进入 `characters_present`；`visibility=offscreen/occluded` 的角色可以不进入 `characters_present`，但必须保留在 `spatial_layout` 中用于空间连续性。
    - 每个 shot 必须输出 `focus_character_ids` 数组，表示当前镜头的视觉焦点/说话主体；近景或特写可以只聚焦一个角色，但不代表其他角色从空间中消失。
    - 每个 shot 的 `spatial_layout` 必须输出 `camera_anchor` 对象，用结构化方式描述机位锚定：`camera_position` 表示相机所在的真实空间点，`shooting_direction` 表示拍摄方向，`relative_to_character` 表示相机相对主要焦点角色的位置和角度，`view_direction` 表示从容器/场景坐标看相机朝向（如 `rear_to_front`、`front_to_rear`、`left_to_right`、`right_to_left`、`unknown`），`screen_axis_mapping` 表示容器自身坐标如何投影到画面左右/上下，`screen_composition` 表示主要角色在画面中的左右/前后/边界关系。
    - **机位锚定必须精确到角色相对位置**：不要只写"从车内拍摄"、"室内镜头"这类容器级描述；必须写清楚"从车内中央扶手区向左侧拍摄，机位位于奶酪_Cheese的右前方45度"这类相机相对角色的方位、角度和画面落点。
    - `opening_frame_description` 必须与 `spatial_layout.camera_anchor` 一致，并在画面描述中体现同一机位锚定；例如说明"奶酪_Cheese位于画面左侧，其身体左侧紧邻左侧车门与车窗，右侧为车内中央区域与驾驶座方向"。
    - **先判定观察点，再写 camera_anchor**：如果 `opening_frame_description` 写了"透过车窗可见"、"隔着玻璃看到车内"、"从窗外看向车内"，则相机必须锚定在车外/窗外对应位置，`camera_position` 不能写成车内后排、车内中央扶手区等车内机位。反过来，如果 `camera_anchor.camera_position` 是车内，`opening_frame_description` 也必须明确是车内视角。
    - **一致性自检**：`camera_anchor.description` 必须能作为 `opening_frame_description` 的第一句视角说明直接拼进去而不矛盾。禁止出现 opening_frame_description 是车外透过车窗观察、但 camera_anchor 写车内向前排拍摄的冲突。
    - **seat_source_constraint / 载具座位来源约束**：载具内的 `slots[].slot` 必须来自原始剧本文字、上一镜头已建立的 `spatial_layout`、或角色动作明确暗示的位置。禁止为了取景方便凭空新增"后排左侧座位/后排右侧座位/后座"；只有原文明确出现"后排/后座/后排座位"或 `changed_positions[]` 写明真实换座时，才允许使用后排座位。
    - 如果原文或上一镜头建立的是左右并排、驾驶座+副驾驶座、驾驶室左侧/右侧、两人同坐前排，则拆分对话镜头后也必须保持同一排左右关系；可通过镜头裁切让非焦点角色 `offscreen`，但不能把副驾驶/并排角色改写成后排角色。
    - **物理坐标与画面投影必须分开**：`slots[].slot_id` 是同一容器内稳定槽位 ID（如 `front_driver_seat`、`front_passenger_seat`），`slots[].slot` 是人类可读槽位名，`slots[].physical_position` 用容器自身坐标描述真实位置（如 `{ "row": "front", "side": "vehicle_left/vehicle_right/center", "basis": "container_forward_direction" }`），`slots[].position_basis` 固定写 `physical_slot`。`screen_position 只是当前镜头投影`，可以因机位变成画面左/右/外；但 `slot_id`、`slot`、`physical_position` 不能因为构图变化而改变。不要把画面左/右反推成换座，也不要因为从车前看、从车后看、透过挡风玻璃看而交换驾驶座和副驾驶座的 occupant。
    - `slots[]` 和 `loose_positions[]` 中的角色/道具必须输出 `visibility`（取值：`visible`、`partial`、`offscreen`、`occluded`）和 `framing_role`（取值：`primary_subject`、`secondary_continuity`、`background`、`offscreen_continuity`）。同一载具/房间中上一镜头已经存在但本镜头不是焦点的角色，必须保留为 `secondary_continuity` 或 `offscreen_continuity`，不要直接删除。
    - **逐项核对上一镜头槽位**：输出当前 shot 前，必须把上一 shot 的 `spatial_layout.containers[].slots[]` 和 `loose_positions[]` 当作检查表逐项核对。除非剧本明确发生真实空间变化，否则上一镜头中同一容器/同一空间里的每个角色槽位都必须在当前 shot 继续出现；不是焦点时改为 `secondary_continuity` 或 `offscreen_continuity`。
    - **真实空间变化必须结构化输出**：如果角色离开原容器/原场景、换座、进入其他区域、从车内到车外、从画内移动到另一空间，必须在 `spatial_layout.continuity.changed_positions[]` 输出对象，不能只写在 description/action 中。对象字段包括：`character_id`、`from_container_id`、`from_slot`、`to_container_id`、`to_slot`、`change_type`、`reason`；`change_type` 取值为 `moved_slot`、`entered_container`、`left_container`、`exited_scene`、`entered_scene`。近景/特写造成的画面裁切不是空间变化，不写入 changed_positions，只保留原 slot 并标记 `visibility=offscreen`。
    - 特写/近景规则：如果 camera_angle、容器、座位/空间关系没有明确变化，上一镜头的非焦点角色必须继续保留在 `spatial_layout` 中；若画面能看到则 `visibility=partial` 或 `visible`，若因裁切看不到则 `visibility=offscreen`，并在 `continuity.notes` 说明其仍在原位置。
    - `characters_present` 表示当前首帧应该可见或局部可见的角色；`focus_character_ids` 表示镜头重点。不要为了表达"单人近景/特写"而把仍在画面边缘、背景或局部可见的角色从 `characters_present` 删除。
    - `continuity` 必须说明与前一分镜相比哪些位置保持不变、哪些发生变化；没有明确移动时，应保持上一分镜的物理槽位和角色占用关系，例如上一镜头奶酪在副驾驶座、奶昔在驾驶座，下一镜头即使机位变为面对驾驶室，也仍然是奶酪在副驾驶座、奶昔在驾驶座；画面左右如不确定，可以写更中性的 `screen_position`，但不能交换物理槽位。
    - 结构字段使用 id 和 name，不使用【【】】或〖〖〗〗标记；描述性文本字段仍按上述标记规则输出。

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


PROP_MARKER_RE = re.compile(r"〖〖([^〗]+)〗〗")
PROMPT_PROP_TEXT_KEYS = {
    "description",
    "opening_frame_description",
    "scene_detail",
    "action",
    "mood",
    "environment_sound",
    "background_music",
    "audio_notes",
    "narrative_purpose",
}


def _normalize_asset_name(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"【【([^】]+)】】", r"\1", text)
    text = re.sub(r"〖〖([^〗]+)〗〗", r"\1", text)
    return re.sub(r"[\s　_（）()【】〖〗《》<>，,。.:：;；、\-]+", "", text).lower()


def _safe_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _find_unique_prop_by_name(name: Any, db_props: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    normalized = _normalize_asset_name(name)
    if not normalized:
        return None

    for prop in db_props:
        if _normalize_asset_name(prop.get("name")) == normalized:
            return prop

    fuzzy_matches = [
        prop for prop in db_props
        if _normalize_asset_name(prop.get("name")).endswith(normalized)
        or normalized.endswith(_normalize_asset_name(prop.get("name")))
    ]
    return fuzzy_matches[0] if len(fuzzy_matches) == 1 else None


def _prop_name_appears_in_script(name: Any, script_content: str) -> bool:
    normalized_name = _normalize_asset_name(name)
    if not normalized_name:
        return False
    return normalized_name in _normalize_asset_name(script_content)


def _replace_prop_markers(text: str, valid_marker_props: List[Dict[str, Any]]) -> str:
    def replace(match: re.Match) -> str:
        raw_name = match.group(1).strip()
        matched = _find_unique_prop_by_name(raw_name, valid_marker_props)
        if matched:
            return f"〖〖{matched.get('name', raw_name)}〗〗"
        return raw_name

    return PROP_MARKER_RE.sub(replace, text)


def _flatten_db_locations(db_locations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """递归展平 get_tree_by_world 返回的树形场景列表。

    必须保留 id/name/parent_id：后续 sanitize 对齐父级、名称兜底匹配都依赖完整字段。
    与 location_structure_guard.flatten_db_locations 一致，树节点缺 parent_id 时从父节点继承。
    """
    from services.location_structure_guard import flatten_db_locations

    return flatten_db_locations(db_locations or [])


def _find_unique_location_by_name(name: Any, db_locations_flat: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """按名称在数据库场景中精确匹配 → 唯一后缀模糊匹配（参照 _find_unique_prop_by_name）。"""
    normalized = _normalize_asset_name(name)
    if not normalized:
        return None
    for loc in db_locations_flat:
        if _normalize_asset_name(loc.get("name")) == normalized:
            return loc
    fuzzy_matches = [
        loc for loc in db_locations_flat
        if _normalize_asset_name(loc.get("name")).endswith(normalized)
        or normalized.endswith(_normalize_asset_name(loc.get("name")))
    ]
    return fuzzy_matches[0] if len(fuzzy_matches) == 1 else None


def _align_location_parent_to_database(
    location: Dict[str, Any],
    db_row: Dict[str, Any],
    db_id_to_internal: Dict[int, str],
) -> None:
    """已绑定 DB 的场景：parent_id 以数据库层级为准，忽略 LLM 乱写的父级。"""
    actual_parent_db_id = _safe_int(db_row.get("parent_id"))
    if actual_parent_db_id is None:
        location["parent_id"] = None
        if location.get("level") is not None:
            try:
                location["level"] = 0
            except Exception:
                pass
        return
    parent_internal = db_id_to_internal.get(actual_parent_db_id)
    if parent_internal:
        location["parent_id"] = parent_internal
    else:
        # 父场景未出现在本段 locations 中时，清空错误 parent，避免 location_parent_conflict。
        # 数据库侧父子关系仍以 location_db_id 对应行的 parent_id 为准。
        location["parent_id"] = None


def sanitize_parsed_location_references(
    parsed_data: Dict[str, Any],
    db_locations: Optional[List[Dict[str, Any]]] = None,
    script_content: str = "",
) -> Dict[str, Any]:
    """
    清理 LLM 幻觉出的场景引用。

    LLM 可能在 locations 里声明数据库根本不存在的 location_db_id（编造的假 ID），
    或把 location_db_id 留空当作"新场景"。这里以数据库已有场景为准：
      1. 用 location_db_id 对照数据库主键核实；不在则按名称兜底匹配；
         匹配上 → 复用 DB id（只认数据库场景），并按 DB 回写 parent_id。
      2. 仍未匹配、且 location_db_id 为 null 的新场景 / 子场景 → 保留，
         由后续 storyboard_location_bootstrap_service 负责入库与 id 回填。
         parent_id（内部 loc_xxx）、level、description、atmosphere、
         environment_sound、background_music 等字段完整携带，供九宫格 prompt 使用。
      3. 编造了假 location_db_id（非 null 但 DB 不存在）→ 丢弃，避免假场景穿透。
      4. shot.location_id 指向被丢弃 / 悬空的 location 时置为 null，
         避免假场景穿透到下游 storyboard_scene.prompt.location。
      5. 已给出有效 location_db_id 时，禁止因 LLM 乱写 parent 触发
         location_parent_conflict：父级一律按数据库记录对齐或清空。
    """
    db_flat = _flatten_db_locations(db_locations or [])
    db_locations_by_id = {
        _safe_int(loc.get("id")): loc
        for loc in db_flat
        if _safe_int(loc.get("id")) is not None
    }

    from services.location_structure_guard import match_location_with_parent

    source_locations = [
        location for location in (parsed_data.get("locations") or [])
        if isinstance(location, dict)
    ]
    locations_by_key = {
        str(location.get("id")): location
        for location in source_locations
        if location.get("id") not in (None, "")
    }
    valid_locations: List[Dict[str, Any]] = []
    valid_location_ids = set()  # 合法 location 的内部 loc_xxx
    unpersisted_count = 0
    for location in source_locations:
        given_db_id = _safe_int(location.get("location_db_id"))
        db_match = db_locations_by_id.get(given_db_id)
        if db_match:
            # 显式有效 DB id：始终保留，后续按 DB 对齐 parent。
            pass
        else:
            match_result = match_location_with_parent(location, locations_by_key, db_flat)
            # 名称兜底只有父级一致时才允许绑定。同名异父保留为未入库候选，
            # 让合并级硬门禁给出 location_parent_conflict，而不是静默洗成复用。
            db_match = None if match_result.conflict else match_result.db_location

        if db_match:
            # 已匹配 DB 场景：写回真实 DB id 与名称
            location["location_db_id"] = db_match.get("id")
            location["name"] = db_match.get("name") or location.get("name")
            valid_locations.append(location)
            valid_location_ids.add(str(location.get("id")))
            continue

        # 未匹配 DB：区分"新场景（location_db_id 为 null）"与"编造假 id"
        if _safe_int(location.get("location_db_id")) is None:
            # 新场景 / 子场景：保留，等待 bootstrap 入库与 id 回填
            location["location_db_id"] = None
            valid_locations.append(location)
            valid_location_ids.add(str(location.get("id")))
            unpersisted_count += 1
        # 否则：编造的非 null 假 id → 丢弃

    # 第二遍：凡已绑定 location_db_id 的场景，parent 以数据库为准
    db_id_to_internal: Dict[int, str] = {}
    for location in valid_locations:
        db_id = _safe_int(location.get("location_db_id"))
        internal_id = str(location.get("id") or "").strip()
        if db_id is not None and internal_id:
            db_id_to_internal[db_id] = internal_id
    for location in valid_locations:
        db_id = _safe_int(location.get("location_db_id"))
        if db_id is None:
            continue
        db_row = db_locations_by_id.get(db_id)
        if not db_row:
            continue
        _align_location_parent_to_database(location, db_row, db_id_to_internal)

    parsed_data["locations"] = valid_locations

    # 调试 / 日志辅助字段，不影响旧结构
    metadata = parsed_data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        parsed_data["metadata"] = metadata
    metadata["has_unpersisted_locations"] = unpersisted_count > 0
    metadata["unpersisted_location_count"] = unpersisted_count

    # shot.location_id 悬空或指向被丢弃的 location → 置 null
    for group in parsed_data.get("shot_groups") or []:
        if not isinstance(group, dict):
            continue
        for shot in group.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            loc_id = str(shot.get("location_id") or "")
            if not loc_id or loc_id not in valid_location_ids:
                shot["location_id"] = None

    return parsed_data


def _spatial_container_key(container: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (
        str(container.get("container_type") or ""),
        str(container.get("prop_id") or ""),
        _normalize_asset_name(container.get("name")),
        _normalize_asset_name(container.get("area")),
    )


def _is_character_slot(slot: Dict[str, Any]) -> bool:
    return (
        isinstance(slot, dict)
        and str(slot.get("occupant_type") or "").lower() == "character"
        and bool(slot.get("character_id"))
    )


def _append_unique_text(values: List[Any], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in [str(item) for item in values]:
        values.append(text)


def _changed_positions_include_character(spatial: Dict[str, Any], character_id: str) -> bool:
    continuity = spatial.get("continuity")
    if not isinstance(continuity, dict):
        return False

    changed_positions = continuity.get("changed_positions")
    if not isinstance(changed_positions, list):
        return False

    return any(
        isinstance(change, dict) and str(change.get("character_id") or "") == character_id
        for change in changed_positions
    )


_STABLE_SPATIAL_SLOT_FIELDS = (
    "slot_id",
    "slot",
    "physical_position",
    "position_basis",
)


def _slot_stable_label(slot: Dict[str, Any]) -> str:
    return str(slot.get("slot_id") or slot.get("slot") or slot.get("screen_position") or "").strip()


def _inherit_stable_slot_identity(
    current_slot: Dict[str, Any],
    previous_slot: Dict[str, Any],
) -> bool:
    inherited = False
    for field in _STABLE_SPATIAL_SLOT_FIELDS:
        if field in previous_slot and current_slot.get(field) != previous_slot[field]:
            current_slot[field] = previous_slot[field]
            inherited = True
    return inherited


def repair_spatial_layout_continuity(parsed_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    修复 LLM 在近景/特写中漏掉的空间连续性角色。

    解析提示词要求非焦点角色保留在 spatial_layout，但模型仍可能只输出当前焦点。
    这里按相邻分镜兜底：同一容器里的上一镜头角色若没有在当前镜头出现，就以
    offscreen_continuity 方式补回原 slot；不强行加入 characters_present。
    """
    return _repair_spatial_layout_continuity_core(parsed_data)


def _should_repair_spatial_layout(
    segment_context: Optional[Dict[str, Any]],
) -> bool:
    """v3 由 enterprise 状态机物化，禁止再执行旧空间修复。"""
    return int((segment_context or {}).get("spatial_state_version") or 0) != 1


def _build_incremental_spatial_prompt(
    segment_context: Dict[str, Any],
) -> str:
    previous_state = json.dumps(
        segment_context.get("previous_state") or {},
        ensure_ascii=False,
    )
    allowed_ids = json.dumps(
        segment_context.get("spatial_catalog_prompt") or {},
        ensure_ascii=False,
        indent=2,
    )
    planned_changes = json.dumps(
        segment_context.get("planned_state_changes") or [],
        ensure_ascii=False,
        indent=2,
    )
    previous_camera = json.dumps(
        segment_context.get("previous_camera_summary") or {},
        ensure_ascii=False,
        indent=2,
    )
    return f"""

**【效果模式 v3 · 增量空间意图】**
后端已保存完整物理状态。你负责镜头艺术创作，并只声明剧情中真实发生的空间变化；不要逐镜抄写未变化实体的位置。

每个镜头必须输出 `spatial_intent.state_changes` 数组；没有移动时输出空数组。支持 enter、move、exit、pickup、put_down、transfer。实体和目标只能引用下方允许 ID；anchors 为空时省略 anchor_id，禁止自造 anchor_id。

**二维固定点（优先使用）**：`points` 是完整剧本规划阶段生成的稳定物理点。发生入场或移动时，如果目标存在于 points，`to` 只需输出 `point_id`，不要重复生成或修改 `position_2d`。同一 `point_id` 在所有 segment 中代表同一物理位置；不得因构图变化交换驾驶座/副驾驶座、沙发左右位或柜台内外侧。`entity_points` 是上一段实体当前所在点。没有合适 point 时才使用允许的 container+slot/anchor；普通姿态调整不属于移动。

**道具持有（极易错，必须遵守）**：
- `pickup`：持有人写在 `to.holder_character_id`（推荐）；也可写 change 顶层 `holder_character_id`。不要只把 container/slot 写进 to 却漏 holder。
- `put_down`：`from.holder_character_id` 必须是当前真实持有人；`to` 为放下后的物理落点（container+slot 或 anchor）。
- `transfer`：`from.holder_character_id` 为交出方，`to.holder_character_id` 为接收方（接收方也可写顶层 holder）。
- 角色**提着/拿着道具入场**：`enter` 道具时可在 `to` 或顶层写 `holder_character_id`（持有人须已在场或同一镜更早 enter）；后端会记为手持，不必再单独 pickup。
- 手持中的道具随持有人移动；不要对已手持道具再写无 holder 的自由 move 到台面——应使用 `put_down`。

`characters_present 和 props_present 是唯一可见性真源`：它们只表示当前画面能看见什么，不代表角色/道具离开物理世界。不要新增其他重复的可见性列表。

正例：上一镜林晓在沙发左侧、陈总在右侧；当前是林晓特写，陈总未出镜且没有离开。characters_present 只写林晓，spatial_intent.state_changes=[]。后端会把陈总保留为 offscreen_continuity；禁止为了不出镜而声明 exit。

【上一段或本独立段的规范入点状态（紧凑只读）】
```json
{previous_state}
```
【当前 segment 空间作用域、允许 ID 与二维固定点】
```json
{allowed_ids}
```
【规划期剧情变化（参考，不得由后端代执行）】
```json
{planned_changes}
```
【上一镜摄影机摘要（仅艺术参考）】
```json
{previous_camera}
```
"""


def _repair_shot_spatial_layout_from_previous(
    spatial: Dict[str, Any],
    previous_spatial: Dict[str, Any],
    valid_character_ids: set,
) -> None:
    current_containers = [
        container for container in spatial.get("containers") or []
        if isinstance(container, dict)
    ]
    previous_containers = [
        container for container in previous_spatial.get("containers") or []
        if isinstance(container, dict)
    ]
    if not current_containers or not previous_containers:
        return

    current_by_key = {
        _spatial_container_key(container): container
        for container in current_containers
    }
    current_character_ids = {
        str(slot.get("character_id"))
        for container in current_containers
        for slot in container.get("slots") or []
        if _is_character_slot(slot)
    }

    continuity = spatial.get("continuity")
    if not isinstance(continuity, dict):
        continuity = {}
        spatial["continuity"] = continuity
    unchanged_slots = continuity.get("unchanged_slots")
    if not isinstance(unchanged_slots, list):
        unchanged_slots = []
        continuity["unchanged_slots"] = unchanged_slots

    carried_notes: List[str] = []
    for previous_container in previous_containers:
        current_container = current_by_key.get(_spatial_container_key(previous_container))
        if not current_container:
            continue

        current_slots = current_container.get("slots")
        if not isinstance(current_slots, list):
            current_slots = []
            current_container["slots"] = current_slots

        previous_slots_by_character = {
            str(slot.get("character_id")): slot
            for slot in previous_container.get("slots") or []
            if _is_character_slot(slot)
        }
        for current_slot in current_slots:
            if not _is_character_slot(current_slot):
                continue
            character_id = str(current_slot.get("character_id"))
            previous_slot = previous_slots_by_character.get(character_id)
            if not previous_slot:
                continue
            if _changed_positions_include_character(spatial, character_id):
                continue
            if _inherit_stable_slot_identity(current_slot, previous_slot):
                _append_unique_text(unchanged_slots, _slot_stable_label(current_slot))

        for previous_slot in previous_container.get("slots") or []:
            if not _is_character_slot(previous_slot):
                continue

            character_id = str(previous_slot.get("character_id"))
            if valid_character_ids and character_id not in valid_character_ids:
                continue
            if character_id in current_character_ids:
                continue
            if _changed_positions_include_character(spatial, character_id):
                continue

            carried_slot = dict(previous_slot)
            carried_slot["visibility"] = "offscreen"
            carried_slot["framing_role"] = "offscreen_continuity"
            current_slots.append(carried_slot)
            current_character_ids.add(character_id)

            slot_name = _slot_stable_label(carried_slot)
            _append_unique_text(unchanged_slots, slot_name)
            name = carried_slot.get("name") or character_id
            if slot_name:
                carried_notes.append(f"{name}仍在{slot_name}，本镜头因构图裁切处于镜头外")
            else:
                carried_notes.append(f"{name}仍在上一镜头空间位置，本镜头因构图裁切处于镜头外")

    if carried_notes:
        old_notes = str(continuity.get("notes") or "").strip()
        addendum = "；".join(carried_notes)
        continuity["notes"] = f"{old_notes}；{addendum}" if old_notes else addendum


def sanitize_parsed_prop_references(
    parsed_data: Dict[str, Any],
    db_props: Optional[List[Dict[str, Any]]] = None,
    script_content: str = "",
) -> Dict[str, Any]:
    """
    清理 LLM 幻觉出的道具引用。

    LLM 可能在画面提示词里标记未提供、也未出现在原始剧本中的道具。
    这里以数据库道具和原始剧本文本为准，避免无效道具进入 props、props_present
    或后续参考图匹配。
    """
    db_props = db_props or []
    db_props_by_id = {
        _safe_int(prop.get("id")): prop
        for prop in db_props
        if _safe_int(prop.get("id")) is not None
    }

    valid_props: List[Dict[str, Any]] = []
    valid_prop_ids = set()
    for prop in parsed_data.get("props") or []:
        if not isinstance(prop, dict):
            continue

        prop_name = prop.get("name")
        db_match = db_props_by_id.get(_safe_int(prop.get("props_db_id")))
        if not db_match:
            db_match = _find_unique_prop_by_name(prop_name, db_props)

        if db_match:
            prop["props_db_id"] = db_match.get("id")
            prop["name"] = db_match.get("name") or prop_name
            valid_props.append(prop)
            valid_prop_ids.add(str(prop.get("id")))
            continue

        if _prop_name_appears_in_script(prop_name, script_content):
            prop["props_db_id"] = None
            valid_props.append(prop)
            valid_prop_ids.add(str(prop.get("id")))

    parsed_data["props"] = valid_props

    valid_marker_props = []
    seen_marker_names = set()
    for prop in [*valid_props, *db_props]:
        normalized = _normalize_asset_name(prop.get("name") if isinstance(prop, dict) else "")
        if normalized and normalized not in seen_marker_names:
            seen_marker_names.add(normalized)
            valid_marker_props.append(prop)

    for group in parsed_data.get("shot_groups") or []:
        if not isinstance(group, dict):
            continue
        for shot in group.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            if isinstance(shot.get("props_present"), list):
                shot["props_present"] = [
                    prop_id for prop_id in shot["props_present"]
                    if str(prop_id) in valid_prop_ids
                ]
            for key in PROMPT_PROP_TEXT_KEYS:
                if isinstance(shot.get(key), str):
                    shot[key] = _replace_prop_markers(shot[key], valid_marker_props)

    return parsed_data


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
  "spatial_world": {
    "space_units": [
      {
        "space_unit_id": "space_prop_001_cabin",
        "name": "泡泡蒸汽车驾驶室",
        "owner_type": "prop",
        "owner_id": "prop_001",
        "location_ids": ["loc_001", "loc_002"],
        "coordinate_frame": {
          "frame_id": "frame_prop_001_cabin",
          "origin": "驾驶室中心",
          "axes": {
            "x_positive": "车辆自身右侧",
            "y_positive": "车辆自身前方",
            "z_positive": "上方"
          },
          "scale": "normalized_unit_box",
          "locked": true
        },
        "anchors": [
          {
            "anchor_id": "front_driver_seat",
            "label": "驾驶座",
            "position_3d": {"x": 0.55, "y": 0.45, "z": 0.25}
          },
          {
            "anchor_id": "front_passenger_seat",
            "label": "副驾驶座",
            "position_3d": {"x": -0.55, "y": 0.45, "z": 0.25}
          }
        ]
      },
      {
        "space_unit_id": "space_loc_002_syrup_trap",
        "name": "糖浆陷阱区域",
        "owner_type": "location",
        "owner_id": "loc_002",
        "location_ids": ["loc_002"],
        "coordinate_frame": {
          "frame_id": "frame_loc_002_syrup_trap",
          "origin": "糖浆陷阱区域中心",
          "axes": {
            "x_positive": "道路右侧",
            "y_positive": "道路前方",
            "z_positive": "上方"
          },
          "scale": "normalized_scene_box",
          "locked": true
        },
        "anchors": [
          {
            "anchor_id": "syrup_pool_center",
            "label": "糖浆池中心",
            "position_3d": {"x": 0, "y": 0, "z": 0}
          }
        ]
      }
    ]
  },
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
          "opening_frame_description": "镜头起始画面的详细描述（用于AI生成首帧图像,必须详细到能让AI准确还原画面,包括：画面中所有在场角色（用【【角色名】】格式）的位置、姿态、表情或动作（固有外貌如发型/体型/标志服装不要写，交给角色库）；场景布局、物品摆放、光线方向和强度；构图信息如三分法、景深、视角等。涉及道具时用〖〖道具名〗〗格式）",
          "scene_detail": "场景详细描述（描述整个镜头过程中的画面变化,涉及角色时用【【角色名】】格式，涉及道具时用〖〖道具名〗〗格式）",
          "characters_present": ["char_001"],
          "focus_character_ids": ["char_001"],
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
          "difficulty": "易/中/难",
          "difficulty_reason": "难度判定依据（一句话，综合人物数量/动作/时长/道具/镜头运动）",
          "spatial_layout": {
            "schema_version": 2,
            "space_unit_refs": ["space_prop_001_cabin"],
            "camera_pose": {
              "space_unit_id": "space_prop_001_cabin",
              "eye": {"x": 0.0, "y": -0.8, "z": 0.6},
              "target": {"x": 0.3, "y": 0.45, "z": 0.35},
              "up": {"x": 0, "y": 0, "z": 1},
              "fov": "medium"
            },
            "camera_anchor": {
              "description": "从车外左侧车窗外向车内拍摄，机位位于【【奶酪_Cheese】】的左前方约30度，隔着车窗玻璃观察车内",
              "camera_position": "车外左侧车窗外",
              "shooting_direction": "穿过左侧车窗向车内驾驶台方向拍摄",
              "relative_to_character": {
                "character_id": "char_001",
                "name": "奶酪_Cheese",
                "position": "左前方30度",
                "distance": "隔着车窗的中景距离"
              },
              "view_direction": "left_to_right",
              "screen_axis_mapping": {
                "container_left": "screen_left",
                "container_right": "screen_right",
                "container_front": "screen_depth_front",
                "container_rear": "screen_depth_back"
              },
              "screen_composition": "【【奶酪_Cheese】】位于画面左侧并贴近左侧车窗玻璃，【【奶昔_Milkshake】】位于画面右侧驾驶座，二者之间可见驾驶台和拉杆"
            },
            "location_path": [
              {
                "location_id": "loc_001",
                "location_db_id": 123,
                "name": "真实场景名称",
                "role": "current_scene"
              }
            ],
            "containers": [
              {
                "container_type": "prop",
                "prop_id": "prop_001",
                "props_db_id": 456,
                "name": "真实道具名称",
                "area": "容器内区域，如驾驶室",
                "position_in_location": "该容器在当前场景中的位置",
                "slots": [
                  {
                    "space_unit_id": "space_prop_001_cabin",
                    "anchor_id": "front_passenger_seat",
                    "slot_id": "front_left_seat",
                    "slot": "驾驶室左侧座位",
                    "position_3d": {"x": -0.55, "y": 0.45, "z": 0.25},
                    "physical_position": {
                      "row": "front",
                      "side": "vehicle_left",
                      "basis": "container_forward_direction"
                    },
                    "position_basis": "physical_slot",
                    "screen_position": "画面左侧",
                    "occupant_type": "character",
                    "character_id": "char_001",
                    "character_db_id": 789,
                    "name": "角色名",
                    "pose": "当前镜头姿态或动作",
                    "visibility": "visible/partial/offscreen/occluded",
                    "framing_role": "primary_subject/secondary_continuity/background/offscreen_continuity"
                  }
                ]
              }
            ],
            "loose_positions": [],
            "continuity": {
              "unchanged_slots": [],
              "changed_positions": [
                {
                  "character_id": "char_002",
                  "from_container_id": "prop_001",
                  "from_slot": "副驾驶座",
                  "to_container_id": null,
                  "to_slot": null,
                  "change_type": "moved_slot/entered_container/left_container/exited_scene/entered_scene",
                  "reason": "真实空间变化原因；如果只是近景裁切导致看不见，不要写 changed_positions"
                }
              ],
              "notes": "说明与前一分镜的位置延续或变化"
            }
          },
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
          "difficulty": "中",
          "difficulty_reason": "两人互动递接关键道具，含简单镜头运动",
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
    model_id: Optional[int] = None,
    enable_thinking: bool = False,
    thinking_effort: str = "medium",
    previous_parsed_result: Optional[Dict[str, Any]] = None,
    qc_feedback: Optional[Any] = None,
    # 分段拆分支持（见 docs/script/script_parser_incremental_split_design.md §7.2）
    # 不传时行为与原调用完全一致；传入后约束模型只为当前分段生成分镜。
    segment_context: Optional[Dict[str, Any]] = None,
    # 拆分任务创建时由服务端生成的角色库不可变快照；传入后禁止在段内重新读库。
    character_contract: Optional[Dict[str, Any]] = None,
    # strict_json=True 时禁用末尾补括号修复，解析失败直接交给调用方重试。
    # 默认 False 保留兼容能力，但补全成功后不再提前 return，会继续走完整后处理。
    strict_json: bool = False,
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
        previous_parsed_result: 质检失败后的上一轮完整拆分 JSON（可选）
        qc_feedback: 质检报告（QcReport / dict / 文本），注入重拆要求（可选）
    
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
            log_dir = Path(ScriptParserConstants.DIAGNOSTIC_LOG_DIR)
            await asyncio.to_thread(log_dir.mkdir, parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        else:
            log_dir = None
            timestamp = None

        # 获取数据库中的场景列表（如果提供了world_id）
        db_locations_text = ""
        db_locations = []
        if world_id is not None:
            try:
                from model.location import LocationModel
                logger.info(f"Attempting to load locations for world_id: {world_id}")
                db_locations = await asyncio.to_thread(
                    LocationModel.get_tree_by_world,
                    world_id,
                    20,
                )
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

**【硬性前提·禁止假设世界资产为空】**
- 严禁在思考中假设或声称"世界资产为空""没有预置世界资产""这是独立剧本无预置资产"。世界已有场景严格以下方【数据库已有场景列表】为准。
- 剧本中出现的每个地点，必须先在下方列表中按"名称+描述语义相似"查找匹配项并复用其 location_db_id。
- 列表里没有的新地点：优先挂到列表中语义相关的已有顶层作为子场景（parent_id 指向已有顶层的内部 loc_xxx）；只有确实找不到合适父场景时，才作为 parent_id=null 的新顶层场景登记。

**【数据库已有场景列表】**
以下是数据库中已存在的场景（最多20个），如果剧本中的场景与数据库中的场景相同或相似，请在返回的location对象中设置location_db_id字段为对应的数据库场景ID：

{chr(10).join(location_lines)}

**【重要警告】关于location_db_id与parent_id：**
- 如果剧本中的场景与上述数据库场景匹配，请设置location_db_id为数据库场景的ID（必须是上面列表中实际存在的ID）
- **已设置真实 location_db_id 时：以数据库该行为唯一真源**——name 用库中名称；parent_id 必须与库中父子一致（树形缩进表示父子；顶层场景 parent_id=null）
- **禁止**在已绑定 location_db_id 后，凭剧情把顶层场景改写成某大厅/走廊的子场景，或改挂到错误父场景
- **禁止因时间不同复制场景**：同一物理地点（如前台、大堂）在剧本中出现「深夜/白天/次日」等不同时间，仍必须复用库中已有场景或本输出中已登记的同一 location；**不要**创建「前台（深夜版）」这类时间变体子场景，**也不要给场景名加下划线/连接符/括号等时段后缀**（`现代客厅_夜晚`、`大堂-深夜` 都违规，必须去掉后缀归并为 `现代客厅`/`大堂`）。时间只写在分镜字段（time_of_day、画面描述、氛围）里
- 如果剧本中的场景是新场景，不在数据库中，则location_db_id必须设置为null；优先把 parent_id 指向本输出中已有的合法父场景（已有顶层）内部 id，确实找不到合适父场景时才留空（parent_id=null）作为新顶层登记
- 匹配时要考虑场景名称和描述的相似性，不需要完全一致（**匹配地点本身，忽略时间后缀**）
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
        db_props = []
        if world_id is not None:
            try:
                from model.props import PropsModel
                logger.info(f"Attempting to load props for world_id: {world_id}")
                props_result = await asyncio.to_thread(
                    PropsModel.list_by_world,
                    world_id,
                    1,
                    50,
                )
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
- **严禁在画面描述中添加数据库列表和原始剧本文本都没有出现的道具；这类道具不能放入props数组、props_present，也不能用〖〖〗〗标记**
"""
                    logger.info(f"Generated db_props_text with {len(props_lines)} props entries")
                else:
                    logger.warning(f"No props found for world_id: {world_id}")
            except Exception as e:
                logger.error(f"Failed to load database props: {e}", exc_info=True)

        # 获取数据库中的角色列表（如果提供了world_id）
        db_characters_text = ""
        if world_id is not None or character_contract is not None:
            try:
                from services.script_split_character_contract import (
                    build_character_contract_snapshot,
                    contract_to_parser_characters,
                )
                effective_contract = character_contract
                if effective_contract is None:
                    effective_contract = await asyncio.to_thread(
                        build_character_contract_snapshot,
                        world_id,
                    )
                db_characters = contract_to_parser_characters(effective_contract)
                logger.info(
                    "Loaded %d characters from immutable character contract for world_id=%s",
                    len(db_characters),
                    world_id,
                )

                if db_characters:
                    # 将角色列表格式化为文本
                    char_lines = []
                    for char in db_characters:
                        # 拼接角色的多个维度信息（身份/外貌/性格），让 LLM 对每个角色有更全面的认识，
                        # 减少因信息片面而漏写次要角色的情况
                        _parts = []
                        for _key, _label in (('identity', '身份'), ('appearance', '外貌'), ('personality', '性格')):
                            _val = char.get(_key)
                            if _val:
                                _parts.append(f"{_label}: {_val}")
                        char_desc = "；".join(_parts) if _parts else "无"
                        char_lines.append(f"- ID: {char['id']}, 名称: {char['name']}, 描述: {char_desc}")

                    db_characters_text = f"""

**【数据库已有角色列表】**
以下是数据库中已存在的完整角色快照，如果剧本中的角色与数据库中的角色相同或相似，请在返回的character对象中设置character_db_id字段为对应的数据库角色ID：

{chr(10).join(char_lines)}

**【重要警告】关于character_db_id字段：**
- 如果剧本中的角色与上述数据库角色匹配，请设置character_db_id为数据库角色的ID（必须是上面列表中实际存在的ID）
- 匹配数据库角色后，character.name 必须逐字使用列表中的完整名称；禁止省略下划线后的外文名、使用简称、翻译或自行改名
- 图片/视频提示词引用该角色时，必须逐字写成 `【【完整名称】】`；例如列表名称为 `奶昔_Milkshake`，只能写 `【【奶昔_Milkshake】】`，禁止写 `【【奶昔】】`
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
  * **【焦点规则】每个镜头只能聚焦一个说话角色：`focus_character_ids` 只放该说话角色，`framing_role=primary_subject` 只给该角色**
  * **【空间连续性例外】非说话角色如果上一镜头已经在同一载具、房间、座位或空间关系中，且本镜头没有在 `spatial_layout.continuity.changed_positions` 声明真实空间变化，不能从 `spatial_layout` 中删除；应以 `secondary_continuity`、`background` 或 `offscreen_continuity` 保留**
  * **【正确做法】画面描述聚焦说话角色，但允许用弱化方式交代非说话角色：例如“画面边缘/背景中/模糊轮廓/肩部局部/镜头外仍在副驾驶位”。严禁把非说话角色写成发言主体或抢占画面主体**
  * **【禁止行为】严禁把非说话角色写成发言主体、动作主体或第二主角；但不要为了单人近景而让仍在场的角色凭空消失**
  * 按照对话顺序依次拆分，保持对话的连贯性
  * 每个拆分镜头的shot_type应该使用"近景"或"中景"，展现说话角色的面部表情
  * 每个拆分镜头的duration根据该角色台词长度合理分配（通常3-6秒）
  * characters_present数组默认包含说话角色；如果非说话角色在首帧中仍然可见或局部可见（visibility 为 visible/partial），也必须保留在 characters_present。若非说话角色完全因裁切到镜头外，则不放入 characters_present，但必须在 spatial_layout 中保留其 slot，并标记 visibility=offscreen、framing_role=offscreen_continuity。
  
- **【关键】遵守180度轴线原则，避免画面越轴：**
  * 假设两个角色A和B对话，建立一条虚拟的轴线连接两人
  * 摄像机必须始终保持在轴线的同一侧拍摄
  * 正确示例：角色A在画面左侧面向右，角色B在画面右侧面向左（正反打）
  * 错误示例：角色A和B都面向同一方向，或者位置关系突然颠倒
  * 在opening_frame_description中明确描述说话角色在画面中的位置和朝向；如非说话角色可见，只能作为空间连续性背景/边缘/局部信息简短描述
  
- **【拆分示例 - 正确做法】：**
  * 原镜头：中景，A和B在咖啡厅对话
    - dialogue: [{"character_id": "A", "text": "你好吗？"}, {"character_id": "B", "text": "我很好，谢谢"}]
    - opening_frame_description: "中景：【【A】】和【【B】】坐在咖啡厅..." ❌ 错误！
    
  * 拆分后（正确）：
    - 镜头1：中景，A说话
      - dialogue: [{"character_id": "A", "text": "你好吗？"}]
      - focus_character_ids: ["char_001"]  // 只有A是说话焦点
      - characters_present: ["char_001"]  // 如果B被构图裁切到镜头外，则只放可见的A
      - description: "【【A】】说话，视线看向镜头外的对座"  // 聚焦A，但保留对座空间关系
      - opening_frame_description: "中景：【【A】】坐在咖啡厅的座位上，身体微微前倾，双手放在桌上，面带微笑，眼神看向画面右侧（镜头外），嘴唇微动正在说话；对座的B仍在原座位但被当前构图裁切到镜头外"  ✓ 正确！A是焦点，B以镜头外空间连续性保留
      - spatial_layout: A的slot标记primary_subject；B的原slot继续保留，visibility=offscreen，framing_role=offscreen_continuity
      - scene_detail: "【【A】】在咖啡厅中说话，表情友好，仍朝向对座回应"  ✓ 正确！只让A成为动作主体
      - action: "【【A】】微笑着询问镜头外的对方"  ✓ 正确！只让A成为动作主体
      
    - 镜头2：中景，B回应
      - dialogue: [{"character_id": "B", "text": "我很好，谢谢"}]
      - focus_character_ids: ["char_002"]  // 只有B是说话焦点
      - characters_present: ["char_002"]
      - description: "【【B】】回应，视线看向镜头外的对座"
      - opening_frame_description: "中景：【【B】】坐在咖啡厅的另一侧座位，身体放松靠在椅背上，双手交叉放在胸前，面带笑容，眼神看向画面左侧（镜头外），点头回应；对座的A仍在原座位但被当前构图裁切到镜头外"  ✓ 正确！B是焦点，A以镜头外空间连续性保留
      - spatial_layout: B的slot标记primary_subject；A的原slot继续保留，visibility=offscreen，framing_role=offscreen_continuity
      - scene_detail: "【【B】】在咖啡厅中回应，表情轻松愉快"
      - action: "【【B】】点头微笑着回答"

- **【错误示例 - 严禁这样做】：**
  * ❌ 错误1：opening_frame_description: "中景：【【A】】和【【B】】坐在咖啡厅，【【A】】正在说话..."
    - 问题：把A和B都写成同等画面主体，削弱了单人焦点
  * ❌ 错误2：scene_detail: "【【A】】对【【B】】说话，【【B】】在认真倾听"
    - 问题：把非说话角色B写成动作主体；应改为“A看向镜头外的对座说话”，B只在 spatial_layout 中保留空间位置
  * ❌ 错误3：description: "【【A】】和【【B】】在对话"
    - 问题：没有明确当前说话焦点
  * ❌ 错误4：focus_character_ids: ["char_001", "char_002"]
    - 问题：单人对话镜头包含了两个焦点/说话主体
  
- **【正确示例 - 应该这样做】：**
  * ✓ 正确1：opening_frame_description: "中景：【【A】】坐在咖啡厅，身体前倾，面带微笑看向镜头外右侧，正在说话"
    - 只描述A，通过"看向镜头外"暗示对方存在
  * ✓ 正确2：scene_detail: "【【B】】在咖啡厅中回应，表情轻松"
    - 只描述B的状态
  * ✓ 正确3：description: "【【A】】说话"
    - 只提一个角色
  * ✓ 正确4：focus_character_ids: ["char_001"]；characters_present 可包含首帧中可见/局部可见的空间连续性角色
    - 只有一个说话焦点；非说话角色如仍在画面边缘或背景中，可作为 secondary_continuity 保留

- **注意事项：**
  * 拆分后的镜头仍然属于同一个shot_group（如果总时长不超限）
  * 保持场景的连续性，location_id、time_of_day、weather等保持一致
  * 通过"看向镜头外"、"看向右侧/左侧"等描述暗示对话对象的存在，但不要直接描述对方
  * 确保拆分后的镜头在视觉上能够自然衔接（通过轴线原则）

- **【防漏拆·极其重要】原镜头里有几个角色在对话，就必须拆出几个对应的单人镜头，严禁只拆出部分角色**：
  * 例如原镜头 dialogue 依次为 A、B、C 三人发言，必须拆出 3 个镜头，分别聚焦 A、B、C，不能只拆出 A、B 而漏掉 C
  * 即使某角色台词很短或只有一句反应（如"嗯"、"好的"），也必须为其单独拆出一个镜头，让该角色有自己的画面出场
  * 拆分完成后请自检：原镜头 characters_present 中的每个说话角色，是否都成为了至少一个拆分镜头的唯一 focus_character；若有说话角色从未单独成为焦点，必须补齐
  * 这与"角色完整出场"规则一致：拆分模式下"全员出场"= 每个对话角色都有属于自己的焦点镜头；同一空间里的非说话角色仍可作为空间连续性角色保留

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

        # 质检失败重拆：注入上一轮结果与问题列表
        qc_retry_block = ""
        qc_feedback_log_data = None
        if previous_parsed_result or qc_feedback:
            try:
                from llm.script_split_qc_agent import compact_parsed_for_feedback, QcReport
            except Exception:
                compact_parsed_for_feedback = None
                QcReport = None
            prev_text = ""
            if previous_parsed_result and compact_parsed_for_feedback:
                try:
                    prev_text = compact_parsed_for_feedback(previous_parsed_result)
                except Exception:
                    prev_text = json.dumps(previous_parsed_result, ensure_ascii=False)[:80000]
            elif previous_parsed_result:
                prev_text = json.dumps(previous_parsed_result, ensure_ascii=False)[:80000]
            feedback_text = ""
            if qc_feedback is not None:
                if QcReport and isinstance(qc_feedback, QcReport):
                    qc_feedback_log_data = qc_feedback.to_dict()
                    feedback_text = qc_feedback.format_for_prompt()
                elif isinstance(qc_feedback, dict):
                    qc_feedback_log_data = qc_feedback
                    try:
                        issues = qc_feedback.get("issues") or []
                        lines = [qc_feedback.get("summary") or "质检未通过："]
                        for i, iss in enumerate(issues[:40], 1):
                            if isinstance(iss, dict):
                                lines.append(
                                    f"{i}. [{iss.get('severity','error').upper()}][{iss.get('code')}] "
                                    f"{iss.get('shot_ref','')} {iss.get('field','')}: {iss.get('message','')}"
                                )
                        feedback_text = "\n".join(lines)
                    except Exception:
                        feedback_text = json.dumps(qc_feedback, ensure_ascii=False)[:20000]
                else:
                    qc_feedback_log_data = {"text": str(qc_feedback)}
                    feedback_text = str(qc_feedback)[:20000]
            qc_retry_block = f"""

**【质检失败 · 必须重拆修复】**
上一轮拆分未通过质检。请输出**当前段完整 JSON**（不要只输出 diff，也不要只输出 shot_groups）。
完整 JSON 必须包含顶层 `characters`、`locations`、`props`、`spatial_world`、`shot_groups`。
优先修复 severity=error 的项；未提及的部分不要无故改坏。

【质检反馈】
{feedback_text or '（无结构化反馈）'}

【上一轮拆分结果（压缩 JSON，供对照修复）】
```json
{prev_text or '{}'}
```

"""

        # 分段拆分上下文：约束模型只为当前分段生成分镜（见设计文档 §7.2）。
        # 不传 segment_context 时该块为空，行为与原调用完全一致。
        segment_context_block = ""
        if segment_context:
            import json as _json_for_ctx
            seg_id = segment_context.get("segment_id", "")
            seg_idx = segment_context.get("segment_index")
            total_seg = segment_context.get("total_segments")
            accepted_registry = segment_context.get("accepted_registry") or {}
            tail_summary = segment_context.get("previous_tail_summary") or []
            continuity_state = segment_context.get("continuity_state") or {}
            id_reservations = segment_context.get("id_reservations") or {}
            registry_text = _json_for_ctx.dumps(accepted_registry, ensure_ascii=False)[:80000] if accepted_registry else "{}"
            tail_text = _json_for_ctx.dumps(tail_summary, ensure_ascii=False)[:20000] if tail_summary else "[]"
            continuity_text = _json_for_ctx.dumps(continuity_state, ensure_ascii=False)[:20000] if continuity_state else "{}"
            res_text = ", ".join(f"{k}={v}" for k, v in id_reservations.items()) if id_reservations else "（首段，从 char_001/loc_001/prop_001 起）"

            # 效果模式（quality）：把空间契约从"参考信息"提升为"硬约束"。
            # 历史问题：原 continuity_text 只是平铺的 JSON 参考，模型不知道首/末镜头
            # 的角色位置必须逐字段等于契约值，导致 quality_continuity_in/out_mismatch
            # 占质检错误 50%+。同时 spatial_world（合法 space_unit/anchor 清单）从未下发，
            # 模型自行编造容器/锚点 → ref_prop_unknown / ref_anchor_unknown 占 30%+。
            quality_mode = bool(segment_context.get("quality_mode"))
            spatial_contract_block = ""
            incremental_spatial = (
                quality_mode
                and int(segment_context.get("spatial_state_version") or 0) == 1
            )
            if incremental_spatial:
                spatial_contract_block = _build_incremental_spatial_prompt(
                    segment_context
                )
            if quality_mode and not incremental_spatial:
                spatial_contract = segment_context.get("spatial_contract") or {}
                continuity_in = spatial_contract.get("continuity_in") or {}
                continuity_out = spatial_contract.get("continuity_out") or {}
                state_changes = spatial_contract.get("state_changes") or []
                spatial_world = segment_context.get("spatial_world") or {}
                global_registry = segment_context.get("global_registry") or {}

                # 合法空间引用清单：从 spatial_world 提取 space_unit_id 与 (space_unit_id, anchor_id)
                su_ids = [u.get("space_unit_id") for u in (spatial_world.get("space_units") or []) if u.get("space_unit_id")]
                anchor_pairs = []
                for u in (spatial_world.get("space_units") or []):
                    suid = u.get("space_unit_id")
                    for a in (u.get("anchors") or []):
                        if suid and a.get("anchor_id"):
                            anchor_pairs.append(f"{suid}/{a['anchor_id']}")
                su_text = ", ".join(su_ids) if su_ids else "（无，需在本段 spatial_world 中声明后再引用）"
                anchor_text = ", ".join(anchor_pairs) if anchor_pairs else "（无）"
                sc_text = _json_for_ctx.dumps(state_changes, ensure_ascii=False)[:8000] if state_changes else "[]"
                gr_text = _json_for_ctx.dumps(global_registry, ensure_ascii=False)[:40000] if global_registry else "{}"

                # 入点/出点约束（①②项）按依赖类型分叉（设计文档 §11.1）：
                # - 有 upstream_spatial_handoff（依赖段）：用上游真实布局，continuity_in/out 不作硬约束
                # - 无 handoff（独立段）：用规划契约 continuity_in/out
                upstream_handoff = segment_context.get("upstream_spatial_handoff") or {}
                if upstream_handoff:
                    from enterprise.services.script_split_quality.spatial_handoff import serialize_handoff
                    handoff_text = serialize_handoff(upstream_handoff)
                    entry_exit_constraint = f"""1. **首镜头入点约束（继承上游真实布局）**：首镜头每个在场角色的物理位置必须**继承上游段最后镜头的实际 spatial_layout**（space_unit_id / container_id / slot_id / position_3d 完全一致）。以下 JSON 来自上游真实生成结果，不是规划猜测：
```json
{handoff_text}
```
2. **末镜头出点约束**：末镜头同理，按剧情推进设置出点位置，必须与本段 state_changes 一致。"""
                else:
                    cin_text = _json_for_ctx.dumps(continuity_in, ensure_ascii=False)[:8000] if continuity_in else "{}"
                    cout_text = _json_for_ctx.dumps(continuity_out, ensure_ascii=False)[:8000] if continuity_out else "{}"
                    entry_exit_constraint = f"""1. **首镜头入点约束**：首镜头 spatial_layout 中，continuity_in.characters 列出的每个 character_id，其在 containers.slots（或 loose_positions）里的 space_unit_id、container_id、slot_id 必须**完全等于**契约给定值。契约中未出现的角色不得在首镜头的 spatial_layout 中出现位置。
```json
{cin_text}
```
2. **末镜头出点约束**：末镜头同理，每个在场角色位置必须**完全等于** continuity_out 的值。
```json
{cout_text}
```"""

                spatial_contract_block = f"""

**【效果模式 · 空间连续性硬约束（必须严格遵守，否则质检必失败）】**
本段分镜的**首镜头**与**末镜头**是段间衔接点，其中每个在场角色的物理位置必须**逐字段等于**下方给定值（space_unit_id / container_id / slot_id 三者完全一致，不得近似、不得省略）。

{entry_exit_constraint}

3. **段内位置变化**：仅允许 continuity 契约声明的 state_changes，不得自行增减角色移动。state_changes 如下：
```json
{sc_text}
```

4. **合法空间引用清单**：spatial_layout 中引用的 space_unit_id、anchor_id 必须来自下列合法集合，或在**本段 shot_groups 同级的 spatial_world 中先行声明**。不得编造未声明的容器(container)/锚点(anchor)/空间单元(space_unit)。
   - 合法 space_unit_id：{su_text}
   - 合法 anchor（格式 space_unit_id/anchor_id）：{anchor_text}

5. **全局资产真源**：以下为规划阶段确定的全局实体注册表（characters/locations/props/spatial_world）。已有实体必须复用其中 id；**新实体用 char_tmp_xxx / loc_tmp_xxx / prop_tmp_xxx（本段唯一）**，不要自行占用预留数字号（参考起始：{res_text}）。同名/同 db_id 禁止另起新 id。
```json
{gr_text}
```
"""

            segment_context_block = f"""

**【分段拆分模式 · 第 {seg_idx}/{total_seg} 段 segment_id={seg_id}】**
你只需为下方剧本内容中的**当前分段**生成分镜，不要生成其他段。
- 历史尾部摘要只用于保持连续性，**不得重复生成**已拆过的历史镜头。
- 优先复用「已接受资产注册表」中的角色/场景/道具：同名或同 db_id 必须使用注册表里的全局 id（char_xxx/loc_xxx/prop_xxx）。
- **全局 ID 规则（重要）**：
  - **已有实体**：id 必须等于注册表中的 id；name 与注册表一致；有则填 character_db_id/location_db_id/props_db_id。
  - **本段新建实体**：不要自行猜测下一个 loc_005/prop_005 数字号；请使用**本段内唯一**的临时 id：`loc_tmp_<英文或拼音后缀>`、`prop_tmp_<后缀>`、`char_tmp_<后缀>`（例：`loc_tmp_balcony`、`prop_tmp_badge`）。镜头与 spatial 中引用同一临时 id。后端会按 name/db_id 匹配注册表并分配真正的全局编号。
  - **禁止**新实体从 char_001/loc_001/prop_001 重开编号，也禁止使用已占用号段。
  - 预留起始（仅供参考，新实体请用 tmp）：{res_text}。
- **场景层级硬规则**：拆分流程严禁创建新的顶层场景。请尽可能按数据库场景列表中的真实 `location_db_id` 复用已有场景；允许复用已有顶层场景，但 `location_db_id` 必须真实有效。
- **已有 DB 场景（已声明真实 location_db_id）**：必须按该 ID 复用，name/`parent_id` 以数据库列表为准；**禁止**为“剧情上像子区域”而把库中顶层场景的 `parent_id` 改写成其他场景。不确定父子时：`parent_id=null`（由库真源决定），不要猜。
- **同一地点不因时间拆分**：剧本「场景3：前台 - 深夜十二点」与已有「酒店前台区域/大堂」是同一物理空间时，**必须复用已有 location**（优先 location_db_id=库中前台或大堂），**禁止**新建「前台区域（深夜版）」等时间变体场景或仅为时间变化挂子场景。时间变化只写在 shot 的 `time_of_day` 与画面/氛围描述中。
- 若确需创建新场景，必须输出 `location_db_id=null` 且 `parent_id` 指向一个合法父场景内部 ID；严禁输出 `location_db_id=null,parent_id=null`，也严禁为绕过父场景缺失而把子场景提升为顶层；**且新场景必须是新的物理空间，不能仅是已有场景的时间版**；新场景的 id 用 `loc_tmp_xxx`。
- 分镜编号可以是段内编号，最终由后端统一重排。
{spatial_contract_block}
【已接受资产注册表（必须复用其中已有全局 ID）】
```json
{registry_text}
```

【上一段最后镜头摘要（仅用于连续性参考，勿重复生成）】
```json
{tail_text}
```

【上一段结束时的空间连续性状态】
```json
{continuity_text}
```
"""

        # 构建用户提示词
        user_prompt = f"""请将以下剧本内容解析为结构化的JSON数据。
{qc_retry_block}{segment_context_block}
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
   - 必须包含：该镜头 characters_present 中**所有在场角色**（用【【角色名】】格式包裹），并**分别**写出每个人物的位置、姿态、表情、当前动作（固有外貌如发型/体型/标志服装不要写，交给角色库）
   - 必须包含：场景布局、物品摆放、光线方向和强度
   - 必须包含：构图信息（如三分法、景深、视角等）
   - 描述要具体到能让AI准确还原画面
   - **【重要】不得遗漏任何在场角色，即便某角色只是静态出现也必须点名并写出位置/姿态**
   - **【近景/特写连续性】近景、特写只改变构图焦点，不自动改变角色是否在场。如果上一镜头中另一个角色仍在同一车舱/房间/座位，且本镜头没有在 `spatial_layout.continuity.changed_positions` 声明真实空间变化，必须说明他在本镜头中是边缘可见、背景模糊、局部可见，还是因裁切处于镜头外；禁止让角色凭空消失。**
   - **【真实空间变化】角色离开原容器/原场景、换座、进入其他区域等语义必须由你在同一次 JSON 输出的 `spatial_layout.continuity.changed_positions[]` 中结构化表达；后处理只读取这个结构化字段，不会从自然语言描述里猜测。**
   - 必须与 `focus_character_ids`、`spatial_layout.slots[].visibility`、`spatial_layout.slots[].framing_role` 保持一致：主角写充分，secondary_continuity 角色弱化但保留空间关系。
   - 必须与 `spatial_layout.camera_anchor` 保持一致：首帧描述要写清相机在真实空间中的位置、拍摄方向、相对主要角色的方位角度，以及主要角色在画面左右/前后/边界上的落点。禁止只写"从车内拍摄"、"室内视角"这类无法复原机位的笼统描述。
   - 如果首帧描述使用"透过车窗可见"、"隔着玻璃看到车内"、"窗外看向车内"等外部观察措辞，`spatial_layout.camera_anchor.camera_position` 必须写成车外/窗外位置；禁止同时输出车内后排、车内中央扶手区等内部机位。
   - 遵守 `seat_source_constraint`：载具内角色座位必须继承原文或上一镜头已建立的物理座位。若角色原本是左右并排/副驾驶位/驾驶室左侧或右侧，不能因为近景、单人焦点或机位变化而改成后排座位；后排座位只有原文明确写出或 `changed_positions[]` 声明真实换座时才可出现。
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

7.1 **【角色出场完整性·硬性要求】每个shot的 characters_present 中列出的角色，必须在分镜文本中全部出场，严禁遗漏**：
   - **画面提示词（opening_frame_description、scene_detail）**：characters_present 中的**每一个角色**都必须点名（用【【角色名】】格式），并写出其位置、姿态、表情或当前动作
   - **视频提示词（description、action）**：characters_present 中的**每一个角色**都至少在其中一处有可见动作或位置交代
   - 即使某角色没有台词或处于静态（如操控载具、观察、等待），也必须写出其位置与姿态，不能因为"不显眼"而漏写
   - **【与多人对话拆分的关系】**：若下方“多人对话拆分要求”生效，则多人对话镜头会被拆成多个单人焦点镜头；`focus_character_ids` 只包含当前说话角色，但 `characters_present` 仍应包含首帧中可见或局部可见的空间连续性角色。非说话角色如果完全被近景/特写裁切到画面外，则可不放入 `characters_present`，但必须在 `spatial_layout` 保留原 slot，并标记 `visibility=offscreen`、`framing_role=offscreen_continuity`。拆分时必须保证原镜头中**每一个有对话的角色都被拆出对应镜头**，不能只拆部分角色（详见拆分要求中的防漏拆说明）
   - 错误示例：characters_present 含某角色，但画面/动作描写中完全没有提到该角色 ✗
   - 错误示例（只点名无动态）：只写"【【A】】和【【B】】在场"，没有各自的位置/姿态/动作 ✗

8. **道具名称格式要求（极其重要 - 严禁违反）**：
   - **严禁在 opening_frame_description、scene_detail、description、action 等所有画面描述文本字段中使用 prop_001、prop_002 等道具ID来替代道具的实际名称**
   - 道具在画面描述中必须使用其真实名称（如"百元大钞"、"手机"、"钥匙"等），而不是其ID（如"prop_002"）
   - **道具名称必须用〖〖道具名〗〗格式包裹**，例如"〖〖百元大钞〗〗"、"〖〖手机〗〗"、"〖〖钥匙〗〗"
   - props_present 字段使用道具ID引用，但所有画面描述文本字段中必须使用带 〖〖〗〗 标记的道具真实名称
   - 正确示例："【【服务员】】将一张〖〖百元大钞〗〗拍在桌上"、"〖〖公文包〗〗【【德保罗】】站在门口"
   - 错误示例："【【服务员】】将一张【【prop_002】】拍在桌上" ❌ 严禁这样做
   - 错误示例："【【服务员】】将一张【【百元大钞】】拍在桌上" ❌ 道具不能使用角色标记
   - 错误示例：数据库和原始剧本都没有"扩音器"，却写"〖〖扩音器〗〗掉在地上" ❌ 严禁幻想道具
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
        await _save_log_file_async(
            log_dir,
            f"script_parser_{timestamp}_01_system_prompt.txt",
            SCRIPT_PARSER_SYSTEM_PROMPT,
        )
        await _save_log_file_async(
            log_dir,
            f"script_parser_{timestamp}_02_user_prompt.txt",
            user_prompt,
        )
        if qc_retry_block:
            await _save_log_file_async(
                log_dir,
                f"script_parser_{timestamp}_03_qc_feedback.json",
                qc_feedback_log_data or {},
            )
            await _save_log_file_async(
                log_dir,
                f"script_parser_{timestamp}_03_qc_retry_prompt.txt",
                qc_retry_block,
            )

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
        response = await asyncio.to_thread(
            llm_client.call_api,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=65536,
            auth_token=auth_token,
            vendor_id=vendor_id,
            model_id=model_id,
            enable_thinking=enable_thinking,
            thinking_effort=thinking_effort,
        )
        
        # 提取响应内容
        response_content = response.choices[0].message.content if response.choices else ""
        
        logger.info(f"LLM响应长度: {len(response_content)} 字符")
        
        # 保存原始响应
        await _save_log_file_async(
            log_dir,
            f"script_parser_{timestamp}_04_raw_response.txt",
            response_content,
        )
        
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
        await _save_log_file_async(
            log_dir,
            f"script_parser_{timestamp}_05_cleaned_content.txt",
            cleaned_content,
        )
        
        # 解析JSON
        try:
            parsed_data = json.loads(cleaned_content)
            
            # 保存解析成功的JSON
            await _save_log_file_async(
                log_dir,
                f"script_parser_{timestamp}_06_parsed_success.json",
                parsed_data,
            )
            
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
            await _save_log_file_async(
                log_dir,
                f"script_parser_{timestamp}_ERROR_parse_failed.txt",
                error_info,
            )
            
            logger.error(f"JSON解析失败，完整内容长度: {len(cleaned_content)}")
            logger.error(f"错误位置: {e.lineno}行, {e.colno}列")
            logger.error(f"内容末尾500字符: ...{cleaned_content[-500:]}")
            
            # 尝试修复常见的JSON问题
            # 1. 如果JSON被截断，尝试找到最后一个完整的对象
            #    strict_json=True（分段任务）禁用补全：截断必须重试当前段，
            #    防止把不完整分镜误判为成功。
            #    strict_json=False（兼容旧调用）保留补全，但补全成功后不再提前 return，
            #    必须继续执行与正常 JSON 相同的完整校验和后处理。
            if not strict_json and not cleaned_content.endswith('}'):
                logger.warning("检测到JSON可能被截断，尝试修复...")
                # 找到最后一个完整的shot_groups数组结束位置
                last_bracket = cleaned_content.rfind(']')
                if last_bracket > 0:
                    # 尝试补全JSON
                    fixed_content = cleaned_content[:last_bracket+1] + '\n}'

                    # 保存修复尝试
                    await _save_log_file_async(
                        log_dir,
                        f"script_parser_{timestamp}_07_fixed_attempt.txt",
                        fixed_content,
                    )

                    try:
                        parsed_data = json.loads(fixed_content)

                        # 保存修复成功的JSON
                        await _save_log_file_async(
                            log_dir,
                            f"script_parser_{timestamp}_08_fixed_success.json",
                            parsed_data,
                        )

                        logger.info("JSON修复成功（兼容模式，将继续执行完整后处理）")
                        # 不再提前 return：补全结果必须走下面的必需字段验证 + 清洗 + 空间修复 + 分组重排
                    except Exception as fix_error:
                        logger.error(f"JSON修复失败: {str(fix_error)}")
                        raise Exception(f"JSON解析失败: {str(e)}\n响应长度: {len(cleaned_content)} 字符\n错误位置: 第{e.lineno}行, 第{e.colno}列\n建议: 剧本内容可能过长，请尝试缩短剧本或分段处理\n详细日志已保存到: {log_dir}/script_parser_{timestamp}_*.txt")
            else:
                raise Exception(f"JSON解析失败: {str(e)}\n响应长度: {len(cleaned_content)} 字符\n错误位置: 第{e.lineno}行, 第{e.colno}列\n建议: 剧本内容可能过长，请尝试缩短剧本或分段处理\n详细日志已保存到: {log_dir}/script_parser_{timestamp}_*.txt")
        
        # 验证必需字段
        required_keys = ["characters", "locations", "shot_groups"]
        missing_keys = [key for key in required_keys if key not in parsed_data]
        if missing_keys:
            raise Exception(f"返回的JSON缺少必需字段: {', '.join(missing_keys)}")
        
        parsed_data = sanitize_parsed_prop_references(parsed_data, db_props, script_content)
        await _save_log_file_async(
            log_dir,
            f"script_parser_{timestamp}_06_prop_sanitized.json",
            parsed_data,
        )

        # 清理 LLM 幻觉出的场景引用：核实 location_db_id 对照数据库主键 + 名称兜底，
        # 失效 location 被丢弃，shot.location_id 悬空则置 null
        parsed_data = sanitize_parsed_location_references(parsed_data, db_locations, script_content)
        await _save_log_file_async(
            log_dir,
            f"script_parser_{timestamp}_07_location_sanitized.json",
            parsed_data,
        )

        if _should_repair_spatial_layout(segment_context):
            parsed_data = repair_spatial_layout_continuity(parsed_data)
            await _save_log_file_async(
                log_dir,
                f"script_parser_{timestamp}_08_spatial_continuity_repaired.json",
                parsed_data,
            )
        else:
            await _save_log_file_async(
                log_dir,
                f"script_parser_{timestamp}_08_spatial_intent_raw.json",
                parsed_data,
            )

        # 重新组合分镜组，确保每组不超过max_group_duration秒
        parsed_data = await asyncio.to_thread(
            reorganize_shot_groups,
            parsed_data,
            max_group_duration,
            log_dir,
            timestamp,
        )
        
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
        await _save_log_file_async(
            log_dir,
            f"script_parser_{timestamp}_00_SUMMARY.txt",
            summary,
        )

        if ENABLE_SCRIPT_PARSER_LOGGING:
            logger.info(f"解析成功，详细日志已保存到: {log_dir}/script_parser_{timestamp}_*.txt")
        else:
            logger.info("解析成功")
        
        return parsed_data
        
    except Exception as e:
        raise Exception(f"剧本解析失败: {str(e)}")


def validate_parsed_script(data: Dict[str, Any]) -> tuple[bool, str]:
    """
    验证解析后的剧本数据结构是否正确（shot_groups 协议）。

    历史上该校验器检查扁平的顶层 shots 数组，与 parse_script_to_shots 实际产出的
    shot_groups[].shots[] 结构不一致，导致长期无人调用。现修正为当前协议，
    拆出可复用的段级/全局校验逻辑，供分段拆分和原调用复用。

    Args:
        data: 解析后的剧本数据

    Returns:
        (是否有效, 错误信息)
    """
    try:
        # 检查必需字段
        required_keys = ["characters", "locations", "shot_groups"]
        for key in required_keys:
            if key not in data:
                return False, f"缺少必需字段: {key}"

        # 验证characters
        if not isinstance(data["characters"], list):
            return False, "characters必须是数组"

        character_ids = set()
        for idx, char in enumerate(data["characters"]):
            if not isinstance(char, dict):
                return False, f"characters[{idx}]不是对象"
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
            if not isinstance(loc, dict):
                return False, f"locations[{idx}]不是对象"
            if "id" not in loc:
                return False, f"locations[{idx}]缺少id字段"
            if "name" not in loc:
                return False, f"locations[{idx}]缺少name字段"
            location_ids.add(loc["id"])

        # 验证shot_groups
        if not isinstance(data["shot_groups"], list):
            return False, "shot_groups必须是数组"

        for g_idx, group in enumerate(data["shot_groups"]):
            if not isinstance(group, dict):
                return False, f"shot_groups[{g_idx}]不是对象"
            shots = group.get("shots")
            if not isinstance(shots, list):
                return False, f"shot_groups[{g_idx}]缺少shots数组"

            for s_idx, shot in enumerate(shots):
                if not isinstance(shot, dict):
                    return False, f"shot_groups[{g_idx}].shots[{s_idx}]不是对象"
                if "shot_id" not in shot:
                    return False, f"shot_groups[{g_idx}].shots[{s_idx}]缺少shot_id字段"
                if "duration" not in shot:
                    return False, f"shot_groups[{g_idx}].shots[{s_idx}]缺少duration字段"

                # 验证location_id引用
                if "location_id" in shot and shot["location_id"] is not None \
                        and shot["location_id"] not in location_ids:
                    return False, f"shot_groups[{g_idx}].shots[{s_idx}]的location_id '{shot['location_id']}'不存在"

                # 验证characters_present引用
                if "characters_present" in shot:
                    for char_id in shot["characters_present"]:
                        if char_id not in character_ids:
                            return False, f"shot_groups[{g_idx}].shots[{s_idx}]的characters_present包含不存在的character_id '{char_id}'"

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
