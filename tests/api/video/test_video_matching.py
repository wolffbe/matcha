# tests/api/video/test_video_matching.py
import subprocess
import os
import shutil
import requests
import pytest
import time
import sys

# Import config for thresholds
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_script_dir, '..', '..', '..'))
_config_path = os.path.join(_project_root, 'matching', 'app', 'config.py')

if not os.path.exists(_config_path):
    raise ImportError(f"config.py not found at {_config_path}")

# Parse config.py directly to avoid pydantic dependency
def _parse_config(config_path):
    """Extract threshold values from config.py without importing it."""
    config = {}
    with open(config_path, 'r') as f:
        content = f.read()
    
    for line in content.split('\n'):
        line = line.strip()
        for key in ['video_threshold', 'video_offset', 'video_max_hamming']:
            if line.startswith(f'{key}:'):
                if '=' in line:
                    val_str = line.split('=')[1].strip()
                    try:
                        if key == 'video_max_hamming':
                            config[key] = int(val_str)
                        else:
                            config[key] = float(val_str)
                    except ValueError:
                        pass
    return config

_config = _parse_config(_config_path)
VIDEO_THRESHOLD = _config.get('video_threshold', 0.85)
VIDEO_OFFSET = _config.get('video_offset', 0)

# Allow override via environment variable for sweep testing
VIDEO_MAX_HAMMING = int(os.environ.get('VIDEO_MAX_HAMMING', _config.get('video_max_hamming', 32)))

# Print the hamming value being used (captured in logs for plotting)
print(f"\n=== VIDEO_MAX_HAMMING={VIDEO_MAX_HAMMING} ===\n")

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
TMP_DIR = "./tmp/tests/api/video_matching"
REQUEST_TIMEOUT = 300
VIDEO_DURATION = 50

# Test percentages
CROP_PERCENTAGES = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
TRIM_PERCENTAGES = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]

# Tolerance for range checks
TOLERANCE = 3.0


def wait_for_service(timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{BASE_URL}/stats", timeout=5)
            if r.status_code == 200:
                return True
        except:
            pass
        time.sleep(1)
    raise RuntimeError(f"Service not available after {timeout}s")


def get_stats():
    r = requests.get(f"{BASE_URL}/stats", timeout=5)
    return r.json() if r.status_code == 200 else {}


@pytest.fixture(scope="module", autouse=True)
def setup_teardown():
    wait_for_service()
    os.makedirs(TMP_DIR, exist_ok=True)
    yield
    shutil.rmtree(TMP_DIR, ignore_errors=True)


def reset():
    requests.post(f"{BASE_URL}/reset", timeout=30)
    for _ in range(20):
        stats = get_stats()
        if stats.get("total_video_hashes", 0) == 0:
            return
        time.sleep(0.2)


def has_audio_stream(file_path):
    """Check if file has an audio stream."""
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        file_path
    ], capture_output=True, text=True)
    return "audio" in result.stdout


def get_duration(path):
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ], capture_output=True, text=True)
    return float(result.stdout.strip())


def create_base_video(filename):
    """Create a test video without audio stream."""
    path = os.path.join(TMP_DIR, filename)
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={VIDEO_DURATION}:size=640x480:rate=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-an",
        path
    ], capture_output=True, check=True)
    assert not has_audio_stream(path), f"Video {path} should not have audio stream"
    return path


def create_different_video(filename):
    """Create a completely different video without audio stream."""
    path = os.path.join(TMP_DIR, filename)
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"cellauto=s=640x480:rate=24:rule=110:random_seed=42,trim=duration={VIDEO_DURATION}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-an",
        path
    ], capture_output=True, check=True)
    assert not has_audio_stream(path), f"Video {path} should not have audio stream"
    return path


def create_crop_right(input_path, output_name, crop_percent):
    path = os.path.join(TMP_DIR, output_name)
    crop_w = 1.0 - crop_percent / 100.0
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"crop=iw*{crop_w}:ih:0:0,pad=640:480:0:0:black",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path
    ], capture_output=True, check=True)
    return path


def create_crop_left(input_path, output_name, crop_percent):
    path = os.path.join(TMP_DIR, output_name)
    crop_w = 1.0 - crop_percent / 100.0
    pad_x = int(640 * crop_percent / 100.0)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"crop=iw*{crop_w}:ih:iw*{crop_percent/100.0}:0,pad=640:480:{pad_x}:0:black",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path
    ], capture_output=True, check=True)
    return path


