"""
MCP JSON生成工具集
提供标准化的角色、世界、地点、道具JSON文件创建功能，作为MCP工具供AI模型调用
"""

import json
import os
import re
import logging
import requests
import time
import urllib.parse
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime
from script_writer_core.file_manager import FileManager
from script_writer_core.skill_loader import SkillLoader
from script_writer_core.cron_task_manager import get_task_manager
from config.config_util import get_config
from config.constant import FilePathConstants

# 设置技能调用日志
def setup_skill_logger():
    """设置技能调用专用日志记录器"""
    logger = logging.getLogger('skill_calls')
    if not logger.handlers:
        handler = logging.FileHandler('api_interaction.log', encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

def log_skill_interaction(message: str, data: Any = None):
    """记录技能调用日志到文件"""
    logger = setup_skill_logger()
    if data:
        logger.info(f"{message} - Data: {json.dumps(data, ensure_ascii=False, indent=2)}")
    else:
        logger.info(message)

# 全局技能加载器实例
_skill_loader = None
# 全局文件管理器实例
_file_manager = None

def get_skill_loader():
    """获取技能加载器实例（单例模式）"""
    global _skill_loader
    if _skill_loader is None:
        _skill_loader = SkillLoader()
    return _skill_loader

def set_file_manager(file_manager: FileManager):
    """设置全局文件管理器实例"""
    global _file_manager
    _file_manager = file_manager

def get_file_manager() -> FileManager:
    """获取文件管理器实例"""
    global _file_manager
    if _file_manager is None:
        # 如果没有设置，创建默认实例（向上两级到项目根目录）
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _file_manager = FileManager(base_dir=project_root)
    return _file_manager


def get_task_status(user_id: str, world_id: str, auth_token: str, item_type: int, item_name: str) -> Dict[str, Any]:
    """
    查询指定项目的任务状态
    
    **重要限制**: 此函数仅支持单个图片生成任务（generate_text_to_image）的状态查询。
    不适用于多宫格图片生成任务（generate_4grid_character_images、generate_4grid_location_images、generate_4grid_prop_images）。
    请勿对多宫格生成任务调用此函数。
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        item_type: 项目类型 (1=character, 2=location, 3=props)
        item_name: 项目名称
    
    Returns:
        Dict[str, Any]: 包含任务状态信息的字典
    """
    try:
        
        # 使用task_manager读取任务状态
        task_manager = get_task_manager()
        data = task_manager._read_task_status_file(user_id, world_id)
        
        # 查找指定项目的状态
        item_type_key = str(item_type)
        if item_type_key not in data:
            return {
                'success': True,
                'status': 'not_found',
                'message': '未找到该项目的任务状态',
                'item_type': item_type,
                'item_name': item_name
            }
        
        # 查找具体项目（使用item_name作为key）
        items = data[item_type_key]
        if item_name in items:
            item = items[item_name]
            return {
                'success': True,
                'status': item.get('status', 'unknown'),
                'update_time': item.get('update_time', ''),
                'message': f"项目 '{item_name}' 的任务状态: {item.get('status', 'unknown')}",
                'item_type': item_type,
                'item_name': item_name
            }
        
        # 未找到指定项目
        return {
            'success': True,
            'status': 'not_found',
            'message': f"未找到项目 '{item_name}' 的任务状态",
            'item_type': item_type,
            'item_name': item_name
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': f"查询任务状态失败: {str(e)}",
            'item_type': item_type,
            'item_name': item_name
        }


def validate_name_for_filename(name: str, field_name: str = "名称") -> Dict[str, Any]:
    """
    验证名称是否只包含中文、英文、数字、点号、下划线，确保可以用作文件名
    
    Args:
        name: 要验证的名称
        field_name: 字段名称，用于错误提示
        
    Returns:
        dict: 包含验证结果和清理后的名称
    """
    if not name or not name.strip():
        return {
            'valid': False,
            'error': f'{field_name}不能为空',
            'cleaned_name': ''
        }
    
    # 使用正则表达式检查是否只包含中文、英文字母、数字
    import re
    
    # 匹配中文字符、英文字母、数字、点号、下划线
    valid_pattern = re.compile(r'^[\u4e00-\u9fff\w._]+$')
    
    # 清理名称：只保留中文、英文、数字、点号、下划线
    cleaned_name = re.sub(r'[^\u4e00-\u9fff\w._]', '', name.strip())
    
    if not cleaned_name:
        return {
            'valid': False,
            'error': f'{field_name}必须包含至少一个中文、英文、数字、点号或下划线字符',
            'cleaned_name': ''
        }
    
    # 检查原始名称是否包含非法字符
    if not valid_pattern.match(name.strip()):
        return {
            'valid': False,
            'error': f'{field_name}只能包含中文、英文字母、数字、点号(.) 和下划线(_)，不能包含其他特殊字符、空格或符号。建议使用: "{cleaned_name}"',
            'cleaned_name': cleaned_name
        }
    
    return {
        'valid': True,
        'error': None,
        'cleaned_name': cleaned_name
    }


def validate_image_url(url: str, field_name: str = "reference_image") -> Dict[str, Any]:
    """
    验证图片URL是否为合法的HTTP/HTTPS地址
    
    Args:
        url: 要验证的URL
        field_name: 字段名称，用于错误提示
        
    Returns:
        dict: 包含验证结果
    """
    if not url or not isinstance(url, str):
        return {
            'valid': False,
            'error': f'{field_name}必须是字符串类型'
        }
    
    url = url.strip()
    
    # 检查是否以http://或https://开头
    if not (url.startswith('http://') or url.startswith('https://')):
        return {
            'valid': False,
            'error': f'{field_name}必须是合法的HTTP图片地址（以http://或https://开头）。请不要传入非URL内容，该字段只能传入图片URL地址。'
        }
    
    # 简单的URL格式验证
    url_pattern = re.compile(
        r'^https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    if not url_pattern.match(url):
        return {
            'valid': False,
            'error': f'{field_name}的URL格式不正确。请提供合法的HTTP图片地址，不要传入非URL内容。'
        }
    
    return {
        'valid': True,
        'error': None
    }


def create_character_json(user_id: str, world_id: str, auth_token: str, name: str, age: str = None, identity: str = None, 
                         appearance: str = None, personality: str = None, behavior: str = None, 
                         other_info: str = None, reference_image: str = None, 
                         _temp_filename: str = None, **additional_fields) -> Dict[str, Any]:
    """
    创建标准格式的角色JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 角色名称（必填，只能包含中文、英文、数字）
        age: 角色年龄（可选，字符串）
        identity: 身份（可选）
        appearance: 外貌（可选）
        personality: 性格（可选）
        behavior: 行为（可选）
        other_info: 其他信息（可选）
        reference_image: 参考图片（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '角色名称不能为空且必须是字符串'
            }
        
        # 验证名称
        validation_result = validate_name_for_filename(name, "角色名称")
        if not validation_result['valid']:
            return {
                'success': False,
                'error': validation_result['error']
            }
        validated_name = validation_result['cleaned_name']
        
        # 验证reference_image（如果提供）
        if reference_image is not None:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }
        
        # 创建角色数据
        character_data = {
            'name': validated_name,
            'user_id': int(user_id),
            'world_id': int(world_id),
            'created_at': datetime.now().isoformat()
        }
        
        # 添加可选字段
        if age is not None:
            character_data['age'] = age
        if identity is not None:
            character_data['identity'] = identity
        if appearance is not None:
            character_data['appearance'] = appearance
        if personality is not None:
            character_data['personality'] = personality
        if behavior is not None:
            character_data['behavior'] = behavior
        if other_info is not None:
            character_data['other_info'] = other_info
        if reference_image is not None:
            character_data['reference_image'] = reference_image
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in character_data:  # 避免覆盖核心字段
                character_data[key] = value
        
        # 生成安全的文件名（支持临时文件名用于比较）
        filename = _temp_filename if _temp_filename else f"character_{validated_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        success = file_manager.save_json_content(user_id, world_id, "characters", filename, character_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存角色JSON文件失败'
            }
        
        file_path = file_manager.get_content_file_path(user_id, world_id, "characters", filename)
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'character_data': character_data,
            'message': f'角色 "{name}" 的JSON文件已创建: {filename}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'创建角色JSON失败: {str(e)}'
        }


def create_script_json(user_id: str, world_id: str, auth_token: str, title: str, episode_number: int = None, content: str = None, **additional_fields) -> Dict[str, Any]:
    """
    创建标准格式的剧本JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        title: 剧本标题（必填，只能包含中文、英文、数字）
               ⚠️ 重要：为避免文件名重复，建议将集数信息包含在title中
               推荐格式："剧本名_第N集"  
               例如："神话擂台_第1集" 或 "神话擂台_诸仙听令"
        episode_number: 计划第几集（可选）
        content: 剧本内容（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
              如果文件已存在，将返回错误信息
    """
    try:
        # 验证必填字段
        if not title or not isinstance(title, str):
            return {
                'success': False,
                'error': '剧本标题不能为空且必须是字符串'
            }
        
        # 验证名称
        validation_result = validate_name_for_filename(title, "剧本标题")
        if not validation_result['valid']:
            return {
                'success': False,
                'error': validation_result['error']
            }
        validated_title = validation_result['cleaned_name']
        
        # 构建剧本数据结构（匹配数据库表结构）
        script_data = {
            'title': validated_title,
            'episode_number': episode_number,
            'content': content or "",
            'user_id': user_id,
            'world_id': world_id,
            'create_time': datetime.now().isoformat(),
            'update_time': datetime.now().isoformat()
        }
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in script_data and value is not None:
                script_data[key] = value
        
        # 生成安全的文件名
        filename = f"script_{validated_title}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        
        # 如果提供了 episode_number，检查是否存在冲突
        if episode_number is not None:
            scripts_dir = file_manager.get_content_dir_path(user_id, world_id, "scripts")
            import os
            import glob
            
            if os.path.exists(scripts_dir):
                # 遍历所有剧本文件，检查 episode_number 是否冲突
                script_files = glob.glob(os.path.join(scripts_dir, "script_*.json"))
                for script_file in script_files:
                    try:
                        with open(script_file, 'r', encoding='utf-8') as f:
                            existing_script = json.load(f)
                            existing_episode = existing_script.get('episode_number')
                            
                            # 检查 episode_number 是否冲突
                            if existing_episode == episode_number:
                                existing_title = existing_script.get('title', '未知')
                                return {
                                    'success': False,
                                    'error': f'集数冲突：第 {episode_number} 集已存在（标题："{existing_title}"）。同一世界下不允许创建相同集数的剧本。',
                                    'existing_file': script_file,
                                    'existing_title': existing_title,
                                    'conflicting_episode_number': episode_number
                                }
                    except Exception as e:
                        # 如果读取某个文件失败，记录日志但继续检查其他文件
                        logging.warning(f"读取剧本文件 {script_file} 失败: {str(e)}")
                        continue
        
        # 检查文件是否已存在
        file_path = file_manager.get_content_file_path(user_id, world_id, "scripts", filename)
        import os
        if os.path.exists(file_path):
            return {
                'success': False,
                'error': f'文件名冲突：剧本文件 "{filename}" 已存在。请在title中添加集数以区分不同剧本。例如："{validated_title}_第{episode_number}集"',
                'existing_file': file_path,
                'suggestion': f'建议使用："{validated_title}_第{episode_number}集"' if episode_number else f'建议在title中添加集数或场景信息'
            }
        
        success = file_manager.save_json_content(user_id, world_id, "scripts", filename, script_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存剧本JSON文件失败'
            }

        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'script_data': script_data,
            'message': f'剧本 "{title}" 的JSON文件已创建: {filename}'
        }
            
    except Exception as e:
        return {
            'success': False,
            'error': f'创建剧本JSON失败: {str(e)}'
        }


def create_world_json(user_id: str, world_id: str, auth_token: str, name: str, description: str = None, **additional_fields) -> Dict[str, Any]:
    """
    创建标准格式的世界JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 世界名称（必填，只能包含中文、英文、数字）
        description: 世界描述（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '世界名称不能为空且必须是字符串'
            }
        
        # 验证名称
        validation_result = validate_name_for_filename(name, "世界名称")
        if not validation_result['valid']:
            return {
                'success': False,
                'error': validation_result['error']
            }
        validated_name = validation_result['cleaned_name']
        
        # 创建世界数据
        world_data = {
            'name': validated_name,
            'user_id': user_id,
            'created_at': datetime.now().isoformat()
        }
        
        # 添加可选字段
        if description is not None:
            world_data['description'] = description
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in world_data:
                world_data[key] = value
        
        # 生成安全的文件名
        filename = f"world_{validated_name}.json"
        
        # 使用FileManager统一路径管理 (世界文件保存在用户根目录下的worlds文件夹)
        file_manager = get_file_manager()
        # 对于世界文件，使用world_id="0"因为世界本身不属于特定世界
        success = file_manager.save_json_content(user_id, "0", "worlds", filename, world_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存世界JSON文件失败'
            }
        
        file_path = file_manager.get_content_file_path(user_id, "0", "worlds", filename)
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'world_data': world_data,
            'message': f'世界 "{name}" 的JSON文件已创建: {filename}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'创建世界JSON失败: {str(e)}'
        }


