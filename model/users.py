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

from utils.log_sanitizer import mask_email, mask_phone

logger = logging.getLogger(__name__)


def parse_implementation_preferences(raw) -> dict:
    """Parse users.implementation_preferences JSON into a dict. Invalid input → {}."""
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def get_active_preference_group_data(preferences: dict, active_group) -> dict:
    groups = preferences.get('groups') if isinstance(preferences, dict) else None
    if not isinstance(groups, dict):
        return {}
    group_key = str(active_group if active_group is not None else 1)
    group = groups.get(group_key, {})
    return group if isinstance(group, dict) else {}


def get_group_preference_map(group: dict) -> dict:
    prefs = group.get('preferences') if isinstance(group, dict) else None
    return prefs if isinstance(prefs, dict) else {}


def get_group_lock_map(group: dict) -> dict:
    locks = group.get('locks') if isinstance(group, dict) else None
    return locks if isinstance(locks, dict) else {}


def is_task_implementation_locked(group: dict, task_key: str) -> bool:
    """True only when the task has a preferred implementation AND locks[task_key] is True."""
    if not task_key:
        return False
    prefs = get_group_preference_map(group)
    if not prefs.get(task_key):
        return False
    locks = get_group_lock_map(group)
    return locks.get(task_key) is True


def collect_true_locks(group: dict) -> Dict[str, bool]:
    prefs = get_group_preference_map(group)
    locks = get_group_lock_map(group)
    return {key: True for key, value in locks.items() if value is True and prefs.get(key)}


