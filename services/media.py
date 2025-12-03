import subprocess
import uuid
import os
import shutil
import logging
import numpy as np
import pdqhash
from PIL import Image

logger = logging.getLogger(__name__)


class MediaService:
    
    # 8 int32s = 256 bits = 32 bytes (matches PDQ hash size)
    FINGERPRINT_INTS = 8
    FINGERPRINT_BITS = 256
    
    @staticmethod
    def detect_type(file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
            logger.info(f"Detected image by extension: {ext}")
            return "image"
        
        if ext in ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a']:
            logger.info(f"Detected audio by extension: {ext}")
            return "audio"
        
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            file_path
        ], capture_output=True, text=True)
        
        output = result.stdout.strip()
        
        has_video = "video" in output
        has_audio = "audio" in output
        
        if has_video:
            result = subprocess.run([
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path
            ], capture_output=True, text=True)
            
            try:
                duration = float(result.stdout.strip())
                if duration > 0.5:
                    logger.info(f"Detected video via ffprobe (duration={duration:.1f}s)")
                    return "video"
            except:
                pass
            
            logger.info("Detected image via ffprobe (short/still video)")
            return "image"
        
        if has_audio:
            logger.info("Detected audio via ffprobe")
            return "audio"
        
        logger.info("Unknown media type")
        return "unknown"
    
    @staticmethod
    def hex_to_bytes(hex_str: str) -> np.ndarray:
        """Convert 64-char hex string to 32-byte array for PDQ hashes."""
        return np.array([int(hex_str[i:i+2], 16) for i in range(0, 64, 2)], dtype=np.uint8)
    
    @staticmethod
    def hash_image(image_path: str) -> tuple[str, int]:
        img = Image.open(image_path).convert("RGB")
        hash_vector, quality = pdqhash.compute(np.array(img))
        hex_str = ''.join(format(b, '02x') for b in np.packbits(hash_vector))
        return hex_str, int(quality)
    
    @staticmethod
    def compute_video_hashes(file_path: str, is_image: bool = False) -> list[dict]:
        if is_image:
            try:
                hex_str, quality = MediaService.hash_image(file_path)
                logger.info(f"Computed image hash (quality={quality})")
                return [{
                    "frame_number": 0,
                    "quality": quality,
                    "timestamp": 0.0,
                    "hex": hex_str
                }]
            except Exception as e:
                logger.error(f"Image hash error: {e}")
                return []
        
        tmp_dir = f"/tmp/{uuid.uuid4()}_frames"
        os.makedirs(tmp_dir, exist_ok=True)
        
        try:
            logger.info("Extracting frames at 1 fps...")
            result = subprocess.run([
                "ffmpeg", "-y", "-i", file_path,
                "-vf", "fps=1",
                "-q:v", "2",
                f"{tmp_dir}/frame_%04d.jpg"
            ], capture_output=True, text=True, timeout=600)
            
            if result.returncode != 0:
                logger.error(f"ffmpeg frame extraction failed: {result.stderr}")
                return []
            
            hashes = []
            frame_files = sorted([f for f in os.listdir(tmp_dir) if f.endswith('.jpg')])
            logger.info(f"Extracted {len(frame_files)} frames, computing hashes...")
            
            for i, frame_file in enumerate(frame_files):
                frame_path = os.path.join(tmp_dir, frame_file)
                try:
                    hex_str, quality = MediaService.hash_image(frame_path)
                    hashes.append({
                        "frame_number": i,
                        "quality": quality,
                        "timestamp": float(i),
                        "hex": hex_str
                    })
                except Exception as e:
                    logger.error(f"Frame {i} hash error: {e}")
            
            logger.info(f"Computed {len(hashes)} video frame hashes")
            return hashes
            
        except Exception as e:
            logger.error(f"Video hash error: {e}")
            return []
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    
    @classmethod
    def compute_audio_fingerprints(
        cls,
        file_path: str,
        window_seconds: float = 3.0,
        hop_seconds: float = 0.5
    ) -> list[dict]:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error("Could not get audio duration")
            return []
        
        try:
            duration = float(result.stdout.strip())
        except:
            logger.error("Could not parse audio duration")
            return []
        
        logger.info(f"Computing audio fingerprints (duration={duration:.1f}s, window={window_seconds}s, hop={hop_seconds}s)")
        
        segments = []
        start_time = 0.0
        
        while start_time + window_seconds <= duration:
            tmp_segment = f"/tmp/{uuid.uuid4()}_segment.wav"
            
            try:
                result = subprocess.run([
                    "ffmpeg", "-y",
                    "-ss", str(start_time),
                    "-t", str(window_seconds),
                    "-i", file_path,
                    "-ac", "1", "-ar", "11025",
                    "-f", "wav", tmp_segment
                ], capture_output=True, text=True, timeout=60)
                
                if result.returncode != 0:
                    start_time += hop_seconds
                    continue
                
                result = subprocess.run([
                    "fpcalc", "-raw", "-plain", tmp_segment
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0 and result.stdout.strip():
                    fingerprint = [int(x) for x in result.stdout.strip().split(",")]
                    segments.append({
                        "start_time": start_time,
                        "duration": window_seconds,
                        "fingerprint": fingerprint
                    })
            except Exception as e:
                logger.error(f"Fingerprint error at {start_time}s: {e}")
            finally:
                if os.path.exists(tmp_segment):
                    os.remove(tmp_segment)
            
            start_time += hop_seconds
        
        logger.info(f"Computed {len(segments)} audio fingerprint segments")
        return segments
    
    @classmethod
    def fingerprint_to_binary(cls, fingerprint: list[int]) -> np.ndarray:
        """
        Convert Chromaprint fingerprint (list of int32) to 32-byte binary array.
        
        Chromaprint outputs variable-length array of 32-bit integers.
        We take first 8 integers = 256 bits = 32 bytes.
        This matches PDQ hash size for consistent Hamming distance comparison.
        """
        # Pad or truncate to exactly 8 integers
        if len(fingerprint) >= cls.FINGERPRINT_INTS:
            fp = fingerprint[:cls.FINGERPRINT_INTS]
        else:
            fp = fingerprint + [0] * (cls.FINGERPRINT_INTS - len(fingerprint))
        
        # Convert each int32 to 4 bytes (big-endian order)
        # Handle signed integers by masking to unsigned
        binary = np.array([
            (int(val) >> shift) & 0xFF
            for val in fp
            for shift in [24, 16, 8, 0]
        ], dtype=np.uint8)
        
        return binary  # 32 bytes = 256 bits
    
    @classmethod
    def fingerprint_to_hex(cls, fingerprint: list[int]) -> str:
        """Convert fingerprint to hex string for storage/display."""
        binary = cls.fingerprint_to_binary(fingerprint)
        return ''.join(format(b, '02x') for b in binary)