def _truncate_content(content: str, limit: Optional[int] = None) -> str:
    """
    根据limit参数截断内容
    
    Args:
        content: 要截断的内容
        limit: 字符数限制，None表示不限制
    
    Returns:
        str: 截断后的内容
    """
    if limit is None or limit <= 0:
        return content
    
    if len(content) <= limit:
        return content
    
    return content[:limit] + "...(已截断)"


def read_world(user_id: str, world_id: str, auth_token: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    读取当前世界的完整信息 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        limit: 字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 操作结果，包含success状态和世界所有字段（story_outline, visual_style, era_environment, color_language, composition_preference）
    """
    try:
        # 验证上下文
        if not user_id or not world_id:
            return {
                'success': False,
                'error': '无法获取用户或世界信息，请确保会话已正确初始化'
            }
        
        # 使用FileManager读取世界信息
        file_manager = get_file_manager()
        world_data = file_manager.get_world_json(user_id, world_id)
        
        if not world_data:
            return {
                'success': False,
                'error': '未找到世界信息文件'
            }
        
        return {
            'success': True,
            'world_id': world_id,
            'world_name': world_data.get('name', ''),
            'story_outline': _truncate_content(world_data.get('story_outline', ''), limit),
            'visual_style': _truncate_content(world_data.get('visual_style', ''), limit),
            'era_environment': _truncate_content(world_data.get('era_environment', ''), limit),
            'color_language': _truncate_content(world_data.get('color_language', ''), limit),
            'composition_preference': _truncate_content(world_data.get('composition_preference', ''), limit),
            'message': f'成功读取世界 "{world_data.get("name", "")}" 的完整信息'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'读取世界信息失败: {str(e)}'
        }


def update_world(
    user_id: str, world_id: str, auth_token: str,
    story_outline: str = None,
    visual_style: str = None,
    era_environment: str = None,
    color_language: str = None,
    composition_preference: str = None
) -> Dict[str, Any]:
    """
    更新当前世界的信息 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        story_outline: 故事大纲内容（可选）
        visual_style: 画面风格（可选）
        era_environment: 时代环境（可选）
        color_language: 色彩语言（可选）
        composition_preference: 构图倾向（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证至少有一个字段需要更新
        if all(v is None for v in [story_outline, visual_style, era_environment, color_language, composition_preference]):
            return {
                'success': False,
                'error': '至少需要提供一个字段进行更新'
            }
        
        # 使用FileManager读取现有世界信息
        file_manager = get_file_manager()
        world_data = file_manager.get_world_json(user_id, world_id)
        
        if not world_data:
            # 如果世界信息文件不存在，创建一个新的
            world_data = {
                'id': int(world_id),
                'name': f'World_{world_id}',
                'user_id': int(user_id)
            }
        
        # 更新提供的字段
        if story_outline is not None:
            world_data['story_outline'] = story_outline
        if visual_style is not None:
            world_data['visual_style'] = visual_style
        if era_environment is not None:
            world_data['era_environment'] = era_environment
        if color_language is not None:
            world_data['color_language'] = color_language
        if composition_preference is not None:
            world_data['composition_preference'] = composition_preference
        
        # 保存更新后的世界信息
        success = file_manager.save_world(world_data, user_id, world_id)
        
        if not success:
            return {
                'success': False,
                'error': '保存世界信息失败'
            }
        
        updated_fields = []
        if story_outline is not None:
            updated_fields.append('story_outline')
        if visual_style is not None:
            updated_fields.append('visual_style')
        if era_environment is not None:
            updated_fields.append('era_environment')
        if color_language is not None:
            updated_fields.append('color_language')
        if composition_preference is not None:
            updated_fields.append('composition_preference')
        
        return {
            'success': True,
            'world_id': world_id,
            'world_name': world_data.get('name', ''),
            'updated_fields': updated_fields,
            'message': f'成功更新世界 "{world_data.get("name", "")}" 的信息: {", ".join(updated_fields)}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'更新世界信息失败: {str(e)}'
        }


def create_location_json(user_id: str, world_id: str, auth_token: str, name: str, description: str = None, 
                        reference_image: str = None, _temp_filename: str = None, **additional_fields) -> Dict[str, Any]:
    """
    创建标准格式的地点JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 地点名称（必填，只能包含中文、英文、数字）
        description: 地点描述（可选）
        reference_image: 参考图片（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '地点名称不能为空且必须是字符串'
            }
        
        # 验证名称
        validation_result = validate_name_for_filename(name, "地点名称")
        if not validation_result['valid']:
            return {
                'success': False,
                'error': validation_result['error']
            }
        validated_name = validation_result['cleaned_name']
        
        # 验证reference_image（如果提供）
        if reference_image is not None:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }
        
        # 创建地点数据
        location_data = {
            'name': validated_name,
            'world_id': int(world_id),
            'user_id': int(user_id),
            'created_at': datetime.now().isoformat()
        }
        
        # 添加可选字段 - parent_id保持为null
        location_data['parent_id'] = None
        if reference_image is not None:
            location_data['reference_image'] = reference_image
        if description is not None:
            location_data['description'] = description
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in location_data:
                location_data[key] = value
        
        # 生成安全的文件名（支持临时文件名用于比较）
        filename = _temp_filename if _temp_filename else f"location_{validated_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        success = file_manager.save_json_content(user_id, world_id, "locations", filename, location_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存地点JSON文件失败'
            }
        
        file_path = file_manager.get_content_file_path(user_id, world_id, "locations", filename)
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'location_data': location_data,
            'message': f'地点 "{name}" 的JSON文件已创建: {filename}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'创建地点JSON失败: {str(e)}'
        }


def create_prop_json(user_id: str, world_id: str, auth_token: str, name: str, prop_type: str = None, description: str = None, reference_image: str = None, _temp_filename: str = None, **additional_fields) -> Dict[str, Any]:
    """
    创建标准格式的道具JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 道具名称（必填，只能包含中文、英文、数字）
        prop_type: 道具类型（可选）
        description: 道具描述（可选）
        reference_image: 参考图片（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '道具名称不能为空且必须是字符串'
            }
        
        # 验证名称
        validation_result = validate_name_for_filename(name, "道具名称")
        if not validation_result['valid']:
            return {
                'success': False,
                'error': validation_result['error']
            }
        validated_name = validation_result['cleaned_name']
        
        # 验证reference_image（如果提供）
        if reference_image is not None:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }
        
        # 创建道具数据
        prop_data = {
            'name': validated_name,
            'world_id': int(world_id),
            'user_id': int(user_id),
            'created_at': datetime.now().isoformat()
        }
        
        # 添加可选字段
        if prop_type is not None:
            prop_data['type'] = prop_type
        if description is not None:
            prop_data['description'] = description
        if reference_image is not None:
            prop_data['reference_image'] = reference_image
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in prop_data:
                prop_data[key] = value
        
        # 生成安全的文件名（支持临时文件名用于比较）
        if _temp_filename:
            filename = _temp_filename
        else:
            safe_name = _sanitize_filename(name)
            filename = f"prop_{safe_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        success = file_manager.save_json_content(user_id, world_id, "props", filename, prop_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存道具JSON文件失败'
            }
        
        file_path = file_manager.get_content_file_path(user_id, world_id, "props", filename)
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'prop_data': prop_data,
            'message': f'道具 "{name}" 的JSON文件已创建: {filename}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'创建道具JSON失败: {str(e)}'
        }


