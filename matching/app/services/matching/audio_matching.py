# app/services/matching/audio_matching.py
import uuid
import logging
from typing import Dict, List
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue

from app.services.matching.matching_base import (
    AUDIO_COLLECTION,
    fingerprint_to_vector,
    euclidean_to_hamming,
    count_segments
)

logger = logging.getLogger(__name__)

AUDIO_HAMMING_THRESHOLD = 80


class AudioMatcher:
    def __init__(self, qdrant: QdrantClient):
        self.qdrant = qdrant

    def add_segments(self, item_id: str, audio_segments: list) -> int:
        """Index audio segments for an item. Returns count of indexed segments."""
        if not audio_segments:
            return 0
        
        points = []
        for i, seg in enumerate(audio_segments):
            fp = seg.get("fingerprint", [])
            if fp:
                points.append(PointStruct(
                    id=str(uuid.uuid4()),
                    vector=fingerprint_to_vector(fp),
                    payload={
                        "item_id": item_id,
                        "segment_index": i,
                        "start_time": seg.get("start_time", 0)
                    }
                ))
        
        if points:
            self.qdrant.upsert(collection_name=AUDIO_COLLECTION, points=points)
        
        return len(points)

    def match_segments(self, audio_segments: list) -> Dict[str, float]:
        """
        Match audio segments against indexed items.
        Returns dict of item_id -> match percentage.
        Uses multi-offset alignment to handle middle cuts.
        """
        if not audio_segments:
            return {}
        
        # For each indexed item, collect (query_idx, indexed_idx) pairs
        item_matches: Dict[str, List[tuple]] = {}
        
        for query_idx, seg in enumerate(audio_segments):
            fp = seg.get("fingerprint", [])
            if not fp:
                continue
            
            results = self.qdrant.query_points(
                collection_name=AUDIO_COLLECTION,
                query=fingerprint_to_vector(fp),
                limit=10
            )
            
            for pt in results.points:
                if euclidean_to_hamming(pt.score) <= AUDIO_HAMMING_THRESHOLD:
                    hit_id = pt.payload.get("item_id")
                    indexed_idx = pt.payload.get("segment_index", 0)
                    item_matches.setdefault(hit_id, []).append((query_idx, indexed_idx))
        
        query_count = len([s for s in audio_segments if s.get("fingerprint")])
        if query_count == 0:
            return {}
        
        results = {}
        for hit_id, matches in item_matches.items():
            indexed_count = count_segments(self.qdrant, AUDIO_COLLECTION, hit_id)
            
            # Multi-offset detection: find all significant alignment offsets
            # offset = indexed_idx - query_idx
            offset_counts: Dict[int, set] = {}
            for query_idx, indexed_idx in matches:
                offset = indexed_idx - query_idx
                offset_counts.setdefault(offset, set()).add(query_idx)
            
            # Find significant offsets (at least 3 matches or 10% of query)
            min_matches = max(3, query_count // 10)
            significant_offsets = {
                offset: query_indices
                for offset, query_indices in offset_counts.items()
                if len(query_indices) >= min_matches
            }
            
            if not significant_offsets:
                # Fall back to best single offset if no significant ones
                if offset_counts:
                    best_offset = max(offset_counts.items(), key=lambda x: len(x[1]))
                    significant_offsets = {best_offset[0]: best_offset[1]}
            
            # Combine all matched query segments across significant offsets
            all_matched_queries = set()
            for query_indices in significant_offsets.values():
                all_matched_queries.update(query_indices)
            
            total_matched = len(all_matched_queries)
            
            # Score: matched segments / larger of (query, indexed)
            pct = total_matched / max(query_count, indexed_count) * 100 if max(query_count, indexed_count) > 0 else 0
            results[hit_id] = pct
        
        return results

    def delete_item(self, item_id: str):
        """Delete all audio segments for an item."""
        self.qdrant.delete(
            collection_name=AUDIO_COLLECTION,
            points_selector=Filter(must=[FieldCondition(key="item_id", match=MatchValue(value=item_id))])
        )

    def get_segment_count(self) -> int:
        """Get total number of audio segments indexed."""
        try:
            return self.qdrant.get_collection(AUDIO_COLLECTION).points_count
        except:
            return 0