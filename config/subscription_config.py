"""
微信月度订阅（委托代扣·周期扣费）—— 临时 hardcode 配置

本文件包含月度订阅的套餐业务数据（价格/算力/赠送/协议模板ID）。
   敏感密钥（V2 密钥）不在本文件：运行时从 config_prod.yml / config_dev.yml 的
   pay.wxpay.api_v2_key 读取（该文件已被 .gitignore 排除）。

产品说明（微信委托代扣-周期扣费）：
  - 首期：支付中签约（V2 API /pay/contractorder），用户支付首月费用的同时完成自动续费签约；
  - 续期：商户按月发起委托代扣（V2 API /pay/pappayapply），扣款前按规则下发预扣费通知；
  - 解约：V2 API /papay/deletecontract，或用户在微信侧自助解约（回调同步）。

套餐与赠送规则来源：《智剧通算力定价_新价目方案.html》（2026-09-09）
  - 每档一个微信协议模板（共 4 个：智剧通-入门版/标准版/专业版/旗舰版），固定金额按月扣费；
  - computing_power 为「不抽成每期到账」；有邀请人抽佣时按佣金比例打折（commission/settle），
    赠送算力不参与抽成；
  - first_period_bonus 仅每份新签约的首期发放（解约后重新订阅视为新订阅，可再次享受）。
"""
from typing import Dict, List, Optional

# ==================== 月度订阅套餐（业务定义·新价目方案） ====================
# plan_id: 本地套餐ID（subscription_orders.subscription_plan_id / 合约表关联用）
# computing_power: 每周期（30天）常规到账算力（不抽成口径）
# granted_after_commission: 邀请抽成后参考值（仅展示，实际以 commission/settle 计算为准）
# first_period_bonus: 首次订阅加送算力（仅首期，随首月一并发放）
# template_id: 该档位对应的微信商户平台「委托代扣协议模板」ID（⚠️ 待填，共 4 个模板）
# badge: 前端角标（可选）
MONTHLY_SUBSCRIPTION_PLANS: List[Dict] = [
    {
        "plan_id": 101,
        "name": "入门版",
        "price": 29.9,
        "computing_power": 428,
        "granted_after_commission": 328,
        "first_period_bonus": 100,
        "template_id": "223101",   # 模板1：智剧通-入门版 ¥29.9/期（2026-09-10 审核通过）
        "badge": None,
    },
    {
        "plan_id": 102,
        "name": "标准版",
        "price": 59.9,
        "computing_power": 1000,
        "granted_after_commission": 808,
        "first_period_bonus": 200,
        "template_id": "223102",   # 模板2：智剧通-标准版 ¥59.9/期（2026-09-10 审核通过）
        "badge": None,
    },
    {
        "plan_id": 103,
        "name": "专业版",
        "price": 129.0,
        "computing_power": 2524,
        "granted_after_commission": 2148,
        "first_period_bonus": 300,
        "template_id": "223103",   # 模板3：智剧通-专业版 ¥129/期（2026-09-10 审核通过）
        "badge": None,
    },
    {
        "plan_id": 104,
        "name": "旗舰版",
        "price": 299.0,
        "computing_power": 6216,
        "granted_after_commission": 5598,
        "first_period_bonus": 500,
        "template_id": "223104",   # 模板4：智剧通-旗舰版 ¥299/期（2026-09-10 审核通过）
        "badge": None,
    },
]


def get_subscription_plan(plan_id: int) -> Optional[Dict]:
    """按本地套餐ID查套餐定义，不存在返回 None"""
    for plan in MONTHLY_SUBSCRIPTION_PLANS:
        if plan["plan_id"] == plan_id:
            return dict(plan)
    return None