def read_character_json(user_id: str, world_id: str, auth_token: str, name: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    读取角色JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 角色名称
        limit: 输出字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 操作结果，包含success状态和角色数据
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '角色名称不能为空且必须是字符串'
            }
        
        # 使用FileManager读取文件
        file_manager = get_file_manager()
        character_data = file_manager.get_character_json(name, user_id, world_id)

        if character_data is None:
            return {
                'success': False,
                'error': f'角色 "{name}" 不存在或读取失败'
            }
        
        # 对文本字段应用limit
        if limit is not None and limit > 0:
            for key in ['appearance', 'personality', 'behavior', 'other_info', 'identity']:
                if key in character_data and isinstance(character_data[key], str):
                    character_data[key] = _truncate_content(character_data[key], limit)
        
        return {
            'success': True,
            'data': character_data,
            'message': f'成功读取角色 "{name}"'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'读取角色JSON失败: {str(e)}'
        }


def read_script_json(user_id: str, world_id: str, auth_token: str, title: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    读取剧本JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        title: 剧本标题
        limit: 输出字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 操作结果，包含success状态和剧本数据
    """
    try:
        # 验证必填字段
        if not title or not isinstance(title, str):
            return {
                'success': False,
                'error': '剧本标题不能为空且必须是字符串'
            }
        
        safe_title = _sanitize_filename(title)
        
        # 使用FileManager读取文件
        file_manager = get_file_manager()
        script_data = file_manager.get_script(safe_title, user_id, world_id)
        
        if script_data is None:
            return {
                'success': False,
                'error': f'剧本 "{title}" 不存在或读取失败'
            }
        
        # 对content字段应用limit
        if limit is not None and limit > 0:
            if 'content' in script_data and isinstance(script_data['content'], str):
                script_data['content'] = _truncate_content(script_data['content'], limit)
        
        return {
            'success': True,
            'data': script_data,
            'message': f'成功读取剧本 "{title}"'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'读取剧本JSON失败: {str(e)}'
        }



def read_location_json(user_id: str, world_id: str, auth_token: str, name: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    读取地点JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 地点名称
        limit: 输出字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 包含success状态和数据的结果
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '地点名称不能为空且必须是字符串'
            }
        
        safe_name = _sanitize_filename(name)
        filename = f"location_{safe_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        file_path = file_manager.get_content_file_path(user_id, world_id, "locations", filename)
        
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                location_data = json.load(f)
            
            # 对description字段应用limit
            if limit is not None and limit > 0:
                if 'description' in location_data and isinstance(location_data['description'], str):
                    location_data['description'] = _truncate_content(location_data['description'], limit)
            
            return {
                'success': True,
                'data': location_data,
                'message': f'成功读取地点 "{name}" 的信息'
            }
        else:
            return {
                'success': False,
                'error': f'地点 "{name}" 不存在'
            }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'读取地点JSON失败: {str(e)}'
        }


def read_prop_json(user_id: str, world_id: str, auth_token: str, name: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    读取道具JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 道具名称
        limit: 输出字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 包含success状态和数据的结果
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '道具名称不能为空且必须是字符串'
            }
        
        safe_name = _sanitize_filename(name)
        filename = f"prop_{safe_name}.json"
        
        base_dir = "files"
        user_dir = os.path.join(base_dir, str(user_id))
        world_dir = os.path.join(user_dir, str(world_id))
        props_dir = os.path.join(world_dir, "props")
        file_path = os.path.join(props_dir, filename)
        
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                prop_data = json.load(f)
            
            # 对description字段应用limit
            if limit is not None and limit > 0:
                if 'description' in prop_data and isinstance(prop_data['description'], str):
                    prop_data['description'] = _truncate_content(prop_data['description'], limit)
            
            return {
                'success': True,
                'data': prop_data,
                'message': f'成功读取道具 "{name}" 的信息'
            }
        else:
            return {
                'success': False,
                'error': f'道具 "{name}" 不存在'
            }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'读取道具JSON失败: {str(e)}'
        }



def list_location_jsons(user_id: str, world_id: str, auth_token: str) -> Dict[str, Any]:
    """
    列出所有地点JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
    
    Returns:
        dict: 包含success状态和地点文件列表的结果
    """
    try:
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        locations_dir = file_manager.get_content_dir_path(user_id, world_id, "locations")
        
        if not os.path.exists(locations_dir):
            return {
                'success': True,
                'data': [],
                'message': '地点目录不存在，返回空列表'
            }
        
        files = []
        for filename in os.listdir(locations_dir):
            if filename.startswith("location_") and filename.endswith(".json"):
                files.append(filename)
        
        return {
            'success': True,
            'data': sorted(files),
            'message': f'成功获取 {len(files)} 个地点文件'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'列出地点文件失败: {str(e)}',
            'data': []
        }


def list_prop_jsons(user_id: str, world_id: str, auth_token: str) -> Dict[str, Any]:
    """
    列出所有道具JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
    
    Returns:
        dict: 包含success状态和道具文件列表的结果
    """
    try:
        base_dir = "files"
        user_dir = os.path.join(base_dir, str(user_id))
        world_dir = os.path.join(user_dir, str(world_id))
        props_dir = os.path.join(world_dir, "props")
        
        if not os.path.exists(props_dir):
            return {
                'success': True,
                'data': [],
                'message': '道具目录不存在，返回空列表'
            }
        
        files = []
        for filename in os.listdir(props_dir):
            if filename.startswith("prop_") and filename.endswith(".json"):
                files.append(filename)
        
        return {
            'success': True,
            'data': sorted(files),
            'message': f'成功获取 {len(files)} 个道具文件'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'列出道具文件失败: {str(e)}',
            'data': []
        }


def list_character_jsons(user_id: str, world_id: str, auth_token: str) -> Dict[str, Any]:
    """
    列出所有角色JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
    
    Returns:
        dict: 包含success状态和角色文件列表的结果
    """
    try:
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        characters_dir = file_manager.get_content_dir_path(user_id, world_id, "characters")
        
        if not os.path.exists(characters_dir):
            return {
                'success': True,
                'data': [],
                'message': '角色目录不存在，返回空列表'
            }
        
        files = []
        for filename in os.listdir(characters_dir):
            if filename.startswith("character_") and filename.endswith(".json"):
                files.append(filename)
        
        return {
            'success': True,
            'data': sorted(files),
            'message': f'成功获取 {len(files)} 个角色文件'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'列出角色文件失败: {str(e)}',
            'data': []
        }


def update_character_json(user_id: str, world_id: str, auth_token: str, name: str, age: str = None, identity: str = None, 
                         appearance: str = None, personality: str = None, behavior: str = None, 
                         other_info: str = None, reference_image: str = None, **additional_fields) -> Dict[str, Any]:
    """
    更新角色JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 角色名称（必填，用于定位文件）
        age: 角色年龄（可选）
        identity: 身份（可选）
        appearance: 外貌（可选）
        personality: 性格（可选）
        behavior: 行为（可选）
        other_info: 其他信息（可选）
        reference_image: 参考图片（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '角色名称不能为空且必须是字符串'
            }
        
        # 生成安全的文件名
        safe_name = _sanitize_filename(name)
        filename = f"character_{safe_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        file_path = file_manager.get_content_file_path(user_id, world_id, "characters", filename)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return {
                'success': False,
                'error': f'角色 "{name}" 不存在，无法更新'
            }
        
        # 读取现有数据
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        
        # 验证reference_image（如果提供）
        if reference_image is not None:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }
        
        # 更新字段（只更新提供的非None字段）
        if age is not None:
            existing_data['age'] = age
        if identity is not None:
            existing_data['identity'] = identity
        if appearance is not None:
            existing_data['appearance'] = appearance
        if personality is not None:
            existing_data['personality'] = personality
        if behavior is not None:
            existing_data['behavior'] = behavior
        if other_info is not None:
            existing_data['other_info'] = other_info
        if reference_image is not None:
            existing_data['reference_image'] = reference_image
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in ['name', 'user_id', 'world_id', 'created_at']:  # 保护核心字段
                existing_data[key] = value
        
        # 更新修改时间
        existing_data['updated_at'] = datetime.now().isoformat()
        
        # 保存更新后的数据
        success = file_manager.save_json_content(user_id, world_id, "characters", filename, existing_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存角色JSON文件失败'
            }
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'character_data': existing_data,
            'message': f'角色 "{name}" 已成功更新'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'更新角色JSON失败: {str(e)}'
        }


