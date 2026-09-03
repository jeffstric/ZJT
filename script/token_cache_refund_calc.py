#!/usr/bin/env python3
"""缓存双重计费 BUG 历史退费测算脚本（一次性审计,只读,不写库）

背景（详见 docs/backend/token_cache_double_billing_fix.md）：
  2026-01-24 起,计费公式把「含缓存命中的全量 input_token」按未命中全价计费,
  缓存命中部分又按缓存价加收一次 → 缓存命中 token 被双重计费。
  修复提交将 base_cost 的输入项改为未命中部分(input_token - cache_read)。
  本脚本按历史流水逐条重算「实收-应收」,输出每个用户应退算力清单。

两个时代的流水格式：
  A. 老格式(2026-01-24~04-10, 整数除法+未计算token结转, 无抽成)：
     "原始token(..) | 未计算token(..) | 聚合后token(..) | 剩余token(..)"
     - note 不含阈值 → 用 (聚合-剩余)=k*阈值 反解历史阈值(gcd)，
       并用「重算扣减==账面扣减」逐行端到端验证。
     - 归因用 token_log 原始表(含未产生扣费流水的零头调用,归因更完整)。
  B. 新格式(2026-04-10起, 百分位累积+可选抽成/峰谷)：
     "token(..) | 阈值(..) | [抽成.. 倍率.. 基础算力..] | 本次算力成本.."
     - note 自带阈值与倍率,直接重算;自校验=公式复算与note记录成本一致。

应退算力(每行) = 缓存命中token × (1/输入阈值 - 1/缓存阈值) × 倍率

充值资格过滤（业务口径,默认开启,--include-unpaid 可关闭仅审计）：
  累计实付(payment_orders status=1 的 SUM(price)) <= 0.1 元的用户不退——
  覆盖「从未充值」与「仅 0.1 元首充体验包」两类（体验包详情见
  config/constant.py TokenRefundCalcConstants）。

用法（干跑,只输出清单,不发放）：
  comfyui_env=prod python script/token_cache_refund_calc.py --full            # 清单输出 /tmp/refund_result.csv
  comfyui_env=prod python script/token_cache_refund_calc.py --full --include-unpaid  # 不做充值过滤(审计)
  comfyui_env=prod python script/token_cache_refund_calc.py --validate-user 1596
  comfyui_env=prod python script/token_cache_refund_calc.py --crosscheck 40
可选： --out /tmp/refund_result.csv 指定清单输出路径

注意：本脚本只做测算。实际发放请业务确认后另行编写(参照
script/settle_history_switch_diff.py 的幂等发放模式)。
"""
import argparse
import csv
import math
import os
import re
import sys
from collections import defaultdict
from decimal import Decimal

# 项目根目录加入 sys.path（脚本直击运行场景）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pymysql  # noqa: E402

from config.constant import TokenRefundCalcConstants  # noqa: E402
from model.database import get_db_connection  # noqa: E402

RE_TOKEN = re.compile(r'token\(输入:(\d+), 输出:(\d+), 缓存读取:(\d+)\)')
RE_THR = re.compile(r'阈值\(输入:(\d+), 输出:(\d+), 缓存读取:(\d+)\)')
RE_MULT = re.compile(r'倍率:([\d.]+)')
RE_COST = re.compile(r'本次算力成本:([\d.]+)')


def parse_triple(note, prefix):
    """提取 '<prefix>token(输入:X, 输出:Y, 缓存读取:Z)' 的三元组"""
    m = re.search(re.escape(prefix) + r'token\(输入:(\d+), 输出:(\d+), 缓存读取:(\d+)\)', note)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def parse_new(note):
    """新格式: 需含 token(..) 与 阈值(..)。返回 dict 或 None。"""
    if not note:
        return None
    m, t = RE_TOKEN.search(note), RE_THR.search(note)
    if not (m and t) or '原始token' in note:
        return None
    inp, outp, cache = int(m.group(1)), int(m.group(2)), int(m.group(3))
    ti, to, tc = int(t.group(1)), int(t.group(2)), int(t.group(3))
    if ti <= 0 or to <= 0 or tc <= 0:
        return None
    mm = RE_MULT.search(note)
    mult = float(mm.group(1)) if mm else 1.0
    # 与修复后的公式同口径: 输入只按未命中部分计价
    actual_base = inp / ti + outp / to + cache / tc
    correct_base = max(0, inp - cache) / ti + outp / to + cache / tc
    overcharge = (actual_base - correct_base) * mult
    check_ok = None
    c = RE_COST.search(note)
    if c:
        check_ok = abs(float(c.group(1)) - actual_base * mult) <= 0.001
    return dict(inp=inp, outp=outp, cache=cache, ti=ti, mult=mult,
                actual_base=actual_base, correct_base=correct_base,
                overcharge=overcharge, check_ok=check_ok)


