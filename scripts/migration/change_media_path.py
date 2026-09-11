#!/usr/bin/env python3
"""
迁移脚本：替换数据库及磁盘文件中媒体路径的 Host

用法：
    python scripts/migration/change_media_path.py --new-host ssh.perseids.cn:13000
    python scripts/migration/change_media_path.py --old-host localhost:9003 --new-host ssh.perseids.cn:13000
    python scripts/migration/change_media_path.py --old-host localhost:9003 --new-host ssh.perseids.cn:13000 --dry-run
    # http -> https：host 参数支持 http:// 或 https:// 前缀（不带前缀时默认 http）
    python scripts/migration/change_media_path.py --old-host http://ailive.perseids.cn --new-host https://ailive.perseids.cn --dry-run
"""
import os
import sys
import json
import argparse
from urllib.parse import quote

# 添加项目根目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from model.database import get_db_connection

# 简单文本字段：(表名, 字段名)
TEXT_FIELDS = [
    ("ai_tools", "image_path"),
    ("character", "reference_image"),
    ("character", "default_voice"),
    ("location", "reference_image"),
    ("props", "reference_image"),
]

# JSON 字段：(表名, 字段名, JSON 结构类型)
# url_list: ["url1", "url2"]
# object_list: [{"url": "...", "label": "..."}]
JSON_FIELDS = [
    ("ai_tools", "reference_images", "url_list"),
    ("character", "reference_images", "object_list"),
    ("location", "reference_images", "object_list"),
]


def _parse_host(value):
    """解析 --old-host/--new-host 参数：支持可选的 http:// 或 https:// 前缀，默认 http。

    返回 (scheme, host)，例如 "https://ailive.perseids.cn" -> ("https", "ailive.perseids.cn")。
    """
    if value.startswith("https://"):
        return "https", value[len("https://"):]
    if value.startswith("http://"):
        return "http", value[len("http://"):]
    return "http", value


def replace_host_in_text(old_prefix, new_prefix):
    """处理简单文本字段，使用 SQL REPLACE 直接替换。

    old_prefix/new_prefix 为含 scheme 的完整前缀（如 "http://ailive.perseids.cn"），
    因此可以表达 http -> https 的替换；LIKE 匹配同样带前缀，避免误统计已是新前缀的行。
    """
    stats = {}

    for table, field in TEXT_FIELDS:
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # 先统计匹配行数
                cursor.execute(
                    f"SELECT COUNT(*) as cnt FROM `{table}` WHERE `{field}` LIKE %s",
                    (f"%{old_prefix}%",)
                )
                count = cursor.fetchone()["cnt"]

                if count == 0:
                    print(f"  [{table}.{field}] 无匹配记录，跳过")
                    stats[f"{table}.{field}"] = 0
                    continue

                print(f"  [{table}.{field}] 匹配 {count} 条记录")

                # 执行替换
                cursor.execute(
                    f"UPDATE `{table}` SET `{field}` = REPLACE(`{field}`, %s, %s) WHERE `{field}` LIKE %s",
                    (old_prefix, new_prefix, f"%{old_prefix}%")
                )
                affected = cursor.rowcount
                conn.commit()
                print(f"  [{table}.{field}] 已更新 {affected} 条记录")
                stats[f"{table}.{field}"] = affected
        except Exception as e:
            print(f"  [{table}.{field}] 错误: {e}")
            stats[f"{table}.{field}"] = -1

    return stats


