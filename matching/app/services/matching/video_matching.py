# app/services/matching/video_matching.py
"""
Video matching using PDQ perceptual hashes.

PDQ (Perceptual hash for Digital media Quality) produces 256-bit hashes.
Hamming distance is used to compare hashes - lower distance means more similar.

Threshold controls which frames count as matched:
- max_hamming=64 (default) accepts ~25% bit difference
- Frames with hamming > max_hamming are not counted (contribute 0)

Score formula:
- Each matched frame contributes: (256 - hamming) / 256
- score = sum(frame_similarities) / max(query_frames, indexed_frames) * 100
- is_exact = True only if all frames match with hamming=0 and all frames accounted for
"""
import uuid
import logging
from typing import Dict, List, Tuple
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue, QueryRequest
from app.services.matching.matching_base import (
    VIDEO_COLLECTION,
    HASH_DIM,
    hash_to_vector,
    euclidean_to_hamming,
    build_project_filter,
    get_project_value
)

logger = logging.getLogger(__name__)


class VideoMatcher:
    def __init__(self, qdrant: QdrantClient):
        self.qdrant = qdrant

    def add_hashes(self, item_id: str, video_hashes: list, project: str = None) -> int:
        """Index video frame hashes for an item. Returns count of indexed hashes."""
        if not video_hashes:
            return 0
        
        project_value = get_project_value(project)
        
        # First pass: count valid hashes
        valid_hashes = []
        for i, h in enumerate(video_hashes):
            hex_val = h.get("hex", h) if isinstance(h, dict) else h
            if hex_val and len(str(hex_val)) == 64:
                valid_hashes.append((i, str(hex_val)))
        
        total_frames = len(valid_hashes)
        if total_frames == 0:
            return 0
        
        # Second pass: create points with total_frames in payload
        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=hash_to_vector(hex_val),
                payload={
                    "item_id": item_id,
                    "frame_index": i,
                    "total_frames": total_frames,
                    "project": project_value
                }
            )
            for i, hex_val in valid_hashes
        ]
        
        self.qdrant.upsert(collection_name=VIDEO_COLLECTION, points=points)
        return total_frames

    def match_hashes(self, video_hashes: list, threshold: float, offset: float, 
                     max_hamming: int = None, project: str = None) -> Dict[str, dict]:
        """
        Match video frame hashes against indexed items using Qdrant batch search.
        
        Algorithm:
        1. Batch search all query frames in one request
        2. For each query frame, find best match within threshold
        3. Each matched frame contributes (256-hamming)/256 to score
        4. Score = sum(similarities) / max(query_frames, indexed_frames) * 100
        
        Args:
            video_hashes: List of query frame hashes
            threshold: Similarity threshold (0.0-1.0)
            offset: Calibration offset to subtract from threshold
            max_hamming: Direct hamming threshold (overrides threshold/offset if provided)
            project: Project name to filter by
            
        Returns:
            Dict mapping item_id to {score: float, is_exact: bool}
        """
        if not video_hashes:
            return {}
        
        # Calculate max hamming - use direct value if provided, otherwise from threshold
        if max_hamming is not None:
            ham_thresh = max_hamming
        else:
            effective_threshold = max(0, threshold - offset)
            ham_thresh = int(HASH_DIM * (1 - effective_threshold))
        
        # Check collection
        try:
            collection_info = self.qdrant.get_collection(VIDEO_COLLECTION)
            points_count = collection_info.points_count
        except:
            points_count = 0
        
        logger.info(f"VIDEO MATCH: max_hamming={ham_thresh}, points={points_count}, project={project}")
        
        if points_count == 0:
            return {}
        
        # Build project filter
        query_filter = build_project_filter(project)
        
        # Parse query hashes
        query_vectors: List[Tuple[int, List[float]]] = []
        for idx, h in enumerate(video_hashes):
            hex_val = h.get("hex", h) if isinstance(h, dict) else h
            if hex_val and len(str(hex_val)) == 64:
                query_vectors.append((idx, hash_to_vector(str(hex_val))))
        
        total_query = len(query_vectors)
        if total_query == 0:
            return {}
        
        # Batch search all frames at once
        requests = [
            QueryRequest(
                query=vec,
                filter=query_filter,
                limit=100,  # Get enough candidates to find correct item
                with_payload=True
            )
            for idx, vec in query_vectors
        ]
        
        try:
            batch_results = self.qdrant.query_batch_points(
                collection_name=VIDEO_COLLECTION,
                requests=requests
            )
        except Exception as e:
            logger.error(f"Batch search failed: {e}")
            return {}
        
        # Process results - track both directions
        # item_id -> set of matched query frame indices
        item_query_matches: Dict[str, set] = {}
        # item_id -> set of matched indexed frame indices  
        item_indexed_matches: Dict[str, set] = {}
        # item_id -> list of hamming distances
        item_hammings: Dict[str, List[int]] = {}
        # item_id -> total_frames (from payload)
        item_indexed_counts: Dict[str, int] = {}
        
        for idx, result in enumerate(batch_results):
            points = result.points if hasattr(result, 'points') else result
            
            if not points:
                continue
            
            # Find best match within threshold
            best_hamming = HASH_DIM + 1
            best_item = None
            best_indexed_frame = None
            best_total_frames = 1
            
            for pt in points:
                hamming = euclidean_to_hamming(pt.score)
                
                if hamming <= ham_thresh and hamming < best_hamming:
                    best_hamming = hamming
                    best_item = pt.payload.get("item_id")
                    best_indexed_frame = pt.payload.get("frame_index", 0)
                    best_total_frames = pt.payload.get("total_frames", 1)
            
            if best_item:
                item_query_matches.setdefault(best_item, set()).add(idx)
                item_indexed_matches.setdefault(best_item, set()).add(best_indexed_frame)
                item_hammings.setdefault(best_item, []).append(best_hamming)
                item_indexed_counts[best_item] = best_total_frames
        
        # Calculate scores
        results = {}
        for item_id in item_query_matches.keys():
            indexed_count = item_indexed_counts.get(item_id, 1)
            
            query_matched = len(item_query_matches[item_id])
            indexed_matched = len(item_indexed_matches[item_id])
            hammings = item_hammings[item_id]
            
            max_frames = max(total_query, indexed_count)
            
            # Score = sum of similarities / max frames
            # Each matched frame contributes (256-hamming)/256, unmatched contribute 0
            total_similarity = sum((HASH_DIM - h) / HASH_DIM for h in hammings)
            pct = (total_similarity / max_frames) * 100 if max_frames > 0 else 0
            
            # is_exact only if all frames matched with hamming=0 AND counts match
            all_exact = all(h == 0 for h in hammings)
            is_exact = all_exact and query_matched == total_query and indexed_matched == indexed_count
            
            # Cap at 99.9% if not exact
            if not is_exact and pct > 99.9:
                pct = 99.9
            
            logger.info(f"  [{item_id[:8]}]: q_match={query_matched}, i_match={indexed_matched}, "
                       f"query={total_query}, indexed={indexed_count}, "
                       f"score={pct:.1f}%, exact={is_exact}")
            results[item_id] = {"score": pct, "is_exact": is_exact}
        
        return results

    def delete_item(self, item_id: str, project: str = None):
        """Delete all video hashes for an item."""
        project_value = get_project_value(project)
        conditions = [
            FieldCondition(key="item_id", match=MatchValue(value=item_id)),
            FieldCondition(key="project", match=MatchValue(value=project_value))
        ]
        
        self.qdrant.delete(
            collection_name=VIDEO_COLLECTION,
            points_selector=Filter(must=conditions)
        )

    def get_hash_count(self) -> int:
        """Get total number of video hashes indexed."""
        try:
            return self.qdrant.get_collection(VIDEO_COLLECTION).points_count
        except:
            return 0