def update_location_json(user_id: str, world_id: str, auth_token: str, name: str, parent_id: str = None, 
                        reference_image: str = None, description: str = None, **additional_fields) -> Dict[str, Any]:
    """
    更新地点JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 地点名称（必填，用于定位文件）
        parent_id: 父级地点ID（可选）
        reference_image: 参考图片（可选）
        description: 地点描述（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '地点名称不能为空且必须是字符串'
            }
        
        # 生成安全的文件名
        safe_name = _sanitize_filename(name)
        filename = f"location_{safe_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        file_path = file_manager.get_content_file_path(user_id, world_id, "locations", filename)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return {
                'success': False,
                'error': f'地点 "{name}" 不存在，无法更新'
            }
        
        # 读取现有数据
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        
        # 验证reference_image（如果提供）
        if reference_image is not None:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }
        
        # 更新字段（只更新提供的非None字段）
        if parent_id is not None:
            existing_data['parent_id'] = parent_id
        if reference_image is not None:
            existing_data['reference_image'] = reference_image
        if description is not None:
            existing_data['description'] = description
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in ['name', 'user_id', 'world_id', 'created_at']:  # 保护核心字段
                existing_data[key] = value
        
        # 更新修改时间
        existing_data['updated_at'] = datetime.now().isoformat()
        
        # 保存更新后的数据
        success = file_manager.save_json_content(user_id, world_id, "locations", filename, existing_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存地点JSON文件失败'
            }
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'location_data': existing_data,
            'message': f'地点 "{name}" 已成功更新'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'更新地点JSON失败: {str(e)}'
        }


def update_prop_json(user_id: str, world_id: str, auth_token: str, name: str, prop_type: str = None, 
                    description: str = None, reference_image: str = None, **additional_fields) -> Dict[str, Any]:
    """
    更新道具JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 道具名称（必填，用于定位文件）
        prop_type: 道具类型（可选）
        description: 道具描述（可选）
        reference_image: 参考图片（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '道具名称不能为空且必须是字符串'
            }
        
        # 生成安全的文件名
        safe_name = _sanitize_filename(name)
        filename = f"prop_{safe_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        file_path = file_manager.get_content_file_path(user_id, world_id, "props", filename)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return {
                'success': False,
                'error': f'道具 "{name}" 不存在，无法更新'
            }
        
        # 读取现有数据
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        
        # 验证reference_image（如果提供）
        if reference_image is not None:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }
        
        # 更新字段（只更新提供的非None字段）
        if prop_type is not None:
            existing_data['type'] = prop_type
        if description is not None:
            existing_data['description'] = description
        if reference_image is not None:
            existing_data['reference_image'] = reference_image
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in ['name', 'user_id', 'world_id', 'created_at']:  # 保护核心字段
                existing_data[key] = value
        
        # 更新修改时间
        existing_data['updated_at'] = datetime.now().isoformat()
        
        # 保存更新后的数据
        success = file_manager.save_json_content(user_id, world_id, "props", filename, existing_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存道具JSON文件失败'
            }
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'prop_data': existing_data,
            'message': f'道具 "{name}" 已成功更新'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'更新道具JSON失败: {str(e)}'
        }


def update_script_json(user_id: str, world_id: str, auth_token: str, title: str, episode_number: int = None, content: str = None, **additional_fields) -> Dict[str, Any]:
    """
    更新剧本JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        title: 剧本标题（必填，用于定位文件）
        episode_number: 计划第几集（可选）
        content: 剧本内容（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not title or not isinstance(title, str):
            return {
                'success': False,
                'error': '剧本标题不能为空且必须是字符串'
            }
        
        # 生成安全的文件名
        safe_title = _sanitize_filename(title)
        filename = f"script_{safe_title}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        file_path = file_manager.get_content_file_path(user_id, world_id, "scripts", filename)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return {
                'success': False,
                'error': f'剧本 "{title}" 不存在，无法更新'
            }
        
        # 读取现有数据
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        
        # 更新字段（只更新提供的非None字段）
        if episode_number is not None:
            existing_data['episode_number'] = episode_number
        if content is not None:
            existing_data['content'] = content
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in ['title', 'user_id', 'world_id', 'create_time']:  # 保护核心字段
                existing_data[key] = value
        
        # 更新修改时间
        existing_data['update_time'] = datetime.now().isoformat()
        
        # 保存更新后的数据
        success = file_manager.save_json_content(user_id, world_id, "scripts", filename, existing_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存剧本JSON文件失败'
            }
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'script_data': existing_data,
            'message': f'剧本 "{title}" 已成功更新'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'更新剧本JSON失败: {str(e)}'
        }


def _sanitize_filename(name: str) -> str:
    """
    清理文件名，移除不安全字符
    
    Args:
        name: 原始名称
    
    Returns:
        str: 安全的文件名
    """
    # 移除或替换不安全字符
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', name)
    safe_name = re.sub(r'\s+', '_', safe_name)  # 空格替换为下划线
    safe_name = safe_name.strip('._')  # 移除开头结尾的点和下划线
    
    # 限制长度
    if len(safe_name) > 50:
        safe_name = safe_name[:50]
    
    # 确保不为空
    if not safe_name:
        safe_name = "unnamed"
    
    return safe_name


def get_script_problem(user_id: str, world_id: str, auth_token: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    获取剧本问题文件内容 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        limit: 字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 操作结果，包含success状态和文件内容
    """
    try:
        
        # 验证上下文
        if not user_id or not world_id:
            return {
                'success': False,
                'error': '无法获取用户和世界信息，请确保会话已正确初始化',
                'verdict': True,
                'problem': ''
            }
        
        # 使用FileManager读取剧本问题
        file_manager = get_file_manager()
        problem_data = file_manager.get_script_problem(user_id, world_id)
        
        verdict = problem_data.get('verdict', True)
        problem = problem_data.get('problem', '')
        
        # 对problem字段应用limit
        if limit is not None and limit > 0:
            problem = _truncate_content(problem, limit)
        
        return {
            'success': True,
            'verdict': verdict,
            'problem': problem,
            'message': f'成功获取剧本问题 (verdict: {verdict})'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'获取剧本问题失败: {str(e)}',
            'verdict': True,
            'problem': ''
        }


