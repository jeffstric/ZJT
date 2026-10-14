"""MiniMax H3 提示词优化：变体判定、模板组装、结构校验与 extra_config 合并。"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config.constant import (
    H3_PROMPT_OPTIMIZE_VARIANT_FL2VA,
    H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
    H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
    H3_PROMPT_OPTIMIZE_VARIANT_REF2VA,
)
from config.unified_config import DriverKey
from task.pipeline_drivers.h3_prompt_optimize_driver import H3PromptOptimizePipelineDriver
from task.pipeline_drivers.h3_prompt_optimize_util import (
    assign_h3_keyframe_ref_pictures,
    build_h3_optimize_user_message,
    h3_slot_source_prompt,
    kfref_required_clauses,
    load_h3_prompt_template,
    merge_h3_prompt_extra_config,
    parse_h3_optimize_kfref_output,
    parse_storyboard_dialogue_model,
    resolve_h3_prompt_variant,
    validate_h3_optimized_prompt,
)


def test_first_frame_only_is_i2va():
    tool = SimpleNamespace(image_path="/a.png", reference_images=None, extra_config=None)
    assert resolve_h3_prompt_variant(tool) == H3_PROMPT_OPTIMIZE_VARIANT_I2VA


def test_first_and_last_frame_is_fl2va():
    tool = SimpleNamespace(image_path="/a.png,/b.png", reference_images=None, extra_config=None)
    assert resolve_h3_prompt_variant(tool) == H3_PROMPT_OPTIMIZE_VARIANT_FL2VA


def test_no_image_returns_none():
    tool = SimpleNamespace(image_path="", reference_images=None, extra_config=None)
    assert resolve_h3_prompt_variant(tool) is None


def test_reference_task_key_is_ref2va():
    """参考生视频：有任一参考资产（图/视频/音频）即为 Ref2VA"""
    tool = SimpleNamespace(
        image_path=None,
        reference_images='["a.png", "b.png"]',
        video_path="v1.mp4",
        audio_path="a1.wav",
        extra_config=None,
    )
    assert resolve_h3_prompt_variant(tool, task_key=DriverKey.MINIMAX_H3_REFERENCE_TO_VIDEO) == H3_PROMPT_OPTIMIZE_VARIANT_REF2VA


def test_reference_task_key_without_assets_returns_none():
    """参考生视频：只认参考资产，image_path 首尾帧不触发 Ref2VA"""
    tool = SimpleNamespace(
        image_path="a.png",
        reference_images=None,
        video_path=None,
        audio_path=None,
        extra_config=None,
    )
    assert resolve_h3_prompt_variant(tool, task_key=DriverKey.MINIMAX_H3_REFERENCE_TO_VIDEO) is None


def test_ref2va_message_lists_assets_and_duration():
    message = build_h3_optimize_user_message(
        "两个人在房间里跳舞",
        H3_PROMPT_OPTIMIZE_VARIANT_REF2VA,
        8,
        template="GUIDE",
        ref_counts={"images": 3, "videos": 1, "audios": 1},
    )
    assert "GUIDE" in message
    assert "8.00" in message
    assert "3 张输入参考图片" in message
    assert "<picture_1>~<picture_3>" in message
    assert "1 个输入参考视频" in message
    assert "1 个输入参考音频" in message
    assert "两个人在房间里跳舞" in message


def test_ref2va_template_selected_by_variant():
    template = load_h3_prompt_template(H3_PROMPT_OPTIMIZE_VARIANT_REF2VA)
    assert "subject_definitions" in template
    assert "retention_analysis" in template
    assert "Ref2VA" in template


def test_validate_ref2va():
    ref2va = (
        "subject_definitions: <subject_1> is the woman in <picture_1>.\n\n"
        "summary: [reference generation] The target video shows <subject_1> dancing.\n\n"
        "retention_analysis: <subject_1> (appears in [Shot 1]): fully_preserved - kept.\n\n"
        "detailed_description: [Shot 1] ...\n\n"
        "overall_soundscape: quiet\n\n"
        "non_diegetic_music: N/A"
    )
    assert validate_h3_optimized_prompt(ref2va, H3_PROMPT_OPTIMIZE_VARIANT_REF2VA)
    assert not validate_h3_optimized_prompt("just a shot", H3_PROMPT_OPTIMIZE_VARIANT_REF2VA)
    # 缺任一六段字段不通过
    assert not validate_h3_optimized_prompt(
        ref2va.replace("non_diegetic_music: N/A", ""), H3_PROMPT_OPTIMIZE_VARIANT_REF2VA
    )


def test_user_message_keeps_original_and_guide():
    original = "镜头缓推，女主转头微笑"
    message = build_h3_optimize_user_message(
        original,
        H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
        5,
        template="GUIDE_BODY",
    )
    assert "GUIDE_BODY" in message
    assert "首帧图" in message
    assert original in message
    assert "I2VA" in load_h3_prompt_template()
    assert "FL2VA" in load_h3_prompt_template()
    assert "T2VA" not in load_h3_prompt_template() or "Do not invent T2VA" in load_h3_prompt_template()


def test_fl2va_message_includes_duration():
    message = build_h3_optimize_user_message(
        "walk forward",
        H3_PROMPT_OPTIMIZE_VARIANT_FL2VA,
        8,
        template="GUIDE",
    )
    assert "8.00" in message
    assert "尾帧图" in message


def test_user_message_includes_fidelity_note_for_quoted_chinese_dialogue():
    """引号内中文对话：点名片段 + 条件式保真指令（线上案例：说：“原来是这样！”）"""
    message = build_h3_optimize_user_message(
        "镜头拉进，女主思考过程中，突然顿悟，说：“原来是这样！”",
        H3_PROMPT_OPTIMIZE_VARIANT_FL2VA,
        5,
        template="GUIDE",
    )
    assert "引号包裹的 Chinese 片段" in message
    assert '- "原来是这样！"' in message
    assert "[Chinese]" in message
    assert "严禁翻译或改写" in message
    # 条件式措辞：角色判断交给 LLM，而非断言引号内容必为对话
    assert "若它们是角色说出的台词" in message
    assert "描述性用法" in message


def test_user_message_fidelity_note_covers_emphasis_quotes():
    """引号表强调/术语（非对话）同样出现指令，但措辞为条件式，由 LLM 判断"""
    message = build_h3_optimize_user_message(
        "女主做出“思考”的动作",
        H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
        5,
        template="GUIDE",
    )
    assert '- "思考"' in message
    assert "描述性用法" in message


def test_user_message_no_fidelity_note_for_plain_prompts():
    """纯英文、无引号中文、空 prompt 不追加保真点名指令，但追加禁止虚构对白提示"""
    for original in ("walk forward, she smiles", "镜头缓推，女主转头微笑", ""):
        message = build_h3_optimize_user_message(
            original,
            H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
            5,
            template="GUIDE",
        )
        assert "引号包裹的" not in message
        assert "严禁虚构" in message
        assert "不得出现 <d> 标签" in message


def test_user_message_no_dialogue_note_for_timbre_only_prompt():
    """线上案例 ai_tools 231:原文仅音色参考无台词,注入反幻觉提示,禁止 LLM 虚构 <d> 对白"""
    message = build_h3_optimize_user_message(
        "参考音频说明：音频1是角色：李卫国的音色样本，角色说话时请保持相同音色。",
        H3_PROMPT_OPTIMIZE_VARIANT_REF2VA,
        5,
        template="GUIDE",
    )
    assert "严禁虚构" in message
    assert "音色参考仅约束" in message
    assert "不得出现 <d> 标签" in message
    # 反幻觉提示位于指令区，原文仍完整附在消息末尾
    assert message.rstrip().endswith("角色说话时请保持相同音色。")


def test_fidelity_note_language_tag_japanese_and_korean():
    """假名→[Japanese]，谚文→[Korean]，标签按片段字符集自适应"""
    japanese = build_h3_optimize_user_message(
        "彼は「そうだったのか！」と叫んだ",
        H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
        5,
        template="GUIDE",
    )
    assert "[Japanese]" in japanese
    assert '- "そうだったのか！"' in japanese

    korean = build_h3_optimize_user_message(
        "그녀는 “안녕!”라고 말했다",
        H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
        5,
        template="GUIDE",
    )
    assert "[Korean]" in korean
    assert '- "안녕!"' in korean


def test_system_prompt_requires_dialogue_fidelity():
    """system prompt 不再要求整段全英文：对话/歌词/屏幕文字保留原语言"""
    from task.pipeline_drivers.h3_prompt_optimize_driver import _SYSTEM_PROMPT
    assert "never" in _SYSTEM_PROMPT and "translate" in _SYSTEM_PROMPT
    assert "[Chinese]" in _SYSTEM_PROMPT
    assert "Output only the final English prompt" not in _SYSTEM_PROMPT


def test_validate_i2va_and_fl2va():
    i2va = (
        "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        "integrated_multimodal_description: [Shot 1] hello\n\n"
        "overall_soundscape: rain\n\n"
        "non_diegetic_music: N/A"
    )
    fl2va = (
        "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.\n\n"
        "integrated_multimodal_description: [Shot 1] hello\n\n"
        "overall_soundscape: rain\n\n"
        "non_diegetic_music: N/A"
    )
    assert validate_h3_optimized_prompt(i2va, H3_PROMPT_OPTIMIZE_VARIANT_I2VA)
    assert not validate_h3_optimized_prompt(i2va, H3_PROMPT_OPTIMIZE_VARIANT_FL2VA)
    assert validate_h3_optimized_prompt(fl2va, H3_PROMPT_OPTIMIZE_VARIANT_FL2VA)
    assert not validate_h3_optimized_prompt("just a shot", H3_PROMPT_OPTIMIZE_VARIANT_I2VA)


def test_merge_extra_config_keeps_first_original():
    first = merge_h3_prompt_extra_config(
        {"resolution": "720P"},
        original_prompt="old",
        optimized_prompt="new",
        variant="I2VA",
        fallback=False,
    )
    second = merge_h3_prompt_extra_config(
        first,
        original_prompt="changed",
        optimized_prompt="newer",
        variant="I2VA",
        fallback=True,
    )
    import json
    data = json.loads(second)
    assert data["original_prompt"] == "old"
    assert data["h3_prompt_optimize"]["optimized_prompt"] == "newer"
    assert data["h3_prompt_optimize"]["fallback"] is True
    assert data["resolution"] == "720P"


def test_merge_extra_config_stores_has_dialogue_flag():
    """KFRef 成功优化存 LLM 判断；回退原文存 None（驱动回退正则兜底）。"""
    import json
    ok = json.loads(merge_h3_prompt_extra_config(
        None,
        original_prompt="原文",
        optimized_prompt="rewritten",
        variant="KFRef",
        fallback=False,
        has_dialogue=False,
    ))
    assert ok["h3_prompt_optimize"]["has_dialogue"] is False

    fallback = json.loads(merge_h3_prompt_extra_config(
        None,
        original_prompt="原文",
        optimized_prompt="原文",
        variant="KFRef",
        fallback=True,
    ))
    assert fallback["h3_prompt_optimize"]["has_dialogue"] is None


def test_parse_h3_optimize_kfref_output():
    """首行 JSON 头协议：代码强校验格式，格式正确才提取正文作为视频提示词。"""
    body = "<Picture 1> is the EXACT starting key frame at 0.00 seconds.\n\n[Shot 1] ..."
    prompt, flag = parse_h3_optimize_kfref_output('{"has_dialogue": false}\n\n' + body)
    assert prompt == body
    assert flag is False
    prompt, flag = parse_h3_optimize_kfref_output('{"has_dialogue": true}\n' + body)
    assert prompt == body
    assert flag is True
    # 额外字段忽略；围栏包裹先剥再解析
    prompt, _ = parse_h3_optimize_kfref_output('```{"has_dialogue": false, "extra": 1}\n\n' + body + "\n```")
    assert prompt == body
    # 头后正文又被包进围栏：剥掉围栏再返回，围栏不得残留进最终提示词
    prompt, _ = parse_h3_optimize_kfref_output('{"has_dialogue": false}\n\n```text\n' + body + "\n```")
    assert prompt == body
    assert "```" not in prompt
    # 各类非法格式整条拒绝：(None, None) 触发重试，两次失败回退原文
    for bad in (
        "",                                     # 空
        "no header\n\n" + body,                 # 首行不是 JSON
        '["has_dialogue"]\n\n' + body,          # 非 dict
        '{"dialogue": true}\n\n' + body,        # 缺 has_dialogue
        '{"has_dialogue": "yes"}\n\n' + body,   # 非布尔
        '{"has_dialogue": null}\n\n' + body,    # null 不是布尔
        '{"has_dialogue": true}\n\n   ',        # 头后无正文
    ):
        assert parse_h3_optimize_kfref_output(bad) == (None, None), bad


def _kfref_ok_body(audio_line: str = "") -> str:
    return (
        "<Picture 1> is the EXACT starting key frame at 0.00 seconds.\n\n"
        + audio_line
        + "[Shot 1] The older man sweeps the ground. Ambient sound of footsteps only."
    )


def test_optimize_kfref_returns_dialogue_flag_from_header():
    driver = H3PromptOptimizePipelineDriver()
    driver.logger = MagicMock()
    slots = assign_h3_keyframe_ref_pictures(["first.png"], "图1是首帧。")

    async def fake_llm(original, variant, duration, step_params):
        return '{"has_dialogue": false}\n\n' + _kfref_ok_body()

    driver._call_llm = fake_llm
    optimized, fallback, error, flag = asyncio.run(driver._optimize(
        "无对白，只有扫帚声", H3_PROMPT_OPTIMIZE_VARIANT_KF_REF, 5.0, {"keyframe_slots": slots},
    ))
    assert fallback is False and error is None
    assert flag is False
    assert optimized.startswith("<Picture 1> is the EXACT starting key frame")

    async def fake_llm_spoken(original, variant, duration, step_params):
        return '{"has_dialogue": true}\n\n' + _kfref_ok_body(
            "<Audio 1> is the voice-timbre reference for the older man in <Picture 2> (S1): "
            "it provides voice timbre, vocal identity, speaking tone, rhythm, intonation, and lip-sync pacing.\n\n"
        )

    driver._call_llm = fake_llm_spoken
    _, fallback, _, flag = asyncio.run(driver._optimize(
        "李卫国说「今天到此为止」", H3_PROMPT_OPTIMIZE_VARIANT_KF_REF, 5.0, {"keyframe_slots": slots},
    ))
    assert fallback is False
    assert flag is True


def test_optimize_kfref_falls_back_when_header_or_forbid_fails():
    driver = H3PromptOptimizePipelineDriver()
    driver.logger = MagicMock()
    slots = assign_h3_keyframe_ref_pictures(["first.png"], "图1是首帧。")
    calls = {"n": 0}

    # LLM 不守协议（无 JSON 头）：两次都失败 → 回退原文，has_dialogue=None
    async def no_header(original, variant, duration, step_params):
        calls["n"] += 1
        return _kfref_ok_body()

    driver._call_llm = no_header
    optimized, fallback, error, flag = asyncio.run(driver._optimize(
        "原文", H3_PROMPT_OPTIMIZE_VARIANT_KF_REF, 5.0, {"keyframe_slots": slots},
    ))
    assert fallback is True and flag is None
    assert optimized == "原文" and calls["n"] == 2

    # 判无台词却仍写 <Audio 1>：forbid_audio_refs 校验拒绝 → 重试耗尽回退
    async def says_false_but_writes_audio(original, variant, duration, step_params):
        return '{"has_dialogue": false}\n\n' + _kfref_ok_body(
            "<Audio 1> is a reference audio for voice timbre.\n\n"
        )

    driver._call_llm = says_false_but_writes_audio
    optimized, fallback, error, flag = asyncio.run(driver._optimize(
        "无对白原文", H3_PROMPT_OPTIMIZE_VARIANT_KF_REF, 5.0, {"keyframe_slots": slots},
    ))
    assert fallback is True and flag is None and optimized == "无对白原文"


def test_step_configs_pass_image_prompt_note_for_kfref():
    """extra_config.image_prompt_note → KFRef 步骤参数；其他变体不携带。"""
    from task.pipeline_drivers import PipelineDriverFactory

    kfref_tool = SimpleNamespace(
        prompt="图1是首帧",
        image_path=None,
        reference_images='["first.png"]',
        extra_config=json.dumps({"image_mode": "multi_reference", "image_prompt_note": "左侧是李卫国"}),
        duration=5,
        video_path=None,
        audio_path=None,
    )
    with patch('task.pipeline_drivers.get_dynamic_config_value', return_value=True):
        configs = PipelineDriverFactory.build_h3_prompt_optimize_step_configs(
            kfref_tool, task_key="minimax_h3_keyframe_ref_to_video",
        )
    assert len(configs) == 1
    assert configs[0]["params"]["image_prompt_note"] == "左侧是李卫国"

    no_note_tool = SimpleNamespace(
        prompt="图1是首帧",
        image_path=None,
        reference_images='["first.png"]',
        extra_config=json.dumps({"image_mode": "multi_reference"}),
        duration=5,
        video_path=None,
        audio_path=None,
    )
    with patch('task.pipeline_drivers.get_dynamic_config_value', return_value=True):
        configs = PipelineDriverFactory.build_h3_prompt_optimize_step_configs(
            no_note_tool, task_key="minimax_h3_keyframe_ref_to_video",
        )
    assert "image_prompt_note" not in configs[0]["params"]


def test_parse_storyboard_dialogue_model_object():
    cfg = json.dumps({'selectedLlmModel': {'model': 'qwen-plus', 'vendor_id': 5}})
    assert parse_storyboard_dialogue_model(cfg) == ('qwen-plus', 5)


def test_parse_storyboard_dialogue_model_string():
    cfg = json.dumps({'selectedLlmModel': 'gemini-3-flash-preview'})
    assert parse_storyboard_dialogue_model(cfg) == ('gemini-3-flash-preview', None)


def test_parse_storyboard_dialogue_model_missing():
    assert parse_storyboard_dialogue_model(None) is None
    assert parse_storyboard_dialogue_model('{}') is None


@patch('llm.llm_client_factory.is_llm_client_configured', return_value=True)
@patch('llm.llm_client_factory.get_llm_client')
@patch('config.config_util.get_dynamic_config_value')
def test_resolve_prefers_chat_model(mock_config, mock_get_client, mock_configured):
    """优先使用 step.params 的对话模型（storyboard 用户个性化选择）"""
    mock_config.return_value = 'deepseek-v4-flash'
    model, vendor_id = H3PromptOptimizePipelineDriver.resolve_h3_optimize_model(
        {'chat_model': 'qwen-plus', 'chat_vendor_id': 5}
    )
    assert model == 'qwen-plus'
    assert vendor_id == 5
    mock_get_client.assert_called_once_with('qwen-plus', vendor_id=5)


def test_keyframe_ref_two_images_is_kfref_not_fl2va():
    """两张参考图不能掉进 FL2VA，否则 Picture 2 会被写成尾帧。"""
    tool = SimpleNamespace(
        image_path=None,
        reference_images='["a.png", "b.png"]',
        video_path=None,
        audio_path=None,
        extra_config='{"image_mode": "multi_reference"}',
    )
    assert resolve_h3_prompt_variant(
        tool, task_key=DriverKey.MINIMAX_H3_KEYFRAME_REF_TO_VIDEO
    ) == H3_PROMPT_OPTIMIZE_VARIANT_KF_REF


def test_assign_keyframe_ref_pictures():
    both = assign_h3_keyframe_ref_pictures(
        ["first.png", "ref.png", "last.png"],
        "图1是首帧，图2是林月，图3是尾帧。",
    )
    assert (both["picture_1"], both["picture_2"], both["picture_3"]) == ("first.png", "ref.png", "last.png")
    assert both["roles"] == {"picture_1": "start", "picture_2": "reference", "picture_3": "end"}

    only_first = assign_h3_keyframe_ref_pictures(
        ["first.png", "ref1.png", "ref2.png"],
        "图1是首帧，图2是甲，图3是乙。",
    )
    assert (only_first["picture_1"], only_first["picture_2"], only_first["picture_3"]) == (
        "first.png", "ref1.png", "ref2.png",
    )
    assert only_first["roles"]["picture_3"] == "reference"

    only_last = assign_h3_keyframe_ref_pictures(
        ["ref.png", "last.png"],
        "图2是尾帧。",
    )
    assert (only_last["picture_1"], only_last["picture_2"], only_last["picture_3"]) == ("ref.png", "", "last.png")
    assert only_last["roles"]["picture_3"] == "end"

    last_only_image = assign_h3_keyframe_ref_pictures(["last.png"], "图1是尾帧。")
    assert (last_only_image["picture_1"], last_only_image["picture_2"], last_only_image["picture_3"]) == ("", "", "last.png")

    first_and_last = assign_h3_keyframe_ref_pictures(
        ["first.png", "last.png"],
        "图1是首帧，图2是尾帧。",
    )
    assert (first_and_last["picture_1"], first_and_last["picture_2"], first_and_last["picture_3"]) == (
        "first.png", "", "last.png",
    )

    dropped = assign_h3_keyframe_ref_pictures(
        ["first.png", "ref1.png", "ref2.png", "last.png"],
        "图1是首帧，图4是尾帧。",
    )
    assert dropped["picture_2"] == "ref1.png"
    assert dropped["picture_3"] == "last.png"
    assert dropped["unused_urls"] == ["ref2.png"]


def test_kfref_instruction_uses_real_slots_and_capital_picture():
    slots = assign_h3_keyframe_ref_pictures(
        ["first.png", "ref.png", "last.png"],
        "图1是首帧，图3是尾帧。",
    )
    message = build_h3_optimize_user_message(
        "从首帧走到尾帧",
        H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
        6,
        template="GUIDE",
        ref_counts={"images": 3, "videos": 1, "audios": 1},
        keyframe_slots=slots,
    )
    # 前缀基础由代码按图槽事实写死；audio reference 段由 LLM 按台词判断自选
    assert "类型前缀基础为 [keyframe completion + reference generation]" in message
    assert " + audio reference" in message
    assert "<Picture 1> is the EXACT starting key frame at 0.00 seconds." in message
    assert "<Picture 3> is the EXACT ending key frame at 6.00 seconds (ref_image3)." in message
    picture2 = next(line for line in message.splitlines() if "<Picture 2>" in line)
    assert "not an ending key frame" in picture2
    assert "尾帧" not in picture2
    assert "last frame" not in picture2.lower()
    assert "<video_N>" in message
    assert "不要把起始姿势写成结尾姿势" in message
    kfref_guide = load_h3_prompt_template(H3_PROMPT_OPTIMIZE_VARIANT_KF_REF)
    assert "subject_definitions:" not in kfref_guide
    assert "mandatory keyframe sentence" in kfref_guide
    assert "subject_definitions" in load_h3_prompt_template(H3_PROMPT_OPTIMIZE_VARIANT_REF2VA)


def test_kfref_instruction_names_second_audio_when_two_are_present():
    slots = assign_h3_keyframe_ref_pictures(
        ["first.png", "ref.png", "last.png"],
        "图1是首帧，图3是尾帧。",
    )
    message = build_h3_optimize_user_message(
        "两段音色",
        H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
        10,
        template="GUIDE",
        ref_counts={"images": 3, "videos": 0, "audios": 3},
        keyframe_slots=slots,
    )
    # 3 路截断到 2：指令给「可用 2 路」事实与绑定句骨架，写不写由 LLM 判台词后自选
    assert "有 2 个可用参考音频。第一段写成 <Audio 1>，第二段写成 <Audio 2>" in message
    assert "voice-timbre reference for <该说话人在画面中的具体描述> (S1)" in message
    assert "原文没有台词：不写任何 <Audio N>" in message
    assert "不要写 <Audio 3>" in message
    # 输出协议段：首行 JSON 头由代码强校验
    assert '{"has_dialogue": true} 或 {"has_dialogue": false}' in message
    guide = load_h3_prompt_template(H3_PROMPT_OPTIMIZE_VARIANT_KF_REF)
    assert "has_dialogue" in guide
    assert "Speaker binding rules" in guide
    assert "Never use a bare position word alone" in guide
    assert "mean nothing to the video model" in guide
    assert "ambient and environmental sound" in guide
    assert "voice-timbre reference only. Do not copy" not in guide


def test_kfref_audio_sentence_depends_on_spoken_lines():
    slots = assign_h3_keyframe_ref_pictures(["first.png", "ref.png"], "图1是首帧。")
    # 0 路音频（注入跳过/无角色音色）：无论 LLM 判有无台词，都不写任何 <Audio N>
    zero_audio = build_h3_optimize_user_message(
        "参考音频说明：音频1是角色：李卫国的音色样本，角色说话时请保持相同音色。",
        H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
        10,
        template="GUIDE",
        ref_counts={"images": 2, "videos": 0, "audios": 0},
        keyframe_slots=slots,
    )
    assert "没有可用参考音频：无论原文有无台词，都不要写任何 <Audio N>。" in zero_audio
    assert "类型前缀基础为 [keyframe completion + reference generation]" in zero_audio

    # 有 2 路音频：条件式指令让 LLM 先判台词再选句式（语义判断不在这层做）
    two_audio = build_h3_optimize_user_message(
        "参考音频说明：音频1是角色：李卫国的音色样本，角色说话时请保持相同音色。",
        H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
        10,
        template="GUIDE",
        ref_counts={"images": 2, "videos": 0, "audios": 2},
        keyframe_slots=slots,
    )
    assert "先判断原文有没有角色说出或唱出的台词" in two_audio
    assert "店名/标语" in two_audio
    assert "原文没有台词：不写任何 <Audio N>" in two_audio
    assert "每一段绑定到各自的说话人" in two_audio

    # 非 KFRef 变体不出现条件式音频指令与协议段
    ref2va = build_h3_optimize_user_message(
        "参考音频说明：音频1是角色：李卫国的音色样本，角色说话时请保持相同音色。",
        H3_PROMPT_OPTIMIZE_VARIANT_REF2VA,
        5,
        template="GUIDE",
        ref_counts={"images": 1, "videos": 0, "audios": 1},
    )
    assert "先判断原文有没有角色说出或唱出的台词" not in ref2va
    assert "has_dialogue" not in ref2va


def test_kfref_instruction_carries_image_prompt_note():
    """分镜画面构成作为绑定原料进指令；无 note 时指令自动降级（不出现原料块）。"""
    slots = assign_h3_keyframe_ref_pictures(["first.png", "ref.png"], "图1是首帧。")
    with_note = build_h3_optimize_user_message(
        "赵志高在右侧呵斥",
        H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
        5,
        template="GUIDE",
        ref_counts={"images": 2, "videos": 0, "audios": 1},
        keyframe_slots=slots,
        image_prompt_note="李卫国穿灰色工装站在画面左侧，赵志高在右侧",
    )
    assert "绑定原料（生成本分镜图片所用的画面构成，含人物站位与外观）" in with_note
    assert "李卫国穿灰色工装站在画面左侧" in with_note
    without_note = build_h3_optimize_user_message(
        "赵志高在右侧呵斥",
        H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
        5,
        template="GUIDE",
        ref_counts={"images": 2, "videos": 0, "audios": 1},
        keyframe_slots=slots,
    )
    assert "绑定原料" not in without_note
    assert "说话人绑定规则" in without_note


def test_kfref_instruction_omits_the_unused_keyframe_sentence():
    first_only = assign_h3_keyframe_ref_pictures(["first.png", "ref.png"], "图1是首帧。")
    first_message = build_h3_optimize_user_message(
        "只有首帧",
        H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
        5,
        template="GUIDE",
        ref_counts={"images": 2, "videos": 0, "audios": 0},
        keyframe_slots=first_only,
    )
    assert "<Picture 1> is the EXACT starting key frame at 0.00 seconds." in first_message
    assert "EXACT ending key frame" not in first_message
    assert "不要把起始姿势写成结尾姿势" not in first_message

    last_only = assign_h3_keyframe_ref_pictures(["ref.png", "last.png"], "图2是尾帧。")
    last_message = build_h3_optimize_user_message(
        "只有尾帧",
        H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
        10,
        template="GUIDE",
        ref_counts={"images": 2, "videos": 0, "audios": 0},
        keyframe_slots=last_only,
    )
    assert "EXACT starting key frame" not in last_message
    assert "<Picture 3> is the EXACT ending key frame at 10.00 seconds (ref_image3)." in last_message


def test_kfref_validator_requires_exact_keyframe_sentences():
    slots = assign_h3_keyframe_ref_pictures(
        ["first.png", "ref.png", "last.png"],
        "图1是首帧，图3是尾帧。",
    )
    paraphrased = (
        "subject_definitions: <Subject 1> is the woman.\n\n"
        "summary: [keyframe completion] The shot starts on <Picture 1>.\n\n"
        "retention_analysis: <Subject 1> (appears in [Shot 1]): fully_preserved - kept.\n\n"
        "detailed_description: [Shot 1] ...\n\n"
        "overall_soundscape: quiet\n\n"
        "non_diegetic_music: N/A"
    )
    assert not validate_h3_optimized_prompt(
        paraphrased,
        H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
        keyframe_slots=slots,
        duration=10,
    )
    written_by_model = (
        "<Picture 1> is the EXACT starting key frame at 0.00 seconds. "
        "The opening frame must not be reinterpreted.\n\n"
        "<Picture 2> is a character reference.\n\n"
        "<Picture 3> is the EXACT ending key frame at 10.00 seconds (ref_image3). "
        "It is the target last frame.\n\n"
        "[Shot 1] The supervisor speaks."
    )
    assert kfref_required_clauses(slots, 10) == [
        "<Picture 1> is the EXACT starting key frame at 0.00 seconds.",
        "<Picture 3> is the EXACT ending key frame at 10.00 seconds (ref_image3).",
    ]
    assert validate_h3_optimized_prompt(
        written_by_model,
        H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
        keyframe_slots=slots,
        duration=10,
    )
    assert not validate_h3_optimized_prompt(
        written_by_model,
        H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
        keyframe_slots=slots,
        duration=5,
    )


def test_slot_source_prompt_prefers_optimizer_original():
    extra = {
        "original_prompt": "外层原文 图1是首帧",
        "h3_prompt_optimize": {
            "original_prompt": "优化前 图2是尾帧",
            "optimized_prompt": "subject_definitions: rewritten",
        },
    }
    assert h3_slot_source_prompt(extra, "当前提示词没有标记") == "优化前 图2是尾帧"
    assert h3_slot_source_prompt({"original_prompt": "只有外层 图1是首帧"}, "fallback") == "只有外层 图1是首帧"
    assert h3_slot_source_prompt(None, "图1是首帧") == "图1是首帧"


@patch("task.pipeline_drivers.get_dynamic_config_value", return_value=True)
def test_kfref_step_config_passes_slot_plan(_mock_cfg):
    from task.pipeline_drivers import PipelineDriverFactory

    tool = SimpleNamespace(
        prompt="从图1走到图3\n\n图1是首帧，图2是林月，图3是尾帧。",
        reference_images='["first.png", "ref.png", "last.png"]',
        video_path="clip.mp4",
        audio_path="voice.wav",
        duration=6,
        image_path=None,
        extra_config='{"image_mode":"multi_reference"}',
    )
    configs = PipelineDriverFactory.build_h3_prompt_optimize_step_configs(
        tool,
        task_key=DriverKey.MINIMAX_H3_KEYFRAME_REF_TO_VIDEO,
    )
    assert len(configs) == 1
    params = configs[0]["params"]
    assert params["variant"] == H3_PROMPT_OPTIMIZE_VARIANT_KF_REF
    assert params["keyframe_slots"]["roles"] == {
        "picture_1": "start",
        "picture_2": "reference",
        "picture_3": "end",
    }
    assert params["ref_counts"]["audios"] == 1


@patch('llm.llm_client_factory.is_llm_client_configured', side_effect=[False, True])
@patch('llm.llm_client_factory.get_llm_client')
@patch('config.config_util.get_dynamic_config_value')
def test_resolve_falls_back_to_pipeline_config(mock_config, mock_get_client, mock_configured):
    """对话模型未配置密钥 → 回退 pipeline 全局配置模型"""
    mock_config.return_value = 'deepseek-v4-flash'
    model, vendor_id = H3PromptOptimizePipelineDriver.resolve_h3_optimize_model(
        {'chat_model': 'qwen-plus', 'chat_vendor_id': 5}
    )
    assert model == 'deepseek-v4-flash'


@patch('llm.llm_client_factory.is_llm_client_configured', return_value=False)
@patch('llm.llm_client_factory.get_llm_client')
@patch('config.config_util.get_dynamic_config_value')
def test_resolve_returns_none_when_all_unconfigured(mock_config, mock_get_client, mock_configured):
    """所有候选模型均未配置密钥 → 返回 (None, None)，驱动将回退原文不做空跑"""
    mock_config.return_value = 'deepseek-v4-flash'
    model, vendor_id = H3PromptOptimizePipelineDriver.resolve_h3_optimize_model(
        {'chat_model': 'qwen-plus', 'chat_vendor_id': 5}
    )
    assert model is None
    assert vendor_id is None


def _ref2va_ok_body(extra: str = "") -> str:
    """结构合法的 Ref2VA 优化输出骨架（六段字段齐全）。"""
    return (
        "subject_definitions: <subject_1> is the man in <picture_1>.\n\n"
        "summary: [reference generation] A quiet office scene.\n\n"
        "retention_analysis: <subject_1> (appears in [Shot 1]): fully_preserved - identity kept.\n\n"
        "detailed_description: [Shot 1] He nods silently and glances around the room.\n"
        + extra
        + "\n\noverall_soundscape: Room tone only.\n\n"
        "non_diegetic_music: N/A"
    )


def test_user_message_no_dialogue_note_rewrites_speaking_intent():
    """线上案例 ai_tools 56837：无台词但动作写「准备开口」，note 要求改写为无声动作。"""
    message = build_h3_optimize_user_message(
        "描述：胡敏环视一圈团队成员，准备开口。音频备注：无对白",
        H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
        5,
        template="GUIDE",
    )
    # note 特有措辞（原文不含「欲言又止/嘴唇闭合」，命中即说明指令已注入）
    assert "欲言又止" in message
    assert "改写为无声动作" in message
    assert "嘴唇闭合" in message
    assert "无法识别的含糊语音" in message


def test_validate_forbid_dialogue_blocks_speaking_intent():
    """forbid_dialogue 拦 <d> 与说话意图短语；无声动作与普通名词（loudspeaker）不误伤。"""
    ok = _ref2va_ok_body()
    assert validate_h3_optimized_prompt(ok, H3_PROMPT_OPTIMIZE_VARIANT_REF2VA, forbid_dialogue=True)
    assert validate_h3_optimized_prompt(
        _ref2va_ok_body("A loudspeaker on the wall plays static noise."),
        H3_PROMPT_OPTIMIZE_VARIANT_REF2VA,
        forbid_dialogue=True,
    )
    for bad in (
        _ref2va_ok_body("He says: <d>[Chinese] 你好</d>"),
        _ref2va_ok_body("He gives a slight nod, ready to speak."),
        _ref2va_ok_body("She opens her mouth to speak."),
        _ref2va_ok_body("He is about to say something."),
        _ref2va_ok_body("他准备开口说话。"),
    ):
        assert not validate_h3_optimized_prompt(
            bad, H3_PROMPT_OPTIMIZE_VARIANT_REF2VA, forbid_dialogue=True
        ), bad
        # 有台词场景不开 forbid_dialogue，同样内容不拦
        assert validate_h3_optimized_prompt(
            bad, H3_PROMPT_OPTIMIZE_VARIANT_REF2VA, forbid_dialogue=False
        ), bad


def test_optimize_ref2va_no_dialogue_forbids_audio_and_speaking_intent():
    """Ref2VA 无台词：优化结果含 <audio 引用或说话意图短语均打回，耗尽回退原文。"""
    driver = H3PromptOptimizePipelineDriver()
    driver.logger = MagicMock()
    calls = {"n": 0}

    async def writes_audio(original, variant, duration, step_params):
        calls["n"] += 1
        return _ref2va_ok_body(
            "<audio_1> is the voice-timbre reference for <subject_1> (S1)."
        )

    driver._call_llm = writes_audio
    optimized, fallback, _, flag = asyncio.run(driver._optimize(
        "无对白镜头，只有环境音", H3_PROMPT_OPTIMIZE_VARIANT_REF2VA, 5.0, {},
    ))
    assert fallback is True and flag is None
    assert optimized == "无对白镜头，只有环境音"
    assert calls["n"] == 2

    async def keeps_speaking_intent(original, variant, duration, step_params):
        return _ref2va_ok_body("He gives a slight nod, ready to speak.")

    driver._call_llm = keeps_speaking_intent
    optimized, fallback, _, _ = asyncio.run(driver._optimize(
        "胡敏环视众人，准备开口。音频备注：无对白", H3_PROMPT_OPTIMIZE_VARIANT_REF2VA, 5.0, {},
    ))
    assert fallback is True and optimized.startswith("胡敏环视众人")

    async def clean(original, variant, duration, step_params):
        return _ref2va_ok_body()

    driver._call_llm = clean
    optimized, fallback, error, _ = asyncio.run(driver._optimize(
        "无对白镜头", H3_PROMPT_OPTIMIZE_VARIANT_REF2VA, 5.0, {},
    ))
    assert fallback is False and error is None

    # 有台词：音色引用与 <d> 均合法，forbid 不开
    async def with_dialogue(original, variant, duration, step_params):
        return _ref2va_ok_body(
            "<audio_1> is the voice-timbre reference for <subject_1> (S1). "
            "He says: <d>[Chinese] 今天到此为止</d>"
        )

    driver._call_llm = with_dialogue
    optimized, fallback, _, _ = asyncio.run(driver._optimize(
        "李卫国说「今天到此为止」", H3_PROMPT_OPTIMIZE_VARIANT_REF2VA, 5.0, {},
    ))
    assert fallback is False and "<audio_1>" in optimized