def replace_host_in_json(old_prefix, new_prefix, dry_run=False):
    """处理 JSON 字段，Python 解析后替换 URL 中的前缀"""
    stats = {}

    for table, field, json_type in JSON_FIELDS:
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # 查询包含旧前缀的行
                cursor.execute(
                    f"SELECT id, `{field}` FROM `{table}` WHERE `{field}` LIKE %s",
                    (f"%{old_prefix}%",)
                )
                rows = cursor.fetchall()

                if not rows:
                    print(f"  [{table}.{field}] 无匹配记录，跳过")
                    stats[f"{table}.{field}"] = 0
                    continue

                print(f"  [{table}.{field}] 匹配 {len(rows)} 条记录")

                if dry_run:
                    # 预览：显示第一条的替换前后对比
                    if rows:
                        sample = rows[0][field]
                        print(f"    预览 ID={rows[0]['id']}:")
                        print(f"      替换前: {sample[:120]}...")
                    stats[f"{table}.{field}"] = len(rows)
                    continue

                updated = 0
                for row in rows:
                    row_id = row["id"]
                    raw = row[field]
                    if not raw:
                        continue

                    try:
                        data = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        print(f"    警告: ID={row_id} JSON 解析失败，跳过")
                        continue

                    changed = False

                    if json_type == "url_list" and isinstance(data, list):
                        for i, url in enumerate(data):
                            if isinstance(url, str) and old_prefix in url:
                                data[i] = url.replace(old_prefix, new_prefix)
                                changed = True

                    elif json_type == "object_list" and isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and "url" in item:
                                url = item["url"]
                                if isinstance(url, str) and old_prefix in url:
                                    item["url"] = url.replace(old_prefix, new_prefix)
                                    changed = True

                    if changed:
                        new_json = json.dumps(data, ensure_ascii=False)
                        cursor.execute(
                            f"UPDATE `{table}` SET `{field}` = %s WHERE id = %s",
                            (new_json, row_id)
                        )
                        updated += 1

                conn.commit()
                print(f"  [{table}.{field}] 已更新 {updated} 条记录")
                stats[f"{table}.{field}"] = updated
        except Exception as e:
            print(f"  [{table}.{field}] 错误: {e}")
            stats[f"{table}.{field}"] = -1

    return stats


def _replace_ref_in_obj(obj, old_prefix, new_prefix):
    """递归遍历 JSON 对象，替换所有 reference_image 字段中的前缀。返回是否修改。"""
    changed = False
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "reference_image" and isinstance(val, str) and old_prefix in val:
                obj[key] = val.replace(old_prefix, new_prefix)
                changed = True
            elif isinstance(val, (dict, list)):
                if _replace_ref_in_obj(val, old_prefix, new_prefix):
                    changed = True
            elif isinstance(val, str) and old_prefix in val:
                # 尝试解析字符串中的 JSON 并递归替换
                try:
                    nested = json.loads(val)
                    if isinstance(nested, (dict, list)):
                        if _replace_ref_in_obj(nested, old_prefix, new_prefix):
                            obj[key] = json.dumps(nested, ensure_ascii=False)
                            changed = True
                except (json.JSONDecodeError, TypeError):
                    pass
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, (dict, list)):
                if _replace_ref_in_obj(item, old_prefix, new_prefix):
                    changed = True
            elif isinstance(item, str) and old_prefix in item:
                try:
                    nested = json.loads(item)
                    if isinstance(nested, (dict, list)):
                        if _replace_ref_in_obj(nested, old_prefix, new_prefix):
                            obj[i] = json.dumps(nested, ensure_ascii=False)
                            changed = True
                except (json.JSONDecodeError, TypeError):
                    pass
    return changed


def _replace_all_strings_in_obj(obj, old_prefix, new_prefix):
    """递归遍历 JSON 对象，替换所有字符串值中的前缀。用于 workflow_data 等深层嵌套 JSON。"""
    changed = False
    if isinstance(obj, dict):
        for key, val in list(obj.items()):
            if isinstance(val, str) and old_prefix in val:
                obj[key] = val.replace(old_prefix, new_prefix)
                changed = True
            elif isinstance(val, (dict, list)):
                if _replace_all_strings_in_obj(val, old_prefix, new_prefix):
                    changed = True
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str) and old_prefix in item:
                obj[i] = item.replace(old_prefix, new_prefix)
                changed = True
            elif isinstance(item, (dict, list)):
                if _replace_all_strings_in_obj(item, old_prefix, new_prefix):
                    changed = True
    return changed


