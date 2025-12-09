# app/services/matching.py
import uuid
import logging
import numpy as np
from typing import Dict, List, Any
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, PointStruct,
    Filter, FieldCondition, MatchValue,
    HnswConfigDiff
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from app.config import settings

logger = logging.getLogger(__name__)

VIDEO_COLLECTION = "video_hashes"
AUDIO_COLLECTION = "audio_hashes"
IMAGE_COLLECTION = "image_hashes"

HASH_DIM = 256
FINGERPRINT_INTS = 8


class MatchingService:
    def __init__(self):
        self.qdrant = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        self._init_collections()
        
        # Transcript storage
        self.transcript_texts: Dict[str, str] = {}  # item_id -> normalized text
        self.tfidf_vectorizer = TfidfVectorizer()
        self.tfidf_matrix = None
        self.tfidf_item_ids: List[str] = []

    def _init_collections(self):
        existing = {c.name for c in self.qdrant.get_collections().collections}
        for name in [VIDEO_COLLECTION, AUDIO_COLLECTION, IMAGE_COLLECTION]:
            if name not in existing:
                self.qdrant.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=HASH_DIM, distance=Distance.EUCLID),
                    hnsw_config=HnswConfigDiff(m=16, ef_construct=100)
                )

    # ========== Vector Helpers ==========

    def _hash_to_vector(self, hash_hex: str) -> list[float]:
        hash_bytes = bytes.fromhex(hash_hex)
        return np.unpackbits(np.frombuffer(hash_bytes, dtype=np.uint8)).astype(np.float32).tolist()

    def _fingerprint_to_vector(self, fingerprint: list[int]) -> list[float]:
        fp = (fingerprint[:FINGERPRINT_INTS] + [0] * FINGERPRINT_INTS)[:FINGERPRINT_INTS]
        result = []
        for val in fp:
            # Handle 32-bit signed integers properly
            v = int(val) & 0xFFFFFFFF  # Convert to unsigned 32-bit
            result.extend([
                (v >> 24) & 0xFF,
                (v >> 16) & 0xFF,
                (v >> 8) & 0xFF,
                v & 0xFF
            ])
        binary = bytes(result)
        return np.unpackbits(np.frombuffer(binary, dtype=np.uint8)).astype(np.float32).tolist()

    @staticmethod
    def _euclidean_to_hamming(euclidean_dist: float) -> int:
        return int(round(euclidean_dist ** 2))

    def _count_segments(self, collection: str, item_id: str) -> int:
        result = self.qdrant.scroll(
            collection_name=collection,
            scroll_filter=Filter(must=[FieldCondition(key="item_id", match=MatchValue(value=item_id))]),
            limit=10000, with_payload=False, with_vectors=False
        )
        return len(result[0])

    # ========== Transcript Indexing (TF-IDF + Cosine Similarity) ==========

    def _rebuild_tfidf(self):
        """Rebuild TF-IDF matrix from all stored transcripts."""
        if not self.transcript_texts:
            self.tfidf_matrix = None
            self.tfidf_item_ids = []
            return
        
        self.tfidf_item_ids = list(self.transcript_texts.keys())
        texts = [self.transcript_texts[item_id] for item_id in self.tfidf_item_ids]
        
        self.tfidf_vectorizer = TfidfVectorizer()
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(texts)

    def _index_transcript(self, item_id: str, text: str) -> int:
        """Index normalized transcript text."""
        if not text or not text.strip():
            return 0
        
        self.transcript_texts[item_id] = text
        self._rebuild_tfidf()
        
        return 1

    def _match_transcript(self, text: str) -> Dict[str, float]:
        """Match normalized transcript text against indexed transcripts using TF-IDF cosine similarity."""
        if not text or not text.strip():
            return {}
        
        if self.tfidf_matrix is None or len(self.tfidf_item_ids) == 0:
            return {}
        
        # Transform query using fitted vectorizer
        query_vector = self.tfidf_vectorizer.transform([text])
        
        # Compute cosine similarity with all indexed transcripts
        similarities = cosine_similarity(query_vector, self.tfidf_matrix)[0]
        
        results = {}
        for idx, item_id in enumerate(self.tfidf_item_ids):
            sim = similarities[idx]
            if sim > 0:
                results[item_id] = sim * 100
        
        return results

    # ========== Main API ==========

    def add_item(self, item_id: str, item_type: str, video_hashes: list = None,
                 audio_segments: list = None, transcript_text: str = None, **kwargs) -> dict:
        
        if video_hashes:
            collection = IMAGE_COLLECTION if item_type == "image" else VIDEO_COLLECTION
            points = []
            for i, h in enumerate(video_hashes):
                hex_val = h.get("hex", h) if isinstance(h, dict) else h
                if hex_val and len(str(hex_val)) == 64:
                    points.append(PointStruct(
                        id=str(uuid.uuid4()),
                        vector=self._hash_to_vector(str(hex_val)),
                        payload={"item_id": item_id, "frame_index": i}
                    ))
            if points:
                self.qdrant.upsert(collection_name=collection, points=points)

        if audio_segments:
            points = []
            for i, seg in enumerate(audio_segments):
                fp = seg.get("fingerprint", [])
                if fp:
                    points.append(PointStruct(
                        id=str(uuid.uuid4()),
                        vector=self._fingerprint_to_vector(fp),
                        payload={"item_id": item_id, "segment_index": i, "start_time": seg.get("start_time", 0)}
                    ))
            if points:
                self.qdrant.upsert(collection_name=AUDIO_COLLECTION, points=points)

        indexed_transcripts = 0
        if transcript_text:
            indexed_transcripts = self._index_transcript(item_id, transcript_text)

        return {"indexed": True, "item_id": item_id, "indexed_transcripts": indexed_transcripts}

    def match_item(self, item_type: str = None, video_hashes: list = None,
                   audio_segments: list = None, transcript_text: str = None,
                   image_threshold: float = None, video_threshold: float = None,
                   audio_threshold: float = None, transcript_threshold: float = None,
                   image_offset: float = None, video_offset: float = None,
                   audio_offset: float = None, transcript_offset: float = None,
                   **kwargs) -> list[dict]:
        
        # Get thresholds (convert to percentage)
        img_thresh = (image_threshold if image_threshold is not None else settings.image_threshold) * 100
        vid_thresh = (video_threshold if video_threshold is not None else settings.video_threshold) * 100
        aud_thresh = (audio_threshold if audio_threshold is not None else settings.audio_threshold) * 100
        txt_thresh = (transcript_threshold if transcript_threshold is not None else settings.transcript_threshold) * 100
        
        # Get offsets (convert to percentage)
        img_off = (image_offset if image_offset is not None else settings.image_offset) * 100
        vid_off = (video_offset if video_offset is not None else settings.video_offset) * 100
        aud_off = (audio_offset if audio_offset is not None else settings.audio_offset) * 100
        txt_off = (transcript_offset if transcript_offset is not None else settings.transcript_offset) * 100
        
        media_type = item_type or "unknown"
        candidates = {}

        # Hamming thresholds
        hamming = {"image": 20, "video": 28, "audio": 80}

        # Match video/image hashes
        if video_hashes:
            collection = IMAGE_COLLECTION if media_type == "image" else VIDEO_COLLECTION
            key = "image_match_percent" if media_type == "image" else "video_match_percent"
            ham_thresh = hamming.get(media_type, 28)
            
            matched = {}
            total = 0
            for idx, h in enumerate(video_hashes):
                hex_val = h.get("hex", h) if isinstance(h, dict) else h
                if not hex_val or len(str(hex_val)) != 64:
                    continue
                total += 1
                results = self.qdrant.query_points(
                    collection_name=collection,
                    query=self._hash_to_vector(str(hex_val)),
                    limit=10
                )
                for pt in results.points:
                    hit_id = pt.payload.get("item_id")
                    if self._euclidean_to_hamming(pt.score) <= ham_thresh:
                        matched.setdefault(hit_id, set()).add(idx)

            for hit_id, segs in matched.items():
                indexed = self._count_segments(collection, hit_id)
                pct = len(segs) / max(total, indexed) * 100 if max(total, indexed) > 0 else 0
                candidates.setdefault(hit_id, {})[key] = pct

        # Match audio with multi-offset alignment (handles middle cuts)
        if audio_segments:
            # For each indexed item, collect (query_idx, indexed_idx) pairs
            item_matches: Dict[str, List[tuple]] = {}
            
            for query_idx, seg in enumerate(audio_segments):
                fp = seg.get("fingerprint", [])
                if not fp:
                    continue
                results = self.qdrant.query_points(
                    collection_name=AUDIO_COLLECTION,
                    query=self._fingerprint_to_vector(fp),
                    limit=10
                )
                for pt in results.points:
                    if self._euclidean_to_hamming(pt.score) <= hamming["audio"]:
                        hit_id = pt.payload.get("item_id")
                        indexed_idx = pt.payload.get("segment_index", 0)
                        item_matches.setdefault(hit_id, []).append((query_idx, indexed_idx))
            
            query_count = len([s for s in audio_segments if s.get("fingerprint")])
            
            for hit_id, matches in item_matches.items():
                indexed_count = self._count_segments(AUDIO_COLLECTION, hit_id)
                
                # Multi-offset detection: find all significant alignment offsets
                # offset = indexed_idx - query_idx
                # Group matches by offset
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
                # Each query segment counted only once
                all_matched_queries = set()
                for query_indices in significant_offsets.values():
                    all_matched_queries.update(query_indices)
                
                total_matched = len(all_matched_queries)
                
                # Score: matched segments / larger of (query, indexed)
                pct = total_matched / max(query_count, indexed_count) * 100 if max(query_count, indexed_count) > 0 else 0
                candidates.setdefault(hit_id, {})["audio_match_percent"] = pct

        # Match transcript
        if transcript_text:
            for item_id, pct in self._match_transcript(transcript_text).items():
                candidates.setdefault(item_id, {})["transcript_match_percent"] = pct

        # Build results with per-type threshold + offset logic
        # For each type: 100% = exact_match, >= threshold - offset = near_match, < threshold - offset = no match
        results = []
        for item_id, data in candidates.items():
            audio_pct = data.get("audio_match_percent", 0)
            transcript_pct = data.get("transcript_match_percent", 0)
            image_pct = data.get("image_match_percent", 0)
            video_pct = data.get("video_match_percent", 0)

            # Check each type against its own threshold
            image_matches = image_pct >= (img_thresh - img_off) if image_pct > 0 else False
            video_matches = video_pct >= (vid_thresh - vid_off) if video_pct > 0 else False
            audio_matches = audio_pct >= (aud_thresh - aud_off) if audio_pct > 0 else False
            transcript_matches = transcript_pct >= (txt_thresh - txt_off) if transcript_pct > 0 else False

            # Determine if any type matches based on media type
            if media_type == "image":
                any_match = image_matches
                best_pct = image_pct
            elif media_type == "video":
                any_match = video_matches or audio_matches or transcript_matches
                best_pct = max(video_pct, audio_pct, transcript_pct)
            else:  # audio
                any_match = audio_matches or transcript_matches
                best_pct = max(audio_pct, transcript_pct)

            if not any_match:
                continue

            # exact_match only if 100%
            if media_type == "image":
                status = "exact_match" if image_pct == 100 else "near_match"
            elif media_type == "video":
                status = "exact_match" if video_pct == 100 or audio_pct == 100 or transcript_pct == 100 else "near_match"
            else:
                status = "exact_match" if audio_pct == 100 or transcript_pct == 100 else "near_match"

            results.append({
                "item_id": item_id,
                "status": status,
                "image_match_percent": image_pct if media_type == "image" else None,
                "video_match_percent": video_pct if media_type == "video" else None,
                "audio_match_percent": audio_pct if media_type != "image" else None,
                "transcript_match_percent": transcript_pct if media_type != "image" else None,
            })

        results.sort(key=lambda x: max(
            x.get("image_match_percent") or 0,
            x.get("video_match_percent") or 0,
            x.get("audio_match_percent") or 0,
            x.get("transcript_match_percent") or 0
        ), reverse=True)

        return results

    def delete_item(self, item_id: str) -> dict:
        for collection in [VIDEO_COLLECTION, AUDIO_COLLECTION, IMAGE_COLLECTION]:
            self.qdrant.delete(
                collection_name=collection,
                points_selector=Filter(must=[FieldCondition(key="item_id", match=MatchValue(value=item_id))])
            )
        
        # Remove transcript and rebuild TF-IDF
        if item_id in self.transcript_texts:
            del self.transcript_texts[item_id]
            self._rebuild_tfidf()
        
        return {"deleted": True, "item_id": item_id}

    def reset(self) -> dict:
        for collection in [VIDEO_COLLECTION, AUDIO_COLLECTION, IMAGE_COLLECTION]:
            try:
                self.qdrant.delete_collection(collection_name=collection)
            except:
                pass
        self._init_collections()
        
        # Clear transcripts
        self.transcript_texts.clear()
        self.tfidf_matrix = None
        self.tfidf_item_ids = []
        
        return {"reset": True}

    def get_stats(self) -> dict:
        stats = {"total_video_hashes": 0, "total_audio_segments": 0, 
                 "total_image_hashes": 0, "total_transcripts": len(self.transcript_texts)}
        for coll, key in [(VIDEO_COLLECTION, "total_video_hashes"),
                          (AUDIO_COLLECTION, "total_audio_segments"),
                          (IMAGE_COLLECTION, "total_image_hashes")]:
            try:
                stats[key] = self.qdrant.get_collection(coll).points_count
            except:
                pass
        return stats