"""音色库预置音色指纹回填：音频理解模型实听样本生成 voice.voice_desc。

背景：同 style 分类下的预置音色听感各异，模板表统一文案会让文字指纹失去
区分度（用户反馈）。本脚本用音频理解模型（mimo-v2.6-pro，OpenAI 兼容
input_audio 格式实测可用）逐个实听预置样本，生成 30~60 字纯声学指纹写回
voice.voice_desc。

用法（在项目根目录）：
    comfyui_env=prod PYTHONUTF8=1 python scripts/backfill_voice_desc.py [--limit N]

- 只处理 provider='reference_audio' 且 voice_desc 为空的音色（可重复执行，
  已回填的自动跳过）；新增预置音色后再跑一次即可增量覆盖。
- 失败重试一次，仍失败则跳过并打印，不影响其余音色。
- 生成提示词与 script_writer 音色分析口径一致：纯声学六维、与 style 分类
  互为校验、排除角色身份/情感/录音质量。
"""
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AUDIO_MODEL = 'mimo-v2.6-pro'
PROMPT_TEMPLATE = (
    "请仔细听这段人声音频，输出该声音的声学音色指纹，30~60字一句话，"
    "只写：性别与年龄段、音高（低沉/清亮）、音色质感（沙哑/圆润/清脆等）、"
    "音量、语速、语气习惯。不要写角色身份、名字、情感状态和录音质量。"
    "参考分类（用于校对你的性别年龄段判断，以实际听感为准）：{style}。"
)


def main(limit: int = 0) -> None:
    from llm.llm_client_factory import get_llm_client
    from model.database import execute_query, execute_update
    from model.voice import PROVIDER_REFERENCE_AUDIO

    rows = execute_query(
        "SELECT id, name, style, audio_url FROM `voice` "
        "WHERE provider=%s AND is_active=1 AND (voice_desc IS NULL OR voice_desc='') "
        "ORDER BY id",
        (PROVIDER_REFERENCE_AUDIO,),
        fetch_all=True,
    ) or []
    if limit > 0:
        rows = rows[:limit]
    print(f"待回填音色数: {len(rows)}")
    client = get_llm_client(AUDIO_MODEL)

    ok = fail = 0
    for row in rows:
        audio_rel = str(row['audio_url'] or '').lstrip('/')
        local_path = os.path.join('web', audio_rel)
        if not os.path.isfile(local_path):
            print(f"[SKIP] id={row['id']} {row['name']}: 音频文件缺失 {audio_rel}")
            fail += 1
            continue

        b64 = base64.b64encode(open(local_path, 'rb').read()).decode()
        messages = [
            {"role": "system", "content": "你是专业的声音设计师，擅长通过听音频判断人声的声学特征。"},
            {"role": "user", "content": [
                {"type": "text", "text": PROMPT_TEMPLATE.format(style=row['style'] or '未知')},
                {"type": "input_audio", "input_audio": {"data": b64, "format": "mp3"}},
            ]},
        ]

        desc = ''
        for attempt in (1, 2):
            try:
                resp = client.call_api(
                    model=AUDIO_MODEL, messages=messages,
                    temperature=0.2, max_tokens=300, request_timeout=90,
                )
                desc = (resp.choices[0].message.content or '').strip() if resp and resp.choices else ''
                if desc:
                    break
            except Exception as exc:
                print(f"[WARN] id={row['id']} {row['name']} 第{attempt}次失败: {str(exc)[:100]}")
                time.sleep(3)

        if not desc:
            print(f"[FAIL] id={row['id']} {row['name']}: 两次尝试均无输出")
            fail += 1
            time.sleep(1)
            continue

        desc = desc[:1000]
        execute_update(
            "UPDATE `voice` SET voice_desc=%s WHERE id=%s",
            (desc, row['id']),
        )
        ok += 1
        print(f"[OK] id={row['id']} {row['name']}: {desc[:40]}")
        time.sleep(1.5)

    print(f"完成: 成功 {ok}，失败 {fail}")


if __name__ == '__main__':
    limit = 0
    if len(sys.argv) > 2 and sys.argv[1] == '--limit':
        limit = int(sys.argv[2])
    main(limit)
