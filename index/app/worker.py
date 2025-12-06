import json
import logging
from redis import Redis

from app.config import settings
from app.services.index import IndexService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    redis_conn = Redis.from_url(settings.redis_url)
    index_service = IndexService()

    logger.info(f"Index worker started, listening on {settings.request_queue}")

    while True:
        try:
            # Blocking pop from request queue
            _, message = redis_conn.blpop(settings.request_queue)
            request = json.loads(message)

            request_id = request.get("request_id")
            action = request.get("action")
            reply_queue = f"{settings.result_queue_prefix}{request_id}"

            logger.info(f"Processing {action} request {request_id[:8]}...")

            try:
                if action == "add":
                    result = index_service.add_item(
                        item_id=request["item_id"],
                        item_type=request["item_type"],
                        video_hashes=request.get("video_hashes"),
                        audio_segments=request.get("audio_segments"),
                        transcript_segments=request.get("transcript_segments"),
                        transcript_text=request.get("transcript_text")
                    )
                    response = {"success": True, "result": result}

                elif action == "match":
                    results = index_service.match(
                        query_type=request["query_type"],
                        video_hashes=request.get("video_hashes"),
                        audio_segments=request.get("audio_segments"),
                        transcript_segments=request.get("transcript_segments"),
                        image_threshold=request.get("image_threshold", settings.image_threshold),
                        video_threshold=request.get("video_threshold", settings.video_threshold),
                        audio_threshold=request.get("audio_threshold", settings.audio_threshold),
                        transcript_threshold=request.get("transcript_threshold", settings.transcript_threshold),
                        image_hamming_distance=request.get("image_hamming_distance", settings.image_hamming_distance),
                        video_hamming_distance=request.get("video_hamming_distance", settings.video_hamming_distance),
                        audio_hamming_distance=request.get("audio_hamming_distance", settings.audio_hamming_distance)
                    )
                    response = {"success": True, "results": results}

                elif action == "delete":
                    deleted = index_service.delete(request["item_id"])
                    response = {"success": True, "deleted": deleted}

                elif action == "reset":
                    count = index_service.reset()
                    response = {"success": True, "cleared": count}

                elif action == "stats":
                    stats = index_service.stats()
                    response = {"success": True, "stats": stats}

                else:
                    response = {"success": False, "error": f"Unknown action: {action}"}

            except Exception as e:
                logger.error(f"Request {request_id[:8]}... failed: {e}")
                response = {"success": False, "error": str(e)}

            # Push response to reply queue
            redis_conn.rpush(reply_queue, json.dumps(response))
            redis_conn.expire(reply_queue, 300)  # 5 min TTL

            logger.info(f"Completed {action} request {request_id[:8]}...")

        except Exception as e:
            logger.error(f"Worker error: {e}")


if __name__ == "__main__":
    main()