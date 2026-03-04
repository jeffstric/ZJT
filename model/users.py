"""
Users Model - Database operations for users table
对应Go的models/users.go
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging
import random
import string

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
            SELECT id, phone, status, role, created_at, updated_at, invite_code, inviter_id, first_recharge
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
