"""應用設定：從環境變數 / .env 載入，集中管理可調參數。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 欄位會自動對應同名（不分大小寫）的環境變數；.env 不存在時用下方預設值。
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 預設指向本機 Postgres；測試與免 Docker 開發時可覆寫成 sqlite+aiosqlite。
    database_url: str = "postgresql+asyncpg://chatweb:chatweb@localhost:5432/chatweb"
    jwt_secret: str = "dev-secret-change-me"  # 正式環境務必以環境變數覆寫
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # token 有效時間（分鐘），預設 1 天
    # CORS 允許來源以逗號分隔字串存放（環境變數友善），用時再切成 list。
    cors_origins: str = "http://localhost:5000,http://localhost:5001,http://localhost:5002"
    upload_dir: str = str(
        __import__("pathlib").Path(__file__).resolve().parents[1] / "uploads"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """快取單一 Settings 實例，避免每次請求重讀 .env。"""
    return Settings()
