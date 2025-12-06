# index/app/services/index.py
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, PointStruct,
    Filter, FieldCondition, MatchValue,
    HnswConfigDiff
)
from datasketch import MinHashLSH, MinHash
import os
import uuid
import logging
from .hashing import hex_to_bytes, fingerprint_to_binary

logger = logging.getLogger(__name__)

QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", 6333))

# Collection names
VIDEO_COLLECTION = "video_hashes"
AUDIO_COLLECTION = "audio_hashes"
IMAGE_COLLECTION = "image_hashes"

# Vector dimensions (256-bit hashes = 256 dimensions as binary)
HASH_DIM = 256


class IndexService:
    def __init__(self):
        self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        self._init_collections()
        
        # Transcript LSH (keep in-memory for now)
        self.transcript_lsh = MinHashLSH(threshold=0.5, num_perm=128)
        self.transcript_minhashes: dict[str, MinHash] = {}
        self.transcript_segments: dict[str, list] = {}

    def _init_collections(self):
        """Initialize Qdrant collections with HNSW indexing."""
        
        collections = [VIDEO_COLLECTION, AUDIO_COLLECTION, IMAGE_COLLECTION]
        existing = {c.name for c in self.client.get_collections().collections}
        
        for collection_name in collections:
            if collection_name not in existing:
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=HASH_DIM,
                        distance=Distance.EUCLID
                    ),
                    hnsw_config=HnswConfigDiff(
                        m=16,
                        ef_construct=100,
                    )
                )

    def _extract_hash(self, hash_item) -> str:
        """Extract hash hex string from various formats."""
        if isinstance(hash_item, dict):
            return hash_item.get("hex") or hash_item.get("hash") or hash_item.get("hash_hex", "")
        elif isinstance(hash_item, str):
            return hash_item
        else:
            return str(hash_item) if hash_item else ""

    def _hash_to_vector(self, hash_hex: str) -> list[float]:
        """Convert hex hash to binary vector (256 dimensions of 0.0 or 1.0)."""
        hash_bytes = hex_to_bytes(hash_hex)
        binary = np.unpackbits(np.frombuffer(hash_bytes, dtype=np.uint8))
        return binary.astype(np.float32).tolist()

    def _fingerprint_to_vector(self, fingerprint: list[int]) -> list[float]:
        """Convert Chromaprint fingerprint to binary vector."""
        binary = fingerprint_to_binary(fingerprint)
        # Pad or truncate to 256 bits (32 bytes)
        if len(binary) < 32:
            binary = binary + b'\x00' * (32 - len(binary))
        elif len(binary) > 32:
            binary = binary[:32]
        bits = np.unpackbits(np.frombuffer(binary, dtype=np.uint8))
        return bits.astype(np.float32).tolist()

    def _euclidean_to_hamming(self, euclidean_dist: float) -> int:
        """Convert Euclidean distance back to Hamming distance for binary vectors."""
        return int(round(euclidean_dist ** 2))

    def _hamming_to_euclidean(self, hamming_dist: int) -> float:
        """Convert Hamming threshold to Euclidean threshold."""
        return np.sqrt(hamming_dist)

    def add_item(
        self,
        item_id: str,
        item_type: str,
        video_hashes: list = None,
        audio_segments: list[dict] = None,
        transcript_segments: list[dict] = None,
        **kwargs
    ) -> dict:
        """Add item to indexes."""
        
        # Add video/image hashes
        if video_hashes:
            collection = IMAGE_COLLECTION if item_type == "image" else VIDEO_COLLECTION
            points = []
            for i, hash_item in enumerate(video_hashes):
                hash_hex = self._extract_hash(hash_item)
                
                if not hash_hex or len(hash_hex) != 64:
                    logger.warning(f"Skipping invalid hash: length={len(hash_hex) if hash_hex else 0}")
                    continue
                
                point_id = str(uuid.uuid4())
                vector = self._hash_to_vector(hash_hex)
                points.append(PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "item_id": item_id,
                        "frame_index": i,
                        "hash_hex": hash_hex
                    }
                ))
            if points:
                self.client.upsert(collection_name=collection, points=points)
                logger.info(f"Added {len(points)} hashes to {collection} for item {item_id}")

        # Add audio segments
        if audio_segments:
            points = []
            for i, seg in enumerate(audio_segments):
                fingerprint = seg.get("fingerprint", [])
                if fingerprint:
                    point_id = str(uuid.uuid4())
                    vector = self._fingerprint_to_vector(fingerprint)
                    points.append(PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "item_id": item_id,
                            "segment_index": i,
                            "start_time": seg.get("start_time", 0),
                            "end_time": seg.get("end_time", 0)
                        }
                    ))
            if points:
                self.client.upsert(collection_name=AUDIO_COLLECTION, points=points)
                logger.info(f"Added {len(points)} audio segments for item {item_id}")

        # Add transcript segments (MinHash LSH)
        if transcript_segments:
            self.transcript_segments[item_id] = transcript_segments
            combined_text = " ".join(s.get("text", "") for s in transcript_segments)
            if combined_text.strip():
                mh = MinHash(num_perm=128)
                for word in combined_text.lower().split():
                    mh.update(word.encode('utf-8'))
                self.transcript_minhashes[item_id] = mh
                try:
                    self.transcript_lsh.insert(item_id, mh)
                except ValueError:
                    pass  # Already exists

        return {"indexed": True, "item_id": item_id}

    def match_item(
        self,
        item_type: str = None,
        query_type: str = None,
        video_hashes: list = None,
        audio_segments: list[dict] = None,
        transcript_segments: list[dict] = None,
        image_hamming_distance: int = 10,
        video_hamming_distance: int = 28,
        audio_hamming_distance: int = 28,
        transcript_threshold: float = 0.85,
        **kwargs
    ) -> list[dict]:
        """Find matching items."""
        
        # Support both item_type and query_type
        media_type = item_type or query_type or "unknown"
        candidates = {}

        # Match video/image hashes
        if video_hashes:
            collection = IMAGE_COLLECTION if media_type == "image" else VIDEO_COLLECTION
            hamming_threshold = image_hamming_distance if media_type == "image" else video_hamming_distance
            
            match_counts = {}
            min_distances = {}
            
            for hash_item in video_hashes:
                hash_hex = self._extract_hash(hash_item)
                
                if not hash_hex or len(hash_hex) != 64:
                    continue
                
                vector = self._hash_to_vector(hash_hex)
                
                # Use query_points instead of search (new API)
                results = self.client.query_points(
                    collection_name=collection,
                    query=vector,
                    limit=10
                )
                
                for point in results.points:
                    hit_item_id = point.payload.get("item_id")
                    # score is distance in Qdrant
                    hamming = self._euclidean_to_hamming(point.score)
                    
                    if hamming <= hamming_threshold:
                        match_counts[hit_item_id] = match_counts.get(hit_item_id, 0) + 1
                        if hit_item_id not in min_distances or hamming < min_distances[hit_item_id]:
                            min_distances[hit_item_id] = hamming

            for cand_id, count in match_counts.items():
                match_pct = (1 - min_distances[cand_id] / 256) * 100
                key = "image" if media_type == "image" else "video"
                candidates[cand_id] = candidates.get(cand_id, {})
                candidates[cand_id][f"{key}_match_percent"] = match_pct
                candidates[cand_id][f"{key}_hamming_distance"] = min_distances[cand_id]
                candidates[cand_id]["match_count"] = count

        # Match audio segments
        if audio_segments:
            match_counts = {}
            min_distances = {}
            
            for seg in audio_segments:
                fingerprint = seg.get("fingerprint", [])
                if fingerprint:
                    vector = self._fingerprint_to_vector(fingerprint)
                    
                    results = self.client.query_points(
                        collection_name=AUDIO_COLLECTION,
                        query=vector,
                        limit=10
                    )
                    
                    for point in results.points:
                        hit_item_id = point.payload.get("item_id")
                        hamming = self._euclidean_to_hamming(point.score)
                        
                        if hamming <= audio_hamming_distance:
                            match_counts[hit_item_id] = match_counts.get(hit_item_id, 0) + 1
                            if hit_item_id not in min_distances or hamming < min_distances[hit_item_id]:
                                min_distances[hit_item_id] = hamming

            for cand_id, count in match_counts.items():
                match_pct = (1 - min_distances[cand_id] / 256) * 100
                candidates[cand_id] = candidates.get(cand_id, {})
                candidates[cand_id]["audio_match_percent"] = match_pct
                candidates[cand_id]["audio_hamming_distance"] = min_distances[cand_id]

        # Match transcript
        if transcript_segments:
            combined_text = " ".join(s.get("text", "") for s in transcript_segments)
            if combined_text.strip():
                query_mh = MinHash(num_perm=128)
                for word in combined_text.lower().split():
                    query_mh.update(word.encode('utf-8'))
                
                matches = self.transcript_lsh.query(query_mh)
                for cand_id in matches:
                    if cand_id in self.transcript_minhashes:
                        similarity = query_mh.jaccard(self.transcript_minhashes[cand_id])
                        if similarity >= transcript_threshold:
                            candidates[cand_id] = candidates.get(cand_id, {})
                            candidates[cand_id]["transcript_match_percent"] = similarity * 100

        # Build results
        results = []
        for cand_id, data in candidates.items():
            result = {
                "item_id": cand_id,
                "status": "no_match",
                "image_match_percent": data.get("image_match_percent"),
                "video_match_percent": data.get("video_match_percent"),
                "audio_match_percent": data.get("audio_match_percent"),
                "transcript_match_percent": data.get("transcript_match_percent"),
                "image_hamming_distance": data.get("image_hamming_distance"),
                "video_hamming_distance": data.get("video_hamming_distance"),
                "audio_hamming_distance": data.get("audio_hamming_distance"),
            }
            
            has_match = any([
                data.get("image_match_percent"),
                data.get("video_match_percent"),
                data.get("audio_match_percent"),
                data.get("transcript_match_percent")
            ])
            
            if has_match:
                is_exact = (
                    (data.get("image_hamming_distance") == 0) or
                    (data.get("video_hamming_distance") == 0) or
                    (data.get("audio_hamming_distance") == 0)
                )
                result["status"] = "exact_match" if is_exact else "near_match"
            
            results.append(result)

        results.sort(key=lambda x: max(
            x.get("image_match_percent") or 0,
            x.get("video_match_percent") or 0,
            x.get("audio_match_percent") or 0,
            x.get("transcript_match_percent") or 0
        ), reverse=True)

        return results

    def delete_item(self, item_id: str, **kwargs) -> dict:
        """Delete item from all indexes."""
        for collection in [VIDEO_COLLECTION, AUDIO_COLLECTION, IMAGE_COLLECTION]:
            self.client.delete(
                collection_name=collection,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="item_id",
                            match=MatchValue(value=item_id)
                        )
                    ]
                )
            )

        if item_id in self.transcript_minhashes:
            try:
                self.transcript_lsh.remove(item_id)
            except:
                pass
            del self.transcript_minhashes[item_id]
        if item_id in self.transcript_segments:
            del self.transcript_segments[item_id]

        return {"deleted": True, "item_id": item_id}

    def reset(self, **kwargs) -> dict:
        """Reset all indexes."""
        for collection in [VIDEO_COLLECTION, AUDIO_COLLECTION, IMAGE_COLLECTION]:
            try:
                self.client.delete_collection(collection_name=collection)
            except:
                pass
        
        self._init_collections()
        
        self.transcript_lsh = MinHashLSH(threshold=0.5, num_perm=128)
        self.transcript_minhashes.clear()
        self.transcript_segments.clear()

        return {"reset": True}

    def get_stats(self, **kwargs) -> dict:
        """Get index statistics."""
        stats = {
            "total_items": 0,
            "total_video_hashes": 0,
            "total_audio_segments": 0,
            "total_image_hashes": 0,
            "total_transcript_segments": len(self.transcript_segments)
        }
        
        try:
            video_info = self.client.get_collection(VIDEO_COLLECTION)
            stats["total_video_hashes"] = video_info.points_count
        except:
            pass
            
        try:
            audio_info = self.client.get_collection(AUDIO_COLLECTION)
            stats["total_audio_segments"] = audio_info.points_count
        except:
            pass
            
        try:
            image_info = self.client.get_collection(IMAGE_COLLECTION)
            stats["total_image_hashes"] = image_info.points_count
        except:
            pass

        stats["total_items"] = len(self.transcript_segments)

        return stats