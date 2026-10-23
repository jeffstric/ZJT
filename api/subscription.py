"""
月度订阅 API 路由（微信委托代扣·周期扣费）

接口清单：
  - GET  /api/subscription/plans           订阅套餐列表（附当前用户订阅状态）
  - POST /api/subscription/wechat-sign-pay 创建「支付中签约」订单（首期）
  - GET  /api/subscription/status          我的订阅状态
  - GET  /api/subscription/order-status    单笔订阅订单支付状态（Native 扫码后轮询感知支付成功）
  - POST /api/subscription/cancel          解约（当期权益保留至周期结束）
  - POST /api/subscription/pay-callback    支付/扣款结果通知（微信→商户，V2 XML）
  - POST /api/subscription/contract-callback 签约/解约结果通知（微信→商户，V2 XML）
"""
import asyncio
import logging
import traceback
from typing import Optional

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from config.config_util import get_dynamic_config_value
from config.constant import SubscriptionOrderStatus
from config.subscription_config import MONTHLY_SUBSCRIPTION_PLANS
from model.subscription_orders import SubscriptionOrdersModel
from perseids_server.client import async_make_perseids_request
from perseids_server.utils.permission import require_permission
from services import subscription_service
from services.subscription_service import SubscriptionServiceError
from utils.wx_papay_util import xml_to_dict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


def _http_error(exc: SubscriptionServiceError) -> HTTPException:
    """业务异常 -> HTTPException（保持与现有支付接口 detail 风格一致）"""
    return HTTPException(status_code=exc.status_code, detail=exc.message)


# ==================== 请求模型 ====================

class SubscriptionSignPayRequest(BaseModel):
    subscription_plan_id: int
    user_id: int
    auth_token: str
    is_wechat_browser: bool = False
    openid: Optional[str] = None
    payment_ip: Optional[str] = None
    display_name: Optional[str] = None


class SubscriptionCancelRequest(BaseModel):
    user_id: int
    auth_token: str


# ==================== 鉴权辅助（与 /api/recharge/wechat-pay 一致） ====================

