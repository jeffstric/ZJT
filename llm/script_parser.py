"""
剧本解析模块

将文字剧本解析为结构化的分镜数据
"""

import json
import os
import yaml
from typing import Dict, Any, Optional
from llm.qwen import call_qwen_chat_async
from config_util import get_config_path

# ============================================================
# 日志开关配置
# ============================================================
# 设置为 True 启用详细日志记录（保存所有LLM请求和响应到文件）
# 设置为 False 禁用文件日志记录（仅保留控制台日志）
ENABLE_SCRIPT_PARSER_LOGGING = False

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
SCRIPT_PARSER_SYSTEM_PROMPT = """你是一个专业的影视剧本分析师和分镜师，擅长将剧本拆解为人物、场景和分镜。
你需要根据输入的剧本内容，输出结构化的JSON格式数据。

输出要求：
1. 必须严格按照指定的JSON格式输出
2. 分镜组默认每个15秒，可根据剧情需要调整
3. 人物信息要完整，包括角色定位和描述
4. 场景信息要详细，包括时间、天气、氛围、环境音、背景音乐等
5. 分镜要包含镜头类型、运动方式、对话、动作等详细信息
6. opening_frame_description是最关键字段，用于AI生成首帧图像，必须非常详细描述镜头起始画面（包括人物位置、姿态、表情、场景布局、光线效果、构图信息等）
7. 确保所有ID引用关系正确（如shot中的location_id和character_id要对应）
8. 只输出纯JSON内容，不要添加```json```标记或任何解释性文字

ID格式规范：
- shot_id: s001-s999（最多10位字符）
- character_id: char_001-char_999
- location_id: loc_001-loc_999
- group_id: grp_001-grp_999
"""

# JSON格式示例模板
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
      "type": "室内/室外",
      "description": "场景详细描述（必须非常详细，包括环境布局、物品摆设、光线、色调等）",
      "time_of_day": "具体时间段（如'下午3点左右'、'傍晚日落时分'）",
      "weather": "天气（室外必填，室内填null）",
      "atmosphere": "氛围",
      "environment_sound": "环境音描述（如'街道车辆声、行人脚步声'）",
      "background_music": "背景音乐描述（如'轻快的爵士乐'）"
    }
  ],
  "shots": [
    {
      "shot_id": "shot_001",
      "shot_number": 1,
      "duration": 5.0,
      "location_id": "loc_001",
      "shot_type": "远景/中景/近景/特写",
      "camera_movement": "固定/推进/拉远/跟随/摇移/升降",
      "description": "镜头简要描述",
      "opening_frame_description": "镜头起始画面的详细描述（用于AI生成首帧图像，必须详细到能让AI准确还原画面，包括：人物位置、姿态、表情、服装；场景布局、物品摆放、光线方向和强度；构图信息如三分法、景深、视角等）",
      "scene_detail": "场景详细描述（描述整个镜头过程中的画面变化）",
      "characters_present": ["char_001"],
      "dialogue": [
        {
          "character_id": "char_001",
          "character_name": "人物名称",
          "text": "对话内容"
        }
      ],
      "action": "动作描述",
      "mood": "情绪氛围",
      "environment_sound": "环境音（场景中的自然声音，如脚步声、车辆声等）",
      "background_music": "背景音乐（配乐，如钢琴曲、爵士乐等）",
      "audio_notes": "音频备注"
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
    model: Optional[str] = None,
    temperature: float = 0.7
) -> Dict[str, Any]:
    """
    将剧本内容解析为结构化的人物、场景和分镜数据
    
    Args:
        script_content: 剧本文本内容
        max_group_duration: 每个镜头组的最大时长（秒），默认15秒
        model: 使用的LLM模型，默认使用配置文件中的模型
        temperature: 温度参数，控制创意性，默认0.7
    
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
        
        # 构建用户提示词
        user_prompt = f"""请将以下剧本内容解析为结构化的JSON数据。

剧本内容：
{script_content}

**【核心要求 - 必须严格遵守】**

1. **镜头组时长限制（最重要）**：
   - 每个shot_group内所有shots的duration总和不能超过{max_group_duration}秒
   - 如果一个场景需要超过{max_group_duration}秒，必须拆分成多个shot_group
   - 示例：如果max={max_group_duration}秒，一个场景有3个镜头分别为5秒、6秒、7秒（总计18秒），必须拆分为两组：
     * 第一组：5秒+6秒=11秒
     * 第二组：7秒

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

6. **输出格式**：
   - 必须严格按照以下JSON格式输出
   - 确保所有ID引用关系正确
   - 只输出纯JSON内容
   - 不要添加```json```标记
   - 不要添加任何解释性文字

JSON格式示例：
{JSON_FORMAT_EXAMPLE}

请开始解析："""

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
        logger.info(f"调用LLM API，temperature={temperature}")
        response_content = await call_qwen_chat_async(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=16000
        )
        
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
        model=model
    )
