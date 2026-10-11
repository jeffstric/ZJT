"""火山引擎（豆包语音）大模型语音合成专用常量。

独立于 config/constant.py 维护：音色清单与计价档位会随运营持续扩充，
避免主常量文件继续膨胀（AGENTS.md 规则 5 的"必要时新增"分支）。

接入/开通/计费说明见 docs/audio/volcengine_tts.md。
"""
import os


class VolcengineTtsConstants:
    """火山引擎（豆包语音）大模型语音合成常量。

    接口为 V3 单向流式 HTTP（openspeech.bytedance.com，一次性输入文本、
    chunked 流式返回音频帧），官方推荐大模型音色接入 V3。
    鉴权使用豆包语音控制台（语音技术）的 App Key + Access Key，
    与方舟 volcengine.api_key 不是同一套开通/计费体系。
    """
    API_HOST = "https://openspeech.bytedance.com"
    UNIDIRECTIONAL_PATH = "/api/v3/tts/unidirectional"
    RESOURCE_ID = "volc.service_type.10029"

    # 消息帧类型（4 字节头首字节低 4 位，与官方 v3 协议一致）
    MSG_TYPE_FULL_SERVER_RESPONSE = 0x9
    MSG_TYPE_AUDIO_ONLY_RESPONSE = 0xB
    MSG_TYPE_ERROR_RESPONSE = 0xF

    DEFAULT_ENCODING = "mp3"
    DEFAULT_SAMPLE_RATE = 24000
    DEFAULT_BITRATE = 128000

    # 快速合成为同步接口，单次请求必须显式超时（AGENTS.md 超时红线）
    TIMEOUT_SECONDS = 30
    PREVIEW_TIMEOUT_SECONDS = 20

    # 单次合成文本上限（字符）；火山按字符计费，上限同时是计价档位终点
    MAX_TEXT_LENGTH = 2000
    # 试听固定示例句：服务端写死防"自定义试听文本"套利（免费+按音色缓存）
    PREVIEW_TEXT = "你好，我是你的AI配音员，很高兴为你朗读这段文字。"

    # 语速语义与 DialogueTtsSpeedConstants 对齐（1.0 正常，>1 更快）
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


# 火山预置免费音色种子清单（voice 表 user_id=0 系统预置行的唯一事实来源）。
# ⚠️ 上线前请对照官方音色列表（volcengine.com/DoubaoVoice/Tonelist-1）核对
# voice_type 拼写与"免费"标记；个别音色若控制台不可用/需付费，直接把对应行
# 从该清单移除或在 voice 表置 is_active=0 即可（接口按 is_active 过滤）。
# 语言取值：zh / zh-dialect（方言）；多数中文音色支持中英混说。
VOLCENGINE_TTS_VOICES = [
    {"voice_type": "BV700_streaming", "name": "通用女声",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "标准通用女声，自然平稳，适合口播与旁白", "sort_order": 1},
    {"voice_type": "BV701_streaming", "name": "通用男声",
     "gender": "male", "language": "zh", "style": "通用",
     "description": "标准通用男声，沉稳大气，适合口播与旁白", "sort_order": 2},
    {"voice_type": "BV001_streaming", "name": "灿灿",
     "gender": "female", "language": "zh", "style": "阳光少女",
     "description": "阳光活力的少女音，情感表现丰富", "sort_order": 3},
    {"voice_type": "BV002_streaming", "name": "擎苍",
     "gender": "male", "language": "zh", "style": "低沉磁性",
     "description": "低沉磁性的男声，适合纪录片、宣传片", "sort_order": 4},
    {"voice_type": "BV100_streaming", "name": "燃烧的情绪女声",
     "gender": "female", "language": "zh", "style": "激情",
     "description": "充满激情的女声，适合热血、竞技解说", "sort_order": 5},
    {"voice_type": "BV104_streaming", "name": "燃烧的情绪男声",
     "gender": "male", "language": "zh", "style": "激情",
     "description": "充满激情的男声，适合热血、竞技解说", "sort_order": 6},
    {"voice_type": "BV120_streaming", "name": "惊奇小说女声",
     "gender": "female", "language": "zh", "style": "悬疑故事",
     "description": "娓娓道来的故事女声，适合小说、有声书", "sort_order": 7},
    {"voice_type": "BV123_streaming", "name": "惊奇小说男声",
     "gender": "male", "language": "zh", "style": "悬疑故事",
     "description": "沉浸感强的故事男声，适合小说、有声书", "sort_order": 8},
    {"voice_type": "BV102_streaming", "name": "螺丝书先生",
     "gender": "male", "language": "zh", "style": "评书说书",
     "description": "京腔评书风格男声，适合曲艺、说书类内容", "sort_order": 9},
    {"voice_type": "BV157_streaming", "name": "老铁女声",
     "gender": "female", "language": "zh-dialect", "style": "东北方言",
     "description": "东北方言女声，幽默接地气", "sort_order": 10},
    {"voice_type": "BV158_streaming", "name": "老铁男声",
     "gender": "male", "language": "zh-dialect", "style": "东北方言",
     "description": "东北方言男声，幽默接地气", "sort_order": 11},
    {"voice_type": "BV021_streaming", "name": "女主播",
     "gender": "female", "language": "zh", "style": "新闻播报",
     "description": "新闻播报风格女声，字正腔圆", "sort_order": 12},
    {"voice_type": "BV056_streaming", "name": "温柔少御",
     "gender": "female", "language": "zh", "style": "温柔知性",
     "description": "温柔知性的御姐音，适合情感、治愈内容", "sort_order": 13},
]


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
