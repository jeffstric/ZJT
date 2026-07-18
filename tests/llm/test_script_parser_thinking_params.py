import json
import asyncio
from types import SimpleNamespace

from llm import script_parser


def test_parse_script_to_shots_passes_thinking_params_to_llm_client(monkeypatch):
    captured = {}

    class FakeClient:
        def call_api(self, **kwargs):
            captured.update(kwargs)
            content = json.dumps({
                "characters": [],
                "locations": [],
                "props": [],
                "shot_groups": [],
            })
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content)
                    )
                ]
            )

    monkeypatch.setattr(script_parser, "ENABLE_SCRIPT_PARSER_LOGGING", False)
    monkeypatch.setattr(script_parser, "get_llm_client", lambda model, vendor_id=None: FakeClient())

    asyncio.run(
        script_parser.parse_script_to_shots(
            script_content="INT. ROOM - DAY",
            model="deepseek-v4-flash",
            vendor_id=10,
            model_id=1007,
            enable_thinking=True,
            thinking_effort="high",
        )
    )

    assert captured["vendor_id"] == 10
    assert captured["model_id"] == 1007
    assert captured["enable_thinking"] is True
    assert captured["thinking_effort"] == "high"
