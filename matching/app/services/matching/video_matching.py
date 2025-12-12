# app/services/matching/video_matching.py
import uuid
import logging
from typing import Dict
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue
from app.services.matching.matching_base import (
    VIDEO_COLLECTION,
    HASH_DIM,
    hash_to_vector,
    euclidean_to_hamming,
    count_segments
)

logger = logging.getLogger(__name__)


class VideoMatcher:
    def __init__(self, qdrant: QdrantClient):
        self.qdrant = qdrant

    def add_hashes(self, item_id: str, video_hashes: list) -> int:
        """Index video frame hashes for an item. Returns count of indexed hashes."""
        if not video_hashes:
            return 0
        
        points = []
        for i, h in enumerate(video_hashes):
            hex_val = h.get("hex", h) if isinstance(h, dict) else h
            if hex_val and len(str(hex_val)) == 64:
                points.append(PointStruct(
                    id=str(uuid.uuid4()),
                    vector=hash_to_vector(str(hex_val)),
                    payload={"item_id": item_id, "frame_index": i}
                ))
        
        if points:
            self.qdrant.upsert(collection_name=VIDEO_COLLECTION, points=points)
        
        return len(points)

    def match_hashes(self, video_hashes: list, threshold: float, offset: float) -> Dict[str, float]:
        """
        Match video frame hashes against indexed items.
        
        threshold and offset control the hamming cutoff:
        - effective_threshold = threshold - offset
        - max_hamming = 256 * (1 - effective_threshold)
        - e.g., threshold=0.85, offset=0.03 → 82% similarity → max 46 bits different
        
        Returns dict of item_id -> match percentage.
        """
        if not video_hashes:
            return {}
        
        # Calculate hamming threshold from API params
        # exact_hamming: for rounding to 100%
        # max_hamming: for filtering results
        if threshold > 0:
            exact_hamming = int(HASH_DIM * (1 - threshold))
        else:
            exact_hamming = -1  # never round to 100%
        
        effective_threshold = threshold - offset
        max_hamming = int(HASH_DIM * (1 - effective_threshold))
        
        logger.info(f"VIDEO MATCH: threshold={threshold}, offset={offset} → "
                   f"exact_hamming={exact_hamming}, max_hamming={max_hamming}")
        
        matched: Dict[str, set] = {}
        total = 0
        
        for idx, h in enumerate(video_hashes):
            hex_val = h.get("hex", h) if isinstance(h, dict) else h
            if not hex_val or len(str(hex_val)) != 64:
                continue
            
            total += 1
            results = self.qdrant.query_points(
                collection_name=VIDEO_COLLECTION,
                query=hash_to_vector(str(hex_val)),
                limit=10
            )
            
            for pt in results.points:
                hit_id = pt.payload.get("item_id")
                hamming = euclidean_to_hamming(pt.score)
                if hamming <= max_hamming:
                    matched.setdefault(hit_id, set()).add(idx)
        
        if total == 0:
            return {}
        
        results = {}
        for hit_id, segs in matched.items():
            indexed = count_segments(self.qdrant, VIDEO_COLLECTION, hit_id)
            matched_count = len(segs)
            max_count = max(total, indexed)
            
            # Calculate raw percentage
            raw_pct = matched_count / max_count * 100 if max_count > 0 else 0
            
            # Round to 100% if within exact threshold
            if raw_pct >= (threshold * 100):
                pct = 100.0
            else:
                pct = raw_pct
            
            logger.info(f"  [{hit_id[:8]}]: matched={matched_count}/{max_count}, score={pct:.1f}%")
            results[hit_id] = pct
        
        return results

    def delete_item(self, item_id: str):
        """Delete all video hashes for an item."""
        self.qdrant.delete(
            collection_name=VIDEO_COLLECTION,
            points_selector=Filter(must=[FieldCondition(key="item_id", match=MatchValue(value=item_id))])
        )

    def get_hash_count(self) -> int:
        """Get total number of video hashes indexed."""
        try:
            return self.qdrant.get_collection(VIDEO_COLLECTION).points_count
        except:
            return 0