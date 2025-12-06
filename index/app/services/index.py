import logging
import faiss
import numpy as np
import re
from collections import defaultdict
from datasketch import MinHash, MinHashLSH

from app.services.hashing import HashingService

logger = logging.getLogger(__name__)


class IndexService:

    def __init__(self):
        self.video_index = faiss.IndexBinaryFlat(256)
        self.audio_index = faiss.IndexBinaryFlat(256)
        self.lsh = MinHashLSH(threshold=0.5, num_perm=128)

        self.items = {}
        self.video_metadata = []
        self.audio_metadata = []
        self.transcript_metadata = {}

        logger.info("IndexService initialized")

    def _text_to_shingles(self, text: str, k: int = 3) -> set:
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        words = [w for w in text.split() if w]
        if len(words) < k:
            return set([" ".join(words)]) if words else set()
        return set(" ".join(words[i:i+k]) for i in range(len(words) - k + 1))

    def _create_minhash(self, text: str) -> MinHash:
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
    ) -> dict:
        if item_id in self.items:
            item = self.items[item_id]
            return {
                "item_id": item_id,
                "indexed": False,
                "num_video_hashes": item.get("num_video_hashes", 0),
                "num_audio_segments": item.get("num_audio_segments", 0),
                "num_transcript_segments": item.get("num_transcript_segments", 0)
            }

        num_video = 0
        num_audio = 0
        num_transcript = 0

        if video_hashes:
            for vh in video_hashes:
                hash_bytes = HashingService.hex_to_bytes(vh["hex"])
                self.video_index.add(np.array([hash_bytes], dtype=np.uint8))
                self.video_metadata.append({
                    "item_id": item_id,
                    "frame_number": vh["frame_number"],
                    "timestamp": vh["timestamp"]
                })
                num_video += 1

        if audio_segments:
            for seg in audio_segments:
                binary = HashingService.fingerprint_to_binary(seg["fingerprint"])
                self.audio_index.add(np.array([binary], dtype=np.uint8))
                self.audio_metadata.append({
                    "item_id": item_id,
                    "start_time": seg["start_time"],
                    "duration": seg["duration"]
                })
                num_audio += 1

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
                        pass

        self.items[item_id] = {
            "type": item_type,
            "num_video_hashes": num_video,
            "num_audio_segments": num_audio,
            "num_transcript_segments": num_transcript,
            "transcript_text": transcript_text
        }

        logger.info(f"Indexed {item_type} {item_id[:12]}... (v={num_video}, a={num_audio}, t={num_transcript})")

        return {
            "item_id": item_id,
            "indexed": True,
            "num_video_hashes": num_video,
            "num_audio_segments": num_audio,
            "num_transcript_segments": num_transcript
        }

    def match(
        self,
        query_type: str,
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

        item_min_image_hamming = defaultdict(lambda: 999)
        item_min_video_hamming = defaultdict(lambda: 999)
        item_min_audio_hamming = defaultdict(lambda: 999)
        item_transcript_matches = defaultdict(float)

        if video_hashes and self.video_index.ntotal > 0:
            search_hamming = max(image_hamming_distance, video_hamming_distance)

            for vh in video_hashes:
                hash_bytes = HashingService.hex_to_bytes(vh["hex"])
                hash_array = np.array([hash_bytes], dtype=np.uint8)
                lims, D, I = self.video_index.range_search(hash_array, search_hamming + 1)

                for j in range(lims[0], lims[1]):
                    idx = I[j]
                    dist = int(D[j])
                    if idx < len(self.video_metadata):
                        meta = self.video_metadata[idx]
                        target_id = meta["item_id"]
                        target_type = self.items.get(target_id, {}).get("type", "unknown")

                        if target_type == "image":
                            if dist <= image_hamming_distance:
                                item_min_image_hamming[target_id] = min(item_min_image_hamming[target_id], dist)
                        else:
                            if dist <= video_hamming_distance:
                                item_min_video_hamming[target_id] = min(item_min_video_hamming[target_id], dist)

        if audio_segments and self.audio_index.ntotal > 0:
            for seg in audio_segments:
                binary = HashingService.fingerprint_to_binary(seg["fingerprint"])
                binary_array = np.array([binary], dtype=np.uint8)
                lims, D, I = self.audio_index.range_search(binary_array, audio_hamming_distance + 1)

                for j in range(lims[0], lims[1]):
                    idx = I[j]
                    dist = int(D[j])
                    if idx < len(self.audio_metadata):
                        meta = self.audio_metadata[idx]
                        item_min_audio_hamming[meta["item_id"]] = min(item_min_audio_hamming[meta["item_id"]], dist)

        if transcript_segments and self.transcript_metadata:
            transcript_sum = defaultdict(float)
            transcript_count = defaultdict(int)
            for seg in transcript_segments:
                text = seg.get("text", "")
                if text.strip():
                    query_mh = self._create_minhash(text)
                    for key in self.lsh.query(query_mh):
                        if key in self.transcript_metadata:
                            meta = self.transcript_metadata[key]
                            sim = query_mh.jaccard(meta["minhash"])
                            transcript_sum[meta["item_id"]] += sim
                            transcript_count[meta["item_id"]] += 1
            for item_id in transcript_sum:
                if transcript_count[item_id] > 0:
                    item_transcript_matches[item_id] = transcript_sum[item_id] / transcript_count[item_id]

        all_ids = (
            set(item_min_image_hamming.keys()) |
            set(item_min_video_hamming.keys()) |
            set(item_min_audio_hamming.keys()) |
            set(item_transcript_matches.keys())
        )

        results = []
        for item_id in all_ids:
            img_pct = vid_pct = aud_pct = trans_pct = None
            img_dist = vid_dist = aud_dist = None
            has_img = has_vid = has_aud = has_trans = False

            if item_id in item_min_image_hamming:
                img_dist = item_min_image_hamming[item_id]
                if img_dist <= image_hamming_distance:
                    img_pct = (1.0 - img_dist / max(image_hamming_distance, 1)) * 100
                    if img_pct >= image_threshold * 100:
                        has_img = True

            if item_id in item_min_video_hamming:
                vid_dist = item_min_video_hamming[item_id]
                if vid_dist <= video_hamming_distance:
                    vid_pct = (1.0 - vid_dist / max(video_hamming_distance, 1)) * 100
                    if vid_pct >= video_threshold * 100:
                        has_vid = True

            if item_id in item_min_audio_hamming:
                aud_dist = item_min_audio_hamming[item_id]
                if aud_dist <= audio_hamming_distance:
                    aud_pct = (1.0 - aud_dist / max(audio_hamming_distance, 1)) * 100
                    if aud_pct >= audio_threshold * 100:
                        has_aud = True

            if item_id in item_transcript_matches:
                trans_pct = item_transcript_matches[item_id] * 100
                if trans_pct >= transcript_threshold * 100:
                    has_trans = True

            if has_img or has_vid or has_aud or has_trans:
                all_exact = True
                if img_pct is not None and img_pct < 100:
                    all_exact = False
                if vid_pct is not None and vid_pct < 100:
                    all_exact = False
                if aud_pct is not None and aud_pct < 100:
                    all_exact = False
                if trans_pct is not None and trans_pct < 100:
                    all_exact = False

                results.append({
                    "item_id": item_id,
                    "status": "exact_match" if all_exact else "near_match",
                    "image_match_percent": round(img_pct, 2) if img_pct else None,
                    "video_match_percent": round(vid_pct, 2) if vid_pct else None,
                    "audio_match_percent": round(aud_pct, 2) if aud_pct else None,
                    "transcript_match_percent": round(trans_pct, 2) if trans_pct else None,
                    "image_hamming_distance": img_dist,
                    "video_hamming_distance": vid_dist,
                    "audio_hamming_distance": aud_dist
                })

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

        return results

    def delete(self, item_id: str) -> bool:
        if item_id not in self.items:
            return False

        del self.items[item_id]

        new_video = [m for m in self.video_metadata if m["item_id"] != item_id]
        new_audio = [m for m in self.audio_metadata if m["item_id"] != item_id]

        keys_to_remove = [k for k, v in self.transcript_metadata.items() if v["item_id"] == item_id]
        for key in keys_to_remove:
            try:
                self.lsh.remove(key)
            except:
                pass
            del self.transcript_metadata[key]

        self.video_index = faiss.IndexBinaryFlat(256)
        self.video_metadata = new_video

        self.audio_index = faiss.IndexBinaryFlat(256)
        self.audio_metadata = new_audio

        logger.info(f"Deleted {item_id[:12]}...")
        return True

    def reset(self) -> int:
        count = len(self.items)
        self.video_index = faiss.IndexBinaryFlat(256)
        self.audio_index = faiss.IndexBinaryFlat(256)
        self.lsh = MinHashLSH(threshold=0.5, num_perm=128)
        self.items = {}
        self.video_metadata = []
        self.audio_metadata = []
        self.transcript_metadata = {}
        logger.info(f"Reset, cleared {count} items")
        return count

    def stats(self) -> dict:
        return {
            "total_items": len(self.items),
            "total_video_hashes": self.video_index.ntotal,
            "total_audio_segments": self.audio_index.ntotal,
            "total_transcript_segments": len(self.transcript_metadata)
        }