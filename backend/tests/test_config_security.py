"""正式環境安全前置檢查:ensure_secure() 對預設 jwt_secret 的把關。"""

import pytest

from app.config import DEFAULT_JWT_SECRET, Settings


def _settings(**overrides) -> Settings:
    # _env_file=None:不讀本機 .env,讓測試只依傳入值,結果可預期。
    base = {"environment": "development", "jwt_secret": "x", "_env_file": None}
    base.update(overrides)
    return Settings(**base)


def test_production_with_default_secret_refuses_startup():
    s = _settings(environment="production", jwt_secret=DEFAULT_JWT_SECRET)
    assert s.is_production is True
    with pytest.raises(RuntimeError):
        s.ensure_secure()


def test_production_with_overridden_secret_ok():
    s = _settings(environment="production", jwt_secret="a-real-strong-secret")
    s.ensure_secure()  # 不應拋錯


def test_non_production_allows_default_secret():
    # 開發/測試環境用預設密鑰是允許的(免設定即可跑)。
    s = _settings(environment="development", jwt_secret=DEFAULT_JWT_SECRET)
    assert s.is_production is False
    s.ensure_secure()  # 不應拋錯


def test_environment_case_insensitive():
    assert _settings(environment="Production").is_production is True
    assert _settings(environment="PRODUCTION").is_production is True