async def _verify_auth_token(auth_token: str, user_id: int) -> str:
    """校验用户登录状态，失败抛 SubscriptionServiceError(401)"""
    success, message, _ = await async_make_perseids_request(
        endpoint='user/check_computing_power',
        method='GET',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    if not success:
        logger.warning(f"User {user_id} authentication failed or expired")
        raise SubscriptionServiceError("登录已过期，请重新登录", status_code=401)
    return auth_token


def _resolve_auth_token(request: Request, auth_token: Optional[str]) -> Optional[str]:
    """token 来源：Query 参数（存量兼容）→ Authorization 头。

    红线14：auth_token 禁止拼进 URL query（Referer/浏览器历史/服务端日志泄漏），
    新前端统一走 Authorization 头；Query 仅兼容未升级的旧客户端。
    语义与 server.py 的 extract_bearer_token 一致（兼容裸 token 与空 Bearer）。
    """
    if auth_token:
        return auth_token
    header = (request.headers.get('authorization') or '').strip()
    if not header or header.lower() == 'bearer':
        return None
    if header.lower().startswith('bearer '):
        header = header[7:].strip()
    return header or None


# ==================== 客户端接口 ====================

@router.get("/plans")
@require_permission("computing:view_packages")
async def get_subscription_plans(request: Request, auth_token: Optional[str] = Query(None)):
    """获取月度订阅套餐列表（附当前用户订阅状态，前端据此展示管理入口）"""
    try:
        token = _resolve_auth_token(request, auth_token)
        status = None
        if token:
            success, message, response_data = await async_make_perseids_request(
                endpoint='user/get_user_id_by_auth_token',
                method='POST',
                headers={'Authorization': f'Bearer {token}'}
            )
            if success and response_data.get('user_id'):
                status = subscription_service.get_subscription_status(int(response_data['user_id']))
            else:
                # 有 token 但校验失败（老用户登录态失效）：首期优惠资格 fail-closed。
                # 否则前端按 eligible=true 展示 ¥18.8+加赠，实收却按签约记录扣 29.9
                # 无加赠 → 客诉。未登录（无 token）走下方默认分支按新用户展示营销价。
                status = {"subscribed": False, "status": "none", "first_bonus_eligible": False}
        return JSONResponse({
            "success": True,
            "plans": [dict(p) for p in MONTHLY_SUBSCRIPTION_PLANS],
            "subscription": status or {
                "subscribed": False,
                "status": "none",
                # 未登录视为潜在新用户，展示首期营销价；下单必经登录，届时按真实资格刷新
                "first_bonus_eligible": True,
            },
        })
    except Exception as e:
        logger.error(f"Failed to get subscription plans: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"获取订阅套餐失败: {e}")


@router.post("/wechat-sign-pay")
@require_permission("order:create")
async def create_subscription_sign_pay(request: Request, payload: SubscriptionSignPayRequest):
    """创建「支付中签约」订单：返回扫码 code_url（外部浏览器）或 JSAPI 参数（微信内）"""
    try:
        if not payload.auth_token:
            raise HTTPException(status_code=400, detail="Authentication token is required")
        await _verify_auth_token(payload.auth_token, payload.user_id)

        # 生产安全闸：V2 密钥（api_v2_key）缺失时回调验签 fail-closed（回调将被拒绝），
        # 不允许发起签约支付/展示二维码，从源头避免"用户已付款但回调无法入账"
        if not (get_dynamic_config_value("pay", "wxpay", "api_v2_key", default="") or "").strip():
            logger.error("pay.wxpay.api_v2_key missing; refuse to create subscription sign-pay order")
            raise HTTPException(status_code=503, detail="微信支付密钥未配置，无法发起订阅支付，请联系管理员")

        result = await subscription_service.create_sign_pay_order(
            user_id=payload.user_id,
            subscription_plan_id=payload.subscription_plan_id,
            is_wechat_browser=payload.is_wechat_browser,
            openid=payload.openid,
            payment_ip=payload.payment_ip,
            display_name=payload.display_name or str(payload.user_id),
        )
        result["success"] = True
        result["message"] = "订单创建成功，请在微信中完成支付并确认开通自动续费"
        return JSONResponse(result)
    except SubscriptionServiceError as e:
        raise _http_error(e)
    except HTTPException:
        # 空 token 400 / V2 密钥缺失 503 等需原样透出，不得被下方 500 吞掉
        #（与 /order-status 的 404 透传同一模式）
        raise
    except Exception as e:
        logger.error(f"Failed to create subscription sign-pay: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"创建订阅订单失败: {e}")


@router.get("/status")
@require_permission("order:create")
async def get_subscription_status(request: Request, user_id: int, auth_token: Optional[str] = Query(None)):
    """我的订阅状态：套餐、当前周期、下一扣款日、签约状态"""
    try:
        token = _resolve_auth_token(request, auth_token)
        if not token:
            raise SubscriptionServiceError("登录已过期，请重新登录", status_code=401)
        await _verify_auth_token(token, user_id)
        status = subscription_service.get_subscription_status(user_id)
        return JSONResponse({"success": True, "subscription": status})
    except SubscriptionServiceError as e:
        raise _http_error(e)
    except Exception as e:
        logger.error(f"Failed to get subscription status: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"获取订阅状态失败: {e}")


@router.get("/order-status")
@require_permission("order:create")
async def get_subscription_order_status(
    request: Request,
    order_id: str = Query(...),
    user_id: int = Query(...),
    auth_token: Optional[str] = Query(None),
):
    """单笔订阅订单支付状态：Native 扫码支付后前端轮询，感知支付成功并刷新订阅状态。

    仅允许查询本人订单；status 见 SubscriptionOrderStatus（1=PAID 已支付）。
    """
    try:
        token = _resolve_auth_token(request, auth_token)
        if not token:
            raise SubscriptionServiceError("登录已过期，请重新登录", status_code=401)
        await _verify_auth_token(token, user_id)
        order = await asyncio.to_thread(SubscriptionOrdersModel.get_by_order_id, order_id)
        if not order or int(order.user_id) != int(user_id):
            raise HTTPException(status_code=404, detail="订单不存在")
        return JSONResponse({
            "success": True,
            "order_id": order_id,
            "status": int(order.status),
            "paid": int(order.status) == SubscriptionOrderStatus.PAID,
        })
    except SubscriptionServiceError as e:
        raise _http_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get subscription order status: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"获取订单状态失败: {e}")


@router.post("/cancel")
@require_permission("order:create")
async def cancel_subscription(request: Request, payload: SubscriptionCancelRequest):
    """用户解约：当期已付权益保留至周期结束，之后不再扣款"""
    try:
        await _verify_auth_token(payload.auth_token, payload.user_id)
        result = await subscription_service.cancel_subscription(payload.user_id)
        result["success"] = True
        result["message"] = "订阅已取消，当期权益保留至周期结束"
        return JSONResponse(result)
    except SubscriptionServiceError as e:
        raise _http_error(e)
    except Exception as e:
        logger.error(f"Failed to cancel subscription: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"取消订阅失败: {e}")


# ==================== 微信回调（无鉴权，微信服务器调用） ====================

def _wechat_xml_response(ok: bool, message: str = "OK") -> Response:
    code = "SUCCESS" if ok else "FAIL"
    xml = (
        "<xml>"
        f"<return_code><![CDATA[{code}]]></return_code>"
        f"<return_msg><![CDATA[{message}]]></return_msg>"
        "</xml>"
    )
    return Response(content=xml, media_type="text/xml; charset=utf-8")


@router.post("/pay-callback")
async def subscription_pay_callback(request: Request):
    """
    支付/扣款结果通知（V2 XML）：首期「支付中签约」支付结果 + 续期委托代扣扣款结果
    """
    try:
        body = await request.body()
        params = xml_to_dict(body.decode("utf-8"))
        logger.info(f"Subscription pay callback: out_trade_no={params.get('out_trade_no')}, "
                    f"result={params.get('result_code')}")
        processed = await subscription_service.handle_pay_callback(params)
        if not processed:
            return _wechat_xml_response(False, "订单不存在或验签失败")
        return _wechat_xml_response(True)
    except Exception as e:
        logger.error(f"Subscription pay callback error: {e}")
        logger.error(traceback.format_exc())
        return _wechat_xml_response(False, "处理异常")


@router.post("/contract-callback")
async def subscription_contract_callback(request: Request):
    """
    签约/解约结果通知（V2 XML）：change_type=ADD 签约 / DELETE 解约
    """
    try:
        body = await request.body()
        params = xml_to_dict(body.decode("utf-8"))
        logger.info(f"Subscription contract callback: code={params.get('contract_code')}, "
                    f"change_type={params.get('change_type')}")
        processed = await subscription_service.handle_contract_callback(params)
        if not processed:
            return _wechat_xml_response(False, "记录不存在或验签失败")
        return _wechat_xml_response(True)
    except Exception as e:
        logger.error(f"Subscription contract callback error: {e}")
        logger.error(traceback.format_exc())
        return _wechat_xml_response(False, "处理异常")
