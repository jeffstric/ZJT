"""
微信委托代扣（PAPay·周期扣费）工具类
封装月度订阅所需的 V2 XML 接口 + V3 混用接口（预扣费通知）

接口清单（微信支付委托代扣-周期扣费）：
  - 支付中签约   POST /pay/contractorder        （V2 XML，首期：支付+签约一步完成）
  - 申请扣款     POST /pay/pappayapply          （V2 XML，续期扣款）
  - 查询签约关系 POST /papay/querycontract      （V2 XML）
  - 申请解约     POST /papay/deletecontract     （V2 XML）
  - 查询订单     POST /pay/orderquery           （V2 XML，通用查单）
  - 预扣费通知   POST /v3/papay/contracts/{contract_id}/notify （V3 JSON）

签名规则：
  - V2 XML：MD5（参数 ASCII 升序 k=v& 拼接，排除 sign/空值，末尾 &key=APIv2密钥，结果大写）
  - V3 JSON：WECHATPAY2-SHA256-RSA2048（复用 utils/wechat_pay_util.py 的 RSA 签名）

注意：本类方法均为同步阻塞函数（requests），web 接口调用时必须用 asyncio.to_thread 包装。
"""
import time
import uuid
import hashlib
import logging
import xml.etree.ElementTree as ET
from typing import Dict, Optional, Tuple
import json
import requests

from config.constant import SubscriptionConstants

logger = logging.getLogger(__name__)

# 微信支付 V2 XML 网关
WX_API_BASE = "https://api.mch.weixin.qq.com"


def _xml_cdata(value) -> str:
    """构造 V2 XML 节点文本（统一 CDATA 包裹，规避中文/特殊字符转义问题）"""
    return f"<![CDATA[{value}]]>"


def dict_to_xml(params: Dict) -> str:
    """dict -> V2 XML 请求报文（不含 sign 字段时由调用方先行剔除）"""
    items = []
    for k, v in params.items():
        if v is None:
            continue
        items.append(f"<{k}>{_xml_cdata(v)}</{k}>")
    return f"<xml>{''.join(items)}</xml>"


def xml_to_dict(xml_text: str) -> Dict:
    """V2 XML 报文 -> dict（回调解析用；Python xml.etree 不解析外部实体，无 XXE 风险）"""
    try:
        root = ET.fromstring(xml_text)
        return {child.tag: (child.text or "").strip() for child in root}
    except ET.ParseError as e:
        logger.error(f"Failed to parse wechat xml: {e}")
        return {}


