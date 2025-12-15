# tests/test_audio_matching.py
import subprocess
import os
import requests
import pytest
import time

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
TMP_DIR = "./tmp/tests/api/audio_matching"
REQUEST_TIMEOUT = 300

LOREM_IPSUM = """
Lorem ipsum dolor sit amet, consectetur adipiscing elit. 
Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. 
Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris.
Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore.
Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt.
"""

DIFFERENT_TEXT = """
The quick brown fox jumps over the lazy dog.
Pack my box with five dozen liquor jugs.
How vexingly quick daft zebras jump.
Sphinx of black quartz, judge my vow.
The five boxing wizards jump quickly.
"""


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
    dir_to_remove = TMP_DIR
    while dir_to_remove and dir_to_remove not in (".", "./", ""):
        try:
            os.rmdir(dir_to_remove)
            dir_to_remove = os.path.dirname(dir_to_remove)
            if dir_to_remove == "./tmp":
                try:
                    os.rmdir(dir_to_remove)
                except OSError:
                    pass
                break
        except OSError:
            break


def reset():
    requests.post(f"{BASE_URL}/reset", timeout=30)
    for _ in range(20):
        stats = get_stats()
        if (stats.get("total_audio_segments", 0) == 0 and 
            stats.get("total_transcripts", 0) == 0):
            return
        time.sleep(0.2)


def create_speech_audio(filename, text):
    wav_path = os.path.join(TMP_DIR, filename.replace('.mp3', '.wav'))
    mp3_path = os.path.join(TMP_DIR, filename)
    subprocess.run(["espeak", "-w", wav_path, text], capture_output=True, check=True)
    subprocess.run(["ffmpeg", "-y", "-i", wav_path, "-c:a", "libmp3lame", "-b:a", "192k", mp3_path], 
                   capture_output=True, check=True)
    if os.path.exists(wav_path):
        os.remove(wav_path)
    return mp3_path


def get_duration(path):
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ], capture_output=True, text=True)
    return float(result.stdout.strip())


def trim_start(input_path, output_name, trim_percent):
    output_path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    start_time = duration * (trim_percent / 100.0)
    subprocess.run([
        "ffmpeg", "-y", "-ss", str(start_time), "-i", input_path,
        "-c:a", "libmp3lame", output_path
    ], capture_output=True, check=True)
    return output_path


def trim_end(input_path, output_name, trim_percent):
    output_path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    new_duration = duration * (1.0 - trim_percent / 100.0)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path, "-t", str(new_duration),
        "-c:a", "libmp3lame", output_path
    ], capture_output=True, check=True)
    return output_path


def trim_middle(input_path, output_name, trim_percent):
    output_path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    trim_duration = duration * (trim_percent / 100.0)
    start_cut = (duration - trim_duration) / 2
    end_cut = start_cut + trim_duration
    
    part1 = os.path.join(TMP_DIR, f"part1_{output_name}")
    part2 = os.path.join(TMP_DIR, f"part2_{output_name}")
    concat_list = os.path.join(TMP_DIR, f"concat_{output_name}.txt")
    
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path, "-t", str(start_cut),
        "-c:a", "libmp3lame", part1
    ], capture_output=True, check=True)
    
    subprocess.run([
        "ffmpeg", "-y", "-ss", str(end_cut), "-i", input_path,
        "-c:a", "libmp3lame", part2
    ], capture_output=True, check=True)
    
    with open(concat_list, 'w') as f:
        f.write(f"file '{os.path.abspath(part1)}'\n")
        f.write(f"file '{os.path.abspath(part2)}'\n")
    
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
        "-c:a", "libmp3lame", output_path
    ], capture_output=True, check=True)
    
    for f in [part1, part2, concat_list]:
        if os.path.exists(f):
            os.remove(f)
    
    return output_path