def set_script_problem(user_id: str, world_id: str, auth_token: str, verdict: bool, problem: str) -> Dict[str, Any]:
    """
    设置剧本问题文件内容 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        verdict: 判定结果，True表示有问题，False表示无问题
        problem: 问题描述（当verdict为True时必填）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证问题内容
        if problem is None:
            problem = ''  # 允许空字符串，用于清空问题
        
        # 使用FileManager保存剧本问题
        file_manager = get_file_manager()
        success = file_manager.set_script_problem(verdict, problem, user_id, world_id)
        
        if not success:
            return {
                'success': False,
                'error': '保存剧本问题失败'
            }
        
        return {
            'success': True,
            'message': f'剧本问题已成功保存 (verdict: {verdict}, {len(problem)} 字符)'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'设置剧本问题失败: {str(e)}'
        }


# MCP工具定义（供MCP服务器使用）
MCP_TOOLS = [
    {
        "name": "create_character_json",
        "description": "创建或者更新标准格式的角色JSON文件，确保数据格式一致性",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "角色名称（允许中文、英文、数字、点号、下划线）"
                },
                "age": {
                    "type": "string",
                    "description": "角色年龄（可选）"
                },
                "identity": {
                    "type": "string",
                    "description": "身份（可选）"
                },
                "appearance": {
                    "type": "string",
                    "description": "外貌（可选）"
                },
                "personality": {
                    "type": "string",
                    "description": "性格（可选）"
                },
                "behavior": {
                    "type": "string",
                    "description": "行为（可选）"
                },
                "other_info": {
                    "type": "string",
                    "description": "其他信息（可选）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "create_script_json",
        "description": "创建或者更新标准格式的剧本JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "剧本标题（允许中文、英文、数字、点号、下划线）"
                },
                "episode_number": {
                    "type": "integer",
                    "description": "计划第几集（可选）"
                },
                "content": {
                    "type": "string",
                    "description": "剧本内容（可选）"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "create_location_json",
        "description": "创建或者更新标准格式的地点JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "地点名称（允许中文、英文、数字、点号、下划线）"
                },
                "parent_id": {
                    "type": "string",
                    "description": "父级地点ID（可选）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                },
                "description": {
                    "type": "string",
                    "description": "地点描述（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "create_prop_json",
        "description": "创建或者更新标准格式的道具JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "道具名称（允许中文、英文、数字、点号、下划线）"
                },
                "prop_type": {
                    "type": "string",
                    "description": "道具类型（可选）"
                },
                "description": {
                    "type": "string",
                    "description": "道具描述（可选）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "read_character_json",
        "description": "读取指定角色的JSON数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "角色名称（允许中文、英文、数字、点号、下划线）"
                },
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "read_script_json",
        "description": "读取指定剧本的JSON数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "剧本标题（允许中文、英文、数字、点号、下划线）"
                },
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "read_location_json",
        "description": "读取指定地点的JSON数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "地点名称（允许中文、英文、数字、点号、下划线）"
                },
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "read_prop_json",
        "description": "读取指定道具的JSON数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "道具名称（允许中文、英文、数字、点号、下划线）"
                },
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "list_location_jsons",
        "description": "列出当前世界的所有地点JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "list_prop_jsons",
        "description": "列出当前世界的所有道具JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "list_character_jsons",
        "description": "列出当前世界的所有角色JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "update_character_json",
        "description": "更新角色JSON文件的指定字段",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "角色名称（用于定位文件）"
                },
                "age": {
                    "type": "string",
                    "description": "角色年龄（可选）"
                },
                "identity": {
                    "type": "string",
                    "description": "身份（可选）"
                },
                "appearance": {
                    "type": "string",
                    "description": "外貌（可选）"
                },
                "personality": {
                    "type": "string",
                    "description": "性格（可选）"
                },
                "behavior": {
                    "type": "string",
                    "description": "行为（可选）"
                },
                "other_info": {
                    "type": "string",
                    "description": "其他信息（可选）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_location_json",
        "description": "更新地点JSON文件的指定字段",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "地点名称（用于定位文件）"
                },
                "parent_id": {
                    "type": "string",
                    "description": "父级地点ID（可选）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                },
                "description": {
                    "type": "string",
                    "description": "地点描述（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_prop_json",
        "description": "更新道具JSON文件的指定字段",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "道具名称（用于定位文件）"
                },
                "prop_type": {
                    "type": "string",
                    "description": "道具类型（可选）"
                },
                "description": {
                    "type": "string",
                    "description": "道具描述（可选）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_script_json",
        "description": "更新剧本JSON文件的指定字段",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "剧本标题（用于定位文件）"
                },
                "episode_number": {
                    "type": "integer",
                    "description": "计划第几集（可选）"
                },
                "content": {
                    "type": "string",
                    "description": "剧本内容（可选）"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "read_world",
        "description": "读取当前世界的完整信息，包括故事大纲、画面风格、时代环境、色彩语言、构图倾向等",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": []
        }
    },
    {
        "name": "update_world",
        "description": "更新当前世界的信息，可以更新故事大纲、画面风格、时代环境、色彩语言、构图倾向等字段",
        "inputSchema": {
            "type": "object",
            "properties": {
                "story_outline": {
                    "type": "string",
                    "description": "故事大纲内容（可选）"
                },
                "visual_style": {
                    "type": "string",
                    "description": "画面风格（可选）"
                },
                "era_environment": {
                    "type": "string",
                    "description": "时代环境（可选）"
                },
                "color_language": {
                    "type": "string",
                    "description": "色彩语言（可选）"
                },
                "composition_preference": {
                    "type": "string",
                    "description": "构图倾向（可选）"
                }
            },
            "required": []
        }
    },
    {
        "name": "list_script_jsons",
        "description": "列出当前世界的所有剧本JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "create_world_json",
        "description": "创建标准格式的世界JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "世界名称（允许中文、英文、数字、点号、下划线）"
                },
                "description": {
                    "type": "string",
                    "description": "世界描述（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "skill",
        "description": "🚨 MANDATORY: 获取专业技能的完整指导内容。在执行剧本创作、角色设计、场景构建等任务前必须先调用此工具。系统采用渐进式披露架构，所有专业知识存储在外部技能系统中，不调用此工具将无法获得正确的工作指导。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "SkillName": {
                    "type": "string",
                    "description": "要调用的技能名称。必须是可用技能列表中的一个。"
                }
            },
            "required": ["SkillName"]
        }
    },
    {
        "name": "get_script_problem",
        "description": "获取剧本问题文件内容（由content-compliance-checker审核后记录的问题）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": []
        }
    },
    {
        "name": "set_script_problem",
        "description": "设置剧本问题文件内容（用于记录审核报告和发现的问题）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "boolean",
                    "description": "审核结果，true表示通过，false表示不通过"
                },
                "problem": {
                    "type": "string",
                    "description": "剧本问题文本，通常是审核报告的完整内容"
                }
            },
            "required": ["verdict", "problem"]
        }
    },
    {
        "name": "get_long_user_input",
        "description": "读取用户长文本输入的完整内容。当用户输入超过5000字时，系统会自动保存完整内容到文件，并在消息中提示文件名。使用此工具可以读取完整内容。如果文件不存在，会返回可用文件列表供纠错。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "文件名，格式为：HH:MM:SS.txt，例如：14:57:23.txt"
                },
                "limit": {
                    "type": "integer",
                    "description": "可选，限制返回字符数，避免token消耗过大。不填则返回完整内容。"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "generate_text_to_image",
        "description": "文本生成图片功能（非阻塞版本，支持后台任务）。根据提示词发起图片生成请求，立即返回project_ids。如果指定item_type和item_name，会创建后台任务自动处理图片下载和更新。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "图片描述提示词（必填），例如：'一个女孩，漫画风格'"
                },
                "model": {
                    "type": "string",
                    "description": "使用的模型（可选，默认：gemini-3-pro-image-preview）"
                },
                "aspect_ratio": {
                    "type": "string",
                    "description": "图片宽高比（可选，默认：16:9），支持格式如：16:9, 4:3, 1:1等"
                },
                "count": {
                    "type": "integer",
                    "description": "生成图片数量（可选，默认：1）"
                },
                "item_type": {
                    "type": "integer",
                    "description": "物品类型（可选）：1=角色(character), 2=地点(location), 3=道具(props)。指定后会创建后台任务自动处理"
                },
                "item_name": {
                    "type": "string",
                    "description": "物品名称（可选），当指定item_type时必填，会自动更新对应物品的reference_image字段"
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "generate_4grid_character_images",
        "description": "生成4宫格角色图像并自动切分更新到各个角色（一站式解决方案）。自动构建4宫格JSON格式，添加image_size=4k参数生成高分辨率图像，轮询等待生成完成，自动下载并切分4宫格图像为4个独立图像，自动更新每个角色的reference_image字段。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "character_names": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个角色的名称列表（必须是4个），例如：['角色1', '角色2', '角色3', '角色4']"
                },
                "prompts": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个角色的完整提示词列表（必须是4个），每个提示词对应一个角色的详细描述"
                },
                "model": {
                    "type": "string",
                    "description": "使用的模型（可选，默认：NanoBananaPro）"
                }
            },
            "required": ["character_names", "prompts"]
        }
    },
    {
        "name": "generate_4grid_location_images",
        "description": "生成4宫格场景图像并自动切分更新到各个场景（一站式解决方案）。自动构建4宫格JSON格式，添加image_size=4k参数生成高分辨率图像，轮询等待生成完成，自动下载并切分4宫格图像为4个独立图像，自动更新每个场景的reference_image字段。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "location_names": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个场景的名称列表（必须是4个），例如：['场景1', '场景2', '场景3', '场景4']。如果实际场景少于4个，用'placeholder'补齐"
                },
                "prompts": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个场景的完整提示词列表（必须是4个），每个提示词对应一个场景的详细描述。如果实际场景少于4个，用'pure black background'补齐"
                },
                "model": {
                    "type": "string",
                    "description": "使用的模型（可选，默认：NanoBananaPro）"
                }
            },
            "required": ["location_names", "prompts"]
        }
    },
    {
        "name": "generate_4grid_prop_images",
        "description": "生成4宫格道具图像并自动切分更新到各个道具（一站式解决方案）。自动构建4宫格JSON格式，添加image_size=4k参数生成高分辨率图像，轮询等待生成完成，自动下载并切分4宫格图像为4个独立图像，自动更新每个道具的reference_image字段。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prop_names": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个道具的名称列表（必须是4个），例如：['道具1', '道具2', '道具3', '道具4']。如果实际道具少于4个，用'placeholder'补齐"
                },
                "prompts": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个道具的完整提示词列表（必须是4个），每个提示词对应一个道具的详细描述。如果实际道具少于4个，用'pure black background'补齐"
                },
                "model": {
                    "type": "string",
                    "description": "使用的模型（可选，默认：NanoBananaPro）"
                }
            },
            "required": ["prop_names", "prompts"]
        }
    },
    {
        "name": "get_task_status",
        "description": "查询指定项目的图片生成任务状态，从文件系统中读取状态信息。**重要**: 仅支持单个图片生成任务（generate_text_to_image），不支持多宫格生成任务（generate_4grid_character_images、generate_4grid_location_images、generate_4grid_prop_images），请勿对多宫格任务调用此工具",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_type": {
                    "type": "integer",
                    "description": "项目类型: 1=角色, 2=场景, 3=道具"
                },
                "item_name": {
                    "type": "string",
                    "description": "项目对应名称，比如角色名，场景名，道具名等"
                }
            },
            "required": ["item_type", "item_name"]
        }
    }
]


def list_script_jsons(user_id: str, world_id: str, auth_token: str) -> Dict[str, Any]:
    """
    列出所有剧本JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
    
    Returns:
        dict: 包含success状态和剧本文件列表的结果
    """
    try:
        # 获取上下文信息
        # context = get_context()
        # user_id = context.get('user_id')
        # world_id = context.get('world_id')
        
        # 验证上下文
        if not user_id or not world_id:
            return {
                'success': False,
                'error': '无法获取用户和世界信息，请确保会话已正确初始化',
                'data': []
            }
        
        base_dir = "files"
        user_dir = os.path.join(base_dir, str(user_id))
        world_dir = os.path.join(user_dir, str(world_id))
        scripts_dir = os.path.join(world_dir, "scripts")
        
        if not os.path.exists(scripts_dir):
            return {
                'success': True,
                'data': [],
                'message': '剧本目录不存在，返回空列表'
            }
        
        files = []
        for filename in os.listdir(scripts_dir):
            if filename.startswith("script_") and filename.endswith(".json"):
                files.append(filename)
        
        return {
            'success': True,
            'data': sorted(files),
            'message': f'成功获取 {len(files)} 个剧本文件'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'列出剧本文件失败: {str(e)}',
            'data': []
        }


def skill(SkillName: str) -> Dict[str, Any]:
    """
    调用指定技能获取详细指导和提示词 - MCP工具函数
    
    Args:
        SkillName: 技能名称
        
    Returns:
        dict: 包含技能详细内容的字典
    """
    try:
        log_skill_interaction(f"[技能调用] 开始调用技能: {SkillName}", {"skill_name": SkillName})
        skill_loader = get_skill_loader()
        
        # 检查技能是否存在
        available_skills = skill_loader.list_skills()
        log_skill_interaction(f"[技能调用] 可用技能列表: {available_skills}", {"available_skills": available_skills})
        
        if SkillName not in available_skills:
            error_msg = f'技能 "{SkillName}" 不存在。可用技能: {", ".join(available_skills)}'
            log_skill_interaction(f"[技能调用错误] {error_msg}", {"skill_name": SkillName, "error": error_msg})
            return {
                'success': False,
                'error': error_msg,
                'content': ''
            }
        
        # 获取技能的完整内容
        log_skill_interaction(f"[技能调用] 开始加载技能内容: {SkillName}", {"skill_name": SkillName})
        skill_data = skill_loader.get_skill_full_content(SkillName)
        if not skill_data:
            error_msg = f'无法加载技能 "{SkillName}" 的内容'
            log_skill_interaction(f"[技能调用错误] {error_msg}", {"skill_name": SkillName, "error": error_msg})
            return {
                'success': False,
                'error': error_msg,
                'content': ''
            }
        
        # 构建技能内容响应
        skill_content = f"# {skill_data.get('name', SkillName)} 技能\n\n"
        
        if skill_data.get('description'):
            skill_content += f"**描述**: {skill_data['description']}\n\n"
        
        skill_content += skill_data.get('prompt', '')
        
        log_skill_interaction(f"[技能调用] 成功加载技能: {SkillName}, 内容长度: {len(skill_content)}", {
            "skill_name": SkillName, 
            "content_length": len(skill_content)
        })
        
        result = {
            'success': True,
            'message': f'成功加载技能 "{SkillName}"',
            'content': skill_content,
            'skill_name': SkillName,
            'metadata': skill_loader.get_skill_metadata(SkillName)
        }
        
        log_skill_interaction(f"[技能调用] 返回结果: success={result['success']}, message={result['message']}", {
            "skill_name": SkillName,
            "success": result['success'],
            "message": result['message']
        })
        return result
        
    except Exception as e:
        error_msg = f'调用技能失败: {str(e)}'
        log_skill_interaction(f"[技能调用异常] {error_msg}", {
            "skill_name": SkillName,
            "error": str(e)
        })
        import traceback
        log_skill_interaction(f"[技能调用异常] 堆栈跟踪", {
            "skill_name": SkillName,
            "traceback": traceback.format_exc()
        })
        return {
            'success': False,
            'error': error_msg,
            'content': ''
        }

def generate_text_to_image(user_id: str, world_id: str, auth_token: str, prompt: str, 
                          model: str = "gemini-3-pro-image-preview", 
                          aspect_ratio: str = "16:9", count: int = 1, 
                          item_type: int = None, item_name: str = None, 
                          force_update_exist_image: bool = False,
                          is_grid: bool = False) -> Dict[str, Any]:
    """
    文本生成图片 - MCP工具函数（非阻塞版本，支持后台任务处理）
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        prompt: 图片描述提示词（必填）
        model: 使用的模型（默认：gemini-3-pro-image-preview）
        aspect_ratio: 图片宽高比（默认：16:9）
        count: 生成图片数量（默认：1）
        item_type: 物品类型（可选）：1=角色(character), 2=地点(location), 3=道具(props)
        item_name: 物品名称（可选），当指定item_type时必填，会自动更新对应物品的reference_image字段
        force_update_exist_image: 是否强制更新已存在的图像（默认：False）
                                 - False: 如果角色/场景/道具已有参考图像，则跳过生成
                                 - True: 强制生成并更新，覆盖现有图像
        is_grid: 是否为4宫格批量生成（默认：False）
                - True: 添加 image_size="4k" 参数，用于4宫格高分辨率生成
    
    Returns:
        dict: 操作结果，包含success状态和project_ids。如果指定了item_type和item_name，会创建后台任务自动处理
    """
    try:
        # 验证 auth_token
        if not auth_token:
            return {
                'success': False,
                'error': '认证令牌不能为空'
            }
        
        # 验证必填字段
        if not prompt or not isinstance(prompt, str):
            return {
                'success': False,
                'error': '图片描述提示词不能为空且必须是字符串'
            }
        
        # 验证item_type和item_name参数
        if item_type is not None:
            # 检测是否应该使用4宫格生成
            if not isinstance(item_type, int) or item_type not in [1, 2, 3, 4, 5, 6]:
                return {
                    'success': False,
                    'error': 'item_type参数错误。正确值：1=角色, 2=地点, 3=道具, 4=角色四宫格, 5=场景四宫格, 6=道具四宫格'
                }
            
            # 如果是单个角色/场景/道具类型(1/2/3)，但没有设置is_grid=True，给出提示
            if item_type in [1, 2, 3] and not is_grid:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"[提示] 正在为单个项目生成图像 (item_type={item_type}, item_name={item_name})。如果需要批量生成4个或更多项目，建议使用 generate_4grid_character_images() / generate_4grid_images() 函数以提高效率。")
            
            # 如果提供了item_type，必须同时提供item_name
            if not item_name or not isinstance(item_name, str):
                return {
                    'success': False,
                    'error': '当指定item_type时，必须同时提供item_name参数'
                }
            
            # 检查是否已有相同任务正在进行
            task_manager = get_task_manager()
            if task_manager.is_item_generating(item_type, item_name, user_id):
                return {
                    'success': False,
                    'error': f'该项目正在生成图片中，请等待完成后再试。可以调用相关API查询任务状态。'
                }
            
            # 检查是否已存在参考图像（除非强制更新）
            if not force_update_exist_image:
                file_manager = get_file_manager()
                
                # 根据item_type检查对应的JSON文件
                existing_data = None
                if item_type == 1:  # 角色
                    existing_data = file_manager.get_character_json(item_name, user_id, world_id)
                elif item_type == 2:  # 地点
                    existing_data = file_manager.get_location_json(item_name, user_id, world_id)
                elif item_type == 3:  # 道具
                    existing_data = file_manager.get_prop_json(item_name, user_id, world_id)
                
                # 如果找到数据且已有参考图像，则跳过生成
                if existing_data and existing_data.get('reference_image'):
                    item_type_name = {1: '角色', 2: '地点', 3: '道具'}.get(item_type, '项目')
                    return {
                        'success': False,
                        'error': f'{item_type_name} "{item_name}" 已存在参考图像，如需更新请设置 force_update_exist_image=True',
                        'existing_image': existing_data.get('reference_image'),
                        'skip_reason': 'already_has_image'
                    }
    
        # 需要读取内网，避免ssh.perseids.cn 内网无法访问的问题
        server_config = get_config().get("server", {})
        comfyui_base_url = server_config.get("comfyui_base_url_inner") or server_config.get("host", "")
        
        if not comfyui_base_url:
            return {
                'success': False,
                'error': '配置文件中未找到comfyui_base_url_inner或host配置'
            }
        
        # 准备请求数据
        request_data = {
            'prompt': prompt,
            'model': model,
            'aspect_ratio': aspect_ratio,
            'count': count,
            'user_id': user_id,
            'auth_token': auth_token
        }
        
        # 如果是4宫格生成，添加 image_size 参数
        if is_grid:
            request_data['image_size'] = '4k'
        
        # 发起文本生成图片请求
        api_url = f"{comfyui_base_url.rstrip('/')}/api/text-to-image"
        
        try:
            # 接口使用 Form 参数，需要使用 data 而不是 json 来发送表单数据
            response = requests.post(api_url, data=request_data, timeout=30)
            response.raise_for_status()
            
            result_data = response.json()
            project_ids = result_data.get('project_ids', [])
            
            if not project_ids:
                return {
                    'success': False,
                    'error': '图片生成请求成功但未返回project_ids'
                }
            
            # 如果指定了item_type和item_name，创建后台任务
            task_id = None
            if item_type is not None and item_name:
                try:
                    task_manager = get_task_manager()
                    task_id = task_manager.create_image_task(
                        project_id=project_ids[0],
                        item_type=item_type,
                        item_name=item_name,
                        comfyui_base_url=comfyui_base_url,
                        auth_token=auth_token,
                        user_id=user_id,
                        world_id=world_id
                    )
                except ValueError as e:
                    # 任务冲突
                    return {
                        'success': False,
                        'error': str(e)
                    }
                except Exception as e:
                    # 任务创建失败，但图片生成请求已提交
                    return {
                        'success': True,
                        'project_ids': project_ids,
                        'status': 'submitted',
                        'message': f'图片生成请求已提交，但后台任务创建失败: {str(e)}',
                        'warning': f'后台任务创建失败: {str(e)}',
                        'comfyui_base_url': comfyui_base_url
                    }
            
            result = {
                'success': True,
                'project_ids': project_ids,
                'status': 'submitted',
                'comfyui_base_url': comfyui_base_url
            }
            
            if task_id:
                result.update({
                    'task_id': task_id,
                    'item_type': item_type,
                    'item_name': item_name,
                    'message': f'图片生成请求已提交，后台任务已创建。project_ids: {project_ids}, task_id: {task_id}'
                })
            else:
                result['message'] = f'图片生成请求已提交，project_ids: {project_ids}'
            
            return result
            
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': f'图片生成请求失败: {str(e)}'
            }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'图片生成过程中发生错误: {str(e)}'
        }


def generate_4grid_images(user_id: str, world_id: str, auth_token: str, 
                         item_names: List[str], prompts: List[str],
                         item_type: int,
                         model: str = "gemini-3-pro-image-preview") -> Dict[str, Any]:
    """
    生成4宫格图像并自动切分更新到各个项目（角色/场景/道具）
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        item_names: 4个项目的名称列表（必须是4个）
        prompts: 4个项目的提示词列表（必须是4个）
        item_type: 项目类型（4=角色四宫格, 5=场景四宫格, 6=道具四宫格）
        model: 使用的模型（默认：NanoBananaPro）
    
    Returns:
        dict: 操作结果，包含每个项目的更新状态
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # 项目类型映射（4宫格专用）
    item_type_map = {
        4: {'name': 'character_grid', 'name_cn': '角色四宫格', 'base_type': 1},
        5: {'name': 'location_grid', 'name_cn': '场景四宫格', 'base_type': 2},
        6: {'name': 'prop_grid', 'name_cn': '道具四宫格', 'base_type': 3}
    }
    
    try:
        if item_type not in item_type_map:
            return {
                'success': False,
                'error': f'无效的item_type: {item_type}，必须是4(角色四宫格)、5(场景四宫格)或6(道具四宫格)'
            }
        
        item_info = item_type_map[item_type]
        logger.info(f"[4GRID] 开始执行 generate_4grid_images，类型={item_info['name_cn']}")
        logger.info(f"[4GRID] user_id={user_id}, world_id={world_id}")
        logger.info(f"[4GRID] item_names={item_names}, count={len(item_names) if isinstance(item_names, list) else 'NOT_LIST'}")
        logger.info(f"[4GRID] prompts count={len(prompts) if isinstance(prompts, list) else 'NOT_LIST'}")
        logger.info(f"[4GRID] model={model}")
        
        # 验证参数
        if len(item_names) != 4:
            return {
                'success': False,
                'error': f'item_names必须包含4个{item_info["name_cn"]}名称，当前提供了{len(item_names)}个'
            }
        
        if len(prompts) != 4:
            return {
                'success': False,
                'error': f'prompts必须包含4个提示词，当前提供了{len(prompts)}个'
            }
        
        # 检查是否已存在参考图像
        file_manager = get_file_manager()
        base_type = item_info['base_type']
        
        for name in item_names:
            # 跳过占位符
            if name.lower() in ['placeholder', 'pure black background']:
                continue
                
            existing_data = None
            if base_type == 1:
                existing_data = file_manager.get_character_json(name, user_id, world_id)
            elif base_type == 2:
                existing_data = file_manager.get_location_json(name, user_id, world_id)
            elif base_type == 3:
                existing_data = file_manager.get_prop_json(name, user_id, world_id)
            
            if existing_data and existing_data.get('reference_image'):
                return {
                    'success': False,
                    'error': f'已经存在的 {name} 不允许更新，必须在人工确认会导致 已有的形象被覆盖 后，再调用 generate_text_to_image 函数(force_update_exist_image 为true）去更新。'
                }
        
        # 构建4宫格JSON格式的prompt
        grid_prompt = {
            "image_generation_model": model,
            "grid_layout": "2x2",
            "grid_aspect_ratio": "16:9",
            "global_watermark": "",
            "shots": [
                {"shot_number": f"Shot {i+1}", "prompt_text": prompt}
                for i, prompt in enumerate(prompts)
            ]
        }
        
        # 构建item_name（将4个名称用逗号连接）
        combined_item_name = ','.join(item_names)
        
        # 调用图像生成API（使用is_grid=True）
        logger.info(f"[4GRID] 准备调用 generate_text_to_image")
        logger.info(f"[4GRID] grid_prompt: {json.dumps(grid_prompt, ensure_ascii=False)[:200]}...")
        logger.info(f"[4GRID] item_type={item_type}, item_name={combined_item_name}")
        
        result = generate_text_to_image(
            user_id=user_id,
            world_id=world_id,
            auth_token=auth_token,
            prompt=json.dumps(grid_prompt),
            model=model,
            aspect_ratio="16:9",
            count=1,
            item_type=item_type,  # 传递4宫格类型（4/5/6）
            item_name=combined_item_name,  # 传递组合的名称
            force_update_exist_image=False,
            is_grid=True  # 关键：启用4k参数
        )
        
        logger.info(f"[4GRID] generate_text_to_image 返回: success={result.get('success')}")
        
        # 直接返回结果，后续的轮询、下载、切分、更新操作由 cron_task_manager.py 处理
        if result.get('success'):
            result['item_type_name'] = item_info['name_cn']
            result['base_item_type'] = item_info['base_type']  # 基础类型（1/2/3）用于后续更新
            result['item_names'] = item_names
            logger.info(f"[4GRID] {item_info['name_cn']}图像生成请求已提交，后续处理由后台任务管理器完成")
        
        return result
        
    except Exception as e:
        return {
            'success': False,
            'error': f'4宫格图像生成过程中发生错误: {str(e)}'
        }


