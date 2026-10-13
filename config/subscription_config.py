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
  - 每档一个微信协议模板。标准版/专业版/旗舰版为固定金额；入门版模板 224144 同时支持
    首期优惠价与后续标准价，新签约一律用该模板（已在约的旧合约仍用库里的 223101 续费）。
  - price 是续费价，也是「已有成功签约」用户再开通时的首期价。
    first_period_price 仅入门版：没有历史成功签约时，支付中签约按这个价扣首期。
  - computing_power 为每期常规到账（尾数统一为 8 的口径，与文档"抽成后"一致，所有用户统一）；
  - first_period_bonus 为首订加赠，仅在「签约成功」后发放：用户只付款但签约未生效（订阅被关闭）
    时不加赠；且仅限用户首份「成功签约」合约的首期发放一次（只付款未签约的历史合约不消耗资格，
    之后签约成功仍可享受；已有历史成功签约的重新订阅不再享受）。加赠不走渠道抽佣。
  - 2026-09-22：入门版首订加赠由 200 改为 40；首次开通首期 18.8 元，第 2 期起仍 29.9 元。
    18.8 的首月渠道不分佣；第 2 期起以及再订的 29.9 仍按入门版档位 4.28 元结算。
"""
from typing import Dict, List, Optional

# ==================== 月度订阅套餐（业务定义·新价目方案） ====================
# plan_id: 本地套餐ID（subscription_orders.subscription_plan_id / 合约表关联用）
# computing_power: 每周期（30天）常规到账算力（不抽成口径）
# granted_after_commission: 邀请抽成后参考值（仅展示，实际以 commission/settle 计算为准）
# first_period_price: 首期优惠价（元）。仅无历史成功签约时用于支付中签约；缺省则首期也按 price
# first_period_bonus: 首次订阅加送算力（仅签约成功后发放；仅首份成功签约合约的首期一次，随首月一并发放）
# template_id: 该档位对应的微信商户平台「委托代扣协议模板」ID
# price: 续费价（元）；入门版再订用户的首期也按这个价
# badge: 前端角标（可选）
MONTHLY_SUBSCRIPTION_PLANS: List[Dict] = [
    {
        "plan_id": 101,
        "name": "入门版",
        "price": 29.9,
        "first_period_price": 18.8,
        "computing_power": 328,
        "granted_after_commission": 328,
        "first_period_bonus": 40,
        "template_id": "224144",   # 首期优惠 18.8 / 后续 29.9（新签约一律用此模板）
        "badge": None,
    },
    {
        "plan_id": 102,
        "name": "标准版",
        "price": 59.9,
        "computing_power": 808,
        "granted_after_commission": 808,
        "first_period_bonus": 400,
        "template_id": "223102",   # 模板2：智剧通-标准版 ¥59.9/期（2026-09-10 审核通过）
        "badge": None,
    },
    {
        "plan_id": 103,
        "name": "专业版",
        "price": 129.0,
        "computing_power": 2148,
        "granted_after_commission": 2148,
        "first_period_bonus": 600,
        "template_id": "223103",   # 模板3：智剧通-专业版 ¥129/期（2026-09-10 审核通过）
        "badge": None,
    },
    {
        "plan_id": 104,
        "name": "旗舰版",
        "price": 299.0,
        "computing_power": 5598,
        "granted_after_commission": 5598,
        "first_period_bonus": 1000,
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


def is_upgrade_plan(current_plan_id: int, new_plan_id: int) -> bool:
    """判断 new 是否为高于 current 的升级套餐（套餐按 plan_id 与价格单调递增）"""
    return int(new_plan_id) > int(current_plan_id)


