# hashing/app/models.py
from pydantic import BaseModel
from typing import Optional


class HashResponse(BaseModel):
    item_id: str
    type: str
    indexed: bool
    num_video_hashes: int = 0
    num_audio_segments: int = 0
    num_transcript_segments: int = 0
    transcript_text: Optional[str] = None


class MatchResult(BaseModel):
    item_id: str
    status: str
    image_match_percent: Optional[float] = None
    video_match_percent: Optional[float] = None
    audio_match_percent: Optional[float] = None
    transcript_match_percent: Optional[float] = None
    image_hamming_distance: Optional[int] = None
    video_hamming_distance: Optional[int] = None
    audio_hamming_distance: Optional[int] = None


class DeleteResponse(BaseModel):
    item_id: str
    deleted: bool


class ResetResponse(BaseModel):
    reset: bool


class StatsResponse(BaseModel):
    total_items: int = 0
    total_video_hashes: int = 0
    total_audio_segments: int = 0
    total_image_hashes: int = 0
    total_transcript_segments: int = 0