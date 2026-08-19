"""
智能插入分镜服务：提供 LLM 驱动的分镜智能插入能力
供工作流 (video-workflow) 和故事板 (storyboard) 共用
"""
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


def get_default_llm_model(user_id: str, world_id: str) -> Optional[Dict[str, Any]]:
    """读取世界级默认对话模型（复用 script_writer 的逻辑）"""
    from api.script_writer import get_default_llm_model as _get_default_llm_model
    return _get_default_llm_model(user_id, world_id)


def load_skill_prompt(user_id: int) -> Optional[str]:
    """加载 storyboard-insert skill 提示词"""
    from script_writer_core.skill_loader import SkillLoader
    loader = SkillLoader(user_id=int(user_id))
    return loader.get_skill_prompt('storyboard-insert')


def build_context(
    prev_shot: Optional[Dict],
    next_shot: Optional[Dict],
    script_data: Dict = None,
    script_content: str = ''
) -> str:
    """构建智能插入的上下文
    
    Args:
        prev_shot: 前一个分镜数据
        next_shot: 后一个分镜数据
        script_data: 剧本解析数据（可选）
        script_content: 原始剧本内容（可选）
    
    Returns:
        格式化的上下文文本
    """
    parts = []

    # 添加原始剧本内容（如果提供）
    if script_content:
        parts.append("## 原始剧本内容")
        parts.append(script_content)

    if prev_shot:
        parts.append("## 前一个分镜")
        parts.append(_format_shot_for_prompt(prev_shot))

    if next_shot:
        parts.append("## 后一个分镜")
        parts.append(_format_shot_for_prompt(next_shot))

    if script_data:
        parts.append("## 剧本上下文")
        if script_data.get('title'):
            parts.append(f"- 剧本名称: {script_data.get('title', '')}")
        if script_data.get('genre'):
            parts.append(f"- 剧本类型: {script_data.get('genre', '')}")
        if script_data.get('synopsis'):
            parts.append(f"- 故事梗概: {script_data.get('synopsis', '')}")

    return "\n\n".join(parts)


def _format_shot_for_prompt(shot: Dict) -> str:
    """将分镜数据格式化为提示词文本"""
    lines = []
    field_map = {
        'shot_id': '镜头ID',
        'description': '描述',
        'opening_frame_description': '起始画面',
        'action': '动作',
        'camera_angle': '摄影角度',
        'shot_type': '镜头类型',
        'camera_movement': '运镜方式',
        'mood': '情绪',
        'characters_present': '出场角色',
        'dialogue': '对话',
        'duration': '时长',
        'scene_detail': '场景细节',
        'time_of_day': '时间段',
        'weather': '天气',
    }
    for key, label in field_map.items():
        value = shot.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def call_llm_for_smart_insert(
    model: str,
    messages: List[Dict],
    vendor_id: Optional[int] = None
) -> str:
    """同步调用 LLM 生成智能插入内容，返回文本内容"""
    from llm.llm_client_factory import get_llm_client
    client = get_llm_client(model, vendor_id=vendor_id)
    response = client.call_api(
        model=model,
        messages=messages,
        temperature=0.7,
        max_tokens=4096,
        agent_id="smart_insert_shot",
    )
    # call_api 返回 OpenAI 风格响应对象，需提取文本内容
    if response and getattr(response, 'choices', None):
        return response.choices[0].message.content or ''
    if isinstance(response, str):
        return response
    return ''


def extract_json_from_response(response: str) -> Dict:
    """从 LLM 响应中提取 JSON"""
    import re
    # 尝试提取 ```json ... ``` 代码块
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
    if json_match:
        response = json_match.group(1)
    
    # 尝试找到第一个 { 和最后一个 }
    start = response.find('{')
    end = response.rfind('}')
    if start != -1 and end != -1 and end > start:
        response = response[start:end + 1]
    
    return json.loads(response)


async def smart_insert_shot(
    user_id: int,
    world_id: str,
    prev_shot: Optional[Dict],
    next_shot: Optional[Dict],
    script_data: Dict = None,
    script_content: str = ''
) -> Dict[str, Any]:
    """智能插入分镜的核心逻辑
    
    Args:
        user_id: 用户 ID
        world_id: 世界 ID
        prev_shot: 前一个分镜数据
        next_shot: 后一个分镜数据
        script_data: 剧本解析数据（可选）
        script_content: 原始剧本内容（可选）
    
    Returns:
        生成的分镜数据字典
    """
    # 1. 获取用户偏好的 LLM 模型
    llm_config = await asyncio.to_thread(
        get_default_llm_model, str(user_id), str(world_id)
    )
    if not llm_config:
        logger.warning(
            f"智能插入：未找到用户 {user_id} 在世界 {world_id} 的默认 LLM 模型配置，使用默认模型"
        )
    
    from config.constant import SMART_INSERT_SHOT_DEFAULT_MODEL
    model = llm_config['model'] if llm_config else SMART_INSERT_SHOT_DEFAULT_MODEL
    vendor_id = llm_config.get('vendor_id') if llm_config else None
    logger.info(f"智能插入：使用模型 {model} (vendor_id={vendor_id})")

    # 2. 加载 skill 提示词
    skill_prompt = load_skill_prompt(user_id)
    if not skill_prompt:
        raise ValueError("storyboard-insert skill 不存在")

    # 3. 构建上下文消息
    context = build_context(prev_shot, next_shot, script_data, script_content)
    messages = [
        {"role": "user", "content": f"{skill_prompt}\n\n{context}"}
    ]

    # 4. 调用 LLM
    response = await asyncio.to_thread(
        call_llm_for_smart_insert, model, messages, vendor_id
    )

    # 5. 解析 LLM 返回的 JSON
    if not response:
        raise ValueError("LLM 返回内容为空，请检查模型配置或重试")
    try:
        shot_data = json.loads(response)
    except json.JSONDecodeError:
        shot_data = extract_json_from_response(response)

    return shot_data
