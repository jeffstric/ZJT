"""火山引擎（豆包语音）大模型语音合成专用常量。

独立于 config/constant.py 维护：音色清单与计价档位会随运营持续扩充，
避免主常量文件继续膨胀（AGENTS.md 规则 5 的"必要时新增"分支）。

接入/开通/计费说明见 docs/audio/volcengine_tts.md。
2026-10 实测对齐语音合成 2.0（seed-tts-2.0）接口。
"""
import os


class VolcengineTtsConstants:
    """火山引擎（豆包语音）语音合成 2.0 常量。

    接口为 V3 单向流式 HTTP（openspeech.bytedance.com，一次性输入文本、
    chunked 流式返回 JSON 块，data 字段为 base64 音频）。
    鉴权使用新版豆包语音控制台的单 API Key（X-Api-Key 头），
    与方舟 volcengine.api_key 不是同一套体系。
    """
    API_HOST = "https://openspeech.bytedance.com"
    UNIDIRECTIONAL_PATH = "/api/v3/tts/unidirectional"
    # 语音合成大模型 2.0（官方文档 X-Api-Resource-Id 可选值；
    # seed-icl-2.0 为声音复刻 2.0，二期接入）
    RESOURCE_ID = "seed-tts-2.0"

    # 响应 JSON 块业务码：0=数据块正常；20000000=合成完成（结束块）
    OK_CODES = (0, 20000000)
    FINISH_CODE = 20000000

    DEFAULT_ENCODING = "mp3"
    DEFAULT_SAMPLE_RATE = 24000
    # mp3 比特率可选 [64000, 160000]
    DEFAULT_BITRATE = 64000

    # 快速合成为同步接口，单次请求必须显式超时（AGENTS.md 超时红线）
    TIMEOUT_SECONDS = 30
    PREVIEW_TIMEOUT_SECONDS = 20

    # 单次合成文本上限（字符）；火山按字符计费，上限同时是计价档位终点
    MAX_TEXT_LENGTH = 2000
    # 试听固定示例句：服务端写死防"自定义试听文本"套利（免费+按音色缓存）
    PREVIEW_TEXT = "你好，我是你的AI配音员，很高兴为你朗读这段文字。"

    # 语速：对外沿用 speed_ratio 语义（1.0 正常，>1 更快），请求体换算为
    # speech_rate = (speed_ratio - 1) * 100，取值范围 [-50, 100]（官方文档）。
    SPEED_DEFAULT = 1.0
    SPEED_MIN = 0.5
    SPEED_MAX = 2.0

    # 字符档位计价：文本字符数 ≤ 档位上限 → 消耗对应整数算力（向上取整吸附，
    # 与视频按时长吸附档位同构）。默认按 0.0008 元/字符定价（火山后付费成本约
    # 5 元/万字符 = 0.0005 元/字符，1 算力 = 0.04 元）。运营可通过动态配置
    # volcengine_tts.power_tiers 热更新（DB 优先、YAML 兜底），格式为
    # [[上限字符, 算力], ...] 升序列表。
    POWER_TIERS = [
        (50, 1),
        (200, 4),
        (500, 10),
        (1000, 20),
        (2000, 40),
    ]

    # 本地落盘目录（相对项目根），对外 URL 为 {server_host}/upload/tts/volcengine/
    RESULT_SUBDIR = os.path.join("upload", "tts", "volcengine")
    PREVIEW_FILENAME_PREFIX = "preview_"


# 火山语音合成 2.0 预置音色种子清单（voice 表 user_id=0 系统预置行的唯一事实来源）。
# ⚠️ 音色 ID 为 2.0 音色库（控制台 > 音色库）实测可用的 *_uranus_bigtts 系列，
# 2026-10-12 逐一合成验证通过；后续增补直接追加行 + 迁移（或后台 INSERT）。
# 语言取值：zh；2.0 音色普遍支持中英混说。
VOLCENGINE_TTS_VOICES = [
    {"voice_type": "zh_female_vv_uranus_bigtts", "name": "Vivi 2.0",
     "gender": "female", "language": "zh", "style": "治愈柔和",
     "description": "语调平稳、咬字柔和、自带治愈安抚力的女声，适合客服与陪伴场景", "sort_order": 1},
    {"voice_type": "zh_female_xiaohe_uranus_bigtts", "name": "小何 2.0",
     "gender": "female", "language": "zh", "style": "甜美活力",
     "description": "声线甜美有活力的妹妹音，活泼开朗，适合口播与有声阅读", "sort_order": 2},
    {"voice_type": "zh_male_wennuanahu_uranus_bigtts", "name": "温暖阿虎 2.0",
     "gender": "male", "language": "zh", "style": "温暖沉稳",
     "description": "温暖沉稳的男声，亲和力强，适合旁白与讲故事", "sort_order": 3},
    {"voice_type": "zh_male_jieshuoxiaoming_uranus_bigtts", "name": "解说小明 2.0",
     "gender": "male", "language": "zh", "style": "解说配音",
     "description": "专业解说风格男声，适合纪录片、影视解说", "sort_order": 4},
    {"voice_type": "zh_female_wenroumama_uranus_bigtts", "name": "温柔妈妈 2.0",
     "gender": "female", "language": "zh", "style": "温柔亲切",
     "description": "温柔亲切的成熟女声，适合母婴、生活类内容", "sort_order": 5},
    {"voice_type": "zh_female_sophie_uranus_bigtts", "name": "魅力苏菲 2.0",
     "gender": "female", "language": "zh", "style": "知性优雅",
     "description": "知性优雅的女声，适合品牌宣传、情感内容", "sort_order": 6},
    {"voice_type": "zh_female_meilinvyou_uranus_bigtts", "name": "魅力女友 2.0",
     "gender": "female", "language": "zh", "style": "妩媚成熟",
     "description": "性感妩媚的御姐音，成熟有魅力，适合直播、视频配音", "sort_order": 7},
]


def speed_ratio_to_speech_rate(speed_ratio: float) -> int:
    """speed_ratio（1.0 正常，>1 更快）→ 2.0 接口 speech_rate（-50~100，100=2.0倍速）。"""
    speed = normalize_volcengine_tts_speed(speed_ratio)
    return int(round((speed - 1.0) * 100))


def calc_volcengine_tts_power(char_count: int, tiers=None) -> int:
    """按字符档位向上取整吸附计价：取第一个 上限≥char_count 的档位算力。

    超出最大档位返回 0（调用方应按超长文本拒绝）；空/非法档位配置同样返回 0。
    """
    if not tiers:
        tiers = VolcengineTtsConstants.POWER_TIERS
    try:
        count = int(char_count)
    except (TypeError, ValueError):
        return 0
    if count <= 0:
        return 0
    for limit, power in tiers:
        try:
            if count <= int(limit) and int(power) > 0:
                return int(power)
        except (TypeError, ValueError):
            continue
    return 0


def normalize_volcengine_tts_speed(value) -> float:
    """火山 TTS 语速归一化：收敛到 [SPEED_MIN, SPEED_MAX]，非法返回默认。"""
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return VolcengineTtsConstants.SPEED_DEFAULT
    if speed != speed:  # NaN
        return VolcengineTtsConstants.SPEED_DEFAULT
    return round(min(VolcengineTtsConstants.SPEED_MAX,
                     max(VolcengineTtsConstants.SPEED_MIN, speed)), 2)
