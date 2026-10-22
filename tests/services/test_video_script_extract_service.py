# -*- coding: utf-8 -*-
"""视频提取剧本服务（services/video_script_extract_service.py）单元测试。

覆盖：纯函数（切片计划 / ASR 分段合并 / 转写稿格式化 / 帧抽稀 /
多模态消息构造 / 剧本清洗）+ DB 任务状态表（创建 / 状态读取 /
每用户并发限制 / TTL 过期失联）。任务状态已落库（script_extract_task），
测试用同接口的内存假模型替换 DB 层，不依赖真实数据库。

pipeline 各阶段的 ffmpeg / httpx / LLM 交互不在此覆盖（外部依赖打桩成本高，
纯函数已覆盖拼装逻辑；集成验证走浏览器实测）。
"""
import asyncio
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model.script_extract_task import ScriptExtractTask  # noqa: E402
from services.video_script_extract_service import (  # noqa: E402
    ScriptExtractError,
    build_extract_sample_points,
    build_script_llm_messages,
    build_slice_ranges,
    clean_script_text,
    create_extract_task,
    format_asr_transcript,
    format_time_label,
    frame_budget,
    get_extract_task,
    merge_asr_slice_results,
    thin_points_by_time,
)
from config.constant import VideoScriptExtractConstants as C  # noqa: E402


class _FakeScriptExtractTaskModel:
    """内存版假模型：与 ScriptExtractTaskModel 同接口（替代 DB 层）。"""

    rows: dict = {}

    @classmethod
    def reset(cls):
        cls.rows = {}

    @classmethod
    def create(cls, task_id, user_id, stage):
        cls.rows[task_id] = {
            "task_id": task_id,
            "user_id": user_id,
            "status": "running",
            "stage": stage,
            "progress": {},
            "error": None,
            "result": None,
            "updated_at": datetime.now(),
        }
        return 1

    @classmethod
    def get_by_task_id(cls, task_id):
        row = cls.rows.get(task_id)
        return ScriptExtractTask(**row) if row else None

    @classmethod
    def update(cls, task_id, **fields):
        row = cls.rows.get(task_id)
        if row is None:
            return 0
        row.update(fields)
        row["updated_at"] = datetime.now()
        return 1

    @classmethod
    def get_running_by_user(cls, user_id, stale_seconds):
        fresh = [
            row for row in cls.rows.values()
            if row["user_id"] == user_id and row["status"] == "running"
            and not ScriptExtractTask(**row).is_expired(stale_seconds)
        ]
        if not fresh:
            return None
        fresh.sort(key=lambda r: r["updated_at"], reverse=True)
        return ScriptExtractTask(**fresh[0])

    @classmethod
    def mark_stale_running_failed(cls, user_id, stale_seconds, error):
        affected = 0
        for row in cls.rows.values():
            if row["user_id"] != user_id or row["status"] != "running":
                continue
            if ScriptExtractTask(**row).is_expired(stale_seconds):
                row["status"] = "failed"
                row["error"] = error
                affected += 1
        return affected

    @classmethod
    def cleanup_expired(cls, ttl_seconds, limit=500):
        expired = [
            tid for tid, row in cls.rows.items()
            if ScriptExtractTask(**row).is_expired(ttl_seconds)
        ]
        for tid in expired[:limit]:
            cls.rows.pop(tid, None)
        return len(expired[:limit])


class TestBuildSliceRanges(unittest.TestCase):
    def test_short_audio_single_slice(self):
        self.assertEqual(build_slice_ranges(30.0, 60.0), [(0.0, 30.0)])

    def test_exact_multiple(self):
        self.assertEqual(
            build_slice_ranges(120.0, 60.0),
            [(0.0, 60.0), (60.0, 120.0)],
        )

    def test_tail_slice_shorter(self):
        ranges = build_slice_ranges(150.0, 60.0)
        self.assertEqual(ranges, [(0.0, 60.0), (60.0, 120.0), (120.0, 150.0)])

    def test_zero_and_negative_duration(self):
        self.assertEqual(build_slice_ranges(0, 60.0), [])
        self.assertEqual(build_slice_ranges(-5.0, 60.0), [])


class TestMergeAsrSliceResults(unittest.TestCase):
    def test_offsets_applied_and_sorted(self):
        # 第二段偏移 60s，乱序提供（第二段先到）
        merged = merge_asr_slice_results([
            (60.0, [(1.0, 2.0, "乙"), (0.0, 0.8, "甲")]),
            (0.0, [(59.0, 59.9, "开篇")]),
        ])
        self.assertEqual(
            merged,
            [(59.0, 59.9, "开篇"), (60.0, 60.8, "甲"), (61.0, 62.0, "乙")],
        )

    def test_empty_text_dropped(self):
        merged = merge_asr_slice_results([(0.0, [(0.0, 1.0, "  "), (1.0, 2.0, "词")])])
        self.assertEqual(merged, [(1.0, 2.0, "词")])


