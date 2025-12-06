from fastapi import FastAPI, UploadFile, File, HTTPException, Query
import hashlib
import os
import logging

from app.config import settings
from app.models import HashResponse, MatchResult, DeleteResponse, ResetResponse, StatsResponse
from app.services.hashing import HashingService
from app.services.transcript import TranscriptService
from app.services.index_client import IndexClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Media Hashing API")
index_client = IndexClient()

# Init transcript service
if settings.openai_api_key:
    TranscriptService.init_openai(settings.openai_api_key)


def compute_file_hash(file_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/hash", response_model=HashResponse)
async def hash_media(file: UploadFile = File(...), language: str = Query(None)):
    filename = file.filename or "unknown"
    tmp_path = f"/tmp/{filename}"

    logger.info(f"Hash request: {filename}")

    try:
        with open(tmp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        item_id = compute_file_hash(tmp_path)
        media_type = HashingService.detect_type(tmp_path)

        if media_type == "unknown":
            raise HTTPException(status_code=400, detail="Unknown media type")

        video_hashes = []
        audio_segments = []
        transcript_segments = []
        transcript_text = None

        if media_type == "video":
            video_hashes = HashingService.compute_video_hashes(tmp_path)
            if not video_hashes:
                raise HTTPException(status_code=400, detail="Could not extract video hashes")
            audio_segments = HashingService.compute_audio_fingerprints(tmp_path)
            if not audio_segments:
                raise HTTPException(status_code=400, detail="Could not extract audio fingerprints")
            result = TranscriptService.transcribe(tmp_path, language)
            if result:
                transcript_segments = result["segments"]
                transcript_text = result["full_text"]

        elif media_type == "audio":
            audio_segments = HashingService.compute_audio_fingerprints(tmp_path)
            if not audio_segments:
                raise HTTPException(status_code=400, detail="Could not extract audio fingerprints")
            result = TranscriptService.transcribe(tmp_path, language)
            if result:
                transcript_segments = result["segments"]
                transcript_text = result["full_text"]

        elif media_type == "image":
            video_hashes = HashingService.compute_video_hashes(tmp_path, is_image=True)
            if not video_hashes:
                raise HTTPException(status_code=400, detail="Could not extract image hash")

        # Send to index via queue
        index_result = index_client.add_item(
            item_id=item_id,
            item_type=media_type,
            video_hashes=video_hashes or None,
            audio_segments=audio_segments or None,
            transcript_segments=transcript_segments or None,
            transcript_text=transcript_text
        )

        return HashResponse(
            item_id=item_id,
            type=media_type,
            indexed=index_result["indexed"],
            num_video_hashes=index_result["num_video_hashes"],
            num_audio_segments=index_result["num_audio_segments"],
            num_transcript_segments=index_result["num_transcript_segments"],
            transcript_text=transcript_text
        )

    except HTTPException:
        raise
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        logger.error(f"Hash failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.post("/match", response_model=list[MatchResult])
async def match_media(
    file: UploadFile = File(...),
    image_threshold: float = Query(None, ge=0.0, le=1.0),
    video_threshold: float = Query(None, ge=0.0, le=1.0),
    audio_threshold: float = Query(None, ge=0.0, le=1.0),
    transcript_threshold: float = Query(None, ge=0.0, le=1.0),
    image_hamming_distance: int = Query(None, ge=0, le=256),
    video_hamming_distance: int = Query(None, ge=0, le=256),
    audio_hamming_distance: int = Query(None, ge=0, le=256)
):
    filename = file.filename or "unknown"
    tmp_path = f"/tmp/{filename}"

    logger.info(f"Match request: {filename}")

    try:
        with open(tmp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        media_type = HashingService.detect_type(tmp_path)
        if media_type == "unknown":
            raise HTTPException(status_code=400, detail="Unknown media type")

        video_hashes = []
        audio_segments = []
        transcript_segments = []

        if media_type == "video":
            video_hashes = HashingService.compute_video_hashes(tmp_path)
            audio_segments = HashingService.compute_audio_fingerprints(tmp_path)
            result = TranscriptService.transcribe(tmp_path)
            if result:
                transcript_segments = result["segments"]

        elif media_type == "audio":
            audio_segments = HashingService.compute_audio_fingerprints(tmp_path)
            result = TranscriptService.transcribe(tmp_path)
            if result:
                transcript_segments = result["segments"]

        elif media_type == "image":
            video_hashes = HashingService.compute_video_hashes(tmp_path, is_image=True)

        # Match via queue
        results = index_client.match(
            query_type=media_type,
            video_hashes=video_hashes or None,
            audio_segments=audio_segments or None,
            transcript_segments=transcript_segments or None,
            image_threshold=image_threshold,
            video_threshold=video_threshold,
            audio_threshold=audio_threshold,
            transcript_threshold=transcript_threshold,
            image_hamming_distance=image_hamming_distance,
            video_hamming_distance=video_hamming_distance,
            audio_hamming_distance=audio_hamming_distance
        )

        return [MatchResult(**r) for r in results]

    except HTTPException:
        raise
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        logger.error(f"Match failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.delete("/delete/{item_id}", response_model=DeleteResponse)
async def delete_item(item_id: str):
    try:
        deleted = index_client.delete(item_id)
        return DeleteResponse(item_id=item_id, deleted=deleted)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reset", response_model=ResetResponse)
async def reset_index():
    try:
        count = index_client.reset()
        return ResetResponse(cleared=count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    try:
        stats = index_client.stats()
        return StatsResponse(**stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))