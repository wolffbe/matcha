from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    redis_url: str = "redis://localhost:6379"
    request_queue: str = "index_requests"
    result_queue_prefix: str = "results_"
    request_timeout: int = 120

    class Config:
        env_file = ".env"


settings = Settings()