# 深层嵌套 JSON 字段：(表名, 主键字段, JSON字段名)
# 这些字段内部任意层级的字符串值都可能包含 URL
NESTED_JSON_FIELDS = [
    ("video_workflow", "id", "workflow_data"),
]


def replace_host_in_nested_json(old_prefix, new_prefix, old_host, dry_run=False):
    """处理深层嵌套 JSON 字段（如 video_workflow.workflow_data），递归替换所有字符串中的前缀"""
    # URL 编码形式: http%3A%2F%2Fssh.perseids.cn%3A13000 → https%3A%2F%2Fyiliao.perseids.cn
    old_prefix_encoded = quote(old_prefix, safe='')
    new_prefix_encoded = quote(new_prefix, safe='')
    stats = {}

    for table, pk_field, field in NESTED_JSON_FIELDS:
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # 查询包含旧 host 的行：用不带 scheme 的 host 匹配，
                # 才能同时命中明文（http://host）与 URL 编码（http%3A%2F%2Fhost）两种形式；
                # 替换阶段的两遍 REPLACE 只会动旧前缀，已是新前缀的行不受影响
                cursor.execute(
                    f"SELECT `{pk_field}`, `{field}` FROM `{table}` WHERE `{field}` LIKE %s",
                    (f"%{old_host}%",)
                )
                rows = cursor.fetchall()

                if not rows:
                    print(f"  [{table}.{field}] 无匹配记录，跳过")
                    stats[f"{table}.{field}"] = 0
                    continue

                print(f"  [{table}.{field}] 匹配 {len(rows)} 条记录")

                if dry_run:
                    # 预览：列出匹配的记录 ID
                    ids = [str(row[pk_field]) for row in rows[:10]]
                    print(f"    匹配 ID: {', '.join(ids)}{'...' if len(rows) > 10 else ''}")
                    stats[f"{table}.{field}"] = len(rows)
                    continue

                updated = 0
                for row in rows:
                    row_id = row[pk_field]
                    raw = row[field]
                    if not raw:
                        continue

                    # workflow_data 可能已经是 dict（pymysql JSON 字段自动解析）
                    if isinstance(raw, str):
                        try:
                            data = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            print(f"    警告: ID={row_id} JSON 解析失败，跳过")
                            continue
                    elif isinstance(raw, dict):
                        data = raw
                    elif isinstance(raw, list):
                        data = raw
                    else:
                        continue

                    changed = False
                    # 第一遍：替换明文 URL (http://ssh.perseids.cn:13000)
                    if _replace_all_strings_in_obj(data, old_prefix, new_prefix):
                        changed = True
                    # 第二遍：替换 URL 编码形式 (http%3A%2F%2Fssh.perseids.cn%3A13000)
                    if _replace_all_strings_in_obj(data, old_prefix_encoded, new_prefix_encoded):
                        changed = True

                    if changed:
                        new_json = json.dumps(data, ensure_ascii=False)
                        cursor.execute(
                            f"UPDATE `{table}` SET `{field}` = %s WHERE `{pk_field}` = %s",
                            (new_json, row_id)
                        )
                        updated += 1

                conn.commit()
                print(f"  [{table}.{field}] 已更新 {updated} 条记录")
                stats[f"{table}.{field}"] = updated
        except Exception as e:
            print(f"  [{table}.{field}] 错误: {e}")
            stats[f"{table}.{field}"] = -1

    return stats


