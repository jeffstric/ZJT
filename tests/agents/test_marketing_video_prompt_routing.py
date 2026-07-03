from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_community_video_sop_remains_enterprise_only_placeholder():
    sop = _read("agents/skills/marketing-pm/sops/sop-video-generation.md")

    assert "营销视频生成流程（商业版专属）" in sop
    assert "视频生成功能仅商业版本支持" in sop
    assert "不要尝试调用视频生成工具" in sop
    assert "普通视频生成流程" not in sop


def test_community_video_skill_warns_enterprise_override_is_real_runtime_path():
    skill = _read("agents/skills/marketing-video/SKILL.md")

    assert "维护提醒（给后续智能体）" in skill
    assert "开源/社区版仓库中的默认占位 skill" in skill
    assert "enterprise/skills/marketing-video/SKILL.md" in skill
    assert "商业版运行时不会生效" in skill


def test_marketing_pm_routes_video_intent_to_enterprise_overridable_sop():
    prompt = _read("agents/skills/marketing-pm/SKILL.md")

    assert "视频创作" in prompt
    assert "sop-video-generation" in prompt
    assert "生成一个视频，一个女孩在跳舞" in prompt
    assert "普通视频请求由企业版 sop-video-generation 处理" in prompt
    assert "不得在 PM 层直接询问商品展示、广告宣传、品牌宣传等营销用途" in prompt


def test_enterprise_video_sop_does_not_force_marketing_purpose_for_concrete_prompt():
    sop = _read("enterprise/sops/sop-video-generation.md")

    assert "普通视频" in sop
    assert "一个女孩在跳舞" in sop
    assert "不得询问商品展示、广告宣传、品牌宣传等营销用途" in sop
    assert "不要使用下方通用营销视频用途 `ask_user`" in sop


def test_enterprise_video_sop_preserves_local_life_marketing_rules():
    sop = _read("enterprise/sops/sop-video-generation.md")

    assert "本地生活行业" in sop
    assert "餐饮、酒旅、旅游、丽人、休闲娱乐、到店零售、生活服务等；非本地生活则按普通营销视频处理" in sop
    assert "本地生活视频提问规则（必须优先使用）" in sop
    assert "本地生活视频模型推荐检查" in sop
    assert "Seedance2.0 系列模型" in sop
    assert 'options=["商品展示视频", "广告宣传视频", "社交媒体短视频", "品牌宣传片"]' in sop


def test_enterprise_video_expert_preserves_ordinary_video_prompt_intent():
    skill = _read("enterprise/skills/marketing-video/SKILL.md")

    assert "营销视频创作专家" in skill
    assert "普通视频" in skill
    assert "营销视频" in skill
    assert "不得把普通视频改写成商品展示、广告宣传、品牌宣传或社交媒体营销用途" in skill
    assert "一个女孩在跳舞" in skill
