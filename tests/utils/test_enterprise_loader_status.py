from unittest.mock import patch

from utils.enterprise_loader import EnterpriseLoader


class _HealthyEnterpriseModule:
    @staticmethod
    def register(_app) -> None:
        return None


class _BrokenRegistrationModule:
    @staticmethod
    def register(_app) -> None:
        raise RuntimeError("injected registration failure")


def test_successful_enterprise_registration_enables_license_control() -> None:
    loader = EnterpriseLoader()

    with patch(
        "utils.enterprise_loader.importlib.import_module",
        return_value=_HealthyEnterpriseModule,
    ):
        loader.load(object())

    assert loader.get_runtime_status() == {
        "package_available": True,
        "registration_ready": True,
        "license_control_available": True,
        "registration_failed": False,
        "failure_reason": None,
        "enterprise_version": None,
    }


def test_registration_failure_keeps_package_visible_but_disables_actions() -> None:
    loader = EnterpriseLoader()

    with patch(
        "utils.enterprise_loader.importlib.import_module",
        return_value=_BrokenRegistrationModule,
    ):
        loader.load(object())

    status = loader.get_runtime_status()
    assert status["package_available"] is True
    assert status["registration_ready"] is False
    assert status["license_control_available"] is False
    assert status["registration_failed"] is True
    assert "注册未完成" in str(status["failure_reason"])


def test_import_failure_hides_license_entry_and_disables_actions() -> None:
    loader = EnterpriseLoader()

    with patch(
        "utils.enterprise_loader.importlib.import_module",
        side_effect=RuntimeError("simulated pyarmor/import failure"),
    ):
        loader.load(object())

    status = loader.get_runtime_status()
    assert status["package_available"] is False
    assert status["registration_ready"] is False
    assert status["license_control_available"] is False
    assert status["registration_failed"] is False
    # 包无法导入时不把内部错误或路径暴露给管理界面。
    assert status["failure_reason"] is None