class TestFormatTranscript(unittest.TestCase):
    def test_format_time_label(self):
        self.assertEqual(format_time_label(0), "00:00")
        self.assertEqual(format_time_label(65.4), "01:05")
        self.assertEqual(format_time_label(3700), "1:01:40")

    def test_format_asr_transcript_lines(self):
        text = format_asr_transcript([(0.0, 1.0, "你好"), (61.0, 62.0, "世界")])
        self.assertEqual(text, "[00:00] 你好\n[01:01] 世界")


class TestThinPointsByTime(unittest.TestCase):
    def test_no_thinning_under_limit(self):
        self.assertEqual(thin_points_by_time([1.0, 2.0, 3.0], 8), [1.0, 2.0, 3.0])

    def test_even_thinning_keeps_first_and_last(self):
        picked = thin_points_by_time([float(i) for i in range(21)], 6)
        self.assertEqual(len(picked), 6)
        self.assertEqual(picked[0], 0.0)
        self.assertEqual(picked[-1], 20.0)

    def test_limit_one_keeps_first(self):
        self.assertEqual(thin_points_by_time([1.0, 2.0, 3.0], 1), [1.0])


class TestBuildExtractSamplePoints(unittest.TestCase):
    """采样计划：切换点为主、不足补均匀点、合并去重、超量抽稀（保首尾）。"""

    def test_dense_scene_points_thinned_to_limit(self):
        # 96 个切换点 → 抽稀到 24，保首尾
        pts = build_extract_sample_points(
            [float(i) for i in range(96)], 250.0, 24, 0.2,
        )
        self.assertEqual(len(pts), 24)
        self.assertEqual(pts[0], 0.05)
        self.assertEqual(pts[-1], 95.0)

    def test_sparse_scene_points_padded_uniformly(self):
        # 长视频切换点只有 2 个 → 补均匀点到 10
        pts = build_extract_sample_points([100.0, 500.0], 871.0, 10, 0.2)
        self.assertEqual(len(pts), 10)
        self.assertEqual(pts[0], 0.0)
        self.assertEqual(pts[-1], 870.95)

    def test_no_scene_points_all_uniform(self):
        # 无切换点（超检测上限且检测失败）：纯均匀采样
        pts = build_extract_sample_points([], 871.0, 6, 0.2)
        self.assertEqual(len(pts), 6)
        self.assertAlmostEqual(pts[0], 0.0)
        self.assertAlmostEqual(pts[-1], 870.95)

    def test_min_gap_dedup(self):
        # 10s 视频要 100 帧：均匀补点后被 min_gap 合并（相邻间隔 ≥1s），不会产出过密帧
        pts = build_extract_sample_points([0.0, 0.05, 0.1, 5.0], 10.0, 100, 1.0)
        self.assertEqual(len(pts), 10)
        self.assertEqual(pts[0], 0.0)
        self.assertLessEqual(pts[-1], 9.95)
        gaps = [round(b - a, 2) for a, b in zip(pts, pts[1:])]
        self.assertTrue(all(g >= 1.0 for g in gaps))

    def test_scene_points_clamped_into_range(self):
        # 界外切换点 clamp 进 [0.05, duration-0.05]
        pts = build_extract_sample_points([-5.0, 999.0], 10.0, 10, 0.2)
        self.assertGreaterEqual(min(pts), 0.0)
        self.assertLessEqual(max(pts), 9.95)


class TestBuildScriptLlmMessages(unittest.TestCase):
    def test_content_alternates_text_and_image(self):
        frames = [
            {"index": 1, "time_label": "00:00", "data_url": "data:image/jpeg;base64,AAA"},
            {"index": 2, "time_label": "00:35", "data_url": "data:image/jpeg;base64,BBB"},
        ]
        messages = build_script_llm_messages("[00:00] 你好", frames, 95.0)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        user = messages[1]
        self.assertEqual(user["role"], "user")
        types = [item["type"] for item in user["content"]]
        # 首个 text（任务说明+转写稿）+ 每帧（text 标签 + image_url）
        self.assertEqual(types, ["text", "text", "image_url", "text", "image_url"])
        self.assertIn("[00:00] 你好", user["content"][0]["text"])
        self.assertIn("关键帧2（时间点 00:35）", user["content"][3]["text"])
        self.assertEqual(
            user["content"][4]["image_url"]["url"],
            "data:image/jpeg;base64,BBB",
        )

    def test_missing_transcript_hint(self):
        messages = build_script_llm_messages("", [], 30.0)
        self.assertIn("没有可用的语音转写稿", messages[1]["content"][0]["text"])


class TestCleanScriptText(unittest.TestCase):
    def test_strips_code_fence(self):
        self.assertEqual(clean_script_text("```markdown\n# 剧本\n```\n"), "# 剧本")

    def test_strips_wrapping_quotes(self):
        self.assertEqual(clean_script_text("「剧本内容」"), "剧本内容")

    def test_truncates_to_limit(self):
        text = "字" * (C.MAX_SCRIPT_CHARS + 100)
        self.assertEqual(len(clean_script_text(text)), C.MAX_SCRIPT_CHARS)

    def test_plain_text_untouched(self):
        self.assertEqual(clean_script_text("# 标题\n正文"), "# 标题\n正文")


