from functools import lru_cache
from typing import Set
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """アプリケーション設定管理（環境変数および.envから読込）"""

    # LINE Messaging API 設定
    LINE_CHANNEL_SECRET: str = Field(
        default="dummy_channel_secret",
        description="LINE Channel Secret",
    )
    LINE_CHANNEL_ACCESS_TOKEN: str = Field(
        default="dummy_channel_access_token",
        description="LINE Channel Access Token",
    )
    LINE_BOT_USER_ID: str = Field(
        default="",
        description="LINE Bot User ID (メンション検知の精度向上用・省略可能)",
    )

    # Google Gemini API 設定
    GEMINI_API_KEY: str = Field(
        default="dummy_gemini_api_key",
        description="Google Gemini API Key",
    )
    GEMINI_MODEL: str = Field(
        default="gemini-2.5-flash",
        description="使用するGeminiモデル名",
    )

    # セキュリティ・アクセス制御（カンマ区切り文字列）
    ALLOWED_GROUP_IDS_RAW: str = Field(
        default="",
        alias="ALLOWED_GROUP_IDS",
        description="利用を許可するグループID（カンマ区切り・空の場合は全グループ許可）",
    )
    ALLOWED_USER_IDS_RAW: str = Field(
        default="",
        alias="ALLOWED_USER_IDS",
        description="利用を許可するユーザーID（カンマ区切り・空の場合は全ユーザー許可）",
    )

    # サーバー設定
    PORT: int = Field(default=8000, description="コンテナ内待受ポート")
    LOG_LEVEL: str = Field(default="INFO", description="ログレベル")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_group_ids(self) -> Set[str]:
        """カンマ区切りの文字列をトリムされたセットとして返す"""
        if not self.ALLOWED_GROUP_IDS_RAW.strip():
            return set()
        return {gid.strip() for gid in self.ALLOWED_GROUP_IDS_RAW.split(",") if gid.strip()}

    @property
    def allowed_user_ids(self) -> Set[str]:
        """カンマ区切りの文字列をトリムされたセットとして返す"""
        if not self.ALLOWED_USER_IDS_RAW.strip():
            return set()
        return {uid.strip() for uid in self.ALLOWED_USER_IDS_RAW.split(",") if uid.strip()}


@lru_cache()
def get_settings() -> Settings:
    """設定シングルトンインスタンスを取得"""
    return Settings()
