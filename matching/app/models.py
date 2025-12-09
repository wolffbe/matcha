# app/models.py
from pydantic import BaseModel


class HashResponse(BaseModel):
    item_id: str
    type: str
    indexed: bool
    num_video_hashes: int = 0
    num_audio_segments: int = 0
    has_transcript: bool = False


class MatchResult(BaseModel):
    item_id: str
    status: str  # "exact_match" or "near_match"
    image_match_percent: float | None = None
    video_match_percent: float | None = None
    audio_match_percent: float | None = None
    transcript_match_percent: float | None = None


class DeleteResponse(BaseModel):
    item_id: str
    deleted: bool


class ResetResponse(BaseModel):
    reset: bool


class StatsResponse(BaseModel):
    total_video_hashes: int = 0
    total_audio_segments: int = 0
    total_image_hashes: int = 0
    total_transcripts: int = 0