from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # OpenAI API key for transcription
    openai_api_key: str = ""
    
    # Match thresholds (minimum match percentage to include in results)
    # With distance-based matching: threshold 0.0 = accept any distance up to max
    # Formula: match_pct = (1 - distance/max_distance) * 100
    # Example with max_distance=31: threshold 0.5 accepts distance ≤ 15
    image_threshold: float = 0.9
    video_threshold: float = 0.85
    audio_threshold: float = 0.85
    transcript_threshold: float = 0.85
    
    # Hamming distance thresholds (0-256 bits, lower = stricter)
    # These determine the maximum distance to consider as a potential match
    # PDQ image hashes: typically 0-31 for near-duplicates
    image_hamming_distance: int = 28
    # PDQ video frame hashes: typically 0-31 for near-duplicates
    video_hamming_distance: int = 28
    # Chromaprint audio: may need higher threshold (more variance in audio encoding)
    audio_hamming_distance: int = 60
    
    # MinHash LSH settings for transcript matching
    shingle_size: int = 3
    lsh_threshold: float = 0.5
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()