def parse_old(note):
    """老格式: 原始/未计算/聚合后/剩余 四元组。返回 dict 或 None。"""
    if not note or '原始token' not in note:
        return None
    raw = parse_triple(note, '原始')
    carry = parse_triple(note, '未计算')
    agg = parse_triple(note, '聚合后')
    rem = parse_triple(note, '剩余')
    if not all((raw, carry, agg, rem)):
        return None
    # 结构自洽: 原始 + 未计算 == 聚合后
    struct_ok = all(raw[i] + carry[i] == agg[i] for i in range(3))
    return dict(raw=raw, carry=carry, agg=agg, rem=rem, struct_ok=struct_ok)


def fetch_deduct_rows():
    """流式拉取全部 token 扣费流水(显式列名,元组游标)"""
    with get_db_connection() as conn:
        cur = conn.cursor(pymysql.cursors.SSCursor)
        cur.execute("""
            SELECT id, user_id, computing_power, note, transaction_id, created_at
            FROM computing_power_log
            WHERE message='Token消耗扣除算力' AND behavior='deduct'
            ORDER BY id
        """)
        for row in cur:
            yield row
        cur.close()


def solve_thresholds(old_rows_with_meta):
    """按 (vendor,model) 反解历史阈值: 对每类, 聚合-剩余 = k*阈值, k>=1。
    thr = gcd(所有非零差值)。返回 {(v,m): (thr_in, thr_out, thr_cache)}。"""
    diffs = defaultdict(lambda: [set(), set(), set()])
    for r in old_rows_with_meta:
        key = (r['vendor_id'], r['model_id'])
        for i in range(3):
            d = r['old']['agg'][i] - r['old']['rem'][i]
            if d > 0:
                diffs[key][i].add(d)
    solved = {}
    for key, cats in diffs.items():
        thrs = []
        for cat in cats:
            if not cat:
                thrs.append(None)  # 该类从未扣减过, 无法反解
            else:
                g = 0
                for d in cat:
                    g = math.gcd(g, d)
                thrs.append(g)
        solved[key] = tuple(thrs)
    return solved


def cmd_validate_user(user_id):
    n = check_fail = 0
    actual_charged = 0
    base_sum = correct_sum = overcharge_sum = 0.0
    for log_id, uid, power, note, txn, created in fetch_deduct_rows():
        if uid != user_id:
            continue
        p = parse_new(note)
        if not p:
            print(f"[{log_id}] 非新格式流水跳过: {str(note)[:60]!r}")
            continue
        n += 1
        actual_charged += power
        base_sum += p['actual_base']
        correct_sum += p['correct_base']
        overcharge_sum += p['overcharge']
        if p['check_ok'] is False:
            check_fail += 1
            print(f"[{log_id}] 公式自校验失败 note={note[:120]}")
    print(f"\n== 用户 {user_id} 汇总 ==")
    print(f"新格式解析行数: {n}, 公式自校验失败: {check_fail}")
    print(f"账面扣减合计: {actual_charged}")
    print(f"实收基础合计(未乘倍率): {base_sum:.1f}")
    print(f"应收基础合计(未乘倍率): {correct_sum:.1f}")
    print(f"应退算力(含倍率): {overcharge_sum:.1f}")


