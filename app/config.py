from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "E-Commerce Market Analysis Agent"
    app_version: str = "1.0.0"
    debug: bool = False

    # LLM — optional. When absent, the system uses deterministic fallback synthesis.
    groq_api_key: str | None = None
    llm_model: str = "llama-3.3-70b-versatile"
    llm_max_tokens: int = 1024
    llm_timeout: float = 30.0

    # Orchestrator behavior
    tool_timeout: float = 10.0
    max_retries: int = 2

    @property
    def llm_available(self) -> bool:
        return bool(self.groq_api_key)


# Singleton — imported everywhere
settings = Settings()
