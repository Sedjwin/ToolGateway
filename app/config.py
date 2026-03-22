from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8006
    database_url: str = "sqlite+aiosqlite:///./data/toolgateway.db"

    service_key: str = "change-me-service-key"
    admin_key: str = "change-me-admin-key"

    aigateway_url: str = "http://localhost:8001"
    evaluator_endpoint: str = "/gateway/evaluate"
    http_timeout_seconds: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TOOLGATEWAY_",
        extra="ignore",
    )


settings = Settings()