def generate_4grid_character_images(user_id: str, world_id: str, auth_token: str, 
                                    character_names: List[str], prompts: List[str],
                                    model: str = "gemini-3-pro-image-preview") -> Dict[str, Any]:
    """
    生成4宫格角色图像并自动切分更新到各个角色（向后兼容的包装函数）
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        character_names: 4个角色的名称列表（必须是4个）
        prompts: 4个角色的提示词列表（必须是4个）
        model: 使用的模型（默认：gemini-3-pro-image-preview）
    
    Returns:
        dict: 操作结果，包含每个角色的更新状态
    """
    result = generate_4grid_images(
        user_id=user_id,
        world_id=world_id,
        auth_token=auth_token,
        item_names=character_names,
        prompts=prompts,
        item_type=4,  # 角色四宫格类型
        model=model
    )
    
    # 转换返回格式以保持向后兼容
    if result.get('success') and 'items' in result:
        result['characters'] = result['items']
    
    return result


def generate_4grid_location_images(user_id: str, world_id: str, auth_token: str, 
                                    location_names: List[str], prompts: List[str],
                                    model: str = "gemini-3-pro-image-preview") -> Dict[str, Any]:
    """
    生成4宫格场景图像并自动切分更新到各个场景（向后兼容的包装函数）
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        location_names: 4个场景的名称列表（必须是4个）
        prompts: 4个场景的提示词列表（必须是4个）
        model: 使用的模型（默认：gemini-3-pro-image-preview）
    
    Returns:
        dict: 操作结果，包含每个场景的更新状态
    """
    result = generate_4grid_images(
        user_id=user_id,
        world_id=world_id,
        auth_token=auth_token,
        item_names=location_names,
        prompts=prompts,
        item_type=5,  # 场景四宫格类型
        model=model
    )
    
    # 转换返回格式以保持向后兼容
    if result.get('success') and 'items' in result:
        result['locations'] = result['items']
    
    return result


