# app/services/matching/image_matching.py
import uuid
import logging
from typing import Dict
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue

from app.services.matching.matching_base import (
    IMAGE_COLLECTION,
    hash_to_vector,
    euclidean_to_hamming
)

logger = logging.getLogger(__name__)


class ImageMatcher:
    def __init__(self, qdrant: QdrantClient):
        self.qdrant = qdrant

    def add_hash(self, item_id: str, video_hashes: list) -> int:
        """Index image hash for an item. Returns count of indexed hashes (0 or 1)."""
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
            self.qdrant.upsert(collection_name=IMAGE_COLLECTION, points=points)
        
        return len(points)

    def match_hash(self, video_hashes: list, hamming_threshold: int) -> Dict[str, float]:
        """
        Match image hash against indexed items.
        Returns dict of item_id -> match percentage (based on hamming distance).
        
        Args:
            video_hashes: List of image hashes to match
            hamming_threshold: Maximum hamming distance to consider a match
        """
        if not video_hashes:
            return {}
        
        # For images: find best (lowest) hamming distance per item
        best_matches: Dict[str, int] = {}
        
        for h in video_hashes:
            hex_val = h.get("hex", h) if isinstance(h, dict) else h
            if not hex_val or len(str(hex_val)) != 64:
                continue
            
            results = self.qdrant.query_points(
                collection_name=IMAGE_COLLECTION,
                query=hash_to_vector(str(hex_val)),
                limit=10
            )
            
            for pt in results.points:
                hit_id = pt.payload.get("item_id")
                ham_dist = euclidean_to_hamming(pt.score)
                if ham_dist <= hamming_threshold:
                    if hit_id not in best_matches or ham_dist < best_matches[hit_id]:
                        best_matches[hit_id] = ham_dist
        
        # Convert hamming distance to percentage (256 bits total)
        results = {}
        for hit_id, ham_dist in best_matches.items():
            pct = (256 - ham_dist) / 256 * 100
            results[hit_id] = pct
        
        return results

    def delete_item(self, item_id: str):
        """Delete image hash for an item."""
        self.qdrant.delete(
            collection_name=IMAGE_COLLECTION,
            points_selector=Filter(must=[FieldCondition(key="item_id", match=MatchValue(value=item_id))])
        )

    def get_hash_count(self) -> int:
        """Get total number of image hashes indexed."""
        try:
            return self.qdrant.get_collection(IMAGE_COLLECTION).points_count
        except:
            return 0