class User:
    """User model class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.phone = kwargs.get('phone')
        self.email = kwargs.get('email')
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
        self.commission_rate = kwargs.get('commission_rate')
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
            'email': self.email,
            'status': self.status,
            'serial_number': self.serial_number,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'role': self.role,
            'terms_agreed': self.terms_agreed,
            'invite_code': self.invite_code,
            'inviter_id': self.inviter_id,
            'commission_rate': float(self.commission_rate) if self.commission_rate is not None else None,
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
            logger.error(
                "Failed to get user by phone %s: %s",
                mask_phone(phone),
                e,
            )
            raise

    @staticmethod
    def get_by_email(email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        sql = "SELECT * FROM users WHERE email = %s"
        try:
            result = execute_query(sql, (email,), fetch_one=True)
            if result:
                return User(**result)
            return None
        except Exception as e:
            logger.error(
                "Failed to get user by email %s: %s",
                mask_email(email),
                e,
            )
            raise

    @staticmethod
    def get_by_phone_or_email(identifier: str) -> Optional[User]:
        """根据手机号或邮箱获取用户（用于统一登录）"""
        # 先判断是手机号还是邮箱
        import re
        if re.match(r'^1[3-9]\d{9}$', identifier):
            return UsersModel.get_by_phone(identifier)
        elif '@' in identifier:
            return UsersModel.get_by_email(identifier)
        else:
            # 尝试两种都查
            user = UsersModel.get_by_phone(identifier)
            if not user:
                user = UsersModel.get_by_email(identifier)
            return user

    @staticmethod
    def update_email(user_id: int, email: Optional[str]) -> int:
        """更新用户邮箱"""
        sql = "UPDATE users SET email = %s, updated_at = NOW() WHERE id = %s"
        try:
            affected = execute_update(sql, (email, user_id))
            logger.info(
                "Updated user %s email to %s",
                user_id,
                mask_email(email),
            )
            return affected
        except Exception as e:
            logger.error(f"Failed to update email for user {user_id}: {e}")
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
        inviter_id: Optional[int] = None,
        email: Optional[str] = None
    ) -> int:
        """创建新用户"""
        sql = """
            INSERT INTO users (phone, email, password_hash, role, terms_agreed, invite_code, inviter_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        try:
            user_id = execute_insert(sql, (phone, email, password_hash, role, terms_agreed, invite_code, inviter_id))
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
    def get_commission_rate(user_id: int):
        """获取邀请人佣金比例（Decimal；None/0 表示不抽佣）"""
        sql = "SELECT commission_rate FROM users WHERE id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            return result['commission_rate'] if result else None
        except Exception as e:
            logger.error(f"Failed to get commission rate for user {user_id}: {e}")
            raise

    @staticmethod
    def update_commission_rate(user_id: int, rate) -> int:
        """设置邀请人佣金比例（0~0.5；0=关闭抽佣）"""
        sql = "UPDATE users SET commission_rate = %s, updated_at = NOW() WHERE id = %s"
        try:
            return execute_update(sql, (rate, user_id))
        except Exception as e:
            logger.error(f"Failed to update commission rate for user {user_id}: {e}")
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
            where_conditions.append("(phone LIKE %s OR email LIKE %s)")
            params.append(f"%{keyword}%")
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
            SELECT id, phone, email, status, role, created_at, updated_at, invite_code, inviter_id, first_recharge,
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
    def _load_preference_state(user_id: int) -> tuple:
        """读取用户偏好 JSON 与当前激活组。用户不存在时返回 ({}, '1')。"""
        sql = """
            SELECT implementation_preferences, active_preference_group
            FROM users WHERE id = %s
        """
        result = execute_query(sql, (user_id,), fetch_one=True)
        if not result:
            return {}, '1'
        preferences = parse_implementation_preferences(result.get('implementation_preferences'))
        active_group = result.get('active_preference_group', 1)
        return preferences, str(active_group if active_group is not None else 1)

    @staticmethod
    def _save_preference_state(user_id: int, preferences: dict) -> int:
        sql_update = """
            UPDATE users
            SET implementation_preferences = %s, updated_at = NOW()
            WHERE id = %s
        """
        return execute_update(sql_update, (json.dumps(preferences, ensure_ascii=False), user_id))

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
        try:
            preferences, active_group = UsersModel._load_preference_state(user_id)
            group = get_active_preference_group_data(preferences, active_group)
            return get_group_preference_map(group).get(task_key)
        except Exception as e:
            logger.error(f"Failed to get implementation preference for user {user_id}: {e}")
            return None

    @staticmethod
    def is_implementation_locked(user_id: int, task_key: str) -> bool:
        """当前激活组是否将该任务类型固定为指定实现方（失败不切换）。"""
        try:
            preferences, active_group = UsersModel._load_preference_state(user_id)
            group = get_active_preference_group_data(preferences, active_group)
            return is_task_implementation_locked(group, task_key)
        except Exception as e:
            logger.error(f"Failed to get implementation lock for user {user_id}: {e}")
            return False

    @staticmethod
    def set_implementation_preference(
        user_id: int,
        task_key: str,
        implementation: str,
        locked: bool = False,
    ) -> int:
        """
        设置用户实现方偏好（当前激活组）

        Args:
            user_id: 用户ID
            task_key: 任务key（如 gemini-2.5-flash-image-preview）
            implementation: 实现方名称（如 gemini_duomi_v1）
            locked: True 表示固定该实现方，失败后不切换其他供应商

        Returns:
            受影响的行数
        """
        try:
            preferences, active_group = UsersModel._load_preference_state(user_id)
            groups = preferences.get('groups')
            if not isinstance(groups, dict):
                groups = {}
                preferences['groups'] = groups
            if active_group not in groups or not isinstance(groups.get(active_group), dict):
                groups[active_group] = {'name': '默认配置' if active_group == '1' else f'组{active_group}', 'preferences': {}}

            group = groups[active_group]
            prefs = get_group_preference_map(group)
            prefs[task_key] = implementation
            group['preferences'] = prefs

            locks = get_group_lock_map(group)
            if locked:
                locks[task_key] = True
            else:
                locks.pop(task_key, None)
            group['locks'] = locks
            groups[active_group] = group
            preferences['groups'] = groups

            affected = UsersModel._save_preference_state(user_id, preferences)
            logger.info(
                f"Set implementation preference for user {user_id}: "
                f"{task_key} -> {implementation}, locked={bool(locked)}"
            )
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
        try:
            preferences, active_group = UsersModel._load_preference_state(user_id)
            group = get_active_preference_group_data(preferences, active_group)
            return dict(get_group_preference_map(group))
        except Exception as e:
            logger.error(f"Failed to get all preferences for user {user_id}: {e}")
            return {}

    @staticmethod
    def get_all_locks(user_id: int) -> Dict[str, bool]:
        """获取当前激活组中已固定（且仍有对应偏好）的任务类型。"""
        try:
            preferences, active_group = UsersModel._load_preference_state(user_id)
            group = get_active_preference_group_data(preferences, active_group)
            return collect_true_locks(group)
        except Exception as e:
            logger.error(f"Failed to get implementation locks for user {user_id}: {e}")
            return {}

    @staticmethod
    def clear_implementation_preference(user_id: int, task_key: str) -> int:
        """
        清除用户对某任务的实现方偏好（同时清除固定标记）

        Args:
            user_id: 用户ID
            task_key: 任务key

        Returns:
            受影响的行数
        """
        try:
            preferences, active_group = UsersModel._load_preference_state(user_id)
            groups = preferences.get('groups')
            if not isinstance(groups, dict):
                return 0
            group = groups.get(active_group)
            if not isinstance(group, dict):
                return 0

            prefs = get_group_preference_map(group)
            locks = get_group_lock_map(group)
            changed = False
            if task_key in prefs:
                del prefs[task_key]
                group['preferences'] = prefs
                changed = True
            if task_key in locks:
                del locks[task_key]
                group['locks'] = locks
                changed = True
            if not changed:
                return 0

            groups[active_group] = group
            preferences['groups'] = groups
            return UsersModel._save_preference_state(user_id, preferences)
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
  `phone` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '手机号',
  `email` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '邮箱',
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
  `commission_rate` decimal(5,4) NOT NULL DEFAULT '0.0000' COMMENT '邀请人佣金比例(0~0.5；0=关闭抽佣)',
  `first_recharge` tinyint DEFAULT '0' COMMENT '是否首次充值',
  `implementation_preferences` json DEFAULT NULL COMMENT '用户实现方偏好配置（groups.preferences / groups.locks）',
  `active_preference_group` int DEFAULT NULL COMMENT '当前激活的偏好组',
  `api_token` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用户API Token（智剧通接口授权）',
  `zjt_token_enabled` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否启用智剧通Token（0-未启用，1-已启用）',
  `zjt_token_expire_at` datetime DEFAULT NULL COMMENT '智剧通Token过期时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `idx_phone` (`phone`) USING BTREE,
  UNIQUE KEY `idx_email` (`email`) USING BTREE,
  UNIQUE KEY `idx_serial_number` (`serial_number`) USING BTREE,
  UNIQUE KEY `idx_api_token` (`api_token`),
  KEY `invite_code` (`invite_code`) USING BTREE,
  KEY `inviter_id` (`inviter_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表'
"""
