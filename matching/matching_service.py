# services/index.py
import logging
import faiss
import numpy as np
import re
from collections import defaultdict
from datasketch import MinHash, MinHashLSH

from hashing.hashing_service import HashingService

logger = logging.getLogger(__name__)


class MatchingService:
    
    def __init__(self):
        # Both video and audio now use 256-bit binary hashes with Hamming distance
        self.video_index = faiss.IndexBinaryFlat(256)  # 256-bit PDQ hash
        self.audio_index = faiss.IndexBinaryFlat(256)  # 256-bit Chromaprint binary
        
        self.lsh = MinHashLSH(threshold=0.5, num_perm=128)
        
        self.items = {}
        self.video_metadata = []
        self.audio_metadata = []
        self.transcript_metadata = {}
        
        logger.info("MatchingService initialized (video=Hamming/256bit, audio=Hamming/256bit)")
    
    def _text_to_shingles(self, text: str, k: int = 3) -> set:
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        words = [w for w in text.split() if w]
        if len(words) < k:
            return set([" ".join(words)]) if words else set()
        return set(" ".join(words[i:i+k]) for i in range(len(words) - k + 1))
    
    def _create_minhash(self, text: str) -> MinHash:
        """Create MinHash from text"""
        m = MinHash(num_perm=128)
        for shingle in self._text_to_shingles(text):
            m.update(shingle.encode('utf-8'))
        return m
    
    def add_item(
        self,
        item_id: str,
        item_type: str,
        video_hashes: list[dict] | None = None,
        audio_segments: list[dict] | None = None,
        transcript_segments: list[dict] | None = None,
        transcript_text: str | None = None
    ):
        if item_id in self.items:
            logger.info(f"Item {item_id[:12]}... already indexed, skipping")
            return
        
        num_video = 0
        num_audio = 0
        num_transcript = 0
        
        # Index video hashes
        if video_hashes:
            for vh in video_hashes:
                hash_bytes = HashingService.hex_to_bytes(vh["hex"])
                hash_array = np.array([hash_bytes], dtype=np.uint8)
                self.video_index.add(hash_array)
                self.video_metadata.append({
                    "item_id": item_id,
                    "frame_number": vh["frame_number"],
                    "timestamp": vh["timestamp"]
                })
                num_video += 1
        
        # Index audio segments (now using binary Hamming)
        if audio_segments:
            for seg in audio_segments:
                binary = HashingService.fingerprint_to_binary(seg["fingerprint"])
                binary_array = np.array([binary], dtype=np.uint8)
                self.audio_index.add(binary_array)
                self.audio_metadata.append({
                    "item_id": item_id,
                    "start_time": seg["start_time"],
                    "duration": seg["duration"]
                })
                num_audio += 1
        
        # Index transcript segments
        if transcript_segments:
            for i, seg in enumerate(transcript_segments):
                text = seg.get("text", "")
                if text.strip():
                    minhash = self._create_minhash(text)
                    key = f"{item_id}_seg_{i}"
                    try:
                        self.lsh.insert(key, minhash)
                        self.transcript_metadata[key] = {
                            "item_id": item_id,
                            "segment_index": i,
                            "text": text,
                            "minhash": minhash
                        }
                        num_transcript += 1
                    except ValueError:
                        pass  # Duplicate key
        
        self.items[item_id] = {
            "type": item_type,
            "num_video_hashes": num_video,
            "num_audio_segments": num_audio,
            "num_transcript_segments": num_transcript,
            "transcript_text": transcript_text
        }
        
        logger.info(
            f"Indexed {item_type} {item_id[:12]}... "
            f"(video={num_video}, audio={num_audio}, transcript={num_transcript})"
        )
    
    def match(
        self,
        query_type: str = "video",
        video_hashes: list[dict] | None = None,
        audio_segments: list[dict] | None = None,
        transcript_segments: list[dict] | None = None,
        image_threshold: float = 0.90,
        video_threshold: float = 0.85,
        audio_threshold: float = 0.85,
        transcript_threshold: float = 0.90,
        image_hamming_distance: int = 31,
        video_hamming_distance: int = 31,
        audio_hamming_distance: int = 31
    ) -> list[dict]:
        
        # Track minimum hamming distance per item (lower = better match)
        item_min_image_hamming = defaultdict(lambda: 999)
        item_min_video_hamming = defaultdict(lambda: 999)
        item_min_audio_hamming = defaultdict(lambda: 999)
        item_transcript_matches = defaultdict(float)
        
        num_query_hashes = 0
        num_query_audio = 0
        num_query_transcript = 0
        
        # Match video/image hashes (Hamming distance)
        if video_hashes and self.video_index.ntotal > 0:
            num_query_hashes = len(video_hashes)
            
            # Use the more permissive threshold to get all candidates
            search_hamming = max(image_hamming_distance, video_hamming_distance)
            
            for i, vh in enumerate(video_hashes):
                hash_bytes = HashingService.hex_to_bytes(vh["hex"])
                hash_array = np.array([hash_bytes], dtype=np.uint8)
                
                lims, D, I = self.video_index.range_search(hash_array, search_hamming + 1)
                
                for j in range(lims[0], lims[1]):
                    idx = I[j]
                    dist = int(D[j])
                    if idx < len(self.video_metadata):
                        meta = self.video_metadata[idx]
                        target_item_id = meta["item_id"]
                        target_type = self.items.get(target_item_id, {}).get("type", "unknown")
                        
                        # Track minimum distance by target type
                        if target_type == "image":
                            if dist <= image_hamming_distance:
                                item_min_image_hamming[target_item_id] = min(
                                    item_min_image_hamming[target_item_id], dist
                                )
                        else:  # video
                            if dist <= video_hamming_distance:
                                item_min_video_hamming[target_item_id] = min(
                                    item_min_video_hamming[target_item_id], dist
                                )
        
        # Match audio segments (Hamming distance)
        if audio_segments and self.audio_index.ntotal > 0:
            num_query_audio = len(audio_segments)
            for i, seg in enumerate(audio_segments):
                binary = HashingService.fingerprint_to_binary(seg["fingerprint"])
                binary_array = np.array([binary], dtype=np.uint8)
                
                lims, D, I = self.audio_index.range_search(binary_array, audio_hamming_distance + 1)
                
                for j in range(lims[0], lims[1]):
                    idx = I[j]
                    dist = int(D[j])
                    if idx < len(self.audio_metadata):
                        meta = self.audio_metadata[idx]
                        item_min_audio_hamming[meta["item_id"]] = min(
                            item_min_audio_hamming[meta["item_id"]], dist
                        )
        
        # Match transcript segments
        if transcript_segments and self.transcript_metadata:
            num_query_transcript = len(transcript_segments)
            transcript_sum = defaultdict(float)
            transcript_count = defaultdict(int)
            for seg in transcript_segments:
                text = seg.get("text", "")
                if text.strip():
                    query_minhash = self._create_minhash(text)
                    candidates = self.lsh.query(query_minhash)
                    for candidate_key in candidates:
                        if candidate_key in self.transcript_metadata:
                            meta = self.transcript_metadata[candidate_key]
                            item_id = meta["item_id"]
                            candidate_minhash = meta["minhash"]
                            similarity = query_minhash.jaccard(candidate_minhash)
                            transcript_sum[item_id] += similarity
                            transcript_count[item_id] += 1
            for item_id in transcript_sum:
                if transcript_count[item_id] > 0:
                    item_transcript_matches[item_id] = transcript_sum[item_id] / transcript_count[item_id]
        
        logger.info(
            f"Query ({query_type}): hashes={num_query_hashes}, audio={num_query_audio} segments, "
            f"transcript={num_query_transcript} segments "
            f"(image_hamming={image_hamming_distance}, video_hamming={video_hamming_distance}, audio_hamming={audio_hamming_distance})"
        )
        
        # Aggregate results
        all_item_ids = (
            set(item_min_image_hamming.keys()) | 
            set(item_min_video_hamming.keys()) | 
            set(item_min_audio_hamming.keys()) | 
            set(item_transcript_matches.keys())
        )
        
        results = []
        for item_id in all_item_ids:
            target_type = self.items.get(item_id, {}).get("type", "unknown")
            
            image_match_pct = None
            video_match_pct = None
            audio_match_pct = None
            transcript_sim = None
            
            min_image_dist = None
            min_video_dist = None
            min_audio_dist = None
            
            has_image_match = False
            has_video_match = False
            has_audio_match = False
            has_transcript_match = False
            
            # Calculate image match percentage from hamming distance
            # 0 distance = 100%, max distance = 0%
            if item_id in item_min_image_hamming:
                min_image_dist = item_min_image_hamming[item_id]
                if min_image_dist <= image_hamming_distance:
                    if image_hamming_distance == 0:
                        # Only exact match (distance 0) counts as 100%
                        image_match_pct = 100.0 if min_image_dist == 0 else 0.0
                    else:
                        image_match_pct = (1.0 - (min_image_dist / image_hamming_distance)) * 100
                    if image_match_pct >= image_threshold * 100:
                        has_image_match = True
            
            # Calculate video match percentage from hamming distance
            if item_id in item_min_video_hamming:
                min_video_dist = item_min_video_hamming[item_id]
                if min_video_dist <= video_hamming_distance:
                    if video_hamming_distance == 0:
                        video_match_pct = 100.0 if min_video_dist == 0 else 0.0
                    else:
                        video_match_pct = (1.0 - (min_video_dist / video_hamming_distance)) * 100
                    if video_match_pct >= video_threshold * 100:
                        has_video_match = True
            
            # Calculate audio match percentage from hamming distance
            if item_id in item_min_audio_hamming:
                min_audio_dist = item_min_audio_hamming[item_id]
                if min_audio_dist <= audio_hamming_distance:
                    if audio_hamming_distance == 0:
                        audio_match_pct = 100.0 if min_audio_dist == 0 else 0.0
                    else:
                        audio_match_pct = (1.0 - (min_audio_dist / audio_hamming_distance)) * 100
                    if audio_match_pct >= audio_threshold * 100:
                        has_audio_match = True
            
            # Transcript similarity (already 0-1)
            if item_id in item_transcript_matches:
                transcript_sim = item_transcript_matches[item_id] * 100
                if transcript_sim >= transcript_threshold * 100:
                    has_transcript_match = True
            
            # Determine if this is a match (at least one modality above threshold)
            if has_image_match or has_video_match or has_audio_match or has_transcript_match:
                # Check if all present modalities are at 100%
                all_exact = True
                
                if image_match_pct is not None and image_match_pct < 100:
                    all_exact = False
                if video_match_pct is not None and video_match_pct < 100:
                    all_exact = False
                if audio_match_pct is not None and audio_match_pct < 100:
                    all_exact = False
                if transcript_sim is not None and transcript_sim < 100:
                    all_exact = False
                
                status = "exact_match" if all_exact else "near_match"
                
                results.append({
                    "item_id": item_id,
                    "status": status,
                    "image_match_percent": round(image_match_pct, 2) if image_match_pct is not None else None,
                    "video_match_percent": round(video_match_pct, 2) if video_match_pct is not None else None,
                    "audio_match_percent": round(audio_match_pct, 2) if audio_match_pct is not None else None,
                    "transcript_match_percent": round(transcript_sim, 2) if transcript_sim is not None else None,
                    "image_hamming_distance": min_image_dist,
                    "video_hamming_distance": min_video_dist,
                    "audio_hamming_distance": min_audio_dist
                })
        
        # Sort: exact_match first, then by highest percentages
        results.sort(key=lambda x: (
            x["status"] != "exact_match",
            -(x["image_match_percent"] or 0),
            -(x["video_match_percent"] or 0),
            -(x["audio_match_percent"] or 0),
            -(x["transcript_match_percent"] or 0)
        ))

        if not results:
            return [{
                "item_id": "",
                "status": "no_match",
                "image_match_percent": None,
                "video_match_percent": None,
                "audio_match_percent": None,
                "transcript_match_percent": None,
                "image_hamming_distance": None,
                "video_hamming_distance": None,
                "audio_hamming_distance": None
            }]

        best = results[0]
        logger.info(
            f"Found {len(results)} match(es). Best: {best['item_id'][:12] if best['item_id'] else 'none'}... "
            f"image={best['image_match_percent']}% video={best['video_match_percent']}% "
            f"audio={best['audio_match_percent']}% transcript={best['transcript_match_percent']}% "
            f"image_hamming={best.get('image_hamming_distance')} video_hamming={best.get('video_hamming_distance')} "
            f"audio_hamming={best.get('audio_hamming_distance')}"
        )

        return results
    
    def delete(self, item_id: str) -> bool:
        if item_id not in self.items:
            logger.info(f"Delete: item {item_id[:12]}... not found")
            return False
        
        del self.items[item_id]
        
        # Rebuild video index
        new_video_metadata = []
        for meta in self.video_metadata:
            if meta["item_id"] != item_id:
                new_video_metadata.append(meta)
        
        # Rebuild audio index
        new_audio_metadata = []
        for meta in self.audio_metadata:
            if meta["item_id"] != item_id:
                new_audio_metadata.append(meta)
        
        # Rebuild transcript index
        keys_to_remove = [k for k, v in self.transcript_metadata.items() if v["item_id"] == item_id]
        for key in keys_to_remove:
            try:
                self.lsh.remove(key)
            except:
                pass
            del self.transcript_metadata[key]
        
        self._rebuild_indexes(new_video_metadata, new_audio_metadata)
        
        logger.info(f"Deleted item {item_id[:12]}...")
        return True
    
    def _rebuild_indexes(self, video_metadata: list, audio_metadata: list):
        """Rebuild FAISS indexes after deletion"""
        self.video_index = faiss.IndexBinaryFlat(256)
        self.video_metadata = video_metadata
        
        self.audio_index = faiss.IndexBinaryFlat(256)
        self.audio_metadata = audio_metadata
    
    def reset(self) -> int:
        count = len(self.items)
        
        self.video_index = faiss.IndexBinaryFlat(256)
        self.audio_index = faiss.IndexBinaryFlat(256)
        self.lsh = MinHashLSH(threshold=0.5, num_perm=128)
        
        self.items = {}
        self.video_metadata = []
        self.audio_metadata = []
        self.transcript_metadata = {}
        
        logger.info(f"Index reset, cleared {count} items")
        return count
    
    def stats(self) -> dict:
        stats = {
            "total_items": len(self.items),
            "total_video_hashes": self.video_index.ntotal,
            "total_audio_segments": self.audio_index.ntotal,
            "total_transcript_segments": len(self.transcript_metadata)
        }
        logger.info(
            f"Stats: {stats['total_items']} items, {stats['total_video_hashes']} video hashes, "
            f"{stats['total_audio_segments']} audio segments, {stats['total_transcript_segments']} transcript segments"
        )
        return stats