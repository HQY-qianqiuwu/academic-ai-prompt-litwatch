import pytest
from pydantic import ValidationError

from litwatch.config import Settings
from litwatch.runtime import RuntimeMode, RuntimeStatus


def test_runtime_defaults_to_python():
    settings = Settings(_env_file=None)

    assert settings.runtime_mode is RuntimeMode.PYTHON_DEFAULT
    assert RuntimeStatus.from_mode(settings.runtime_mode).requires_dify is False


def test_unknown_runtime_mode_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, runtime_mode="unknown")
