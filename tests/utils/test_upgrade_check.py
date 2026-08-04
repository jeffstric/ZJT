"""
升级检查脚本单元测试

测试 scripts/upgrade_check.py 中的纯函数逻辑。
使用 mock 隔离 git 命令、文件系统、YAML 解析等外部依赖。
"""
import os
import sys
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
        """HEAD 上有 tag 时纳入候选（并可成为最高版本）"""
        mock_git.side_effect = [
            (0, "v1.5.1\n", ""),  # tag --points-at HEAD
            (0, "v1.5.0\n", ""),  # describe
        ]
        with patch('scripts.upgrade_check.read_pyproject_version', return_value=None):
            result = get_local_version(Path("/fake"), git_cmd="git")
        self.assertEqual(result, "v1.5.1")

    @patch('scripts.upgrade_check.run_git')
    def test_git_describe_fallback(self, mock_git):
        """tag --points-at 无结果，回退到 git describe（无更高 pyproject）"""
        mock_git.side_effect = [
            (0, "", ""),          # tag --points-at HEAD: empty
            (0, "v1.4.0\n", ""),  # describe --tags --abbrev=0
        ]
        with patch('scripts.upgrade_check.read_pyproject_version', return_value=None):
            result = get_local_version(Path("/fake"), git_cmd="git")
        self.assertEqual(result, "v1.4.0")

    @patch('scripts.upgrade_check.run_git')
    def test_pyproject_wins_when_newer_than_describe(self, mock_git):
        """describe 停在旧 tag、pyproject 已是新版本时，取更高者（防启动死循环）"""
        mock_git.side_effect = [
            (0, "", ""),          # tag --points-at HEAD: empty
            (0, "2.0.2\n", ""),   # describe 仍为旧 tag
        ]
        with patch('scripts.upgrade_check.read_pyproject_version', return_value="2.0.3"):
            result = get_local_version(Path("/fake"), git_cmd="git")
        self.assertEqual(result, "2.0.3")

    @patch('scripts.upgrade_check.run_git')
    def test_multiple_tags_picks_highest(self, mock_git):
        """多个 tag 在 HEAD 时选择最高的"""
        mock_git.side_effect = [
            (0, "v1.5.0\nv1.5.1\nv1.4.9\n", ""),  # multiple tags
            (0, "v1.5.0\n", ""),                  # describe
        ]
        with patch('scripts.upgrade_check.read_pyproject_version', return_value=None):
            result = get_local_version(Path("/fake"), git_cmd="git")
        self.assertEqual(result, "v1.5.1")

    @patch('scripts.upgrade_check.run_git')
    def test_fallback_to_pyproject_toml(self, mock_git):
        """git 不可用时回退到 pyproject.toml"""
        mock_git.side_effect = [
            (1, "", "not a git repo"),
            (1, "", "not a git repo"),
        ]
        with patch('scripts.upgrade_check.read_pyproject_version', return_value="1.3.0"):
            result = get_local_version(Path("/fake"), git_cmd="git")

        self.assertEqual(result, "1.3.0")

    def test_no_git_no_pyproject(self):
        """无 git 且无 pyproject.toml"""
        pyproject = MagicMock()
        pyproject.exists.return_value = False

        with patch.object(Path, '__truediv__', return_value=pyproject):
            result = get_local_version(Path("/fake"), git_cmd=None)

        self.assertEqual(result, "unknown")


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

    @patch('scripts.upgrade_check.run_git')
    def test_success(self, mock_git):
        mock_git.side_effect = [
            (0, "", ""),  # fetch --tags
            (0, "", ""),  # reset origin/branch
        ]
        success, message = perform_update("git", Path("/fake"), "main", 30)
        self.assertTrue(success)
        self.assertEqual(message, "")

    @patch('scripts.upgrade_check.run_git')
    def test_success_with_target_tag(self, mock_git):
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

    @patch('scripts.upgrade_check.run_git')
    def test_target_tag_fallback_to_branch(self, mock_git):
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

    @patch('scripts.upgrade_check.run_git')
    def test_fetch_failure(self, mock_git):
        mock_git.side_effect = [
            (1, "", "network error"),  # fetch fails
        ]
        success, message = perform_update("git", Path("/fake"), "main", 30)
        self.assertFalse(success)
        self.assertIn("fetch 失败", message)

    @patch('scripts.upgrade_check.run_git')
    def test_reset_failure(self, mock_git):
        mock_git.side_effect = [
            (0, "", ""),       # fetch ok
            (1, "", "conflict"),  # reset fails
        ]
        success, message = perform_update("git", Path("/fake"), "main", 30)
        self.assertFalse(success)
        self.assertIn("reset 失败", message)


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
