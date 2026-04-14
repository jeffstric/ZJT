"""
Users Model - Database operations for users table
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging
import random
import string
import json

logger = logging.getLogger(__name__)


class User:
    """User model class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.phone = kwargs.get('phone')
        self.password_hash = kwargs.get('password_hash')
        self.status = kwargs.get('status', 1)
        self.serial_number = kwargs.get('serial_number', '')
        self.secret_key = kwargs.get('secret_key')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
        self.role = kwargs.get('role', 'user')
        self.terms_agreed = kwargs.get('terms_agreed', 0)
        self.invite_code = kwargs.get('invite_code')
        self.inviter_id = kwargs.get('inviter_id')
        self.first_recharge = kwargs.get('first_recharge', 0)
        self.zjt_token_enabled = kwargs.get('zjt_token_enabled', 0)
        self.zjt_token_expire_at = kwargs.get('zjt_token_expire_at')
        # 实现方偏好相关字段
        prefs = kwargs.get('implementation_preferences')
        if isinstance(prefs, str):
            prefs = json.loads(prefs)
        self.implementation_preferences = prefs if prefs else {}
        self.active_preference_group = kwargs.get('active_preference_group', 1)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'user_id': self.id,
            'phone': self.phone,
            'status': self.status,
            'serial_number': self.serial_number,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'role': self.role,
            'terms_agreed': self.terms_agreed,
            'invite_code': self.invite_code,
            'inviter_id': self.inviter_id,
            'first_recharge': self.first_recharge,
            'implementation_preferences': self.implementation_preferences,
            'active_preference_group': self.active_preference_group,
            'zjt_token_enabled': self.zjt_token_enabled,
            'zjt_token_expire_at': self.zjt_token_expire_at,
        }


