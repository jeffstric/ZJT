"""
升级检查脚本单元测试

测试 scripts/upgrade_check.py 中的纯函数逻辑。
使用 mock 隔离 git 命令、文件系统、YAML 解析等外部依赖。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from scripts.upgrade_check import (
    parse_version,
    compare_version,
    get_local_version,
    get_remote_latest_tag,
    perform_update,
    update_remote_url_if_needed,
    check_binaries_for_version,
    run_git,
    normalize_repo_url,
    is_auth_or_prompt_error,
    fetch_remote_with_fallback,
    check_user_module_update_safety,
    check_user_module_compatibility,
    _parse_pyproject_version,
    _version_satisfies,
)


class TestParseVersion(unittest.TestCase):
    """测试 parse_version"""

    def test_standard_version(self):
        self.assertEqual(parse_version("1.5.1"), [1, 5, 1])

    def test_version_with_v_prefix(self):
        self.assertEqual(parse_version("v1.5.1"), [1, 5, 1])

    def test_version_with_V_prefix(self):
        self.assertEqual(parse_version("V2.0.0"), [2, 0, 0])

    def test_version_with_suffix(self):
        self.assertEqual(parse_version("1.5.1-beta"), [1, 5, 1])

    def test_version_with_rc_suffix(self):
        self.assertEqual(parse_version("v1.5.1-rc1"), [1, 5, 1])

    def test_two_part_version(self):
        self.assertEqual(parse_version("1.5"), [1, 5])

    def test_single_part_version(self):
        self.assertEqual(parse_version("5"), [5])

    def test_non_numeric_parts(self):
        self.assertEqual(parse_version("1.x.3"), [1, 0, 3])

    def test_complex_version(self):
        self.assertEqual(parse_version("v3.10.25-alpha"), [3, 10, 25])


class TestCompareVersion(unittest.TestCase):
    """测试 compare_version"""

    def test_equal_versions(self):
        self.assertEqual(compare_version("1.5.1", "1.5.1"), 0)

    def test_v1_greater_patch(self):
        self.assertEqual(compare_version("1.5.2", "1.5.1"), 1)

    def test_v1_less_patch(self):
        self.assertEqual(compare_version("1.5.1", "1.5.2"), -1)

    def test_v1_greater_major(self):
        self.assertEqual(compare_version("2.0.0", "1.9.9"), 1)

    def test_v1_less_major(self):
        self.assertEqual(compare_version("1.9.9", "2.0.0"), -1)

    def test_v_prefix_ignored(self):
        self.assertEqual(compare_version("v1.5.1", "1.5.1"), 0)

    def test_different_lengths_equal_prefix(self):
        self.assertEqual(compare_version("1.5", "1.5.0"), 0)
        self.assertEqual(compare_version("1.5.1", "1.5"), 1)
        self.assertEqual(compare_version("1.5", "1.5.1"), -1)

    def test_zero_versions(self):
        self.assertEqual(compare_version("0.0.0", "0.0.0"), 0)

    def test_with_suffix(self):
        self.assertEqual(compare_version("1.5.1-beta", "1.5.1"), 0)


class TestGetLocalVersion(unittest.TestCase):
    """测试 get_local_version"""

    @patch('scripts.upgrade_check.run_git')
    def test_git_tag_points_at_head(self, mock_git):
        """Git tag 不再定义本地应用版本。"""
        with patch('scripts.upgrade_check.read_pyproject_version', return_value=None):
            result = get_local_version(Path("/fake"), git_cmd="git")
        self.assertEqual(result, "unknown")
        mock_git.assert_not_called()

    @patch('scripts.upgrade_check.run_git')
    def test_git_describe_fallback(self, mock_git):
        """即使存在 describe tag，也只返回 pyproject 版本。"""
        with patch('scripts.upgrade_check.read_pyproject_version', return_value="1.4.1"):
            result = get_local_version(Path("/fake"), git_cmd="git")
        self.assertEqual(result, "1.4.1")
        mock_git.assert_not_called()

    @patch('scripts.upgrade_check.run_git')
    def test_pyproject_wins_when_newer_than_describe(self, mock_git):
        """pyproject 始终定义本地版本。"""
        with patch('scripts.upgrade_check.read_pyproject_version', return_value="2.0.3"):
            result = get_local_version(Path("/fake"), git_cmd="git")
        self.assertEqual(result, "2.0.3")
        mock_git.assert_not_called()

    @patch('scripts.upgrade_check.run_git')
    def test_multiple_tags_picks_highest(self, mock_git):
        """异常高版本 tag 不能覆盖 pyproject。"""
        with patch('scripts.upgrade_check.read_pyproject_version', return_value="1.5.0"):
            result = get_local_version(Path("/fake"), git_cmd="git")
        self.assertEqual(result, "1.5.0")
        mock_git.assert_not_called()

    @patch('scripts.upgrade_check.run_git')
    def test_fallback_to_pyproject_toml(self, mock_git):
        """git 不可用时回退到 pyproject.toml"""
        with patch('scripts.upgrade_check.read_pyproject_version', return_value="1.3.0"):
            result = get_local_version(Path("/fake"), git_cmd="git")

        self.assertEqual(result, "1.3.0")
        mock_git.assert_not_called()

    def test_no_git_no_pyproject(self):
        """无 git 且无 pyproject.toml"""
        pyproject = MagicMock()
        pyproject.exists.return_value = False

        with patch.object(Path, '__truediv__', return_value=pyproject):
            result = get_local_version(Path("/fake"), git_cmd=None)

        self.assertEqual(result, "unknown")


class TestParsePyprojectVersion(unittest.TestCase):
    def test_reads_only_project_table(self):
        content = '[tool.demo]\nversion = "99.0.0"\n[project]\nversion = "2.1.5"\n'
        self.assertEqual(_parse_pyproject_version(content), "2.1.5")

    def test_rejects_missing_or_invalid_project_version(self):
        self.assertIsNone(_parse_pyproject_version('[tool.demo]\nversion = "99.0.0"\n'))
        self.assertIsNone(_parse_pyproject_version('[project\nversion = "2.1.5"'))


class TestGetRemoteLatestTag(unittest.TestCase):
    """测试 get_remote_latest_tag"""

    @patch('scripts.upgrade_check.run_git')
    def test_returns_highest_tag(self, mock_git):
        output = (
            "abc123 refs/tags/v1.4.0\n"
            "def456 refs/tags/v1.5.0\n"
            "ghi789 refs/tags/v1.3.0\n"
        )
        mock_git.return_value = (0, output, "")
        result = get_remote_latest_tag("git", Path("/fake"), 30)
        self.assertEqual(result, "v1.5.0")

    @patch('scripts.upgrade_check.run_git')
    def test_filters_peeled_refs(self, mock_git):
        output = (
            "abc123 refs/tags/v1.5.0\n"
            "abc123 refs/tags/v1.5.0^{}\n"
        )
        mock_git.return_value = (0, output, "")
        result = get_remote_latest_tag("git", Path("/fake"), 30)
        self.assertEqual(result, "v1.5.0")

    @patch('scripts.upgrade_check.run_git')
    def test_filters_non_version_tags(self, mock_git):
        """过滤无点号的非版本 tag"""
        output = "abc123 refs/tags/latest\n"
        mock_git.return_value = (0, output, "")
        result = get_remote_latest_tag("git", Path("/fake"), 30)
        self.assertIsNone(result)

    @patch('scripts.upgrade_check.run_git')
    def test_empty_output(self, mock_git):
        mock_git.return_value = (0, "", "")
        result = get_remote_latest_tag("git", Path("/fake"), 30)
        self.assertIsNone(result)

    @patch('scripts.upgrade_check.run_git')
    def test_git_failure(self, mock_git):
        mock_git.return_value = (1, "", "error")
        result = get_remote_latest_tag("git", Path("/fake"), 30)
        self.assertIsNone(result)


class TestPerformUpdate(unittest.TestCase):
    """测试 perform_update"""

    @patch('scripts.upgrade_check.check_user_module_update_safety', return_value=(True, ""))
    @patch('scripts.upgrade_check.run_git')
    def test_success(self, mock_git, _mock_safety):
        mock_git.side_effect = [
            (0, "", ""),  # fetch --tags
            (0, "", ""),  # reset origin/branch
        ]
        success, message = perform_update("git", Path("/fake"), "main", 30)
        self.assertTrue(success)
        self.assertEqual(message, "")

    @patch('scripts.upgrade_check.check_user_module_update_safety', return_value=(True, ""))
    @patch('scripts.upgrade_check.run_git')
    def test_success_with_target_tag(self, mock_git, _mock_safety):
        mock_git.side_effect = [
            (0, "", ""),  # fetch --tags
            (0, "", ""),  # reset to tag
        ]
        success, message = perform_update(
            "git", Path("/fake"), "main", 30, target_tag="2.0.3"
        )
        self.assertTrue(success)
        self.assertEqual(message, "")
        # 第二次调用应为 reset --hard 2.0.3
        self.assertEqual(mock_git.call_args_list[1][0][1], ["reset", "--hard", "2.0.3"])

    @patch('scripts.upgrade_check.check_user_module_update_safety', return_value=(True, ""))
    @patch('scripts.upgrade_check.run_git')
    def test_target_tag_fallback_to_branch(self, mock_git, _mock_safety):
        mock_git.side_effect = [
            (0, "", ""),       # fetch
            (1, "", "not found"),  # reset tag fails
            (0, "", ""),       # reset branch ok
        ]
        success, message = perform_update(
            "git", Path("/fake"), "main", 30, target_tag="2.0.3"
        )
        self.assertTrue(success)
        self.assertEqual(mock_git.call_args_list[2][0][1], ["reset", "--hard", "origin/main"])

    @patch('scripts.upgrade_check.check_user_module_update_safety', return_value=(True, ""))
    @patch('scripts.upgrade_check.run_git')
    def test_fetch_failure(self, mock_git, _mock_safety):
        mock_git.side_effect = [
            (1, "", "network error"),  # fetch fails
        ]
        success, message = perform_update("git", Path("/fake"), "main", 30)
        self.assertFalse(success)
        self.assertIn("fetch 失败", message)

    @patch('scripts.upgrade_check.check_user_module_update_safety', return_value=(True, ""))
    @patch('scripts.upgrade_check.run_git')
    def test_reset_failure(self, mock_git, _mock_safety):
        mock_git.side_effect = [
            (0, "", ""),       # fetch ok
            (1, "", "conflict"),  # reset fails
        ]
        success, message = perform_update("git", Path("/fake"), "main", 30)
        self.assertFalse(success)
        self.assertIn("reset 失败", message)

    @patch('scripts.upgrade_check.quarantine_locked_native_binaries', return_value=[])
    @patch('scripts.upgrade_check.run_git')
    def test_windows_unlink_retry_then_success(self, mock_git, mock_quarantine):
        """Windows 占用 .pyd 时：第一次 reset 失败，移走后重试成功。"""
        unlink_err = (
            "error: unable to unlink old "
            "'enterprise/pyarmor_runtime_015284/pyarmor_runtime.pyd': Invalid argument"
        )
        mock_git.side_effect = [
            (0, "", ""),          # fetch
            (1, "", unlink_err),  # reset tag fail (unlink)
            (0, "", ""),          # retry reset tag ok
        ]
        with patch('scripts.upgrade_check.sys.platform', 'win32'):
            success, message = perform_update(
                "git", Path("/fake"), "main", 30, target_tag="2.2.0"
            )
        self.assertTrue(success)
        self.assertEqual(message, "")
        # quarantine 至少被调用：预清理 + 失败后重试前
        self.assertGreaterEqual(mock_quarantine.call_count, 2)


class TestUserModuleUpdateSafety(unittest.TestCase):
    """用户模块目录不能被 reset 目标接管。"""

    @patch("scripts.upgrade_check.get_user_module_root_for_upgrade")
    @patch("scripts.upgrade_check.run_git")
    def test_external_root_is_not_affected(self, mock_git, mock_root):
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as module_dir:
            mock_root.return_value = Path(module_dir)
            safe, message = check_user_module_update_safety(
                "git", Path(project_dir), "v2.2.0", 30
            )
        self.assertTrue(safe)
        self.assertEqual(message, "")
        mock_git.assert_not_called()

    @patch("scripts.upgrade_check.get_user_module_root_for_upgrade")
    @patch("scripts.upgrade_check.run_git")
    def test_internal_untracked_root_is_safe(self, mock_git, mock_root):
        with tempfile.TemporaryDirectory() as project_dir:
            module_dir = Path(project_dir) / "data" / "user_modules"
            module_dir.mkdir(parents=True)
            mock_root.return_value = module_dir
            mock_git.side_effect = [(0, "", ""), (0, "", "")]
            safe, message = check_user_module_update_safety(
                "git", Path(project_dir), "v2.2.0", 30
            )
        self.assertTrue(safe)
        self.assertEqual(message, "")

    @patch("scripts.upgrade_check.get_user_module_root_for_upgrade")
    @patch("scripts.upgrade_check.run_git")
    def test_missing_internal_root_still_checks_target_collision(self, mock_git, mock_root):
        with tempfile.TemporaryDirectory() as project_dir:
            module_dir = Path(project_dir) / "data" / "user_modules"
            mock_root.return_value = module_dir
            mock_git.side_effect = [
                (0, "", ""),
                (0, "data/user_modules/owned-by-core.py", ""),
            ]
            safe, message = check_user_module_update_safety(
                "git", Path(project_dir), "v2.2.0", 30
            )
        self.assertFalse(safe)
        self.assertIn("目标版本", message)

    @patch("scripts.upgrade_check.get_user_module_root_for_upgrade")
    @patch("scripts.upgrade_check.run_git")
    def test_current_tracked_root_is_rejected(self, mock_git, mock_root):
        with tempfile.TemporaryDirectory() as project_dir:
            module_dir = Path(project_dir) / "data" / "user_modules"
            module_dir.mkdir(parents=True)
            mock_root.return_value = module_dir
            mock_git.return_value = (0, "data/user_modules/module.py", "")
            safe, message = check_user_module_update_safety(
                "git", Path(project_dir), "v2.2.0", 30
            )
        self.assertFalse(safe)
        self.assertIn("已被 Git 跟踪", message)

    @patch("scripts.upgrade_check.get_user_module_root_for_upgrade")
    @patch("scripts.upgrade_check.run_git")
    def test_target_path_collision_is_rejected(self, mock_git, mock_root):
        with tempfile.TemporaryDirectory() as project_dir:
            module_dir = Path(project_dir) / "data" / "user_modules"
            module_dir.mkdir(parents=True)
            mock_root.return_value = module_dir
            mock_git.side_effect = [
                (0, "", ""),
                (0, "data/user_modules/owned-by-core.py", ""),
            ]
            safe, message = check_user_module_update_safety(
                "git", Path(project_dir), "v2.2.0", 30
            )
        self.assertFalse(safe)
        self.assertIn("拒绝自动更新", message)


class TestUserModuleCompatibility(unittest.TestCase):
    def test_version_constraints(self):
        self.assertTrue(_version_satisfies("2.1.5", ">=2.1.5,<3.0"))
        self.assertFalse(_version_satisfies("3.0.0", ">=2.1.5,<3.0"))

    @patch("scripts.upgrade_check.run_git")
    @patch("scripts.upgrade_check.get_user_module_root_for_upgrade")
    def test_compatible_release_allows_update(self, mock_root, mock_git):
        with tempfile.TemporaryDirectory() as module_dir:
            root = Path(module_dir)
            release = root / "modules" / "demo.echo" / "releases" / "1.0.0-test"
            release.mkdir(parents=True)
            (release / "manifest.json").write_text(
                '{"manifest_schema_version":1,"module_id":"demo.echo","version":"1.0.0",'
                '"rpc_protocol":"user-module-rpc/v1","driver_protocol":"media-driver/v1",'
                '"sdk_version":"1.0.0","execution_model":"native_async",'
                '"core_compat":">=2.1.5,<3.0","python_compat":">=3.10,<3.11",'
                '"capabilities":[{"media_kind":"image"}]}',
                encoding="utf-8",
            )
            mock_root.return_value = root
            mock_git.return_value = (
                0,
                '{"abi_schema_version":1,"core_version":"0.0.1","python_version":"3.10.20",'
                '"manifest_schema_versions":[1],"rpc_protocol_versions":["user-module-rpc/v1"],'
                '"driver_protocol_versions":["media-driver/v1"],"sdk_versions":["1.0.0"],'
                '"execution_models":["native_async"],"media_kinds":["image","video","audio"]}',
                "",
            )
            mock_git.side_effect = [mock_git.return_value, (0, '[project]\nversion = "2.2.0"\n', "")]
            safe, message = check_user_module_compatibility(
                "git", Path("/fake"), "v2.2.0", 30
            )
            report = (root / "state" / "update-compatibility.json").read_text(encoding="utf-8")
        self.assertTrue(safe)
        self.assertEqual(message, "")
        self.assertIn('"compatible": true', report)

    @patch("scripts.upgrade_check.run_git")
    @patch("scripts.upgrade_check.get_user_module_root_for_upgrade")
    def test_incompatible_release_blocks_by_default(self, mock_root, mock_git):
        with tempfile.TemporaryDirectory() as module_dir:
            root = Path(module_dir)
            release = root / "modules" / "demo.echo" / "releases" / "1.0.0-test"
            release.mkdir(parents=True)
            (release / "manifest.json").write_text(
                '{"manifest_schema_version":1,"module_id":"demo.echo","version":"1.0.0",'
                '"rpc_protocol":"user-module-rpc/v0","driver_protocol":"media-driver/v1",'
                '"sdk_version":"1.0.0","execution_model":"native_async",'
                '"capabilities":[{"media_kind":"image"}]}',
                encoding="utf-8",
            )
            mock_root.return_value = root
            mock_git.return_value = (
                0,
                '{"abi_schema_version":1,"core_version":"2.2.0","python_version":"3.10.20",'
                '"manifest_schema_versions":[1],"rpc_protocol_versions":["user-module-rpc/v1"],'
                '"driver_protocol_versions":["media-driver/v1"],"sdk_versions":["1.0.0"],'
                '"execution_models":["native_async"],"media_kinds":["image"]}',
                "",
            )
            mock_git.side_effect = [mock_git.return_value, (0, '[project]\nversion = "2.2.0"\n', "")]
            safe, message = check_user_module_compatibility(
                "git", Path("/fake"), "v2.2.0", 30
            )
        self.assertFalse(safe)
        self.assertIn("已阻止自动更新", message)

    @patch("scripts.upgrade_check.run_git")
    @patch("scripts.upgrade_check.get_user_module_root_for_upgrade")
    def test_quarantine_policy_records_but_allows_update(self, mock_root, mock_git):
        with tempfile.TemporaryDirectory() as module_dir:
            root = Path(module_dir)
            release = root / "modules" / "demo.echo" / "releases" / "broken"
            release.mkdir(parents=True)
            (release / "manifest.json").write_text("{}", encoding="utf-8")
            mock_root.return_value = root
            mock_git.return_value = (
                0,
                '{"abi_schema_version":1,"core_version":"2.2.0","python_version":"3.10.20",'
                '"manifest_schema_versions":[1],"rpc_protocol_versions":[],"driver_protocol_versions":[], '
                '"sdk_versions":[],"execution_models":[],"media_kinds":[]}',
                "",
            )
            mock_git.side_effect = [mock_git.return_value, (0, '[project]\nversion = "2.2.0"\n', "")]
            safe, message = check_user_module_compatibility(
                "git", Path("/fake"), "v2.2.0", 30, policy="quarantine"
            )
        self.assertTrue(safe)
        self.assertTrue(message)


class TestUpdateRemoteUrlIfNeeded(unittest.TestCase):
    """测试 update_remote_url_if_needed"""

    @patch('scripts.upgrade_check.run_git')
    def test_already_on_first_source(self, mock_git):
        """当前 origin 已经是最高优先级源"""
        mock_git.side_effect = [
            (0, "https://github.com/repo.git\n", ""),  # get-url
        ]
        result = update_remote_url_if_needed(
            "git", Path("/fake"),
            ["https://github.com/repo", "https://backup.com/repo"],
            30
        )
        self.assertTrue(result)

    @patch('scripts.upgrade_check.run_git')
    def test_switch_to_first_source(self, mock_git):
        """切换到最高优先级源"""
        mock_git.side_effect = [
            (0, "https://old.com/repo.git\n", ""),  # get-url
            (0, "", ""),   # set-url
            (0, "", ""),   # ls-remote check
        ]
        result = update_remote_url_if_needed(
            "git", Path("/fake"),
            ["https://new.com/repo", "https://old.com/repo"],
            30
        )
        self.assertTrue(result)

    @patch('scripts.upgrade_check.run_git')
    def test_no_origin_adds_first(self, mock_git):
        """没有 origin，添加第一个源"""
        mock_git.side_effect = [
            (1, "", "no origin"),  # get-url: no origin
            (0, "", ""),           # remote add
        ]
        result = update_remote_url_if_needed(
            "git", Path("/fake"),
            ["https://github.com/repo"],
            30
        )
        self.assertTrue(result)

    @patch('scripts.upgrade_check.run_git')
    def test_first_source_unavailable_fallback(self, mock_git):
        """最高优先级源不可用，回退到当前源"""
        mock_git.side_effect = [
            (0, "https://backup.com/repo.git\n", ""),  # get-url
            (0, "", ""),   # set-url to first
            (1, "", ""),   # ls-remote fails (first unavailable)
            (0, "", ""),   # restore set-url
        ]
        result = update_remote_url_if_needed(
            "git", Path("/fake"),
            ["https://primary.com/repo", "https://backup.com/repo"],
            30
        )
        self.assertTrue(result)

    @patch('scripts.upgrade_check.run_git')
    def test_url_normalization_with_dot_git(self, mock_git):
        """URL 标准化：去掉 .git 后缀"""
        mock_git.side_effect = [
            (0, "https://github.com/repo\n", ""),  # get-url (without .git)
        ]
        result = update_remote_url_if_needed(
            "git", Path("/fake"),
            ["https://github.com/repo.git"],  # with .git
            30
        )
        self.assertTrue(result)


class TestCheckBinariesForVersion(unittest.TestCase):
    """测试 check_binaries_for_version"""

    def test_empty_config(self):
        result = check_binaries_for_version(Path("/fake"), {}, "v1.0.0")
        self.assertEqual(result, [])

    def test_no_binaries_key(self):
        result = check_binaries_for_version(Path("/fake"), {"other": "data"}, "v1.0.0")
        self.assertEqual(result, [])

    def test_version_below_required_since(self):
        """版本低于 required_since，跳过检查"""
        config = {
            "binaries": {
                "ffmpeg": {
                    "required_since": "2.0.0",
                    "check_paths": {"linux": "bin/ffmpeg"},
                    "description": "Video processor"
                }
            }
        }
        result = check_binaries_for_version(Path("/fake"), config, "v1.0.0")
        self.assertEqual(result, [])

    @patch('scripts.upgrade_check.sys')
    def test_missing_binary_reported(self, mock_sys):
        """缺少的二进制被报告"""
        mock_sys.platform = "linux"
        config = {
            "binaries": {
                "ffmpeg": {
                    "required_since": "0.0.1",
                    "check_paths": {"linux": "bin/ffmpeg"},
                    "description": "Video processor",
                    "download_url": "https://example.com/ffmpeg"
                }
            }
        }
        fake_path = MagicMock()
        fake_path.exists.return_value = False

        with patch.object(Path, '__truediv__', return_value=fake_path):
            result = check_binaries_for_version(Path("/fake"), config, "v1.0.0")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'ffmpeg')
        self.assertEqual(result[0]['download_url'], 'https://example.com/ffmpeg')

    def test_existing_binary_not_reported(self):
        """存在的二进制不被报告"""
        config = {
            "binaries": {
                "git": {
                    "required_since": "0.0.1",
                    "check_paths": {"linux": "bin/git"},
                }
            }
        }
        fake_path = MagicMock()
        fake_path.exists.return_value = True

        with patch.object(Path, '__truediv__', return_value=fake_path):
            result = check_binaries_for_version(Path("/fake"), config, "v1.0.0")

        self.assertEqual(result, [])

    def test_no_check_path_for_platform(self):
        """当前平台没有配置检查路径"""
        config = {
            "binaries": {
                "ffmpeg": {
                    "required_since": "0.0.1",
                    "check_paths": {"windows": "bin/ffmpeg.exe"},
                }
            }
        }
        # 假设在 linux 上运行但配置只有 windows 路径
        with patch('scripts.upgrade_check.sys') as mock_sys:
            mock_sys.platform = "linux"
            result = check_binaries_for_version(Path("/fake"), config, "v1.0.0")
        self.assertEqual(result, [])


class TestRunGit(unittest.TestCase):
    """测试 run_git"""

    @patch('scripts.upgrade_check.subprocess.run')
    def test_success_with_capture(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        rc, out, err = run_git("git", ["status"], Path("/fake"))
        self.assertEqual(rc, 0)
        self.assertEqual(out, "output")

    @patch('scripts.upgrade_check.subprocess.run')
    def test_injects_credential_helper_disable(self, mock_run):
        """必须用 -c credential.helper=，禁止空 GIT_CONFIG_VALUE"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        run_git("git", ["fetch", "origin"], Path("/fake"))
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[:3], ["git", "-c", "credential.helper="])
        self.assertEqual(cmd[3:], ["fetch", "origin"])
        env = mock_run.call_args[1]["env"]
        self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0")
        self.assertNotIn("GIT_CONFIG_COUNT", env)

    @patch('scripts.upgrade_check.subprocess.run')
    def test_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)

        rc, out, err = run_git("git", ["fetch"], Path("/fake"))
        self.assertEqual(rc, -1)
        self.assertEqual(err, "timeout")

    @patch('scripts.upgrade_check.subprocess.run')
    def test_exception(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")

        rc, out, err = run_git("git", ["status"], Path("/fake"))
        self.assertEqual(rc, -1)
        self.assertIn("git not found", err)


class TestNormalizeAndAuthError(unittest.TestCase):
    def test_normalize_repo_url(self):
        self.assertEqual(
            normalize_repo_url("https://gitee.com/a/b.git/"),
            "https://gitee.com/a/b",
        )
        self.assertEqual(normalize_repo_url(""), "")

    def test_is_auth_or_prompt_error(self):
        self.assertTrue(
            is_auth_or_prompt_error(
                "fatal: could not read Username for 'https://gitee.com': "
                "terminal prompts disabled"
            )
        )
        self.assertTrue(is_auth_or_prompt_error("Authentication failed"))
        self.assertFalse(is_auth_or_prompt_error("timeout"))
        self.assertFalse(is_auth_or_prompt_error(""))


class TestFetchRemoteWithFallback(unittest.TestCase):
    """测试多源 fetch 回退"""

    @patch('scripts.upgrade_check.run_git')
    def test_first_source_success(self, mock_git):
        mock_git.side_effect = [
            (0, "https://gitee.com/a/b.git\n", ""),  # get current
            (0, "https://gitee.com/a/b.git\n", ""),  # get current in loop
            (0, "", ""),  # fetch ok
        ]
        ok, err = fetch_remote_with_fallback(
            "git", Path("/fake"),
            ["https://gitee.com/a/b.git", "https://github.com/a/b.git"],
            "main", 30,
        )
        self.assertTrue(ok)
        self.assertEqual(err, "")

    @patch('scripts.upgrade_check.run_git')
    def test_fallback_to_second_source(self, mock_git):
        """Gitee 鉴权失败后自动切 GitHub"""
        auth_err = (
            "fatal: could not read Username for 'https://gitee.com': "
            "terminal prompts disabled"
        )
        mock_git.side_effect = [
            (0, "https://gitee.com/a/b.git\n", ""),  # get current (outer)
            (0, "https://gitee.com/a/b.git\n", ""),  # loop #1 get current
            (1, "", auth_err),  # fetch gitee fails
            (0, "https://gitee.com/a/b.git\n", ""),  # loop #2 get current
            (0, "", ""),  # set-url github
            (0, "", ""),  # fetch github ok
        ]
        ok, err = fetch_remote_with_fallback(
            "git", Path("/fake"),
            ["https://gitee.com/a/b.git", "https://github.com/a/b.git"],
            "main", 30,
        )
        self.assertTrue(ok)
        self.assertEqual(err, "")
        # 确认 set-url 到 github
        set_url_calls = [
            c for c in mock_git.call_args_list
            if c[0][1][:2] == ["remote", "set-url"]
        ]
        self.assertTrue(set_url_calls)
        self.assertEqual(
            set_url_calls[0][0][1],
            ["remote", "set-url", "origin", "https://github.com/a/b.git"],
        )

    @patch('scripts.upgrade_check.run_git')
    def test_all_sources_fail(self, mock_git):
        mock_git.side_effect = [
            (0, "https://gitee.com/a/b.git\n", ""),
            (0, "https://gitee.com/a/b.git\n", ""),
            (1, "", "network error"),
            (0, "https://gitee.com/a/b.git\n", ""),
            (0, "", ""),  # set-url
            (1, "", "network error 2"),
        ]
        ok, err = fetch_remote_with_fallback(
            "git", Path("/fake"),
            ["https://gitee.com/a/b.git", "https://github.com/a/b.git"],
            "main", 30,
        )
        self.assertFalse(ok)
        self.assertIn("network error", err)


if __name__ == '__main__':
    unittest.main()
