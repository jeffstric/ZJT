import logging
import traceback
import os
import platform
import subprocess
import uuid as uuid_module
import asyncio

from perseids_server.services.auth_service import AuthService
from perseids_server.services.computing_power_service import ComputingPowerService
from perseids_server.services.verify_code_service import VerifyCodeService

logger = logging.getLogger(__name__)

def _extract_token_from_headers(headers: dict) -> str:
    """
    从请求头中提取token
    """
    if not headers:
        return None
    auth_header = headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    return auth_header


def make_perseids_request(endpoint=None, data=None, method='POST', headers=None):
    """
    内部认证服务请求（同步版本）
    :param endpoint: str 接口路径
    :param data: dict 请求数据
    :param method: str 请求方法
    :param headers: dict 请求头
    :return: tuple (bool, str, dict) 是否成功，消息，响应数据
    """
    try:
        token = _extract_token_from_headers(headers)
        payload = data or {}
        logger.debug(f"内部认证请求: {endpoint}, 数据: {payload}")
        
        # 根据endpoint路由到对应的内部服务
        if endpoint == 'user/check_computing_power':
            user_id = AuthService.verify_token(token)
            if not user_id:
                return False, '无效的认证信息', {}
            result = ComputingPowerService.check_computing_power(user_id)
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif endpoint == 'user/calculate_computing_power':
            user_id = AuthService.verify_token(token)
            if not user_id:
                return False, '无效的认证信息', {}
            result = ComputingPowerService.calculate_computing_power(
                user_id=user_id,
                computing_power=payload.get('computing_power', 0),
                behavior=payload.get('behavior', 'deduct'),
                transaction_id=payload.get('transaction_id', ''),
                message=payload.get('message'),
                note=payload.get('note')
            )
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif endpoint == 'user/computing_power_logs':
            user_id = AuthService.verify_token(token)
            if not user_id:
                return False, '无效的认证信息', {}
            result = ComputingPowerService.get_computing_power_logs(
                user_id=user_id,
                limit=payload.get('page_size', 20),
                offset=(payload.get('page', 1) - 1) * payload.get('page_size', 20),
                behavior=payload.get('behavior')
            )
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif endpoint == 'user/invitation_reward_stats':
            user_id = AuthService.verify_token(token)
            if not user_id:
                return False, '无效的认证信息', {}
            result = ComputingPowerService.get_invitation_reward_stats(user_id)
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif endpoint == 'user/get_user_id_by_auth_token':
            user_id = AuthService.verify_token(token)
            if user_id:
                return True, '获取成功', {'user_id': user_id}
            return False, '无效的认证信息', {}
        
        elif endpoint == 'user/check_first_recharge':
            user_id = AuthService.verify_token(token)
            if not user_id:
                return False, '无效的认证信息', {}
            result = AuthService.check_first_recharge(user_id)
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif endpoint == 'user/update_first_recharge':
            user_id = AuthService.verify_token(token)
            if not user_id:
                return False, '无效的认证信息', {}
            result = AuthService.update_first_recharge(user_id, payload.get('status', 1))
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif endpoint == 'send_verify_code':
            result = VerifyCodeService.create_verify_code(
                phone=payload.get('phone'),
                code_type=payload.get('type', 'register')
            )
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif endpoint == 'auth/logout':
            result = AuthService.logout(token)
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif endpoint == 'get_auth_token_by_user_id':
            result = AuthService.get_auth_token_by_user_id(
                user_id=payload.get('user_id')
            )
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif endpoint == 'user/token_log':
            user_id = AuthService.verify_token(token)
            if not user_id:
                return False, '无效的认证信息', {}
            result = AuthService.create_token_log(
                user_id=user_id,
                input_token=payload.get('input_token'),
                output_token=payload.get('output_token'),
                cache_read=payload.get('cache_read'),
                cache_creation=payload.get('cache_creation'),
                vendor_id=payload.get('vendor_id'),
                model_id=payload.get('model_id'),
                note=payload.get('note')
            )
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif endpoint == 'user/models':
            result = AuthService.get_all_models(
                limit=payload.get('limit', 50),
                offset=payload.get('offset', 0)
            )
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        else:
            logger.warning(f"未知的endpoint: {endpoint}")
            return False, f'未知的接口: {endpoint}', {}

    except Exception as e:
        logger.error(f'内部认证服务调用失败: {str(e)}')
        logger.error(traceback.format_exc())
        return False, '服务器内部错误', {}

async def async_make_perseids_request(endpoint=None, data=None, method='POST', headers=None):
    """
    内部认证服务请求（异步非阻塞版本）
    使用 asyncio.to_thread 包装同步服务调用，避免阻塞事件循环
    :param endpoint: str 接口路径
    :param data: dict 请求数据
    :param method: str 请求方法
    :param headers: dict 请求头
    :return: tuple (bool, str, dict) 是否成功，消息，响应数据
    """
    return await asyncio.to_thread(make_perseids_request, endpoint, data, method, headers)


