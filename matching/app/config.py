# app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    
    # Per-type thresholds (0-1)
    image_threshold: float = 0.90
    video_threshold: float = 0.85
    audio_threshold: float = 0.85
    transcript_threshold: float = 0.85
    
    # Per-type offsets (0-0.5)
    image_offset: float = 0.0125
    video_offset: float = 0
    audio_offset: float = 0.02
    transcript_offset: float = 0.05
    
    # Video max hamming distance (for 256-bit PDQ hashes)
    # Hamming 32 ≈ 87.5% threshold
    video_max_hamming: int = 32
    
    class Config:
        env_file = ".env"


settings = Settings()