def generate_4grid_prop_images(user_id: str, world_id: str, auth_token: str, 
                                prop_names: List[str], prompts: List[str],
                                model: str = "gemini-3-pro-image-preview") -> Dict[str, Any]:
    """
    生成4宫格道具图像并自动切分更新到各个道具（向后兼容的包装函数）
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        prop_names: 4个道具的名称列表（必须是4个）
        prompts: 4个道具的提示词列表（必须是4个）
        model: 使用的模型（默认：gemini-3-pro-image-preview）
    
    Returns:
        dict: 操作结果，包含每个道具的更新状态
    """
    result = generate_4grid_images(
        user_id=user_id,
        world_id=world_id,
        auth_token=auth_token,
        item_names=prop_names,
        prompts=prompts,
        item_type=6,  # 道具四宫格类型
        model=model
    )
    
    # 转换返回格式以保持向后兼容
    if result.get('success') and 'items' in result:
        result['props'] = result['items']
    
    return result


def get_long_user_input(user_id: str, world_id: str, auth_token: str, name: str, limit: Optional[int] = None) -> str:
    """
    读取用户长文本输入的完整内容
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 文件名（例如：2026_01_22_14_01_12_abc123.txt）
        limit: 可选，限制返回字符数，避免token消耗过大
    
    Returns:
        文件完整内容或限制长度的内容
    
    Raises:
        ValueError: 文件不存在时抛出
    """
    if not user_id or not world_id:
        return json.dumps({
            'success': False,
            'error': '用户ID和世界ID不能为空'
        }, ensure_ascii=False)
    
    file_dir = os.path.join(FilePathConstants._SCRIPT_WRITER_USER_DATA_SUBDIR, str(user_id), str(world_id), "user_long_input")
    file_path = os.path.join(file_dir, name)
    
    if not os.path.exists(file_path):
        # 文件不存在时，列出目录中的所有文件供纠错
        available_files = []
        if os.path.exists(file_dir):
            try:
                available_files = [f for f in os.listdir(file_dir) if f.endswith('.txt')]
                available_files.sort(reverse=True)  # 按时间倒序排列
            except Exception as e:
                logger.error(f"列出user_long_input目录失败: {e}")
        
        return json.dumps({
            'success': False,
            'error': f'文件不存在：{name}',
            'available_files': available_files,
            'suggestion': f'可用的文件列表（共{len(available_files)}个）：{", ".join(available_files[:10])}' if available_files else '目录中没有可用文件'
        }, ensure_ascii=False)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if limit and len(content) > limit:
            truncated_content = content[:limit]
            return json.dumps({
                'success': True,
                'content': truncated_content,
                'truncated': True,
                'total_length': len(content),
                'message': f'内容已截断，完整内容共 {len(content)} 字，返回前 {limit} 字'
            }, ensure_ascii=False)
        
        return json.dumps({
            'success': True,
            'content': content,
            'truncated': False,
            'total_length': len(content)
        }, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({
            'success': False,
            'error': f'读取文件失败：{str(e)}'
        }, ensure_ascii=False)


def test_mcp_tools():
    """测试所有MCP工具函数"""
    print("=== MCP JSON工具集测试 ===")
    print("已设置测试上下文: user_id=test_user, world_id=test_world")
    
    # 测试1: 世界创建
    print("\n1. 测试世界创建:")
    world_result = create_world_json("测试世界", description="这是一个测试世界")
    print(f"世界创建结果: {world_result}")
    
    # 测试2: 名称验证功能
    print("\n2. 测试名称验证功能:")
    test_names = [
        ("张三", True),  # 纯中文，应该通过
        ("John", True),  # 纯英文，应该通过
        ("角色123", True),  # 中文+数字，应该通过
        ("Character1", True),  # 英文+数字，应该通过
        ("张三-李四", False),  # 包含特殊字符，应该失败
        ("角色 1", False),  # 包含空格，应该失败
        ("角色@1", False),  # 包含特殊符号，应该失败
        ("", False),  # 空字符串，应该失败
        ("   ", False),  # 只有空格，应该失败
    ]
    
    for test_name, should_pass in test_names:
        result = validate_name_for_filename(test_name, "测试名称")
        status = "✅ 通过" if result['valid'] == should_pass else "❌ 失败"
        print(f"  测试 '{test_name}': {status}")
        if not result['valid']:
            print(f"    错误: {result['error']}")
            if result['cleaned_name']:
                print(f"    建议: {result['cleaned_name']}")
    
    # 测试3: 技能调用
    print("\n3. 测试技能调用:")
    skill_result = skill("character-creator")
    print(f"技能调用结果: {skill_result.get('success', False)}")
    if skill_result.get('success'):
        print(f"技能内容长度: {len(skill_result.get('content', ''))} 字符")
    else:
        print(f"错误: {skill_result.get('error', '未知错误')}")
    
    # 测试4: 角色创建（包含名称验证）
    print("\n4. 测试角色创建:")
    
    # 测试有效名称
    print("  测试有效名称:")
    character_result = create_character_json(
        "张三",
        age="25",
        identity="程序员",
        appearance="中等身材，戴眼镜",
        personality="内向但专注"
    )
    print(f"  角色创建结果: {character_result.get('success', False)} - {character_result.get('message', character_result.get('error', ''))}")
    
    # 测试无效名称
    print("  测试无效名称:")
    invalid_character_result = create_character_json(
        "张三-李四",  # 包含特殊字符
        age="30",
        identity="设计师"
    )
    print(f"  无效名称结果: {invalid_character_result.get('success', False)} - {invalid_character_result.get('error', '')}")
    
    # 测试5: 地点创建（包含名称验证）
    print("\n5. 测试地点创建:")
    
    # 测试有效名称
    print("  测试有效名称:")
    location_result = create_location_json(
        "办公室",
        description="一个现代化的办公环境"
    )
    print(f"  地点创建结果: {location_result.get('success', False)} - {location_result.get('message', location_result.get('error', ''))}")
    
    # 测试无效名称
    print("  测试无效名称:")
    invalid_location_result = create_location_json(
        "办公室@1号楼",  # 包含特殊字符
        description="包含特殊字符的地点名称"
    )
    print(f"  无效名称结果: {invalid_location_result.get('success', False)} - {invalid_location_result.get('error', '')}")
    
    # 测试6: 道具创建（包含名称验证）
    print("\n6. 测试道具创建:")
    
    # 测试有效名称
    print("  测试有效名称:")
    prop_result = create_prop_json(
        "笔记本电脑",
        prop_type="电子设备",
        description="高性能的工作笔记本"
    )
    print(f"  道具创建结果: {prop_result.get('success', False)} - {prop_result.get('message', prop_result.get('error', ''))}")
    
    # 测试无效名称
    print("  测试无效名称:")
    invalid_prop_result = create_prop_json(
        "笔记本电脑#1",  # 包含特殊字符
        description="包含特殊字符的道具名称"
    )
    print(f"  无效名称结果: {invalid_prop_result.get('success', False)} - {invalid_prop_result.get('error', '')}")
    
    print("\n=== 名称验证功能测试完成 ===")
    print("所有创建函数现在都会验证名称只包含中文、英文、数字，确保文件名安全。")
    print("如果名称包含非法字符，会返回错误信息和建议的清理后名称。")
    
    # 测试5: 读取世界
    print("\n5. 测试读取世界:")
    world_data = read_world("测试世界")
    print(f"世界读取结果: {world_data}")
    
    # 测试6: 读取角色
    print("\n6. 测试读取角色:")
    character_data = read_character_json("张三")
    print(f"角色读取结果: {character_data}")
    
    # 测试7: 读取地点
    print("\n7. 测试读取地点:")
    location_data = read_location_json("办公室")
    print(f"地点读取结果: {location_data}")
    
    # 测试8: 读取道具
    print("\n8. 测试读取道具:")
    prop_data = read_prop_json("笔记本电脑")
    print(f"道具读取结果: {prop_data}")
    
    print("\n9. 测试列出所有角色:")
    all_characters = list_character_jsons()
    print(f"所有角色文件: {all_characters}")
    
    # 测试10: 列出所有地点
    print("\n10. 测试列出所有地点:")
    all_locations = list_location_jsons()
    print(f"所有地点文件: {all_locations}")
    
    # 测试11: 列出所有道具
    print("\n11. 测试列出所有道具:")
    all_props = list_prop_jsons()
    print(f"所有道具文件: {all_props}")
    
    # 测试12: 错误输入测试
    print("\n12. 测试错误输入:")
    error_result = create_character_json("")
    print(f"错误输入测试: {error_result}")
    
    # 测试13: 上下文缺失测试
    print("\n13. 测试上下文缺失:")

    no_context_result = create_character_json("测试角色")
    print(f"无上下文测试: {no_context_result}")
    
    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    test_mcp_tools()
