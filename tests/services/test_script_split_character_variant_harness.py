"""角色形象变化变体——挡板集成测试。

设计意图（与纯单测的区别）：
- 「盯死拆分结果」：LLM 输出不可控，这里用固定 fixture 模拟 merge 后的
  拆分结果（变化点/延续/不在场/revert/非DB角色全覆盖），让被测路径完全确定。
- 「挡板生图后端」：FakeVariantBackend 替换三个外部依赖——角色 DB 查询、
  item_type=7 变体图提交、grid_image_task 轮询，并真实模拟跨 tick 状态推进
  （提交 → 处理中 → 完成并写回角色 reference_images），从而驱动**真实的**
  sanitize → ensure（多 tick）→ collect_ready_variant_map →
  build_storyboard_scenes_from_parsed_script 全链路。
- 断言对准计数器而非「拆分完成」：该特性失败静默降级，bug 会伪装成正常，
  所以每个用例都核对提交次数（幂等/去重不变量）与 plan 状态计数。
"""
import copy
import json
import os
from types import SimpleNamespace

import pytest

# 挡板测试默认关闭，避免常规 pytest 全量运行时执行；需要时显式开启：
#   SCRIPT_SPLIT_VARIANT_HARNESS=1 python -m pytest tests/services/test_script_split_character_variant_harness.py
pytestmark = pytest.mark.skipif(
    os.environ.get("SCRIPT_SPLIT_VARIANT_HARNESS") != "1",
    reason="挡板集成测试默认关闭；设 SCRIPT_SPLIT_VARIANT_HARNESS=1 开启",
)

from api import storyboard as storyboard_api
from model.grid_image_tasks import GridImageTaskStatus
from services.script_split_character_variant_service import (
    EFFECTIVE_CHANGES_FIELD,
    PLAN_METADATA_KEY,
    collect_ready_variant_map,
    ensure_character_variants,
    sanitize_and_propagate_appearance_changes,
)


# ---------------------------------------------------------------------------
# 挡板 1：假生图后端（角色 DB + 变体提交 + grid 任务轮询，带跨 tick 状态机）
# ---------------------------------------------------------------------------
class FakeVariantBackend:
    """stateful 假后端：记录每次提交，按 poll 次数推进任务终态并写回变体。"""

    def __init__(self, complete_after_polls=2, fail_labels=()):
        # db_id -> 角色（reference_images 为 JSON 字符串，与真实模型一致）
        self.characters = {}
        self.characters_by_name = {}
        # task_key -> grid 任务
        self.grid_tasks = {}
        # 提交记录 [(character_name, label)] —— 去重/幂等断言的核心证据
        self.submissions = []
        self.complete_after_polls = complete_after_polls
        self.fail_labels = set(fail_labels)
        self._seq = 0

    def add_character(self, db_id, name, main_image="http://img/main.png"):
        character = SimpleNamespace(
            name=name, reference_image=main_image, reference_images="[]",
        )
        self.characters[int(db_id)] = character
        self.characters_by_name[name] = character
        return character

    # --- 被 monkeypatch 的三个接口 ---

    def get_character(self, db_id):
        return self.characters.get(int(db_id))

    def submit(self, **kwargs):
        """替换 generate_character_variant_image：登记提交并建档 grid 任务。"""
        label = kwargs["variant_label"]
        character_name = kwargs["character_name"]
        self.submissions.append((character_name, label))
        self._seq += 1
        task_key = f"fake_task_{self._seq}"
        status = (
            GridImageTaskStatus.FAILED
            if label in self.fail_labels
            else GridImageTaskStatus.QUEUED
        )
        self.grid_tasks[task_key] = SimpleNamespace(
            status=status, polls=0, label=label, character_name=character_name,
        )
        return {"success": True, "task_id": task_key}

    def get_grid_task(self, task_key):
        """替换 GridImageTasksModel.get_by_task_key：模拟 poll 推进与写回。"""
        grid_task = self.grid_tasks.get(str(task_key))
        if grid_task is None:
            return None
        if grid_task.status in (GridImageTaskStatus.QUEUED, GridImageTaskStatus.PROCESSING):
            grid_task.polls += 1
            if grid_task.polls >= self.complete_after_polls:
                grid_task.status = GridImageTaskStatus.COMPLETED
                # 模拟真实管线的产物写回：变体 URL 追加进角色 reference_images
                character = self.characters_by_name[grid_task.character_name]
                variants = json.loads(character.reference_images)
                variants.append({
                    "id": f"v{grid_task.polls}",
                    "label": grid_task.label,
                    "url": f"http://fakeimg/{grid_task.character_name}/{grid_task.label}.png",
                })
                character.reference_images = json.dumps(variants, ensure_ascii=False)
        return grid_task

    def install(self, monkeypatch):
        monkeypatch.setattr(
            "model.character.CharacterModel.get_by_id",
            staticmethod(self.get_character),
        )
        monkeypatch.setattr(
            "model.grid_image_tasks.GridImageTasksModel.get_by_task_key",
            staticmethod(self.get_grid_task),
        )
        monkeypatch.setattr(
            "script_writer_core.mcp_tool.generate_character_variant_image",
            self.submit,
        )


