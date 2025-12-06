# index/app/worker.py
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
                    results = index_service.match_item(
                        query_type=request.get("query_type"),
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
                    result = index_service.delete_item(request["item_id"])
                    response = {"success": True, "deleted": result.get("deleted", True)}

                elif action == "reset":
                    result = index_service.reset()
                    response = {"success": True, "reset": result.get("reset", True)}

                elif action == "stats":
                    stats = index_service.get_stats()
                    response = {"success": True, "stats": stats}

                else:
                    response = {"success": False, "error": f"Unknown action: {action}"}

            except Exception as e:
                logger.error(f"Request {request_id[:8]}... failed: {e}")
                response = {"success": False, "error": str(e)}

            redis_conn.rpush(reply_queue, json.dumps(response))
            redis_conn.expire(reply_queue, 300)
            logger.info(f"Completed {action} request {request_id[:8]}...")

        except Exception as e:
            logger.error(f"Worker error: {e}")


if __name__ == "__main__":
    main()