def hash_file(path):
    with open(path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/hash",
            files={"file": (os.path.basename(path), f, "audio/mpeg")},
            timeout=REQUEST_TIMEOUT
        )
    if r.status_code != 200:
        print(f"Hash failed: {r.status_code} - {r.text}")
        return None
    return r.json()


def match_file(path, audio_threshold=None, audio_offset=None,
               transcript_threshold=None, transcript_offset=None):
    params = {}
    if audio_threshold is not None:
        params["audio_threshold"] = audio_threshold
    if audio_offset is not None:
        params["audio_offset"] = audio_offset
    if transcript_threshold is not None:
        params["transcript_threshold"] = transcript_threshold
    if transcript_offset is not None:
        params["transcript_offset"] = transcript_offset
    
    with open(path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/match",
            files={"file": (os.path.basename(path), f, "audio/mpeg")},
            params=params,
            timeout=REQUEST_TIMEOUT
        )
    if r.status_code != 200:
        print(f"Match failed: {r.status_code} - {r.text}")
        return None
    return r.json()


def assert_valid_audio_match(match):
    """Assert match has valid structure for audio."""
    item_id = match.get('item_id', '')
    assert len(item_id) == 64 and all(c in '0123456789abcdef' for c in item_id), \
        f"item_id should be SHA256 hash, got: {item_id}"
    assert match.get('image_match_percent') is None, \
        f"image_match_percent should be None for audio, got: {match.get('image_match_percent')}"
    assert match.get('video_match_percent') is None, \
        f"video_match_percent should be None for audio, got: {match.get('video_match_percent')}"


def get_audio_match(path, audio_threshold=0.85, audio_offset=0.03,
                    transcript_threshold=0.85, transcript_offset=-0.01):
    """Get audio match percentages and status."""
    # Get raw percentages (threshold=0 returns all matches)
    raw_matches = match_file(path, 
                            audio_threshold=0.0, audio_offset=0.0,
                            transcript_threshold=0.0, transcript_offset=0.0)
    
    if raw_matches and len(raw_matches) >= 1:
        m = raw_matches[0]
        assert_valid_audio_match(m)
        audio_pct = m.get('audio_match_percent', 0.0) or 0.0
        transcript_pct = m.get('transcript_match_percent', 0.0) or 0.0
    else:
        audio_pct = 0.0
        transcript_pct = 0.0
    
    # Get status with actual thresholds
    real_matches = match_file(path, 
                             audio_threshold=audio_threshold, audio_offset=audio_offset,
                             transcript_threshold=transcript_threshold, transcript_offset=transcript_offset)
    
    if real_matches and len(real_matches) >= 1:
        status = real_matches[0]['status']
        # If we got a match, at least one of audio or transcript must be > 0
        assert audio_pct > 0 or transcript_pct > 0, \
            f"Got match with status={status} but audio_pct={audio_pct}, transcript_pct={transcript_pct}"
    else:
        status = "no_match"
    
    return audio_pct, transcript_pct, status


