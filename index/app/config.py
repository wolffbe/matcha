from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    request_queue: str = "index_requests"
    result_queue_prefix: str = "results_"
    
    image_threshold: float = 0.90
    video_threshold: float = 0.85
    audio_threshold: float = 0.85
    transcript_threshold: float = 0.85
    image_hamming_distance: int = 27
    video_hamming_distance: int = 27
    audio_hamming_distance: int = 60

    class Config:
        env_file = ".env"


settings = Settings()