import pytest
from pydantic import ValidationError

from vireon.config import Settings


def test_production_requires_non_default_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret="change-me-in-production")
