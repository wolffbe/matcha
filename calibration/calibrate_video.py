# tests/calibrate_video.py
import requests
import subprocess
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8000"
TMP_DIR = "./tmp/video_threshold_calibration"
VIDEO_DURATION = 20  # seconds

# Percentages for all tests
# 2,4,6,8,10 should MATCH (≤10%)
# 12,14,16,18,20 should NOT MATCH (>10%)
PERCENTAGES = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
MATCH_THRESHOLD = 10  # ≤10% should match

# Lorem ipsum text for speech
LOREM_IPSUM = """
Lorem ipsum dolor sit amet, consectetur adipiscing elit. 
Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. 
Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. 
Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. 
Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.
Curabitur pretium tincidunt lacus. Nulla gravida orci a odio.
"""

DIFFERENT_TEXT = """
This is completely different content that should not match any of the lorem ipsum texts.
The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs.
How vexingly quick daft zebras jump. The five boxing wizards jump quickly.
"""


def setup():
    os.makedirs(TMP_DIR, exist_ok=True)


def cleanup():
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    parent = Path(TMP_DIR).parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()


def reset():
    requests.post(f"{BASE_URL}/reset")


def format_duration(seconds):
    """Format duration in human-readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {mins}m {secs:.1f}s"


def check_dependencies():
    """Check if required tools are installed and working"""
    # Check espeak
    result = subprocess.run(["which", "espeak"], capture_output=True)
    if result.returncode != 0:
        print("ERROR: espeak not installed. Run: sudo apt-get install espeak")
        sys.exit(1)
    
    # Check ffmpeg
    result = subprocess.run(["which", "ffmpeg"], capture_output=True)
    if result.returncode != 0:
        print("ERROR: ffmpeg not installed")
        sys.exit(1)
    
    # Check ffprobe
    result = subprocess.run(["which", "ffprobe"], capture_output=True)
    if result.returncode != 0:
        print("ERROR: ffprobe not installed")
        sys.exit(1)
    
    print("Dependencies OK: espeak, ffmpeg, ffprobe")


def get_duration(path):
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ], capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except:
        return 0


def create_speech_audio(filename, text, speed=140):
    """Create speech audio using espeak"""
    wav_path = os.path.join(TMP_DIR, filename.replace('.mp3', '.wav'))
    mp3_path = os.path.join(TMP_DIR, filename)
    
    result = subprocess.run([
        "espeak", "-s", str(speed),
        "-w", wav_path,
        text
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"espeak failed: {result.stderr}")
        return None
    
    if not os.path.exists(wav_path):
        print(f"espeak did not create {wav_path}")
        return None
    
    wav_size = os.path.getsize(wav_path)
    if wav_size == 0:
        print(f"espeak created empty file")
        return None
    
    result = subprocess.run([
        "ffmpeg", "-y", "-i", wav_path,
        "-c:a", "libmp3lame", "-b:a", "128k",
        mp3_path
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"ffmpeg mp3 conversion failed: {result.stderr}")
        return None
    
    if os.path.exists(wav_path):
        os.remove(wav_path)
    
    duration = get_duration(mp3_path)
    if duration == 0:
        print(f"Created audio has 0 duration")
        return None
    
    return mp3_path


def create_base_video(filename, text):
    """Create a test video with speech audio"""
    path = os.path.join(TMP_DIR, filename)
    
    audio_path = create_speech_audio("audio.mp3", text, speed=130)
    if not audio_path:
        print("Failed to create speech audio")
        sys.exit(1)
    
    audio_duration = get_duration(audio_path)
    print(f"Audio duration: {audio_duration:.1f}s")
    
    if audio_duration < 10:
        print(f"WARNING: Audio too short ({audio_duration:.1f}s), expected 20s+")
    
    duration = max(VIDEO_DURATION, audio_duration + 1)
    
    # Create video with audio - use copy to preserve audio
    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=640x480:rate=1",
        "-i", audio_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-map", "0:v", "-map", "1:a",
        path
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"ffmpeg video creation failed: {result.stderr}")
        sys.exit(1)
    
    # Verify audio stream exists
    verify = subprocess.run([
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        path
    ], capture_output=True, text=True)
    
    if "audio" not in verify.stdout:
        print(f"WARNING: Video has no audio stream!")
        print(f"ffprobe output: '{verify.stdout}'")
    else:
        print(f"Video has audio stream: OK")
    
    if os.path.exists(audio_path):
        os.remove(audio_path)
    
    video_duration = get_duration(path)
    return path, video_duration


def create_different_video(filename, text):
    """Create a completely different video"""
    path = os.path.join(TMP_DIR, filename)
    
    audio_path = create_speech_audio("diff_audio.mp3", text, speed=160)
    if not audio_path:
        print("Failed to create different speech audio")
        sys.exit(1)
    
    audio_duration = get_duration(audio_path)
    duration = max(VIDEO_DURATION, audio_duration + 1)
    
    # Create video with audio - use copy to preserve audio
    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=red:duration={duration}:size=640x480:rate=1",
        "-i", audio_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-map", "0:v", "-map", "1:a",
        path
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"ffmpeg different video creation failed: {result.stderr}")
        sys.exit(1)
    
    if os.path.exists(audio_path):
        os.remove(audio_path)
    
    return path


# =============================================================================
# VIDEO SPATIAL MODIFICATIONS (affects video frames only, audio unchanged)
# =============================================================================

def create_crop_right(input_path, output_name, crop_percent):
    path = os.path.join(TMP_DIR, output_name)
    crop_w = 1.0 - crop_percent / 100.0
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"crop=iw*{crop_w}:ih:0:0,pad=640:480:0:0:black",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        path
    ], capture_output=True, check=True)
    return path


def create_crop_left(input_path, output_name, crop_percent):
    path = os.path.join(TMP_DIR, output_name)
    crop_w = 1.0 - crop_percent / 100.0
    pad_x = int(640 * crop_percent / 100.0)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"crop=iw*{crop_w}:ih:iw*{crop_percent/100.0}:0,pad=640:480:{pad_x}:0:black",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        path
    ], capture_output=True, check=True)
    return path


def create_crop_top(input_path, output_name, crop_percent):
    path = os.path.join(TMP_DIR, output_name)
    crop_h = 1.0 - crop_percent / 100.0
    pad_y = int(480 * crop_percent / 100.0)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"crop=iw:ih*{crop_h}:0:ih*{crop_percent/100.0},pad=640:480:0:{pad_y}:black",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        path
    ], capture_output=True, check=True)
    return path


def create_crop_bottom(input_path, output_name, crop_percent):
    path = os.path.join(TMP_DIR, output_name)
    crop_h = 1.0 - crop_percent / 100.0
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"crop=iw:ih*{crop_h}:0:0,pad=640:480:0:0:black",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        path
    ], capture_output=True, check=True)
    return path


def create_grayscale(input_path, output_name):
    path = os.path.join(TMP_DIR, output_name)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", "format=gray",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        path
    ], capture_output=True, check=True)
    return path


def create_resized(input_path, output_name, scale_percent):
    path = os.path.join(TMP_DIR, output_name)
    scale = scale_percent / 100.0
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"scale=iw*{scale}:ih*{scale},scale=640:480",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        path
    ], capture_output=True, check=True)
    return path


def create_no_audio(input_path, output_name):
    path = os.path.join(TMP_DIR, output_name)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-an",
        "-c:v", "copy",
        path
    ], capture_output=True, check=True)
    return path


# =============================================================================
# TEMPORAL MODIFICATIONS (affects both video and audio)
# =============================================================================

def create_trim_start(input_path, output_name, trim_percent):
    path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    trim_seconds = duration * trim_percent / 100.0
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-ss", str(trim_seconds),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        path
    ], capture_output=True, check=True)
    return path


def create_trim_end(input_path, output_name, trim_percent):
    path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    new_duration = duration * (1.0 - trim_percent / 100.0)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-t", str(new_duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        path
    ], capture_output=True, check=True)
    return path


def create_trim_middle(input_path, output_name, trim_percent):
    path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    trim_seconds = duration * trim_percent / 100.0
    first_half_end = (duration - trim_seconds) / 2
    second_half_start = first_half_end + trim_seconds
    
    base_name = output_name.replace('.mp4', '')
    part1 = os.path.join(TMP_DIR, f"{base_name}_part1.mp4")
    part2 = os.path.join(TMP_DIR, f"{base_name}_part2.mp4")
    concat_file = os.path.join(TMP_DIR, f"{base_name}_concat.txt")
    
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-t", str(first_half_end),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        part1
    ], capture_output=True, check=True)
    
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-ss", str(second_half_start),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        part2
    ], capture_output=True, check=True)
    
    with open(concat_file, "w") as f:
        f.write(f"file '{os.path.abspath(part1)}'\n")
        f.write(f"file '{os.path.abspath(part2)}'\n")
    
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        path
    ], capture_output=True, check=True)
    
    for f_path in [part1, part2, concat_file]:
        if os.path.exists(f_path):
            os.remove(f_path)
    
    return path


# =============================================================================
# QUALITY MODIFICATIONS (affects both video and audio bitrate)
# =============================================================================

def create_quality_reduced(input_path, output_name, reduction_percent):
    """Reduce both video and audio quality by the given percentage"""
    path = os.path.join(TMP_DIR, output_name)
    quality_factor = 1.0 - (reduction_percent / 100.0)
    
    # Video: base 1000k, reduced proportionally
    video_bitrate = int(1000 * (quality_factor ** 3))
    video_bitrate = max(100, video_bitrate)
    
    # Audio: base 128k, reduced proportionally
    audio_bitrate = int(128 * (quality_factor ** 3))
    audio_bitrate = max(16, audio_bitrate)
    
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-b:v", f"{video_bitrate}k", "-pix_fmt", "yuv420p",
        "-c:a", "libmp3lame", "-b:a", f"{audio_bitrate}k",
        path
    ], capture_output=True, check=True)
    return path


# =============================================================================
# SPEED MODIFICATIONS (affects both video and audio speed)
# =============================================================================

def create_speed_adjusted(input_path, output_name, speed_factor):
    """Adjust speed of entire video (video + audio together)"""
    path = os.path.join(TMP_DIR, output_name)
    video_pts = 1.0 / speed_factor
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-filter_complex", f"[0:v]setpts={video_pts}*PTS[v];[0:a]atempo={speed_factor}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "libmp3lame", "-b:a", "128k",
        path
    ], capture_output=True, check=True)
    return path


# =============================================================================
# AUDIO-ONLY MODIFICATIONS (affects audio track only, video unchanged)
# =============================================================================

def create_audio_noise(input_path, output_name, noise_percent):
    """Add white noise to the audio track only"""
    path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    noise_weight = noise_percent / 100.0
    signal_weight = 1.0 - noise_weight
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-f", "lavfi", "-i", f"anoisesrc=a=0.3:c=white:d={duration}",
        "-filter_complex", f"[0:a][1:a]amix=inputs=2:duration=first:weights={signal_weight} {noise_weight}[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "libmp3lame", "-b:a", "128k",
        path
    ], capture_output=True, check=True)
    return path


def create_audio_mono(input_path, output_name):
    """Convert audio to mono, video unchanged"""
    path = os.path.join(TMP_DIR, output_name)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "copy",
        "-ac", "1",
        "-c:a", "libmp3lame", "-b:a", "128k",
        path
    ], capture_output=True, check=True)
    return path


def create_audio_volume_adjusted(input_path, output_name, volume_factor):
    """Adjust audio volume only, video unchanged"""
    path = os.path.join(TMP_DIR, output_name)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "copy",
        "-filter:a", f"volume={volume_factor}",
        "-c:a", "libmp3lame", "-b:a", "128k",
        path
    ], capture_output=True, check=True)
    return path


# =============================================================================
# MATCHING FUNCTIONS
# =============================================================================

def hash_video(video_path):
    """Hash a video and return the item_id."""
    with open(video_path, "rb") as f:
        r = requests.post(f"{BASE_URL}/hash", files={"file": ("video.mp4", f, "video/mp4")})
        if r.status_code != 200:
            print(f"Hash failed: {r.json()}")
            return None
        return r.json().get("item_id")


def query_match(query_path, video_hamming_distance, audio_hamming_distance):
    """Query against already-indexed base video."""
    with open(query_path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/match?video_hamming_distance={video_hamming_distance}&audio_hamming_distance={audio_hamming_distance}",
            files={"file": ("query.mp4", f, "video/mp4")}
        )
    
    if r.status_code != 200:
        return {
            "matched": False,
            "item_id": None,
            "video": None,
            "audio": None,
            "transcript": None,
            "status": None,
            "video_hamming_distance": None,
            "audio_hamming_distance": None
        }
    
    matches = r.json()
    if not matches:
        return {
            "matched": False,
            "item_id": None,
            "video": None,
            "audio": None,
            "transcript": None,
            "status": None,
            "video_hamming_distance": None,
            "audio_hamming_distance": None
        }
    
    best = matches[0]
    matched = best.get("status") != "no_match"
    return {
        "matched": matched,
        "item_id": best.get("item_id") if matched else None,
        "video": best.get("video_match_percent"),
        "audio": best.get("audio_match_percent"),
        "transcript": best.get("transcript_match_percent"),
        "status": best.get("status"),
        "video_hamming_distance": best.get("video_hamming_distance"),
        "audio_hamming_distance": best.get("audio_hamming_distance")
    }


def run_calibrations_for_thresholds(video_hamming_distance, audio_hamming_distance, base_path, base_item_id, different_path):
    """Run all calibrations for given thresholds. Base video already indexed."""
    results = {}
    total_correct = 0
    total_calibrations = 0
    
    # Build test cases: (key, name, expected_match, create_fn, test_type)
    # test_type: "query" = query modified against base, "index" = index modified, query base
    test_cases = []
    
    # Controls
    test_cases.append(("exact", "Exact match", True, lambda: base_path, "query"))
    test_cases.append(("different", "Different video", False, lambda: different_path, "query"))
    
    # Crop tests - all four sides (video spatial - query modified against base)
    for side in ["right", "left", "top", "bottom"]:
        for pct in PERCENTAGES:
            expected = pct <= MATCH_THRESHOLD
            if side == "right":
                test_cases.append((f"crop_right_{pct}", f"Crop right {pct}%", expected,
                                  lambda p=pct: create_crop_right(base_path, f"crop_right_{p}.mp4", p), "query"))
            elif side == "left":
                test_cases.append((f"crop_left_{pct}", f"Crop left {pct}%", expected,
                                  lambda p=pct: create_crop_left(base_path, f"crop_left_{p}.mp4", p), "query"))
            elif side == "top":
                test_cases.append((f"crop_top_{pct}", f"Crop top {pct}%", expected,
                                  lambda p=pct: create_crop_top(base_path, f"crop_top_{p}.mp4", p), "query"))
            elif side == "bottom":
                test_cases.append((f"crop_bottom_{pct}", f"Crop bottom {pct}%", expected,
                                  lambda p=pct: create_crop_bottom(base_path, f"crop_bottom_{p}.mp4", p), "query"))
    
    # Grayscale (always should match)
    test_cases.append(("grayscale", "Grayscale", True,
                      lambda: create_grayscale(base_path, "grayscale.mp4"), "query"))
    
    # No audio (should match on video)
    test_cases.append(("no_audio", "No audio", True,
                      lambda: create_no_audio(base_path, "no_audio.mp4"), "query"))
    
    # Resize tests (scale = 100 - pct)
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        scale = 100 - pct
        test_cases.append((f"resize_{pct}", f"Resize {pct}%", expected,
                          lambda s=scale, p=pct: create_resized(base_path, f"resize_{p}.mp4", s), "query"))
    
    # Trim tests - start, end, middle (temporal - index modified, query base)
    for location in ["start", "end", "middle"]:
        for pct in PERCENTAGES:
            expected = pct <= MATCH_THRESHOLD
            if location == "start":
                test_cases.append((f"trim_start_{pct}", f"Trim start {pct}%", expected,
                                  lambda p=pct: create_trim_start(base_path, f"trim_start_{p}.mp4", p), "index"))
            elif location == "end":
                test_cases.append((f"trim_end_{pct}", f"Trim end {pct}%", expected,
                                  lambda p=pct: create_trim_end(base_path, f"trim_end_{p}.mp4", p), "index"))
            elif location == "middle":
                test_cases.append((f"trim_middle_{pct}", f"Trim middle {pct}%", expected,
                                  lambda p=pct: create_trim_middle(base_path, f"trim_middle_{p}.mp4", p), "index"))
    
    # Quality tests (video + audio bitrate)
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        test_cases.append((f"quality_{pct}", f"Quality -{pct}%", expected,
                          lambda p=pct: create_quality_reduced(base_path, f"quality_{p}.mp4", p), "query"))
    
    # Speed tests (video + audio speed)
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        speed_down = 1.0 - pct / 100.0
        speed_up = 1.0 + pct / 100.0
        test_cases.append((f"speed_down_{pct}", f"Speed -{pct}%", expected,
                          lambda s=speed_down, p=pct: create_speed_adjusted(base_path, f"speed_down_{p}.mp4", s), "query"))
        test_cases.append((f"speed_up_{pct}", f"Speed +{pct}%", expected,
                          lambda s=speed_up, p=pct: create_speed_adjusted(base_path, f"speed_up_{p}.mp4", s), "query"))
    
    # Audio-only tests
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        test_cases.append((f"audio_noise_{pct}", f"Audio noise {pct}%", expected,
                          lambda p=pct: create_audio_noise(base_path, f"audio_noise_{p}.mp4", p), "query"))
        vol_down = 1.0 - pct / 100.0
        vol_up = 1.0 + pct / 100.0
        test_cases.append((f"audio_vol_down_{pct}", f"Audio vol -{pct}%", expected,
                          lambda v=vol_down, p=pct: create_audio_volume_adjusted(base_path, f"audio_vol_down_{p}.mp4", v), "query"))
        test_cases.append((f"audio_vol_up_{pct}", f"Audio vol +{pct}%", expected,
                          lambda v=vol_up, p=pct: create_audio_volume_adjusted(base_path, f"audio_vol_up_{p}.mp4", v), "query"))
    
    # Audio mono (always should match)
    test_cases.append(("audio_mono", "Audio mono", True,
                      lambda: create_audio_mono(base_path, "audio_mono.mp4"), "query"))
    
    # Run all tests
    for key, name, expected_match, create_fn, test_type in test_cases:
        if test_type == "query":
            # Query modified against already-indexed base
            query_path = create_fn()
            result = query_match(query_path, video_hamming_distance, audio_hamming_distance)
        else:
            # Index modified, query with base (for trim tests)
            modified_path = create_fn()
            reset()
            modified_item_id = hash_video(modified_path)
            if not modified_item_id:
                result = {"matched": False, "video": None, "audio": None, "transcript": None,
                         "status": None, "video_hamming_distance": None, "audio_hamming_distance": None, "item_id": None}
            else:
                result = query_match(base_path, video_hamming_distance, audio_hamming_distance)
            # Re-index base for subsequent tests
            reset()
            hash_video(base_path)
        
        correct = result["matched"] == expected_match
        
        results[key] = {
            "name": name,
            "expected": expected_match,
            "matched": result["matched"],
            "correct": correct,
            "item_id": result.get("item_id"),
            "item_id_correct": result.get("item_id") == base_item_id if result["matched"] and test_type == "query" else True,
            "video": result["video"],
            "audio": result["audio"],
            "transcript": result["transcript"],
            "status": result["status"],
            "video_hamming_distance": result["video_hamming_distance"],
            "audio_hamming_distance": result["audio_hamming_distance"]
        }
        
        if correct:
            total_correct += 1
        total_calibrations += 1
    
    return {
        "video_hamming_distance": video_hamming_distance,
        "audio_hamming_distance": audio_hamming_distance,
        "base_item_id": base_item_id,
        "results": results,
        "overall_correct": total_correct,
        "overall_total": total_calibrations,
        "overall_rate": total_correct / total_calibrations if total_calibrations > 0 else 0
    }


def find_optimal_thresholds(video_hamming_values, audio_hamming_values):
    start_time = time.time()
    
    print(f"Testing video hamming thresholds: {video_hamming_values}")
    print(f"Testing audio hamming thresholds: {audio_hamming_values}")
    print("=" * 80)
    print()
    
    # Create base and different videos once
    print("Creating base video with speech...", end=" ", flush=True)
    base_path, duration = create_base_video("base.mp4", LOREM_IPSUM)
    print(f"done ({duration:.1f}s)")
    
    print("Creating different video...", end=" ", flush=True)
    different_path = create_different_video("different.mp4", DIFFERENT_TEXT)
    print("done")
    print()
    
    all_results = []
    
    for v_hamming in video_hamming_values:
        for a_hamming in audio_hamming_values:
            print(f"Calibrating video_hamming={v_hamming}, audio_hamming={a_hamming}...", end=" ", flush=True)
            
            # Reset and index base video once per threshold combination
            reset()
            base_item_id = hash_video(base_path)
            if not base_item_id:
                print("Failed to hash base video")
                continue
            
            result = run_calibrations_for_thresholds(v_hamming, a_hamming, base_path, base_item_id, different_path)
            all_results.append(result)
            
            print(f"{result['overall_correct']}/{result['overall_total']} ({result['overall_rate']*100:.0f}%)")
    
    elapsed_time = time.time() - start_time
    best = max(all_results, key=lambda x: x["overall_rate"])
    
    return best, all_results, elapsed_time


def format_results(stats):
    """Format results as a string for both printing and file export."""
    lines = []
    
    # Build display order
    test_display = [
        ("exact", "Exact match (should match)"),
        ("different", "Different video (should NOT match)"),
    ]
    
    # Crop tests - all four sides
    for side in ["right", "left", "top", "bottom"]:
        for pct in PERCENTAGES:
            expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
            test_display.append((f"crop_{side}_{pct}", f"Crop {side} {pct}% (should {expected})"))
    
    test_display.append(("grayscale", "Grayscale (should match)"))
    test_display.append(("no_audio", "No audio (should match)"))
    
    # Resize tests
    for pct in PERCENTAGES:
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        test_display.append((f"resize_{pct}", f"Resize {pct}% (should {expected})"))
    
    # Trim tests - start, end, middle
    for location in ["start", "end", "middle"]:
        for pct in PERCENTAGES:
            expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
            test_display.append((f"trim_{location}_{pct}", f"Trim {location} {pct}% (should {expected})"))
    
    # Quality tests
    for pct in PERCENTAGES:
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        test_display.append((f"quality_{pct}", f"Quality -{pct}% (should {expected})"))
    
    # Speed tests
    for pct in PERCENTAGES:
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        test_display.append((f"speed_down_{pct}", f"Speed -{pct}% (should {expected})"))
        test_display.append((f"speed_up_{pct}", f"Speed +{pct}% (should {expected})"))
    
    # Audio tests
    for pct in PERCENTAGES:
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        test_display.append((f"audio_noise_{pct}", f"Audio noise {pct}% (should {expected})"))
        test_display.append((f"audio_vol_down_{pct}", f"Audio vol -{pct}% (should {expected})"))
        test_display.append((f"audio_vol_up_{pct}", f"Audio vol +{pct}% (should {expected})"))
    
    test_display.append(("audio_mono", "Audio mono (should match)"))
    
    lines.append("")
    lines.append(f"Base video item_id: {stats['base_item_id']}")
    lines.append("")
    lines.append(f"{'Calibration':<50} | {'Pass':<6} | {'Video':<8} | {'Audio':<8} | {'Trans':<8} | {'V-Ham':<8} | {'A-Ham':<8} | {'Status':<12} | {'Item ID':<14}")
    lines.append("-" * 150)
    
    for key, name in test_display:
        r = stats["results"].get(key)
        if r is None:
            continue
        pass_str = "✓" if r["correct"] else "✗"
        video_str = f"{r['video']:.0f}%" if r.get('video') is not None else "-"
        audio_str = f"{r['audio']:.0f}%" if r.get('audio') is not None else "-"
        trans_str = f"{r['transcript']:.0f}%" if r.get('transcript') is not None else "-"
        v_hamming_str = str(r.get("video_hamming_distance")) if r.get("video_hamming_distance") is not None else "-"
        a_hamming_str = str(r.get("audio_hamming_distance")) if r.get("audio_hamming_distance") is not None else "-"
        status_str = str(r.get("status")) if r.get("status") is not None else "-"
        item_id_str = r.get("item_id", "")[:12] + "..." if r.get("item_id") else "-"
        lines.append(f"{name:<50} | {pass_str:<6} | {video_str:<8} | {audio_str:<8} | {trans_str:<8} | {v_hamming_str:<8} | {a_hamming_str:<8} | {status_str:<12} | {item_id_str:<14}")
    
    lines.append("-" * 150)
    lines.append(f"{'OVERALL':<50} | {stats['overall_correct']}/{stats['overall_total']}  | {stats['overall_rate']*100:.0f}%")
    return "\n".join(lines)


def format_all_results(all_results):
    """Format all threshold results as a string."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("ALL THRESHOLD COMBINATIONS")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"{'V-Hamming':<12} | {'A-Hamming':<12} | {'Correct':<10} | {'Rate':<10}")
    lines.append("-" * 50)
    for r in sorted(all_results, key=lambda x: -x["overall_rate"]):
        lines.append(f"{r['video_hamming_distance']:<12} | {r['audio_hamming_distance']:<12} | {r['overall_correct']}/{r['overall_total']:<7} | {r['overall_rate']*100:.0f}%")
    return "\n".join(lines)