def create_crop_top(input_path, output_name, crop_percent):
    path = os.path.join(TMP_DIR, output_name)
    crop_h = 1.0 - crop_percent / 100.0
    pad_y = int(480 * crop_percent / 100.0)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"crop=iw:ih*{crop_h}:0:ih*{crop_percent/100.0},pad=640:480:0:{pad_y}:black",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path
    ], capture_output=True, check=True)
    return path


def create_crop_bottom(input_path, output_name, crop_percent):
    path = os.path.join(TMP_DIR, output_name)
    crop_h = 1.0 - crop_percent / 100.0
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"crop=iw:ih*{crop_h}:0:0,pad=640:480:0:0:black",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path
    ], capture_output=True, check=True)
    return path


def create_trim_start(input_path, output_name, trim_percent):
    path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    trim_seconds = duration * trim_percent / 100.0
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-ss", str(trim_seconds),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path
    ], capture_output=True, check=True)
    return path


def create_trim_end(input_path, output_name, trim_percent):
    path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    new_duration = duration * (1.0 - trim_percent / 100.0)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-t", str(new_duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path
    ], capture_output=True, check=True)
    return path


def create_trim_middle(input_path, output_name, trim_percent):
    """Remove the middle X% of video."""
    path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    trim_duration = duration * (trim_percent / 100.0)
    start_cut = (duration - trim_duration) / 2
    end_cut = start_cut + trim_duration
    
    part1 = os.path.join(TMP_DIR, f"part1_{output_name}")
    part2 = os.path.join(TMP_DIR, f"part2_{output_name}")
    concat_list = os.path.join(TMP_DIR, f"concat_{output_name}.txt")
    
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path, "-t", str(start_cut),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", part1
    ], capture_output=True, check=True)
    
    subprocess.run([
        "ffmpeg", "-y", "-ss", str(end_cut), "-i", input_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", part2
    ], capture_output=True, check=True)
    
    with open(concat_list, 'w') as f:
        f.write(f"file '{os.path.abspath(part1)}'\n")
        f.write(f"file '{os.path.abspath(part2)}'\n")
    
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path
    ], capture_output=True, check=True)
    
    for f in [part1, part2, concat_list]:
        if os.path.exists(f):
            os.remove(f)
    
    return path


def create_speed_change(input_path, output_name, speed_factor):
    """Change video speed. speed_factor > 1 = faster, < 1 = slower."""
    path = os.path.join(TMP_DIR, output_name)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"setpts={1/speed_factor}*PTS",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path
    ], capture_output=True, check=True)
    return path


def hash_file(path):
    with open(path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/hash",
            files={"file": (os.path.basename(path), f, "video/mp4")},
            timeout=REQUEST_TIMEOUT
        )
    if r.status_code != 200:
        print(f"Hash failed: {r.status_code} - {r.text}")
        return None
    return r.json()


def match_file(path, video_threshold=None, video_offset=None, video_max_hamming=None):
    params = {}
    if video_threshold is not None:
        params["video_threshold"] = video_threshold
    if video_offset is not None:
        params["video_offset"] = video_offset
    if video_max_hamming is not None:
        params["video_max_hamming"] = video_max_hamming
    
    with open(path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/match",
            files={"file": (os.path.basename(path), f, "video/mp4")},
            params=params if params else None,
            timeout=REQUEST_TIMEOUT
        )
    if r.status_code != 200:
        print(f"Match failed: {r.status_code} - {r.text}")
        return None
    return r.json()


def validate_match_response(match, expected_status):
    """Validate match response structure."""
    # item_id must be SHA256 (64 hex chars)
    item_id = match.get('item_id', '')
    assert len(item_id) == 64 and all(c in '0123456789abcdef' for c in item_id), \
        f"item_id should be SHA256 hash, got: {item_id}"
    
    # For video tests: image should be None, audio/transcript should be present
    assert match.get('image_match_percent') is None, \
        f"image_match_percent should be None for video, got: {match.get('image_match_percent')}"
    assert match.get('audio_match_percent') is not None, \
        f"audio_match_percent should not be None for video"
    assert match.get('transcript_match_percent') is not None, \
        f"transcript_match_percent should not be None for video"
    
    # Status validation
    assert match.get('status') == expected_status, \
        f"Expected status={expected_status}, got: {match.get('status')}"