class TestExactMatch:
    def test_exact_match(self):
        reset()
        base_path = create_speech_audio("exact.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        audio_pct, transcript_pct, status = get_audio_match(base_path)
        print(f"Exact match: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")


class TestNoMatch:
    def test_different_audio_no_match(self):
        reset()
        base_path = create_speech_audio("base_diff.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        different_path = create_speech_audio("different.mp3", DIFFERENT_TEXT)
        audio_pct, transcript_pct, status = get_audio_match(different_path)
        print(f"Different audio: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")


class TestTrimStart:
    def test_trim_start_13_percent(self):
        reset()
        base_path = create_speech_audio("base_s13.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_start(base_path, "trim_s13.mp3", 13)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim START 13%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_start_14_percent(self):
        reset()
        base_path = create_speech_audio("base_s14.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_start(base_path, "trim_s14.mp3", 14)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim START 14%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_start_15_percent(self):
        reset()
        base_path = create_speech_audio("base_s15.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_start(base_path, "trim_s15.mp3", 15)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim START 15%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_start_16_percent(self):
        reset()
        base_path = create_speech_audio("base_s16.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_start(base_path, "trim_s16.mp3", 16)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim START 16%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_start_17_percent(self):
        reset()
        base_path = create_speech_audio("base_s17.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_start(base_path, "trim_s17.mp3", 17)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim START 17%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_start_18_percent(self):
        reset()
        base_path = create_speech_audio("base_s18.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_start(base_path, "trim_s18.mp3", 18)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim START 18%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_start_19_percent(self):
        reset()
        base_path = create_speech_audio("base_s19.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_start(base_path, "trim_s19.mp3", 19)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim START 19%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_start_20_percent(self):
        reset()
        base_path = create_speech_audio("base_s20.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_start(base_path, "trim_s20.mp3", 20)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim START 20%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")


class TestTrimEnd:
    def test_trim_end_13_percent(self):
        reset()
        base_path = create_speech_audio("base_e13.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_end(base_path, "trim_e13.mp3", 13)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim END 13%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_end_14_percent(self):
        reset()
        base_path = create_speech_audio("base_e14.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_end(base_path, "trim_e14.mp3", 14)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim END 14%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_end_15_percent(self):
        reset()
        base_path = create_speech_audio("base_e15.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_end(base_path, "trim_e15.mp3", 15)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim END 15%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_end_16_percent(self):
        reset()
        base_path = create_speech_audio("base_e16.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_end(base_path, "trim_e16.mp3", 16)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim END 16%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_end_17_percent(self):
        reset()
        base_path = create_speech_audio("base_e17.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_end(base_path, "trim_e17.mp3", 17)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim END 17%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_end_18_percent(self):
        reset()
        base_path = create_speech_audio("base_e18.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_end(base_path, "trim_e18.mp3", 18)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim END 18%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_end_19_percent(self):
        reset()
        base_path = create_speech_audio("base_e19.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_end(base_path, "trim_e19.mp3", 19)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim END 19%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_end_20_percent(self):
        reset()
        base_path = create_speech_audio("base_e20.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_end(base_path, "trim_e20.mp3", 20)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim END 20%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")


class TestTrimMiddle:
    def test_trim_middle_13_percent(self):
        reset()
        base_path = create_speech_audio("base_m13.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_middle(base_path, "trim_m13.mp3", 13)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim MIDDLE 13%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_middle_14_percent(self):
        reset()
        base_path = create_speech_audio("base_m14.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_middle(base_path, "trim_m14.mp3", 14)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim MIDDLE 14%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_middle_15_percent(self):
        reset()
        base_path = create_speech_audio("base_m15.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_middle(base_path, "trim_m15.mp3", 15)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim MIDDLE 15%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_middle_16_percent(self):
        reset()
        base_path = create_speech_audio("base_m16.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_middle(base_path, "trim_m16.mp3", 16)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim MIDDLE 16%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_middle_17_percent(self):
        reset()
        base_path = create_speech_audio("base_m17.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_middle(base_path, "trim_m17.mp3", 17)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim MIDDLE 17%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_middle_18_percent(self):
        reset()
        base_path = create_speech_audio("base_m18.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_middle(base_path, "trim_m18.mp3", 18)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim MIDDLE 18%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_middle_19_percent(self):
        reset()
        base_path = create_speech_audio("base_m19.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_middle(base_path, "trim_m19.mp3", 19)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim MIDDLE 19%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")

    def test_trim_middle_20_percent(self):
        reset()
        base_path = create_speech_audio("base_m20.mp3", LOREM_IPSUM)
        hash_file(base_path)
        time.sleep(1)
        
        modified = trim_middle(base_path, "trim_m20.mp3", 20)
        audio_pct, transcript_pct, status = get_audio_match(modified)
        print(f"Trim MIDDLE 20%: audio={audio_pct:.1f}%, transcript={transcript_pct:.1f}%, status={status}")