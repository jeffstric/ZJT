"""
月度订阅业务服务（微信委托代扣·周期扣费）

职责：
  - 首期「支付中签约」订单创建（pay/contractorder）
  - 支付/扣款结果回调处理（发算力、顺延周期）
  - 签约/解约结果回调处理
  - 用户解约（papay/deletecontract）
  - 订阅状态查询
  - 续期调度核心（预扣费通知 → 申请扣款 → 失败重试 → 窗口耗尽关单；
    支付成功但签约通知未到的合约主动查单收尾）

支付产品与周期规则（微信委托代扣-周期扣费）：
  - pre_notify 模式（默认）：到期前 N 天下发预扣费通知 → 当日+次日为等待期（不可扣）→
    之后 7 天可扣费期（每日 7:00~22:00）内实时扣款
  - direct 模式：直接申请扣款，微信向用户下发通知，24 小时后自动扣款
  - 首期签约后 12 小时内的扣款立即执行（不适用等待期），首期由「支付中签约」直接完成支付

注意：所有微信接口调用（requests 同步）均已用 asyncio.to_thread 包装，不阻塞事件循环。
"""
import asyncio
import logging
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from config.config_util import get_dynamic_config_value
from config.constant import (
    SubscriptionConstants,
    WxContractStatus,
    SubscriptionOrderStatus,
)
from config.subscription_config import get_subscription_plan, is_upgrade_plan
from model.database import execute_update
from model.wx_papay_contracts import WxPapayContractsModel
from model.subscription_orders import SubscriptionOrdersModel
from perseids_server.client import async_make_perseids_request
from utils.wechat_pay_util import WechatPayUtil
from utils.wx_papay_util import WxPapayUtil

logger = logging.getLogger(__name__)

# 北京时间（Asia/Shanghai 无夏令时，固定 UTC+8 即等价；tzdata 缺失环境走固定偏移兜底）
try:
    from zoneinfo import ZoneInfo
    _CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - 依赖环境兜底
    _CN_TZ = timezone(timedelta(hours=8))


def _now_cn() -> datetime:
    return datetime.now(_CN_TZ)


def _in_deduct_window() -> bool:
    """微信约束：预扣费通知/申请扣款仅北京时间 7:00~22:00 可发起"""
    return SubscriptionConstants.DEDUCT_ALLOWED_HOUR_START <= _now_cn().hour < SubscriptionConstants.DEDUCT_ALLOWED_HOUR_END


class _WechatV3AuthBuilder:
    """基于 WechatPayUtil._generate_sign 的 V3 授权头构造器（兼容旧版本 wechat_pay_util）"""

    def __init__(self, util: WechatPayUtil):
        self._util = util

    def __call__(self, http_method: str, url_path: str, request_body: str) -> str:
        timestamp = str(int(time.time()))
        nonce_str = uuid.uuid4().hex
        signature = self._util._generate_sign(http_method, url_path, timestamp, nonce_str, request_body)
        return (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{self._util.mch_id}",'
            f'nonce_str="{nonce_str}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{self._util.api_key}",'
            f'signature="{signature}"'
        )


def get_papay_util(plan_template_id: Optional[str] = None) -> WxPapayUtil:
    """
    构建委托代扣工具实例

    商户号/appId 等复用现有 pay.wxpay 动态配置；协议模板ID与 V2 密钥来自
    config/subscription_config.py（临时 hardcode，待统一迁移）。
    每档套餐一个微信协议模板，template_id 优先取套餐配置，缺省用全局兜底。

    Args:
        plan_template_id: 套餐专属协议模板ID（可选）
    """
    wechat_v3 = WechatPayUtil(
        app_id=get_dynamic_config_value("pay", "wxpay", "appId", default=""),
        mch_id=get_dynamic_config_value("pay", "wxpay", "mchId", default=""),
        api_key=get_dynamic_config_value("pay", "wxpay", "api_key", default=""),
        APIv3_key=get_dynamic_config_value("pay", "wxpay", "APIv3_key", default=""),
    )
    # V2 密钥来自 config_prod.yml / config_dev.yml 的 pay.wxpay.api_v2_key（不入 git）
    api_v2_key = get_dynamic_config_value("pay", "wxpay", "api_v2_key", default="")
    return WxPapayUtil(
        app_id=wechat_v3.app_id,
        mch_id=wechat_v3.mch_id,
        api_v2_key=api_v2_key,
        plan_template_id=plan_template_id or "",
        v3_authorization_builder=_WechatV3AuthBuilder(wechat_v3),
    )


