# app/services/hashing.py
import subprocess
import uuid
import os
import shutil
import logging
import numpy as np
import pdqhash
from PIL import Image

logger = logging.getLogger(__name__)


class HashingService:

    @staticmethod
    def detect_type(file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
            return "image"
        if ext in ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a']:
            return "audio"

        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0", file_path
        ], capture_output=True, text=True)

        output = result.stdout.strip()
        if "video" in output:
            dur_result = subprocess.run([
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", file_path
            ], capture_output=True, text=True)
            try:
                if float(dur_result.stdout.strip()) > 0.5:
                    return "video"
            except:
                pass
            return "image"
        if "audio" in output:
            return "audio"
        return "unknown"

    @staticmethod
    def hash_image(image_path: str) -> tuple[str, int]:
        img = Image.open(image_path).convert("RGB")
        hash_vector, quality = pdqhash.compute(np.array(img))
        hex_str = ''.join(format(b, '02x') for b in np.packbits(hash_vector))
        return hex_str, int(quality)

    @classmethod
    def compute_video_hashes(cls, file_path: str, is_image: bool = False) -> list[dict]:
        if is_image:
            try:
                hex_str, quality = cls.hash_image(file_path)
                return [{"frame_number": 0, "quality": quality, "timestamp": 0.0, "hex": hex_str}]
            except Exception as e:
                logger.error(f"Image hash error: {e}")
                return []

        tmp_dir = f"/tmp/{uuid.uuid4()}_frames"
        os.makedirs(tmp_dir, exist_ok=True)

        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", file_path,
                "-vf", "fps=1", "-q:v", "2",
                f"{tmp_dir}/frame_%04d.jpg"
            ], capture_output=True, timeout=600)

            hashes = []
            frames = sorted([f for f in os.listdir(tmp_dir) if f.endswith('.jpg')])

            for i, frame in enumerate(frames):
                try:
                    hex_str, quality = cls.hash_image(os.path.join(tmp_dir, frame))
                    hashes.append({"frame_number": i, "quality": quality, "timestamp": float(i), "hex": hex_str})
                except:
                    pass

            return hashes
        except Exception as e:
            logger.error(f"Video hash error: {e}")
            return []
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @classmethod
    def compute_audio_fingerprints(cls, file_path: str, window: float = 3.0, hop: float = 0.5) -> list[dict]:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ], capture_output=True, text=True)

        try:
            duration = float(result.stdout.strip())
        except:
            return []

        segments = []
        start = 0.0

        while start + window <= duration:
            tmp = f"/tmp/{uuid.uuid4()}_seg.wav"
            try:
                subprocess.run([
                    "ffmpeg", "-y", "-ss", str(start), "-t", str(window),
                    "-i", file_path, "-ac", "1", "-ar", "11025", "-f", "wav", tmp
                ], capture_output=True, timeout=60)

                result = subprocess.run(["fpcalc", "-raw", "-plain", tmp], capture_output=True, text=True, timeout=30)

                if result.returncode == 0 and result.stdout.strip():
                    fp = [int(x) for x in result.stdout.strip().split(",")]
                    segments.append({"start_time": start, "duration": window, "fingerprint": fp})
            except:
                pass
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
            start += hop

        return segments