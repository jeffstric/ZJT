# -*- coding: utf-8 -*-
"""视频提取剧本服务（services/video_script_extract_service.py）单元测试。

覆盖：纯函数（切片计划 / ASR 分段合并 / 转写稿格式化 / 帧抽稀 /
多模态消息构造 / 剧本清洗）+ 内存任务注册表（创建 / 状态读取 /
每用户并发限制 / TTL 过期清理）。

pipeline 各阶段的 ffmpeg / httpx / LLM 交互不在此覆盖（外部依赖打桩成本高，
纯函数已覆盖拼装逻辑；集成验证走浏览器实测）。
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.video_script_extract_service import (  # noqa: E402
    _EXTRACT_TASKS,
    _RUNNING_BY_USER,
    ScriptExtractError,
    build_script_llm_messages,
    build_slice_ranges,
    clean_script_text,
    create_extract_task,
    format_asr_transcript,
    format_time_label,
    get_extract_task,
    merge_asr_slice_results,
    thin_frames_by_time,
)
from config.constant import VideoScriptExtractConstants as C  # noqa: E402


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


class TestThinFramesByTime(unittest.TestCase):
    def _frames(self, n):
        return [{"path": f"f{i}.jpg", "time_sec": float(i)} for i in range(n)]

    def test_no_thinning_under_limit(self):
        frames = self._frames(5)
        self.assertEqual(thin_frames_by_time(frames, 16), frames)

    def test_even_thinning_keeps_first_and_last(self):
        frames = self._frames(21)
        picked = thin_frames_by_time(frames, 6)
        self.assertEqual(len(picked), 6)
        self.assertEqual(picked[0]["time_sec"], 0.0)
        self.assertEqual(picked[-1]["time_sec"], 20.0)

    def test_no_duplicates(self):
        frames = self._frames(3)
        picked = thin_frames_by_time(frames, 8)
        self.assertEqual(len(picked), 3)


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


class TestTaskRegistry(unittest.TestCase):
    def setUp(self):
        _EXTRACT_TASKS.clear()
        _RUNNING_BY_USER.clear()

    tearDown = setUp

    def test_create_and_get_task(self):
        async def _noop(task_id, video_path, auth_token):
            return None

        with patch("services.video_script_extract_service._run_extract_task", _noop):
            task_id, err = asyncio.run(create_extract_task("/tmp/v.mp4", 7, "tok"))
        self.assertIsNone(err)
        task = get_extract_task(task_id)
        self.assertEqual(task["status"], "running")
        self.assertEqual(task["stage"], C.STAGE_FRAMES)
        self.assertEqual(task["user_id"], 7)
        self.assertIsNone(task["error"])
        # 状态视图不暴露内部字段
        self.assertNotIn("asyncio_task", task)
        self.assertNotIn("created_at", task)

    def test_second_task_rejected_while_running(self):
        async def _pending(task_id, video_path, auth_token):
            # 模拟任务仍在运行：不结束事件循环内的注册表状态
            await asyncio.sleep(0)

        with patch("services.video_script_extract_service._run_extract_task", _pending):
            first, _ = asyncio.run(create_extract_task("/tmp/v.mp4", 7, "tok"))
            second, err = asyncio.run(create_extract_task("/tmp/v2.mp4", 7, "tok"))
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIn("已有剧本提取任务进行中", err)

    def test_new_task_allowed_after_failure(self):
        async def _fail_then_clear(task_id, video_path, auth_token):
            # 模拟任务立即失败并释放并发位（复用真实 finally 语义）
            task = _EXTRACT_TASKS.get(task_id)
            if task is not None:
                task["status"] = "failed"
                task["error"] = "boom"
                _RUNNING_BY_USER.pop(task["user_id"], None)

        with patch("services.video_script_extract_service._run_extract_task", _fail_then_clear):
            first, _ = asyncio.run(create_extract_task("/tmp/v.mp4", 7, "tok"))
            second, err = asyncio.run(create_extract_task("/tmp/v2.mp4", 7, "tok"))
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNone(err)

    def test_expired_task_invisible(self):
        async def _noop(task_id, video_path, auth_token):
            return None

        with patch("services.video_script_extract_service._run_extract_task", _noop):
            task_id, _ = asyncio.run(create_extract_task("/tmp/v.mp4", 7, "tok"))
        _EXTRACT_TASKS[task_id]["created_at"] -= (C.TASK_TTL_SECONDS + 10)
        self.assertIsNone(get_extract_task(task_id))


if __name__ == "__main__":
    unittest.main()
