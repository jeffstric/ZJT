"""
故事板 ↔ 工作流画布互转（api/storyboard_conversion.py）纯函数单测

只覆盖无 DB 依赖的转换核心：帧收集归组与视频产物挂接、parsed_data 重建与
资产收集、场景→shot 映射、workflow_data 组装（含视频节点）。落库与端点行为
由本地冒烟验证（见 docs/storyboard/storyboard_workflow_conversion.md）。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _seed_config(monkeypatch):
    monkeypatch.setenv("comfyui_env", "unit")
    import config.config_util as config_util

    config_util._config_cache["config_unit.yml"] = {
        "database": {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "unit",
            "password": "unit",
            "database": "unit",
        }
    }


def _frame(node_id, shot_id, shot_number=None, y=0, x=0, image_url='', last_frame_url='',
           dialogue=None, db_info=None, present=None):
    shot = {
        'shot_id': shot_id,
        'shot_number': shot_number,
        'duration': 5,
        'location_name': '夜市街口',
        'description': '描述',
        'opening_frame_description': '首帧描述',
        'scene_detail': '细节',
        'dialogue': dialogue or [],
        'characters_present': present or [],
        'db_character_info': db_info or [],
    }
    return {
        'id': node_id, 'type': 'shot_frame', 'title': str(node_id), 'x': x, 'y': y,
        'data': {'shotJson': shot, 'imageUrl': image_url, 'lastFrameUrl': last_frame_url},
    }


def _video_node(node_id, url, y=0, x=0):
    return {'id': node_id, 'type': 'video', 'title': '视频', 'x': x, 'y': y,
            'data': {'url': url, 'name': '分镜视频', 'project_id': None}}


def test_collect_frames_groups_and_collects_videos():
    from api.storyboard_conversion import _collect_frames_from_workflow

    group_a = {'id': 10, 'type': 'shot_group', 'title': '第一幕', 'x': 800, 'y': 0, 'data': {'groupId': 'g1'}}
    f1 = _frame(11, 's002', shot_number=2)   # 组内按 shot_number 排序
    f2 = _frame(12, 's001', shot_number=1)
    f3 = _frame(21, 's003', shot_number=3)
    v1 = _video_node(31, 'https://cdn.example.com/v1.mp4')
    v2 = _video_node(32, 'https://cdn.example.com/v2.mp4')
    v_blob = _video_node(33, 'blob:http://localhost/xyz')   # blob 临时产物不收集
    v_empty = _video_node(34, '')
    v_rel = _video_node(35, '/upload/workflow/1/a.mp4')     # 站内相对路径有效
    other = {'id': 99, 'type': 'image', 'title': 'i', 'x': 0, 'y': 0, 'data': {}}
    workflow_data = {
        'nodes': [other, group_a, f1, f2, f3, v1, v2, v_blob, v_empty, v_rel,
                  {'id': 40, 'type': 'image', 'title': '分镜图', 'x': 1800, 'y': 0,
                   'data': {'url': 'https://cdn.example.com/gen1.png', 'preview': 'https://cdn.example.com/gen1.png', 'name': '分镜图'}},
                  {'id': 41, 'type': 'image', 'title': '分镜图', 'x': 1800, 'y': 280,
                   'data': {'url': 'https://cdn.example.com/gen2.png', 'name': '分镜图'}},
                  {'id': 42, 'type': 'image', 'title': '无URL图', 'x': 1800, 'y': 560, 'data': {}}],
        'connections': [
            {'id': 1, 'from': 10, 'to': 11},
            {'id': 2, 'from': 10, 'to': 12},
            {'id': 3, 'from': 10, 'to': 21},
            # 分镜帧 → 视频节点（视频产物挂接）
            {'id': 4, 'from': 12, 'to': 31},
            {'id': 5, 'from': 12, 'to': 32},
            {'id': 6, 'from': 12, 'to': 33},
            {'id': 7, 'from': 12, 'to': 34},
            {'id': 8, 'from': 12, 'to': 35},
            # 分镜帧 → 图片节点（原生"生成分镜图"产物形态）
            {'id': 9, 'from': 11, 'to': 40},
            {'id': 10, 'from': 11, 'to': 41},
            {'id': 11, 'from': 11, 'to': 42},
        ],
    }
    groups, script_meta, frame_videos, frame_images = _collect_frames_from_workflow(workflow_data)

    assert [g['group_name'] for g in groups] == ['第一幕']
    assert [f['id'] for f in groups[0]['frames']] == [12, 11, 21]
    # http 绝对地址与站内相对路径收集，blob:/空被过滤
    assert frame_videos == {12: ['https://cdn.example.com/v1.mp4', 'https://cdn.example.com/v2.mp4',
                                 '/upload/workflow/1/a.mp4']}
    # 连线图片节点按连线顺序收集（无 URL 的被过滤）
    assert frame_images == {11: ['https://cdn.example.com/gen1.png', 'https://cdn.example.com/gen2.png']}
    assert script_meta['script_id'] is None


def test_build_parsed_data_collects_assets():
    from api.storyboard_conversion import _build_parsed_data_from_frames

    frame = _frame(
        1, 's001', dialogue=[{'character_name': '林小雨', 'text': '你好'}],
        db_info=[{'character_id': 'c1', 'db_character_id': 2, 'db_character_name': '林小雨'}],
        last_frame_url='https://cdn.example.com/a_last.png',
        # 自带图为空：首帧应回退到连线 image 节点（原生"生成分镜图"只写图片节点）
    )
    groups = [{
        'group_id': 'g1', 'group_name': '第一幕',
        # 无剧本节点画布：分组 scriptData 携带角色/道具名册
        'script_data': {'characters': [{'id': '2', 'name': '林小雨', 'character_db_id': 2}],
                        'props': [{'id': 'p1', 'name': '袋子', 'props_db_id': 9}]},
        'frames': [frame],
    }]
    frame_videos = {1: ['https://cdn.example.com/v1.mp4']}
    frame_images = {1: ['https://cdn.example.com/gen1.png', 'https://cdn.example.com/gen2.png']}
    parsed_data, assets = _build_parsed_data_from_frames(
        groups, {'parsed_data': {}}, style='写实', frame_videos=frame_videos, frame_images=frame_images)

    # 分组 scriptData 回退为角色/道具名册
    assert {'id': '2', 'name': '林小雨', 'character_db_id': 2} in parsed_data['characters']
    assert (parsed_data['props'] or [{}])[0]['name'] == '袋子'
    shot = parsed_data['shot_groups'][0]['shots'][0]
    assert shot['dialogue'][0]['character_id'] == '2'
    # 资产按 source_shot_key 收集：连线图首张为选中首帧，全部作为候选
    assert assets == {
        's001': {
            'first_frame': 'https://cdn.example.com/gen1.png',
            'last_frame': 'https://cdn.example.com/a_last.png',
            'videos': ['https://cdn.example.com/v1.mp4'],
            'image_candidates': ['https://cdn.example.com/gen1.png', 'https://cdn.example.com/gen2.png'],
        }
    }
    assert parsed_data['style'] == '写实'


def test_build_scenes_payload_via_shared_builder():
    """parsed_data 重建结果能被 build_storyboard_scenes_from_parsed_script 正常消费。"""
    from api.storyboard import build_storyboard_scenes_from_parsed_script
    from api.storyboard_conversion import _build_parsed_data_from_frames

    frame = _frame(
        1, 's001', dialogue=[{'character_name': '林小雨', 'text': '你好'}],
        db_info=[{'character_id': 'c1', 'db_character_id': 2, 'db_character_name': '林小雨'}],
    )
    parsed_data, _ = _build_parsed_data_from_frames(
        [{'group_id': 'g1', 'group_name': '第一幕', 'frames': [frame]}], {}, '', {})

    payloads = build_storyboard_scenes_from_parsed_script(parsed_data)
    assert len(payloads) == 1
    scene = payloads[0]
    assert scene['source_shot_key'] == 's001'
    assert scene['dialogues'] and scene['dialogues'][0]['character_id'] == 2
    assert scene['act_name'] == '第一幕'


def test_scene_to_shot_field_mapping():
    from api.storyboard_conversion import _scene_to_shot

    scene = {
        'id': 7, 'title': '分镜1', 'duration': 4.5,
        'prompt_json': {
            'perspective': '中景', 'scene_desc': '夜市街口', 'character_desc': '林小雨',
            'location': {'id': 3, 'name': '码头'},
            'props': [{'id': 'p1', 'name': '袋子', 'db_id': 9}],
        },
        'video_prompt': '镜头推进，穿过人群',
        'video_config_json': {'shot_type': '中景', 'camera_movement': '推进'},
        'source_shot_key': 's009',
        'video_type': 'digital_human',
        'dialogues': [{'character_id': 2, 'text': '到货了。'}],
    }
    shot, props, db_info = _scene_to_shot(scene, 3, {2: '林小雨'})

    assert shot['shot_id'] == 's009'           # 沿用原 key，键稳定可追溯
    assert shot['shot_number'] == 3
    assert shot['duration'] == 4.5
    # 场景显式类型随 shotJson 往返（反向 resolve_scene_video_type 经 _llm_presentation 采信）
    assert shot['video_type'] == 'digital_human'
    assert shot['opening_frame_description'] == '中景，夜市街口，林小雨'
    assert shot['description'] == '镜头推进，穿过人群'
    assert shot['db_location_id'] == 3 and shot['location_name'] == '码头'
    assert shot['dialogue'] == [{'character_name': '林小雨', 'text': '到货了。', 'character_id': '2'}]
    assert shot['db_character_info'] == [{'character_id': '2', 'db_character_id': 2, 'db_character_name': '林小雨'}]
    assert shot['characters_present'] == ['2']
    assert props == [{'id': 'p1', 'name': '袋子', 'props_db_id': 9}]
    assert db_info and db_info[0]['db_character_name'] == '林小雨'

    # 无 source_shot_key 的手工场景 → sb_ 前缀
    shot2, _, _ = _scene_to_shot({**scene, 'source_shot_key': None}, 4, {2: '林小雨'})
    assert shot2['shot_id'] == 'sb_7'


def test_build_workflow_data_carries_assets():
    """故事板选中首帧进视频首帧槽并连到分镜首帧端口；尾帧只写 lastFrameUrl。"""
    from api.storyboard_conversion import _build_workflow_data_from_storyboard

    storyboard = SimpleNamespace(
        id=4, title='测试板', world_id=1, workflow_ratio='16:9', style='写实',
        style_reference_image='', composition_preference='',
        script_id=None,
    )
    scenes = [
        {
            'id': 11, 'title': '分镜1', 'duration': 5, 'act_name': '第一幕',
            'prompt_json': {'perspective': '', 'scene_desc': '码头清晨', 'character_desc': '',
                            'location': {}, 'props': []},
            'video_prompt': '货轮进港', 'video_config_json': {}, 'source_shot_key': 's101',
            'first_frame_url': 'https://cdn/f1.png',
            'last_frame_url': 'https://cdn/f1_last.png',
            'video_url': 'https://cdn/v1.mp4',
            'dialogues': [],
        },
        {
            'id': 12, 'title': '分镜2', 'duration': 4, 'act_name': '第一幕',
            'prompt_json': {'perspective': '', 'scene_desc': '甲板', 'character_desc': '',
                            'location': {}, 'props': []},
            'video_prompt': '', 'video_config_json': {}, 'source_shot_key': None,
            'first_frame_url': '', 'last_frame_url': '', 'video_url': '',
            'dialogues': [],
        },
    ]
    wf = _build_workflow_data_from_storyboard(storyboard, scenes, {2: '陈默'}, None)

    nodes = {n['id']: n for n in wf['nodes']}
    types = sorted(n['type'] for n in wf['nodes'])
    # 2 分镜帧 + 1 分镜组 + 1 图片（分镜1有首帧）+ 1 视频（只有分镜1有视频）
    assert types == ['image', 'shot_frame', 'shot_frame', 'shot_group', 'video']

    frame1 = next(n for n in wf['nodes'] if n['type'] == 'shot_frame' and n['data']['shotJson']['shot_id'] == 's101')
    # 首帧在「视频首帧」槽，不写入 imageUrl（那个槽画在尾帧控件下面，会看起来像尾帧）
    assert frame1['data']['previewImageUrl'] == 'https://cdn/f1.png'
    assert frame1['data']['imageUrl'] == ''
    assert frame1['data']['lastFrameUrl'] == 'https://cdn/f1_last.png'

    image_node = next(n for n in wf['nodes'] if n['type'] == 'image')
    assert image_node['data']['url'] == 'https://cdn/f1.png'
    assert image_node['data']['name'] == '分镜1图'
    assert image_node['title'] == '分镜1图'   # 与原生生成产物一致（title 与 data.name 同值）

    # 本机绝对 URL（生成链路写死的 host:port）→ 相对路径，画布可跨端口移植
    frame_local = _frame(21, 's201', image_url='http://127.0.0.1:13010/upload/cache/x.png')
    scenes_local = [dict(scenes[0], source_shot_key='s201',
                         first_frame_url='http://localhost:13004/upload/cache/y.png',
                         video_url='', last_frame_url='')]
    wf2 = _build_workflow_data_from_storyboard(storyboard, scenes_local, {}, None)
    img_local = next(n for n in wf2['nodes'] if n['type'] == 'image')
    assert img_local['data']['url'] == '/upload/cache/y.png'
    f_local = next(n for n in wf2['nodes'] if n['type'] == 'shot_frame')
    assert f_local['data']['previewImageUrl'] == '/upload/cache/y.png'
    assert f_local['data']['imageUrl'] == ''
    assert f_local['data']['lastFrameUrl'] == ''
    # 没有视频时，首帧图仍然连到分镜「视频首帧」端口，且不产生尾帧连线
    assert wf2['firstFrameConnections'] == [{'id': 1, 'from': img_local['id'], 'to': f_local['id']}]
    assert wf2['lastFrameConnections'] == []
    # 连线：分镜帧 → 图片节点（与画布原生"生成分镜图"产物形态一致）
    pair = {(c['from'], c['to']) for c in wf['connections']}
    assert (frame1['id'], image_node['id']) in pair

    video_node = next(n for n in wf['nodes'] if n['type'] == 'video')
    assert video_node['data']['url'] == 'https://cdn/v1.mp4'
    assert video_node['data']['name'] == '分镜1视频'
    assert (frame1['id'], video_node['id']) in pair
    # 首帧连线指向分镜节点的视频首帧端口，不指向视频节点
    assert wf['firstFrameConnections'] == [{'id': 1, 'from': image_node['id'], 'to': frame1['id']}]
    assert wf['lastFrameConnections'] == []
    assert wf['nextFirstFrameConnId'] == 2

    # 无图无视频场景不产生 image/video 节点
    frame2 = next(n for n in wf['nodes'] if n['type'] == 'shot_frame'
                  and n['data']['shotJson']['shot_id'] == 'sb_12')
    assert frame2['data']['previewImageUrl'] == ''
    assert frame2['data']['imageUrl'] == '' and frame2['data']['lastFrameUrl'] == ''
    assert not any(c['from'] == frame2['id'] for c in wf['connections'])

    # 计数器覆盖全部节点与连线
    assert wf['nextNodeId'] == max(nodes) + 1
    assert wf['nextConnId'] == len(wf['connections']) + 1
