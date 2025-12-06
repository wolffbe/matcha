from pydantic import BaseModel


class HashResponse(BaseModel):
    item_id: str
    type: str
    indexed: bool
    num_video_hashes: int = 0
    num_audio_segments: int = 0
    num_transcript_segments: int = 0
    transcript_text: str | None = None


class MatchResult(BaseModel):
    item_id: str
    status: str
    image_match_percent: float | None = None
    video_match_percent: float | None = None
    audio_match_percent: float | None = None
    transcript_match_percent: float | None = None
    image_hamming_distance: int | None = None
    video_hamming_distance: int | None = None
    audio_hamming_distance: int | None = None


class DeleteResponse(BaseModel):
    item_id: str
    deleted: bool


class ResetResponse(BaseModel):
    cleared: int


class StatsResponse(BaseModel):
    total_items: int
    total_video_hashes: int
    total_audio_segments: int
    total_transcript_segments: int