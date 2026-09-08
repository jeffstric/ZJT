"""大世界导入 job 状态共享文件存储的单测。

背景：job 状态原本是 api/script_writer.py 的进程内存字典，gunicorn 多 worker 下
前端轮询 /api/world-import-status 落到其他 worker 会 404，误报"导入失败"。
现改为落盘到 <项目根>/temp/world_import_jobs/<job_id>.json，任一 worker 均可读。

覆盖：
- 创建 / 读取 / 更新 / 不存在时静默
- 另一个独立 Python 进程写入的 job 文件，本进程能读到（跨 worker 可见性）
- job_id 只接受 uuid，路径穿越不会读到目录外文件
- 并发计数只算 TTL 内的 active job
- TTL 清理删除过期 .json 与残留 .json.tmp
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid

import pytest

from api import script_writer
from config.constant import WORLD_IMPORT_JOB_TTL


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def jobs_dir(tmp_path, monkeypatch):
    target = tmp_path / "world_import_jobs"
    monkeypatch.setattr(script_writer, "_world_import_jobs_dir", lambda: str(target))
    return target


def _new_job(**overrides):
    now = time.time()
    job = {
        'status': 'pending',
        'stage': 'pending',
        'progress': 0,
        'message': '任务已创建',
        'result': None,
        'error': None,
        'started_at': now,
        'updated_at': now,
        'user_id': '2',
        'world_id': '278',
    }
    job.update(overrides)
    return job


# ==================== 创建 / 读取 / 更新 ====================

def test_create_then_get_roundtrip(jobs_dir):
    job_id = str(uuid.uuid4())
    _run(script_writer._create_world_import_job(job_id, _new_job()))

    assert (jobs_dir / f"{job_id}.json").is_file()
    assert not (jobs_dir / f"{job_id}.json.tmp").exists(), "原子写完成后不应残留 tmp"

    got = _run(script_writer._get_world_import_job(job_id))
    assert got is not None
    assert got['status'] == 'pending'
    assert got['world_id'] == '278'


def test_set_updates_fields_and_bumps_updated_at(jobs_dir):
    job_id = str(uuid.uuid4())
    _run(script_writer._create_world_import_job(job_id, _new_job(updated_at=1.0)))

    _run(script_writer._set_world_import_job(
        job_id, status='done', stage='done', progress=100, result={'scripts': 3},
    ))

    got = _run(script_writer._get_world_import_job(job_id))
    assert got['status'] == 'done'
    assert got['progress'] == 100
    assert got['result'] == {'scripts': 3}
    assert got['updated_at'] > 1.0
    # 未更新的字段保留
    assert got['user_id'] == '2'


def test_set_on_missing_job_is_silent(jobs_dir):
    job_id = str(uuid.uuid4())
    _run(script_writer._set_world_import_job(job_id, status='done'))
    assert _run(script_writer._get_world_import_job(job_id)) is None
    assert not jobs_dir.exists() or not any(jobs_dir.iterdir())


def test_get_unknown_job_returns_none(jobs_dir):
    assert _run(script_writer._get_world_import_job(str(uuid.uuid4()))) is None


# ==================== 跨 worker 可见性 ====================

def test_job_written_by_another_process_is_visible(jobs_dir):
    """模拟另一个 gunicorn worker：独立 Python 进程直接落盘，本进程必须能读到。"""
    job_id = str(uuid.uuid4())
    jobs_dir.mkdir(parents=True, exist_ok=True)
    payload = _new_job(status='downloading', stage='downloading', progress=42)
    code = (
        "import json,sys\n"
        "path, payload = sys.argv[1], json.loads(sys.argv[2])\n"
        "open(path, 'w', encoding='utf-8').write(json.dumps(payload, ensure_ascii=False))\n"
    )
    subprocess.run(
        [sys.executable, "-c", code, str(jobs_dir / f"{job_id}.json"), json.dumps(payload)],
        check=True, timeout=30,
    )

    got = _run(script_writer._get_world_import_job(job_id))
    assert got is not None
    assert got['status'] == 'downloading'
    assert got['progress'] == 42


def test_job_id_accepts_uuid_variants_consistently(jobs_dir):
    """uuid 的大写 / 花括号写法应归一化到同一个文件。"""
    canonical = str(uuid.uuid4())
    _run(script_writer._create_world_import_job(canonical, _new_job()))

    assert _run(script_writer._get_world_import_job(canonical.upper())) is not None
    assert _run(script_writer._get_world_import_job("{" + canonical + "}")) is not None


# ==================== 安全：job_id 路径穿越 ====================

@pytest.mark.parametrize("bad_id", [
    "../../etc/passwd",
    "..%2F..%2Fetc%2Fpasswd",
    "not-a-uuid",
    "",
    "abc.json",
    "../" + str(uuid.uuid4()),
])
def test_invalid_job_id_rejected(jobs_dir, bad_id):
    assert script_writer._world_import_job_path(bad_id) is None
    assert _run(script_writer._get_world_import_job(bad_id)) is None


def test_invalid_job_id_never_reads_outside_dir(jobs_dir, tmp_path):
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps({'status': 'done'}), encoding='utf-8')
    assert _run(script_writer._get_world_import_job("../secret")) is None
    assert _run(script_writer._get_world_import_job("../secret.json")) is None


# ==================== 并发计数 ====================

def test_count_active_only_counts_fresh_active_jobs(jobs_dir):
    _run(script_writer._create_world_import_job(str(uuid.uuid4()), _new_job(status='pending')))
    _run(script_writer._create_world_import_job(str(uuid.uuid4()), _new_job(status='downloading')))
    _run(script_writer._create_world_import_job(str(uuid.uuid4()), _new_job(status='unpacking')))
    _run(script_writer._create_world_import_job(str(uuid.uuid4()), _new_job(status='done')))
    _run(script_writer._create_world_import_job(str(uuid.uuid4()), _new_job(status='failed')))
    # 宿主进程已死的僵尸：状态 active 但超过 TTL 未更新
    stale = time.time() - WORLD_IMPORT_JOB_TTL - 10
    _run(script_writer._create_world_import_job(
        str(uuid.uuid4()), _new_job(status='downloading', updated_at=stale),
    ))

    assert _run(script_writer._count_active_world_import_jobs()) == 3


def test_count_active_on_missing_dir_is_zero(jobs_dir):
    assert not jobs_dir.exists()
    assert _run(script_writer._count_active_world_import_jobs()) == 0


# ==================== TTL 清理 ====================

def test_cleanup_removes_expired_json_and_tmp_but_keeps_fresh(jobs_dir):
    fresh_id = str(uuid.uuid4())
    _run(script_writer._create_world_import_job(fresh_id, _new_job(status='done')))

    expired_id = str(uuid.uuid4())
    _run(script_writer._create_world_import_job(expired_id, _new_job(status='done')))
    expired_path = jobs_dir / f"{expired_id}.json"
    old = time.time() - WORLD_IMPORT_JOB_TTL - 60
    os.utime(expired_path, (old, old))

    # 写入中途进程崩溃残留的 tmp
    stale_tmp = jobs_dir / f"{uuid.uuid4()}.json.tmp"
    stale_tmp.write_text("{", encoding='utf-8')
    os.utime(stale_tmp, (old, old))

    # 目录里的无关文件不应被碰
    unrelated = jobs_dir / "README.txt"
    unrelated.write_text("keep", encoding='utf-8')
    os.utime(unrelated, (old, old))

    removed = script_writer._cleanup_expired_world_import_jobs_sync()

    assert removed == 2
    assert (jobs_dir / f"{fresh_id}.json").exists()
    assert not expired_path.exists()
    assert not stale_tmp.exists()
    assert unrelated.exists()


def test_cleanup_on_missing_dir_is_noop(jobs_dir):
    assert script_writer._cleanup_expired_world_import_jobs_sync() == 0


# ==================== 读取容错 ====================

def test_read_tolerates_truncated_json_then_returns_none(jobs_dir, monkeypatch):
    """读到半截 JSON（理论上不会发生，因原子替换）也不抛异常，重试后返回 None。"""
    monkeypatch.setattr(script_writer, "WORLD_IMPORT_JOB_READ_RETRY_INTERVAL", 0)
    job_id = str(uuid.uuid4())
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / f"{job_id}.json").write_text('{"status": "down', encoding='utf-8')

    assert _run(script_writer._get_world_import_job(job_id)) is None
