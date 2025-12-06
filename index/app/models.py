from pydantic import BaseModel


class VideoHash(BaseModel):
    frame_number: int
    quality: int
    timestamp: float
    hex: str


class AudioSegment(BaseModel):
    start_time: float
    duration: float
    fingerprint: list[int]


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class AddItemRequest(BaseModel):
    item_id: str
    item_type: str
    video_hashes: list[VideoHash] | None = None
    audio_segments: list[AudioSegment] | None = None
    transcript_segments: list[TranscriptSegment] | None = None
    transcript_text: str | None = None


class AddItemResponse(BaseModel):
    item_id: str
    indexed: bool
    num_video_hashes: int = 0
    num_audio_segments: int = 0
    num_transcript_segments: int = 0


class MatchRequest(BaseModel):
    query_type: str
    video_hashes: list[VideoHash] | None = None
    audio_segments: list[AudioSegment] | None = None
    transcript_segments: list[TranscriptSegment] | None = None


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