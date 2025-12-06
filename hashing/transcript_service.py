# services/transcript.py
from openai import OpenAI
import subprocess
import os
import logging

logger = logging.getLogger(__name__)


class TranscriptService:
    client = None
    
    @classmethod
    def init_openai(cls, api_key: str):
        cls.client = OpenAI(api_key=api_key)
        logger.info("OpenAI Whisper client initialized")
    
    @classmethod
    def transcribe(cls, file_path: str, language: str = None) -> dict | None:
        if not cls.client:
            logger.error("No OpenAI client initialized")
            return None
        
        tmp_wav = f"/tmp/{os.path.basename(file_path)}.wav"
        
        try:
            logger.info("Converting to WAV for transcription...")
            result = subprocess.run([
                "ffmpeg", "-y", "-i", file_path,
                "-ac", "1", "-ar", "16000",
                "-f", "wav", tmp_wav
            ], capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                logger.error(f"ffmpeg WAV conversion failed: {result.stderr}")
                return None
            
            if not os.path.exists(tmp_wav):
                logger.error("WAV file not created")
                return None
            
            file_size = os.path.getsize(tmp_wav)
            logger.info(f"WAV file ready ({file_size} bytes), calling Whisper API...")
            
            with open(tmp_wav, "rb") as audio_file:
                params = {
                    "model": "whisper-1",
                    "file": audio_file,
                    "response_format": "verbose_json"
                }
                if language:
                    params["language"] = language
                    logger.info(f"Using language hint: {language}")
                
                response = cls.client.audio.transcriptions.create(**params)
            
            segments = []
            if hasattr(response, 'segments') and response.segments:
                for seg in response.segments:
                    segments.append({
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text
                    })
            
            text_preview = response.text[:100] + "..." if len(response.text) > 100 else response.text
            logger.info(f"Transcription complete: {len(segments)} segments, {len(response.text)} chars")
            logger.info(f"Transcript preview: \"{text_preview}\"")
            
            return {
                "full_text": response.text,
                "segments": segments
            }
            
        except Exception as e:
            logger.error(f"Transcription failed: {type(e).__name__}: {e}")
            return None
        finally:
            if os.path.exists(tmp_wav):
                os.remove(tmp_wav)