def get_video_match(path, video_max_hamming=None):
    """Get video match percentage and status using config thresholds."""
    if video_max_hamming is None:
        video_max_hamming = VIDEO_MAX_HAMMING
    
    matches = match_file(path, 
                        video_threshold=VIDEO_THRESHOLD, 
                        video_offset=VIDEO_OFFSET, 
                        video_max_hamming=video_max_hamming)
    if matches and len(matches) >= 1:
        m = matches[0]
        video_pct = m.get('video_match_percent', 0.0) or 0.0
        status = m['status']
        
        # Validate response structure
        item_id = m.get('item_id', '')
        assert len(item_id) == 64 and all(c in '0123456789abcdef' for c in item_id), \
            f"item_id should be SHA256 hash, got: {item_id}"
        
        # If we got a match result, video_pct must be > 0
        assert video_pct > 0, f"Got match with status={status} but video_pct={video_pct}"
        
        return video_pct, status, m
    else:
        return 0.0, "no_match", None


def assert_match(video_pct, status, match, expected_pct, expected_status):
    """Assert match results with range tolerance."""
    if expected_status == "no_match":
        assert status == "no_match", f"Expected no_match, got {status}"
        assert video_pct == 0.0, f"Expected 0% for no_match, got {video_pct}"
        assert match is None, "Match should be None for no_match"
    else:
        assert status == expected_status, f"Expected {expected_status}, got {status}"
        assert abs(video_pct - expected_pct) <= TOLERANCE, \
            f"Expected {expected_pct}% ± {TOLERANCE}%, got {video_pct}%"
        validate_match_response(match, expected_status)


class TestExactMatch:
    def test_exact_match(self):
        """Same file should return 100% with exact_match status."""
        reset()
        base_path = create_base_video("exact.mp4")
        hash_file(base_path)
        time.sleep(0.5)
        
        video_pct, status, match = get_video_match(base_path)
        print(f"Exact match: video={video_pct:.1f}%, status={status}")
        
        assert video_pct == 100.0, f"Expected video 100%, got {video_pct}"
        assert status == "exact_match", f"Expected exact_match, got {status}"
        validate_match_response(match, "exact_match")


class TestNoMatch:
    def test_different_video_no_match(self):
        """Completely different video should not match."""
        reset()
        base_path = create_base_video("base_diff.mp4")
        hash_file(base_path)
        time.sleep(0.5)
        
        different_path = create_different_video("different.mp4")
        video_pct, status, match = get_video_match(different_path)
        print(f"Different video: video={video_pct:.1f}%, status={status}")
        
        assert status == "no_match", f"Expected no_match, got {status}"
        assert video_pct == 0.0, f"Expected 0% for no_match, got {video_pct}"
        assert match is None, "Match should be None for no_match"


class TestCropRight:
    """Crop from right side - expected: no match (PDQ sensitive to horizontal changes)."""
    
    @pytest.mark.parametrize("pct", CROP_PERCENTAGES)
    def test_crop_right_match(self, pct):
        reset()
        base_path = create_base_video(f"base_cr{pct:02d}.mp4")
        hash_file(base_path)
        time.sleep(0.5)
        
        modified = create_crop_right(base_path, f"crop_r{pct:02d}.mp4", pct)
        video_pct, status, match = get_video_match(modified)
        print(f"Crop RIGHT {pct}%: video={video_pct:.1f}%, status={status}")
        
        # All crop right should be no_match
        assert_match(video_pct, status, match, 0.0, "no_match")


class TestCropLeft:
    """Crop from left side - expected: no match (PDQ sensitive to horizontal changes)."""
    
    @pytest.mark.parametrize("pct", CROP_PERCENTAGES)
    def test_crop_left_match(self, pct):
        reset()
        base_path = create_base_video(f"base_cl{pct:02d}.mp4")
        hash_file(base_path)
        time.sleep(0.5)
        
        modified = create_crop_left(base_path, f"crop_l{pct:02d}.mp4", pct)
        video_pct, status, match = get_video_match(modified)
        print(f"Crop LEFT {pct}%: video={video_pct:.1f}%, status={status}")
        
        # All crop left should be no_match
        assert_match(video_pct, status, match, 0.0, "no_match")


