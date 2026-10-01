from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    agent_provider: str = "qwen"
    openai_api_key: str = ""
    openai_model: str = "gpt-6-astra"
    openai_base_url: str = ""
    dashscope_api_key: str = ""
    qwen_model: str = "qwen-plus"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    agent_data_dir: str = "data"
    enable_unpublished_homework_scenario: bool = False
    enable_scenario_fixtures: bool = False
    backend_host: str = "127.0.0.1"
    backend_port: int = 8421


@lru_cache
def get_settings() -> Settings:
    return Settings()
