"""
文件管理模块
用于管理角色卡和剧本文件的读取、保存
"""

import os
import re
import json
import shutil
import zipfile
import tempfile
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any, Set, Tuple
from config.constant import FilePathConstants, StoryType, UploadPathConstants
from utils.project_path import get_project_root

logger = logging.getLogger(__name__)


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
    
    def resolve_character_file_path(
        self, character_name: str, user_id: str = "0", world_id: str = "0"
    ) -> Optional[Path]:
        """
        解析角色 JSON 文件真实路径。

        查找顺序：
        1. character_{name}.json
        2. character_{sanitize(name)}.json（空格/特殊字符转下划线）
        3. {name}.json
        4. 扫描 characters/character_*.json，按 JSON 内 name 字段匹配
        """
        self._ensure_directories(user_id, world_id)
        characters_dir = self._get_user_world_path(user_id, world_id) / "characters"
        if not characters_dir.exists():
            return None

        name = (character_name or "").strip()
        if not name:
            return None

        # 与 mcp_tool._sanitize_filename 对齐的轻量清理（避免循环导入）
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', name)
        safe_name = re.sub(r'\s+', '_', safe_name).strip('._')
        if len(safe_name) > 50:
            safe_name = safe_name[:50]

        candidates = [
            characters_dir / f"character_{name}.json",
            characters_dir / f"character_{safe_name}.json",
            characters_dir / f"{name}.json",
        ]
        # 去重但保序
        seen = set()
        unique_candidates = []
        for p in candidates:
            key = str(p)
            if key not in seen:
                seen.add(key)
                unique_candidates.append(p)

        for file_path in unique_candidates:
            if file_path.exists():
                return file_path

        # 回退：扫描 JSON 内 name 字段（兼容拼音/临时文件名）
        for file_path in characters_dir.glob("character_*.json"):
            try:
                char_data = json.loads(file_path.read_text(encoding='utf-8'))
                if isinstance(char_data, dict) and (char_data.get('name') or '').strip() == name:
                    return file_path
            except Exception as e:
                print(f"扫描角色卡失败 {file_path}: {e}")

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
        file_path = self.resolve_character_file_path(character_name, user_id, world_id)
        if not file_path:
            return None

        try:
            json_content = file_path.read_text(encoding='utf-8')
            return json.loads(json_content)
        except Exception as e:
            print(f"读取角色卡JSON失败 {character_name} ({file_path}): {e}")
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
        
        for file_path in scripts_dir.glob("*.json"):
            try:
                content = file_path.read_text(encoding='utf-8')
                script_data = json.loads(content)

                # 从JSON数据中获取信息
                title = script_data.get('title', file_path.stem)
                episode_number = script_data.get('episode_number', None)
                script_content = script_data.get('content', '')

                # 生成展示名称：第x集：title
                if episode_number is not None:
                    display_name = f"第{episode_number}集：{title}"
                else:
                    display_name = title

                scripts.append({
                    'name': title,
                    'file_name': file_path.stem,  # 磁盘文件名（不含扩展名）
                    'display_name': display_name,
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

        # 回退：遍历所有 json 文件，按 title 或 episode_number 匹配
        if scripts_dir.exists():
            for fp in scripts_dir.glob("*.json"):
                try:
                    data = json.loads(fp.read_text(encoding='utf-8'))
                    if data.get('title') == script_name or str(data.get('episode_number')) == script_name:
                        return data
                except Exception:
                    continue

        return None
    
    def save_script(self, script_name: str, content: str, user_id: str = "0", world_id: str = "0") -> bool:
        """
        保存剧本

        Args:
            script_name: 剧本名称或集数
            content: 剧本内容（JSON格式字符串）
            user_id: 用户ID，默认为 "0"
            world_id: 世界ID，默认为 "0"

        Returns:
            是否保存成功
        """
        self._ensure_directories(user_id, world_id)
        scripts_dir = self._get_user_world_path(user_id, world_id) / "scripts"

        # 解析 content 获取 episode_number
        episode_number = None
        title = script_name
        try:
            content_data = json.loads(content)
            episode_number = content_data.get('episode_number')
            title = content_data.get('title', script_name)
        except (json.JSONDecodeError, AttributeError):
            pass

        # 确定文件名：优先使用 episode_number
        if episode_number is not None:
            filename = f"{episode_number}.json"
        else:
            filename = f"script_{script_name}.json"

        file_path = scripts_dir / filename

        # 清理旧格式文件：如果旧 script_{title}.json 存在且与新文件名不同，删除旧文件
        if episode_number is not None:
            old_file = scripts_dir / f"script_{title}.json"
            if old_file.exists() and old_file != file_path:
                try:
                    old_file.unlink()
                    print(f"✓ 已清理旧格式文件: {old_file}")
                except Exception as e:
                    print(f"⚠ 清理旧文件失败: {e}")

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
            script_name: 剧本名称或集数
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

        # 回退：遍历所有 json 文件，按 title 或 episode_number 匹配
        if scripts_dir.exists():
            for fp in scripts_dir.glob("*.json"):
                try:
                    data = json.loads(fp.read_text(encoding='utf-8'))
                    if data.get('title') == script_name or str(data.get('episode_number')) == script_name:
                        fp.unlink()
                        print(f"✓ 剧本已删除: {fp}")
                        return True
                except Exception:
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
                world_data['story_type'] = StoryType.normalize(world_data.get('story_type'))
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
            world_data['story_type'] = StoryType.normalize(world_data.get('story_type'))
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
            
            story_type = world_data.get('story_type') or 'dialogue'
            story_type_labels = {
                'dialogue': '对话剧情',
                'narration': '旁白解说',
                'music_mv': '音乐MV',
            }
            context += f"**故事类型**: {story_type_labels.get(story_type, '对话剧情')} ({story_type})\n\n"

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
                # 优先使用 file_name（集数）查找，回退到 title
                lookup_key = script.get('file_name', script['name'])
                script_data = self.get_script(lookup_key, user_id, world_id)
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

    # ==================== 导出/导入 ====================

    # 匹配 reference_image URL 的正则：{SERVER_HOST}/upload/{type}/pic/{filename}
    _IMAGE_URL_PATTERN = re.compile(r'/upload/(character|location|props)/pic/([^"\s\'}\]]+)')

    # 匹配 default_voice URL 的正则：{SERVER_HOST}/upload/character/voice/{filename}
    _VOICE_URL_PATTERN = re.compile(r'/upload/character/voice/([^"\s\'}\]]+)')

    # 音频扩展名白名单
    _AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac'}

    # 导出时需要清除的数据库字段
    _DB_ID_FIELDS = {'id', 'world_id', 'user_id', 'create_time', 'update_time'}

    def _strip_db_ids(self, data: Any) -> Any:
        """
        清除 JSON 顶层 dict 中的数据库 ID 字段，避免跨世界导入时 ID 冲突。
        仅清除顶层字段，不递归处理嵌套 dict。
        """
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in self._DB_ID_FIELDS}
        return data

    def _collect_voice_from_url(self, url: str) -> Optional[Tuple[str, Path]]:
        """
        从音频 URL 中提取文件名和实际文件路径。

        Args:
            url: 音频 URL，如 http://host/upload/character/voice/voice_001.wav

        Returns:
            (filename, file_path) 或 None
        """
        if not url or not isinstance(url, str):
            return None
        match = self._VOICE_URL_PATTERN.search(url)
        if not match:
            return None
        filename = match.group(1)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in self._AUDIO_EXTENSIONS:
            return None
        file_path = self.base_dir / UploadPathConstants.UPLOAD_ROOT / UploadPathConstants.CHARACTER_VOICE_DIR / filename
        if file_path.exists():
            return (filename, file_path)
        return None

    def _collect_image_from_url(self, url: str) -> Optional[Tuple[str, str, Path]]:
        """
        从图片 URL 中提取类型、文件名和实际文件路径

        Args:
            url: 图片 URL，如 http://host/upload/character/pic/uuid.png

        Returns:
            (image_type, filename, file_path) 或 None
        """
        if not url or not isinstance(url, str):
            return None
        match = self._IMAGE_URL_PATTERN.search(url)
        if not match:
            return None
        image_type = match.group(1)  # character / location / props
        filename = match.group(2)    # uuid.png
        file_path = self.base_dir / UploadPathConstants.UPLOAD_ROOT / image_type / "pic" / filename
        if file_path.exists():
            return (image_type, filename, file_path)
        return None

    def _rewrite_image_urls(self, data: Any, image_mapping: Dict[str, str], collected: Set[str],
                             zipf: Optional[zipfile.ZipFile] = None,
                             audio_mapping: Optional[Dict[str, str]] = None,
                             collected_audios: Optional[Set[str]] = None) -> Any:
        """
        递归扫描 JSON 数据，替换图片/音频 URL 为相对路径，并收集文件到 zip

        Args:
            data: JSON 数据（dict/list/str/其他）
            image_mapping: URL → 相对路径 的映射表（会被修改）
            collected: 已收集的图片文件名集合（会被修改）
            zipf: zipfile 对象，如果提供则将图片/音频写入 zip
            audio_mapping: 音频 filename → original_url_path 的映射表
            collected_audios: 已收集的音频文件名集合

        Returns:
            处理后的数据
        """
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if key == 'reference_image' and isinstance(value, str) and value.strip():
                    # 单张参考图
                    info = self._collect_image_from_url(value)
                    if info:
                        image_type, filename, file_path = info
                        rel_path = f"images/{filename}"
                        if filename not in collected and zipf:
                            zipf.write(file_path, rel_path)
                            collected.add(filename)
                        result[key] = rel_path
                        image_mapping[filename] = f"/upload/{image_type}/pic/{filename}"
                    else:
                        result[key] = value
                elif key == 'reference_images' and isinstance(value, list):
                    # 多角度参考图列表
                    new_list = []
                    for item in value:
                        if isinstance(item, dict) and 'url' in item:
                            info = self._collect_image_from_url(item['url'])
                            if info:
                                image_type, filename, file_path = info
                                rel_path = f"images/{filename}"
                                if filename not in collected and zipf:
                                    zipf.write(file_path, rel_path)
                                    collected.add(filename)
                                new_item = {**item, 'url': rel_path}
                                image_mapping[filename] = f"/upload/{image_type}/pic/{filename}"
                            else:
                                new_item = item
                            new_list.append(new_item)
                        else:
                            new_list.append(item)
                    result[key] = new_list
                elif key == 'default_voice' and isinstance(value, str) and value.strip():
                    # 角色默认音频
                    if audio_mapping is not None and collected_audios is not None:
                        info = self._collect_voice_from_url(value)
                        if info:
                            filename, file_path = info
                            rel_path = f"audios/{filename}"
                            if filename not in collected_audios and zipf:
                                zipf.write(file_path, rel_path)
                                collected_audios.add(filename)
                            result[key] = rel_path
                            audio_mapping[filename] = f"/upload/character/voice/{filename}"
                        else:
                            result[key] = value
                    else:
                        result[key] = value
                else:
                    result[key] = self._rewrite_image_urls(
                        value, image_mapping, collected, zipf,
                        audio_mapping=audio_mapping, collected_audios=collected_audios
                    )
            return result
        elif isinstance(data, list):
            return [self._rewrite_image_urls(
                item, image_mapping, collected, zipf,
                audio_mapping=audio_mapping, collected_audios=collected_audios
            ) for item in data]
        else:
            return data

    def export_world(self, user_id: str, world_id: str) -> str:
        """
        导出世界完整数据（含图片）为 zip 包

        Args:
            user_id: 用户ID
            world_id: 世界ID

        Returns:
            zip 文件的临时路径
        """
        base_path = self._get_user_world_path(user_id, world_id)
        if not base_path.exists():
            raise FileNotFoundError(f"世界目录不存在: {base_path}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 优先使用世界名称作为导出文件名，便于用户识别
        world_data = self.get_world_json(user_id, world_id)
        world_name = (world_data.get('name') or '').strip() if world_data else ''
        if world_name:
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', world_name)
            safe_name = re.sub(r'\s+', '_', safe_name).strip('._')
            if len(safe_name) > 50:
                safe_name = safe_name[:50]
            zip_name = f"{safe_name}_{timestamp}.zip" if safe_name else f"world_export_{world_id}_{timestamp}.zip"
        else:
            zip_name = f"world_export_{world_id}_{timestamp}.zip"
        zip_path = Path(tempfile.gettempdir()) / zip_name

        collected_images: Set[str] = set()
        image_mapping: Dict[str, str] = {}  # filename → original_url_path
        collected_audios: Set[str] = set()
        audio_mapping: Dict[str, str] = {}  # filename → original_url_path

        export_subdirs = ['characters', 'locations', 'props', 'scripts', 'worlds']

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 1. 打包各子目录的 JSON 文件（重写图片/音频 URL，清除数据库 ID）
            for subdir in export_subdirs:
                subdir_path = base_path / subdir
                if not subdir_path.exists():
                    continue
                for json_file in sorted(subdir_path.glob('*.json')):
                    try:
                        json_content = json_file.read_text(encoding='utf-8')
                        data = json.loads(json_content)
                        # 重写 URL 并收集图片和音频
                        data = self._rewrite_image_urls(
                            data, image_mapping, collected_images, zipf,
                            audio_mapping=audio_mapping, collected_audios=collected_audios
                        )
                        # 清除数据库 ID 字段
                        data = self._strip_db_ids(data)
                        zipf.writestr(
                            f"{subdir}/{json_file.name}",
                            json.dumps(data, ensure_ascii=False, indent=2)
                        )
                    except Exception as e:
                        logger.warning(f"导出文件失败 {json_file}: {e}")

            # 2. 打包 script_problem.json
            problem_file = base_path / "script_problem.json"
            if problem_file.exists():
                zipf.write(problem_file, "script_problem.json")

            # 3. 写入 image_mapping.json（导入时用于还原 URL）
            if image_mapping:
                zipf.writestr(
                    "image_mapping.json",
                    json.dumps(image_mapping, ensure_ascii=False, indent=2)
                )

            # 3.5 写入 audio_mapping.json（导入时用于还原音频 URL）
            if audio_mapping:
                zipf.writestr(
                    "audio_mapping.json",
                    json.dumps(audio_mapping, ensure_ascii=False, indent=2)
                )

            # 4. 写入 metadata.json
            metadata = {
                "export_version": "1.0",
                "export_time": datetime.now().isoformat(),
                "world_id": str(world_id),
                "user_id": str(user_id),
                "image_count": len(collected_images),
                "audio_count": len(collected_audios),
                "subdirs": export_subdirs
            }
            zipf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

        logger.info(f"世界导出完成: {zip_path} (图片 {len(collected_images)} 张, 音频 {len(collected_audios)} 个)")
        return str(zip_path)

    def _restore_image_urls(self, data: Any, reverse_mapping: Dict[str, str],
                              uploaded: Dict[str, str], upload_base: Path,
                              audio_mapping: Optional[Dict[str, str]] = None) -> Any:
        """
        递归扫描 JSON 数据，将相对路径还原为完整 URL，并复制图片到 upload 目录

        Args:
            data: JSON 数据
            reverse_mapping: 相对路径(filename) → 原始 URL路径 的映射
            uploaded: filename → 新的完整URL路径 的映射（会被修改）
            upload_base: upload 根目录
            audio_mapping: 音频 filename → 原始 URL路径 的映射

        Returns:
            处理后的数据
        """
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if key == 'reference_image' and isinstance(value, str):
                    filename = value.replace('images/', '') if value.startswith('images/') else None
                    if filename and filename in reverse_mapping:
                        # 复制图片到 upload 目录
                        src_path = filename  # zip 内路径
                        url_path = reverse_mapping[filename]
                        result[key] = url_path
                        uploaded[filename] = url_path
                    else:
                        result[key] = value
                elif key == 'reference_images' and isinstance(value, list):
                    new_list = []
                    for item in value:
                        if isinstance(item, dict) and 'url' in item:
                            url_val = item['url']
                            filename = url_val.replace('images/', '') if url_val.startswith('images/') else None
                            if filename and filename in reverse_mapping:
                                url_path = reverse_mapping[filename]
                                new_item = {**item, 'url': url_path}
                                uploaded[filename] = url_path
                            else:
                                new_item = item
                            new_list.append(new_item)
                        else:
                            new_list.append(item)
                    result[key] = new_list
                elif key == 'default_voice' and isinstance(value, str) and audio_mapping:
                    # 还原角色音频 URL
                    audio_filename = value.replace('audios/', '') if value.startswith('audios/') else None
                    if audio_filename and audio_filename in audio_mapping:
                        result[key] = audio_mapping[audio_filename]
                    else:
                        result[key] = value
                else:
                    result[key] = self._restore_image_urls(
                        value, reverse_mapping, uploaded, upload_base,
                        audio_mapping=audio_mapping
                    )
            return result
        elif isinstance(data, list):
            return [self._restore_image_urls(
                item, reverse_mapping, uploaded, upload_base,
                audio_mapping=audio_mapping
            ) for item in data]
        else:
            return data

    def import_world(self, user_id: str, world_id: str, zip_path: str) -> Dict[str, Any]:
        """
        从 zip 包导入世界数据

        Args:
            user_id: 用户ID
            world_id: 世界ID
            zip_path: zip 文件路径

        Returns:
            导入结果统计
        """
        base_path = self._get_user_world_path(user_id, world_id)
        self._ensure_directories(user_id, world_id)

        upload_base = self.base_dir / UploadPathConstants.UPLOAD_ROOT
        result = {
            "scripts": 0, "characters": 0, "locations": 0, "props": 0,
            "worlds": 0, "images": 0, "audios": 0, "errors": []
        }

        with zipfile.ZipFile(zip_path, 'r') as zipf:
            # 1. 读取 image_mapping.json
            image_mapping = {}
            if "image_mapping.json" in zipf.namelist():
                try:
                    image_mapping = json.loads(zipf.read("image_mapping.json").decode('utf-8'))
                except Exception as e:
                    logger.warning(f"读取 image_mapping.json 失败: {e}")

            # 1.5 读取 audio_mapping.json
            audio_mapping = {}
            if "audio_mapping.json" in zipf.namelist():
                try:
                    audio_mapping = json.loads(zipf.read("audio_mapping.json").decode('utf-8'))
                except Exception as e:
                    logger.warning(f"读取 audio_mapping.json 失败: {e}")

            # 2. 复制图片到 upload 目录
            uploaded_images: Dict[str, str] = {}  # filename → url_path
            for zip_name in zipf.namelist():
                if not zip_name.startswith('images/'):
                    continue
                filename = zip_name[len('images/'):]
                if not filename or filename.endswith('/'):
                    continue
                if filename not in image_mapping:
                    continue

                url_path = image_mapping[filename]  # /upload/{type}/pic/{filename}
                # 从 url_path 解析目标目录
                match = self._IMAGE_URL_PATTERN.search(url_path)
                if not match:
                    continue
                image_type = match.group(1)
                dest_dir = upload_base / image_type / "pic"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_file = dest_dir / filename

                if not dest_file.exists():
                    try:
                        image_data = zipf.read(zip_name)
                        dest_file.write_bytes(image_data)
                        result["images"] += 1
                    except Exception as e:
                        result["errors"].append(f"图片导入失败 {filename}: {e}")

                uploaded_images[filename] = url_path

            # 2.5 复制音频到 upload 目录
            for zip_name in zipf.namelist():
                if not zip_name.startswith('audios/'):
                    continue
                audio_filename = zip_name[len('audios/'):]
                if not audio_filename or audio_filename.endswith('/'):
                    continue
                if audio_filename not in audio_mapping:
                    continue

                dest_dir = upload_base / UploadPathConstants.CHARACTER_VOICE_DIR
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_file = dest_dir / audio_filename

                if not dest_file.exists():
                    try:
                        audio_data = zipf.read(zip_name)
                        dest_file.write_bytes(audio_data)
                        result["audios"] += 1
                    except Exception as e:
                        result["errors"].append(f"音频导入失败 {audio_filename}: {e}")

            # 3. 导入各子目录的 JSON 文件
            subdir_map = {
                'characters': 'characters',
                'locations': 'locations',
                'props': 'props',
                'scripts': 'scripts',
                'worlds': 'worlds'
            }

            for zip_name in zipf.namelist():
                # 匹配 subdir/filename.json 模式
                parts = zip_name.split('/', 1)
                if len(parts) != 2:
                    continue
                subdir, filename = parts
                if subdir not in subdir_map or not filename.endswith('.json'):
                    continue

                try:
                    content = zipf.read(zip_name).decode('utf-8')
                    data = json.loads(content)

                    # 还原图片和音频 URL
                    data = self._restore_image_urls(
                        data, image_mapping, uploaded_images, upload_base,
                        audio_mapping=audio_mapping
                    )

                    # 写入文件
                    dest_dir = base_path / subdir
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    # 对于 worlds 子目录，重写文件名为目标世界 ID
                    actual_filename = filename
                    if subdir == 'worlds':
                        actual_filename = f"world_{world_id}.json"
                    dest_file = dest_dir / actual_filename
                    dest_file.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding='utf-8'
                    )
                    result[subdir_map[subdir]] += 1
                except Exception as e:
                    result["errors"].append(f"导入失败 {zip_name}: {e}")

            # 4. 导入 script_problem.json
            if "script_problem.json" in zipf.namelist():
                try:
                    content = zipf.read("script_problem.json").decode('utf-8')
                    (base_path / "script_problem.json").write_text(content, encoding='utf-8')
                except Exception as e:
                    result["errors"].append(f"导入 script_problem.json 失败: {e}")

        logger.info(f"世界导入完成: {result}")
        return result

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
