# app/services/matching/audio_matching.py
import uuid
import logging
from typing import Dict, List, Set, Tuple
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue, QueryRequest

from app.services.matching.matching_base import (
    AUDIO_COLLECTION,
    fingerprint_to_vector,
    euclidean_to_hamming,
    count_segments,
    build_project_filter,
    get_project_value
)

logger = logging.getLogger(__name__)

AUDIO_HAMMING_THRESHOLD = 80
WINDOW_SIZE = 10  # segments per window (~5 seconds at 0.5s/segment)
WINDOW_STEP = 5   # overlap of 50%
MIN_WINDOW_MATCHES = 3  # minimum matches within a window to count


class AudioMatcher:
    def __init__(self, qdrant: QdrantClient):
        self.qdrant = qdrant

    def add_segments(self, item_id: str, audio_segments: list, project: str = None) -> int:
        """Index audio segments for an item. Returns count of indexed segments."""
        if not audio_segments:
            return 0
        
        project_value = get_project_value(project)
        
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
                        "start_time": seg.get("start_time", 0),
                        "project": project_value
                    }
                ))
        
        if points:
            self.qdrant.upsert(collection_name=AUDIO_COLLECTION, points=points)
        
        return len(points)

    def _offset_based_score(
        self,
        matches: List[Tuple[int, int]],
        query_count: int,
        indexed_count: int
    ) -> Tuple[float, Set[int]]:
        """
        Offset-based alignment: groups matches by temporal offset.
        Best for continuous aligned segments (trims from start/end).
        
        Returns: (match_percentage, set of matched query indices)
        """
        if not matches:
            return 0.0, set()
        
        # Group by offset
        offset_counts: Dict[int, Set[int]] = {}
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
            # Fall back to best single offset
            if offset_counts:
                best_offset = max(offset_counts.items(), key=lambda x: len(x[1]))
                significant_offsets = {best_offset[0]: best_offset[1]}
        
        # Combine all matched query segments
        all_matched_queries: Set[int] = set()
        for query_indices in significant_offsets.values():
            all_matched_queries.update(query_indices)
        
        total_matched = len(all_matched_queries)
        pct = total_matched / max(query_count, indexed_count) * 100 if max(query_count, indexed_count) > 0 else 0
        
        return pct, all_matched_queries

    def _sliding_window_score(
        self,
        matches: List[Tuple[int, int]],
        query_count: int,
        indexed_count: int
    ) -> Tuple[float, Set[int]]:
        """
        Sliding window alignment: finds local alignments within windows.
        Best for discontinuous segments (middle cuts, rearrangements).
        
        Returns: (match_percentage, set of matched query indices)
        """
        if not matches or query_count < WINDOW_SIZE:
            return 0.0, set()
        
        # Build lookup: query_idx -> list of matched indexed_idx
        query_to_indexed: Dict[int, List[int]] = {}
        for query_idx, indexed_idx in matches:
            query_to_indexed.setdefault(query_idx, []).append(indexed_idx)
        
        all_matched_queries: Set[int] = set()
        
        # Slide window across query segments
        for window_start in range(0, query_count - WINDOW_SIZE + 1, WINDOW_STEP):
            window_end = window_start + WINDOW_SIZE
            
            # Get matches within this query window
            window_matches: List[Tuple[int, int]] = []
            for query_idx in range(window_start, window_end):
                if query_idx in query_to_indexed:
                    for indexed_idx in query_to_indexed[query_idx]:
                        window_matches.append((query_idx, indexed_idx))
            
            if len(window_matches) < MIN_WINDOW_MATCHES:
                continue
            
            # Find best offset within this window
            offset_counts: Dict[int, Set[int]] = {}
            for query_idx, indexed_idx in window_matches:
                offset = indexed_idx - query_idx
                offset_counts.setdefault(offset, set()).add(query_idx)
            
            if offset_counts:
                best_offset, best_queries = max(offset_counts.items(), key=lambda x: len(x[1]))
                if len(best_queries) >= MIN_WINDOW_MATCHES:
                    all_matched_queries.update(best_queries)
        
        # Check tail if not covered by full window
        remainder = (query_count - WINDOW_SIZE) % WINDOW_STEP
        if remainder > 0:
            tail_start = query_count - WINDOW_SIZE
            window_matches = []
            for query_idx in range(tail_start, query_count):
                if query_idx in query_to_indexed:
                    for indexed_idx in query_to_indexed[query_idx]:
                        window_matches.append((query_idx, indexed_idx))
            
            if len(window_matches) >= MIN_WINDOW_MATCHES:
                offset_counts = {}
                for query_idx, indexed_idx in window_matches:
                    offset = indexed_idx - query_idx
                    offset_counts.setdefault(offset, set()).add(query_idx)
                
                if offset_counts:
                    best_offset, best_queries = max(offset_counts.items(), key=lambda x: len(x[1]))
                    if len(best_queries) >= MIN_WINDOW_MATCHES:
                        all_matched_queries.update(best_queries)
        
        total_matched = len(all_matched_queries)
        pct = total_matched / max(query_count, indexed_count) * 100 if max(query_count, indexed_count) > 0 else 0
        
        return pct, all_matched_queries

    def _hybrid_score(
        self,
        matches: List[Tuple[int, int]],
        query_count: int,
        indexed_count: int
    ) -> float:
        """
        Hybrid approach: combines offset-based and sliding window alignment.
        
        1. Run offset-based alignment (good for continuous segments)
        2. Run sliding window alignment (good for discontinuous segments)
        3. Take the union of matched segments from both methods
        4. Return the better score
        
        This handles:
        - Trims from start/end (offset-based excels)
        - Middle cuts (sliding window catches both sides)
        - Short audio (offset-based fallback)
        """
        if not matches:
            return 0.0
        
        # Method 1: Offset-based alignment
        offset_pct, offset_matched = self._offset_based_score(matches, query_count, indexed_count)
        
        # Method 2: Sliding window alignment (only for longer audio)
        if query_count >= WINDOW_SIZE:
            window_pct, window_matched = self._sliding_window_score(matches, query_count, indexed_count)
        else:
            window_pct, window_matched = 0.0, set()
        
        # Combine: union of matched segments from both methods
        combined_matched = offset_matched | window_matched
        combined_pct = len(combined_matched) / max(query_count, indexed_count) * 100 if max(query_count, indexed_count) > 0 else 0
        
        # Return best of: offset-only, window-only, or combined
        best_pct = max(offset_pct, window_pct, combined_pct)
        
        return best_pct

    def match_segments(self, audio_segments: list, project: str = None) -> Dict[str, float]:
        """
        Match audio segments against indexed items using hybrid alignment.
        Returns dict of item_id -> match percentage.
        
        Uses hybrid approach combining:
        - Offset-based alignment: finds continuous aligned segments
        - Sliding windows: finds local alignments in discontinuous audio
        
        Handles: trims (start/end/middle), offsets, rearrangements
        """
        if not audio_segments:
            return {}
        
        # Parse query segments
        query_vectors: List[Tuple[int, List[float]]] = []
        for query_idx, seg in enumerate(audio_segments):
            fp = seg.get("fingerprint", [])
            if fp:
                query_vectors.append((query_idx, fingerprint_to_vector(fp)))
        
        query_count = len(query_vectors)
        if query_count == 0:
            return {}
        
        # Build project filter
        query_filter = build_project_filter(project)
        
        # Batch search all segments at once
        requests = [
            QueryRequest(
                query=vec,
                filter=query_filter,
                limit=10,
                with_payload=True
            )
            for query_idx, vec in query_vectors
        ]
        
        try:
            batch_results = self.qdrant.query_batch_points(
                collection_name=AUDIO_COLLECTION,
                requests=requests
            )
        except Exception as e:
            logger.error(f"Batch search failed: {e}")
            return {}
        
        # Collect matches: item_id -> [(query_idx, indexed_idx), ...]
        item_matches: Dict[str, List[Tuple[int, int]]] = {}
        
        for i, result in enumerate(batch_results):
            query_idx = query_vectors[i][0]
            points = result.points if hasattr(result, 'points') else result
            
            for pt in points:
                if euclidean_to_hamming(pt.score) <= AUDIO_HAMMING_THRESHOLD:
                    hit_id = pt.payload.get("item_id")
                    indexed_idx = pt.payload.get("segment_index", 0)
                    item_matches.setdefault(hit_id, []).append((query_idx, indexed_idx))
        
        # Calculate scores using hybrid approach
        results = {}
        for hit_id, matches in item_matches.items():
            indexed_count = count_segments(self.qdrant, AUDIO_COLLECTION, hit_id, project)
            pct = self._hybrid_score(matches, query_count, indexed_count)
            results[hit_id] = pct
        
        return results

    def delete_item(self, item_id: str, project: str = None):
        """Delete all audio segments for an item."""
        project_value = get_project_value(project)
        conditions = [
            FieldCondition(key="item_id", match=MatchValue(value=item_id)),
            FieldCondition(key="project", match=MatchValue(value=project_value))
        ]
        
        self.qdrant.delete(
            collection_name=AUDIO_COLLECTION,
            points_selector=Filter(must=conditions)
        )

    def get_segment_count(self) -> int:
        """Get total number of audio segments indexed."""
        try:
            return self.qdrant.get_collection(AUDIO_COLLECTION).points_count
        except:
            return 0