def cmd_crosscheck(sample_n):
    import random
    random.seed(42)
    with get_db_connection() as conn:
        cur = conn.cursor(pymysql.cursors.Cursor)
        cur.execute("SELECT MIN(id), MAX(id) FROM computing_power_log "
                    "WHERE message='Token消耗扣除算力' AND behavior='deduct'")
        lo, hi = cur.fetchone()
        checked = mismatch = 0
        seen = set()
        while checked < sample_n:
            rid = random.randint(lo, hi)
            if rid in seen:
                continue
            seen.add(rid)
            cur.execute("SELECT note, transaction_id FROM computing_power_log "
                        "WHERE id=%s AND message='Token消耗扣除算力' AND behavior='deduct'", (rid,))
            r = cur.fetchone()
            if not r:
                continue
            note, txn = r
            if not txn or not txn.startswith('token_log_'):
                print(f"[{rid}] transaction_id 异常: {txn}")
                mismatch += 1
                checked += 1
                continue
            cur.execute("SELECT input_token, output_token, cache_read FROM token_log WHERE id=%s",
                        (int(txn[len('token_log_'):]),))
            tr = cur.fetchone()
            parsed = parse_triple(note, '原始') or (lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None)(RE_TOKEN.search(note))
            if not tr or not parsed:
                print(f"[{rid}] 数据缺失 token_log={tr}")
                mismatch += 1
            elif (tr[0], tr[1], tr[2]) != parsed:
                print(f"[{rid}] note=({parsed}) token_log=({tr[0]},{tr[1]},{tr[2]})")
                mismatch += 1
            else:
                print(f"[{rid}] OK in={parsed[0]} cache={parsed[2]}")
            checked += 1
        print(f"\n== 交叉验证: 抽样{checked}行, 不一致{mismatch}行 ==")


def fetch_recharge_totals():
    """累计实付金额(元): payment_orders 中 status=已支付 订单的 SUM(price),按用户聚合。

    退款订单状态会翻转为 3(已退款),不计入;未支付(0)/已取消(2)同样不计入。
    """
    with get_db_connection() as conn:
        cur = conn.cursor(pymysql.cursors.Cursor)
        cur.execute(
            "SELECT user_id, SUM(price) FROM payment_orders WHERE status=%s GROUP BY user_id",
            (TokenRefundCalcConstants.PAYMENT_STATUS_PAID,))
        return {uid: total for uid, total in cur.fetchall()}