def export_results(best, all_results, elapsed_time, filename="./results/calibrate_video.txt"):
    """Export the final results to a file."""
    parent_dir = os.path.dirname(filename)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    
    lines = []
    lines.append("=" * 80)
    lines.append("Video Threshold Calibration Results")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Duration: {format_duration(elapsed_time)}")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Calibration criteria (threshold = 90%):")
    lines.append("  - 2,4,6,8,10% modification: should MATCH (≤10%)")
    lines.append("  - 12,14,16,18,20% modification: should NOT MATCH (>10%)")
    lines.append("")
    lines.append("Note: Both video and audio now use Hamming distance (0-256 bits).")
    lines.append("  - Video: PDQ 256-bit perceptual hash")
    lines.append("  - Audio: Chromaprint converted to 256-bit binary")
    lines.append("")
    lines.append("Test categories:")
    lines.append("  VIDEO SPATIAL (video frames only, audio unchanged):")
    lines.append("    - Crop (right/left/top/bottom): pct% cut off from each side")
    lines.append("    - Resize: scale = 100 - pct")
    lines.append("    - Grayscale: always should match")
    lines.append("    - No audio: always should match (video still matches)")
    lines.append("")
    lines.append("  TEMPORAL (affects both video and audio):")
    lines.append("    - Trim start: pct% removed from beginning")
    lines.append("    - Trim end: pct% removed from end")
    lines.append("    - Trim middle: pct% removed from center")
    lines.append("")
    lines.append("  QUALITY (affects both video and audio bitrate):")
    lines.append("    - Quality: bitrate reduced by pct%")
    lines.append("")
    lines.append("  SPEED (affects both video and audio):")
    lines.append("    - Speed down: factor = 1 - pct/100")
    lines.append("    - Speed up: factor = 1 + pct/100")
    lines.append("")
    lines.append("  AUDIO-ONLY (video unchanged):")
    lines.append("    - Noise: pct% noise mixed in")
    lines.append("    - Volume down: factor = 1 - pct/100")
    lines.append("    - Volume up: factor = 1 + pct/100")
    lines.append("    - Mono: always should match")
    lines.append("")
    lines.append(format_all_results(all_results))
    lines.append("")
    lines.append("=" * 80)
    lines.append(f"BEST: video_hamming_distance={best['video_hamming_distance']}, audio_hamming_distance={best['audio_hamming_distance']}")
    lines.append("=" * 80)
    lines.append(format_results(best))
    lines.append("")
    lines.append(f"VIDEO_HAMMING_DISTANCE={best['video_hamming_distance']}")
    lines.append(f"AUDIO_HAMMING_DISTANCE={best['audio_hamming_distance']}")
    lines.append("")
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nResults exported to {filename}")