class WxPapayUtil:
    """微信委托代扣（周期扣费）工具类"""

    def __init__(
        self,
        app_id: str,
        mch_id: str,
        api_v2_key: str,
        plan_template_id: str,
        v3_authorization_builder=None,
    ):
        """
        Args:
            app_id: 公众号/小程序 AppID
            mch_id: 微信支付商户号
            api_v2_key: V2 API 密钥（32位，XML 报文 MD5 签名用；为空时验签降级跳过）
            plan_template_id: 商户平台「委托代扣协议模板」ID（hardcode 配置）
            v3_authorization_builder: 可调用对象 (http_method, url_path, body) -> Authorization头，
                由 WechatPayUtil.generate_v3_authorization 提供（预扣费通知 V3 接口用）
        """
        self.app_id = app_id
        self.mch_id = mch_id
        self.api_v2_key = api_v2_key
        self.plan_template_id = plan_template_id
        self._v3_authorization_builder = v3_authorization_builder

    # ==================== V2 签名/验签 ====================

    def _sign_v2(self, params: Dict) -> str:
        """
        V2 MD5 签名：参数 ASCII 升序 k=v& 拼接（排除 sign/空值），末尾 &key=密钥，MD5 后大写
        """
        filtered = {
            k: v for k, v in params.items()
            if k != "sign" and v is not None and str(v) != ""
        }
        sorted_str = "&".join(f"{k}={filtered[k]}" for k in sorted(filtered))
        sign_str = f"{sorted_str}&key={self.api_v2_key}"
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    def verify_v2_sign(self, params: Dict) -> bool:
        """
        验证 V2 回调签名

        ⚠️ api_v2_key 未配置时跳过验签（返回 True 并告警），仅限开发联调；
           生产环境必须配置 V2 密钥，否则攻击者可伪造回调。
        """
        if not self.api_v2_key:
            logger.warning("api_v2_key 未配置，跳过 V2 回调验签（仅限开发环境！）")
            return True
        received = params.get("sign")
        if not received:
            return False
        expected = self._sign_v2(params)
        return expected == received.upper()

    # ==================== HTTP 基础 ====================

    def _post_xml(self, url_path: str, params: Dict) -> Dict:
        """发送 V2 XML 请求并解析响应（含签名注入）"""
        params = dict(params)
        params.setdefault("appid", self.app_id)
        params.setdefault("mch_id", self.mch_id)
        params.setdefault("nonce_str", uuid.uuid4().hex[:32])
        params["sign"] = self._sign_v2(params)

        url = f"{WX_API_BASE}{url_path}"
        resp = requests.post(
            url,
            data=dict_to_xml(params).encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"},
            timeout=SubscriptionConstants.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        # 微信 V2 响应头可能不带 charset，requests 会按 ISO-8859-1 解码导致中文乱码、验签失败，须显式 UTF-8
        result = xml_to_dict(resp.content.decode("utf-8"))
        logger.info(f"WxPapay {url_path} response: return_code={result.get('return_code')}, "
                    f"result_code={result.get('result_code')}, err={result.get('err_code')}")
        return result

    @staticmethod
    def _is_success(result: Dict) -> bool:
        return result.get("return_code") == "SUCCESS" and result.get("result_code") == "SUCCESS"

    # ==================== 业务接口 ====================

    def create_contract_order(
        self,
        order_id: str,
        total_fee: int,
        body: str,
        contract_code: str,
        contract_display_account: str,
        notify_url: str,
        contract_notify_url: str,
        trade_type: str = "NATIVE",
        openid: Optional[str] = None,
        product_id: Optional[str] = None,
        client_ip: str = "127.0.0.1",
    ) -> Dict:
        """
        支付中签约（首期）：用户支付的同时完成代扣协议签约
        对应文档：/pay/contractorder

        Args:
            order_id: 商户订单号（32字符内）
            total_fee: 金额（分）
            body: 商品描述
            contract_code: 商户侧签约协议号（唯一，仅数字/大小写字母）
            contract_display_account: 签约页展示的开通账号（不支持表情）
            notify_url: 支付结果回调
            contract_notify_url: 签约结果回调
            trade_type: NATIVE（扫码）/ JSAPI（微信内）
            openid: trade_type=JSAPI 时必填
            product_id: trade_type=NATIVE 时必填（二维码商品ID）
            client_ip: 用户终端IP

        Returns:
            微信响应 dict（成功时含 prepay_id / code_url）
        """
        params = {
            "contract_mchid": self.mch_id,
            "contract_appid": self.app_id,
            "out_trade_no": order_id,
            "body": body,
            "notify_url": notify_url,
            "total_fee": int(total_fee),
            "spbill_create_ip": client_ip,
            "trade_type": trade_type,
            "plan_id": self.plan_template_id,
            "contract_code": contract_code,
            "request_serial": int(time.time() * 1000),
            "contract_display_account": contract_display_account,
            "contract_notify_url": contract_notify_url,
        }
        if trade_type == "JSAPI":
            params["openid"] = openid
        elif trade_type == "NATIVE":
            params["product_id"] = product_id or contract_code
        return self._post_xml("/pay/contractorder", params)

    def build_jsapi_pay_params(self, prepay_id: str) -> Dict:
        """
        依据 V2 prepay_id 生成 JSAPI 调起支付参数（paySign 为 V2 MD5 签名）

        Args:
            prepay_id: 支付中签约接口返回的预支付会话ID（有效期2小时）

        Returns:
            {appId, timeStamp, nonceStr, package, signType, paySign}
        """
        params = {
            "appId": self.app_id,
            "timeStamp": str(int(time.time())),
            "nonceStr": uuid.uuid4().hex[:32],
            "package": f"prepay_id={prepay_id}",
            "signType": "MD5",
        }
        params["paySign"] = self._sign_v2(params)
        return params

    def apply_deduct(
        self,
        order_id: str,
        total_fee: int,
        body: str,
        contract_id: str,
        notify_url: str,
        client_ip: str = "127.0.0.1",
    ) -> Dict:
        """
        申请扣款（续期）：按已签约协议发起委托代扣
        对应文档：/pay/pappayapply

        Returns:
            微信响应 dict（受理成功仅表示已受理，结果以回调/查单为准）
        """
        params = {
            "out_trade_no": order_id,
            "body": body,
            "total_fee": int(total_fee),
            "notify_url": notify_url,
            "trade_type": "PAP",
            "contract_id": contract_id,
            "spbill_create_ip": client_ip,
        }
        return self._post_xml("/pay/pappayapply", params)

    def query_contract(
        self,
        contract_code: Optional[str] = None,
        contract_id: Optional[str] = None,
    ) -> Dict:
        """
        查询签约关系：contract_id 或 plan_id+contract_code 二选一
        对应文档：/papay/querycontract
        返回 contract_state：0=已签约 1=未签约 9=签约进行中
        """
        params = {"version": "1.0"}
        if contract_id:
            params["contract_id"] = contract_id
        else:
            params["plan_id"] = self.plan_template_id
            params["contract_code"] = contract_code
        return self._post_xml("/papay/querycontract", params)

    def delete_contract(
        self,
        remark: str,
        contract_id: Optional[str] = None,
        contract_code: Optional[str] = None,
    ) -> Dict:
        """
        申请解约：contract_id 或 plan_id+contract_code 二选一
        对应文档：/papay/deletecontract
        """
        params = {
            "version": "1.0",
            "contract_termination_remark": remark,
        }
        if contract_id:
            params["contract_id"] = contract_id
        else:
            params["plan_id"] = self.plan_template_id
            params["contract_code"] = contract_code
        return self._post_xml("/papay/deletecontract", params)

    def query_order(self, out_trade_no: Optional[str] = None, transaction_id: Optional[str] = None) -> Dict:
        """
        查询订单（委托代扣订单通用查单）
        对应文档：/pay/orderquery；trade_state=ACCEPT 表示已受理等待扣款
        """
        params = {}
        if transaction_id:
            params["transaction_id"] = transaction_id
        else:
            params["out_trade_no"] = out_trade_no
        return self._post_xml("/pay/orderquery", params)

    def pre_deduct_notify(self, contract_id: str, amount_fen: int) -> Tuple[bool, Dict]:
        """
        预扣费通知（V3 混用接口）：周期扣费前提前告知用户，等待期后进入可扣费期
        对应文档：POST /v3/papay/contracts/{contract_id}/notify
        约束：仅北京时间 7:00~22:00 可调用；成功返回 HTTP 204

        Args:
            contract_id: 微信委托代扣协议ID
            amount_fen: 预计扣费金额（分）

        Returns:
            (是否成功, 响应信息)
        """
        if not self._v3_authorization_builder:
            return False, {"message": "v3_authorization_builder 未配置（缺少微信支付V3证书配置）"}

        url_path = f"/v3/papay/contracts/{contract_id}/notify"
        request_body = {
            "appid": self.app_id,
            "mchid": self.mch_id,
            "estimated_amount": {
                "amount": int(amount_fen),
                "currency": "CNY",
            },
        }
        body_json = json.dumps(request_body)
        auth_header = self._v3_authorization_builder("POST", url_path, body_json)

        resp = requests.post(
            f"{WX_API_BASE}{url_path}",
            data=body_json.encode("utf-8"),
            headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=SubscriptionConstants.HTTP_TIMEOUT_SECONDS,
        )
        # 成功无响应体（204）
        if resp.status_code in (200, 204):
            return True, {"status_code": resp.status_code}
        try:
            err = resp.json()
        except ValueError:
            err = {"raw": resp.text[:500]}
        logger.error(f"pre_deduct_notify failed: contract={contract_id}, resp={err}")
        return False, err

    # ==================== 单据号生成 ====================

    @staticmethod
    def generate_subscription_order_id() -> str:
        """订阅订单号：SUB_时间戳_随机（32字符内，满足微信约束）"""
        return f"{SubscriptionConstants.ORDER_ID_PREFIX}_{int(time.time())}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def generate_contract_code() -> str:
        """商户侧签约协议号：仅数字和大小写字母，同商户号下唯一"""
        return f"{SubscriptionConstants.CONTRACT_CODE_PREFIX}{int(time.time() * 1000)}{uuid.uuid4().hex[:8]}".upper()
