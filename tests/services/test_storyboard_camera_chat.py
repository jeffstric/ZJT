# -*- coding: utf-8 -*-
"""故事板「对话改机位」服务测试：消息组装 / JSON 解析 / clamp。"""
import unittest

from services.storyboard_camera_chat import (
    build_camera_chat_messages,
    parse_camera_instruction,
    parse_camera_json,
)


class TestBuildCameraChatMessages:
    def test_消息含当前机位与指令(self):
        messages = build_camera_chat_messages(
            "把机位移到赵志高正面",
            {"eye": {"x": -0.6, "y": 1.5, "z": 1.8}, "target": {"x": 0.2, "y": 0.8, "z": -0.2}, "fov": 50},
            entities=[],
        )
        assert len(messages) == 1
        content = messages[0]["content"]
        assert "eye=[-0.60, 1.50, 1.80]" in content
        assert "fov=50" in content
        assert "把机位移到赵志高正面" in content

    def test_实体清单带类型与朝向(self):
        messages = build_camera_chat_messages(
            "拉远",
            {"eye": {"x": 0, "y": 1.5, "z": 4}, "target": {"x": 0, "y": 1, "z": 0}, "fov": 40},
            entities=[
                {"name": "赵志高", "kind": "actor", "x": -0.5, "z": 0.5, "facing": 0},
                {"name": "值班桌", "kind": "stage", "x": 1.2, "z": 0.6},
            ],
        )
        content = messages[0]["content"]
        assert "赵志高（actor）x=-0.50, z=0.50 朝向0°" in content
        assert "值班桌（stage）x=1.20, z=0.60" in content

    def test_实体清单截断与指令截断不抛错(self):
        entities = [{"name": f"对象{i}", "kind": "actor", "x": i, "z": 0} for i in range(100)]
        messages = build_camera_chat_messages("很" * 500, {"eye": {}, "target": {}}, entities=entities)
        assert "对象39" in messages[0]["content"]
        assert "对象40" not in messages[0]["content"]
        assert len(messages[0]["content"]) < 2000


class TestParseCameraJson:
    def test_裸JSON解析(self):
        parsed = parse_camera_json('{"eye":[1,2,3],"target":[0,1,0],"fov":45,"reason":"拉远"}')
        assert parsed["eye"] == {"x": 1, "y": 2, "z": 3}
        assert parsed["fov"] == 45
        assert parsed["reason"] == "拉远"
        assert "success" not in parsed  # success 由上层补充，解析层不设置

    def test_markdown围栏JSON解析(self):
        content = '好的，这是新机位：\n```json\n{"eye":[0,1.5,4],"target":[0,1,0],"fov":40}\n```\n完成'
        parsed = parse_camera_json(content)
        assert parsed["eye"]["z"] == 4
        assert parsed["fov"] == 40

    def test_超界clamp(self):
        parsed = parse_camera_json('{"eye":[99, 50, -99],"target":[0, -8, 0],"fov":300}')
        assert parsed["eye"]["x"] == 30.0
        assert parsed["eye"]["y"] == 12.0
        assert parsed["eye"]["z"] == -30.0
        assert parsed["target"]["y"] == -2.0
        assert parsed["fov"] == 120

    def test_缺字段返回None(self):
        assert parse_camera_json('{"target":[0,1,0],"fov":50}') is None
        assert parse_camera_json("不是JSON") is None
        assert parse_camera_json("") is None


class TestParseCameraInstruction(unittest.IsolatedAsyncioTestCase):
    async def test_缺模型直接失败(self):
        result = await parse_camera_instruction(
            "拉远",
            {"eye": {"x": 0, "y": 1.5, "z": 4}, "target": {"x": 0, "y": 1, "z": 0}, "fov": 40},
        )
        self.assertFalse(result["success"])
        self.assertIn("模型", result["error"])


class TestDualFormatAndRobustness:
    """三轮自测补充：eye/target 双格式 + 非法入参健壮性。"""

    def test_parse支持对象格式eye(self):
        # LLM 偶尔返回 {x,y,z} 对象而非数组
        parsed = parse_camera_json('{"eye":{"x":1,"y":2,"z":3},"target":{"x":0,"y":1,"z":0},"fov":45}')
        assert parsed['eye'] == {'x': 1.0, 'y': 2.0, 'z': 3.0}
        assert parsed['fov'] == 45

    def test_messages_机位为字符串或None不崩(self):
        for bad in ('not-a-dict', None, 42):
            msgs = build_camera_chat_messages('升高', bad, [])
            assert 'eye=[0.00, 0.00, 0.00]' in msgs[0]['content']

    def test_messages_数组格式机位(self):
        msgs = build_camera_chat_messages('升高', {'eye': [2, 1.8, 9], 'target': [1.2, 1.2, -1], 'fov': 55}, [])
        assert 'eye=[2.00, 1.80, 9.00]' in msgs[0]['content']
