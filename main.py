from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from contextlib import asynccontextmanager
import hashlib
import os
import logging

from config import settings
from models import HashResponse, MatchResult, DeleteResponse, ResetResponse
from hashing.hashing_service import HashingService
from hashing.transcript_service import TranscriptService
from matching.matching_service import MatchingService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

matching_index = MatchingService()


def compute_file_hash(file_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.openai_api_key:
        TranscriptService.init_openai(settings.openai_api_key)
        logger.info("OpenAI client initialized")
    else:
        raise RuntimeError("OPENAI_API_KEY required")
    yield
    logger.info("Shutting down")


app = FastAPI(title="Media Matching API", lifespan=lifespan)


@app.post("/hash", response_model=HashResponse)
async def hash_media(
    file: UploadFile = File(...),
    language: str = Query(None)
):
    filename = file.filename or "unknown"
    tmp_path = f"/tmp/{filename}"
    logger.info(f"Hash request: {filename}")
    
    try:
        with open(tmp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        file_size = len(content)
        logger.info(f"Saved {filename} ({file_size} bytes)")
        
        item_id = compute_file_hash(tmp_path)
        
        if item_id in matching_index.items:
            logger.info(f"Item {item_id[:12]}... already indexed")
            return HashResponse(
                item_id=item_id,
                type=matching_index.items[item_id]["type"],
                num_video_hashes=matching_index.items[item_id].get("num_video_hashes", 0),
                num_audio_segments=matching_index.items[item_id].get("num_audio_segments", 0),
                num_transcript_segments=matching_index.items[item_id].get("num_transcript_segments", 0),
                transcript_text=matching_index.items[item_id].get("transcript_text")
            )
        
        media_type = MediaService.detect_type(tmp_path)
        logger.info(f"Detected media type: {media_type}")
        
        if media_type == "unknown":
            raise HTTPException(status_code=400, detail="Unknown media type")
        
        video_hashes = []
        audio_segments = []
        transcript_segments = []
        transcript_text = None
        
        if media_type == "video":
            video_hashes = MediaService.compute_video_hashes(tmp_path, is_image=False)
            if not video_hashes:
                raise HTTPException(status_code=400, detail="Could not extract video hashes")
            
            audio_segments = MediaService.compute_audio_fingerprints(tmp_path)
            if not audio_segments:
                raise HTTPException(status_code=400, detail="Could not extract audio fingerprints")
            
            result = TranscriptService.transcribe(tmp_path, language)
            if not result:
                raise HTTPException(status_code=400, detail="Could not transcribe audio")
            transcript_segments = result["segments"]
            transcript_text = result["full_text"]
        
        elif media_type == "audio":
            audio_segments = MediaService.compute_audio_fingerprints(tmp_path)
            if not audio_segments:
                raise HTTPException(status_code=400, detail="Could not extract audio fingerprints")
            
            result = TranscriptService.transcribe(tmp_path, language)
            if not result:
                raise HTTPException(status_code=400, detail="Could not transcribe audio")
            transcript_segments = result["segments"]
            transcript_text = result["full_text"]
        
        elif media_type == "image":
            video_hashes = MediaService.compute_video_hashes(tmp_path, is_image=True)
            if not video_hashes:
                raise HTTPException(status_code=400, detail="Could not extract image hash")
        
        matching_index.add_item(
            item_id=item_id,
            item_type=media_type,
            video_hashes=video_hashes or None,
            audio_segments=audio_segments or None,
            transcript_segments=transcript_segments or None,
            transcript_text=transcript_text
        )
        
        logger.info(f"Hash complete: {filename} -> {item_id[:12]}...")
        
        return HashResponse(
            item_id=item_id,
            type=media_type,
            num_video_hashes=len(video_hashes),
            num_audio_segments=len(audio_segments),
            num_transcript_segments=len(transcript_segments),
            transcript_text=transcript_text
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Hash failed for {filename}: {e}")
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
        
        file_size = len(content)
        logger.info(f"Saved {filename} ({file_size} bytes)")
        
        media_type = MediaService.detect_type(tmp_path)
        logger.info(f"Detected media type: {media_type}")
        
        if media_type == "unknown":
            raise HTTPException(status_code=400, detail="Unknown media type")
        
        video_hashes = []
        audio_segments = []
        transcript_segments = []
        
        if media_type == "video":
            video_hashes = MediaService.compute_video_hashes(tmp_path, is_image=False)
            if not video_hashes:
                raise HTTPException(status_code=400, detail="Could not extract video hashes")
            
            audio_segments = MediaService.compute_audio_fingerprints(tmp_path)
            if not audio_segments:
                raise HTTPException(status_code=400, detail="Could not extract audio fingerprints")
            
            result = TranscriptService.transcribe(tmp_path)
            if not result:
                raise HTTPException(status_code=400, detail="Could not transcribe audio")
            transcript_segments = result["segments"]
        
        elif media_type == "audio":
            audio_segments = MediaService.compute_audio_fingerprints(tmp_path)
            if not audio_segments:
                raise HTTPException(status_code=400, detail="Could not extract audio fingerprints")
            
            result = TranscriptService.transcribe(tmp_path)
            if not result:
                raise HTTPException(status_code=400, detail="Could not transcribe audio")
            transcript_segments = result["segments"]
        
        elif media_type == "image":
            video_hashes = MediaService.compute_video_hashes(tmp_path, is_image=True)
            if not video_hashes:
                raise HTTPException(status_code=400, detail="Could not extract image hash")
        
        i_hamming = image_hamming_distance if image_hamming_distance is not None else settings.image_hamming_distance
        v_hamming = video_hamming_distance if video_hamming_distance is not None else settings.video_hamming_distance
        a_hamming = audio_hamming_distance if audio_hamming_distance is not None else settings.audio_hamming_distance
        logger.info(f"Matching {filename} with image_hamming={i_hamming}, video_hamming={v_hamming}, audio_hamming={a_hamming}")
        
        results = matching_index.match(
            query_type=media_type,
            video_hashes=video_hashes or None,
            audio_segments=audio_segments or None,
            transcript_segments=transcript_segments or None,
            image_threshold=image_threshold if image_threshold is not None else settings.image_threshold,
            video_threshold=video_threshold if video_threshold is not None else settings.video_threshold,
            audio_threshold=audio_threshold if audio_threshold is not None else settings.audio_threshold,
            transcript_threshold=transcript_threshold if transcript_threshold is not None else settings.transcript_threshold,
            image_hamming_distance=i_hamming,
            video_hamming_distance=v_hamming,
            audio_hamming_distance=a_hamming
        )
        
        logger.info(f"Match complete for {filename}: {len(results)} result(s)")
        
        return [MatchResult(**r) for r in results]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Match failed for {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.delete("/delete/{item_id}", response_model=DeleteResponse)
async def delete_item(item_id: str):
    logger.info(f"Delete request: {item_id[:12]}...")
    deleted = matching_index.delete(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")
    logger.info(f"Deleted: {item_id[:12]}...")
    return DeleteResponse(item_id=item_id, deleted=True)


@app.post("/reset", response_model=ResetResponse)
async def reset_index():
    logger.info("Reset request")
    count = matching_index.reset()
    logger.info(f"Reset complete: {count} items cleared")
    return ResetResponse(status="cleared", items_cleared=count)


@app.get("/stats")
async def get_stats():
    logger.info("Stats request")
    return matching_index.stats()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "defaults": {
            "image_threshold": settings.image_threshold,
            "video_threshold": settings.video_threshold,
            "audio_threshold": settings.audio_threshold,
            "transcript_threshold": settings.transcript_threshold,
            "image_hamming_distance": settings.image_hamming_distance,
            "video_hamming_distance": settings.video_hamming_distance,
            "audio_hamming_distance": settings.audio_hamming_distance,
            "shingle_size": settings.shingle_size,
            "lsh_threshold": settings.lsh_threshold
        }
    }