# ---------------------------------------------------------------------------
# 挡板 2：固定的拆分结果（替代 LLM + merge，覆盖全部传播分支）
# ---------------------------------------------------------------------------
def _fixed_split_result():
    """merge 后的确定结果。

    镜头序列：
      s1 小林(11) 换晚礼服（变化点，有描述）
      s2 小林在场（应延续晚礼服）
      s3 小林不在场（无传播）
      s4 小林 revert 恢复默认 → s5 在场（回到主形象）
      s6 阿珍(22) 变身战斗形态（变化点，**空描述**，回归去重 bug）
      s7 阿珍在场（空描述延续——旧代码会在此重复收集 spec）
      s8 新角色 char_003 无 db_id（应被剔除）
    """
    def shot(shot_id, present, changes=None):
        data = {
            "shot_id": shot_id, "shot_number": int(shot_id[1:]),
            "duration": 5, "location_id": "loc_001",
            "camera_angle": "平视", "shot_type": "中景",
            "description": f"镜头{shot_id}", "characters_present": present,
        }
        if changes is not None:
            data["character_appearance_changes"] = changes
        return data

    return {
        "characters": [
            {"id": "char_001", "name": "小林_Xiaolin", "character_db_id": 11},
            {"id": "char_002", "name": "阿珍_Azhen", "character_db_id": 22},
            {"id": "char_003", "name": "新角色", "character_db_id": None},
        ],
        "locations": [{"id": "loc_001", "name": "宴会厅", "location_db_id": 23}],
        "shot_groups": [{
            "group_id": "grp_001", "group_name": "宴会",
            "shots": [
                shot("s1", ["char_001"], [
                    {"character_id": "char_001", "label": "晚礼服",
                     "description": "深蓝色露肩晚礼服，盘发"}]),
                shot("s2", ["char_001"]),
                shot("s3", ["char_002"]),
                shot("s4", ["char_001"], [
                    {"character_id": "char_001", "label": "默认", "revert": True}]),
                shot("s5", ["char_001"]),
                shot("s6", ["char_002"], [
                    {"character_id": "char_002", "label": "战斗形态",
                     "description": ""}]),
                shot("s7", ["char_002"]),
                shot("s8", ["char_003"], [
                    {"character_id": "char_003", "label": "雨衣"}]),
            ],
        }],
    }


def _make_task(world_id=3):
    return SimpleNamespace(
        user_id=7, auth_token="tok",
        get_request_config=lambda: {"world_id": world_id},
    )