def replace_host_in_files(old_prefix, new_prefix, dry_run=False):
    """遍历 files/script_writer 目录，替换 JSON 文件中 reference_image 的前缀"""
    stats = {}

    base_dir = os.path.join(project_root, "files", "script_writer")
    if not os.path.isdir(base_dir):
        print("  [files] 目录不存在，跳过文件扫描")
        return stats

    total_matched = 0
    total_updated = 0

    for dirpath, dirnames, filenames in os.walk(base_dir):
        for filename in filenames:
            if not filename.endswith(".json"):
                continue

            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if _replace_ref_in_obj(data, old_prefix, new_prefix):
                    total_matched += 1

                    if dry_run:
                        if total_matched == 1:
                            print(f"    预览 {filepath}:")
                        continue

                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    total_updated += 1

            except (json.JSONDecodeError, TypeError) as e:
                print(f"    警告: {filepath} JSON 解析失败: {e}")
            except OSError as e:
                print(f"    警告: {filepath} 文件操作失败: {e}")

    if dry_run:
        print(f"  [files] 匹配 {total_matched} 个文件")
        stats["files"] = total_matched
    else:
        print(f"  [files] 已更新 {total_updated} 个文件")
        stats["files"] = total_updated

    return stats


def main():
    parser = argparse.ArgumentParser(description="替换数据库中媒体路径的 Host")
    parser.add_argument(
        "--old-host",
        default="localhost:9003",
        help="旧 host 地址，支持 http:// 或 https:// 前缀，不带前缀时默认 http (默认: localhost:9003)"
    )
    parser.add_argument(
        "--new-host",
        required=True,
        help="新 host 地址 (必填)，支持 http:// 或 https:// 前缀，不带前缀时默认 http"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览，不执行更新"
    )
    args = parser.parse_args()

    old_scheme, old_host = _parse_host(args.old_host)
    new_scheme, new_host = _parse_host(args.new_host)
    old_prefix = f"{old_scheme}://{old_host}"
    new_prefix = f"{new_scheme}://{new_host}"

    print(f"=" * 60)
    print(f"替换媒体路径 Host")
    print(f"  旧前缀: {old_prefix}")
    print(f"  新前缀: {new_prefix}")
    print(f"  预览模式: {'是' if args.dry_run else '否'}")
    print(f"=" * 60)

    print("\n[1/4] 处理简单文本字段...")
    text_stats = replace_host_in_text(old_prefix, new_prefix) if not args.dry_run else _dry_run_text(old_prefix)

    print("\n[2/4] 处理 JSON 字段...")
    json_stats = replace_host_in_json(old_prefix, new_prefix, dry_run=args.dry_run)

    print("\n[3/4] 处理深层嵌套 JSON 字段（workflow_data 等）...")
    nested_stats = replace_host_in_nested_json(old_prefix, new_prefix, old_host, dry_run=args.dry_run)

    print("\n[4/4] 处理磁盘 JSON 文件...")
    file_stats = replace_host_in_files(old_prefix, new_prefix, dry_run=args.dry_run)

    # 汇总
    print(f"\n{'=' * 60}")
    print("处理结果汇总：")
    all_stats = {**(text_stats or {}), **(json_stats or {}), **(nested_stats or {}), **(file_stats or {})}
    total = 0
    for key, val in all_stats.items():
        status = f"{val} 条" if val >= 0 else "失败"
        print(f"  {key}: {status}")
        if val > 0:
            total += val
    print(f"  总计更新: {total} 条")
    if args.dry_run:
        print("  (预览模式，未实际修改数据)")
    print(f"=" * 60)


def _dry_run_text(old_prefix):
    """预览模式：统计文本字段匹配数"""
    stats = {}
    for table, field in TEXT_FIELDS:
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT COUNT(*) as cnt FROM `{table}` WHERE `{field}` LIKE %s",
                    (f"%{old_prefix}%",)
                )
                count = cursor.fetchone()["cnt"]
                print(f"  [{table}.{field}] 匹配 {count} 条记录")
                stats[f"{table}.{field}"] = count
        except Exception as e:
            print(f"  [{table}.{field}] 错误: {e}")
            stats[f"{table}.{field}"] = -1
    return stats


if __name__ == "__main__":
    main()
