# hashing/app/services/index_client.py
import json
import uuid
import logging
from redis import Redis
from app.config import settings

logger = logging.getLogger(__name__)


class IndexClient:
    """Client for communicating with index service via Redis queues."""

    def __init__(self):
        self.redis = Redis.from_url(settings.redis_url)
        self.request_queue = settings.request_queue
        self.result_prefix = settings.result_queue_prefix
        self.timeout = settings.request_timeout

    def _send_request(self, action: str, **kwargs) -> dict:
        request_id = str(uuid.uuid4())
        reply_queue = f"{self.result_prefix}{request_id}"
        request = {"request_id": request_id, "action": action, **kwargs}

        # Send request
        self.redis.rpush(self.request_queue, json.dumps(request))

        # Wait for response
        result = self.redis.blpop(reply_queue, timeout=self.timeout)
        if result is None:
            raise TimeoutError(f"Index service timeout after {self.timeout}s")

        _, response_data = result
        response = json.loads(response_data)

        # Cleanup
        self.redis.delete(reply_queue)

        if not response.get("success"):
            raise Exception(response.get("error", "Unknown error"))

        return response

    def add_item(
        self,
        item_id: str,
        item_type: str,
        video_hashes: list | None = None,
        audio_segments: list | None = None,
        transcript_segments: list | None = None,
        transcript_text: str | None = None
    ) -> dict:
        kwargs = {
            "item_id": item_id,
            "item_type": item_type,
        }

        # Only include relevant fields per media type
        if item_type == "image":
            kwargs["video_hashes"] = video_hashes
        elif item_type == "video":
            kwargs["video_hashes"] = video_hashes
            kwargs["audio_segments"] = audio_segments
            kwargs["transcript_segments"] = transcript_segments
            kwargs["transcript_text"] = transcript_text
        elif item_type == "audio":
            kwargs["audio_segments"] = audio_segments
            kwargs["transcript_segments"] = transcript_segments
            kwargs["transcript_text"] = transcript_text

        response = self._send_request(action="add", **kwargs)
        return response["result"]

    def match(
        self,
        query_type: str,
        video_hashes: list | None = None,
        audio_segments: list | None = None,
        transcript_segments: list | None = None,
        image_threshold: float | None = None,
        video_threshold: float | None = None,
        audio_threshold: float | None = None,
        transcript_threshold: float | None = None,
        image_hamming_distance: int | None = None,
        video_hamming_distance: int | None = None,
        audio_hamming_distance: int | None = None
    ) -> list[dict]:
        kwargs = {
            "query_type": query_type,
        }

        # Only include relevant fields per media type
        if query_type == "image":
            kwargs["video_hashes"] = video_hashes
        elif query_type == "video":
            kwargs["video_hashes"] = video_hashes
            kwargs["audio_segments"] = audio_segments
            kwargs["transcript_segments"] = transcript_segments
        elif query_type == "audio":
            kwargs["audio_segments"] = audio_segments
            kwargs["transcript_segments"] = transcript_segments

        # Add thresholds if provided
        if image_hamming_distance is not None:
            kwargs["image_hamming_distance"] = image_hamming_distance
        if video_hamming_distance is not None:
            kwargs["video_hamming_distance"] = video_hamming_distance
        if audio_hamming_distance is not None:
            kwargs["audio_hamming_distance"] = audio_hamming_distance
        if image_threshold is not None:
            kwargs["image_threshold"] = image_threshold
        if video_threshold is not None:
            kwargs["video_threshold"] = video_threshold
        if audio_threshold is not None:
            kwargs["audio_threshold"] = audio_threshold
        if transcript_threshold is not None:
            kwargs["transcript_threshold"] = transcript_threshold

        response = self._send_request(action="match", **kwargs)
        return response["results"]

    def delete(self, item_id: str) -> bool:
        response = self._send_request(action="delete", item_id=item_id)
        return response["deleted"]

    def reset(self) -> int:
        response = self._send_request(action="reset")
        return response["cleared"]

    def stats(self) -> dict:
        response = self._send_request(action="stats")
        return response["stats"]