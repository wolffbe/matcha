# app/services/matching/matching.py
import logging
from app.config import settings
from app.services.matching.matching_base import (
    VIDEO_COLLECTION, AUDIO_COLLECTION, IMAGE_COLLECTION, TRANSCRIPT_COLLECTION,
    get_qdrant_client, init_collections
)
from app.services.matching.audio_matching import AudioMatcher
from app.services.matching.video_matching import VideoMatcher
from app.services.matching.image_matching import ImageMatcher
from app.services.matching.transcript_matching import TranscriptMatcher

logger = logging.getLogger(__name__)


class MatchingService:
    def __init__(self):
        self.qdrant = get_qdrant_client()
        init_collections(self.qdrant)
        
        self.audio_matcher = AudioMatcher(self.qdrant)
        self.video_matcher = VideoMatcher(self.qdrant)
        self.image_matcher = ImageMatcher(self.qdrant)
        self.transcript_matcher = TranscriptMatcher(self.qdrant)

    def add_item(self, item_id: str, item_type: str, video_hashes: list = None,
                 audio_segments: list = None, transcript_text: str = None, **kwargs) -> dict:
        
        indexed_hashes = 0
        indexed_segments = 0
        indexed_transcripts = 0
        
        if video_hashes:
            if item_type == "image":
                indexed_hashes = self.image_matcher.add_hash(item_id, video_hashes)
            else:
                indexed_hashes = self.video_matcher.add_hashes(item_id, video_hashes)
        
        if audio_segments:
            indexed_segments = self.audio_matcher.add_segments(item_id, audio_segments)
        
        if transcript_text:
            indexed_transcripts = self.transcript_matcher.add_transcript(item_id, transcript_text)
        
        return {
            "indexed": True,
            "item_id": item_id,
            "indexed_hashes": indexed_hashes,
            "indexed_segments": indexed_segments,
            "indexed_transcripts": indexed_transcripts
        }

    def match_item(self, item_type: str = None, video_hashes: list = None,
                   audio_segments: list = None, transcript_text: str = None,
                   image_threshold: float = None, video_threshold: float = None,
                   audio_threshold: float = None, transcript_threshold: float = None,
                   image_offset: float = None, video_offset: float = None,
                   audio_offset: float = None, transcript_offset: float = None,
                   video_max_hamming: int = None,
                   **kwargs) -> list[dict]:
        
        img_thresh = image_threshold if image_threshold is not None else settings.image_threshold
        vid_thresh = video_threshold if video_threshold is not None else settings.video_threshold
        aud_thresh = audio_threshold if audio_threshold is not None else settings.audio_threshold
        txt_thresh = transcript_threshold if transcript_threshold is not None else settings.transcript_threshold
        
        img_off = image_offset if image_offset is not None else settings.image_offset
        vid_off = video_offset if video_offset is not None else settings.video_offset
        aud_off = audio_offset if audio_offset is not None else settings.audio_offset
        txt_off = transcript_offset if transcript_offset is not None else settings.transcript_offset
        
        media_type = item_type or "unknown"
        candidates = {}
                
        if video_hashes:
            if media_type == "image":
                img_ham_thresh = int(256 * (1 - (img_thresh - img_off))) + 1
                for item_id, match_data in self.image_matcher.match_hash(video_hashes, img_ham_thresh).items():
                    candidates.setdefault(item_id, {})["image_match_percent"] = match_data["score"]
                    candidates[item_id]["image_is_exact"] = match_data["is_exact"]
            else:
                for item_id, match_data in self.video_matcher.match_hashes(video_hashes, vid_thresh, vid_off, video_max_hamming).items():
                    candidates.setdefault(item_id, {})["video_match_percent"] = match_data["score"]
                    candidates[item_id]["video_is_exact"] = match_data["is_exact"]
        
        if audio_segments:
            for item_id, pct in self.audio_matcher.match_segments(audio_segments).items():
                candidates.setdefault(item_id, {})["audio_match_percent"] = pct
        
        if transcript_text:
            for item_id, pct in self.transcript_matcher.match_transcript(
                transcript_text, txt_thresh, txt_off
            ).items():
                candidates.setdefault(item_id, {})["transcript_match_percent"] = pct
        
        # Convert to percentage for threshold comparison
        img_thresh_pct = img_thresh * 100
        vid_thresh_pct = vid_thresh * 100
        aud_thresh_pct = aud_thresh * 100
        txt_thresh_pct = txt_thresh * 100
        
        img_off_pct = img_off * 100
        vid_off_pct = vid_off * 100
        aud_off_pct = aud_off * 100
        txt_off_pct = txt_off * 100
        
        results = []
        for item_id, data in candidates.items():
            audio_pct = data.get("audio_match_percent", 0)
            transcript_pct = data.get("transcript_match_percent", 0)
            image_pct = data.get("image_match_percent", 0)
            video_pct = data.get("video_match_percent", 0)
            
            image_matches = image_pct >= (img_thresh_pct - img_off_pct) if image_pct > 0 else False
            video_matches = video_pct >= (vid_thresh_pct - vid_off_pct) if video_pct > 0 else False
            audio_matches = audio_pct >= (aud_thresh_pct - aud_off_pct) if audio_pct > 0 else False
            transcript_matches = transcript_pct >= (txt_thresh_pct - txt_off_pct) if transcript_pct > 0 else False
            
            if media_type == "image":
                any_match = image_matches
            elif media_type == "video":
                any_match = video_matches or audio_matches or transcript_matches
            else:
                any_match = audio_matches or transcript_matches
                        
            if not any_match:
                continue
            
            # exact_match based on is_exact flag (hamming=0 for image/video)
            if media_type == "image":
                image_exact = data.get("image_is_exact", False)
                status = "exact_match" if image_exact else "near_match"
            elif media_type == "video":
                video_exact = data.get("video_is_exact", False)
                audio_exact = audio_pct == 100.0
                transcript_exact = transcript_pct == 100.0
                status = "exact_match" if video_exact or audio_exact or transcript_exact else "near_match"
            else:
                audio_exact = audio_pct == 100.0
                transcript_exact = transcript_pct == 100.0
                status = "exact_match" if audio_exact or transcript_exact else "near_match"
            
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
        self.video_matcher.delete_item(item_id)
        self.audio_matcher.delete_item(item_id)
        self.image_matcher.delete_item(item_id)
        self.transcript_matcher.delete_item(item_id)
        return {"deleted": True, "item_id": item_id}

    def reset(self) -> dict:
        for collection in [VIDEO_COLLECTION, AUDIO_COLLECTION, IMAGE_COLLECTION, TRANSCRIPT_COLLECTION]:
            try:
                self.qdrant.delete_collection(collection_name=collection)
            except:
                pass
        init_collections(self.qdrant)
        return {"reset": True}

    def get_stats(self) -> dict:
        return {
            "total_video_hashes": self.video_matcher.get_hash_count(),
            "total_audio_segments": self.audio_matcher.get_segment_count(),
            "total_image_hashes": self.image_matcher.get_hash_count(),
            "total_transcripts": self.transcript_matcher.get_transcript_count()
        }