def _drive_until_settled(task, final_result, max_ticks=20):
    """模拟 worker tick 循环：反复调用真实 ensure 直到全部终态。"""
    for _ in range(max_ticks):
        summary = ensure_character_variants(task, final_result)
        if summary["all_settled"]:
            return summary
    raise AssertionError(f"超过 {max_ticks} 个 tick 仍未终态，疑似状态机卡死")


def _scenes_by_shot(final_result):
    """用真实的发布构造函数生成 scenes，并按 shot 顺序返回。"""
    variants = collect_ready_variant_map(final_result)
    return storyboard_api.build_storyboard_scenes_from_parsed_script(
        final_result, style="", character_variants=variants,
    )


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------
def test_harness_golden_path_full_pipeline(monkeypatch):
    """全链路：固定拆分结果 → 传播 → 多 tick 生成 → ready 映射 → 分镜参考图。"""
    backend = FakeVariantBackend(complete_after_polls=2)
    backend.add_character(11, "小林_Xiaolin")
    backend.add_character(22, "阿珍_Azhen")
    backend.install(monkeypatch)

    final_result = sanitize_and_propagate_appearance_changes(_fixed_split_result())
    summary = _drive_until_settled(_make_task(), final_result)

    # 提交次数 == 去重后 spec 数（2 个），空描述延续镜头不得造成重复提交
    assert backend.submissions == [
        ("小林_Xiaolin", "晚礼服"), ("阿珍_Azhen", "战斗形态"),
    ]
    # 非 DB 角色被剔除，未出现在 plan 中
    plan = final_result["metadata"][PLAN_METADATA_KEY]
    assert {entry["label"] for entry in plan} == {"晚礼服", "战斗形态"}
    assert summary["ready"] == 2 and summary["failed"] == 0

    # 分镜物化：变化点与延续镜头选中变体，revert 后/不在场/新角色回主图
    scenes = _scenes_by_shot(final_result)
    sel = [
        (scene["prompt"].get("reference_selections") or {}).get("characters", {})
        for scene in scenes
    ]
    assert sel[0]["11"]["label"] == "晚礼服"   # s1 变化点
    assert sel[1]["11"]["label"] == "晚礼服"   # s2 延续
    assert sel[2] == {}                        # s3 小林不在场
    assert sel[3] == {}                        # s4 revert
    assert sel[4] == {}                        # s5 恢复后回主形象
    assert sel[5]["22"]["label"] == "战斗形态"  # s6 变化点（空描述）
    assert sel[6]["22"]["label"] == "战斗形态"  # s7 延续（空描述）
    assert sel[7] == {}                        # s8 非 DB 角色
    # URL 来自挡板写回，证明消费的是「真实生成并落库」的变体
    assert sel[0]["11"]["url"] == "http://fakeimg/小林_Xiaolin/晚礼服.png"


def test_harness_resume_from_checkpoint_no_duplicate_submission(monkeypatch):
    """跨 tick 幂等恢复：模拟 worker 重启（深拷贝检查点 + 新 task），不得重复提交。"""
    backend = FakeVariantBackend(complete_after_polls=3)
    backend.add_character(11, "小林_Xiaolin")
    backend.add_character(22, "阿珍_Azhen")
    backend.install(monkeypatch)

    final_result = sanitize_and_propagate_appearance_changes(_fixed_split_result())
    task = _make_task()

    # tick 1：提交 2 个变体后模拟进程重启
    summary = ensure_character_variants(task, final_result)
    assert summary["submitted"] == 2
    assert len(backend.submissions) == 2

    checkpoint = copy.deepcopy(final_result)  # 持久化 final_result（含 plan）
    resumed_task = _make_task()               # 新 task 对象，模拟新进程

    summary = _drive_until_settled(resumed_task, checkpoint)
    # 恢复后 plan 不重建、已提交条目不重复提交
    assert len(backend.submissions) == 2
    assert summary["ready"] == 2
    # 幂等不变量：再跑一遍 ensure，状态与副作用不变
    again = ensure_character_variants(resumed_task, checkpoint)
    assert again == summary
    assert len(backend.submissions) == 2


