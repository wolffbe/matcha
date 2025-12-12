# app/routes.py
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
import hashlib
import os
import uuid
import logging

from app.config import settings
from app.models import HashResponse, MatchResult, DeleteResponse, ResetResponse, StatsResponse
from app.services.hashing import HashingService
from app.services.matching.matching import MatchingService
from app.services.transcript import TranscriptService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Media Matching API")
hashing_service = HashingService()
matching_service = MatchingService()
transcript_service = TranscriptService()


def compute_file_hash(file_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


@app.get("/health")
async def health():
    return {"status": "ok", **matching_service.get_stats()}


@app.post("/hash", response_model=HashResponse)
async def hash_media(
    file: UploadFile = File(...),
    language: str = Query(None),
    skip_transcript: bool = Query(False, description="Skip transcription for audio/video")
):
    filename = file.filename or "unknown"
    tmp_path = f"/tmp/{uuid.uuid4()}_{filename}"
    logger.info(f"Hash request: {filename}")

    try:
        with open(tmp_path, "wb") as f:
            f.write(await file.read())

        item_id = compute_file_hash(tmp_path)
        media_type = hashing_service.detect_type(tmp_path)

        if media_type == "unknown":
            raise HTTPException(status_code=400, detail="Unknown media type")

        video_hashes = []
        audio_segments = []
        transcript_text = None

        if media_type == "video":
            video_hashes = hashing_service.compute_video_hashes(tmp_path)
            audio_segments = hashing_service.compute_audio_fingerprints(tmp_path)
            if not skip_transcript:
                transcript_text = transcript_service.transcribe(tmp_path, language)
        elif media_type == "audio":
            audio_segments = hashing_service.compute_audio_fingerprints(tmp_path)
            if not skip_transcript:
                transcript_text = transcript_service.transcribe(tmp_path, language)
        elif media_type == "image":
            video_hashes = hashing_service.compute_video_hashes(tmp_path, is_image=True)

        matching_service.add_item(
            item_id=item_id,
            item_type=media_type,
            video_hashes=video_hashes or None,
            audio_segments=audio_segments or None,
            transcript_text=transcript_text
        )

        return HashResponse(
            item_id=item_id,
            type=media_type,
            indexed=True,
            num_video_hashes=len(video_hashes),
            num_audio_segments=len(audio_segments),
            has_transcript=transcript_text is not None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Hash failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.post("/match", response_model=list[MatchResult])
async def match_media(
    file: UploadFile = File(...),
    language: str = Query(None),
    skip_transcript: bool = Query(False, description="Skip transcription for audio/video"),
    # Per-type thresholds
    image_threshold: float = Query(None, ge=0.0, le=1.0, description="Image match threshold (0-1)"),
    video_threshold: float = Query(None, ge=0.0, le=1.0, description="Video match threshold (0-1)"),
    audio_threshold: float = Query(None, ge=0.0, le=1.0, description="Audio match threshold (0-1)"),
    transcript_threshold: float = Query(None, ge=0.0, le=1.0, description="Transcript match threshold (0-1)"),
    # Per-type offsets
    image_offset: float = Query(None, ge=0.0, le=0.5, description="Image offset for near_match (0-0.5)"),
    video_offset: float = Query(None, ge=0.0, le=0.5, description="Video offset for near_match (0-0.5)"),
    audio_offset: float = Query(None, ge=0.0, le=0.5, description="Audio offset for near_match (0-0.5)"),
    transcript_offset: float = Query(None, ge=0.0, le=0.5, description="Transcript offset for near_match (0-0.5)")
):
    filename = file.filename or "unknown"
    tmp_path = f"/tmp/{uuid.uuid4()}_{filename}"
    logger.info(f"Match request: {filename}")

    try:
        with open(tmp_path, "wb") as f:
            f.write(await file.read())

        media_type = hashing_service.detect_type(tmp_path)
        if media_type == "unknown":
            raise HTTPException(status_code=400, detail="Unknown media type")

        video_hashes = []
        audio_segments = []
        transcript_text = None

        if media_type == "video":
            video_hashes = hashing_service.compute_video_hashes(tmp_path)
            audio_segments = hashing_service.compute_audio_fingerprints(tmp_path)
            if not skip_transcript:
                transcript_text = transcript_service.transcribe(tmp_path, language)
        elif media_type == "audio":
            audio_segments = hashing_service.compute_audio_fingerprints(tmp_path)
            if not skip_transcript:
                transcript_text = transcript_service.transcribe(tmp_path, language)
        elif media_type == "image":
            video_hashes = hashing_service.compute_video_hashes(tmp_path, is_image=True)

        results = matching_service.match_item(
            item_type=media_type,
            video_hashes=video_hashes or None,
            audio_segments=audio_segments or None,
            transcript_text=transcript_text,
            image_threshold=image_threshold,
            video_threshold=video_threshold,
            audio_threshold=audio_threshold,
            transcript_threshold=transcript_threshold,
            image_offset=image_offset,
            video_offset=video_offset,
            audio_offset=audio_offset,
            transcript_offset=transcript_offset
        )

        return [MatchResult(**r) for r in results]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Match failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.delete("/delete/{item_id}", response_model=DeleteResponse)
async def delete_item(item_id: str):
    logger.info(f"Delete request: {item_id[:12]}...")
    try:
        matching_service.delete_item(item_id)
        return DeleteResponse(item_id=item_id, deleted=True)
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reset", response_model=ResetResponse)
async def reset_index():
    logger.info("Reset request")
    try:
        matching_service.reset()
        return ResetResponse(reset=True)
    except Exception as e:
        logger.error(f"Reset failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    return StatsResponse(**matching_service.get_stats())