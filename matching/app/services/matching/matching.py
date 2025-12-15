# app/services/matching/matching.py
import logging
from app.config import settings
from app.services.matching.matching_base import (
    VIDEO_COLLECTION, AUDIO_COLLECTION, IMAGE_COLLECTION, TRANSCRIPT_COLLECTION,
    get_qdrant_client, init_collections, build_project_filter, count_collection
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
                 audio_segments: list = None, transcript_text: str = None,
                 project: str = None, **kwargs) -> dict:
        
        indexed_hashes = 0
        indexed_segments = 0
        indexed_transcripts = 0
        
        if video_hashes:
            if item_type == "image":
                indexed_hashes = self.image_matcher.add_hash(item_id, video_hashes, project=project)
            else:
                indexed_hashes = self.video_matcher.add_hashes(item_id, video_hashes, project=project)
        
        if audio_segments:
            indexed_segments = self.audio_matcher.add_segments(item_id, audio_segments, project=project)
        
        if transcript_text:
            indexed_transcripts = self.transcript_matcher.add_transcript(item_id, transcript_text, project=project)
        
        return {
            "indexed": True,
            "item_id": item_id,
            "indexed_hashes": indexed_hashes,
            "indexed_segments": indexed_segments,
            "indexed_transcripts": indexed_transcripts,
            "project": project
        }

    def match_item(self, item_type: str = None, video_hashes: list = None,
                   audio_segments: list = None, transcript_text: str = None,
                   image_threshold: float = None, video_threshold: float = None,
                   audio_threshold: float = None, transcript_threshold: float = None,
                   image_offset: float = None, video_offset: float = None,
                   audio_offset: float = None, transcript_offset: float = None,
                   video_max_hamming: int = None, project: str = None,
                   query_item_id: str = None,
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
                for item_id, match_data in self.image_matcher.match_hash(video_hashes, img_ham_thresh, project=project).items():
                    candidates.setdefault(item_id, {})["image_match_percent"] = match_data["score"]
                    candidates[item_id]["image_is_exact"] = match_data["is_exact"]
            else:
                for item_id, match_data in self.video_matcher.match_hashes(video_hashes, vid_thresh, vid_off, video_max_hamming, project=project).items():
                    candidates.setdefault(item_id, {})["video_match_percent"] = match_data["score"]
                    candidates[item_id]["video_is_exact"] = match_data["is_exact"]
        
        if audio_segments:
            for item_id, pct in self.audio_matcher.match_segments(audio_segments, project=project).items():
                candidates.setdefault(item_id, {})["audio_match_percent"] = pct
        
        if transcript_text:
            for item_id, pct in self.transcript_matcher.match_transcript(
                transcript_text, txt_thresh, txt_off, project=project
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
            
            # exact_match only if SHA256 hashes match (same file)
            # near_match if perceptually similar but different file
            is_exact = query_item_id and item_id == query_item_id
            status = "exact_match" if is_exact else "near_match"
            
            # Cap percentages at 99.99% if not exact same file
            if not is_exact:
                audio_pct = min(audio_pct, 99.99)
                video_pct = min(video_pct, 99.99)
                image_pct = min(image_pct, 99.99)
                transcript_pct = min(transcript_pct, 99.99)
            
            results.append({
                "item_id": item_id,
                "status": status,
                "image_match_percent": image_pct if media_type == "image" else None,
                "video_match_percent": video_pct if media_type == "video" else None,
                "audio_match_percent": audio_pct if media_type != "image" else None,
                "transcript_match_percent": transcript_pct if media_type != "image" else None,
                "project": project,
            })
        
        results.sort(key=lambda x: max(
            x.get("image_match_percent") or 0,
            x.get("video_match_percent") or 0,
            x.get("audio_match_percent") or 0,
            x.get("transcript_match_percent") or 0
        ), reverse=True)
        
        return results

    def delete_item(self, item_id: str, project: str = None) -> dict:
        self.video_matcher.delete_item(item_id, project=project)
        self.audio_matcher.delete_item(item_id, project=project)
        self.image_matcher.delete_item(item_id, project=project)
        self.transcript_matcher.delete_item(item_id, project=project)
        return {"deleted": True, "item_id": item_id, "project": project}

    def reset(self, project: str = None) -> dict:
        # Convert None to default project sentinel
        from app.services.matching.matching_base import get_project_value
        project_value = get_project_value(project)
        
        # Delete only points with matching project
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        project_filter = Filter(must=[FieldCondition(key="project", match=MatchValue(value=project_value))])
        
        for collection in [VIDEO_COLLECTION, AUDIO_COLLECTION, IMAGE_COLLECTION, TRANSCRIPT_COLLECTION]:
            try:
                self.qdrant.delete(
                    collection_name=collection,
                    points_selector=project_filter
                )
            except Exception as e:
                logger.warning(f"Failed to reset {collection} for project {project}: {e}")
        
        return {"reset": True, "project": project}

    def get_stats(self, project: str = None) -> dict:
        return {
            "total_video_hashes": count_collection(self.qdrant, VIDEO_COLLECTION, project),
            "total_audio_segments": count_collection(self.qdrant, AUDIO_COLLECTION, project),
            "total_image_hashes": count_collection(self.qdrant, IMAGE_COLLECTION, project),
            "total_transcripts": count_collection(self.qdrant, TRANSCRIPT_COLLECTION, project),
            "project": project
        }