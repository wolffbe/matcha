from pydantic import BaseModel
from typing import Optional, Literal


class HashResponse(BaseModel):
    item_id: str
    type: str
    num_video_hashes: int = 0
    num_audio_segments: int = 0
    num_transcript_segments: int = 0
    transcript_text: Optional[str] = None


class MatchResult(BaseModel):
    item_id: str
    status: Literal["exact_match", "near_match", "no_match"]
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
    status: str
    items_cleared: int