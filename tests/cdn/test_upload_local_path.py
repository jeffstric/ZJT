"""
upload_local_path 端到端路径约定测试

回归背景：_save_user_asset 曾用 upload 根做 relpath 基准，注册的 local_path 缺
upload/ 前缀，导致中间件查询永不命中、CDN 上传定位不到本地文件，整条卸载链路
静默失效。本测试用真实文件系统验证三方约定的一致性：
1. upload_local_path 产出带 upload/ 前缀的 POSIX 相对路径；
2. 中间件查询格式（请求路径 lstrip("/")）与之相等；
3. trigger_cdn_upload 的定位方式（项目根拼接）能解析到真实文件。
"""
import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.media_mapping_util import extract_local_path_from_url, upload_local_path
from utils.project_path import get_project_root, get_upload_dir


class TestUploadLocalPath(unittest.TestCase):
    """规范 local_path 三方约定（注册 / 中间件查询 / CDN 上传定位）一致性"""

    def setUp(self):
        self.asset_dir = os.path.join(get_upload_dir(), "workflow", "12")
        os.makedirs(self.asset_dir, exist_ok=True)
        self.file_path = os.path.join(self.asset_dir, "regression_p0_prefix.png")
        with open(self.file_path, "wb") as f:
            f.write(b"png-bytes")

    def tearDown(self):
        shutil.rmtree(os.path.join(get_upload_dir(), "workflow", "12"), ignore_errors=True)

    def test_local_path_has_upload_prefix(self):
        """产出必须带 upload/ 前缀（P0 回归：曾缺失导致链路整体失效）"""
        lp = upload_local_path(self.file_path)
        self.assertEqual(lp, "upload/workflow/12/regression_p0_prefix.png")
        self.assertNotIn("\\", lp)

    def test_middleware_lookup_format_matches(self):
        """中间件以请求路径 lstrip("/") 查库，注册值必须与之相等"""
        lp = upload_local_path(self.file_path)
        request_path = f"/{lp}"  # /upload/workflow/12/xxx.png
        self.assertEqual(request_path.lstrip("/"), lp)

    def test_extract_local_path_round_trip(self):
        """从本服务 /upload/ URL 提取的相对路径与注册值一致（TTS 链路同口径）"""
        lp = upload_local_path(self.file_path)
        url = f"http://some-host.example/{lp}"
        self.assertEqual(extract_local_path_from_url(url), lp)

    def test_cdn_upload_resolves_real_file_from_project_root(self):
        """trigger_cdn_upload 以项目根拼接 local_path 定位文件，必须能找到"""
        lp = upload_local_path(self.file_path)
        resolved = os.path.join(get_project_root(), *lp.split("/"))
        self.assertTrue(os.path.isfile(resolved), f"应解析到真实文件: {resolved}")

    def test_path_outside_upload_dir_falls_back_to_project_relative(self):
        """upload 目录之外的路径退回相对项目根口径（防御行为明确）"""
        outside = os.path.join(get_project_root(), "docs", "x.md")
        lp = upload_local_path(outside)
        self.assertEqual(lp, "docs/x.md")


if __name__ == '__main__':
    unittest.main()
