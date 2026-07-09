#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
手工补传 CDN 脚本
=================

扫描数据库中"应该上传到七牛云长期桶(qiniu_long_term)但尚未上传成功"的记录，
复用现有 CDN 上传链路进行补传。属于运维补救脚本，非 Web 接口，纯同步执行。

适用场景：
    - 某段时间 auto_upload_to_cdn 未开启或 qiniu_long_term 凭证缺失，导致图片/视频
      生成成功后只落在了本地 upload/ 目录，没有同步到 CDN。
    - 现在配置已就绪，希望把历史遗留的本地文件补传上去。

前置条件（全部满足才会执行上传，否则直接退出、不做任何改动）：
    1. config 中 server.auto_upload_to_cdn = true
    2. config 中 file_storage.qiniu_long_term 的 access_key / secret_key /
       bucket_name / cdn_domain 全部非空（access_key 不等于占位符 "IAM-xxx"）

处理两批数据：
    批次 A — ai_tools 表中"处理完成且 result_url 指向本地 /upload/，但尚未创建
            media_file_mapping"的记录。复用 AIToolsModel.update_with_cdn_sync()
            （内部会创建 mapping + 触发 CDNUtil.trigger_cdn_upload + 写事件日志）。
    批次 B — media_file_mapping 表中"曾创建过映射但上传失败（cloud_path 为空）"的
            历史记录。直接调 CDNUtil.trigger_cdn_upload() 重新上传。

用法：
    # 默认 dry-run，只查库打印将处理的清单，不触发任何上传
    # 通过环境变量 comfyui_env 指定环境（决定加载哪个 config_{env}.yml）
    comfyui_env=prod python scripts/tools/upload_pending_cdn.py

    # 真正执行上传（默认不限条数，一次补传全部）
    comfyui_env=prod python scripts/tools/upload_pending_cdn.py --force

    # 限制每个批次最多处理 50 条
    comfyui_env=prod python scripts/tools/upload_pending_cdn.py --force --limit 50

注意：
    - 本脚本仅复用现有 model / utils 模块，不改动任何业务代码，也不涉及表结构变更。
    - CDNUtil.trigger_cdn_upload() 在独立线程池中异步上传，脚本会在触发后轮询
      cloud_path 是否落库来判断完成情况，带有总超时保护。
