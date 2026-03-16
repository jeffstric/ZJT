"""
文件管理模块
用于管理角色卡和剧本文件的读取、保存
"""

import os
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from config.constant import FilePathConstants
from utils.project_path import get_project_root


class FileManager:
    """文件管理器，处理角色卡和剧本文件"""
    
    def __init__(self, base_dir: str = None):
        """
        初始化文件管理器
        
        Args:
            base_dir: 项目根目录，默认为当前文件所在目录
        """
        if base_dir is None:
            # 使用统一的项目根目录获取函数
            base_dir = get_project_root()
        
        self.base_dir = Path(base_dir)
    
    def _get_user_world_path(self, user_id: str, world_id: str) -> Path:
        """
        获取用户世界的基础路径
        
        Args:
            user_id: 用户ID
            world_id: 世界ID
            
        Returns:
            用户世界的基础路径
        """
        return self.base_dir / FilePathConstants._SCRIPT_WRITER_USER_DATA_SUBDIR / str(user_id) / str(world_id)
    
    def _ensure_directories(self, user_id: str, world_id: str):
        """
        确保用户世界的所有目录存在
        
        Args:
            user_id: 用户ID
            world_id: 世界ID
        """
        base_path = self._get_user_world_path(user_id, world_id)
        
        # 创建所有必要的子目录
        (base_path / "characters").mkdir(parents=True, exist_ok=True)
        (base_path / "locations").mkdir(parents=True, exist_ok=True)
        (base_path / "props").mkdir(parents=True, exist_ok=True)
        (base_path / "scripts").mkdir(parents=True, exist_ok=True)
        (base_path / "worlds").mkdir(parents=True, exist_ok=True)
        
        # 确保 script_problem.json 文件存在
        script_problem_file = base_path / "script_problem.json"
        if not script_problem_file.exists():
            default_data = {"verdict": True, "problem": ""}
            script_problem_file.write_text(json.dumps(default_data, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # ==================== 路径管理工具函数 ====================
    
    def get_content_dir_path(self, user_id: str, world_id: str, content_type: str) -> str:
        """
        获取指定内容类型的目录路径
        
        Args:
            user_id: 用户ID
            world_id: 世界ID
            content_type: 内容类型 ('characters', 'locations', 'props', 'scripts', 'worlds')
            
        Returns:
            完整的目录路径字符串
        """
        self._ensure_directories(user_id, world_id)
        content_dir = self._get_user_world_path(user_id, world_id) / content_type
        return str(content_dir)
    
    def get_content_file_path(self, user_id: str, world_id: str, content_type: str, filename: str) -> str:
        """
        获取指定内容文件的完整路径
        
        Args:
            user_id: 用户ID
            world_id: 世界ID
            content_type: 内容类型 ('characters', 'locations', 'props', 'scripts', 'worlds')
            filename: 文件名
            
        Returns:
            完整的文件路径字符串
        """
        content_dir = self.get_content_dir_path(user_id, world_id, content_type)
        return os.path.join(content_dir, filename)
    
    def save_json_content(self, user_id: str, world_id: str, content_type: str, filename: str, data: dict) -> bool:
        """
        保存JSON内容到指定路径
        
        Args:
            user_id: 用户ID
            world_id: 世界ID
            content_type: 内容类型 ('characters', 'locations', 'props', 'scripts', 'worlds')
            filename: 文件名
            data: 要保存的数据
            
        Returns:
            是否保存成功
        """
        try:
            file_path = self.get_content_file_path(user_id, world_id, content_type, filename)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存JSON文件失败 {file_path}: {e}")
            return False
    
    # ==================== 剧本问题管理 ====================
    
    def get_script_problem(self, user_id: str = "0", world_id: str = "0") -> Dict[str, Any]:
        """
        获取剧本问题文件内容
        
        Args:
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
            
        Returns:
            dict: 包含 verdict (bool) 和 problem (str) 的字典
                 verdict: True表示通过，False表示不通过
                 problem: 剧本问题文本内容
        """
        self._ensure_directories(user_id, world_id)
        script_problem_file = self._get_user_world_path(user_id, world_id) / "script_problem.json"
        
        try:
            if script_problem_file.exists():
                content = script_problem_file.read_text(encoding='utf-8')
                return json.loads(content)
            return {"verdict": True, "problem": ""}
        except Exception as e:
            print(f"读取剧本问题文件失败: {e}")
            return {"verdict": True, "problem": ""}
    
    def set_script_problem(self, verdict: bool, problem: str, user_id: str = "0", world_id: str = "0") -> bool:
        """
        设置剧本问题文件内容
        
        Args:
            verdict: 审核结果，True表示通过，False表示不通过
            problem: 剧本问题文本（通常是审核报告）
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
            
        Returns:
            是否保存成功
        """
        self._ensure_directories(user_id, world_id)
        script_problem_file = self._get_user_world_path(user_id, world_id) / "script_problem.json"
        
        try:
            data = {
                "verdict": verdict,
                "problem": problem
            }
            script_problem_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"✓ 剧本问题已保存: {script_problem_file} (verdict: {verdict})")
            return True
        except Exception as e:
            print(f"✗ 保存剧本问题失败: {e}")
            return False
    
    # ==================== 角色卡管理 ====================
    
    def list_characters(self, user_id: str = "0", world_id: str = "0") -> List[Dict[str, str]]:
        """
        列出所有角色卡（JSON格式）
        
        Args:
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
        
        Returns:
            角色卡列表，每个元素包含 name, file_path, content
        """
        self._ensure_directories(user_id, world_id)
        characters_dir = self._get_user_world_path(user_id, world_id) / "characters"
        characters = []
        
        if not characters_dir.exists():
            return characters
        
        for file_path in characters_dir.glob("character_*.json"):
            try:
                json_content = file_path.read_text(encoding='utf-8')
                char_data = json.loads(json_content)
                
                # 从JSON数据生成可读的内容
                readable_content = self._format_character_json(char_data)
                
                characters.append({
                    'name': char_data.get('name', file_path.stem.replace('character_', '')),
                    'file_path': str(file_path),
                    'content': readable_content,
                    'size': len(readable_content),
                    'json_data': char_data
                })
            except Exception as e:
                print(f"读取角色卡失败 {file_path}: {e}")
        
        return characters
    
    def get_character(self, character_name: str, user_id: str = "0", world_id: str = "0") -> Optional[str]:
        """
        获取指定角色卡内容（格式化字符串）
        
        Args:
            character_name: 角色名称
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
            
        Returns:
            角色卡内容，如果不存在返回 None
        """
        self._ensure_directories(user_id, world_id)
        characters_dir = self._get_user_world_path(user_id, world_id) / "characters"
        
        # 尝试多种文件名格式
        possible_files = [
            characters_dir / f"character_{character_name}.json",
            characters_dir / f"{character_name}.json"
        ]
        
        for file_path in possible_files:
            if file_path.exists():
                try:
                    json_content = file_path.read_text(encoding='utf-8')
                    char_data = json.loads(json_content)
                    return self._format_character_json(char_data)
                except Exception as e:
                    print(f"读取角色卡失败 {character_name}: {e}")
        
        return None
    
    def get_character_json(self, character_name: str, user_id: str = "0", world_id: str = "0") -> Optional[dict]:
        """
        获取指定角色卡的原始JSON数据（用于数据库操作）
        
        Args:
            character_name: 角色名称
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
            
        Returns:
            角色卡JSON字典，如果不存在返回 None
        """
        self._ensure_directories(user_id, world_id)
        characters_dir = self._get_user_world_path(user_id, world_id) / "characters"
        
        # 尝试多种文件名格式
        possible_files = [
            characters_dir / f"character_{character_name}.json",
            characters_dir / f"{character_name}.json"
        ]
        
        for file_path in possible_files:
            if file_path.exists():
                try:
                    json_content = file_path.read_text(encoding='utf-8')
                    char_data = json.loads(json_content)
                    return char_data  # 直接返回JSON字典
                except Exception as e:
                    print(f"读取角色卡JSON失败 {character_name}: {e}")
        
        return None
    
    def save_character(self, character_name: str, content: str, user_id: str = "0", world_id: str = "0") -> bool:
        """
        保存角色卡（JSON格式）
        
        Args:
            character_name: 角色名称
            content: 角色卡内容（JSON字符串）
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
        
        Returns:
            是否保存成功
        """
        self._ensure_directories(user_id, world_id)
        characters_dir = self._get_user_world_path(user_id, world_id) / "characters"
        file_path = characters_dir / f"character_{character_name}.json"
        
        try:
            file_path.write_text(content, encoding='utf-8')
            print(f"✓ 角色卡已保存: {file_path}")
            return True
        except Exception as e:
            print(f"✗ 保存角色卡失败 {character_name}: {e}")
            return False
    
    def delete_character(self, character_name: str, user_id: str = "0", world_id: str = "0") -> bool:
        """
        删除角色卡
        
        Args:
            character_name: 角色名称
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
            
        Returns:
            是否删除成功
        """
        self._ensure_directories(user_id, world_id)
        characters_dir = self._get_user_world_path(user_id, world_id) / "characters"
        file_path = characters_dir / f"character_{character_name}.json"
        
        if not file_path.exists():
            return False
        
        try:
            file_path.unlink()
            print(f"✓ 角色卡已删除: {file_path}")
            return True
        except Exception as e:
            print(f"✗ 删除角色卡失败 {character_name}: {e}")
            return False
    
    def get_all_characters_content(self, user_id: str = "0", world_id: str = "0") -> str:
        """
        获取所有角色卡的内容，用于提供给 AI
        
        Args:
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
        
        Returns:
            所有角色卡内容的汇总字符串
        """
        characters = self.list_characters(user_id, world_id)
        
        if not characters:
            return "当前没有任何角色卡。"
        
        result = f"# 现有角色卡 (共 {len(characters)} 个)\n\n"
        
        for char in characters:
            result += f"## {char['name']}\n\n"
            result += f"```markdown\n{char['content']}\n```\n\n"
            result += "---\n\n"
        
        return result
    
    # ==================== 剧本管理 ====================
    
    def list_scripts(self, user_id: str = "0", world_id: str = "0") -> List[Dict[str, str]]:
        """
        列出所有剧本（JSON格式）
        
        Args:
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
        
        Returns:
            剧本列表，每个元素包含 name, file_path, content, episode_number
        """
        self._ensure_directories(user_id, world_id)
        scripts_dir = self._get_user_world_path(user_id, world_id) / "scripts"
        scripts = []
        
        if not scripts_dir.exists():
            return scripts
        
        for file_path in scripts_dir.glob("script_*.json"):
            try:
                content = file_path.read_text(encoding='utf-8')
                script_data = json.loads(content)
                
                # 从JSON数据中获取信息
                title = script_data.get('title', file_path.stem)
                episode_number = script_data.get('episode_number', None)
                script_content = script_data.get('content', '')
                
                scripts.append({
                    'name': title,
                    'file_path': str(file_path),
                    'content': script_content,
                    'size': len(script_content),
                    'episode': episode_number,
                    'episode_number': episode_number,  # 保持兼容性
                    'title': title,
                    'created_at': script_data.get('create_time', ''),
                    'updated_at': script_data.get('update_time', '')
                })
            except Exception as e:
                print(f"读取剧本失败 {file_path}: {e}")
        
        return scripts
    
    def get_script(self, script_name: str, user_id: str = "0", world_id: str = "0") -> Optional[Dict]:
        """
        获取指定剧本内容（JSON格式）
        
        Args:
            script_name: 剧本名称或文件名
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
            
        Returns:
            剧本数据字典，如果不存在返回 None
        """
        self._ensure_directories(user_id, world_id)
        scripts_dir = self._get_user_world_path(user_id, world_id) / "scripts"
        
        # 尝试不同的文件名格式
        possible_files = [
            scripts_dir / f"{script_name}.json",
            scripts_dir / f"script_{script_name}.json",
            scripts_dir / script_name if script_name.endswith('.json') else None
        ]
        
        for file_path in possible_files:
            if file_path and file_path.exists():
                try:
                    content = file_path.read_text(encoding='utf-8')
                    return json.loads(content)
                except Exception as e:
                    print(f"读取剧本失败 {file_path}: {e}")
                    continue
        
        return None
    
    def save_script(self, script_name: str, content: str, user_id: str = "0", world_id: str = "0") -> bool:
        """
        保存剧本
        
        Args:
            script_name: 剧本名称
            content: 剧本内容（JSON格式字符串）
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
            
        Returns:
            是否保存成功
        """
        self._ensure_directories(user_id, world_id)
        scripts_dir = self._get_user_world_path(user_id, world_id) / "scripts"
        file_path = scripts_dir / f"script_{script_name}.json"
        
        try:
            file_path.write_text(content, encoding='utf-8')
            print(f"✓ 剧本已保存: {file_path}")
            return True
        except Exception as e:
            print(f"✗ 保存剧本失败 {script_name}: {e}")
            return False
    
    def delete_script(self, script_name: str, user_id: str = "0", world_id: str = "0") -> bool:
        """
        删除剧本
        
        Args:
            script_name: 剧本名称
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
            
        Returns:
            是否删除成功
        """
        self._ensure_directories(user_id, world_id)
        scripts_dir = self._get_user_world_path(user_id, world_id) / "scripts"
        
        # 尝试不同的文件名格式
        possible_files = [
            scripts_dir / f"{script_name}.json",
            scripts_dir / f"script_{script_name}.json",
            scripts_dir / script_name if script_name.endswith('.json') else None
        ]
        
        for file_path in possible_files:
            if file_path and file_path.exists():
                try:
                    file_path.unlink()
                    print(f"✓ 剧本已删除: {file_path}")
                    return True
                except Exception as e:
                    print(f"✗ 删除剧本失败 {script_name}: {e}")
                    continue
        
        return False
    
    # ==================== 场景管理 ====================
    
    def list_locations(self, user_id: str = "0", world_id: str = "0") -> List[Dict[str, str]]:
        """列出所有场景"""
        self._ensure_directories(user_id, world_id)
        locations_dir = self._get_user_world_path(user_id, world_id) / "locations"
        locations = []
        
        if not locations_dir.exists():
            return locations
        
        for file_path in locations_dir.glob("location_*.json"):
            try:
                json_content = file_path.read_text(encoding='utf-8')
                loc_data = json.loads(json_content)
                readable_content = self._format_location_json(loc_data)
                
                locations.append({
                    'name': loc_data.get('name', file_path.stem.replace('location_', '')),
                    'file_path': str(file_path),
                    'content': readable_content,
                    'size': len(readable_content),
                    'json_data': loc_data
                })
            except Exception as e:
                print(f"读取场景文件失败 {file_path}: {e}")
        
        return sorted(locations, key=lambda x: x['name'])
    
    def get_location(self, location_name: str, user_id: str = "0", world_id: str = "0") -> Optional[str]:
        """读取场景内容"""
        self._ensure_directories(user_id, world_id)
        locations_dir = self._get_user_world_path(user_id, world_id) / "locations"
        
        # 尝试多种文件名格式
        possible_files = [
            locations_dir / f"location_{location_name}.json",
            locations_dir / f"{location_name}.json"
        ]
        
        for file_path in possible_files:
            if file_path.exists():
                try:
                    json_content = file_path.read_text(encoding='utf-8')
                    loc_data = json.loads(json_content)
                    return self._format_location_json(loc_data)
                except Exception as e:
                    print(f"读取场景失败 {location_name}: {e}")
        
        return None
    
    def get_location_json(self, location_name: str, user_id: str = "0", world_id: str = "0") -> Optional[dict]:
        """
        获取指定场景的原始JSON数据（用于数据库操作）
        
        Args:
            location_name: 场景名称
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
            
        Returns:
            场景JSON字典，如果不存在返回 None
        """
        self._ensure_directories(user_id, world_id)
        locations_dir = self._get_user_world_path(user_id, world_id) / "locations"
        
        # 尝试多种文件名格式
        possible_files = [
            locations_dir / f"location_{location_name}.json",
            locations_dir / f"{location_name}.json"
        ]
        
        for file_path in possible_files:
            if file_path.exists():
                try:
                    json_content = file_path.read_text(encoding='utf-8')
                    loc_data = json.loads(json_content)
                    return loc_data  # 直接返回JSON字典
                except Exception as e:
                    print(f"读取场景JSON失败 {location_name}: {e}")
        
        return None
    
    def save_location(self, location_name: str, content: str, user_id: str = "0", world_id: str = "0") -> bool:
        """保存场景"""
        self._ensure_directories(user_id, world_id)
        locations_dir = self._get_user_world_path(user_id, world_id) / "locations"
        file_path = locations_dir / f"location_{location_name}.json"
        
        try:
            file_path.write_text(content, encoding='utf-8')
            print(f"✓ 场景已保存: {file_path}")
            return True
        except Exception as e:
            print(f"✗ 保存场景失败 {location_name}: {e}")
            return False
    
    def delete_location(self, location_name: str, user_id: str = "0", world_id: str = "0") -> bool:
        """删除场景"""
        self._ensure_directories(user_id, world_id)
        locations_dir = self._get_user_world_path(user_id, world_id) / "locations"
        file_path = locations_dir / f"location_{location_name}.json"
        
        if not file_path.exists():
            return False
        
        try:
            file_path.unlink()
            print(f"✓ 场景已删除: {file_path}")
            return True
        except Exception as e:
            print(f"✗ 删除场景失败 {location_name}: {e}")
            return False
    
    # ==================== 世界管理 ====================
    
    def get_world_json(self, user_id: str = "0", world_id: str = "0") -> Optional[dict]:
        """
        获取世界信息的JSON数据
        
        Args:
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
            
        Returns:
            世界JSON字典，如果不存在返回 None
        """
        self._ensure_directories(user_id, world_id)
        worlds_dir = self._get_user_world_path(user_id, world_id) / "worlds"
        file_path = worlds_dir / f"world_{world_id}.json"
        
        if file_path.exists():
            try:
                json_content = file_path.read_text(encoding='utf-8')
                world_data = json.loads(json_content)
                return world_data
            except Exception as e:
                print(f"读取世界JSON失败 world_id={world_id}: {e}")
        
        return None
    
    def save_world(self, world_data: dict, user_id: str = "0", world_id: str = "0") -> bool:
        """
        保存世界信息（JSON格式）
        
        Args:
            world_data: 世界数据字典
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
        
        Returns:
            是否保存成功
        """
        self._ensure_directories(user_id, world_id)
        worlds_dir = self._get_user_world_path(user_id, world_id) / "worlds"
        file_path = worlds_dir / f"world_{world_id}.json"
        
        try:
            world_json = json.dumps(world_data, ensure_ascii=False, indent=2)
            file_path.write_text(world_json, encoding='utf-8')
            print(f"✓ 世界信息已保存: {file_path}")
            return True
        except Exception as e:
            print(f"✗ 保存世界信息失败 world_id={world_id}: {e}")
            return False
    
    # ==================== 道具管理 ====================
    
    def list_props(self, user_id: str = "0", world_id: str = "0") -> List[Dict[str, str]]:
        """列出所有道具"""
        self._ensure_directories(user_id, world_id)
        props_dir = self._get_user_world_path(user_id, world_id) / "props"
        props = []
        
        if not props_dir.exists():
            return props
        
        for file_path in props_dir.glob("prop_*.json"):
            try:
                json_content = file_path.read_text(encoding='utf-8')
                prop_data = json.loads(json_content)
                readable_content = self._format_prop_json(prop_data)
                
                props.append({
                    'name': prop_data.get('name', file_path.stem.replace('prop_', '')),
                    'file_path': str(file_path),
                    'content': readable_content,
                    'size': len(readable_content),
                    'json_data': prop_data
                })
            except Exception as e:
                print(f"读取道具文件失败 {file_path}: {e}")
        
        return sorted(props, key=lambda x: x['name'])
    
    def get_prop(self, prop_name: str, user_id: str = "0", world_id: str = "0") -> Optional[str]:
        """读取道具内容"""
        self._ensure_directories(user_id, world_id)
        props_dir = self._get_user_world_path(user_id, world_id) / "props"
        
        # 尝试多种文件名格式
        possible_files = [
            props_dir / f"prop_{prop_name}.json",
            props_dir / f"{prop_name}.json"
        ]
        
        for file_path in possible_files:
            if file_path.exists():
                try:
                    json_content = file_path.read_text(encoding='utf-8')
                    prop_data = json.loads(json_content)
                    return self._format_prop_json(prop_data)
                except Exception as e:
                    print(f"读取道具失败 {prop_name}: {e}")
        
        return None
    
    def get_prop_json(self, prop_name: str, user_id: str = "0", world_id: str = "0") -> Optional[dict]:
        """
        获取指定道具的原始JSON数据（用于数据库操作）
        
        Args:
            prop_name: 道具名称
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
            
        Returns:
            道具JSON字典，如果不存在返回 None
        """
        self._ensure_directories(user_id, world_id)
        props_dir = self._get_user_world_path(user_id, world_id) / "props"
        
        # 尝试多种文件名格式
        possible_files = [
            props_dir / f"prop_{prop_name}.json",
            props_dir / f"{prop_name}.json"
        ]
        
        for file_path in possible_files:
            if file_path.exists():
                try:
                    json_content = file_path.read_text(encoding='utf-8')
                    prop_data = json.loads(json_content)
                    return prop_data  # 直接返回JSON字典
                except Exception as e:
                    print(f"读取道具JSON失败 {prop_name}: {e}")
        
        return None
    
    def save_prop(self, prop_name: str, content: str, user_id: str = "0", world_id: str = "0") -> bool:
        """保存道具"""
        self._ensure_directories(user_id, world_id)
        props_dir = self._get_user_world_path(user_id, world_id) / "props"
        file_path = props_dir / f"prop_{prop_name}.json"
        
        try:
            file_path.write_text(content, encoding='utf-8')
            print(f"✓ 道具已保存: {file_path}")
            return True
        except Exception as e:
            print(f"✗ 保存道具失败 {prop_name}: {e}")
            return False
    
    def delete_prop(self, prop_name: str, user_id: str = "0", world_id: str = "0") -> bool:
        """删除道具"""
        self._ensure_directories(user_id, world_id)
        props_dir = self._get_user_world_path(user_id, world_id) / "props"
        file_path = props_dir / f"prop_{prop_name}.json"
        
        if not file_path.exists():
            return False
        
        try:
            file_path.unlink()
            print(f"✓ 道具已删除: {file_path}")
            return True
        except Exception as e:
            print(f"✗ 删除道具失败 {prop_name}: {e}")
            return False
    
    # ==================== JSON格式化方法 ====================
    
    def _format_character_json(self, char_data: Dict) -> str:
        """将角色JSON数据格式化为可读的文本"""
        content = f"# {char_data.get('name', '未知角色')}\n\n"
        
        if char_data.get('age'):
            content += f"**年龄**: {char_data['age']}\n\n"
        
        if char_data.get('identity'):
            content += f"**身份**: {char_data['identity']}\n\n"
        
        if char_data.get('appearance'):
            content += f"## 外貌\n{char_data['appearance']}\n\n"
        
        if char_data.get('personality'):
            content += f"## 性格\n{char_data['personality']}\n\n"
        
        if char_data.get('behavior'):
            content += f"## 行为习惯\n{char_data['behavior']}\n\n"
        
        if char_data.get('other_info'):
            content += f"## 其他信息\n{char_data['other_info']}\n\n"
        
        if char_data.get('reference_image'):
            content += f"**参考图片**: {char_data['reference_image']}\n\n"
        
        return content
    
    def _format_location_json(self, loc_data: Dict) -> str:
        """将场景JSON数据格式化为可读的文本"""
        content = f"# {loc_data.get('name', '未知场景')}\n\n"
        
        if loc_data.get('parent_id'):
            content += f"**父级场景**: {loc_data['parent_id']}\n\n"
        
        if loc_data.get('description'):
            content += f"## 场景描述\n{loc_data['description']}\n\n"
        
        if loc_data.get('reference_image'):
            content += f"**参考图片**: {loc_data['reference_image']}\n\n"
        
        return content
    
    def _format_prop_json(self, prop_data: Dict) -> str:
        """将道具JSON数据格式化为可读的文本"""
        content = f"# {prop_data.get('name', '未知道具')}\n\n"
        
        if prop_data.get('type'):
            content += f"**类型**: {prop_data['type']}\n\n"
        
        if prop_data.get('description'):
            content += f"## 道具描述\n{prop_data['description']}\n\n"
        
        if prop_data.get('reference_image'):
            content += f"**参考图片**: {prop_data['reference_image']}\n\n"
        
        return content

    # ==================== 辅助方法 ====================
    
    def get_context_for_ai(self, user_id: str = "0", world_id: str = "0", summary_only: bool = False) -> str:
        """
        获取完整的上下文信息供 AI 使用
        包括世界信息、角色卡、剧本、场景和道具的完整内容
        
        Args:
            user_id: 用户ID，默认为 "7"
            world_id: 世界ID，默认为 "1"
            summary_only: 是否只返回摘要（200字符），默认False返回完整内容
        
        Returns:
            格式化的上下文字符串，包含所有文件的完整内容或摘要
        """
        context = "# 项目文件资源\n\n"
        
        # 世界信息
        world_data = self.get_world_json(user_id, world_id)
        if world_data:
            context += f"## 世界信息\n\n"
            context += f"**世界名称**: {world_data.get('name', '未命名')}\n\n"
            
            if world_data.get('story_outline'):
                context += f"**故事大纲**:\n{world_data.get('story_outline')}\n\n"
            
            if world_data.get('visual_style'):
                context += f"**画面风格**:\n{world_data.get('visual_style')}\n\n"
            
            if world_data.get('era_environment'):
                context += f"**时代环境**:\n{world_data.get('era_environment')}\n\n"
            
            if world_data.get('color_language'):
                context += f"**色彩语言**:\n{world_data.get('color_language')}\n\n"
            
            if world_data.get('composition_preference'):
                context += f"**构图倾向**:\n{world_data.get('composition_preference')}\n\n"
            
            context += "---\n\n"
        
        # 角色卡信息
        characters = self.list_characters(user_id, world_id)
        context += f"## 角色卡 ({len(characters)} 个)\n\n"
        
        if characters:
            for char in characters:
                char_data = self.get_character(char['name'], user_id, world_id)
                if char_data:
                    context += f"### {char['name']}\n\n"
                    if summary_only:
                        # 只返回前200字符作为摘要
                        summary = char_data[:200]
                        context += f"```\n{summary}\n... (内容已截断，完整内容请使用read_character_json工具读取)\n```\n\n"
                    else:
                        context += f"```\n{char_data}\n```\n\n"
        else:
            context += "暂无角色卡\n\n"
        
        # 剧本信息
        scripts = self.list_scripts(user_id, world_id)
        context += f"## 剧本 ({len(scripts)} 个)\n\n"
        
        if scripts:
            for script in scripts:
                script_data = self.get_script(script['name'], user_id, world_id)
                if script_data:
                    content_str = script_data.get('content', '') if isinstance(script_data, dict) else str(script_data)
                    context += f"### {script['name']}\n\n"
                    if summary_only:
                        # 只返回前200字符作为摘要
                        summary = content_str[:200]
                        context += f"```\n{summary}\n... (内容已截断，完整内容请使用read_script_json工具读取)\n```\n\n"
                    else:
                        context += f"```\n{content_str}\n```\n\n"
        else:
            context += "暂无剧本\n\n"
        
        # 场景信息
        locations = self.list_locations(user_id, world_id)
        context += f"## 场景 ({len(locations)} 个)\n\n"
        
        if locations:
            for loc in locations:
                loc_data = self.get_location(loc['name'], user_id, world_id)
                if loc_data:
                    context += f"### {loc['name']}\n\n"
                    if summary_only:
                        # 只返回前200字符作为摘要
                        summary = loc_data[:200]
                        context += f"```\n{summary}\n... (内容已截断，完整内容请使用read_location_json工具读取)\n```\n\n"
                    else:
                        context += f"```\n{loc_data}\n```\n\n"
        else:
            context += "暂无场景\n\n"
        
        # 道具信息
        props = self.list_props(user_id, world_id)
        context += f"## 道具 ({len(props)} 个)\n\n"
        
        if props:
            for prop in props:
                prop_data = self.get_prop(prop['name'], user_id, world_id)
                if prop_data:
                    context += f"### {prop['name']}\n\n"
                    if summary_only:
                        # 只返回前200字符作为摘要
                        summary = prop_data[:200]
                        context += f"```\n{summary}\n... (内容已截断，完整内容请使用read_prop_json工具读取)\n```\n\n"
                    else:
                        context += f"```\n{prop_data}\n```\n\n"
        else:
            context += "暂无道具\n\n"
        
        return context
    
    def clear_user_world_directory(self, user_id: str, world_id: str) -> bool:
        """
        清空用户世界目录中的所有内容
        删除 characters, locations, props, scripts, worlds 目录及其内容
        以及 script_problem.json 和 agent_history 目录
        
        Args:
            user_id: 用户ID
            world_id: 世界ID
            
        Returns:
            是否清空成功
        """
        import shutil
        
        try:
            base_path = self._get_user_world_path(user_id, world_id)
            
            if not base_path.exists():
                print(f"目录不存在，无需清空: {base_path}")
                return True
            
            # 删除所有子目录和文件
            directories_to_clear = ['characters', 'locations', 'props', 'scripts', 'worlds', 'agent_history']
            files_to_clear = ['script_problem.json']
            
            deleted_count = 0
            
            # 删除目录
            for dir_name in directories_to_clear:
                dir_path = base_path / dir_name
                if dir_path.exists():
                    shutil.rmtree(dir_path)
                    deleted_count += 1
                    print(f"✓ 已删除目录: {dir_path}")
            
            # 删除文件
            for file_name in files_to_clear:
                file_path = base_path / file_name
                if file_path.exists():
                    file_path.unlink()
                    deleted_count += 1
                    print(f"✓ 已删除文件: {file_path}")
            
            print(f"✓ 用户世界目录已清空: {base_path} (删除了 {deleted_count} 项)")
            
            # 重新初始化目录结构
            self._ensure_directories(user_id, world_id)
            print(f"✓ 目录结构已重新初始化")
            
            return True
        except Exception as e:
            print(f"✗ 清空用户世界目录失败: {e}")
            return False
    
    def get_stats(self, user_id: str = "0", world_id: str = "0") -> Dict:
        """
        获取统计信息
        
        Args:
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"
        
        Returns:
            包含统计数据的字典
        """
        characters = self.list_characters(user_id, world_id)
        scripts = self.list_scripts(user_id, world_id)
        locations = self.list_locations(user_id, world_id)
        props = self.list_props(user_id, world_id)
        
        return {
            'characters_count': len(characters),
            'scripts_count': len(scripts),
            'locations_count': len(locations),
            'props_count': len(props),
            'characters_dir': str(self.characters_dir),
            'locations_dir': str(self.locations_dir),
            'props_dir': str(self.props_dir),
            'characters': [c['name'] for c in characters],
            'scripts': [s['name'] for s in scripts],
            'locations': [l['name'] for l in locations],
            'props': [p['name'] for p in props]
        }


# 测试代码
if __name__ == "__main__":
    fm = FileManager()
    
    print("\n=== 统计信息 ===")
    stats = fm.get_stats()
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    
    print("\n=== 角色卡列表 ===")
    characters = fm.list_characters()
    for char in characters:
        print(f"- {char['name']}: {char['size']} 字符")
    
    print("\n=== 剧本列表 ===")
    scripts = fm.list_scripts()
    for script in scripts:
        print(f"- {script['name']}: {script['size']} 字符")
