"""
安全文件操作处理器
确保 AI 操作文件时必须使用带有 user_id 和 world_id 的方法，避免跨用户访问
"""

import re
from typing import Optional, Dict, Any, Tuple
from script_writer_core.file_manager import FileManager
from script_writer_core.auth_helper import AuthHelper


class FileOperationHandler:
    """安全文件操作处理器"""
    
    def __init__(self, user_id: str, world_id: str, auth_token: str, file_manager: FileManager = None):
        """
        初始化文件操作处理器
        
        Args:
            user_id: 用户ID
            world_id: 世界ID
            auth_token: 认证令牌
            file_manager: FileManager 实例（可选，如果不提供则创建新实例）
        """
        self.user_id = user_id
        self.world_id = world_id
        self.auth_token = auth_token
        self.file_manager = file_manager if file_manager is not None else FileManager()
    
    def _verify_auth(self) -> Tuple[bool, Optional[str]]:
        """
        验证认证令牌
        
        Returns:
            tuple: (是否验证通过, 错误信息)
        """
        return AuthHelper.verify_token(self.auth_token, self.user_id, self.world_id)
    
    def process_ai_response(self, response: str) -> tuple[str, list]:
        """
        处理 AI 响应，提取并执行文件操作
        
        Args:
            response: AI 的响应文本
        
        Returns:
            tuple: (处理后的响应文本, 操作结果列表)
        """
        operations = []
        
        # 提取并处理角色卡保存操作
        # 支持大小写不敏感，更灵活的空白符处理
        character_pattern = r'```\s*(?:CHARACTER_CARD|character_card)\s*:\s*([^\n]+)\s*\n([\s\S]+?)```'
        for match in re.finditer(character_pattern, response, re.IGNORECASE):
            char_name = match.group(1).strip()
            char_content = match.group(2).strip()
            
            if char_name and char_content:
                result = self.save_character(char_name, char_content)
                operations.append(result)
        
        # 提取并处理剧本保存操作
        # 支持大小写不敏感，更灵活的空白符处理
        script_pattern = r'```\s*(?:SCRIPT|script)\s*:\s*([^\n]+)\s*\n([\s\S]+?)```'
        for match in re.finditer(script_pattern, response, re.IGNORECASE):
            script_name = match.group(1).strip()
            script_content = match.group(2).strip()
            
            if script_name and script_content:
                result = self.save_script(script_name, script_content)
                operations.append(result)
        
        # 提取并处理场景保存操作
        # 支持大小写不敏感，更灵活的空白符处理
        location_pattern = r'```\s*(?:LOCATION|location)\s*:\s*([^\n]+)\s*\n([\s\S]+?)```'
        for match in re.finditer(location_pattern, response, re.IGNORECASE):
            location_name = match.group(1).strip()
            location_content = match.group(2).strip()
            
            if location_name and location_content:
                result = self.save_location(location_name, location_content)
                operations.append(result)
        
        # 提取并处理道具保存操作
        # 支持大小写不敏感，更灵活的空白符处理
        prop_pattern = r'```\s*(?:PROP|prop)\s*:\s*([^\n]+)\s*\n([\s\S]+?)```'
        for match in re.finditer(prop_pattern, response, re.IGNORECASE):
            prop_name = match.group(1).strip()
            prop_content = match.group(2).strip()
            
            if prop_name and prop_content:
                result = self.save_prop(prop_name, prop_content)
                operations.append(result)
        
        return response, operations
    
    def save_character(self, name: str, content: str) -> Dict[str, Any]:
        """
        保存角色卡（仅保存到文件系统）
        
        Args:
            name: 角色名称
            content: 角色卡内容
        
        Returns:
            dict: 操作结果
        """
        # 验证 auth_token
        is_valid, error_msg = self._verify_auth()
        if not is_valid:
            return {
                'type': 'character',
                'name': name,
                'success': False,
                'error': error_msg or '认证失败',
                'message': f'保存角色卡 "{name}" 失败: {error_msg or "认证失败"}'
            }
        
        try:
            # 只保存到文件系统
            file_result = self.file_manager.save_character(
                name, 
                content, 
                self.user_id, 
                self.world_id
            )
            
            return {
                'type': 'character',
                'name': name,
                'success': True,
                'file_saved': file_result,
                'message': f'角色卡 "{name}" 已保存到文件（使用"提交到数据库"按钮可同步到数据库）'
            }
                
        except Exception as e:
            return {
                'type': 'character',
                'name': name,
                'success': False,
                'error': str(e),
                'message': f'保存角色卡 "{name}" 失败: {str(e)}'
            }
    
    def save_script(self, name: str, content: str) -> Dict[str, Any]:
        """
        保存剧本（仅保存到文件系统）
        
        Args:
            name: 剧本名称
            content: 剧本内容（markdown格式）
        
        Returns:
            dict: 操作结果
        """
        # 验证 auth_token
        is_valid, error_msg = self._verify_auth()
        if not is_valid:
            return {
                'type': 'script',
                'name': name,
                'success': False,
                'error': error_msg or '认证失败',
                'message': f'保存剧本 "{name}" 失败: {error_msg or "认证失败"}'
            }
        
        try:
            # 将markdown内容转换为JSON格式
            from datetime import datetime
            script_data = {
                'title': name,
                'episode_number': None,
                'content': content,
                'create_time': datetime.now().isoformat(),
                'update_time': datetime.now().isoformat()
            }
            
            # 转换为JSON字符串
            import json
            script_json = json.dumps(script_data, ensure_ascii=False, indent=2)
            
            # 保存到文件系统
            file_result = self.file_manager.save_script(
                name, 
                script_json, 
                self.user_id, 
                self.world_id
            )
            
            return {
                'type': 'script',
                'name': name,
                'success': True,
                'file_saved': file_result,
                'message': f'剧本 "{name}" 已保存到文件（使用"提交到数据库"按钮可同步到数据库）'
            }
                
        except Exception as e:
            return {
                'type': 'script',
                'name': name,
                'success': False,
                'error': str(e),
                'message': f'保存剧本 "{name}" 失败: {str(e)}'
            }
    
    def save_location(self, name: str, content: str) -> Dict[str, Any]:
        """
        保存场景（仅保存到文件系统）
        
        Args:
            name: 场景名称
            content: 场景内容
        
        Returns:
            dict: 操作结果
        """
        # 验证 auth_token
        is_valid, error_msg = self._verify_auth()
        if not is_valid:
            return {
                'type': 'location',
                'name': name,
                'success': False,
                'error': error_msg or '认证失败',
                'message': f'保存场景 "{name}" 失败: {error_msg or "认证失败"}'
            }
        
        try:
            # 只保存到文件系统
            file_result = self.file_manager.save_location(
                name, 
                content, 
                self.user_id, 
                self.world_id
            )
            
            return {
                'type': 'location',
                'name': name,
                'success': True,
                'file_saved': file_result,
                'message': f'场景 "{name}" 已保存到文件（使用"提交到数据库"按钮可同步到数据库）'
            }
                
        except Exception as e:
            return {
                'type': 'location',
                'name': name,
                'success': False,
                'error': str(e),
                'message': f'保存场景 "{name}" 失败: {str(e)}'
            }
    
    def save_prop(self, name: str, content: str) -> Dict[str, Any]:
        """
        保存道具（仅文件系统，暂无数据库表）
        
        Args:
            name: 道具名称
            content: 道具内容
        
        Returns:
            dict: 操作结果
        """
        # 验证 auth_token
        is_valid, error_msg = self._verify_auth()
        if not is_valid:
            return {
                'type': 'prop',
                'name': name,
                'success': False,
                'error': error_msg or '认证失败',
                'message': f'保存道具 "{name}" 失败: {error_msg or "认证失败"}'
            }
        
        try:
            # 保存到文件系统
            file_result = self.file_manager.save_prop(
                name, 
                content, 
                self.user_id, 
                self.world_id
            )
            
            return {
                'type': 'prop',
                'name': name,
                'success': True,
                'file_saved': file_result,
                'message': f'道具 "{name}" 已保存到文件'
            }
                
        except Exception as e:
            return {
                'type': 'prop',
                'name': name,
                'success': False,
                'error': str(e),
                'message': f'保存道具 "{name}" 失败: {str(e)}'
            }
    
    def get_character(self, name: str) -> Optional[str]:
        """
        读取角色卡（带权限控制）
        
        Args:
            name: 角色名称
        
        Returns:
            str: 角色卡内容，不存在返回 None
        """
        return self.file_manager.get_character(name, self.user_id, self.world_id)
    
    def get_script(self, name: str) -> Optional[str]:
        """
        读取剧本（带权限控制）
        
        Args:
            name: 剧本名称
        
        Returns:
            str: 剧本内容，不存在返回 None
        """
        return self.file_manager.get_script(name, self.user_id, self.world_id)
    
    def get_location(self, name: str) -> Optional[str]:
        """
        读取场景（带权限控制）
        
        Args:
            name: 场景名称
        
        Returns:
            str: 场景内容，不存在返回 None
        """
        return self.file_manager.get_location(name, self.user_id, self.world_id)
    
    def get_prop(self, name: str) -> Optional[str]:
        """
        读取道具（带权限控制）
        
        Args:
            name: 道具名称
        
        Returns:
            str: 道具内容，不存在返回 None
        """
        return self.file_manager.get_prop(name, self.user_id, self.world_id)
    
    def delete_character(self, name: str) -> bool:
        """
        删除角色卡（带权限控制）
        
        Args:
            name: 角色名称
        
        Returns:
            bool: 删除成功返回 True
        """
        return self.file_manager.delete_character(name, self.user_id, self.world_id)
    
    def delete_script(self, name: str) -> bool:
        """
        删除剧本（带权限控制）
        
        Args:
            name: 剧本名称
        
        Returns:
            bool: 删除成功返回 True
        """
        return self.file_manager.delete_script(name, self.user_id, self.world_id)
    
    def delete_location(self, name: str) -> bool:
        """
        删除场景（带权限控制）
        
        Args:
            name: 场景名称
        
        Returns:
            bool: 删除成功返回 True
        """
        return self.file_manager.delete_location(name, self.user_id, self.world_id)
    
    def delete_prop(self, name: str) -> bool:
        """
        删除道具（带权限控制）
        
        Args:
            name: 道具名称
        
        Returns:
            bool: 删除成功返回 True
        """
        return self.file_manager.delete_prop(name, self.user_id, self.world_id)
    
    def list_all_files(self) -> Dict[str, list]:
        """
        列出当前用户和世界的所有文件
        
        Returns:
            dict: 包含所有文件类型的字典
        """
        return {
            'characters': self.file_manager.list_characters(self.user_id, self.world_id),
            'scripts': self.file_manager.list_scripts(self.user_id, self.world_id),
            'locations': self.file_manager.list_locations(self.user_id, self.world_id),
            'props': self.file_manager.list_props(self.user_id, self.world_id)
        }
