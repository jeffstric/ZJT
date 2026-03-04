"""
认证辅助模块
提供 auth_token 验证功能
"""

from typing import Optional, Tuple
from perseids_client import make_perseids_request
from config.constant import Edition


class AuthHelper:
    """认证辅助类"""
    
    @staticmethod
    def verify_token(auth_token: str, user_id: str = None, world_id: str = None) -> Tuple[bool, Optional[str]]:
        """
        验证 auth_token 是否有效，并确保用户ID一致性
        
        Args:
            auth_token: 认证令牌
            user_id: 用户ID（可选，用于验证 token 是否属于该用户）
            world_id: 世界ID（可选，用于验证 token 是否有权限访问该世界）
        
        Returns:
            tuple: (是否验证通过, 错误信息)
                - (True, None): 验证通过
                - (False, "错误信息"): 验证失败
        """
        # 1. 通过 auth_token 获取用户ID
        headers = {'Authorization': f'Bearer {auth_token}'}
        success, message, response_data = make_perseids_request(
            endpoint='user/get_user_id_by_auth_token',
            method='POST',
            headers=headers
        )

        if not success:
            return False, f'获取用户ID失败: {message}'
        
        if not response_data or 'user_id' not in response_data:
            return False, '无法从认证服务获取用户ID'
        
        token_user_id = str(response_data.get('user_id'))
        
        # 2. 如果提供了 user_id，验证是否与 token 中的用户ID一致
        if user_id is not None:
            if str(user_id) != token_user_id:
                return False, f'用户ID不匹配: 传入的用户ID({user_id})与token中的用户ID({token_user_id})不一致'
        
        # 3. 如果提供了 world_id，验证该世界是否属于该用户
        if world_id is not None:
            try:
                from model.world import WorldModel
                
                world = WorldModel.get_by_id(int(world_id))
                
                if not world:
                    return False, f'世界不存在: world_id={world_id}'

                # 商业版才验证用户隔离
                if Edition.is_enterprise():
                    world_user_id = str(world.user_id)

                    # 验证世界的用户ID与token的用户ID是否一致
                    if world_user_id != token_user_id:
                        return False, f'无权访问该世界: 世界属于用户{world_user_id}，但token属于用户{token_user_id}'

                    # 如果同时提供了 user_id，也要验证与世界的用户ID一致
                    if user_id is not None and str(user_id) != world_user_id:
                        return False, f'用户ID不匹配: 传入的用户ID({user_id})与世界所属用户ID({world_user_id})不一致'

            except Exception as e:
                return False, f'验证世界权限时发生错误: {str(e)}'
        
        return True, None
    