class TestCropTop:
    """Crop from top - expected: near_match for small crops, no_match for larger."""
    
    # Expected values based on observed behavior
    EXPECTED = {
        2: (91.6, "near_match"),
        4: (90.9, "near_match"),
        6: (90.8, "near_match"),
        8: (90.6, "near_match"),
        10: (88.0, "near_match"),
        12: (0.0, "no_match"),
        14: (88.5, "near_match"),
        16: (0.0, "no_match"),
        18: (0.0, "no_match"),
        20: (0.0, "no_match"),
    }
    
    @pytest.mark.parametrize("pct", CROP_PERCENTAGES)
    def test_crop_top_match(self, pct):
        reset()
        base_path = create_base_video(f"base_ct{pct:02d}.mp4")
        hash_file(base_path)
        time.sleep(0.5)
        
        modified = create_crop_top(base_path, f"crop_t{pct:02d}.mp4", pct)
        video_pct, status, match = get_video_match(modified)
        print(f"Crop TOP {pct}%: video={video_pct:.1f}%, status={status}")
        
        expected_pct, expected_status = self.EXPECTED[pct]
        assert_match(video_pct, status, match, expected_pct, expected_status)


class TestCropBottom:
    """Crop from bottom - expected: near_match for 2% and 6%, no_match otherwise."""
    
    EXPECTED = {
        2: (92.9, "near_match"),
        4: (0.0, "no_match"),
        6: (88.2, "near_match"),
        8: (0.0, "no_match"),
        10: (0.0, "no_match"),
        12: (0.0, "no_match"),
        14: (0.0, "no_match"),
        16: (0.0, "no_match"),
        18: (0.0, "no_match"),
        20: (0.0, "no_match"),
    }
    
    @pytest.mark.parametrize("pct", CROP_PERCENTAGES)
    def test_crop_bottom_match(self, pct):
        reset()
        base_path = create_base_video(f"base_cb{pct:02d}.mp4")
        hash_file(base_path)
        time.sleep(0.5)
        
        modified = create_crop_bottom(base_path, f"crop_b{pct:02d}.mp4", pct)
        video_pct, status, match = get_video_match(modified)
        print(f"Crop BOTTOM {pct}%: video={video_pct:.1f}%, status={status}")
        
        expected_pct, expected_status = self.EXPECTED[pct]
        assert_match(video_pct, status, match, expected_pct, expected_status)


class TestTrimStart:
    """Trim from start - expected: near_match with decreasing scores."""
    
    EXPECTED = {
        2: (97.7, "near_match"),
        4: (97.4, "near_match"),
        6: (97.3, "near_match"),
        8: (97.0, "near_match"),
        10: (96.8, "near_match"),
        12: (96.6, "near_match"),
        14: (94.6, "near_match"),
        16: (94.3, "near_match"),
        18: (90.7, "near_match"),
        20: (86.9, "near_match"),
    }
    
    @pytest.mark.parametrize("pct", TRIM_PERCENTAGES)
    def test_trim_start(self, pct):
        reset()
        base_path = create_base_video(f"base_ts{pct:02d}.mp4")
        modified = create_trim_start(base_path, f"trim_s{pct:02d}.mp4", pct)
        hash_file(modified)
        time.sleep(0.5)
        
        video_pct, status, match = get_video_match(base_path)
        print(f"Trim START {pct}%: video={video_pct:.1f}%, status={status}")
        
        expected_pct, expected_status = self.EXPECTED[pct]
        assert_match(video_pct, status, match, expected_pct, expected_status)


class TestTrimEnd:
    """Trim from end - expected: near_match with decreasing scores."""
    
    EXPECTED = {
        2: (99.5, "near_match"),
        4: (99.3, "near_match"),
        6: (99.2, "near_match"),
        8: (99.0, "near_match"),
        10: (98.8, "near_match"),
        12: (98.6, "near_match"),
        14: (98.3, "near_match"),
        16: (96.3, "near_match"),
        18: (92.5, "near_match"),
        20: (92.3, "near_match"),
    }
    
    @pytest.mark.parametrize("pct", TRIM_PERCENTAGES)
    def test_trim_end(self, pct):
        reset()
        base_path = create_base_video(f"base_te{pct:02d}.mp4")
        modified = create_trim_end(base_path, f"trim_e{pct:02d}.mp4", pct)
        hash_file(modified)
        time.sleep(0.5)
        
        video_pct, status, match = get_video_match(base_path)
        print(f"Trim END {pct}%: video={video_pct:.1f}%, status={status}")
        
        expected_pct, expected_status = self.EXPECTED[pct]
        assert_match(video_pct, status, match, expected_pct, expected_status)


