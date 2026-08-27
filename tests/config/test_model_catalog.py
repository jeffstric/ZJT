"""场景模型目录：双档解析与供应商折叠。"""
import unittest

from config.constant import DEFAULT_TEXT_TO_IMAGE_TASK_ID
from config.unified_config import TaskTypeId
from config.model_catalog import (
    TRACK_CUSTOM,
    TRACK_QUALITY,
    TRACK_VALUE,
    ModelScene,
    annotate_llm_models,
    annotate_task_models,
    build_tracks_payload,
    get_model_family,
    infer_track_from_item,
    match_canonical,
    normalize_scene,
    normalize_track,
    pick_llm_route,
    resolve_track_item,
    scene_catalog_map,
    tracks_message,
)


class TestModelCatalog(unittest.TestCase):
    def test_qwen38_ollama_family(self):
        self.assertEqual(get_model_family("qwen3.8:27b"), "Qwen")

    def test_normalize_scene_and_track(self):
        self.assertEqual(normalize_scene("script_split"), ModelScene.LLM_SCRIPT_SPLIT)
        self.assertEqual(normalize_scene("llm.marketing"), ModelScene.LLM_MARKETING)
        self.assertIsNone(normalize_scene("unknown"))
        self.assertEqual(normalize_track("性价比"), TRACK_VALUE)
        self.assertEqual(normalize_track("效果"), TRACK_QUALITY)
        self.assertEqual(normalize_track("nope"), TRACK_VALUE)

    def test_script_split_prefers_deepseek_pair(self):
        models = [
            {"name": "deepseek-v4-flash", "vendor_name": "deepseek", "vendor_id": 1, "model_id": 10},
            {"name": "deepseek-v4-flash", "vendor_name": "zjt_api", "vendor_id": 2, "model_id": 10},
            {"name": "deepseek-v4-pro", "vendor_name": "deepseek", "vendor_id": 1, "model_id": 11},
            {"name": "qwen3.5-plus", "vendor_name": "zjt_api", "vendor_id": 2, "model_id": 20},
        ]
        value, track = resolve_track_item(ModelScene.LLM_SCRIPT_SPLIT, models, TRACK_VALUE, "llm")
        self.assertEqual(track, TRACK_VALUE)
        self.assertEqual(value["vendor_name"], "deepseek")
        self.assertEqual(value["name"], "deepseek-v4-flash")

        quality, track = resolve_track_item(ModelScene.LLM_SCRIPT_SPLIT, models, TRACK_QUALITY, "llm")
        self.assertEqual(track, TRACK_QUALITY)
        self.assertEqual(quality["name"], "deepseek-v4-pro")

    def test_marketing_uses_doubao_not_deepseek(self):
        models = [
            {"name": "deepseek-v4-flash", "vendor_name": "deepseek", "vendor_id": 1, "model_id": 10},
            {"name": "doubao-seed-2-0-lite", "vendor_name": "volcengine", "vendor_id": 3, "model_id": 30},
            {"name": "doubao-seed-2-0-pro", "vendor_name": "volcengine", "vendor_id": 3, "model_id": 31},
        ]
        value, track = resolve_track_item(ModelScene.LLM_MARKETING, models, TRACK_VALUE, "llm")
        self.assertEqual(track, TRACK_VALUE)
        self.assertEqual(value["name"], "doubao-seed-2-0-lite")
        quality, track = resolve_track_item(ModelScene.LLM_MARKETING, models, TRACK_QUALITY, "llm")
        self.assertEqual(quality["name"], "doubao-seed-2-0-pro")

    def test_missing_value_falls_back_to_quality(self):
        models = [
            {"name": "deepseek-v4-pro", "vendor_name": "deepseek", "vendor_id": 1, "model_id": 11},
        ]
        hit, track = resolve_track_item(ModelScene.LLM_CHAT, models, TRACK_VALUE, "llm")
        self.assertEqual(hit["name"], "deepseek-v4-pro")
        self.assertEqual(track, TRACK_QUALITY)

    def test_pick_llm_route_prefers_official_then_cheapest(self):
        candidates = [
            {"name": "deepseek-v4-flash", "vendor_name": "zjt_api", "vendor_id": 2, "input_token_threshold": 80000},
            {"name": "deepseek-v4-flash", "vendor_name": "agnes", "vendor_id": 9, "input_token_threshold": 120000},
        ]
        official = pick_llm_route(candidates, ("deepseek", "zjt_api"))
        self.assertEqual(official["vendor_name"], "zjt_api")
        cheapest = pick_llm_route(candidates, ())
        self.assertEqual(cheapest["vendor_name"], "agnes")

    def test_annotate_llm_marks_default_route(self):
        models = [
            {"name": "deepseek-v4-flash", "vendor_name": "zjt_api", "vendor_id": 2, "model_id": 10},
            {"name": "deepseek-v4-flash", "vendor_name": "deepseek", "vendor_id": 1, "model_id": 10},
        ]
        annotated = annotate_llm_models(models, ModelScene.LLM_CHAT)
        official = next(m for m in annotated if m["vendor_name"] == "deepseek")
        other = next(m for m in annotated if m["vendor_name"] == "zjt_api")
        self.assertTrue(official["is_default_route"])
        self.assertFalse(other["is_default_route"])
        self.assertEqual(official["track"], TRACK_VALUE)
        self.assertEqual(official["family"], "DeepSeek")

    def test_video_task_tracks(self):
        tasks = [
            {"short_key": "minimax_h3", "name": "MiniMax H3", "id": 20},
            {"short_key": "seedance_2_0", "name": "Seedance 2.0", "id": 22},
            {"short_key": "kling", "name": "可灵", "id": 23},
        ]
        annotated = annotate_task_models(tasks, ModelScene.VIDEO_IMAGE_TO_VIDEO)
        by_key = {t["short_key"]: t for t in annotated}
        self.assertEqual(by_key["minimax_h3"]["track"], TRACK_VALUE)
        self.assertEqual(by_key["seedance_2_0"]["track"], TRACK_QUALITY)
        self.assertIsNone(by_key["kling"]["track"])
        self.assertEqual(by_key["seedance_2_0"]["family"], "Seedance")

        hit, track = resolve_track_item(
            ModelScene.VIDEO_IMAGE_TO_VIDEO, tasks, TRACK_QUALITY, "task",
        )
        self.assertEqual(track, TRACK_QUALITY)
        self.assertEqual(hit["short_key"], "seedance_2_0")

    def test_reference_to_video_tracks(self):
        tasks = [
            {"short_key": "vidu_q2", "name": "Vidu Q2", "id": 18},
            {"short_key": "minimax_h3_r2v", "name": "MiniMax H3 参考生视频", "id": 37},
            {"short_key": "seedance_2_0", "name": "Seedance 2.0", "id": 22},
        ]
        annotated = annotate_task_models(tasks, ModelScene.VIDEO_REFERENCE_TO_VIDEO)
        by_key = {t["short_key"]: t for t in annotated}
        self.assertEqual(by_key["minimax_h3_r2v"]["track"], TRACK_VALUE)
        self.assertEqual(by_key["seedance_2_0"]["track"], TRACK_QUALITY)
        self.assertIsNone(by_key["vidu_q2"]["track"])
        value, track = resolve_track_item(
            ModelScene.VIDEO_REFERENCE_TO_VIDEO, tasks, TRACK_VALUE, "task",
        )
        self.assertEqual(track, TRACK_VALUE)
        self.assertEqual(value["short_key"], "minimax_h3_r2v")

    def test_tracks_payload_and_message(self):
        models = [
            {"name": "deepseek-v4-flash", "vendor_name": "deepseek", "vendor_id": 1, "model_id": 10},
            {"name": "deepseek-v4-pro", "vendor_name": "deepseek", "vendor_id": 1, "model_id": 11},
        ]
        payload = build_tracks_payload(ModelScene.LLM_SCRIPT_SPLIT, models, "llm")
        self.assertEqual(payload["scene"], ModelScene.LLM_SCRIPT_SPLIT)
        self.assertTrue(payload["tracks"]["value"]["available"])
        self.assertEqual(payload["tracks"]["quality"]["canonical"], "deepseek-v4-pro")
        message = tracks_message(payload)
        self.assertIn("deepseek-v4-flash", message)
        self.assertIn("deepseek-v4-pro", message)

    def test_infer_custom_when_not_in_tracks(self):
        item = {"name": "qwen3.5-plus", "vendor_name": "zjt_api"}
        self.assertEqual(infer_track_from_item(ModelScene.LLM_CHAT, item, "llm"), TRACK_CUSTOM)

    def test_scene_catalog_map_covers_required_scenes(self):
        catalog = scene_catalog_map()
        self.assertIn(ModelScene.LLM_SCRIPT_SPLIT, catalog)
        self.assertIn(ModelScene.LLM_MARKETING, catalog)
        self.assertEqual(
            catalog[ModelScene.LLM_MARKETING]["tracks"]["value"]["canonical"],
            "doubao-seed-2-0-lite",
        )
        self.assertEqual(catalog[ModelScene.IMAGE_TEXT_TO_IMAGE]["tracks"]["value"]["canonical"], "gpt-image-2")
        self.assertEqual(catalog[ModelScene.IMAGE_TEXT_TO_IMAGE]["tracks"]["quality"]["canonical"], "gpt-image-2")
        self.assertEqual(catalog[ModelScene.IMAGE_IMAGE_EDIT]["tracks"]["value"]["canonical"], "gpt-image-2")
        self.assertEqual(catalog[ModelScene.IMAGE_IMAGE_EDIT]["tracks"]["quality"]["canonical"], "gpt-image-2")
        self.assertEqual(catalog[ModelScene.IMAGE_SCRIPT_WRITER]["tracks"]["value"]["canonical"], "gpt-image-2")
        self.assertEqual(catalog[ModelScene.IMAGE_SCRIPT_WRITER]["tracks"]["quality"]["canonical"], "seedream-5.0-pro")
        self.assertEqual(DEFAULT_TEXT_TO_IMAGE_TASK_ID, TaskTypeId.GPT_IMAGE_2_EDIT)
        self.assertEqual(catalog[ModelScene.VIDEO_IMAGE_TO_VIDEO]["tracks"]["value"]["canonical"], "minimax_h3")
        self.assertEqual(catalog[ModelScene.VIDEO_IMAGE_TO_VIDEO]["tracks"]["quality"]["canonical"], "seedance_2_0")
        self.assertEqual(catalog[ModelScene.VIDEO_TEXT_TO_VIDEO]["tracks"]["value"]["canonical"], "minimax_h3")
        self.assertEqual(catalog[ModelScene.VIDEO_TEXT_TO_VIDEO]["tracks"]["quality"]["canonical"], "seedance_2_0")
        self.assertEqual(catalog[ModelScene.VIDEO_REFERENCE_TO_VIDEO]["tracks"]["value"]["canonical"], "minimax_h3_r2v")
        self.assertEqual(catalog[ModelScene.VIDEO_REFERENCE_TO_VIDEO]["tracks"]["quality"]["canonical"], "seedance_2_0")
        self.assertFalse(match_canonical("", "x"))
        self.assertFalse(match_canonical("seedance_2_0_fast", "seedance_2_0"))
        self.assertTrue(match_canonical("deepseek-v4-flash（性价比）", "deepseek-v4-flash"))


if __name__ == "__main__":
    unittest.main()
