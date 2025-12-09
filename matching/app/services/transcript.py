# app/services/transcript.py
import subprocess
import uuid
import os
import logging
import time
import re
import html
import unicodedata
from openai import OpenAI, RateLimitError, APIError, APITimeoutError, APIConnectionError
from app.config import settings

logger = logging.getLogger(__name__)
MAX_RETRIES = 3


class TranscriptService:
    def __init__(self):
        self.openai = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize text for matching."""
        if not text:
            return ""
        text = html.unescape(text)
        text = unicodedata.normalize("NFKC", text)
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def transcribe(self, file_path: str, language: str = None) -> str | None:
        """Transcribe audio/video file and return normalized text."""
        if not self.openai:
            return None

        tmp_wav = f"/tmp/{uuid.uuid4()}.wav"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", file_path,
                "-ac", "1", "-ar", "16000", "-f", "wav", tmp_wav
            ], capture_output=True, timeout=120)

            if not os.path.exists(tmp_wav):
                logger.error("FFmpeg failed to create WAV file")
                return None

            with open(tmp_wav, "rb") as f:
                params = {"model": "whisper-1", "file": f, "response_format": "text"}
                if language:
                    params["language"] = language

                response = None
                for attempt in range(MAX_RETRIES):
                    try:
                        response = self.openai.audio.transcriptions.create(**params)
                        break
                    except RateLimitError:
                        wait = 2 ** attempt
                        logger.warning(f"OpenAI rate limited, waiting {wait}s (attempt {attempt + 1}/{MAX_RETRIES})")
                        time.sleep(wait)
                        f.seek(0)
                    except (APITimeoutError, APIConnectionError) as e:
                        logger.warning(f"OpenAI connection issue: {e}, retrying...")
                        time.sleep(1)
                        f.seek(0)
                    except APIError as e:
                        logger.error(f"OpenAI API error: {e}")
                        return None

                if not response:
                    logger.error("Transcription failed after retries")
                    return None

            return self._normalize_text(response)

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg timeout")
            return None
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return None
        finally:
            if os.path.exists(tmp_wav):
                os.remove(tmp_wav)