class TestTrimMiddle:
    """Trim from middle - expected: near_match until 20%."""
    
    EXPECTED = {
        2: (99.5, "near_match"),
        4: (97.4, "near_match"),
        6: (97.2, "near_match"),
        8: (97.0, "near_match"),
        10: (96.8, "near_match"),
        12: (96.6, "near_match"),
        14: (92.8, "near_match"),
        16: (89.0, "near_match"),
        18: (87.1, "near_match"),
        20: (0.0, "no_match"),
    }
    
    @pytest.mark.parametrize("pct", TRIM_PERCENTAGES)
    def test_trim_middle(self, pct):
        reset()
        base_path = create_base_video(f"base_tm{pct:02d}.mp4")
        modified = create_trim_middle(base_path, f"trim_m{pct:02d}.mp4", pct)
        hash_file(modified)
        time.sleep(0.5)
        
        video_pct, status, match = get_video_match(base_path)
        print(f"Trim MIDDLE {pct}%: video={video_pct:.1f}%, status={status}")
        
        expected_pct, expected_status = self.EXPECTED[pct]
        assert_match(video_pct, status, match, expected_pct, expected_status)


class TestSpeedDecrease:
    """Speed decrease - expected: zigzag pattern (frame alignment dependent)."""
    
    EXPECTED = {
        2: (0.0, "no_match"),
        4: (0.0, "no_match"),
        6: (85.4, "near_match"),
        8: (0.0, "no_match"),
        10: (87.5, "near_match"),
        12: (0.0, "no_match"),
        14: (0.0, "no_match"),
        16: (86.3, "near_match"),
        18: (0.0, "no_match"),
        20: (0.0, "no_match"),
    }
    
    @pytest.mark.parametrize("pct,factor", [
        (2, 0.98), (4, 0.96), (6, 0.94), (8, 0.92),
        (10, 0.90), (12, 0.88), (14, 0.86), (16, 0.84), (18, 0.82), (20, 0.80),
    ])
    def test_speed_decrease(self, pct, factor):
        reset()
        base_path = create_base_video(f"base_sp_m{pct:02d}.mp4")
        hash_file(base_path)
        time.sleep(0.5)
        
        modified = create_speed_change(base_path, f"speed_m{pct:02d}.mp4", factor)
        video_pct, status, match = get_video_match(modified)
        print(f"Speed -{pct}%: video={video_pct:.1f}%, status={status}")
        
        expected_pct, expected_status = self.EXPECTED[pct]
        assert_match(video_pct, status, match, expected_pct, expected_status)


class TestSpeedIncrease:
    """Speed increase - expected: only 2% matches."""
    
    EXPECTED = {
        2: (86.8, "near_match"),
        4: (0.0, "no_match"),
        6: (0.0, "no_match"),
        8: (0.0, "no_match"),
        10: (0.0, "no_match"),
        12: (0.0, "no_match"),
        14: (0.0, "no_match"),
        16: (0.0, "no_match"),
        18: (0.0, "no_match"),
        20: (0.0, "no_match"),
    }
    
    @pytest.mark.parametrize("pct,factor", [
        (2, 1.02), (4, 1.04), (6, 1.06), (8, 1.08),
        (10, 1.10), (12, 1.12), (14, 1.14), (16, 1.16), (18, 1.18), (20, 1.20),
    ])
    def test_speed_increase(self, pct, factor):
        reset()
        base_path = create_base_video(f"base_sp_p{pct:02d}.mp4")
        hash_file(base_path)
        time.sleep(0.5)
        
        modified = create_speed_change(base_path, f"speed_p{pct:02d}.mp4", factor)
        video_pct, status, match = get_video_match(modified)
        print(f"Speed +{pct}%: video={video_pct:.1f}%, status={status}")
        
        expected_pct, expected_status = self.EXPECTED[pct]
        assert_match(video_pct, status, match, expected_pct, expected_status)