def cmd_full(out_csv, include_unpaid=False):
    users = defaultdict(lambda: dict(rows_new=0, rows_old=0, charged=0,
                                     overcharge_new=0.0, overcharge_old=0.0,
                                     first=None, last=None))
    old_rows_meta = []   # 老格式流水(带vendor/model)
    empty_notes = []
    stats = dict(total=0, new=0, old=0, empty=0, check_fail=0, struct_fail=0)

    for log_id, uid, power, note, txn, created in fetch_deduct_rows():
        stats['total'] += 1
        if not note:
            stats['empty'] += 1
            empty_notes.append((log_id, uid, str(created)))
            continue
        p = parse_new(note)
        if p:
            stats['new'] += 1
            if p['check_ok'] is False:
                stats['check_fail'] += 1
            u = users[uid]
            u['rows_new'] += 1
            u['charged'] += power
            u['overcharge_new'] += p['overcharge']
            if u['first'] is None or created < u['first']:
                u['first'] = created
            if u['last'] is None or created > u['last']:
                u['last'] = created
            continue
        o = parse_old(note)
        if o:
            stats['old'] += 1
            if not o['struct_ok']:
                stats['struct_fail'] += 1
            old_rows_meta.append(dict(log_id=log_id, user_id=uid, power=power,
                                      txn=txn, old=o))
            continue
        stats['empty'] += 1
        empty_notes.append((log_id, uid, str(note)[:50]))

    print(f"[流水分类] 总数={stats['total']} 新格式={stats['new']} 老格式={stats['old']} "
          f"空/未知={stats['empty']}")
    print(f"[质量] 新格式公式自校验失败={stats['check_fail']} "
          f"老格式结构校验失败(原始+未计算!=聚合)={stats['struct_fail']}")

    # ============ 老时代处理 ============
    if old_rows_meta:
        with get_db_connection() as conn:
            cur = conn.cursor(pymysql.cursors.Cursor)
            # 1) 关联 token_log 取 vendor/model
            txns = [r['txn'] for r in old_rows_meta if r['txn']]
            vm = {}
            for i in range(0, len(txns), 1000):
                chunk = txns[i:i + 1000]
                cur.execute(
                    "SELECT id, vendor_id, model_id, input_token, output_token, cache_read "
                    "FROM token_log WHERE id IN (%s)" % ','.join(str(int(t[len('token_log_'):])) for t in chunk))
                for tid, v, m, inp, outp, cache in cur.fetchall():
                    vm[f'token_log_{tid}'] = (v, m, inp, outp, cache)
            for r in old_rows_meta:
                info = vm.get(r['txn'])
                if info:
                    r['vendor_id'], r['model_id'] = info[0], info[1]
                    r['tl_tokens'] = info[2:5]

            solved = solve_thresholds(old_rows_meta)
            print("\n[老时代阈值反解]")
            for key, thrs in sorted(solved.items(), key=lambda kv: str(kv[0])):
                print(f"  vendor={key[0]} model={key[1]} -> 阈值(输入,输出,缓存)={thrs}")

            # 2) 逐行端到端验证: sum(聚合//阈值) == 账面扣减
            vfail = cross_fail = 0
            for r in old_rows_meta:
                thrs = solved.get((r.get('vendor_id'), r.get('model_id')))
                if not thrs or any(t is None for t in thrs):
                    continue
                o = r['old']
                pred = sum(o['agg'][i] // thrs[i] for i in range(3))
                if pred != r['power']:
                    vfail += 1
                    if vfail <= 5:
                        print(f"  扣减不符 流水{r['log_id']}: 重算{pred} vs 账面{r['power']}")
                if r.get('tl_tokens') and r['tl_tokens'] != o['raw']:
                    cross_fail += 1
                    if cross_fail <= 5:
                        print(f"  原始!=token_log 流水{r['log_id']}: {o['raw']} vs {r['tl_tokens']}")
            print(f"[老时代验证] 扣减重算不符={vfail}/{len(old_rows_meta)} 原始token与账表不符={cross_fail}")

            # 3) 按用户归因老时代多收(用 token_log 全量,含零头调用)
            #    边界: 老格式流水最晚时间之前、且未出现在新格式流水中的 vendor 调用
            cur.execute("SELECT MAX(created_at) FROM computing_power_log "
                        "WHERE message='Token消耗扣除算力' AND behavior='deduct' AND note LIKE %s",
                        ('%原始token%',))
            boundary = cur.fetchone()[0]
            # 新格式已覆盖的 token_log id 集合(其归因已按新格式note计入)
            cur.execute("SELECT transaction_id FROM computing_power_log "
                        "WHERE message='Token消耗扣除算力' AND behavior='deduct' AND note LIKE %s",
                        ('%阈值(%',))
            new_txn_ids = {t for (t,) in cur.fetchall() if t}
            old_users = defaultdict(float)
            old_calls = defaultdict(int)
            cur.execute("""
                SELECT tl.id, tl.user_id, tl.vendor_id, tl.model_id, tl.cache_read, tl.created_at
                FROM token_log tl
                WHERE tl.created_at <= %s AND tl.cache_read > 0
            """, (boundary,))
            for tl_id, uid, v, m, cache, created in cur.fetchall():
                txn = f'token_log_{tl_id}'
                if txn in new_txn_ids:
                    continue  # 已按新格式计
                thrs = solved.get((v, m))
                if not thrs or thrs[0] is None or thrs[2] is None:
                    continue
                # 老时代无抽成, 倍率=1.0; 多收 = cache*(1/阈值入 - 1/阈值缓)
                old_users[uid] += cache * (1.0 / thrs[0] - 1.0 / thrs[2])
                old_calls[uid] += 1

        for uid, val in old_users.items():
            u = users[uid]
            u['overcharge_old'] += val
            u['rows_old'] += old_calls.get(uid, 0)
            if u['first'] is None:
                u['first'] = 'old-era'

    # ============ 汇总 ============
    affected = {uid: u for uid, u in users.items()
                if u['overcharge_new'] + u['overcharge_old'] > 0.005}

    def _refund_of(uid):
        u = users[uid]
        return u['overcharge_new'] + u['overcharge_old']

    total_refund = sum(_refund_of(uid) for uid in affected)
    total_new = sum(u['overcharge_new'] for u in affected.values())
    total_old = sum(u['overcharge_old'] for u in affected.values())
    total_charged = sum(u['charged'] for u in affected.values())

    print(f"\n========== 全量结果(未过滤) ==========")
    print(f"需退费用户数: {len(affected)}")
    print(f"退费总量: {total_refund:.1f} 算力 (取整 {round(total_refund)})")
    print(f"  其中新时代(4/10起): {total_new:.1f}, 老时代(1/24~4/10): {total_old:.1f}")
    print(f"涉及用户token扣费账面总量: {total_charged}")

    # ============ 充值资格过滤 ============
    # 业务口径: 未充值 或 累计实付<=0.1元(首充体验包) 的用户不退
    recharge = fetch_recharge_totals()
    min_recharge = Decimal(str(TokenRefundCalcConstants.MIN_RECHARGE_YUAN))
    qualified = {}
    excluded_never, excluded_tiny = [], []
    for uid in affected:
        total_paid = recharge.get(uid)
        if total_paid is None or total_paid <= 0:
            excluded_never.append(uid)
        elif total_paid <= min_recharge:
            excluded_tiny.append(uid)
        else:
            qualified[uid] = affected[uid]

    if not include_unpaid:
        final_set = qualified
        print(f"\n---------- 充值资格过滤 ----------")
        print(f"剔除-从未充值: {len(excluded_never)}人, 涉及应退 {sum(_refund_of(u) for u in excluded_never):.1f} 算力")
        print(f"剔除-仅{TokenRefundCalcConstants.MIN_RECHARGE_YUAN}元体验包: {len(excluded_tiny)}人, "
              f"涉及应退 {sum(_refund_of(u) for u in excluded_tiny):.1f} 算力")
    else:
        final_set = affected
        print(f"\n[--include-unpaid] 未做充值过滤,以下为全量清单")

    q_refund = sum(_refund_of(uid) for uid in final_set)
    q_charged = sum(users[uid]['charged'] for uid in final_set)
    print(f"\n========== 实际退费清单 ==========")
    print(f"退费用户数: {len(final_set)}")
    print(f"退费总量: {q_refund:.1f} 算力 (取整 {round(q_refund)})")
    print(f"涉及用户token扣费账面总量: {q_charged}")

    buckets = {'>=100': 0, '10~100': 0, '1~10': 0, '<1': 0}
    for uid in final_set:
        v = _refund_of(uid)
        if v >= 100: buckets['>=100'] += 1
        elif v >= 10: buckets['10~100'] += 1
        elif v >= 1: buckets['1~10'] += 1
        else: buckets['<1'] += 1
    print(f"退费金额分布(人数): {buckets}")

    print(f"\nTop 20:")
    print(f"{'用户ID':>8} {'应退合计':>9} {'新格式部分':>10} {'老格式部分':>10} {'累计实付元':>10} {'账面token扣费':>13}")
    top = sorted(final_set.items(), key=lambda kv: -_refund_of(kv[0]))
    for uid, u in top[:20]:
        paid = recharge.get(uid)
        print(f"{uid:>8} {_refund_of(uid):>9.2f} {u['overcharge_new']:>10.2f} "
              f"{u['overcharge_old']:>10.2f} {str(paid if paid is not None else 0):>10} {u['charged']:>13}")

    with open(out_csv, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['user_id', 'refund_total', 'refund_new_era', 'refund_old_era',
                    'recharge_total_yuan', 'new_era_deduct_rows', 'old_era_cache_calls',
                    'token_charged_total', 'refund_rounded'])
        for uid, u in sorted(final_set.items(), key=lambda kv: -_refund_of(kv[0])):
            w.writerow([uid,
                        f"{_refund_of(uid):.2f}",
                        f"{u['overcharge_new']:.2f}",
                        f"{u['overcharge_old']:.2f}",
                        str(recharge.get(uid) or 0),
                        u['rows_new'], u['rows_old'], u['charged'],
                        round(_refund_of(uid))])
    print(f"\n完整清单已写入: {out_csv}")
    if empty_notes:
        print(f"注: {len(empty_notes)}条空note流水未单独解析,其中涉及缓存的部分已由老时代token_log归因覆盖")


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='缓存双重计费BUG历史退费测算(只读)')
    ap.add_argument('--validate-user', type=int, help='输出指定用户的逐行核对汇总')
    ap.add_argument('--crosscheck', type=int, help='抽样核对note与token_log一致性')
    ap.add_argument('--full', action='store_true', help='全量测算并输出清单CSV')
    ap.add_argument('--include-unpaid', action='store_true',
                    help='不做充值资格过滤(默认剔除未充值/仅0.1元体验包用户)')
    ap.add_argument('--out', default='/tmp/refund_result.csv', help='清单CSV输出路径')
    args = ap.parse_args()
    if args.validate_user:
        cmd_validate_user(args.validate_user)
    elif args.crosscheck:
        cmd_crosscheck(args.crosscheck)
    elif args.full:
        cmd_full(args.out, include_unpaid=args.include_unpaid)
    else:
        ap.print_help()
        sys.exit(1)
