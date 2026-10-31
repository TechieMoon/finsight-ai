from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    finsight_mode: Literal["mock", "live"] = "mock"
    dart_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    chroma_path: str = "data/chroma"
    request_timeout: float = Field(default=20, ge=1, le=60)
    dart_calls_per_minute: int = Field(default=30, ge=1, le=100)
    api_calls_per_minute: int = Field(default=10, ge=1, le=100)
    rag_max_distance: float = Field(default=0.6, ge=0, le=2)

    def require_live(self, *, rag: bool = False) -> None:
        if not self.dart_api_key.get_secret_value():
            raise ValueError("실제 모드에는 DART_API_KEY가 필요합니다.")
        if rag and not self.openai_api_key.get_secret_value():
            raise ValueError("실제 공시 검색에는 OPENAI_API_KEY가 필요합니다.")


@lru_cache
def settings() -> Settings:
    return Settings()
