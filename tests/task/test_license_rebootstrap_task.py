"""license_rebootstrap_task 门面的委托 / 注册 / 社区默认行为（不连 DB、不联网）。"""
import pytest

import task.license_rebootstrap_task as facade


class _StubProvider:
    available = True

    def __init__(self):
        self.calls = {"rebootstrap": 0}

    def rebootstrap(self) -> None:
        self.calls["rebootstrap"] += 1

    def is_non_transient_error(self, exc: BaseException) -> bool:
        return exc.__class__.__name__ == "SimulatedLicenseError"


@pytest.fixture(autouse=True)
def _reset_provider():
    facade.reset_provider()
    yield
    facade.reset_provider()


def test_community_default_is_noop():
    """未注册商业版实现时（社区版），job 入口必须安全空操作。"""
    assert facade.is_available() is False
    assert facade.rebootstrap_commercial_license() is None
    assert facade.is_non_transient_error(RuntimeError("x")) is False


def test_register_provider_requires_available():
    class _Unavailable:
        available = False

        def rebootstrap(self) -> None:
            pass

        def is_non_transient_error(self, exc: BaseException) -> bool:
            return False

    with pytest.raises(ValueError):
        facade.register_provider(None)
    with pytest.raises(ValueError):
        facade.register_provider(_Unavailable())


def test_registered_provider_receives_delegation():
    stub = _StubProvider()
    facade.register_provider(stub)

    assert facade.is_available() is True
    facade.rebootstrap_commercial_license()
    assert stub.calls["rebootstrap"] == 1


def test_is_non_transient_error_delegates_to_provider():
    class SimulatedLicenseError(Exception):
        pass

    stub = _StubProvider()
    facade.register_provider(stub)

    assert facade.is_non_transient_error(SimulatedLicenseError("denied")) is True
    assert facade.is_non_transient_error(RuntimeError("x")) is False


def test_reset_provider_restores_community_default():
    facade.register_provider(_StubProvider())
    assert facade.is_available() is True

    facade.reset_provider()

    assert facade.is_available() is False
    assert facade.rebootstrap_commercial_license() is None
