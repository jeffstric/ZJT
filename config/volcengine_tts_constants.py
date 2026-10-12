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
# 来源：官方音色列表文档（byteplusvoice/tts-voice-list）全量 2.0 音色共 176 个，
# 覆盖 16 种语言；中文 23 个 + 多语言代表已实测合成验证通过（2026-10-12）。
# 后续增补直接追加行 + 迁移（或后台 INSERT voice 表）。
VOLCENGINE_TTS_VOICES = [
    {"voice_type": "ar_female_dina_uranus_bigtts", "name": "Dina",
     "gender": "female", "language": "ar", "style": "通用",
     "description": "A warm and lively Egyptian woman, deeply versed in local culture", "sort_order": 1},
    {"voice_type": "ar_female_fatma_uranus_bigtts", "name": "Fatma",
     "gender": "female", "language": "ar", "style": "Entertainment",
     "description": "A young woman with a gentle, tender voice, often heard in soft solo monologues", "sort_order": 2},
    {"voice_type": "ar_male_youssef_uranus_bigtts", "name": "Youssef",
     "gender": "male", "language": "ar", "style": "通用",
     "description": "A middle-aged man with a calm, easygoing tone, speaking in an intimate, conversational manner", "sort_order": 3},
    {"voice_type": "de_female_bv081_uranus_bigtts", "name": "Stella",
     "gender": "female", "language": "de", "style": "Education",
     "description": "A young female voice that is objective, composed, and professional", "sort_order": 4},
    {"voice_type": "de_male_sven_uranus_bigtts", "name": "Sven",
     "gender": "male", "language": "de", "style": "通用",
     "description": "A middle-aged man with a deep, magnetic, slightly raspy voice", "sort_order": 5},
    {"voice_type": "en_female_allison_uranus_bigtts", "name": "Allison",
     "gender": "female", "language": "en", "style": "Dubbing",
     "description": "An upbeat, enthusiastic college-aged woman, full of energy and warmth", "sort_order": 6},
    {"voice_type": "en_female_authoritative", "name": "Margaret",
     "gender": "female", "language": "en", "style": "通用",
     "description": "A gentle, sincere big sister who tells her story in a soft, unhurried way", "sort_order": 7},
    {"voice_type": "en_female_brittney_pimintel_uranus_bigtts", "name": "Zoe",
     "gender": "female", "language": "en", "style": "有声书",
     "description": "A calm, gentle young female voice with a steady, understated storytelling tone", "sort_order": 8},
    {"voice_type": "en_female_brittney_uranus_bigtts", "name": "Brittney",
     "gender": "female", "language": "en", "style": "通用",
     "description": "A warm, intelligent older sister with a tender heart", "sort_order": 9},
    {"voice_type": "en_female_dacey_uranus_bigtts", "name": "Dacey",
     "gender": "female", "language": "en", "style": "通用",
     "description": "A crisp, confident, and engaging young female voice", "sort_order": 10},
    {"voice_type": "en_female_female_tutor_ms", "name": "Holly",
     "gender": "female", "language": "en", "style": "Education",
     "description": "An enthusiastic, energetic female host with a vivid, standout style", "sort_order": 11},
    {"voice_type": "en_female_hayley_uranus_bigtts", "name": "Hayley",
     "gender": "female", "language": "en", "style": "Education",
     "description": "A lively female voice with strong emotional tension, skilled at storytelling", "sort_order": 12},
    {"voice_type": "en_female_jane_uranus_bigtts", "name": "Jane",
     "gender": "female", "language": "en", "style": "Dubbing",
     "description": "An energetic young girl with outwardly vivid, expressive emotion", "sort_order": 13},
    {"voice_type": "en_female_jenny_uranus_bigtts", "name": "Jenny",
     "gender": "female", "language": "en", "style": "通用",
     "description": "A naturally cheerful, smiling, warm and talkative personality", "sort_order": 14},
    {"voice_type": "en_female_joanne_uranus_bigtts", "name": "Joanne",
     "gender": "female", "language": "en", "style": "通用",
     "description": "A crisp, lively American young female voice with a light tone and a relaxed, natural conversational feel", "sort_order": 15},
    {"voice_type": "en_female_lana_del_rey_kelley_d_p1_uranus_bigtts", "name": "Lynn",
     "gender": "female", "language": "en", "style": "RolePlay",
     "description": "An American young female voice—soft, slow and slightly husky", "sort_order": 16},
    {"voice_type": "en_female_lana_del_rey_parky_s_p1_uranus_bigtts", "name": "Ivy",
     "gender": "female", "language": "en", "style": "CustomerService",
     "description": "A gentle, soft female voice with a warm, natural tone that is soothing to the ear", "sort_order": 17},
    {"voice_type": "en_female_mel_uranus_bigtts", "name": "Mel",
     "gender": "female", "language": "en", "style": "Education",
     "description": "A lively, dynamic American female voice with vivid ups and downs, skilled at performing animated dialogue", "sort_order": 18},
    {"voice_type": "en_female_myra_cmb_uranus_bigtts", "name": "Sunny",
     "gender": "female", "language": "en", "style": "Education",
     "description": "A crisp, lively American young female voice—full of enthusiasm and outstanding expressiveness", "sort_order": 19},
    {"voice_type": "en_female_myra_uranus_bigtts", "name": "Myra",
     "gender": "female", "language": "en", "style": "Education",
     "description": "A sweet, lively young-girl voice that tells stories in a gentle, moving way", "sort_order": 20},
    {"voice_type": "en_female_nadia_uranus_bigtts", "name": "Blair",
     "gender": "female", "language": "en", "style": "通用",
     "description": "A young American female voice—clean and clear, with a gentle, relaxed way of speaking", "sort_order": 21},
    {"voice_type": "en_female_natasha_uranus_bigtts", "name": "Natasha",
     "gender": "female", "language": "en", "style": "通用",
     "description": "A conversational female voice—bright and vivid, warm and approachable", "sort_order": 22},
    {"voice_type": "en_female_pleasant", "name": "Elaine",
     "gender": "female", "language": "en", "style": "有声书",
     "description": "A gentle, lovely young lady who tells you the little joys of life with heartfelt warmth", "sort_order": 23},
    {"voice_type": "en_female_rachel_p1_uranus_bigtts", "name": "Rachel",
     "gender": "female", "language": "en", "style": "Entertainment",
     "description": "An outwardly expressive young female voice—bright and clear, with strong dramatic flair", "sort_order": 24},
    {"voice_type": "en_female_scarlet_p1_uranus_bigtts", "name": "Scarlet",
     "gender": "female", "language": "en", "style": "CustomerService",
     "description": "A gentle, deeply affectionate older sister whose eyes always hold a spark of light", "sort_order": 25},
    {"voice_type": "en_female_sharron_uranus_bigtts", "name": "Sharron",
     "gender": "female", "language": "en", "style": "Entertainment",
     "description": "A soft-spoken young woman with a gentle, breathy whisper voice—slightly husky, intimate, and soothing, with a ", "sort_order": 26},
    {"voice_type": "en_female_skye_uranus_bigtts", "name": "Skye",
     "gender": "female", "language": "en", "style": "通用",
     "description": "A clear, candid older sister who speaks sincerely and from the heart", "sort_order": 27},
    {"voice_type": "en_female_stokie_uranus_bigtts", "name": "Stokie",
     "gender": "female", "language": "en", "style": "通用",
     "description": "A trendy, casual, and expressive young female voice", "sort_order": 28},
    {"voice_type": "en_female_wenrouzhishijieshuonv_uranus_bigtts", "name": "Megan",
     "gender": "female", "language": "en", "style": "CustomerService",
     "description": "A gentle, fun older sister with American pronunciation who shares interesting knowledge in a relaxed way.", "sort_order": 29},
    {"voice_type": "en_female_xinwenjieshuonv_uranus_bigtts", "name": "Kayla",
     "gender": "female", "language": "en", "style": "RolePlay",
     "description": "An enthusiastic, outgoing female college student with American pronunciation, full of emotion and expressivene", "sort_order": 30},
    {"voice_type": "en_female_zendaya_p1_uranus_bigtts", "name": "Zendaya",
     "gender": "female", "language": "en", "style": "Education",
     "description": "An easygoing, approachable older sister—relaxed and unpretentious, yet full of energy.", "sort_order": 31},
    {"voice_type": "en_male_adam", "name": "Rowan",
     "gender": "male", "language": "en", "style": "通用",
     "description": "An easygoing, natural young man with a subtly cool, aloof edge", "sort_order": 32},
    {"voice_type": "en_male_alberto_uranus_bigtts", "name": "Alberto",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A gentle, approachable man with a low, soothing tone", "sort_order": 33},
    {"voice_type": "en_male_alex_uranus_bigtts", "name": "Alex",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A young man who is objective and composed, with a warm, clear voice", "sort_order": 34},
    {"voice_type": "en_male_bill", "name": "Jones",
     "gender": "male", "language": "en", "style": "Entertainment",
     "description": "A humorous uncle with a thick Southern American rural accent", "sort_order": 35},
    {"voice_type": "en_male_bill_jones_corey_uranus_bigtts", "name": "Bill",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A steady, self-assured male professional with poise and composure", "sort_order": 36},
    {"voice_type": "en_male_brad_pitt_p1_uranus_bigtts", "name": "Brad_Pitt",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A laid-back man with a low, husky voice and a relaxed, easygoing manner", "sort_order": 37},
    {"voice_type": "en_male_bruce_uranus_bigtts", "name": "Adrian",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A composed, level-headed gentleman with rational restraint", "sort_order": 38},
    {"voice_type": "en_male_chandler_p1_uranus_bigtts", "name": "Leo",
     "gender": "male", "language": "en", "style": "Entertainment",
     "description": "A theatrical man with exaggerated, dramatic intonation and rich expressiveness", "sort_order": 39},
    {"voice_type": "en_male_cowboy", "name": "Bob",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A mature man with a deep, resonant, slightly raspy voice and a relaxed, calm demeanor", "sort_order": 40},
    {"voice_type": "en_male_cowboy_john_b_uranus_bigtts", "name": "John",
     "gender": "male", "language": "en", "style": "Entertainment",
     "description": "An energetic, flamboyant uncle with a Southern American accent", "sort_order": 41},
    {"voice_type": "en_male_david_uranus_bigtts", "name": "David",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A middle-aged man with a deep, weighty voice, an unhurried pace, and natural pauses", "sort_order": 42},
    {"voice_type": "en_male_deep", "name": "Orion",
     "gender": "male", "language": "en", "style": "Entertainment",
     "description": "A solid, textured voice with a slow pace and full dramatic expressiveness.", "sort_order": 43},
    {"voice_type": "en_male_diyuwenrounan_uranus_bigtts", "name": "Julian",
     "gender": "male", "language": "en", "style": "有声书",
     "description": "A refined, gentle man who is sincere and friendly, with a relaxed, easygoing way of speaking", "sort_order": 44},
    {"voice_type": "en_male_evil", "name": "Harrison",
     "gender": "male", "language": "en", "style": "Dubbing",
     "description": "An industry heavyweight—rigorous and professional, with a steady, commanding presence", "sort_order": 45},
    {"voice_type": "en_male_excited", "name": "Jasper",
     "gender": "male", "language": "en", "style": "Entertainment",
     "description": "A passionate young male voice—high-spirited and impassioned, with exaggerated, sweeping intonation", "sort_order": 46},
    {"voice_type": "en_male_father", "name": "Alfred",
     "gender": "male", "language": "en", "style": "通用",
     "description": "An elder with a deep, resonant voice and clear, unhurried articulation", "sort_order": 47},
    {"voice_type": "en_male_fernando", "name": "Felix",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A cheerful male voice—lively in conversation and highly contagious in emotion", "sort_order": 48},
    {"voice_type": "en_male_godfather_uranus_bigtts", "name": "Godfather",
     "gender": "male", "language": "en", "style": "有声书",
     "description": "A mature man with sincere emotion who tells his story in a gentle, unhurried way", "sort_order": 49},
    {"voice_type": "en_male_gollum_uranus_bigtts", "name": "Gollum",
     "gender": "male", "language": "en", "style": "RolePlay",
     "description": "A wacky, over-the-top male voice, skilled at creating playful characters", "sort_order": 50},
    {"voice_type": "en_male_hades_uranus_bigtts", "name": "Beau",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A free-spirited mature man with a relaxed, easygoing way of speaking", "sort_order": 51},
    {"voice_type": "en_male_jamie_uranus_bigtts", "name": "Jamie",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A hearty male voice—sincere and candid, witty and full of energy", "sort_order": 52},
    {"voice_type": "en_male_jidongchuanjiaoshi_uranus_bigtts", "name": "Blaze",
     "gender": "male", "language": "en", "style": "Entertainment",
     "description": "An immersive, passionate performance with high-spirited, fervent intonation", "sort_order": 53},
    {"voice_type": "en_male_jimmy_uranus_bigtts", "name": "Jimmy",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A natural, clear American young male voice with smooth, fluent delivery and an easygoing tone", "sort_order": 54},
    {"voice_type": "en_male_joker_uranus_bigtts", "name": "Joker",
     "gender": "male", "language": "en", "style": "Entertainment",
     "description": "An American middle-aged male voice with a slow pace and a warm, magnetic tone", "sort_order": 55},
    {"voice_type": "en_male_josh_coery_uranus_bigtts", "name": "Josiah",
     "gender": "male", "language": "en", "style": "Education",
     "description": "A businesslike young man with a deep, magnetic voice and a dignified, steady tone", "sort_order": 56},
    {"voice_type": "en_male_josh_uranus_bigtts", "name": "Josh",
     "gender": "male", "language": "en", "style": "Dubbing",
     "description": "A clear, bright young man—cheerful, energetic, and easygoing", "sort_order": 57},
    {"voice_type": "en_male_kevin_uranus_bigtts", "name": "Kevin",
     "gender": "male", "language": "en", "style": "Education",
     "description": "A young, clear, and friendly American male voice with fluent, articulate delivery", "sort_order": 58},
    {"voice_type": "en_male_knightley_uranus_bigtts", "name": "Knightley",
     "gender": "male", "language": "en", "style": "有声书",
     "description": "A deep, magnetic American middle-aged male voice with a steady, dignified manner", "sort_order": 59},
    {"voice_type": "en_male_marcus_uranus_bigtts", "name": "Marcus",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A mature American male voice—mellow and deep, skilled at gentle, unhurried storytelling", "sort_order": 60},
    {"voice_type": "en_male_michael", "name": "Chip",
     "gender": "male", "language": "en", "style": "Entertainment",
     "description": "A cartoonish male voice with a lively, high-pitched tone and an exaggerated, comical style", "sort_order": 61},
    {"voice_type": "en_male_michael_kevin_uranus_bigtts", "name": "Michael_Kevin",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A steady, mellow mid-range male voice with a calm, professional narration style", "sort_order": 62},
    {"voice_type": "en_male_michael_uranus_bigtts", "name": "Hank",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A laid-back man with a deep, magnetic voice and a relaxed, easygoing manner", "sort_order": 63},
    {"voice_type": "en_male_motivational", "name": "Rory",
     "gender": "male", "language": "en", "style": "Entertainment",
     "description": "An energetic college-aged man—full of emotion and super dynamic", "sort_order": 64},
    {"voice_type": "en_male_ronald_uranus_bigtts", "name": "Ronald",
     "gender": "male", "language": "en", "style": "有声书",
     "description": "A British gentleman with a deep, resonant, dignified voice", "sort_order": 65},
    {"voice_type": "en_male_russell_uranus_bigtts", "name": "Russell",
     "gender": "male", "language": "en", "style": "通用",
     "description": "An easygoing American male voice—sincere and friendly, with a natural, approachable tone", "sort_order": 66},
    {"voice_type": "en_male_simba_p1_uranus_bigtts", "name": "Simba",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A mature American male voice—deep and reserved, with a steady, composed tone", "sort_order": 67},
    {"voice_type": "en_male_tim_uranus_bigtts", "name": "Tim",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A clear, versatile, and friendly mid-range male voice", "sort_order": 68},
    {"voice_type": "en_male_tom_hiddleston_p1_uranus_bigtts", "name": "Tom",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A deep, reserved uncle whose reciting style is full of narrative feeling.", "sort_order": 69},
    {"voice_type": "en_male_valentino_corey_uranus_bigtts", "name": "Clark",
     "gender": "male", "language": "en", "style": "Dubbing",
     "description": "A mature, dignified uncle with American pronunciation and a steady, powerful professional narration style", "sort_order": 70},
    {"voice_type": "en_male_valentino_uranus_bigtts", "name": "Valentino",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A calm, gentle, and approachable young male voice with a mellow tone", "sort_order": 71},
    {"voice_type": "en_male_yangguangjieshuonan_uranus_bigtts", "name": "Dylan",
     "gender": "male", "language": "en", "style": "通用",
     "description": "A witty, humorous uncle with American pronunciation and a vivid, expressive narrative style.", "sort_order": 72},
    {"voice_type": "es_female_bv084_uranus_bigtts", "name": "Gracie",
     "gender": "female", "language": "es", "style": "通用",
     "description": "A rational, capable woman—calm and composed, with clear, well-organized narration.", "sort_order": 73},
    {"voice_type": "es_female_ht_mx_f6_uranus_bigtts", "name": "Marisol",
     "gender": "female", "language": "es", "style": "通用",
     "description": "A lively, enthusiastic girl-next-door with Latin American Spanish pronunciation, full of energy.", "sort_order": 74},
    {"voice_type": "es_male_dani_uranus_bigtts", "name": "Dani",
     "gender": "male", "language": "es", "style": "有声书",
     "description": "An enthusiastic, talkative uncle with European Spanish pronunciation and a fluent, charming narrative style", "sort_order": 75},
    {"voice_type": "es_male_guillem_uranus_bigtts", "name": "Guillem",
     "gender": "male", "language": "es", "style": "有声书",
     "description": "An easygoing, clam young man—relaxed and natural, and highly approachable.", "sort_order": 76},
    {"voice_type": "fr_female_fr_bv078_uranus_bigtts", "name": "Simone",
     "gender": "female", "language": "fr", "style": "Dubbing",
     "description": "A steady, professional auntie with standard French pronunciation—objective and even-tempered.", "sort_order": 77},
    {"voice_type": "fr_female_fr_f47_uranus_bigtts", "name": "Camille",
     "gender": "female", "language": "fr", "style": "CustomerService",
     "description": "A professional, capable older sister with fluent French pronunciation and a calm, objective narration style", "sort_order": 78},
    {"voice_type": "fr_male_fr_m29_uranus_bigtts", "name": "Maurice",
     "gender": "male", "language": "fr", "style": "Dubbing",
     "description": "A mature, steady uncle with a resonant French voice and a professional, dignified narration style", "sort_order": 79},
    {"voice_type": "fr_male_usseau_uranus_bigtts", "name": "Usseau",
     "gender": "male", "language": "fr", "style": "通用",
     "description": "A sophisticated, crisp, and articulate male voice", "sort_order": 80},
    {"voice_type": "id_female_bv161_uranus_bigtts", "name": "Clara",
     "gender": "female", "language": "id", "style": "通用",
     "description": "A mature female voice with a firm, assertive tone and a strong narrative reading feel", "sort_order": 81},
    {"voice_type": "id_female_bv161dialogue_uranus_bigtts", "name": "Sylvia",
     "gender": "female", "language": "id", "style": "通用",
     "description": "A young woman with shifting emotions—at ease in everyday talk or heated argument, bringing full film-and-TV di", "sort_order": 82},
    {"voice_type": "id_female_bv161narration_uranus_bigtts", "name": "Celeste",
     "gender": "female", "language": "id", "style": "通用",
     "description": "A crisp, assertive female lead with an emotionally rich narrative and explanatory delivery", "sort_order": 83},
    {"voice_type": "id_female_bv164_uranus_bigtts", "name": "Crew",
     "gender": "female", "language": "id", "style": "通用",
     "description": "A natural, vivid young female voice with a warm, engaging storytelling atmosphere", "sort_order": 84},
    {"voice_type": "id_female_f20_uranus_bigtts", "name": "Chloe",
     "gender": "female", "language": "id", "style": "Dubbing",
     "description": "An energetic, lively young woman with a bright, spirited, and expressive delivery", "sort_order": 85},
    {"voice_type": "id_female_phulia_uranus_bigtts", "name": "Phulia",
     "gender": "female", "language": "id", "style": "通用",
     "description": "A lively, cheerful young woman—full of emotion and a performance style brimming with tension.", "sort_order": 86},
    {"voice_type": "id_male_bv160_uranus_bigtts", "name": "Rocco",
     "gender": "male", "language": "id", "style": "通用",
     "description": "An impassioned young man—angry and defiant, with intensely dramatic delivery.", "sort_order": 87},
    {"voice_type": "id_male_bv160dialogue_uranus_bigtts", "name": "Jude",
     "gender": "male", "language": "id", "style": "通用",
     "description": "A young man with natural expressiveness—calm and vivid style.", "sort_order": 88},
    {"voice_type": "id_male_bv160narration_uranus_bigtts", "name": "Hugo",
     "gender": "male", "language": "id", "style": "有声书",
     "description": "An expressive young man with a lively narrative storytelling style", "sort_order": 89},
    {"voice_type": "id_male_bv164dialogue_uranus_bigtts", "name": "Elian",
     "gender": "male", "language": "id", "style": "Dubbing",
     "description": "A gentle, refined young man with a soft, natural voice and an understated delivery", "sort_order": 90},
    {"voice_type": "id_male_bv164narration_uranus_bigtts", "name": "Ronan",
     "gender": "male", "language": "id", "style": "有声书",
     "description": "A professional, steady young male voice—calm and objective, with clear narration", "sort_order": 91},
    {"voice_type": "id_male_han_uranus_bigtts", "name": "Han",
     "gender": "male", "language": "id", "style": "通用",
     "description": "A modern, smooth, and friendly young adult male voice", "sort_order": 92},
    {"voice_type": "id_male_m08_uranus_bigtts", "name": "Kyle",
     "gender": "male", "language": "id", "style": "通用",
     "description": "A rational, steady young man with a calm tone and a professional narration style.", "sort_order": 93},
    {"voice_type": "it_male_enzo_uranus_bigtts", "name": "Enzo",
     "gender": "male", "language": "it", "style": "通用",
     "description": "An authentic, charismatic, and warm Italian male voice", "sort_order": 94},
    {"voice_type": "ja_female_bv024_uranus_bigtts", "name": "Bonnie",
     "gender": "female", "language": "ja", "style": "通用",
     "description": "A gentle, soft female college student—friendly and warm, with an easygoing, unreserved tone.", "sort_order": 95},
    {"voice_type": "ja_female_bv520_uranus_bigtts", "name": "Poppy",
     "gender": "female", "language": "ja", "style": "Dubbing",
     "description": "An energetic young female voice with an anime-and-advertising dubbing style—bright and expressive, with lively", "sort_order": 96},
    {"voice_type": "ja_female_bv521_uranus_bigtts", "name": "Aoi",
     "gender": "female", "language": "ja", "style": "Entertainment",
     "description": "A sweet, lively young woman with a Japanese-style girl voice and strong performance appeal.", "sort_order": 97},
    {"voice_type": "ja_female_bv522_uranus_bigtts", "name": "Hana",
     "gender": "female", "language": "ja", "style": "通用",
     "description": "A professional, dignified young woman with a standard Japanese broadcasting tone—calm and objective.", "sort_order": 98},
    {"voice_type": "ja_female_bv523_uranus_bigtts", "name": "Lily",
     "gender": "female", "language": "ja", "style": "Entertainment",
     "description": "An innocent, carefree little girl with a lively tone, full of childlike charm.", "sort_order": 99},
    {"voice_type": "ja_female_minimi_uranus_bigtts", "name": "Minimi",
     "gender": "female", "language": "ja", "style": "通用",
     "description": "A vibrant, hearty young woman with an outgoing personality and outwardly full emotion.", "sort_order": 100},
    {"voice_type": "ja_female_shirou_uranus_bigtts", "name": "Shirou",
     "gender": "female", "language": "ja", "style": "Dubbing",
     "description": "A bright, brisk young female voice with an anime-and-game dubbing style—lively and spirited in delivery", "sort_order": 101},
    {"voice_type": "ja_male_bv524_uranus_bigtts", "name": "Ken",
     "gender": "male", "language": "ja", "style": "通用",
     "description": "A capable, professional young man with a Japanese broadcast-narration style and a calm, restrained tone.", "sort_order": 102},
    {"voice_type": "ko_female_bv546_uranus_bigtts", "name": "Momo",
     "gender": "female", "language": "ko", "style": "Dubbing",
     "description": "A candid, lively young woman with an anime-and-drama dubbing style and abundant emotion.", "sort_order": 103},
    {"voice_type": "ko_male_bv545_uranus_bigtts", "name": "Jay",
     "gender": "male", "language": "ko", "style": "通用",
     "description": "A hearty young man with a Korean-style, true-to-life performance—full of emotion and natural expression.", "sort_order": 104},
    {"voice_type": "ko_male_m03_uranus_bigtts", "name": "Minho",
     "gender": "male", "language": "ko", "style": "通用",
     "description": "A standard Korean male narrator—highly professional, with a magnetic voice and a steady tone.", "sort_order": 105},
    {"voice_type": "ko_male_shane_uranus_bigtts", "name": "지훈",
     "gender": "male", "language": "ko", "style": "有声书",
     "description": "A steady, refined middle-aged uncle with a highly persuasive tone.", "sort_order": 106},
    {"voice_type": "ms_male_ham_uranus_bigtts", "name": "Ham",
     "gender": "male", "language": "ms", "style": "通用",
     "description": "A steady, easygoing uncle with a Malay everyday-conversation style, an even tone, and a talent for analysis an", "sort_order": 107},
    {"voice_type": "ms_male_naim_uranus_bigtts", "name": "Naim",
     "gender": "male", "language": "ms", "style": "通用",
     "description": "A gentle, refined middle-aged uncle—calm and reserved, rigorous and dependable.", "sort_order": 108},
    {"voice_type": "mx_female_bv065_uranus_bigtts", "name": "Irene",
     "gender": "female", "language": "es", "style": "Education",
     "description": "A calm, objective, capable young woman who is efficient and well-organized.", "sort_order": 109},
    {"voice_type": "mx_female_bv166dialogue_uranus_bigtts", "name": "Lucy",
     "gender": "female", "language": "es", "style": "通用",
     "description": "A playful, cheerful, lovely young woman with vivid, lively emotional expression.", "sort_order": 110},
    {"voice_type": "mx_female_bv166emotion_uranus_bigtts", "name": "Rosa",
     "gender": "female", "language": "es", "style": "通用",
     "description": "A young woman with intense emotion and full dramatic tension—rich in expressiveness.", "sort_order": 111},
    {"voice_type": "mx_female_bv166narrator_uranus_bigtts", "name": "Freya",
     "gender": "female", "language": "es", "style": "有声书",
     "description": "A young female voice with clear pronunciation and a steady, plain, even narration style", "sort_order": 112},
    {"voice_type": "mx_female_leslie_uranus_bigtts", "name": "Leslie",
     "gender": "female", "language": "es", "style": "通用",
     "description": "An approachable, gentle young woman with a soft, natural pace.", "sort_order": 113},
    {"voice_type": "mx_male_bv165dialogue_uranus_bigtts", "name": "Diego",
     "gender": "male", "language": "es", "style": "有声书",
     "description": "A young male voice with clear pronunciation and a plain, even, composed dialogue delivery", "sort_order": 114},
    {"voice_type": "mx_male_bv165narrator_uranus_bigtts", "name": "Marcos",
     "gender": "male", "language": "es", "style": "有声书",
     "description": "A mature male voice with a calm, plain, and composed tone", "sort_order": 115},
    {"voice_type": "mx_male_felipe_uranus_bigtts", "name": "Felipe",
     "gender": "male", "language": "es", "style": "通用",
     "description": "An enthusiastic, sharp-witted cheerful young man, skilled at building a suspenseful atmosphere.", "sort_order": 116},
    {"voice_type": "mx_male_ht_mx_m012_uranus_bigtts", "name": "Derek",
     "gender": "male", "language": "es", "style": "Education",
     "description": "An objective, restrained young man with a distinctly professional narration style—composed and unflappable.", "sort_order": 117},
    {"voice_type": "mx_male_marcelo_uranus_bigtts", "name": "Marcelo",
     "gender": "male", "language": "es", "style": "通用",
     "description": "A gentle, refined young man—steady and dignified.", "sort_order": 118},
    {"voice_type": "pt_female_bv173_uranus_bigtts", "name": "Diana",
     "gender": "female", "language": "pt", "style": "通用",
     "description": "A professional, composed female narrator—clear-minded, sharp, and capable.", "sort_order": 119},
    {"voice_type": "pt_female_bv173dialogue_uranus_bigtts", "name": "Elena",
     "gender": "female", "language": "pt", "style": "Dubbing",
     "description": "An elegant, mature idol-drama female lead—delicate in thought, with a lively, captivating air.", "sort_order": 120},
    {"voice_type": "pt_female_bv173emotion_uranus_bigtts", "name": "Lola",
     "gender": "female", "language": "pt", "style": "通用",
     "description": "A performance sprite who loves the dramatic stage—enthusiastic, full of emotion, and brimming with expressive ", "sort_order": 121},
    {"voice_type": "pt_female_bv173narrator_uranus_bigtts", "name": "Emma",
     "gender": "female", "language": "pt", "style": "Dubbing",
     "description": "A calm, relaxed professional female with a steady, everyday tone and even, unhurried delivery", "sort_order": 122},
    {"voice_type": "pt_female_bv530_uranus_bigtts", "name": "Sofia",
     "gender": "female", "language": "pt", "style": "通用",
     "description": "A gentle, soft, approachable young woman—lively and natural, skilled in Brazilian Portuguese.", "sort_order": 123},
    {"voice_type": "pt_female_mari_uranus_bigtts", "name": "Mari",
     "gender": "female", "language": "pt", "style": "Education",
     "description": "A cheerful young woman with a hearty, commanding voice and a talkative, gracious manner.", "sort_order": 124},
    {"voice_type": "pt_male_bv172_uranus_bigtts", "name": "Sam",
     "gender": "male", "language": "pt", "style": "通用",
     "description": "A two-person dialogue featuring a regular young male voice and a deep, husky middle-aged male voice, with a st", "sort_order": 125},
    {"voice_type": "pt_male_bv172dialogue_uranus_bigtts", "name": "Walter",
     "gender": "male", "language": "pt", "style": "Dubbing",
     "description": "A resonant, husky middle-aged uncle with a serious tone and a strong film-and-TV dialogue feel.", "sort_order": 126},
    {"voice_type": "pt_male_bv172emotion_uranus_bigtts", "name": "Vincent",
     "gender": "male", "language": "pt", "style": "Education",
     "description": "A middle-aged male voice with intense emotion, exaggerated intonation, and standout dramatic expressiveness.", "sort_order": 127},
    {"voice_type": "pt_male_bv172narrator_uranus_bigtts", "name": "Miles",
     "gender": "male", "language": "pt", "style": "有声书",
     "description": "A rational, calm male narrator—rigorous and professional.", "sort_order": 128},
    {"voice_type": "pt_male_bv531_uranus_bigtts", "name": "Arthur",
     "gender": "male", "language": "pt", "style": "通用",
     "description": "A rational, objective middle-aged male voice—steady and dependable.", "sort_order": 129},
    {"voice_type": "pt_male_martins_uranus_bigtts", "name": "Martins",
     "gender": "male", "language": "pt", "style": "通用",
     "description": "A charismatic, warm, and expressive male voice", "sort_order": 130},
    {"voice_type": "pt_male_rael_uranus_bigtts", "name": "Rael",
     "gender": "male", "language": "pt", "style": "Education",
     "description": "A fresh, crisp young man—energetic and sunny, skilled in Brazilian Portuguese.", "sort_order": 131},
    {"voice_type": "ru_female_af07_uranus_bigtts", "name": "Amelia",
     "gender": "female", "language": "ru", "style": "有声书",
     "description": "A gentle, approachable young woman—understanding and graceful.", "sort_order": 132},
    {"voice_type": "ru_female_irinae_uranus_bigtts", "name": "Irinae",
     "gender": "female", "language": "ru", "style": "有声书",
     "description": "An enthusiastic Russian young woman with outwardly expressive, rich emotion.", "sort_order": 133},
    {"voice_type": "ru_female_sophie_uranus_bigtts", "name": "Ksenia",
     "gender": "female", "language": "ru", "style": "通用",
     "description": "A young female voice with a Russian accent—full of energy and warmth, with a strong sense of connection.", "sort_order": 134},
    {"voice_type": "ru_male_pavel_uranus_bigtts", "name": "Pavel",
     "gender": "male", "language": "ru", "style": "通用",
     "description": "A middle-aged male voice with a naturally true-to-life narrative tone—comfortable and natural to listen to.", "sort_order": 135},
    {"voice_type": "ru_male_vlad_uranus_bigtts", "name": "Silas",
     "gender": "male", "language": "ru", "style": "Entertainment",
     "description": "A whisper-style ASMR young male voice—soft, breathy, and intimate, gentle and soothing", "sort_order": 136},
    {"voice_type": "th_female_bv568_angry_uranus_bigtts", "name": "Valeria",
     "gender": "female", "language": "th", "style": "Education",
     "description": "A domineering female lead with shifting emotions—highly expressive and outwardly emotional.", "sort_order": 137},
    {"voice_type": "th_female_bv568_fear_uranus_bigtts", "name": "Iris",
     "gender": "female", "language": "th", "style": "有声书",
     "description": "An anxious, fearful innocent young woman—emotionally fragile and sensitive.", "sort_order": 138},
    {"voice_type": "th_female_bv568_happy_uranus_bigtts", "name": "Zara",
     "gender": "female", "language": "th", "style": "通用",
     "description": "A young woman with full emotion and the quality of both dramatic and animation dubbing—rich in expressiveness.", "sort_order": 139},
    {"voice_type": "th_female_bv568_hate_uranus_bigtts", "name": "Valentina",
     "gender": "female", "language": "th", "style": "通用",
     "description": "A female lead with strong dramatic tension—full, expressive emotion with a distinct film-and-TV dialogue quali", "sort_order": 140},
    {"voice_type": "th_female_bv568_neutral_uranus_bigtts", "name": "Mildred",
     "gender": "female", "language": "th", "style": "通用",
     "description": "A calm, even-tempered young woman with balanced emotion—calm and neutral in her approach.", "sort_order": 141},
    {"voice_type": "th_female_bv568_sad_uranus_bigtts", "name": "Lydia",
     "gender": "female", "language": "th", "style": "Dubbing",
     "description": "A gentle, melancholic young woman with a strong sense of narrative.", "sort_order": 142},
    {"voice_type": "th_female_bv568_suprise_uranus_bigtts", "name": "Phoebe",
     "gender": "female", "language": "th", "style": "有声书",
     "description": "A lively, vivid-minded young woman with a proactive personality and a naturally playful, teasing air.", "sort_order": 143},
    {"voice_type": "tl_female_annika_uranus_bigtts", "name": "Annika",
     "gender": "female", "language": "tl", "style": "通用",
     "description": "An approachable young woman with a gentle tone and an authentic everyday-conversation quality.", "sort_order": 144},
    {"voice_type": "tl_female_hervie_uranus_bigtts", "name": "Hervie",
     "gender": "female", "language": "tl", "style": "有声书",
     "description": "An entertainment-news female anchor—professional, confident, and engaging.", "sort_order": 145},
    {"voice_type": "tl_male_ed_uranus_bigtts", "name": "Ed",
     "gender": "male", "language": "tl", "style": "通用",
     "description": "An approachable, easygoing middle-aged male voice with relaxed, down-to-earth delivery.", "sort_order": 146},
    {"voice_type": "vi_female_hong_uranus_bigtts", "name": "Hong",
     "gender": "female", "language": "vi", "style": "通用",
     "description": "An out-of-town young woman with a Vietnamese accent—straightforward, with frank emotional expression.", "sort_order": 147},
    {"voice_type": "vi_female_ling_uranus_bigtts", "name": "Ling",
     "gender": "female", "language": "vi", "style": "通用",
     "description": "A tender, kind young woman—earnest and dependable in her work.", "sort_order": 148},
    {"voice_type": "vi_female_linh_uranus_bigtts", "name": "Linh",
     "gender": "female", "language": "vi", "style": "Dubbing",
     "description": "A straightforward, candid young woman full of energy—crisp and decisive in expression.", "sort_order": 149},
    {"voice_type": "vi_female_partner_uranus_bigtts", "name": "Partner",
     "gender": "female", "language": "vi", "style": "Dubbing",
     "description": "A young woman with intense, full emotion—brimming with youthful vitality.", "sort_order": 150},
    {"voice_type": "vi_female_ruan_uranus_bigtts", "name": "Ruan",
     "gender": "female", "language": "vi", "style": "通用",
     "description": "A steady, well-measured young woman—clear-minded, dignified, and poised.", "sort_order": 151},
    {"voice_type": "vi_female_wu_uranus_bigtts", "name": "Wu",
     "gender": "female", "language": "vi", "style": "通用",
     "description": "A straightforward, outgoing young woman with a steady, rational mindset.", "sort_order": 152},
    {"voice_type": "vi_male_wumg_uranus_bigtts", "name": "Wumg",
     "gender": "male", "language": "vi", "style": "通用",
     "description": "A modest, patient young man—rigorous and meticulous.", "sort_order": 153},
    {"voice_type": "zh_female_cancan_uranus_bigtts", "name": "Corinne",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A young, vivid and energetic female voice", "sort_order": 154},
    {"voice_type": "zh_female_jitangnv_uranus_bigtts", "name": "Nadia",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A mature, soothing, and deeply emotional female voice", "sort_order": 155},
    {"voice_type": "zh_female_kefunvsheng_uranus_bigtts", "name": "Tracy",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A polished, professional, and courteous female voice", "sort_order": 156},
    {"voice_type": "zh_female_linjianvhai_uranus_bigtts", "name": "Pinky",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A warm, friendly, and approachable young female voice", "sort_order": 157},
    {"voice_type": "zh_female_liuchangnv_uranus_bigtts", "name": "Pearl",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A clear, steady, and highly articulate female voice", "sort_order": 158},
    {"voice_type": "zh_female_meilinvyou_uranus_bigtts", "name": "Opal",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A sweet, intimate, and affectionate young female voice", "sort_order": 159},
    {"voice_type": "zh_female_mizai_uranus_bigtts", "name": "Mabel",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A youthful, playful young female voice—light, friendly, and lively in everyday speech", "sort_order": 160},
    {"voice_type": "zh_female_peiqi_uranus_bigtts", "name": "Holly",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A childlike, innocent, and deeply endearing little girl’s voice", "sort_order": 161},
    {"voice_type": "zh_female_sajiaoxuemei_uranus_bigtts", "name": "Sandy",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A very young, sweet, and playful female voice", "sort_order": 162},
    {"voice_type": "zh_female_shuangkuaisisi_uranus_bigtts", "name": "Gigi",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A steady, composed young female voice with a slightly low, mellow tone", "sort_order": 163},
    {"voice_type": "zh_female_tianmeixiaoyuan_uranus_bigtts", "name": "Esther",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A fresh, innocent, and youthful female voice", "sort_order": 164},
    {"voice_type": "zh_female_vv_uranus_bigtts", "name": "Vivi",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A youthful and vibrant female voice", "sort_order": 165},
    {"voice_type": "zh_female_xiaohe_uranus_bigtts", "name": "Mindy",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A gentle, soft-spoken, and slightly mature female voice", "sort_order": 166},
    {"voice_type": "zh_female_xiaoxue_uranus_bigtts", "name": "Lyla",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A pure, steady, and crystal-clear young female voice", "sort_order": 167},
    {"voice_type": "zh_female_yingyujiaoxue_uranus_bigtts", "name": "Jean",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A clear, authoritative yet encouraging female voice", "sort_order": 168},
    {"voice_type": "zh_female_yuanqi_uranus_bigtts", "name": "Daisy",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "An energetic, cheerful, and optimistic young female voice", "sort_order": 169},
    {"voice_type": "zh_male_dayi_uranus_bigtts", "name": "Magnus",
     "gender": "male", "language": "zh", "style": "通用",
     "description": "A mature, resonant, and slightly dramatic male voice", "sort_order": 170},
    {"voice_type": "zh_male_m191_uranus_bigtts", "name": "Kian",
     "gender": "male", "language": "zh", "style": "通用",
     "description": "A steady, clear, and versatile mid-range male voice", "sort_order": 171},
    {"voice_type": "zh_male_ruyayichen_uranus_bigtts", "name": "Quentin",
     "gender": "male", "language": "zh", "style": "通用",
     "description": "A refined, gentle, and elegant young male voice", "sort_order": 172},
    {"voice_type": "zh_male_shaonianzixin_uranus_bigtts", "name": "Jess",
     "gender": "male", "language": "zh", "style": "通用",
     "description": "A bright, confident, and energetic teenage male voice", "sort_order": 173},
    {"voice_type": "zh_male_sophie_uranus_bigtts", "name": "Sophie",
     "gender": "female", "language": "zh", "style": "通用",
     "description": "A smooth, modern, and soft-spoken young female voice", "sort_order": 174},
    {"voice_type": "zh_male_sunwukong_uranus_bigtts", "name": "Monkey King",
     "gender": "male", "language": "zh", "style": "通用",
     "description": "A monkey king voice", "sort_order": 175},
    {"voice_type": "zh_male_taocheng_uranus_bigtts", "name": "Cedric",
     "gender": "male", "language": "zh", "style": "通用",
     "description": "A steady, clear, and articulate young male voice", "sort_order": 176},
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
