"""應用設定：從環境變數 / .env 載入，集中管理可調參數。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 預設(開發用)JWT 密鑰。正式環境若仍是此值代表沒設 JWT_SECRET，token 可被任意偽造。
DEFAULT_JWT_SECRET = "dev-secret-change-me"


class Settings(BaseSettings):
    # 欄位會自動對應同名（不分大小寫）的環境變數；.env 不存在時用下方預設值。
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 部署環境標記：production 時會強制要求覆寫安全相關預設值（見 ensure_secure）。
    environment: str = "development"
    # 預設指向本機 Postgres；測試與免 Docker 開發時可覆寫成 sqlite+aiosqlite。
    database_url: str = "postgresql+asyncpg://chatweb:chatweb@localhost:5432/chatweb"
    jwt_secret: str = DEFAULT_JWT_SECRET  # 正式環境務必以環境變數覆寫
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # token 有效時間（分鐘），預設 1 天
    # 註冊速率限制：每來源 IP 在 window 秒內最多幾次（E2E/壓測可用環境變數調高以免誤擋）。
    register_rate_limit_max: int = 20
    register_rate_limit_window_seconds: int = 3600
    # CORS 允許來源以逗號分隔字串存放（環境變數友善），用時再切成 list。
    cors_origins: str = "http://localhost:5000,http://localhost:5001,http://localhost:5002"
    upload_dir: str = str(
        __import__("pathlib").Path(__file__).resolve().parents[1] / "uploads"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    def ensure_secure(self) -> None:
        """正式環境的安全前置檢查：拒絕以預設值啟動。

        若 environment=production 卻仍用預設 jwt_secret，任何人都能偽造任意使用者的
        JWT（等同帳號接管），故直接讓 App 啟動失敗，逼使部署端設定 JWT_SECRET。
        """
        if self.is_production and self.jwt_secret == DEFAULT_JWT_SECRET:
            raise RuntimeError(
                "正式環境必須以 JWT_SECRET 環境變數覆寫預設密鑰，否則 token 可被偽造"
            )


@lru_cache
def get_settings() -> Settings:
    """快取單一 Settings 實例，避免每次請求重讀 .env。"""
    return Settings()
