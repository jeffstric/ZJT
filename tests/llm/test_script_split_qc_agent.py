from llm.script_split_qc_agent import run_rule_qc


def _parsed_with_shots(*shots, characters=None):
    return {
        "characters": characters or [],
        "locations": [],
        "props": [],
        "spatial_world": {"space_units": []},
        "shot_groups": [{
            "group_id": "grp_001",
            "shots": list(shots),
        }],
    }


def _shot(number, *, characters_present=None, opening="有效的首帧画面描述"):
    return {
        "shot_number": number,
        "duration": 1,
        "characters_present": characters_present or [],
        "opening_frame_description": opening,
    }


def _error_codes(report):
    return {issue.code for issue in report.issues if issue.severity == "error"}


def test_character_in_frame_resolves_current_segment_id_to_wrapped_name():
    parsed = _parsed_with_shots(
        _shot(
            1,
            characters_present=["char_001"],
            opening="近景：【【林诚】】坐在办公桌后，双手撑住额头。",
        ),
        characters=[{"id": "char_001", "name": "林诚"}],
    )

    report = run_rule_qc(parsed)

    assert "CHAR_NOT_IN_FRAME" not in _error_codes(report)


def test_character_in_frame_resolves_id_from_task_registry():
    parsed = _parsed_with_shots(
        _shot(
            1,
            characters_present=["char_001"],
            opening="近景：【【林诚】】坐在办公桌后，双手撑住额头。",
        ),
    )

    report = run_rule_qc(
        parsed,
        known_characters=[{"id": "char_001", "name": "林诚"}],
    )

    assert "CHAR_NOT_IN_FRAME" not in _error_codes(report)


def test_dialogue_ratio_does_not_fail_qc():
    parsed = _parsed_with_shots(*[_shot(i) for i in range(1, 5)])

    report = run_rule_qc(parsed, script_content="夜晚，两人回到家。\n苏晚：我一直都相信你。")

    assert "TOO_MANY_EMPTY_DIALOGUE_SHOTS" not in _error_codes(report)
    assert report.stats["empty_dialogue_ratio"] == 1.0


def test_missing_wrapped_character_name_is_still_rejected():
    parsed = _parsed_with_shots(
        _shot(
            1,
            characters_present=["char_001"],
            opening="近景：林诚坐在办公桌后，双手撑住额头。",
        ),
        characters=[{"id": "char_001", "name": "林诚"}],
    )

    report = run_rule_qc(parsed)

    assert "CHAR_NOT_IN_FRAME" in _error_codes(report)


def test_short_chinese_dialogues_are_aggregated_when_english_is_required():
    shots = []
    for number, text in enumerate(("你为什么骗我", "我没有骗你", "现在就离开"), start=1):
        shot = _shot(number)
        # 台词写入 description，避免与 DIALOGUE_NOT_IN_VIDEO_PROMPT 规则交叉干扰
        shot["description"] = f'角色说："{text}"'
        shot["dialogue"] = [{"character_id": "char_001", "text": text}]
        shots.append(shot)
    parsed = _parsed_with_shots(*shots)

    report = run_rule_qc(
        parsed,
        dialogue_language="English",
        prompt_language="中文",
    )

    assert "LANG_DIALOGUE_NOT_TARGET" in _error_codes(report)
    issue = next(
        item for item in report.issues
        if item.code == "LANG_DIALOGUE_NOT_TARGET"
    )
    assert issue.field == "dialogue"


def test_short_english_dialogues_are_aggregated_when_chinese_is_required():
    shots = []
    for number, text in enumerate(("Go now", "Stay here", "Trust me"), start=1):
        shot = _shot(number)
        shot["description"] = f'Character says: "{text}"'
        shot["dialogue"] = [{"character_id": "char_001", "text": text}]
        shots.append(shot)

    report = run_rule_qc(
        _parsed_with_shots(*shots),
        dialogue_language="中文",
        prompt_language="中文",
    )

    assert "LANG_DIALOGUE_NOT_TARGET" in _error_codes(report)


def test_short_english_dialogues_pass_with_chinese_visual_prompts():
    shots = []
    for number, text in enumerate(("Go now", "Stay here", "Trust me"), start=1):
        shot = _shot(number, opening="近景：角色站在门前，神情紧张。")
        shot["description"] = f'角色说："{text}"'
        shot["dialogue"] = [{"character_id": "char_001", "text": text}]
        shots.append(shot)

    report = run_rule_qc(
        _parsed_with_shots(*shots),
        dialogue_language="English",
        prompt_language="中文",
    )

    assert "LANG_DIALOGUE_NOT_TARGET" not in _error_codes(report)
    assert "DIALOGUE_NOT_IN_VIDEO_PROMPT" not in _error_codes(report)