class TestFrameBudget(unittest.TestCase):
    """分辨率档位 → 压缩预算（节点参数用），未知档位回退默认档。"""

    def test_known_heights(self):
        self.assertEqual(frame_budget(720), (921_600, 0.5))
        self.assertEqual(frame_budget(480), (409_600, 0.25))
        self.assertEqual(frame_budget(360), (230_400, 0.15))

    def test_unknown_height_falls_back_to_default(self):
        default = frame_budget(720)
        self.assertEqual(frame_budget(1080), default)
        self.assertEqual(frame_budget(0), default)
        self.assertEqual(frame_budget(-1), default)


class TestTaskRegistry(unittest.TestCase):
    def setUp(self):
        _FakeScriptExtractTaskModel.reset()
        patcher = patch(
            "services.video_script_extract_service.ScriptExtractTaskModel",
            _FakeScriptExtractTaskModel,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_create_and_get_task(self):
        async def _noop(*_args, **_kwargs):
            return None

        with patch("services.video_script_extract_service._run_extract_task", _noop):
            task_id, err = asyncio.run(create_extract_task("/tmp/v.mp4", 7, "tok"))
        self.assertIsNone(err)
        task = asyncio.run(get_extract_task(task_id))
        self.assertEqual(task["status"], "running")
        self.assertEqual(task["stage"], C.STAGE_FRAMES)
        self.assertEqual(task["user_id"], 7)
        self.assertIsNone(task["error"])
        # 状态视图不暴露内部字段
        self.assertNotIn("asyncio_task", task)
        self.assertNotIn("created_at", task)

    def test_second_task_rejected_while_running(self):
        async def _pending(*_args, **_kwargs):
            # 模拟任务仍在运行：不结束事件循环内的注册表状态
            await asyncio.sleep(0)

        with patch("services.video_script_extract_service._run_extract_task", _pending):
            first, _ = asyncio.run(create_extract_task("/tmp/v.mp4", 7, "tok"))
            second, err = asyncio.run(create_extract_task("/tmp/v2.mp4", 7, "tok"))
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIn("已有剧本提取任务进行中", err)

    def test_new_task_allowed_after_failure(self):
        async def _fail(task_id, *_args, **_kwargs):
            # 模拟任务立即失败（真实语义：pipeline 把 DB 行标记 failed）
            _FakeScriptExtractTaskModel.update(task_id, status="failed", error="boom")

        with patch("services.video_script_extract_service._run_extract_task", _fail):
            first, _ = asyncio.run(create_extract_task("/tmp/v.mp4", 7, "tok"))
            second, err = asyncio.run(create_extract_task("/tmp/v2.mp4", 7, "tok"))
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNone(err)

    def test_expired_task_invisible(self):
        async def _noop(*_args, **_kwargs):
            return None

        with patch("services.video_script_extract_service._run_extract_task", _noop):
            task_id, _ = asyncio.run(create_extract_task("/tmp/v.mp4", 7, "tok"))
        # running 记录超 TTL 未更新（执行进程失联/服务重启）→ 视为不存在
        _FakeScriptExtractTaskModel.rows[task_id]["updated_at"] = (
            datetime.now() - timedelta(seconds=C.TASK_TTL_SECONDS + 10)
        )
        self.assertIsNone(asyncio.run(get_extract_task(task_id)))

    def test_stale_running_released_and_marked_failed(self):
        async def _noop(*_args, **_kwargs):
            return None

        with patch("services.video_script_extract_service._run_extract_task", _noop):
            old_id, _ = asyncio.run(create_extract_task("/tmp/v.mp4", 7, "tok"))
        # 上一个任务的执行进程失联（updated_at 超 TTL）→ 新任务可创建，旧任务判失败
        _FakeScriptExtractTaskModel.rows[old_id]["updated_at"] = (
            datetime.now() - timedelta(seconds=C.TASK_TTL_SECONDS + 10)
        )
        with patch("services.video_script_extract_service._run_extract_task", _noop):
            new_id, err = asyncio.run(create_extract_task("/tmp/v2.mp4", 7, "tok"))
        self.assertIsNone(err)
        self.assertIsNotNone(new_id)
        self.assertNotEqual(new_id, old_id)
        self.assertEqual(_FakeScriptExtractTaskModel.rows[old_id]["status"], "failed")

    def test_create_requires_user(self):
        async def _noop(*_args, **_kwargs):
            return None

        with patch("services.video_script_extract_service._run_extract_task", _noop):
            task_id, err = asyncio.run(create_extract_task("/tmp/v.mp4", None, "tok"))
        self.assertIsNone(task_id)
        self.assertIsNotNone(err)


if __name__ == "__main__":
    unittest.main()