"""

import argparse
import os
import sys
import time

# ---------------------------------------------------------------------------
# 将项目根目录注入 sys.path（scripts/tools/ 回退两级到项目根）
# 这样才能 import 项目内的 model.* / utils.* / config.*
# ---------------------------------------------------------------------------
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CURRENT_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _parse_args():
    parser = argparse.ArgumentParser(
        description="手工补传 CDN：扫描 ai_tools / media_file_mapping，把本地 upload/ 文件补传到七牛云长期桶",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="每个批次最多处理的记录条数，默认 0 表示不限（处理全部待补传记录）。"
             "如需限量可传如 --limit 100。",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="真正执行上传。不带该参数时为 dry-run，仅打印将处理的清单。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="显式声明 dry-run（与不传 --force 等效，仅打印不执行）。",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=600,
        help="全部触发上传后，等待 cloud_path 落库的总超时（秒），默认 600。",
    )
    return parser.parse_args()


def _check_prerequisites():
    """
    前置条件检查：auto_upload_to_cdn 开启 + qiniu_long_term 凭证齐全。

    满足返回 True，不满足打印中文提示后返回 False。

    注意：配置加载走 config_util.get_config()（依据环境变量 comfyui_env 选择
    config_{env}.yml），与 model.database 的加载来源保持一致。因此请通过环境变量
    指定环境，例如：comfyui_env=prod python scripts/tools/upload_pending_cdn.py
    """
    # 延迟 import，避免 dry-run 之外的无关操作触发模块初始化
    from config.config_util import get_config

    cfg = get_config()

    # 1. auto_upload_to_cdn 开关
    enable_cdn = bool(cfg.get("server", {}).get("auto_upload_to_cdn", False))
    if not enable_cdn:
        print("[前置检查] 未通过：server.auto_upload_to_cdn 未开启（当前 false）。")
        print("           如需补传，请先在配置中设置 server.auto_upload_to_cdn: true 后再运行。")
        return False

    # 2. qiniu_long_term 凭证齐全
    qiniu_lt = cfg.get("file_storage", {}).get("qiniu_long_term", {}) or {}
    ak = (qiniu_lt.get("access_key") or "").strip()
    sk = (qiniu_lt.get("secret_key") or "").strip()
    bucket = (qiniu_lt.get("bucket_name") or "").strip()
    domain = (qiniu_lt.get("cdn_domain") or "").strip()

    missing = []
    if not ak or ak == "IAM-xxx":
        missing.append("access_key")
    if not sk:
        missing.append("secret_key")
    if not bucket:
        missing.append("bucket_name")
    if not domain:
        missing.append("cdn_domain")

    if missing:
        print("[前置检查] 未通过：file_storage.qiniu_long_term 缺失或不完整 -> %s" % ", ".join(missing))
        print("           请在配置中补全 qiniu_long_term 的 access_key/secret_key/bucket_name/cdn_domain。")
        return False

    print("[前置检查] 通过：auto_upload_to_cdn=true / qiniu_long_term 凭证已配置")
    print("           bucket=%s  cdn_domain=%s" % (bucket, domain))
    return True


def _local_file_exists(relative_path):
    """校验 upload/ 下的本地文件是否真实存在。relative_path 不带前导斜杠。"""
    abs_path = os.path.join(_PROJECT_ROOT, relative_path)
    return os.path.exists(abs_path), abs_path


def _fetch_batch_a(limit):
    """
    批次 A：ai_tools 表中处理完成、result_url 指向本地 /upload/、尚未创建 mapping 的记录。
    limit <= 0 表示不限条数（处理全部）。
    返回 [(id, result_url, user_id), ...]
    """
    from model.database import execute_query
    from config.constant import AI_TOOL_STATUS_COMPLETED

    # 注意：MySQL 中 LIMIT 0 表示返回 0 行，因此 limit<=0 时必须去掉 LIMIT 子句
    base_sql = """
        SELECT id, result_url, user_id
        FROM ai_tools
        WHERE media_mapping_id IS NULL
          AND status = %s
          AND result_url IS NOT NULL
          AND result_url LIKE '/upload/%%'
        ORDER BY id
    """
    if limit and limit > 0:
        sql = base_sql + " LIMIT %s"
        params = (AI_TOOL_STATUS_COMPLETED, limit)
    else:
        sql = base_sql
        params = (AI_TOOL_STATUS_COMPLETED,)
    rows = execute_query(sql, params, fetch_all=True)
    return [(r["id"], r["result_url"], r["user_id"]) for r in (rows or [])]


def _fetch_batch_b(limit):
    """
    批次 B：media_file_mapping 表中曾创建映射但上传失败（cloud_path 为空）的历史记录。
    limit <= 0 表示不限条数（处理全部）。
    返回 [(id, local_path), ...]
    """
    from model.database import execute_query

    base_sql = """
        SELECT id, local_path
        FROM media_file_mapping
        WHERE cloud_path IS NULL
          AND status <> 'deleted'
          AND local_path LIKE 'upload/%%'
        ORDER BY id
    """
    if limit and limit > 0:
        sql = base_sql + " LIMIT %s"
        params = (limit,)
    else:
        sql = base_sql
        params = ()
    rows = execute_query(sql, params, fetch_all=True)
    return [(r["id"], r["local_path"]) for r in (rows or [])]


def _print_preview(title, rows, path_index, max_preview=10):
    """dry-run 时打印批次命中清单的前若干条样例。"""
    print("\n%s：命中 %d 条" % (title, len(rows)))
    for i, row in enumerate(rows[:max_preview]):
        rel_path = row[path_index].lstrip("/")
        exists, _ = _local_file_exists(rel_path)
        flag = "存在" if exists else "缺失"
        print("  - id=%s  path=%s  [本地文件%s]" % (row[0], row[path_index], flag))
    if len(rows) > max_preview:
        print("  ... 其余 %d 条略（--force 后会全部处理）" % (len(rows) - max_preview))


def _process_batch_a(rows, force):
    """
    处理批次 A。force=False 仅打印，force=True 真实触发上传。
    返回本轮触发上传的 mapping_id 列表（用于收尾轮询）。
    """
    from model.ai_tools import AIToolsModel

    triggered = []
    ok = skip_missing = fail = 0

    if not force:
        _print_preview("[批次 A] ai_tools 未创建 mapping", rows, path_index=1)
        return triggered

    print("\n[批次 A] 开始处理 %d 条（ai_tools 未创建 mapping）..." % len(rows))
    for idx, (record_id, result_url, user_id) in enumerate(rows, 1):
        rel_path = result_url.lstrip("/")
        exists, abs_path = _local_file_exists(rel_path)
        if not exists:
            print("  [A] record_id=%s 跳过：本地文件不存在 %s" % (record_id, abs_path))
            skip_missing += 1
            continue
        try:
            # 复用现有 CDN 同步入口：内部会检查 enable_cdn、创建 mapping、
            # 触发 trigger_cdn_upload、回写 media_mapping_id、写 CDN_UPLOADED 日志。
            # 传入 user_id 供 mapping 关联用户。
            AIToolsModel.update_with_cdn_sync(
                record_id, result_url=result_url, user_id=user_id
            )
            # 读回刚创建的 mapping_id 用于收尾轮询
            rec = AIToolsModel.get_by_id(record_id)
            mapping_id = getattr(rec, "media_mapping_id", None) if rec else None
            if mapping_id:
                triggered.append(mapping_id)
            print("  [A] record_id=%s result_url=%s -> mapping_id=%s 已触发上传" % (
                record_id, result_url, mapping_id))
            ok += 1
        except Exception as e:
            print("  [A] record_id=%s 失败：%s" % (record_id, e))
            fail += 1

        # 每 20 条短暂让出，避免瞬间堆积过多后台线程池
        if idx % 20 == 0:
            time.sleep(1)

    print("[批次 A] 汇总：成功触发 %d / 本地缺失跳过 %d / 失败 %d" % (ok, skip_missing, fail))
    return triggered


def _process_batch_b(rows, force):
    """
    处理批次 B。force=False 仅打印，force=True 真实触发上传。
    返回本轮触发上传的 mapping_id 列表（用于收尾轮询）。
    """
    from utils.cdn_util import CDNUtil

    triggered = []
    ok = skip_missing = fail = 0

    if not force:
        _print_preview("[批次 B] media_file_mapping cloud_path 为空", rows, path_index=1)
        return triggered

    print("\n[批次 B] 开始处理 %d 条（media_file_mapping 上传失败重试）..." % len(rows))
    for idx, (mapping_id, local_path) in enumerate(rows, 1):
        # local_path 已是不带前导斜杠的相对路径（如 upload/cache/...）
        exists, abs_path = _local_file_exists(local_path)
        if not exists:
            print("  [B] mapping_id=%s 跳过：本地文件不存在 %s" % (mapping_id, abs_path))
            skip_missing += 1
            continue
        try:
            # 直接复用 trigger_cdn_upload：参数即 mapping_id + local_path，
            # 成功后其内部会把 cloud_path 写回。
            CDNUtil.trigger_cdn_upload(mapping_id, local_path)
            triggered.append(mapping_id)
            print("  [B] mapping_id=%s local_path=%s 已触发重传" % (mapping_id, local_path))
            ok += 1
        except Exception as e:
            print("  [B] mapping_id=%s 失败：%s" % (mapping_id, e))
            fail += 1

        if idx % 20 == 0:
            time.sleep(1)

    print("[批次 B] 汇总：成功触发 %d / 本地缺失跳过 %d / 失败 %d" % (ok, skip_missing, fail))
    return triggered


def _wait_for_completion(triggered_mapping_ids, total_timeout):
    """
    等待本轮触发的 mapping 上传完成（cloud_path 落库）。

    CDNUtil.trigger_cdn_upload 在独立线程池中异步上传，脚本触发后必须等待，
    否则进程退出会带走后台线程。这里用轮询 + 总超时的方式，避免无超时阻塞
    （符合 AGENTS.md 超时红线）。

    超时后打印未完成清单并返回，不强行中断后台线程。
    """
    if not triggered_mapping_ids:
        return

    from model.media_file_mapping import MediaFileMappingModel

    print("\n[等待上传] 共 %d 条待落库，最长等待 %ds ..." % (
        len(triggered_mapping_ids), total_timeout))

    pending = set(triggered_mapping_ids)
    deadline = time.time() + total_timeout
    poll_interval = 3  # 秒

    while pending and time.time() < deadline:
        time.sleep(poll_interval)
        done_now = set()
        for mid in list(pending):
            try:
                rec = MediaFileMappingModel.get_by_id(mid)
                if rec and rec.cloud_path:
                    done_now.add(mid)
            except Exception as e:
                print("  [等待上传] 查询 mapping_id=%s 状态失败：%s" % (mid, e))
        pending -= done_now
        if done_now:
            print("  [等待上传] 已完成 %d/%d，剩余 %d" % (
                len(triggered_mapping_ids) - len(pending),
                len(triggered_mapping_ids), len(pending)))

    if pending:
        print("[等待上传] 超时退出，仍有 %d 条未落库 cloud_path：%s" % (
            len(pending), sorted(pending)))
        print("           这些任务的后台上传线程可能仍在进行，请稍后复查 media_file_mapping.cloud_path。")
    else:
        print("[等待上传] 全部 %d 条已成功落库 cloud_path。" % len(triggered_mapping_ids))


def main():
    args = _parse_args()
    # 只要没带 --force，就是 dry-run
    force = args.force and not args.dry_run

    print("=" * 70)
    print("手工补传 CDN 脚本  模式=%s" % ("EXECUTE(--force)" if force else "DRY-RUN"))
    print("=" * 70)

    # 1. 前置条件检查
    if not _check_prerequisites():
        # 前置不满足：直接退出，不连库、不上传
        sys.exit(0)

    # 2. 查询两批数据
    limit_desc = "%d" % args.limit if (args.limit and args.limit > 0) else "不限"
    print("\n[查询] 批次 A（ai_tools 未创建 mapping），limit=%s ..." % limit_desc)
    batch_a = _fetch_batch_a(args.limit)
    print("[查询] 批次 B（media_file_mapping cloud_path 为空），limit=%s ..." % limit_desc)
    batch_b = _fetch_batch_b(args.limit)

    if not batch_a and not batch_b:
        print("\n[结果] 没有需要补传的记录，退出。")
        return

    # 3. 处理
    triggered_a = _process_batch_a(batch_a, force)
    triggered_b = _process_batch_b(batch_b, force)

    # 4. dry-run 结束
    if not force:
        print("\n[DRY-RUN] 以上为待处理清单。确认无误后，加 --force 重新运行以真正执行上传。")
        return

    # 5. 真实执行：等待异步上传完成（带总超时）
    all_triggered = triggered_a + triggered_b
    _wait_for_completion(all_triggered, args.wait_timeout)

    print("\n[完成] 脚本执行结束。")


if __name__ == "__main__":
    main()