class UsersModel:
    """Users database operations"""
    
    @staticmethod
    def get_by_id(user_id: int) -> Optional[User]:
        """根据ID获取用户"""
        sql = "SELECT * FROM users WHERE id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            if result:
                return User(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get user by ID {user_id}: {e}")
            raise
    
    @staticmethod
    def get_by_phone(phone: str) -> Optional[User]:
        """根据手机号获取用户"""
        sql = "SELECT * FROM users WHERE phone = %s"
        try:
            result = execute_query(sql, (phone,), fetch_one=True)
            if result:
                return User(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get user by phone {phone}: {e}")
            raise
    
    @staticmethod
    def get_by_invite_code(invite_code: str) -> Optional[User]:
        """根据邀请码获取用户"""
        sql = "SELECT * FROM users WHERE invite_code = %s"
        try:
            result = execute_query(sql, (invite_code,), fetch_one=True)
            if result:
                return User(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get user by invite_code {invite_code}: {e}")
            raise
    
    @staticmethod
    def create(
        phone: str,
        password_hash: str,
        role: str = 'user',
        terms_agreed: int = 0,
        invite_code: Optional[str] = None,
        inviter_id: Optional[int] = None
    ) -> int:
        """创建新用户"""
        sql = """
            INSERT INTO users (phone, password_hash, role, terms_agreed, invite_code, inviter_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        try:
            user_id = execute_insert(sql, (phone, password_hash, role, terms_agreed, invite_code, inviter_id))
            logger.info(f"Created user with ID: {user_id}")
            return user_id
        except Exception as e:
            logger.error(f"Failed to create user: {e}")
            raise
    
    @staticmethod
    def update_password(user_id: int, password_hash: str) -> int:
        """更新用户密码"""
        sql = "UPDATE users SET password_hash = %s, updated_at = NOW() WHERE id = %s"
        try:
            return execute_update(sql, (password_hash, user_id))
        except Exception as e:
            logger.error(f"Failed to update password for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_serial_number(user_id: int) -> Optional[User]:
        """获取用户的序列号信息"""
        sql = "SELECT id, serial_number, updated_at FROM users WHERE id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            if result:
                return User(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get serial number for user {user_id}: {e}")
            raise
    
    @staticmethod
    def verify_phone(user_id: int, phone: str) -> bool:
        """验证手机号是否属于指定用户"""
        sql = "SELECT phone FROM users WHERE id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            if result:
                return result['phone'] == phone
            return False
        except Exception as e:
            logger.error(f"Failed to verify phone for user {user_id}: {e}")
            raise
    
    @staticmethod
    def check_serial_number_availability(serial_number: str, current_user_id: int) -> bool:
        """检查序列号是否可用（排除当前用户）"""
        sql = "SELECT id FROM users WHERE serial_number = %s AND id != %s"
        try:
            result = execute_query(sql, (serial_number, current_user_id), fetch_one=True)
            return result is None
        except Exception as e:
            logger.error(f"Failed to check serial number availability: {e}")
            raise
    
    @staticmethod
    def check_serial_number_exists(serial_number: str) -> bool:
        """检查序列号是否已存在"""
        sql = "SELECT COUNT(*) as count FROM users WHERE serial_number = %s"
        try:
            result = execute_query(sql, (serial_number,), fetch_one=True)
            return result['count'] > 0 if result else False
        except Exception as e:
            logger.error(f"Failed to check serial number exists: {e}")
            raise
    
    @staticmethod
    def update_serial_number(user_id: int, serial_number: str) -> int:
        """更新用户的序列号"""
        sql = "UPDATE users SET serial_number = %s, updated_at = NOW() WHERE id = %s"
        try:
            return execute_update(sql, (serial_number, user_id))
        except Exception as e:
            logger.error(f"Failed to update serial number for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_first_recharge_status(user_id: int) -> int:
        """查询用户是否完成首充（0-未首充，1-已首充）"""
        sql = "SELECT first_recharge FROM users WHERE id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            return result['first_recharge'] if result else 0
        except Exception as e:
            logger.error(f"Failed to get first recharge status for user {user_id}: {e}")
            raise
    
    @staticmethod
    def update_first_recharge_status(user_id: int, status: int) -> int:
        """更新用户首充状态（0-未首充，1-已首充）"""
        sql = "UPDATE users SET first_recharge = %s, updated_at = NOW() WHERE id = %s"
        try:
            return execute_update(sql, (status, user_id))
        except Exception as e:
            logger.error(f"Failed to update first recharge status for user {user_id}: {e}")
            raise
    
    @staticmethod
    def generate_unique_invite_code() -> str:
        """生成唯一的六位推荐码（数字字母组合）"""
        charset = string.ascii_uppercase + string.digits
        code_length = 6
        
        while True:
            code = ''.join(random.choice(charset) for _ in range(code_length))
            sql = "SELECT COUNT(*) as count FROM users WHERE invite_code = %s"
            try:
                result = execute_query(sql, (code,), fetch_one=True)
                if result and result['count'] == 0:
                    return code
            except Exception as e:
                logger.error(f"Failed to check invite code uniqueness: {e}")
                raise
    
    # ==================== 管理员方法 ====================
    
    @staticmethod
    def get_total_count() -> int:
        """获取用户总数"""
        sql = "SELECT COUNT(*) as count FROM users"
        try:
            result = execute_query(sql, fetch_one=True)
            return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to get total user count: {e}")
            raise
    
    @staticmethod
    def list_all(
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        status: Optional[int] = None,
        role: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        管理员获取用户列表（支持分页和筛选）
        
        Args:
            page: 页码（从1开始）
            page_size: 每页数量
            keyword: 搜索关键词（手机号）
            status: 状态筛选（0-禁用, 1-正常）
            role: 角色筛选（user/admin）
        
        Returns:
            包含 total, page, page_size, data 的字典
        """
        where_conditions = []
        params = []
        
        if keyword:
            where_conditions.append("phone LIKE %s")
            params.append(f"%{keyword}%")
        
        if status is not None:
            where_conditions.append("status = %s")
            params.append(status)
        
        if role:
            where_conditions.append("role = %s")
            params.append(role)
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        # 获取总数
        count_sql = f"SELECT COUNT(*) as count FROM users WHERE {where_clause}"
        try:
            count_result = execute_query(count_sql, tuple(params), fetch_one=True)
            total = count_result['count'] if count_result else 0
        except Exception as e:
            logger.error(f"Failed to count users: {e}")
            raise
        
        # 获取分页数据
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT id, phone, status, role, created_at, updated_at, invite_code, inviter_id, first_recharge,
                   zjt_token_enabled, zjt_token_expire_at
            FROM users
            WHERE {where_clause}
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """
        params.extend([page_size, offset])
        
        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            users = [User(**row).to_dict() for row in results] if results else []
            
            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': users
            }
        except Exception as e:
            logger.error(f"Failed to list users: {e}")
            raise
    
    @staticmethod
    def update_status(user_id: int, status: int) -> int:
        """
        更新用户状态
        
        Args:
            user_id: 用户ID
            status: 新状态（0-禁用, 1-正常）
        
        Returns:
            受影响的行数
        """
        sql = "UPDATE users SET status = %s, updated_at = NOW() WHERE id = %s"
        try:
            affected = execute_update(sql, (status, user_id))
            logger.info(f"Updated user {user_id} status to {status}")
            return affected
        except Exception as e:
            logger.error(f"Failed to update user status: {e}")
            raise
    
    @staticmethod
    def update_role(user_id: int, role: str) -> int:
        """
        更新用户角色
        
        Args:
            user_id: 用户ID
            role: 新角色（user/admin）
        
        Returns:
            受影响的行数
        """
        if role not in ('user', 'admin'):
            raise ValueError(f"Invalid role: {role}")

        sql = "UPDATE users SET role = %s, updated_at = NOW() WHERE id = %s"
        try:
            affected = execute_update(sql, (role, user_id))
            logger.info(f"Updated user {user_id} role to {role}")
            return affected
        except Exception as e:
            logger.error(f"Failed to update user role: {e}")
            raise

    # ==================== 实现方偏好方法 ====================

    @staticmethod
    def get_implementation_preference(user_id: int, task_key: str) -> Optional[str]:
        """
        获取用户对某任务的实现方偏好

        Args:
            user_id: 用户ID
            task_key: 任务key（如 gemini-2.5-flash-image-preview）

        Returns:
            用户偏好的实现方名称，未设置或不存在返回 None
        """
        sql = """
            SELECT implementation_preferences, active_preference_group
            FROM users WHERE id = %s
        """
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            if not result or not result.get('implementation_preferences'):
                return None

            preferences = result['implementation_preferences']
            if isinstance(preferences, str):
                preferences = json.loads(preferences)

            active_group = str(result.get('active_preference_group', 1))

            # 获取当前激活组的偏好
            groups = preferences.get('groups', {})
            active_group_prefs = groups.get(active_group, {})
            group_preferences = active_group_prefs.get('preferences', {})

            return group_preferences.get(task_key)
        except Exception as e:
            logger.error(f"Failed to get implementation preference for user {user_id}: {e}")
            return None

    @staticmethod
    def set_implementation_preference(user_id: int, task_key: str, implementation: str) -> int:
        """
        设置用户实现方偏好（当前激活组）

        Args:
            user_id: 用户ID
            task_key: 任务key（如 gemini-2.5-flash-image-preview）
            implementation: 实现方名称（如 gemini_duomi_v1）

        Returns:
            受影响的行数
        """
        # 先获取当前配置
        sql_get = """
            SELECT implementation_preferences, active_preference_group
            FROM users WHERE id = %s
        """
        try:
            result = execute_query(sql_get, (user_id,), fetch_one=True)
            active_group = 1

            if result and result.get('implementation_preferences'):
                preferences = result['implementation_preferences']
                if isinstance(preferences, str):
                    preferences = json.loads(preferences)
                active_group = result.get('active_preference_group', 1)
            else:
                # 创建默认结构
                preferences = {'groups': {'1': {'name': '默认配置', 'preferences': {}}}}

            # 确保组存在
            groups = preferences.get('groups', {})
            active_group = str(active_group)
            if active_group not in groups:
                groups[active_group] = {'name': f'组{active_group}', 'preferences': {}}

            # 设置偏好
            groups[active_group]['preferences'][task_key] = implementation
            preferences['groups'] = groups

            # 更新数据库
            sql_update = """
                UPDATE users
                SET implementation_preferences = %s, updated_at = NOW()
                WHERE id = %s
            """
            affected = execute_update(sql_update, (json.dumps(preferences, ensure_ascii=False), user_id))
            logger.info(f"Set implementation preference for user {user_id}: {task_key} -> {implementation}")
            return affected
        except Exception as e:
            logger.error(f"Failed to set implementation preference for user {user_id}: {e}")
            raise

    @staticmethod
    def get_all_preferences(user_id: int) -> Dict[str, str]:
        """
        获取用户所有实现方偏好（当前激活组）

        Args:
            user_id: 用户ID

        Returns:
            Dict[task_key, implementation] 偏好字典
        """
        sql = """
            SELECT implementation_preferences, active_preference_group
            FROM users WHERE id = %s
        """
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            if not result or not result.get('implementation_preferences'):
                return {}

            preferences = result['implementation_preferences']
            if isinstance(preferences, str):
                preferences = json.loads(preferences)

            active_group = str(result.get('active_preference_group', 1))
            groups = preferences.get('groups', {})
            active_group_prefs = groups.get(active_group, {})

            return active_group_prefs.get('preferences', {})
        except Exception as e:
            logger.error(f"Failed to get all preferences for user {user_id}: {e}")
            return {}

    @staticmethod
    def clear_implementation_preference(user_id: int, task_key: str) -> int:
        """
        清除用户对某任务的实现方偏好

        Args:
            user_id: 用户ID
            task_key: 任务key

        Returns:
            受影响的行数
        """
        sql_get = """
            SELECT implementation_preferences, active_preference_group
            FROM users WHERE id = %s
        """
        try:
            result = execute_query(sql_get, (user_id,), fetch_one=True)
            if not result or not result.get('implementation_preferences'):
                return 0

            preferences = result['implementation_preferences']
            if isinstance(preferences, str):
                preferences = json.loads(preferences)

            active_group = str(result.get('active_preference_group', 1))
            groups = preferences.get('groups', {})
            active_group_prefs = groups.get(active_group, {})

            # 删除偏好
            if task_key in active_group_prefs.get('preferences', {}):
                del active_group_prefs['preferences'][task_key]
                preferences['groups'][active_group] = active_group_prefs

                sql_update = """
                    UPDATE users
                    SET implementation_preferences = %s, updated_at = NOW()
                    WHERE id = %s
                """
                return execute_update(sql_update, (json.dumps(preferences, ensure_ascii=False), user_id))
            return 0
        except Exception as e:
            logger.error(f"Failed to clear implementation preference for user {user_id}: {e}")
            raise

    @staticmethod
    def get_active_preference_group(user_id: int) -> int:
        """
        获取用户当前激活的偏好组

        Args:
            user_id: 用户ID

        Returns:
            当前激活的组号（默认为1）
        """
        sql = "SELECT active_preference_group FROM users WHERE id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            return result.get('active_preference_group', 1) if result else 1
        except Exception as e:
            logger.error(f"Failed to get active preference group for user {user_id}: {e}")
            return 1

    # ==================== API Token 方法 ====================

    @staticmethod
    def get_api_token(user_id: int) -> Optional[str]:
        """
        获取用户的API Token

        Args:
            user_id: 用户ID

        Returns:
            API Token字符串，不存在返回None
        """
        sql = "SELECT api_token FROM users WHERE id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            if result is None:
                return None
            # 如果列不存在，会抛出异常，这里捕获并返回None
            try:
                return result.get('api_token')
            except Exception:
                return None
        except Exception as e:
            logger.error(f"Failed to get API token for user {user_id}: {e}")
            return None  # 静默处理，返回None

    @staticmethod
    def set_api_token(user_id: int, token: str) -> int:
        """
        设置用户的API Token（覆盖旧值）

        Args:
            user_id: 用户ID
            token: API Token

        Returns:
            受影响的行数
        """
        sql = "UPDATE users SET api_token = %s, updated_at = NOW() WHERE id = %s"
        try:
            affected = execute_update(sql, (token, user_id))
            logger.info(f"Set API token for user {user_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to set API token for user {user_id}: {e}")
            raise

    @staticmethod
    def delete_api_token(user_id: int) -> int:
        """
        删除用户的API Token

        Args:
            user_id: 用户ID

        Returns:
            受影响的行数
        """
        sql = "UPDATE users SET api_token = NULL, updated_at = NOW() WHERE id = %s"
        try:
            affected = execute_update(sql, (user_id,))
            logger.info(f"Deleted API token for user {user_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to delete API token for user {user_id}: {e}")
            raise

    # ==================== 智剧通Token方法 ====================

    @staticmethod
    def get_zjt_token_enabled(user_id: int) -> bool:
        """
        获取用户是否启用了智剧通Token

        Args:
            user_id: 用户ID

        Returns:
            是否启用（True-启用，False-未启用）
        """
        sql = "SELECT zjt_token_enabled FROM users WHERE id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            if result is None:
                return False
            try:
                return bool(result.get('zjt_token_enabled', 0))
            except Exception:
                return False
        except Exception as e:
            logger.error(f"Failed to get zjt_token_enabled for user {user_id}: {e}")
            return False

    @staticmethod
    def set_zjt_token_enabled(user_id: int, enabled: bool) -> int:
        """
        设置用户是否启用智剧通Token

        Args:
            user_id: 用户ID
            enabled: 是否启用

        Returns:
            受影响的行数
        """
        sql = "UPDATE users SET zjt_token_enabled = %s, updated_at = NOW() WHERE id = %s"
        try:
            affected = execute_update(sql, (1 if enabled else 0, user_id))
            logger.info(f"Set zjt_token_enabled for user {user_id} to {enabled}")
            return affected
        except Exception as e:
            logger.error(f"Failed to set zjt_token_enabled for user {user_id}: {e}")
            raise

    @staticmethod
    def get_zjt_token_expire_at(user_id: int) -> Optional[datetime]:
        """
        获取用户智剧通Token过期时间

        Args:
            user_id: 用户ID

        Returns:
            过期时间datetime对象，None表示未设置
        """
        sql = "SELECT zjt_token_expire_at FROM users WHERE id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            if result is None:
                return None
            return result.get('zjt_token_expire_at')
        except Exception as e:
            logger.error(f"Failed to get zjt_token_expire_at for user {user_id}: {e}")
            return None

    @staticmethod
    def set_zjt_token_expire_at(user_id: int, expire_at: Optional[datetime]) -> int:
        """
        设置用户智剧通Token过期时间

        Args:
            user_id: 用户ID
            expire_at: 过期时间datetime对象，None表示永不过期

        Returns:
            受影响的行数
        """
        sql = "UPDATE users SET zjt_token_expire_at = %s, updated_at = NOW() WHERE id = %s"
        try:
            affected = execute_update(sql, (expire_at, user_id))
            logger.info(f"Set zjt_token_expire_at for user {user_id} to {expire_at}")
            return affected
        except Exception as e:
            logger.error(f"Failed to set zjt_token_expire_at for user {user_id}: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `phone` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `password_hash` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '用户状态：1-正常，0-禁用',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `serial_number` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '序列号',
  `secret_key` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `role` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '角色',
  `terms_agreed` tinyint NOT NULL DEFAULT '0' COMMENT '同意条款（0-不同意，1-同意）',
  `invite_code` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '邀请码',
  `inviter_id` int DEFAULT NULL COMMENT '邀请人id',
  `first_recharge` tinyint DEFAULT '0' COMMENT '是否首次充值',
  `implementation_preferences` json DEFAULT NULL COMMENT '用户实现方偏好配置',
  `active_preference_group` int DEFAULT NULL COMMENT '当前激活的偏好组',
  `api_token` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用户API Token（智剧通接口授权）',
  `zjt_token_enabled` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否启用智剧通Token（0-未启用，1-已启用）',
  `zjt_token_expire_at` datetime DEFAULT NULL COMMENT '智剧通Token过期时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `idx_phone` (`phone`) USING BTREE,
  UNIQUE KEY `idx_serial_number` (`serial_number`) USING BTREE,
  UNIQUE KEY `idx_api_token` (`api_token`),
  KEY `invite_code` (`invite_code`) USING BTREE,
  KEY `inviter_id` (`inviter_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表'
"""
