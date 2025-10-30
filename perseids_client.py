import logging
import requests
import traceback
import hmac
import hashlib
import time
import secrets
import json
import os
import yaml
from urllib.parse import quote_plus
from config_util import get_config_path
import platform
import subprocess
import uuid as uuid_module

logger = logging.getLogger(__name__)

# 预共享的密钥（需与服务器端一致）
SECRET_KEY = "7LVmHyyj2UTu"

# Load authentication URL from config
APP_DIR = os.path.dirname(os.path.abspath(__file__))
config_file = get_config_path()
with open(os.path.join(APP_DIR, config_file), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
BASE_URL = config["authentication"]["url"]

def generate_signature(data, timestamp, nonce):
    """
    生成签名
    :param data: dict 请求数据
    :param timestamp: int 时间戳
    :param nonce: str 随机字符串
    :return: str 签名
    """
    logger.debug("开始生成签名...")
    logger.debug(f"原始数据: {data}")
    logger.debug(f"时间戳: {timestamp}")
    logger.debug(f"随机数: {nonce}")

    # 将请求参数按字典序排序
    sorted_keys = sorted(data.keys())
    logger.debug(f"排序后的键: {sorted_keys}")
    
    # 构建参数对并进行 URL 编码
    pairs = []
    for k in sorted_keys:
        # 将值转换为字符串
        v = data[k]
        original_v = v
        if isinstance(v, bool):
            v = str(v).lower()
        elif isinstance(v, (int, float)):
            v = str(v)
        elif not isinstance(v, str):
            # 对于其他类型，尝试 JSON 序列化
            try:
                v = json.dumps(v)
            except:
                v = str(v)
        
        logger.debug(f"处理键值对 - 键: {k}, 原始值: {original_v}, 转换后: {v}")
        
        # URL 编码 key 和 value (使用 quote_plus 匹配 Go 的 url.QueryEscape 行为)
        k = quote_plus(str(k))
        v = quote_plus(str(v))
        pair = f"{k}={v}"
        logger.debug(f"URL编码后的键值对: {pair}")
        pairs.append(pair)
    
    # 拼接参数字符串
    data_str = "&".join(pairs)
    logger.debug(f"参数字符串: {data_str}")
    
    # 拼接签名字符串
    sign_str = f"{data_str}&timestamp={timestamp}&nonce={nonce}"
    logger.debug(f"完整签名字符串: {sign_str}")
    
    # 使用 HMAC-SHA256 生成签名
    signature = hmac.new(
        SECRET_KEY.encode('utf-8'),
        sign_str.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    logger.debug(f"最终签名: {signature}")
    return signature


def make_perseids_request(endpoint=None, data=None, method='POST', headers=None):
    """
    向 Go 服务器发起请求
    :param endpoint: str 接口路径
    :param data: dict 请求数据
    :param method: str 请求方法
    :param headers: dict 请求头
    :return: tuple (bool, str, dict) 是否成功，消息，响应数据
    """
    try:
        timeout = 30
        
        # 构建认证 URL，已含有添加 api/v1 前缀
        auth_url = f"{BASE_URL}/{endpoint}"
        logger.info(f"调用认证服务器 URL: {auth_url}")
        
        # 生成签名所需参数
        timestamp = int(time.time())
        nonce = secrets.token_hex(16)
        
        # 构建请求数据
        payload = data or {}
        logger.debug(f"请求数据: {payload}")
        
        # 生成签名
        signature = generate_signature(payload, timestamp, nonce)
        
        # 构建请求头
        request_headers = headers or {}
        request_headers.update({
            'X-Timestamp': str(timestamp),
            'X-Nonce': nonce,
            'X-Signature': signature
        })
        logger.debug(f"请求头: {request_headers}")
        
        response = requests.request(method, auth_url, json=payload, headers=request_headers, timeout=timeout)
        logger.debug(f"响应状态码: {response.status_code}")
        logger.debug(f"响应内容: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            return data.get('success', False), data.get('message', ''), data.get('data', {})
        else:
            # 尝试解析错误响应
            try:
                error_data = response.json()
                error_message = error_data.get('message', '未知错误')
            except:
                error_message = f'服务器错误 ({response.status_code}): {response.text}'
            
            logger.error(f'认证服务器返回错误: {error_message}')
            return False, error_message, { }

    except Exception as e:
        logger.error(f'调用认证服务器时发生错误: {str(e)}')
        logger.error(traceback.format_exc())
        return False, '服务器内部错误', {}

def call_external_auth_server(phone, password, device_uuid=None, auth_type='login', extra_data=None):
    """
    调用外部认证服务器
    :param phone: 手机号
    :param password: 密码
    :param device_uuid: 设备UUID
    :param auth_type: 认证类型，'login' 或 'register'
    :param extra_data: 额外数据
    :return: (bool, str, dict) 是否成功，消息，数据
    """
    # 构建请求数据
    payload = {
        'phone': phone,
        'password': password,
        'device_uuid': device_uuid
    }
    
    if extra_data:
        logger.debug(f"调用认证服务器 包含extra_data: {extra_data}")
        payload.update(extra_data)

    logger.debug(f"调用认证服务器 参数: {payload}")
    return make_perseids_request(auth_type, payload)

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