def test_harness_degradation_matrix_still_completes(monkeypatch):
    """降级矩阵：无主图 skipped + grid 失败 failed，拆分照样终态且计数正确。

    静默降级是该特性最危险之处——必须核对 summary 计数，而不是接受「完成」。
    """
    backend = FakeVariantBackend(complete_after_polls=2, fail_labels={"战斗形态"})
    backend.add_character(11, "小林_Xiaolin")
    # 阿珍无主参考图 → 提交预检直接 skipped（no_main_image）
    backend.add_character(22, "阿珍_Azhen", main_image="")
    backend.install(monkeypatch)

    final_result = sanitize_and_propagate_appearance_changes(_fixed_split_result())
    summary = _drive_until_settled(_make_task(), final_result)

    assert summary["all_settled"] is True
    assert summary["ready"] == 1      # 仅小林晚礼服
    assert summary["skipped"] == 1    # 阿珍无主图
    by_label = {
        entry["label"]: entry
        for entry in final_result["metadata"][PLAN_METADATA_KEY]
    }
    assert by_label["战斗形态"]["error"] == "no_main_image"

    # 分镜侧：阿珍的镜头回退主形象（不写 reference_selections），小林正常
    scenes = _scenes_by_shot(final_result)
    assert "reference_selections" in scenes[0]["prompt"]
    assert all(
        "reference_selections" not in scenes[i]["prompt"] for i in (2, 3, 4, 5, 6)
    )


def test_harness_grid_failure_error_is_readable(monkeypatch):
    """grid 任务失败：error 必须是可读状态名（回归 grid_task_-1 问题）。"""
    backend = FakeVariantBackend(fail_labels={"晚礼服", "战斗形态"})
    backend.add_character(11, "小林_Xiaolin")
    backend.add_character(22, "阿珍_Azhen")
    backend.install(monkeypatch)

    final_result = sanitize_and_propagate_appearance_changes(_fixed_split_result())
    summary = _drive_until_settled(_make_task(), final_result)

    assert summary["failed"] == 2 and summary["ready"] == 0
    for entry in final_result["metadata"][PLAN_METADATA_KEY]:
        assert entry["error"] == "grid_task_FAILED"


def test_harness_submit_batch_limit_per_tick(monkeypatch):
    """单 tick 提交数受 CHARACTER_VARIANT_SUBMIT_BATCH_SIZE 限制（防 watchdog 超时）。"""
    from config.constant import ScriptSplitConstants

    batch = int(ScriptSplitConstants.CHARACTER_VARIANT_SUBMIT_BATCH_SIZE)
    labels = [f"造型{i}" for i in range(batch + 1)]  # 比单批上限多 1 个

    merged = {
        "characters": [
            {"id": "char_001", "name": "小林_Xiaolin", "character_db_id": 11},
        ],
        "shot_groups": [{
            "group_id": "grp_001",
            "shots": [
                {
                    "shot_id": f"s{i}", "characters_present": ["char_001"],
                    "character_appearance_changes": [
                        {"character_id": "char_001", "label": label,
                         "description": ""}],
                }
                for i, label in enumerate(labels)
            ],
        }],
    }
    backend = FakeVariantBackend(complete_after_polls=100)  # 永不完成，专注提交节奏
    backend.add_character(11, "小林_Xiaolin")
    backend.install(monkeypatch)

    final_result = sanitize_and_propagate_appearance_changes(merged)
    task = _make_task()

    tick1 = ensure_character_variants(task, final_result)
    assert len(backend.submissions) == batch
    assert tick1["submitted"] == batch and tick1["pending"] == 1

    tick2 = ensure_character_variants(task, final_result)
    assert len(backend.submissions) == batch + 1
    assert tick2["pending"] == 0
