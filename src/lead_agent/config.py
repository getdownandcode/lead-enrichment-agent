"""Configuration loaded once from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    tavily_api_key: str | None = None
    max_pages: int = 6
    request_timeout_seconds: float = 20.0
    max_page_text_chars: int = 7000
