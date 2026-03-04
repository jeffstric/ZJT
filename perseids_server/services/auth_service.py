"""
AuthService 认证服务 - 对应Go的handler/auth.go
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import logging

from model.users import UsersModel, User
from model.user_tokens import UserTokensModel
from model.verify_codes import VerifyCodesModel
from model.computing_power import ComputingPowerModel
from model.computing_power_log import ComputingPowerLogModel
from model.login_log import LoginLogModel

from ..utils.token import generate_token, hash_password, verify_password, generate_secret_key
from ..utils.validator import validate_phone, validate_password

logger = logging.getLogger(__name__)


class AuthService:
    """认证服务 - 登录、注册、重置密码等"""
    
    # 常量
    DEFAULT_COMPUTING_POWER = 50  # 默认算力
    INVITE_BONUS_POWER = 75  # 邀请人奖励算力
    INVITED_USER_POWER = 75  # 被邀请人算力
    TOKEN_EXPIRE_DAYS = 30  # Token过期天数
    
    @staticmethod
    def login(
        phone: str,
        password: str,
        device_uuid: Optional[str] = None,
        terms_agreed: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        用户登录
        
        Args:
            phone: 手机号
            password: 密码
            device_uuid: 设备UUID
            terms_agreed: 是否同意条款
            ip_address: IP地址
            user_agent: 用户代理
            
        Returns:
            登录结果字典
        """
        # 验证手机号格式
        if not validate_phone(phone):
            return {"success": False, "message": "无效的手机号格式"}
        
        # 查找用户
        user = UsersModel.get_by_phone(phone)
        if not user:
            return {"success": False, "message": "用户不存在"}
        
        # 检查用户邀请码，没有则生成
        if not user.invite_code:
            try:
                invite_code = UsersModel.generate_unique_invite_code()
                from model.database import execute_update
                execute_update(
                    "UPDATE users SET invite_code = %s WHERE id = %s",
                    (invite_code, user.id)
                )
                user.invite_code = invite_code
            except Exception as e:
                logger.warning(f"生成邀请码失败: {e}")
        
        # 检查条款同意状态
        if terms_agreed is not None:
            if terms_agreed == 0 and user.terms_agreed == 0:
                return {"success": False, "message": "请阅读并同意AI工具服务使用条款"}
            
            if user.terms_agreed == 0 and terms_agreed == 1:
                from model.database import execute_update
                execute_update(
                    "UPDATE users SET terms_agreed = %s WHERE id = %s",
                    (terms_agreed, user.id)
                )
                user.terms_agreed = terms_agreed
        
        # 验证密码
        if not verify_password(password, user.password_hash):
            LoginLogModel.create(user.id, ip_address, user_agent, 0)
            return {"success": False, "message": "密码错误"}
        
        # 检查用户状态
        if user.status != 1:
            LoginLogModel.create(user.id, ip_address, user_agent, 0)
            return {"success": False, "message": "账户已被禁用"}
        
        # 生成token
        token = generate_token(user.id, device_uuid)
        expire_time = datetime.now() + timedelta(days=AuthService.TOKEN_EXPIRE_DAYS)
        
        # 删除旧token并创建新token
        UserTokensModel.delete_by_user_id(user.id)
        UserTokensModel.create(user.id, token, expire_time, device_uuid)
        
        # 记录登录日志
        LoginLogModel.create(user.id, ip_address, user_agent, 1)
        
        logger.info(f"用户登录成功 - ID: {user.id}, 手机号: {phone}")
        
        return {
            "success": True,
            "message": "登录成功",
            "data": {
                "user_id": user.id,
                "phone": user.phone,
                "status": user.status,
                "token": token,
                "invite_code": user.invite_code,
                "role": user.role,
                "terms_agreed": user.terms_agreed,
            }
        }
    
    @staticmethod
    def register(
        phone: str,
        password: str,
        verify_code: str,
        invite_code: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        用户注册
        
        Args:
            phone: 手机号
            password: 密码
            verify_code: 验证码
            invite_code: 邀请码（可选）
            ip_address: IP地址
            user_agent: 用户代理
            
        Returns:
            注册结果字典
        """
        # 验证手机号格式
        if not validate_phone(phone):
            return {"success": False, "message": "无效的手机号格式"}
        
        # 验证密码强度
        valid, msg = validate_password(password)
        if not valid:
            return {"success": False, "message": msg}
        
        # 检查手机号是否已注册
        existing_user = UsersModel.get_by_phone(phone)
        if existing_user:
            return {"success": False, "message": "该手机号已注册"}
        
        # 验证验证码 (register类型)
        if not VerifyCodesModel.verify(phone, verify_code, "register"):
            return {"success": False, "message": "验证码不正确或已过期"}
        
        # 检查邀请码
        inviter_id = None
        if invite_code:
            inviter = UsersModel.get_by_invite_code(invite_code)
            if not inviter:
                return {"success": False, "message": "无效邀请码"}
            inviter_id = inviter.id
        
        # 生成密码哈希
        password_hash = hash_password(password)
        
        # 生成用户邀请码
        user_invite_code = UsersModel.generate_unique_invite_code()
        
        # 生成密钥
        secret_key = generate_secret_key()
        
        # 判断是否是第一个用户，如果是则设为管理员
        total_count = UsersModel.get_total_count()
        is_first_user = total_count == 0
        user_role = "admin" if is_first_user else "user"
        logger.info(f"注册检查: 当前用户总数={total_count}, 是否首个用户={is_first_user}, 分配角色={user_role}")
        
        # 创建用户
        from model.database import execute_insert
        user_id = execute_insert(
            """INSERT INTO users (phone, password_hash, status, role, secret_key, invite_code, inviter_id) 
               VALUES (%s, %s, 1, %s, %s, %s, %s)""",
            (phone, password_hash, user_role, secret_key, user_invite_code, inviter_id)
        )
        
        # 删除验证码
        VerifyCodesModel.delete_by_phone(phone)
        
        # 设置初始算力
        new_user_power = AuthService.INVITED_USER_POWER if inviter_id else AuthService.DEFAULT_COMPUTING_POWER
        ComputingPowerModel.create(user_id, new_user_power, None)
        
        # 给邀请人增加算力
        if inviter_id:
            AuthService._add_inviter_reward(inviter_id, user_id)
        
        # 记录注册日志
        LoginLogModel.create(user_id, ip_address, user_agent, 1)
        
        logger.info(f"用户注册成功 - ID: {user_id}, 手机号: {phone}")
        
        return {
            "success": True,
            "message": "注册成功",
            "data": {
                "user_id": user_id,
                "phone": phone,
                "status": 1,
                "role": user_role,
                "is_first_admin": is_first_user,
            }
        }
    
    @staticmethod
    def _add_inviter_reward(inviter_id: int, new_user_id: int) -> None:
        """给邀请人增加奖励算力"""
        try:
            power = ComputingPowerModel.get_by_user_id(inviter_id)
            if power:
                new_power = power.computing_power + AuthService.INVITE_BONUS_POWER
                ComputingPowerModel.update(inviter_id, new_power)
                
                note = f"邀请奖励算力，被邀请人ID: {new_user_id}"
                ComputingPowerLogModel.create(
                    user_id=inviter_id,
                    behavior="increase",
                    computing_power=AuthService.INVITE_BONUS_POWER,
                    from_value=power.computing_power,
                    to_value=new_power,
                    note=note
                )
            else:
                # 邀请人没有算力记录，创建新记录
                initial_power = AuthService.DEFAULT_COMPUTING_POWER + AuthService.INVITE_BONUS_POWER
                ComputingPowerModel.create(inviter_id, initial_power, None)
                
                note = f"邀请奖励算力，被邀请人ID: {new_user_id}"
                ComputingPowerLogModel.create(
                    user_id=inviter_id,
                    behavior="increase",
                    computing_power=initial_power,
                    from_value=0,
                    to_value=initial_power,
                    note=note
                )
            
            logger.info(f"邀请人算力奖励成功 - 邀请人ID: {inviter_id}")
        except Exception as e:
            logger.error(f"给邀请人增加算力失败: {e}")
    
    @staticmethod
    def logout(token: str) -> Dict[str, Any]:
        """
        用户登出
        
        Args:
            token: 用户token
            
        Returns:
            登出结果
        """
        UserTokensModel.delete_by_token(token)
        return {"success": True, "message": "登出成功"}
    
    @staticmethod
    def reset_password(
        phone: str,
        new_password: str,
        verify_code: str
    ) -> Dict[str, Any]:
        """
        重置密码
        
        Args:
            phone: 手机号
            new_password: 新密码
            verify_code: 验证码
            
        Returns:
            重置结果
        """
        # 验证手机号格式
        if not validate_phone(phone):
            return {"success": False, "message": "无效的手机号格式"}
        
        # 验证密码强度
        valid, msg = validate_password(new_password)
        if not valid:
            return {"success": False, "message": msg}
        
        # 验证验证码 (reset_password类型)
        if not VerifyCodesModel.verify(phone, verify_code, "reset_password"):
            return {"success": False, "message": "验证码不正确或已过期"}
        
        # 查找用户
        user = UsersModel.get_by_phone(phone)
        if not user:
            return {"success": False, "message": "用户不存在"}
        
        # 更新密码
        password_hash = hash_password(new_password)
        UsersModel.update_password(user.id, password_hash)
        
        # 删除验证码
        VerifyCodesModel.delete_by_phone(phone)
        
        # 删除所有token，强制重新登录
        UserTokensModel.delete_by_user_id(user.id)
        
        logger.info(f"用户密码重置成功 - ID: {user.id}, 手机号: {phone}")
        
        return {"success": True, "message": "密码重置成功"}
    
    @staticmethod
    def verify_token(token: str) -> Optional[int]:
        """
        验证token并返回用户ID
        
        Args:
            token: 用户token
            
        Returns:
            用户ID或None
        """
        return UserTokensModel.get_user_id_by_token(token)
    
    @staticmethod
    def get_user_by_token(token: str) -> Optional[User]:
        """
        通过token获取用户信息
        
        Args:
            token: 用户token
            
        Returns:
            用户对象或None
        """
        user_id = UserTokensModel.get_user_id_by_token(token)
        if user_id:
            return UsersModel.get_by_id(user_id)
        return None
    
    @staticmethod
    def check_first_recharge(user_id: int) -> Dict[str, Any]:
        """
        查询用户首充状态
        
        Args:
            user_id: 用户ID
            
        Returns:
            首充状态
        """
        try:
            status = UsersModel.get_first_recharge_status(user_id)
            return {
                "success": True,
                "message": "查询成功",
                "data": {
                    "first_recharge": status,
                }
            }
        except Exception as e:
            logger.error(f"查询首充状态失败: {e}")
            return {"success": False, "message": "查询首充状态失败"}
    
    @staticmethod
    def update_first_recharge(user_id: int, status: int = 1) -> Dict[str, Any]:
        """
        更新用户首充状态
        
        Args:
            user_id: 用户ID
            status: 首充状态（0-未首充，1-已首充）
            
        Returns:
            更新结果
        """
        try:
            UsersModel.update_first_recharge_status(user_id, status)
            return {
                "success": True,
                "message": "首充状态更新成功",
                "data": {
                    "first_recharge": status,
                }
            }
        except Exception as e:
            logger.error(f"更新首充状态失败: {e}")
            return {"success": False, "message": "更新首充状态失败"}
    
    @staticmethod
    def get_auth_token_by_user_id(user_id: int) -> Dict[str, Any]:
        """
        根据用户ID获取认证token
        对应Go的GetAuthTokenByUserID
        
        Args:
            user_id: 用户ID
            
        Returns:
            token信息
        """
        try:
            token = UserTokensModel.get_token_by_user_id(user_id)
            if not token:
                return {"success": False, "message": "未找到有效的token"}
            
            return {
                "success": True,
                "message": "获取token成功",
                "data": {
                    "token": token,
                }
            }
        except Exception as e:
            logger.error(f"查询token失败: {e}")
            return {"success": False, "message": "查询token失败"}
    
    @staticmethod
    def create_token_log(
        user_id: int,
        input_token: Optional[int] = None,
        output_token: Optional[int] = None,
        cache_read: Optional[int] = None,
        cache_creation: Optional[int] = None,
        vendor_id: Optional[int] = None,
        model_id: Optional[int] = None,
        note: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建token日志
        对应Go的CreateTokenLog
        
        Args:
            user_id: 用户ID
            input_token: 输入token数
            output_token: 输出token数
            cache_read: 缓存读取数
            cache_creation: 缓存创建数
            vendor_id: 供应商ID（必填）
            model_id: 模型ID（必填）
            note: 备注
            
        Returns:
            创建结果
        """
        from model.token_log import TokenLogModel
        
        # 校验必填项
        if vendor_id is None:
            return {"success": False, "message": "vendor_id为必填项"}
        if model_id is None:
            return {"success": False, "message": "model_id为必填项"}
        
        try:
            TokenLogModel.create(
                user_id=user_id,
                input_token=input_token,
                output_token=output_token,
                cache_read=cache_read,
                cache_creation=cache_creation,
                vendor_id=vendor_id,
                model_id=model_id,
                note=note
            )
            return {
                "success": True,
                "message": "token日志创建成功"
            }
        except Exception as e:
            logger.error(f"创建token日志失败: {e}")
            return {"success": False, "message": "创建token日志失败"}
    
    @staticmethod
    def get_all_models(limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """
        获取所有模型
        对应Go的GetAllModels
        
        Args:
            limit: 限制数量
            offset: 偏移量
            
        Returns:
            模型列表
        """
        from model.model import ModelModel
        
        try:
            models = ModelModel.get_all(limit=limit, offset=offset)
            return {
                "success": True,
                "message": "查询成功",
                "data": {
                    "models": [m.to_dict() for m in models],
                    "limit": limit,
                    "offset": offset,
                }
            }
        except Exception as e:
            logger.error(f"查询模型数据失败: {e}")
            return {"success": False, "message": "查询模型数据失败"}
