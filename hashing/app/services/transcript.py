from openai import OpenAI
import subprocess
import os
import logging

logger = logging.getLogger(__name__)


class TranscriptService:
    client = None

    @classmethod
    def init_openai(cls, api_key: str):
        if cls.client is None:
            cls.client = OpenAI(api_key=api_key)

    @classmethod
    def transcribe(cls, file_path: str, language: str = None) -> dict | None:
        if not cls.client:
            return None

        tmp_wav = f"/tmp/{os.path.basename(file_path)}.wav"

        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", file_path,
                "-ac", "1", "-ar", "16000", "-f", "wav", tmp_wav
            ], capture_output=True, timeout=120)

            if not os.path.exists(tmp_wav):
                return None

            with open(tmp_wav, "rb") as f:
                params = {"model": "whisper-1", "file": f, "response_format": "verbose_json"}
                if language:
                    params["language"] = language
                response = cls.client.audio.transcriptions.create(**params)

            segments = []
            if hasattr(response, 'segments') and response.segments:
                for seg in response.segments:
                    segments.append({"start": seg.start, "end": seg.end, "text": seg.text})

            return {"full_text": response.text, "segments": segments}

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return None
        finally:
            if os.path.exists(tmp_wav):
                os.remove(tmp_wav)