async def async_call_external_auth_server(phone, password, device_uuid=None, auth_type='login', extra_data=None):
    """
    内部认证服务调用（异步非阻塞版本）
    :param phone: 手机号
    :param password: 密码
    :param device_uuid: 设备UUID
    :param auth_type: 认证类型，'login', 'register' 或 'reset_password'
    :param extra_data: 额外数据
    :return: (bool, str, dict) 是否成功，消息，数据
    """
    return await asyncio.to_thread(
        call_external_auth_server, phone, password, device_uuid, auth_type, extra_data
    )


def call_external_auth_server(phone, password, device_uuid=None, auth_type='login', extra_data=None):
    """
    内部认证服务调用（同步版本）
    :param phone: 手机号
    :param password: 密码
    :param device_uuid: 设备UUID
    :param auth_type: 认证类型，'login', 'register' 或 'reset_password'
    :param extra_data: 额外数据
    :return: (bool, str, dict) 是否成功，消息，数据
    """
    try:
        extra = extra_data or {}
        logger.debug(f"内部认证调用: {auth_type}, phone: {phone}")
        
        if auth_type == 'login':
            result = AuthService.login(
                phone=phone,
                password=password,
                device_uuid=device_uuid,
                terms_agreed=extra.get('terms_agreed')
            )
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif auth_type == 'register':
            result = AuthService.register(
                phone=phone,
                password=password,
                verify_code=extra.get('code'),
                invite_code=extra.get('invite_code')
            )
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        elif auth_type == 'reset_password':
            result = AuthService.reset_password(
                phone=phone,
                new_password=password,
                verify_code=extra.get('code')
            )
            return result.get('success', False), result.get('message', ''), result.get('data', {})
        
        else:
            logger.warning(f"未知的认证类型: {auth_type}")
            return False, f'未知的认证类型: {auth_type}', {}

    except Exception as e:
        logger.error(f'内部认证服务调用失败: {str(e)}')
        logger.error(traceback.format_exc())
        return False, '服务器内部错误', {}

def get_device_uuid():
    """
    获取设备UUID（跨平台支持）
    :return: str 设备UUID
    """
    try:
        system = platform.system()
        
        if system == "Windows":
            # Windows: 使用wmic命令获取UUID
            try:
                result = subprocess.check_output(
                    "wmic csproduct get uuid",
                    shell=True,
                    text=True,
                    stderr=subprocess.DEVNULL
                ).strip()
                lines = result.split('\n')
                if len(lines) >= 2:
                    device_uuid = lines[1].strip()
                    if device_uuid and device_uuid != "UUID":
                        return device_uuid
            except Exception as e:
                logger.warning(f"Windows UUID获取失败: {e}")
        
        elif system == "Linux":
            # Linux: 尝试从 /etc/machine-id 或 /var/lib/dbus/machine-id 读取
            machine_id_paths = [
                "/etc/machine-id",
                "/var/lib/dbus/machine-id"
            ]
            for path in machine_id_paths:
                try:
                    if os.path.exists(path):
                        with open(path, 'r') as f:
                            machine_id = f.read().strip()
                            if machine_id:
                                # 将machine-id转换为UUID格式
                                return str(uuid_module.UUID(machine_id))
                except Exception as e:
                    logger.warning(f"读取 {path} 失败: {e}")
            
            # 备选方案：尝试使用dmidecode（需要root权限）
            try:
                result = subprocess.check_output(
                    ["dmidecode", "-s", "system-uuid"],
                    text=True,
                    stderr=subprocess.DEVNULL
                ).strip()
                if result:
                    return result
            except Exception as e:
                logger.warning(f"dmidecode UUID获取失败: {e}")
        
        elif system == "Darwin":  # macOS
            try:
                result = subprocess.check_output(
                    ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                    text=True,
                    stderr=subprocess.DEVNULL
                )
                for line in result.split('\n'):
                    if "IOPlatformUUID" in line:
                        device_uuid = line.split('"')[3]
                        return device_uuid
            except Exception as e:
                logger.warning(f"macOS UUID获取失败: {e}")
        
        # 如果所有方法都失败，生成一个基于MAC地址的UUID
        logger.warning("无法获取硬件UUID，使用MAC地址生成UUID")
        mac = uuid_module.getnode()
        return str(uuid_module.uuid5(uuid_module.NAMESPACE_DNS, str(mac)))
        
    except Exception as e:
        logger.error(f"获取设备UUID失败: {e}")
        # 最后的备选方案：生成随机UUID
        return str(uuid_module.uuid4())

