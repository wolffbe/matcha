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


def validate_threshold_offset(threshold: float, offset: float, name: str):
    """Validate that threshold - offset stays within 0-1 range."""
    effective = threshold - offset
    if effective < 0.0:
        raise HTTPException(
            status_code=400, 
            detail=f"{name} effective threshold ({threshold} - {offset} = {effective}) cannot be negative"
        )
    if effective > 1.0:
        raise HTTPException(
            status_code=400, 
            detail=f"{name} effective threshold ({threshold} - {offset} = {effective}) cannot exceed 1.0"
        )


@app.get("/health")
async def health():
    return {"status": "ok", **matching_service.get_stats()}


@app.post("/hash", response_model=HashResponse)
async def hash_media(
    file: UploadFile = File(...),
    language: str = Query(None),
    skip_transcript: bool = Query(False, description="Skip transcription for audio/video"),
    project: str = Query(None, description="Project name to group hashes")
):
    filename = file.filename or "unknown"
    tmp_path = f"/tmp/{uuid.uuid4()}_{filename}"
    logger.info(f"Hash request: {filename}" + (f" [project={project}]" if project else ""))

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
            if hashing_service.has_audio_stream(tmp_path):
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
            transcript_text=transcript_text,
            project=project
        )

        return HashResponse(
            item_id=item_id,
            type=media_type,
            indexed=True,
            num_video_hashes=len(video_hashes),
            num_audio_segments=len(audio_segments),
            has_transcript=transcript_text is not None,
            project=project
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
    project: str = Query(None, description="Project name to match against"),
    # Per-type thresholds
    image_threshold: float = Query(None, ge=0.0, le=1.0, description="Image match threshold (0-1)"),
    video_threshold: float = Query(None, ge=0.0, le=1.0, description="Video match threshold (0-1)"),
    audio_threshold: float = Query(None, ge=0.0, le=1.0, description="Audio match threshold (0-1)"),
    transcript_threshold: float = Query(None, ge=0.0, le=1.0, description="Transcript match threshold (0-1)"),
    # Per-type offsets (can be negative)
    image_offset: float = Query(None, ge=-1.0, le=1.0, description="Image offset for near_match (-1 to 1)"),
    video_offset: float = Query(None, ge=-1.0, le=1.0, description="Video offset for near_match (-1 to 1)"),
    audio_offset: float = Query(None, ge=-1.0, le=1.0, description="Audio offset for near_match (-1 to 1)"),
    transcript_offset: float = Query(None, ge=-1.0, le=1.0, description="Transcript offset for near_match (-1 to 1)"),
    # Video frame hamming distance (256-bit VPDQ/PDQ hashes)
    video_max_hamming: int = Query(None, ge=0, le=256, description="Direct hamming threshold for 256-bit video hash (0-256)")
):
    filename = file.filename or "unknown"
    tmp_path = f"/tmp/{uuid.uuid4()}_{filename}"
    logger.info(f"Match request: {filename}" + (f" [project={project}]" if project else ""))

    try:
        with open(tmp_path, "wb") as f:
            f.write(await file.read())

        media_type = hashing_service.detect_type(tmp_path)
        if media_type == "unknown":
            raise HTTPException(status_code=400, detail="Unknown media type")

        # Use config defaults and validate effective thresholds
        img_thresh = image_threshold if image_threshold is not None else settings.image_threshold
        img_off = image_offset if image_offset is not None else settings.image_offset
        validate_threshold_offset(img_thresh, img_off, "image")
        
        vid_thresh = video_threshold if video_threshold is not None else settings.video_threshold
        vid_off = video_offset if video_offset is not None else settings.video_offset
        validate_threshold_offset(vid_thresh, vid_off, "video")
        
        aud_thresh = audio_threshold if audio_threshold is not None else settings.audio_threshold
        aud_off = audio_offset if audio_offset is not None else settings.audio_offset
        validate_threshold_offset(aud_thresh, aud_off, "audio")
        
        trans_thresh = transcript_threshold if transcript_threshold is not None else settings.transcript_threshold
        trans_off = transcript_offset if transcript_offset is not None else settings.transcript_offset
        validate_threshold_offset(trans_thresh, trans_off, "transcript")
        
        # Apply config default for video_max_hamming
        vid_max_ham = video_max_hamming if video_max_hamming is not None else settings.video_max_hamming

        video_hashes = []
        audio_segments = []
        transcript_text = None

        if media_type == "video":
            video_hashes = hashing_service.compute_video_hashes(tmp_path)
            if hashing_service.has_audio_stream(tmp_path):
                audio_segments = hashing_service.compute_audio_fingerprints(tmp_path)
                if not skip_transcript:
                    transcript_text = transcript_service.transcribe(tmp_path, language)
        elif media_type == "audio":
            audio_segments = hashing_service.compute_audio_fingerprints(tmp_path)
            if not skip_transcript:
                transcript_text = transcript_service.transcribe(tmp_path, language)
        elif media_type == "image":
            video_hashes = hashing_service.compute_video_hashes(tmp_path, is_image=True)

        # Compute query file hash for exact_match detection
        query_item_id = compute_file_hash(tmp_path)

        results = matching_service.match_item(
            item_type=media_type,
            video_hashes=video_hashes or None,
            audio_segments=audio_segments or None,
            transcript_text=transcript_text,
            image_threshold=img_thresh,
            video_threshold=vid_thresh,
            audio_threshold=aud_thresh,
            transcript_threshold=trans_thresh,
            image_offset=img_off,
            video_offset=vid_off,
            audio_offset=aud_off,
            transcript_offset=trans_off,
            video_max_hamming=vid_max_ham,
            project=project,
            query_item_id=query_item_id
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
async def delete_item(item_id: str, project: str = Query(None, description="Project name")):
    logger.info(f"Delete request: {item_id[:12]}..." + (f" [project={project}]" if project else ""))
    try:
        matching_service.delete_item(item_id, project=project)
        return DeleteResponse(item_id=item_id, deleted=True, project=project)
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reset", response_model=ResetResponse)
async def reset_index(project: str = Query(None, description="Project name to reset (None = default project)")):
    logger.info(f"Reset request" + (f" [project={project}]" if project else " [default]"))
    try:
        matching_service.reset(project=project)
        return ResetResponse(reset=True, project=project)
    except Exception as e:
        logger.error(f"Reset failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", response_model=StatsResponse)
async def get_stats(project: str = Query(None, description="Project name to get stats for")):
    return StatsResponse(**matching_service.get_stats(project=project))