from services.storyboard_agent_image_tool import StoryboardAgentImageToolExecutor


class FakeToolExecutor:
    def __init__(self):
        self.calls = []

    def get_tool_definitions(self, allowed_tools):
        return [{"function": {"name": name}} for name in allowed_tools]

    def execute_tool(
        self,
        tool_name,
        tool_args,
        user_id,
        world_id,
        auth_token,
        language="zh-CN",
        model=None,
        vendor_id=None,
    ):
        self.calls.append({
            "tool_name": tool_name,
            "tool_args": tool_args,
            "user_id": user_id,
            "world_id": world_id,
            "auth_token": auth_token,
            "language": language,
            "model": model,
            "vendor_id": vendor_id,
        })
        return {"project_ids": [123]}


def _build_executor():
    delegate = FakeToolExecutor()
    executor = StoryboardAgentImageToolExecutor(
        delegate,
        style="水墨动画",
        composition_preference="电影感宽幅构图",
    )
    return executor, delegate


def test_image_tools_append_storyboard_visual_settings_to_prompt_tail():
    for tool_name in ("generate_text_to_image", "edit_image"):
        executor, delegate = _build_executor()

        result = executor.execute_tool(
            tool_name,
            {"prompt": "女孩站在雨中", "image_url": "https://example.com/a.png"},
            "1",
            "2",
            "token",
        )

        prompt = delegate.calls[0]["tool_args"]["prompt"]
        assert prompt == (
            "女孩站在雨中\n\n"
            "图片风格：水墨动画\n"
            "构图倾向：电影感宽幅构图"
        )
        assert result == {"project_ids": [123]}


def test_image_tool_visual_suffix_is_idempotent_and_preserves_caller_args():
    executor, delegate = _build_executor()
    original_args = {
        "prompt": (
            "女孩站在雨中\n\n"
            "图片风格：水墨动画\n"
            "构图倾向：电影感宽幅构图"
        )
    }

    executor.execute_tool("edit_image", original_args, "1", "2", "token")

    submitted = delegate.calls[0]["tool_args"]["prompt"]
    assert submitted.count("图片风格：水墨动画") == 1
    assert submitted.count("构图倾向：电影感宽幅构图") == 1
    assert original_args["prompt"] == submitted


def test_non_image_tool_is_delegated_without_visual_prompt_changes():
    executor, delegate = _build_executor()
    args = {"prompt": "不要改写", "question": "是否继续？"}

    executor.execute_tool("ask_user", args, "1", "2", "token")

    assert delegate.calls[0]["tool_args"] == args
    assert delegate.calls[0]["tool_args"] is not args


def test_tool_definitions_are_delegated_unchanged():
    executor, _delegate = _build_executor()

    assert executor.get_tool_definitions(["edit_image"]) == [
        {"function": {"name": "edit_image"}}
    ]


def test_generation_snapshot_hard_overrides_llm_task_type():
    delegate = FakeToolExecutor()
    executor = StoryboardAgentImageToolExecutor(
        delegate,
        generation_snapshot={
            "task_id": 27,
            "model_key": "locked-model",
            "media_type": "image",
            "mode": "image_edit",
        },
    )

    executor.execute_tool(
        "edit_image",
        {"prompt": "edit", "image_url": "https://example.com/a.png", "task_type": 999},
        "1",
        "2",
        "token",
    )

    assert delegate.calls[0]["tool_args"]["task_type"] == 27


def test_generation_snapshot_hard_overrides_aspect_ratio_to_workflow_ratio():
    """对话改图：即使 Agent 漏传 aspect_ratio，也必须注入 storyboard.workflow_ratio。"""
    delegate = FakeToolExecutor()
    executor = StoryboardAgentImageToolExecutor(
        delegate,
        generation_snapshot={
            "task_id": 26,
            "ratio": "9:16",
            "media_type": "image",
            "mode": "image_edit",
        },
        workflow_ratio="9:16",
    )

    executor.execute_tool(
        "edit_image",
        {
            "prompt": "edit",
            "image_url": "https://example.com/a.png",
            # 故意不传 aspect_ratio，模拟工具 schema「无需传入」时 Agent 省略参数
        },
        "1",
        "2",
        "token",
    )

    assert delegate.calls[0]["tool_args"]["aspect_ratio"] == "9:16"