def test_short_chinese_dialogues_pass_when_chinese_is_required():
    shots = []
    for number, text in enumerate(("你先离开", "我会留下", "不要回头"), start=1):
        shot = _shot(number)
        shot["description"] = f'角色说："{text}"'
        shot["dialogue"] = [{"character_id": "char_001", "text": text}]
        shots.append(shot)

    report = run_rule_qc(
        _parsed_with_shots(*shots),
        dialogue_language="中文",
        prompt_language="中文",
    )

    assert "LANG_DIALOGUE_NOT_TARGET" not in _error_codes(report)
    assert "DIALOGUE_NOT_IN_VIDEO_PROMPT" not in _error_codes(report)


def test_no_dialogue_does_not_trigger_dialogue_language_error():
    report = run_rule_qc(
        _parsed_with_shots(_shot(1)),
        dialogue_language="English",
        prompt_language="中文",
    )

    assert "LANG_DIALOGUE_NOT_TARGET" not in _error_codes(report)


def test_spatial_materialization_warnings_are_exposed_to_qc_report():
    parsed = _parsed_with_shots(_shot(1))
    parsed["_spatial_diagnostics"] = [{
        "code": "spatial_planned_change_missing",
        "severity": "warning",
        "message": "规划变化未被覆盖",
        "shot_ref": "shot_1",
    }]

    report = run_rule_qc(parsed)

    issue = next(
        item for item in report.issues
        if item.code == "spatial_planned_change_missing"
    )
    assert issue.severity == "warning"
    assert report.passed is True


def test_dialogue_missing_from_video_prompt_is_error():
    shot = _shot(1, opening="近景：【【赵志高】】叉腰站在大堂，神情严厉。")
    shot["description"] = "【【赵志高】】叉腰大声呵斥，嘴巴大张。"
    shot["action"] = "【【赵志高】】手指着地。"
    shot["dialogue"] = [{
        "character_id": "char_001",
        "text": "你也没好到哪去！去，把仓库那堆杂物搬了！",
    }]
    parsed = _parsed_with_shots(shot, characters=[{"id": "char_001", "name": "赵志高"}])

    report = run_rule_qc(parsed)

    assert "DIALOGUE_NOT_IN_VIDEO_PROMPT" in _error_codes(report)
    assert report.passed is False


def test_dialogue_present_in_video_prompt_passes():
    line = "你也没好到哪去！去，把仓库那堆杂物搬了！"
    shot = _shot(1, opening="近景：【【赵志高】】叉腰站在大堂，神情严厉。")
    shot["description"] = f'【【赵志高】】叉腰手指着地，怒声说道："{line}"'
    shot["action"] = "【【赵志高】】继续瞪着眼。"
    shot["dialogue"] = [{"character_id": "char_001", "text": line}]
    parsed = _parsed_with_shots(shot, characters=[{"id": "char_001", "name": "赵志高"}])

    report = run_rule_qc(parsed)

    assert "DIALOGUE_NOT_IN_VIDEO_PROMPT" not in _error_codes(report)


def test_dialogue_in_action_with_quote_variants_passes():
    """引号/省略号变体规范化后仍应视为已包含。"""
    shot = _shot(1, opening="近景：【【王小胖】】为难地站着。")
    shot["description"] = "【【王小胖】】往后缩了缩身子。"
    shot["action"] = "【【王小胖】】小声应道：「哦……」"
    shot["dialogue"] = [{"character_id": "char_002", "text": "哦…"}]
    parsed = _parsed_with_shots(shot, characters=[{"id": "char_002", "name": "王小胖"}])

    report = run_rule_qc(parsed)

    # 「哦…」规范化后含于「哦……」——两端都变成「哦...」
    assert "DIALOGUE_NOT_IN_VIDEO_PROMPT" not in _error_codes(report)


def test_no_dialogue_skips_video_prompt_dialogue_check():
    shot = _shot(1)
    shot["description"] = "【【李卫国】】拿着扫帚认真扫地。"
    report = run_rule_qc(_parsed_with_shots(shot))

    assert "DIALOGUE_NOT_IN_VIDEO_PROMPT" not in _error_codes(report)
