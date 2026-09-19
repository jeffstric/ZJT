"""
月度订阅续期定时任务（微信委托代扣·周期扣费）

调度入口：task/scheduler.py 每 SubscriptionConstants.SCHEDULER_INTERVAL_MINUTES 分钟调用一次。
核心逻辑在 services/subscription_service.process_renewals：
  1. 到期前 N 天创建续期订单 + 下发预扣费通知（pre_notify 模式）
  2. 可扣费窗口（北京时间 7:00~22:00）内对到期/失败订单发起申请扣款
  3. 受理超时无回调的订单主动查单确认
  4. 重试窗口耗尽关闭订单（订阅过期）、签约超时清理、算力发放补偿
"""
import asyncio
import logging

from services import subscription_service

logger = logging.getLogger(__name__)


async def process_subscription_renewals():
    """月度订阅续期处理（异步任务，由调度器经 _run_async_task 拉起）"""
    logger.info("[SubscriptionRenewal] Starting subscription renewal tick")
    try:
        await subscription_service.process_renewals()
    except Exception as e:
        # 单次 tick 失败不影响下轮调度；具体子步骤内部已各自捕获
        logger.error(f"[SubscriptionRenewal] Renewal tick failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
    logger.info("[SubscriptionRenewal] Subscription renewal tick finished")