def main():
    print("=" * 80)
    print("Finding Optimal Video Thresholds")
    print("=" * 80)
    print()
    
    # Setup first since check_dependencies uses TMP_DIR
    setup()
    
    check_dependencies()
    print()
    
    print("Calibration criteria (threshold = 90%):")
    print("  - 2,4,6,8,10% modification: should MATCH")
    print("  - 12,14,16,18,20% modification: should NOT MATCH")
    print()
    print("Note: Both video and audio now use Hamming distance (0-256 bits).")
    print()
    print("Tests:")
    print("  - Crop (right/left/top/bottom) x 10 percentages = 40 tests")
    print("  - Trim (start/end/middle) x 10 percentages = 30 tests")
    print("  - Resize, Quality x 10 percentages = 20 tests")
    print("  - Speed (down/up) x 10 percentages = 20 tests")
    print("  - Audio (noise/vol_down/vol_up) x 10 percentages = 30 tests")
    print("  - Grayscale, NoAudio, AudioMono, Exact, Different = 5 tests")
    print("  - Total: 145 tests per threshold combination")
    print()
    
    try:
        best, all_results, elapsed_time = find_optimal_thresholds(
            # Video hamming: PDQ hash, typically 0-31 for near-duplicates
            video_hamming_values=[28],
            # Audio hamming: Chromaprint binary, may need higher threshold
            audio_hamming_values=[60]
        )
        
        print(format_all_results(all_results))
        print()
        print("=" * 80)
        print(f"BEST: video_hamming_distance={best['video_hamming_distance']}, audio_hamming_distance={best['audio_hamming_distance']}")
        print("=" * 80)
        print(format_results(best))
        print()
        print(f"VIDEO_HAMMING_DISTANCE={best['video_hamming_distance']}")
        print(f"AUDIO_HAMMING_DISTANCE={best['audio_hamming_distance']}")
        print(f"\nCompleted in {format_duration(elapsed_time)}")
        
        export_results(best, all_results, elapsed_time, "./results/calibrate_video.txt")
    finally:
        cleanup()


if __name__ == "__main__":
    main()