class SubscriptionServiceError(Exception):
    """订阅业务异常（message 面向用户可读）"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ==================== 首期：支付中签约 ====================

async def create_sign_pay_order(
    user_id: int,
    subscription_plan_id: int,
    is_wechat_browser: bool,
    openid: Optional[str],
    payment_ip: Optional[str],
    display_name: str,
) -> Dict:
    """
    创建「支付中签约」订单：用户支付首月费用的同时完成自动续费签约

    Args:
        user_id: 用户ID
        subscription_plan_id: 本地订阅套餐ID
        is_wechat_browser: 是否微信内浏览器（JSAPI/NATIVE）
        openid: 微信内浏览器必填
        payment_ip: 用户终端IP
        display_name: 签约页展示的开通账号（手机号掩码）

    Returns:
        {order_id, payment_type, code_url | jsapi_params}
    """
    plan = get_subscription_plan(subscription_plan_id)
    if not plan:
        raise SubscriptionServiceError("无效的订阅套餐")

    # 同一用户只允许一条进行中（签约中/已签约）的订阅。
    # 存在未支付完成的 PENDING 签约（用户换了套餐重新发起）：自动放弃旧签约并关闭旧待支付订单，
    # 让用户可以无缝更换套餐；若旧订单用户已付款，回调仍会正常结算（资金不受影响）。
    # 存在已签约生效的 ACTIVE 签约：仅允许升级到更高套餐（无需退订，新单支付成功后自动解约旧约）。
    upgrade_from_contract_code = None
    existing = WxPapayContractsModel.get_active_by_user(user_id)
    if existing:
        if existing.status == WxContractStatus.PENDING:
            WxPapayContractsModel.mark_terminated(
                existing.contract_code, termination_remark='用户重新发起订阅(自动放弃旧签约)')
            old_order = SubscriptionOrdersModel.get_latest_by_contract(existing.contract_code)
            if old_order and old_order.status == SubscriptionOrderStatus.PENDING_PAY:
                SubscriptionOrdersModel.close(old_order.order_id, 'USER_ABANDONED', '用户重新发起订阅')
            logger.info(f"自动放弃未完成签约 {existing.contract_code}（用户 {user_id} 重新发起订阅）")
        elif is_upgrade_plan(existing.subscription_plan_id, plan["plan_id"]):
            upgrade_from_contract_code = existing.contract_code
            logger.info(
                f"Upgrade sign-pay: user {user_id} plan {existing.subscription_plan_id}"
                f" -> {plan['plan_id']}, source contract {existing.contract_code}"
            )
        else:
            raise SubscriptionServiceError("您已订阅月度会员，如需更换为更低套餐请先取消当前订阅")

    if is_wechat_browser and not openid:
        raise SubscriptionServiceError("微信内订阅需要用户openid，请先进行微信授权")

    # 每档套餐一个微信协议模板（固定金额），优先取套餐配置，缺省用全局兜底
    template_id = plan.get("template_id")
    if not template_id:
        raise SubscriptionServiceError(
            "订阅服务未配置完整（缺少微信委托代扣协议模板ID），请联系管理员",
            status_code=500,
        )

    papay = get_papay_util(template_id)

    order_id = WxPapayUtil.generate_subscription_order_id()
    contract_code = WxPapayUtil.generate_contract_code()
    total_fee = int(plan["price"] * 100)
    body = f"{SubscriptionConstants.BODY_PREFIX}-{plan['name']}"

    trade_type = "JSAPI" if is_wechat_browser else "NATIVE"
    result = await asyncio.to_thread(
        papay.create_contract_order,
        order_id=order_id,
        total_fee=total_fee,
        body=body,
        contract_code=contract_code,
        contract_display_account=(
            f"{SubscriptionConstants.CONTRACT_DISPLAY_ACCOUNT_PREFIX}{display_name}"
        )[:64],
        notify_url=_callback_url("pay-callback"),
        contract_notify_url=_callback_url("contract-callback"),
        trade_type=trade_type,
        openid=openid,
        product_id=str(plan["plan_id"]),
        client_ip=payment_ip or "127.0.0.1",
    )

    if result.get("return_code") != "SUCCESS":
        raise SubscriptionServiceError(
            f"签约下单失败: {result.get('return_msg') or '微信接口通信失败'}", status_code=502
        )
    if result.get("result_code") != "SUCCESS":
        detail = (
            result.get("contract_err_code_des")
            or result.get("err_code_des")
            or result.get("err_code")
            or "未知错误"
        )
        raise SubscriptionServiceError(f"签约下单失败: {detail}", status_code=502)

    # 落库：签约记录（签约中）+ 首期订单（待支付；周期在支付成功回调时确定）
    WxPapayContractsModel.create(
        contract_code=contract_code,
        user_id=user_id,
        subscription_plan_id=plan["plan_id"],
        plan_template_id=papay.plan_template_id,
        request_serial=int(datetime.now().timestamp() * 1000),
        openid=openid,
        status=WxContractStatus.PENDING,
    )
    SubscriptionOrdersModel.create(
        order_id=order_id,
        contract_code=contract_code,
        user_id=user_id,
        subscription_plan_id=plan["plan_id"],
        period_index=1,
        amount=plan["price"],
        computing_power=plan["computing_power"],
        period_start=None,
        period_end=None,
        status=SubscriptionOrderStatus.PENDING_PAY,
        upgrade_from_contract_code=upgrade_from_contract_code,
    )

    response = {
        "order_id": order_id,
        "contract_code": contract_code,
        "payment_type": trade_type,
        "price": plan["price"],
        "computing_power": plan["computing_power"],
        "upgrade": bool(upgrade_from_contract_code),
    }
    if upgrade_from_contract_code:
        current_plan = get_subscription_plan(existing.subscription_plan_id)
        if current_plan:
            response["current_plan"] = current_plan
    if trade_type == "JSAPI":
        prepay_id = result.get("prepay_id")
        if not prepay_id:
            raise SubscriptionServiceError("未获取到预支付会话，请稍后重试", status_code=502)
        response["jsapi_params"] = papay.build_jsapi_pay_params(prepay_id)
    else:
        code_url = result.get("code_url")
        if not code_url:
            raise SubscriptionServiceError("未获取到支付二维码，请稍后重试", status_code=502)
        response["code_url"] = code_url
    return response


# ==================== 回调处理 ====================

async def handle_pay_callback(xml_params: Dict) -> bool:
    """
    支付/扣款结果通知（V2 XML→dict）：首期支付中签约支付结果 与 续期委托代扣扣款结果 共用

    Returns:
        True=已处理/幂等跳过（应答SUCCESS）；False=订单不存在（应答FAIL）
    """
    papay = get_papay_util()
    if not papay.verify_v2_sign(xml_params):
        logger.error("Subscription pay callback sign verification failed")
        return False

    order_id = xml_params.get("out_trade_no")
    order = SubscriptionOrdersModel.get_by_order_id(order_id) if order_id else None
    if not order:
        logger.error(f"Subscription pay callback order not found: {order_id}")
        return False

    if xml_params.get("result_code") == "SUCCESS":
        transaction_id = xml_params.get("transaction_id", "")
        await _settle_order_paid(order, transaction_id)
    else:
        err_code = xml_params.get("err_code") or "UNKNOWN"
        err_des = xml_params.get("err_code_des") or "扣款/支付失败"
        if order.period_index == 1:
            # 首期失败：用户重新发起即可，旧单关闭留痕
            SubscriptionOrdersModel.close(order.order_id, err_code, err_des)
        else:
            # 续期失败：窗口内次日重试
            SubscriptionOrdersModel.mark_failed(
                order.order_id, err_code, err_des,
                next_retry_at=_next_morning(),
            )
        logger.warning(f"Subscription order {order_id} failed: {err_code} {err_des}")
    return True


async def _settle_order_paid(order, transaction_id: str) -> None:
    """订单支付/扣款成功结算：幂等落账 + 发算力 + 合约周期顺延（发放失败进补偿，不影响落账）"""
    if order.status == SubscriptionOrderStatus.PAID:
        logger.info(f"Subscription order {order.order_id} already settled, skip")
        return

    # 先落账并标记发放中（崩溃后由补偿任务续发，且不进入扣款重试链路）
    SubscriptionOrdersModel.mark_paid(order.order_id, transaction_id)
    # 同步内存态（供下方首订加赠资格/幂等键判定，避免读到落账前的旧值）
    order.status = SubscriptionOrderStatus.PAID
    order.transaction_id = transaction_id
    SubscriptionOrdersModel.set_grant_flag(order.order_id, "GRANT_PENDING")

    granted = await _settle_and_grant(order, transaction_id)
    # 首订加赠：仅签约成功后发放（合约此时多半仍签约中，ADD 回调/补偿查单成功后再补发；
    # 若签约回调先于支付回调到达，合约已 ACTIVE，此处即发）。发放失败与基础算力一起进补偿。
    bonus_ok = await _grant_first_period_bonus(order)
    SubscriptionOrdersModel.set_grant_flag(
        order.order_id, None if (granted and bonus_ok) else "GRANT_FAILED"
    )

    # 周期顺延：首期从支付时间起算；续期用订单预生成的周期
    now = datetime.now()
    if order.period_index == 1 or not order.period_start or not order.period_end:
        period_start, period_end = now, now + timedelta(days=SubscriptionConstants.PERIOD_DAYS)
    else:
        period_start, period_end = order.period_start, order.period_end
    WxPapayContractsModel.update_period(order.contract_code, period_start, period_end)
    logger.info(
        f"Subscription order {order.order_id} settled: user={order.user_id}, "
        f"power={order.computing_power}, granted={granted}, bonus_ok={bonus_ok}, "
        f"period={period_start}~{period_end}"
    )

    # 套餐升级单：支付成功即切换，解约被替换的旧合约（本地立即终止防双扣，微信侧尽力而为，
    # 未完成部分由续期调度中的补偿任务重试）
    source_contract_code = getattr(order, 'upgrade_from_contract_code', None)
    if source_contract_code:
        try:
            await _terminate_replaced_contract(source_contract_code)
        except Exception:
            logger.exception(
                f"Terminate replaced contract failed: order={order.order_id}, "
                f"source={source_contract_code} (补偿任务会重试)"
            )


async def _terminate_replaced_contract(source_contract_code: str) -> None:
    """套餐升级：终止被替换的旧合约。

    顺序上先本地终止（续期调度只看本地状态，杜绝升级过渡期双扣），再调微信解约 API；
    API 失败仅记录，备注保持 UPGRADE_TERMINATE_REMARK，由补偿任务重试直至微信侧确认。
    """
    contract = WxPapayContractsModel.get_by_contract_code(source_contract_code)
    if not contract or contract.status != WxContractStatus.ACTIVE:
        return

    WxPapayContractsModel.mark_terminated(
        contract.contract_code,
        3,
        SubscriptionConstants.UPGRADE_TERMINATE_REMARK,
    )
    logger.info(f"Upgrade replaced contract terminated locally: {source_contract_code}")

    if not contract.contract_id:
        logger.error(
            f"Upgrade replaced contract {source_contract_code} has no wechat contract_id, "
            f"需人工在商户平台解约"
        )
        return

    ok, err = await _delete_wechat_contract(contract)
    if ok:
        WxPapayContractsModel.update_termination_remark(
            contract.contract_code, SubscriptionConstants.UPGRADE_TERMINATE_REMARK_CONFIRMED)
    else:
        logger.error(
            f"Upgrade wechat delete_contract failed for {source_contract_code}: {err} "
            f"(补偿任务会重试)"
        )


async def _delete_wechat_contract(contract) -> tuple:
    """调微信解约 API。Returns: (是否成功, 错误描述)"""
    papay = get_papay_util()
    result = await asyncio.to_thread(
        papay.delete_contract,
        remark=SubscriptionConstants.UPGRADE_TERMINATE_REMARK,
        contract_id=contract.contract_id,
        contract_code=contract.contract_code,
    )
    if result.get("return_code") == "SUCCESS" and result.get("result_code") == "SUCCESS":
        return True, None
    detail = (
        result.get("err_code_des") or result.get("err_code")
        or result.get("return_msg") or "微信接口失败"
    )
    return False, detail


async def handle_contract_callback(xml_params: Dict) -> bool:
    """
    签约/解约结果通知（V2 XML→dict）

    Returns:
        True=已处理/幂等（应答SUCCESS）；False=验签失败或记录不存在
    """
    papay = get_papay_util()
    if not papay.verify_v2_sign(xml_params):
        logger.error("Subscription contract callback sign verification failed")
        return False

    contract_code = xml_params.get("contract_code")
    contract_id = xml_params.get("contract_id")
    change_type = xml_params.get("change_type")

    contract = WxPapayContractsModel.get_by_contract_code(contract_code) if contract_code else None
    if not contract:
        logger.error(f"Contract callback record not found: {contract_code}")
        return False

    if change_type == "ADD":
        WxPapayContractsModel.mark_signed(contract_code, contract_id, xml_params.get("openid"))
        logger.info(f"Contract signed: code={contract_code}, wechat_id={contract_id}")
        # 签约成功：补发首订加赠（支付回调已先行结算基础算力/权益；幂等，未满足条件自动跳过）
        order = SubscriptionOrdersModel.get_latest_by_contract(contract_code)
        if order:
            await _grant_first_period_bonus(order)
    elif change_type == "DELETE":
        mode = xml_params.get("contract_termination_mode")
        WxPapayContractsModel.mark_terminated(
            contract_code,
            int(mode) if mode and str(mode).isdigit() else None,
            xml_params.get("operate_time"),
        )
        logger.info(f"Contract terminated: code={contract_code}, mode={mode}")
    else:
        logger.warning(f"Unknown contract change_type: {change_type}")
    return True


# ==================== 用户操作 ====================

async def cancel_subscription(user_id: int) -> Dict:
    """
    用户解约：调微信解约API并落本地状态；当期已付权益保留至 current_period_end
    """
    contract = WxPapayContractsModel.get_latest_by_user(user_id)
    if not contract or contract.status != WxContractStatus.ACTIVE:
        raise SubscriptionServiceError("当前没有生效中的订阅")

    papay = get_papay_util()
    result = await asyncio.to_thread(
        papay.delete_contract,
        remark="用户主动取消订阅",
        contract_id=contract.contract_id,
        contract_code=contract.contract_code,
    )
    if result.get("return_code") == "SUCCESS" and result.get("result_code") == "SUCCESS":
        WxPapayContractsModel.mark_terminated(contract.contract_code, 3, "用户主动取消订阅")
    else:
        detail = result.get("err_code_des") or result.get("return_msg") or "微信接口失败"
        raise SubscriptionServiceError(f"解约失败: {detail}", status_code=502)

    return {
        "terminated": True,
        "rights_until": contract.current_period_end.isoformat() if contract.current_period_end else None,
    }


def get_subscription_status(user_id: int) -> Dict:
    """用户订阅状态视图（无订阅/签约中/生效中/已过期/已解约）。

    first_bonus_eligible：首订加赠资格（无历史成功签约合约），前端据此展示「首期订阅加赠」标签。
    """
    contract = WxPapayContractsModel.get_latest_by_user(user_id)
    first_bonus_eligible = not WxPapayContractsModel.exists_signed_contract(user_id)
    if not contract:
        return {
            "subscribed": False,
            "status": "none",
            "first_bonus_eligible": first_bonus_eligible,
        }

    plan = get_subscription_plan(contract.subscription_plan_id) or {}
    now = datetime.now()
    period_end = contract.current_period_end
    base = {
        "plan": plan,
        "status": "unknown",
        "current_period_end": period_end.isoformat() if period_end else None,
        "first_bonus_eligible": first_bonus_eligible,
    }

    if contract.status == WxContractStatus.PENDING:
        # 升级签约中：存在仍生效的旧合约（且新约套餐更高）→ upgrading，当前套餐继续可用
        active_old = WxPapayContractsModel.get_active_signed_by_user(user_id)
        if active_old and is_upgrade_plan(active_old.subscription_plan_id, contract.subscription_plan_id):
            old_plan = get_subscription_plan(active_old.subscription_plan_id) or {}
            pending_plan = get_subscription_plan(contract.subscription_plan_id) or {}
            old_period_end = active_old.current_period_end
            base.update({
                "subscribed": True,
                "status": "upgrading",
                "plan": old_plan,
                "pending_plan": pending_plan,
                "current_period_end": old_period_end.isoformat() if old_period_end else None,
                "next_deduct_date": old_period_end.date().isoformat() if old_period_end else None,
            })
        else:
            base.update({"subscribed": False, "status": "signing"})
    elif contract.status == WxContractStatus.TERMINATED:
        base.update({
            "subscribed": bool(period_end and period_end > now),
            "status": "terminated",
        })
        # 支付成功但签约未生效（与"用户主动解约"区分）：单期权益保留至周期结束，前端引导重新开通订阅
        if contract.termination_remark == SubscriptionConstants.SIGN_FAILED_TERMINATE_REMARK:
            base["sign_not_effective"] = True
    else:  # ACTIVE
        if period_end and period_end > now:
            base.update({
                "subscribed": True,
                "status": "active",
                "next_deduct_date": period_end.date().isoformat(),
            })
        else:
            base.update({"subscribed": False, "status": "expired"})
    return base


# ==================== 续期调度（定时任务核心） ====================

def _next_morning() -> datetime:
    """次日早上 8 点（北京时间扣费窗口内），加随机分钟抖动避免集中扣款"""
    tomorrow = _now_cn() + timedelta(days=1)
    morning = tomorrow.replace(hour=8, minute=random.randint(0, 59), second=0, microsecond=0)
    return morning.replace(tzinfo=None)


async def process_renewals() -> None:
    """
    续期主流程（由调度任务周期调用）：
      1. 到期前 N 天：创建续期订单 +（pre_notify 模式）下发预扣费通知
      2. 可扣费窗口内：对失败/待扣款订单发起申请扣款
      3. 受理超时未回调：主动查单确认
      4. 重试窗口耗尽：关闭订单（订阅自然过期）
      5. 签约中超时清理
    """
    # 微信约束：预扣费通知与申请扣款仅北京时间 7:00~22:00
    if not _in_deduct_window():
        logger.debug("Outside wechat deduct window (7:00-22:00), skip renewal tick")
        return

    await _create_renewal_orders()
    await _apply_due_deductions()
    await _confirm_stale_orders()
    await _reconcile_pending_signs()
    await _cleanup_stale_pending_signs()
    await _retry_upgrade_terminations()
    await process_settlement_retry()


async def _create_renewal_orders() -> None:
    """到期前 N 天创建续期订单；pre_notify 模式同时下发预扣费通知"""
    pre_notify_mode = SubscriptionConstants.DEDUCT_MODE == "pre_notify"
    due_contracts = WxPapayContractsModel.get_renewal_due_contracts(
        SubscriptionConstants.PRE_NOTIFY_LEAD_DAYS
    )
    for contract in due_contracts:
        try:
            latest = SubscriptionOrdersModel.get_latest_by_contract(contract.contract_code)
            # 已存在覆盖下一周期的订单则只补发预扣费通知
            need_create = (
                not latest
                or latest.status == SubscriptionOrderStatus.PAID
                or (latest.period_end and latest.period_end <= contract.current_period_end)
            )
            renewal = latest
            if need_create:
                plan = get_subscription_plan(contract.subscription_plan_id) or {}
                if not plan:
                    logger.error(f"Contract {contract.contract_code} plan {contract.subscription_plan_id} missing, skip")
                    continue
                period_start = contract.current_period_end
                period_end = period_start + timedelta(days=SubscriptionConstants.PERIOD_DAYS)
                next_index = (latest.period_index + 1) if latest else 1
                SubscriptionOrdersModel.create(
                    order_id=WxPapayUtil.generate_subscription_order_id(),
                    contract_code=contract.contract_code,
                    user_id=contract.user_id,
                    subscription_plan_id=contract.subscription_plan_id,
                    period_index=next_index,
                    amount=plan["price"],
                    computing_power=plan["computing_power"],
                    period_start=period_start,
                    period_end=period_end,
                    status=SubscriptionOrderStatus.PENDING_PAY,
                )
                renewal = SubscriptionOrdersModel.get_latest_by_contract(contract.contract_code)

            if pre_notify_mode and renewal and not renewal.prenotify_sent_at and contract.contract_id:
                plan = get_subscription_plan(contract.subscription_plan_id) or {}
                papay = get_papay_util()
                ok, err = await asyncio.to_thread(
                    papay.pre_deduct_notify,
                    contract.contract_id,
                    int(plan.get("price", 0) * 100),
                )
                if ok:
                    SubscriptionOrdersModel.mark_prenotify_sent(renewal.order_id)
                    logger.info(f"Pre-deduct notify sent: contract={contract.contract_code}, order={renewal.order_id}")
                else:
                    logger.error(f"Pre-deduct notify failed: contract={contract.contract_code}, err={err}")
        except Exception:
            logger.exception(f"Create renewal order failed: contract={contract.contract_code}")


def _prenotify_wait_end(prenotify_sent_at: datetime) -> datetime:
    """
    预扣费通知等待期结束时间：通知当日 + 第二个自然日均为等待期，第三日 00:00 起可扣费
    （DB 中 naive 时间按北京时间处理）
    """
    sent = prenotify_sent_at.replace(tzinfo=None)
    return datetime.combine(sent.date() + timedelta(days=2), datetime.min.time())


async def _apply_due_deductions() -> None:
    """对到期应扣款/应重试的订单发起申请扣款；重试窗口耗尽则关闭订单"""
    window_days = SubscriptionConstants.DEDUCT_RETRY_WINDOW_DAYS
    due_orders = SubscriptionOrdersModel.get_retry_due_orders()
    for order in due_orders:
        try:
            # 重试窗口耗尽：关闭订单，订阅随之过期
            if order.period_start and datetime.now() > order.period_start + timedelta(days=window_days):
                SubscriptionOrdersModel.close(
                    order.order_id, "RETRY_EXHAUSTED",
                    f"扣款重试{window_days}天窗口耗尽，订阅过期",
                )
                logger.warning(f"Renewal window exhausted: order={order.order_id}, user={order.user_id}")
                continue

            contract = WxPapayContractsModel.get_by_contract_code(order.contract_code)
            if not contract or contract.status != WxContractStatus.ACTIVE or not contract.contract_id:
                # 合约已解约/签约异常：关闭未完成订单
                SubscriptionOrdersModel.close(order.order_id, "CONTRACT_INVALID", "合约不存在或已解约")
                continue

            # pre_notify 模式须过等待期（通知当日+第二个自然日不可扣）
            if SubscriptionConstants.DEDUCT_MODE == "pre_notify":
                if not order.prenotify_sent_at:
                    continue
                if datetime.now() < _prenotify_wait_end(order.prenotify_sent_at):
                    continue

            plan = get_subscription_plan(order.subscription_plan_id) or {}
            body = f"{SubscriptionConstants.BODY_PREFIX}-{plan.get('name', '续费')}"
            papay = get_papay_util()
            result = await asyncio.to_thread(
                papay.apply_deduct,
                order_id=order.order_id,
                total_fee=int(order.amount * 100),
                body=body,
                contract_id=contract.contract_id,
                notify_url=_callback_url("pay-callback"),
            )
            if result.get("return_code") == "SUCCESS" and result.get("result_code") == "SUCCESS":
                # 受理成功：等待回调（26h 后仍无结果由查单兜底）
                SubscriptionOrdersModel.mark_confirming(order.order_id)
                logger.info(f"Deduct accepted: order={order.order_id}, contract={order.contract_code}")
            else:
                err_code = result.get("err_code") or result.get("return_code") or "UNKNOWN"
                err_des = result.get("err_code_des") or result.get("return_msg") or "申请扣款失败"
                # SYSTEMERROR 可较快重试；业务失败（余额不足等）次日再试
                delay_hours = 1 if err_code == "SYSTEMERROR" else None
                next_retry = (
                    datetime.now() + timedelta(hours=delay_hours)
                    if delay_hours else _next_morning()
                )
                SubscriptionOrdersModel.mark_failed(order.order_id, err_code, err_des, next_retry)
                logger.warning(f"Deduct apply failed: order={order.order_id}, err={err_code}")
        except Exception:
            logger.exception(f"Apply deduction failed: order={order.order_id}")


async def _confirm_stale_orders() -> None:
    """受理成功超时无回调的订单：主动查单确认最终状态"""
    confirm_hours = SubscriptionConstants.DEDUCT_CONFIRM_QUERY_DELAY_HOURS
    stale_orders = SubscriptionOrdersModel.get_stale_confirming_orders(confirm_hours)
    for order in stale_orders:
        try:
            papay = get_papay_util()
            result = await asyncio.to_thread(papay.query_order, order.order_id, None)
            trade_state = result.get("trade_state")
            if result.get("return_code") == "SUCCESS" and result.get("result_code") == "SUCCESS":
                if trade_state == "SUCCESS":
                    await _settle_order_paid(order, result.get("transaction_id", ""))
                elif trade_state == "ACCEPT" or trade_state == "USERPAYING":
                    # 仍在等待自动扣款，继续等
                    SubscriptionOrdersModel.mark_confirming(order.order_id)
                else:
                    # CLOSED/NOTPAY/PAYERROR：失败转重试
                    SubscriptionOrdersModel.mark_failed(
                        order.order_id,
                        trade_state or "UNKNOWN",
                        result.get("trade_state_desc") or "查单确认未成功",
                        _next_morning(),
                    )
            else:
                logger.warning(f"Query order failed: {order.order_id}, {result.get('err_code')}")
        except Exception:
            logger.exception(f"Confirm stale order failed: {order.order_id}")


async def _reconcile_pending_signs() -> None:
    """补偿：首期订单已支付但签约结果通知（ADD 回调）未到的签约中合约，主动向微信查询签约关系收尾。

    支付成功（款项已收、算力已发）而合约仍签约中，说明 ADD 回调丢失或用户未完成签约：
      - contract_state=0（已签约）：补 mark_signed 激活，签约自愈（迟到的 ADD 回调幂等覆盖，无影响）；
      - contract_state=1 / 查询无记录（err_code=-25 RESULT NULL）：签约未生效（无自动续费），
        单期权益保留（订单已结算），合约终止留痕，避免一直停在「签约中」；
      - contract_state=9（签约进行中）/ 查询接口异常：不动，等下一调度周期再查。
    """
    stale = WxPapayContractsModel.get_paid_pending_signs(
        SubscriptionConstants.PENDING_SIGN_CONFIRM_GRACE_MINUTES
    )
    for contract in stale:
        try:
            papay = get_papay_util(contract.plan_template_id)
            result = await asyncio.to_thread(
                papay.query_contract, contract_code=contract.contract_code
            )
            state = (result.get("contract_state") or "").strip()
            if (
                result.get("return_code") == "SUCCESS"
                and result.get("result_code") == "SUCCESS"
                and state == "0"
            ):
                contract_id = (result.get("contract_id") or "").strip()
                if not contract_id:
                    logger.error(
                        f"Querycontract signed but no contract_id: {contract.contract_code}, resp={result}"
                    )
                    continue
                WxPapayContractsModel.mark_signed(
                    contract.contract_code, contract_id, result.get("openid") or contract.openid
                )
                logger.info(
                    f"Pending sign reconciled as signed: {contract.contract_code}, wechat_id={contract_id}"
                )
                # 签约成功（ADD 回调丢失后自愈）：补发首订加赠（幂等，未满足条件自动跳过）
                order = SubscriptionOrdersModel.get_latest_by_contract(contract.contract_code)
                if order:
                    await _grant_first_period_bonus(order)
            elif state == "9":
                logger.info(f"Contract still signing at wechat, wait next tick: {contract.contract_code}")
            elif (
                state == "1"
                or (result.get("result_code") == "FAIL" and result.get("err_code") == "-25")
            ):
                # 微信侧确认未签约：签约未生效，终止合约。
                # 单期权益不受影响：款项已收，订单已结算发算力、周期已顺延，此处只取消"自动续费"，
                # 不退款、不回收算力（用户已付本月费用）。状态视图据备注返回 sign_not_effective 引导重开通。
                WxPapayContractsModel.mark_terminated(
                    contract.contract_code, None, SubscriptionConstants.SIGN_FAILED_TERMINATE_REMARK
                )
                logger.warning(
                    f"Paid but contract not signed at wechat: {contract.contract_code}, "
                    f"user={contract.user_id}, query={result}"
                )
            else:
                logger.warning(
                    f"Querycontract inconclusive for {contract.contract_code}: {result}, retry next tick"
                )
        except Exception:
            logger.exception(f"Reconcile pending sign failed: {contract.contract_code}")


async def _cleanup_stale_pending_signs() -> None:
    """签约中超时（未完成支付+签约）的合约置为已解约，允许用户重新发起"""
    sql = """
        UPDATE wx_papay_contracts
        SET status = 2, terminated_at = NOW(),
            termination_remark = '签约超时未完成(自动清理)',
            update_at = NOW()
        WHERE status = 0
          AND create_at <= DATE_SUB(NOW(), INTERVAL %s HOUR)
    """
    try:
        affected = execute_update(sql, (SubscriptionConstants.PENDING_SIGN_EXPIRE_HOURS,))
        if affected:
            logger.info(f"Cleaned {affected} stale pending sign contracts")
    except Exception:
        logger.exception("Cleanup stale pending signs failed")


async def _retry_upgrade_terminations() -> None:
    """补偿：升级单支付成功后被替换的旧合约，微信侧解约尚未确认的持续重试直至成功"""
    pending = WxPapayContractsModel.get_upgrade_terminated_pending_confirm(
        SubscriptionConstants.UPGRADE_TERMINATE_REMARK
    )
    for contract in pending:
        try:
            if not contract.contract_id:
                logger.error(
                    f"Upgrade replaced contract {contract.contract_code} has no wechat contract_id, "
                    f"需人工在商户平台解约"
                )
                continue
            ok, err = await _delete_wechat_contract(contract)
            if ok:
                WxPapayContractsModel.update_termination_remark(
                    contract.contract_code, SubscriptionConstants.UPGRADE_TERMINATE_REMARK_CONFIRMED)
                logger.info(f"Upgrade replaced contract wechat termination confirmed: {contract.contract_code}")
            else:
                logger.warning(
                    f"Upgrade wechat delete_contract retry failed for {contract.contract_code}: {err}"
                )
        except Exception:
            logger.exception(f"Retry upgrade termination failed: {contract.contract_code}")


async def process_settlement_retry() -> None:
    """补偿发放：已收款但算力未发放完成（GRANT_PENDING/GRANT_FAILED）的订单重试发放。

    基础算力按订单记录重发；首订加赠一并重试（幂等：first_bonus_granted 防重）。
    """
    orders = SubscriptionOrdersModel.get_grant_pending_orders(limit=50)
    for order in orders:
        try:
            granted = await _grant_computing_power(
                order.user_id, order.computing_power, order.transaction_id or ""
            )
            if granted:
                await _grant_first_period_bonus(order)
                SubscriptionOrdersModel.set_grant_flag(order.order_id, None)
                logger.info(f"Grant retry succeeded: order={order.order_id}")
        except Exception:
            logger.exception(f"Settlement retry failed: {order.order_id}")


# ==================== 内部辅助 ====================

def _callback_url(path: str) -> str:
    """回调地址：优先外部配置的 https_host，退回 server.host"""
    from config.config_util import get_config_value
    host = get_config_value("server", "https_host", default="")
    if not host:
        host = get_config_value("server", "host", default="0.0.0.0")
    return f"{host}/api/subscription/{path}"


async def _settle_and_grant(order, transaction_id: str) -> bool:
    """
    抽佣结算 + 发放基础算力（首订加赠不在此发放，见 _grant_first_period_bonus）

    规则（新价目方案）：
      - 基础算力走邀请抽佣结算（commission/settle），有邀请人时按其佣金比例打折；
      - 抽佣调用异常时降级为基础算力全额（宁可漏抽佣，不少发用户算力）。
    """
    plan = get_subscription_plan(order.subscription_plan_id) or {}
    base = order.computing_power
    granted = base
    try:
        settle_ok, settle_msg, settle_data = await async_make_perseids_request(
            endpoint='commission/settle',
            method='POST',
            data={
                "user_id": order.user_id,
                "order_id": order.order_id,
                "transaction_id": transaction_id,
                "package_id": order.subscription_plan_id,
                "price": float(order.amount),
                "computing_power": base,
            },
        )
        if settle_ok and settle_data and 'granted_computing_power' in settle_data:
            granted = settle_data['granted_computing_power']
        else:
            logger.warning(
                f"Subscription commission settle fallback to full power for {order.order_id}: {settle_msg}"
            )
    except Exception as e:
        logger.warning(f"Subscription commission settle failed for {order.order_id}: {e}")

    return await _grant_computing_power(order.user_id, granted, transaction_id)


async def _grant_first_period_bonus(order) -> bool:
    """首订加赠：仅「签约成功」后发放（用户只付款但签约未生效/订阅被关闭时不加赠）。

    发放条件（全部满足）：
      - 首期订单（period_index=1）且已支付；
      - 合约已签约生效（ACTIVE）——支付回调先到、签约结果（ADD 回调）后到时，加赠顺延到签约成功；
      - 该合约为用户首份「成功签约」的合约（只付款未签约的历史合约不消耗资格）；
      - 非升级单（或 UPGRADE_GRANT_FIRST_BONUS 开启）；
      - 该订单加赠未发放过（first_bonus_granted 幂等）。
    Returns:
        True=无需发放（条件不满足/已发放）或发放成功；False=应发放但发放失败（调用方进补偿重试）。
    幂等键：transaction_id + '_FIRST_BONUS'（基础算力已用原 transaction_id 发放，不能复用）。
    """
    if order.period_index != 1 or int(order.status) != SubscriptionOrderStatus.PAID:
        return True
    if getattr(order, 'first_bonus_granted', 0):
        return True
    if getattr(order, 'upgrade_from_contract_code', None) and not SubscriptionConstants.UPGRADE_GRANT_FIRST_BONUS:
        return True
    plan = get_subscription_plan(order.subscription_plan_id) or {}
    bonus = int(plan.get("first_period_bonus", 0))
    if bonus <= 0:
        return True
    contract = WxPapayContractsModel.get_by_contract_code(order.contract_code)
    if not contract or contract.status != WxContractStatus.ACTIVE:
        return True  # 签约未生效，不加赠（非失败）
    if WxPapayContractsModel.exists_signed_contract(order.user_id, exclude_contract_code=order.contract_code):
        return True  # 已有历史成功签约，非首订

    bonus_txn = f"{order.transaction_id or order.order_id}_FIRST_BONUS"
    granted = await _grant_computing_power(order.user_id, bonus, bonus_txn)
    if granted:
        SubscriptionOrdersModel.mark_first_bonus_granted(order.order_id)
        logger.info(
            f"First period bonus granted: order={order.order_id}, user={order.user_id}, bonus={bonus}"
        )
        return True
    return False


async def _grant_computing_power(user_id: int, computing_power: int, transaction_id: str) -> bool:
    """给用户发放算力（复用 perseids 认证服务）"""
    try:
        success, message, response_data = await async_make_perseids_request(
            endpoint='get_auth_token_by_user_id',
            method='POST',
            data={"user_id": user_id},
        )
        if not success:
            logger.error(f"Failed to get auth token for user {user_id}: {message}")
            return False
        auth_token = response_data['token']

        success, message, response_data = await async_make_perseids_request(
            endpoint='user/calculate_computing_power',
            method='POST',
            headers={'Authorization': f'Bearer {auth_token}'},
            data={
                "computing_power": computing_power,
                "behavior": "increase",
                "transaction_id": transaction_id,
            },
        )
        if not success:
            logger.error(f"Failed to grant power for user {user_id}: {message}")
            return False
        return True
    except Exception:
        logger.exception(f"Grant computing power error for user {user_id}")
        return False