def test_workflow_ratio_overrides_wrong_llm_aspect_ratio():
    """Agent 传错 16:9 时，仍强制使用故事板 9:16。"""
    delegate = FakeToolExecutor()
    executor = StoryboardAgentImageToolExecutor(
        delegate,
        generation_snapshot={"task_id": 26, "ratio": "9:16"},
        workflow_ratio="9:16",
    )

    executor.execute_tool(
        "edit_image",
        {
            "prompt": "edit",
            "image_url": "https://example.com/a.png",
            "aspect_ratio": "16:9",
        },
        "1",
        "2",
        "token",
    )

    assert delegate.calls[0]["tool_args"]["aspect_ratio"] == "9:16"


def test_edit_image_merges_forced_reference_urls_when_llm_drops_characters():
    """双角色参考清单存在时，LLM 只传 1 个 URL 也必须补齐。"""
    from services.storyboard_agent_image_tool import merge_forced_reference_urls

    forced = [
        "https://cdn.test/role-a.png",
        "https://cdn.test/role-b.png",
        "https://cdn.test/location.png",
    ]
    assert merge_forced_reference_urls(forced, ["https://cdn.test/role-a.png"]) == forced

    delegate = FakeToolExecutor()
    executor = StoryboardAgentImageToolExecutor(
        delegate,
        forced_reference_urls=forced,
    )
    executor.execute_tool(
        "edit_image",
        {
            "prompt": "两人同框",
            "image_url": "https://cdn.test/role-a.png",
        },
        "1",
        "2",
        "token",
    )
    assert delegate.calls[0]["tool_name"] == "edit_image"
    assert delegate.calls[0]["tool_args"]["image_url"] == ",".join(forced)


def test_generate_text_to_image_converts_to_edit_image_when_forced_refs_exist():
    """有场景参考图时禁止降级文生图，强制走 edit_image 并带全量 URL。"""
    forced = [
        "https://cdn.test/role-a.png",
        "https://cdn.test/role-b.png",
    ]
    delegate = FakeToolExecutor()
    executor = StoryboardAgentImageToolExecutor(
        delegate,
        forced_reference_urls=forced,
        style="水墨",
        composition_preference="三分法",
    )
    executor.execute_tool(
        "generate_text_to_image",
        {"prompt": "两人同框"},
        "1",
        "2",
        "token",
    )
    assert delegate.calls[0]["tool_name"] == "edit_image"
    assert delegate.calls[0]["tool_args"]["image_url"] == ",".join(forced)
    assert "图片风格：水墨" in delegate.calls[0]["tool_args"]["prompt"]


def test_forced_reference_urls_keep_extra_llm_urls_after_authoritative_list():
    forced = ["https://cdn.test/role-a.png", "https://cdn.test/role-b.png"]
    delegate = FakeToolExecutor()
    executor = StoryboardAgentImageToolExecutor(
        delegate,
        forced_reference_urls=forced,
    )
    executor.execute_tool(
        "edit_image",
        {
            "prompt": "edit",
            "image_url": "https://cdn.test/role-a.png,https://cdn.test/user-extra.png",
        },
        "1",
        "2",
        "token",
    )
    assert delegate.calls[0]["tool_args"]["image_url"] == (
        "https://cdn.test/role-a.png,"
        "https://cdn.test/role-b.png,"
        "https://cdn.test/user-extra.png"
    )


def test_edit_image_rebuilds_reference_legend_to_match_forced_urls():
    """补齐 URL 后，prompt 末尾图例必须与最终 image_url 顺序一致。"""
    forced = [
        "https://cdn.test/role-a.png",
        "https://cdn.test/role-b.png",
        "https://cdn.test/location.png",
    ]
    items = [
        {"type": "角色", "name": "德保罗", "url": "https://cdn.test/role-a.png"},
        {"type": "角色", "name": "梅西", "url": "https://cdn.test/role-b.png"},
        {"type": "场景", "name": "街道", "url": "https://cdn.test/location.png"},
    ]
    delegate = FakeToolExecutor()
    executor = StoryboardAgentImageToolExecutor(
        delegate,
        forced_reference_urls=forced,
        forced_reference_items=items,
    )
    executor.execute_tool(
        "edit_image",
        {
            "prompt": "两人同框\n\n参考图说明：图1是角色：德保罗。",
            "image_url": "https://cdn.test/role-a.png",
        },
        "1",
        "2",
        "token",
    )
    prompt = delegate.calls[0]["tool_args"]["prompt"]
    assert delegate.calls[0]["tool_args"]["image_url"] == ",".join(forced)
    assert prompt.count("参考图说明：") == 1
    assert "图1是角色：德保罗" in prompt
    assert "图2是角色：梅西" in prompt
    assert "图3是场景：街道" in prompt
