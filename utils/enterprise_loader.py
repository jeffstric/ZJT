import json
import os
import sys
import logging
import importlib

from config.version import get_app_version
from config.config_util import get_config_value

logger = logging.getLogger(__name__)

ENTERPRISE_DIR = "enterprise"
VERSION_FILE = "version.json"


def _parse_version(v: str) -> tuple:
    """将版本号字符串解析为元组，用于比较"""
    return tuple(int(x) for x in v.split('.'))


def _version_in_range(v: str, min_v: str, max_v: str) -> bool:
    """检查版本 v 是否在 [min_v, max_v] 范围内（闭区间）"""
    pv = _parse_version(v)
    pmin = _parse_version(min_v)
    pmax = _parse_version(max_v)
    return pmin <= pv <= pmax


class EnterpriseLoader:
    def __init__(self):
        self.loaded = False
        self.enterprise_version = None
        # package_available 只有在 enterprise 模块成功导入后才为 True。
        # 仅发现目录/version.json 不足以证明 PyArmor 运行时和加密代码可用。
        self.package_available = False
        self.registration_failed = False
        self.failure_reason = None

    def _get_project_root(self) -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def discover(self) -> bool:
        """检测 enterprise 模块是否存在且版本兼容"""
        self.enterprise_version = None
        self.package_available = False
        self.registration_failed = False
        self.failure_reason = None
        edition_mode = get_config_value('edition', 'mode', default='community')
        if edition_mode != 'enterprise':
            logger.info('Enterprise mode is disabled by configuration')
            return False

        project_root = self._get_project_root()
        enterprise_path = os.path.join(project_root, ENTERPRISE_DIR)

        if not os.path.isdir(enterprise_path):
            logger.info("Enterprise module not found, running in community/basic mode")
            return False

        version_file = os.path.join(enterprise_path, VERSION_FILE)
        if not os.path.isfile(version_file):
            logger.warning("Enterprise directory exists but version.json not found, skipping")
            return False

        try:
            with open(version_file, 'r', encoding='utf-8') as f:
                ent_data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read enterprise version.json: {e}")
            return False

        ent_version = ent_data.get("version", "0.0.0")
        min_core = ent_data.get("min_core_version", "0.0.0")
        max_core = ent_data.get("max_core_version", "99.99.99")

        core_version = get_app_version()

        # 检查核心版本是否满足 enterprise 要求（若 enterprise 未声明则跳过）
        if "min_core_version" in ent_data or "max_core_version" in ent_data:
            if not _version_in_range(core_version, min_core, max_core):
                logger.error(
                    f"Core version {core_version} not in enterprise requirement "
                    f"[{min_core}, {max_core}]"
                )
                return False

        # 检查 enterprise 版本是否满足主仓库要求
        min_ent = get_config_value("enterprise", "min_version", default="0.0.0")
        max_ent = get_config_value("enterprise", "max_version", default="99.99.99")

        if not _version_in_range(ent_version, min_ent, max_ent):
            logger.error(
                f"Enterprise version {ent_version} not in manifest requirement "
                f"[{min_ent}, {max_ent}]"
            )
            return False

        self.enterprise_version = ent_version
        logger.info(f"Enterprise module discovered: version {ent_version}")
        return True

    def load(self, app):
        """加载 enterprise 模块"""
        if self.loaded:
            return

        self.package_available = False
        self.registration_failed = False
        self.failure_reason = None
        try:
            # 确保项目根目录在 sys.path 中，使 Python 能找到 enterprise 包
            project_root = self._get_project_root()
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            enterprise_module = importlib.import_module("enterprise")
            # 能完成 import 才能证明 PyArmor 未过期且商业包当前可执行。
            self.package_available = True
            enterprise_module.register(app)
            self.loaded = True
            logger.info("Enterprise module loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load enterprise module: {e}")
            self.loaded = False
            if self.package_available:
                # 商业包可以正常导入，但后续路由/Provider 注册失败。
                self.registration_failed = True
                self.failure_reason = (
                    "Enterprise 商业包已识别，但组件注册未完成；"
                    "许可证操作暂不可用，请检查服务日志并重启"
                )
            else:
                # 包无法导入（包含 PyArmor 过期、损坏、依赖缺失等情况）。
                # 此时不能展示可提交凭据的许可证入口。
                self.failure_reason = "Enterprise 商业包无法加载"
            try:
                from task.runninghub_key_pool import reset_provider
                reset_provider()
            except Exception:
                pass

            try:
                from services.registration_quota import reset_provider as reset_registration_quota
                reset_registration_quota()
            except Exception:
                pass

            try:
                from services.face_mask_provider import (
                    reset_provider as reset_face_mask_provider,
                )
                reset_face_mask_provider()
            except Exception:
                pass

    def get_runtime_status(self) -> dict[str, object]:
        """返回供管理界面使用的非敏感商业包状态快照。"""
        return {
            "package_available": self.package_available,
            "registration_ready": self.loaded,
            # 当前 Enterprise 注册是全有或全无；只有完整注册后许可证路由
            # 和运行时才可安全接受 Token、刷新或注销请求。
            "license_control_available": self.loaded,
            "registration_failed": self.registration_failed,
            "failure_reason": self.failure_reason if self.package_available else None,
            "enterprise_version": self.enterprise_version,
        }


enterprise_loader = EnterpriseLoader()
