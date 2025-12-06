from fastapi import FastAPI, HTTPException, Query
import logging

from app.config import settings
from app.models import (
    AddItemRequest, AddItemResponse,
    MatchRequest, MatchResult,
    DeleteResponse, ResetResponse, StatsResponse
)
from app.services.index import IndexService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Media Index API")
index_service = IndexService()


@app.get("/health")
async def health():
    return {"status": "ok", "items": len(index_service.items)}


@app.post("/add", response_model=AddItemResponse)
async def add_item(request: AddItemRequest):
    logger.info(f"Add request: {request.item_id[:12]}... type={request.item_type}")

    try:
        result = index_service.add_item(
            item_id=request.item_id,
            item_type=request.item_type,
            video_hashes=[vh.model_dump() for vh in request.video_hashes] if request.video_hashes else None,
            audio_segments=[seg.model_dump() for seg in request.audio_segments] if request.audio_segments else None,
            transcript_segments=[seg.model_dump() for seg in request.transcript_segments] if request.transcript_segments else None,
            transcript_text=request.transcript_text
        )
        return AddItemResponse(**result)
    except Exception as e:
        logger.error(f"Add failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/match", response_model=list[MatchResult])
async def match_item(
    request: MatchRequest,
    image_threshold: float = Query(None, ge=0.0, le=1.0),
    video_threshold: float = Query(None, ge=0.0, le=1.0),
    audio_threshold: float = Query(None, ge=0.0, le=1.0),
    transcript_threshold: float = Query(None, ge=0.0, le=1.0),
    image_hamming_distance: int = Query(None, ge=0, le=256),
    video_hamming_distance: int = Query(None, ge=0, le=256),
    audio_hamming_distance: int = Query(None, ge=0, le=256)
):
    logger.info(f"Match request: type={request.query_type}")

    try:
        results = index_service.match(
            query_type=request.query_type,
            video_hashes=[vh.model_dump() for vh in request.video_hashes] if request.video_hashes else None,
            audio_segments=[seg.model_dump() for seg in request.audio_segments] if request.audio_segments else None,
            transcript_segments=[seg.model_dump() for seg in request.transcript_segments] if request.transcript_segments else None,
            image_threshold=image_threshold if image_threshold is not None else settings.image_threshold,
            video_threshold=video_threshold if video_threshold is not None else settings.video_threshold,
            audio_threshold=audio_threshold if audio_threshold is not None else settings.audio_threshold,
            transcript_threshold=transcript_threshold if transcript_threshold is not None else settings.transcript_threshold,
            image_hamming_distance=image_hamming_distance if image_hamming_distance is not None else settings.image_hamming_distance,
            video_hamming_distance=video_hamming_distance if video_hamming_distance is not None else settings.video_hamming_distance,
            audio_hamming_distance=audio_hamming_distance if audio_hamming_distance is not None else settings.audio_hamming_distance
        )
        return [MatchResult(**r) for r in results]
    except Exception as e:
        logger.error(f"Match failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete/{item_id}", response_model=DeleteResponse)
async def delete_item(item_id: str):
    logger.info(f"Delete request: {item_id[:12]}...")

    if item_id not in index_service.items:
        raise HTTPException(status_code=404, detail="Item not found")

    try:
        deleted = index_service.delete(item_id)
        return DeleteResponse(item_id=item_id, deleted=deleted)
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reset", response_model=ResetResponse)
async def reset_index():
    logger.info("Reset request")

    try:
        count = index_service.reset()
        return ResetResponse(cleared=count)
    except Exception as e:
        logger.error(f"Reset failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    return StatsResponse(**index_service.stats())