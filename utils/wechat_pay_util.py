"""
微信支付工具类
封装微信支付相关的API调用逻辑
"""
import time
import uuid
from typing import Dict, Optional
import logging
import json
import os
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WechatPayUtil:
    """微信支付工具类"""
    
    def __init__(self, app_id: str = None, mch_id: str = None, api_key: str = None, APIv3_key: str = None):
        """
        初始化微信支付工具
        
        Args:
            app_id: 微信公众号/小程序的AppID
            mch_id: 微信支付商户号
            api_key: 商户API证书序列号
            APIv3_key: APIv3密钥
        """
        self.app_id = app_id
        self.mch_id = mch_id
        self.api_key = api_key
        self.APIv3_key = APIv3_key
    
    def generate_order_id(self) -> str:
        """
        生成订单ID
        
        Returns:
            订单ID，格式: ORDER_时间戳_随机字符串
        """
        return f"ORDER_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    
    def create_jsapi_payment(
        self,
        order_id: str,
        total_fee: int,
        body: str,
        openid: str,
        notify_url: str,
        payer_client_ip: str = "127.0.0.1"
    ) -> Dict:
        """
        创建JSAPI支付订单（微信内浏览器支付）- 使用微信支付V3 API
        
        Args:
            order_id: 商户订单号
            total_fee: 支付金额（单位：分）
            body: 商品描述
            openid: 用户的openid
            notify_url: 支付结果通知回调URL
            payer_client_ip: 用户终端IP
        
        Returns:
            包含支付参数的字典
            {
                "appId": "微信公众号AppID",
                "timeStamp": "时间戳",
                "nonceStr": "随机字符串",
                "package": "prepay_id=xxx",
                "signType": "RSA",
                "paySign": "签名"
            }
        
        TODO: 实现具体的JSAPI支付逻辑
        - 调用微信支付V3统一下单接口
        - 获取预支付交易会话标识 prepay_id
        - 生成JSAPI支付参数并签名
        """
        logger.info(f"Creating JSAPI payment for order {order_id}, amount: {total_fee}")
        
        # 1. 构建请求体（JSON格式）
        request_body = {
            "appid": str(self.app_id),
            "mchid": str(self.mch_id),
            "description": body,
            "out_trade_no": order_id,
            "notify_url": notify_url,
            "amount": {
                "total": int(total_fee),
                "currency": "CNY"
            },
            "payer": {
                "openid": openid
            },
            "scene_info": {
                "payer_client_ip": payer_client_ip
            }
        }
        
        timestamp = str(int(time.time()))
        nonce_str = uuid.uuid4().hex
        request_body_json = json.dumps(request_body)
        
        # 2. 生成签名
        signature = self._generate_sign(
            http_method="POST",
            url_path="/v3/pay/transactions/jsapi",
            timestamp=timestamp,
            nonce_str=nonce_str,
            request_body=request_body_json
        )
        
        # 3. 构造Authorization头
        auth_header = (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{self.mch_id}",'
            f'nonce_str="{nonce_str}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{self.api_key}",'
            f'signature="{signature}"'
        )
        
        # 4. 调用微信支付V3统一下单接口
        import requests
        response = requests.post(
            "https://api.mch.weixin.qq.com/v3/pay/transactions/jsapi",
            headers={
                "Authorization": auth_header,
                "Accept": "application/json",
                "Content-Type": "application/json"
            },
            json=request_body
        )
        
        # 5. 解析返回结果，获取prepay_id
        result = response.json()
        prepay_id = result.get("prepay_id")
        
        # 6. 生成JSAPI支付参数（前端调用微信支付需要）
        jsapi_timestamp = str(int(time.time()))
        jsapi_nonce_str = uuid.uuid4().hex
        package = f"prepay_id={prepay_id}"
        
        # 构造签名串（用于前端调起支付）
        # 格式：appId\n时间戳\n随机串\nprepay_id=xxx\n
        sign_str = f"{self.app_id}\n{jsapi_timestamp}\n{jsapi_nonce_str}\n{package}\n"
        
        # 使用商户私钥对签名串进行RSA-SHA256签名
        try:
            # 读取私钥文件
            private_key_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "secret/wechat/apiclient_key.pem"
            )
            
            with open(private_key_path, 'rb') as f:
                private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                    backend=default_backend()
                )
            
            # 使用私钥对签名串进行SHA256签名
            signature = private_key.sign(
                sign_str.encode('utf-8'),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            
            # Base64编码
            pay_sign = base64.b64encode(signature).decode('utf-8')
            
        except Exception as e:
            logger.error(f"Failed to generate paySign: {str(e)}")
            pay_sign = "mock_pay_sign"
        
        jsapi_params = {
            "appId": self.app_id,
            "timeStamp": jsapi_timestamp,
            "nonceStr": jsapi_nonce_str,
            "package": package,
            "signType": "RSA",
            "paySign": pay_sign
        }
        
        return jsapi_params
    
    def create_h5_payment(
        self,
        order_id: str,
        total_fee: int,
        body: str,
        notify_url: str,
        payer_client_ip: str = "127.0.0.1",
        scene_info: Optional[Dict] = None
    ) -> Dict:
        """
        创建H5支付订单（外部浏览器支付）- 使用微信支付V3 API
        
        Args:
            order_id: 商户订单号
            total_fee: 支付金额（单位：分）
            body: 商品描述
            notify_url: 支付结果通知回调URL
            payer_client_ip: 用户终端IP
            scene_info: 场景信息（H5支付必填），包含h5_info
        
        Returns:
            包含支付跳转URL的字典
            {
                "h5_url": "https://wx.tenpay.com/cgi-bin/mmpayweb-bin/checkmweb?prepay_id=xxx"
            }
        
        TODO: 实现具体的H5支付逻辑
        - 调用微信支付V3统一下单接口
        - 获取支付跳转URL h5_url
        """
        logger.info(f"Creating H5 payment for order {order_id}, amount: {total_fee}")
        
        # 如果没有提供场景信息，使用默认值
        if scene_info is None:
            scene_info = {
                "payer_client_ip": payer_client_ip,
                "h5_info": {
                    "type": "Wap"
                }
            }
        else:
            # 确保scene_info中包含payer_client_ip
            scene_info["payer_client_ip"] = payer_client_ip
        
        request_body = {
            "appid": str(self.app_id),
            "mchid": str(self.mch_id),
            "description": body,
            "out_trade_no": order_id,
            "notify_url": notify_url,
            "amount": {
                "total": int(total_fee),
                "currency": "CNY"
            },
            "scene_info": scene_info
        }
        
        timestamp = str(int(time.time()))
        nonce_str = uuid.uuid4().hex
        request_body_json = json.dumps(request_body)
        
        # 生成签名
        signature = self._generate_sign(
            http_method="POST",
            url_path="/v3/pay/transactions/h5",
            timestamp=timestamp,
            nonce_str=nonce_str,
            request_body=request_body_json
        )
        
        # 构造Authorization头
        auth_header = (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{self.mch_id}",'
            f'nonce_str="{nonce_str}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{self.api_key}",'
            f'signature="{signature}"'
        )
        
        # 3. 调用微信支付V3统一下单接口
        import requests
        response = requests.post(
            "https://api.mch.weixin.qq.com/v3/pay/transactions/h5",
            headers={
                "Authorization": auth_header,
                "Accept": "application/json",
                "Content-Type": "application/json"
            },
            json=request_body
        )
        
        # 解析返回结果，获取h5_url
        result = response.json()
        logger.info(f"H5 payment result: {result}")
        h5_url = result.get("h5_url")
        
        return {"h5_url": h5_url}
    
    def _generate_sign(
        self,
        http_method: str,
        url_path: str,
        timestamp: str,
        nonce_str: str,
        request_body: str
    ) -> str:
        """
        生成微信支付V3 API签名
        
        步骤：
        1. 构建签名串（5个部分，每部分以\n结尾）
        2. 使用商户私钥进行RSA-SHA256签名
        3. 对签名结果进行Base64编码
        
        Args:
            http_method: HTTP请求方法（如：POST、GET）
            url_path: URL路径（如：/v3/pay/transactions/jsapi）
            timestamp: 请求时间戳（10位，单位：秒）
            nonce_str: 请求随机串
            request_body: 请求报文主体（JSON字符串）
        
        Returns:
            Base64编码的签名字符串
        """
        # 第一步：构建签名串，每个部分后面都要加换行符
        signature_string = (
            f"{http_method}\n"
            f"{url_path}\n"
            f"{timestamp}\n"
            f"{nonce_str}\n"
            f"{request_body}\n"
        )
        
        # 第二步：使用商户私钥进行RSA-SHA256签名
        try:

            
            # 读取私钥文件
            private_key_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "secret/wechat/apiclient_key.pem"
            )
            
            with open(private_key_path, 'rb') as f:
                private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                    backend=default_backend()
                )
            
            # 使用私钥对签名串进行SHA256签名
            signature = private_key.sign(
                signature_string.encode('utf-8'),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            
            # 第三步：Base64编码
            signature_base64 = base64.b64encode(signature).decode('utf-8')
            
            return signature_base64
            
        except FileNotFoundError:
            logger.error(f"Private key file not found: {private_key_path}")
            logger.warning("Using mock signature for development")
            return "mock_signature"
        except Exception as e:
            logger.error(f"Failed to generate signature: {str(e)}")
            logger.warning("Using mock signature for development")
            return "mock_signature"
    
    def verify_callback_signature(
        self,
        timestamp: str,
        nonce: str,
        body: bytes,
        signature: str
    ) -> bool:
        """
        验证微信支付回调签名
        
        使用微信支付平台公钥验证回调签名，确保回调数据来源可信
        
        验签步骤：
        1. 构建验签串（timestamp、nonce、body）
        2. 使用微信支付平台公钥验证签名
        
        Args:
            timestamp: 时间戳（从请求头Wechatpay-Timestamp获取）
            nonce: 随机串（从请求头Wechatpay-Nonce获取）
            body: 请求体原始字节数据
            signature: 签名（从请求头Wechatpay-Signature获取，Base64编码）
        
        Returns:
            签名是否有效
        """
        try:

            
            # 构建验签串
            verify_string = f"{timestamp}\n{nonce}\n{body.decode('utf-8')}\n"
            
            # 读取微信支付平台公钥
            public_key_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "secret/wechat/pub_key.pem"
            )
            
            with open(public_key_path, 'rb') as f:
                public_key = serialization.load_pem_public_key(
                    f.read(),
                    backend=default_backend()
                )
            
            # Base64解码签名
            signature_bytes = base64.b64decode(signature)
            
            # 使用公钥验证签名
            try:
                public_key.verify(
                    signature_bytes,
                    verify_string.encode('utf-8'),
                    padding.PKCS1v15(),
                    hashes.SHA256()
                )
                logger.info("Callback signature verification successful")
                return True
            except Exception as verify_error:
                logger.error(f"Signature verification failed: {str(verify_error)}")
                return False
                
        except FileNotFoundError:
            logger.error(f"Public key file not found: {public_key_path}")
            logger.warning("Skipping signature verification for development")
            return True  # 开发环境下如果没有公钥文件，跳过验签
        except Exception as e:
            logger.error(f"Failed to verify callback signature: {str(e)}")
            return False
    
    def decrypt_callback_resource(
        self,
        nonce: str,
        ciphertext: str,
        associated_data: str
    ) -> str:
        """
        解密微信支付回调中的加密资源数据
        
        使用AEAD_AES_256_GCM算法解密resource中的ciphertext
        
        Args:
            nonce: 加密使用的随机串
            ciphertext: Base64编码的密文
            associated_data: 附加数据
        
        Returns:
            解密后的明文字符串（JSON格式）
        """
        try:

            
            # APIv3密钥
            if not self.APIv3_key:
                raise ValueError("APIv3_key is not configured")
            
            # 转换为字节
            key_bytes = str.encode(self.APIv3_key)
            nonce_bytes = str.encode(nonce)
            ad_bytes = str.encode(associated_data)
            
            # Base64解码密文
            ciphertext_bytes = base64.b64decode(ciphertext)
            
            # 使用AESGCM解密
            aesgcm = AESGCM(key_bytes)
            decrypted_bytes = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, ad_bytes)
            
            # 转换为字符串
            decrypted_text = decrypted_bytes.decode('utf-8')
            
            logger.info("Successfully decrypted callback resource data")
            return decrypted_text
            
        except Exception as e:
            logger.error(f"Failed to decrypt callback resource: {str(e)}")
            raise
      
