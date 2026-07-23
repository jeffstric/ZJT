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
