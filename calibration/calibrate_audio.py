# tests/calibrate_audio.py
import subprocess
import os
import shutil
import requests
from datetime import datetime
from statistics import mean
from pathlib import Path
import time

BASE_URL = "http://localhost:8000"
TMP_DIR = "./tmp/audio_threshold_calibration"

# Percentages for all tests
# 12,14 should MATCH (≤15% modification, ≥85% remains)
# 16,18 should NOT MATCH (>15% modification, <85% remains)
PERCENTAGES = [12, 14, 16, 18]
MATCH_THRESHOLD = 15  # ≤15% modification should match

LOREM_IPSUM = """
Lorem ipsum dolor sit amet, consectetur adipiscing elit. 
Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. 
Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. 
Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. 
Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.
Curabitur pretium tincidunt lacus. Nulla gravida orci a odio. 
Nullam varius, turpis et commodo pharetra, est eros bibendum elit, nec luctus magna felis sollicitudin mauris.
Integer in mauris eu nibh euismod gravida. Duis ac tellus et risus vulputate vehicula.
Donec lobortis risus a elit. Etiam tempor. Ut ullamcorper, ligula eu tempor congue, eros est euismod turpis.
"""

DIFFERENT_TEXT = """
This is completely different content that should not match any of the lorem ipsum texts.
The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs.
How vexingly quick daft zebras jump. The five boxing wizards jump quickly.
Sphinx of black quartz, judge my vow. Two driven jocks help fax my big quiz.
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


def create_speech_audio(filename, text, speed=140):
    wav_path = os.path.join(TMP_DIR, filename.replace('.mp3', '.wav'))
    mp3_path = os.path.join(TMP_DIR, filename)
    subprocess.run([
        "espeak", "-s", str(speed),
        "-w", wav_path,
        text
    ], capture_output=True, check=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", wav_path,
        "-c:a", "libmp3lame", "-b:a", "128k",
        mp3_path
    ], capture_output=True, check=True)
    if os.path.exists(wav_path):
        os.remove(wav_path)
    return mp3_path, get_duration(mp3_path)


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


def create_trimmed_start(input_path, output_name, trim_percent):
    path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    trim_seconds = duration * trim_percent / 100.0
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-ss", str(trim_seconds),
        "-c:a", "libmp3lame", "-b:a", "128k",
        path
    ], capture_output=True, check=True)
    return path


def create_trimmed_end(input_path, output_name, trim_percent):
    path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    new_duration = duration * (1.0 - trim_percent / 100.0)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-t", str(new_duration),
        "-c:a", "libmp3lame", "-b:a", "128k",
        path
    ], capture_output=True, check=True)
    return path


def create_trimmed_middle(input_path, output_name, trim_percent):
    path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    trim_seconds = duration * trim_percent / 100.0
    first_half_end = (duration - trim_seconds) / 2
    second_half_start = first_half_end + trim_seconds
    base_name = output_name.replace('.mp3', '')
    part1 = os.path.join(TMP_DIR, f"{base_name}_part1.mp3")
    part2 = os.path.join(TMP_DIR, f"{base_name}_part2.mp3")
    concat_file = os.path.join(TMP_DIR, f"{base_name}_concat.txt")
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-t", str(first_half_end),
        "-c:a", "libmp3lame", "-b:a", "128k",
        part1
    ], capture_output=True, check=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-ss", str(second_half_start),
        "-c:a", "libmp3lame", "-b:a", "128k",
        part2
    ], capture_output=True, check=True)
    with open(concat_file, "w") as f:
        f.write(f"file '{os.path.abspath(part1)}'\n")
        f.write(f"file '{os.path.abspath(part2)}'\n")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c:a", "libmp3lame", "-b:a", "128k",
        path
    ], capture_output=True, check=True)
    for f_path in [part1, part2, concat_file]:
        if os.path.exists(f_path):
            os.remove(f_path)
    return path


def create_with_noise(input_path, output_name, noise_percent):
    """Add white noise at the given percentage level (0-100)."""
    path = os.path.join(TMP_DIR, output_name)
    duration = get_duration(input_path)
    noise_weight = noise_percent / 100.0
    signal_weight = 1.0 - noise_weight
    subprocess.run([
        "ffmpeg", "-y",
        "-i", input_path,
        "-f", "lavfi", "-i", f"anoisesrc=a=0.3:c=white:d={duration}",
        "-filter_complex", f"[0:a][1:a]amix=inputs=2:duration=first:weights={signal_weight} {noise_weight}",
        "-c:a", "libmp3lame", "-b:a", "128k",
        path
    ], capture_output=True, check=True)
    return path


def create_quality_reduced(input_path, output_name, reduction_percent):
    """Reduce quality by the given percentage."""
    path = os.path.join(TMP_DIR, output_name)
    quality_factor = 1.0 - (reduction_percent / 100.0)
    bitrate = int(128 * (quality_factor ** 6))
    bitrate = max(8, bitrate)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-c:a", "libmp3lame", "-b:a", f"{bitrate}k",
        path
    ], capture_output=True, check=True)
    return path


def create_mono(input_path, output_name):
    path = os.path.join(TMP_DIR, output_name)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-ac", "1",
        "-c:a", "libmp3lame", "-b:a", "128k",
        path
    ], capture_output=True, check=True)
    return path


def create_volume_adjusted(input_path, output_name, volume_factor):
    path = os.path.join(TMP_DIR, output_name)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", f"volume={volume_factor}",
        "-c:a", "libmp3lame", "-b:a", "128k",
        path
    ], capture_output=True, check=True)
    return path


def create_speed_adjusted(input_path, output_name, speed_factor):
    path = os.path.join(TMP_DIR, output_name)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", f"atempo={speed_factor}",
        "-c:a", "libmp3lame", "-b:a", "128k",
        path
    ], capture_output=True, check=True)
    return path


def query_match(query_path, audio_hamming_distance):
    """Query against already-indexed base audio."""
    with open(query_path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/match?audio_hamming_distance={audio_hamming_distance}",
            files={"file": (os.path.basename(query_path), f, "audio/mpeg")}
        )
    if r.status_code != 200:
        print(f"Match failed: {r.json()}")
        return {"matched": False, "audio": None, "transcript": None, "status": None, "audio_hamming_distance": None}
    
    matches = r.json()
    if not matches:
        return {"matched": False, "audio": None, "transcript": None, "status": None, "audio_hamming_distance": None}
    
    best = matches[0]
    matched = best.get("status") != "no_match"
    return {
        "matched": matched,
        "audio": best.get("audio_match_percent"),
        "transcript": best.get("transcript_match_percent"),
        "status": best.get("status"),
        "audio_hamming_distance": best.get("audio_hamming_distance")
    }


def run_calibrations_for_threshold(audio_hamming_distance, base_path, different_path):
    """Run all calibrations for a given audio Hamming threshold. Base audio already indexed."""
    results = {}
    total_correct = 0
    total_calibrations = 0

    # Build test cases: (key, name, expected_match, create_fn, is_trim_test)
    test_cases = [
        ("exact", "Exact match", True, lambda: base_path, False),
        ("different", "Different audio", False, lambda: different_path, False),
    ]

    # Trim start tests (index trimmed, query with base)
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"trim_start_{pct}"
        name = f"Trim start {pct}%"
        test_cases.append((key, name, expected, lambda p=pct: create_trimmed_start(base_path, f"trim_start_{p}.mp3", p), True))

    # Trim end tests
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"trim_end_{pct}"
        name = f"Trim end {pct}%"
        test_cases.append((key, name, expected, lambda p=pct: create_trimmed_end(base_path, f"trim_end_{p}.mp3", p), True))

    # Trim middle tests
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"trim_middle_{pct}"
        name = f"Trim middle {pct}%"
        test_cases.append((key, name, expected, lambda p=pct: create_trimmed_middle(base_path, f"trim_middle_{p}.mp3", p), True))

    # Noise tests
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"noise_{pct}"
        name = f"Noise {pct}%"
        test_cases.append((key, name, expected, lambda p=pct: create_with_noise(base_path, f"noise_{p}.mp3", p), False))

    # Quality reduced tests
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"quality_{pct}"
        name = f"Quality reduced {pct}%"
        test_cases.append((key, name, expected, lambda p=pct: create_quality_reduced(base_path, f"quality_{p}.mp3", p), False))

    # Mono - single test (binary operation)
    test_cases.append(("mono", "Mono", True, lambda: create_mono(base_path, "mono.mp3"), False))

    # Volume down tests
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"volume_down_{pct}"
        name = f"Volume -{pct}%"
        factor = 1.0 - pct / 100.0
        test_cases.append((key, name, expected, lambda f=factor, p=pct: create_volume_adjusted(base_path, f"vol_down_{p}.mp3", f), False))

    # Volume up tests
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"volume_up_{pct}"
        name = f"Volume +{pct}%"
        factor = 1.0 + pct / 100.0
        test_cases.append((key, name, expected, lambda f=factor, p=pct: create_volume_adjusted(base_path, f"vol_up_{p}.mp3", f), False))

    # Speed down tests
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"speed_down_{pct}"
        name = f"Speed -{pct}%"
        factor = 1.0 - pct / 100.0
        test_cases.append((key, name, expected, lambda f=factor, p=pct: create_speed_adjusted(base_path, f"speed_down_{p}.mp3", f), False))

    # Speed up tests
    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"speed_up_{pct}"
        name = f"Speed +{pct}%"
        factor = 1.0 + pct / 100.0
        test_cases.append((key, name, expected, lambda f=factor, p=pct: create_speed_adjusted(base_path, f"speed_up_{p}.mp3", f), False))

    for key, name, expected_match, create_fn, is_trim_test in test_cases:
        modified_path = create_fn()
        
        if is_trim_test:
            # For trim tests: index trimmed version, query with base
            reset()
            with open(modified_path, "rb") as f:
                r = requests.post(
                    f"{BASE_URL}/hash",
                    files={"file": (os.path.basename(modified_path), f, "audio/mpeg")}
                )
            if r.status_code != 200:
                print(f"Hash failed for {key}: {r.json()}")
                result = {"matched": False, "audio": None, "transcript": None, "status": None, "audio_hamming_distance": None}
            else:
                result = query_match(base_path, audio_hamming_distance)
        else:
            # For other tests: query modified against base (already indexed)
            result = query_match(modified_path, audio_hamming_distance)
        
        correct = result["matched"] == expected_match

        results[key] = {
            "name": name,
            "expected": expected_match,
            "matched": result["matched"],
            "correct": correct,
            "audio": result["audio"],
            "transcript": result["transcript"],
            "status": result["status"],
            "audio_hamming_distance": result["audio_hamming_distance"]
        }

        if correct:
            total_correct += 1
        total_calibrations += 1

    audio_values = [v["audio"] for v in results.values() if v.get("audio") is not None]
    transcript_values = [v["transcript"] for v in results.values() if v.get("transcript") is not None]
    both_pairs = [((v["audio"] + v["transcript"]) / 2.0) for v in results.values() if v.get("audio") is not None and v.get("transcript") is not None]

    avg_audio = mean(audio_values) if audio_values else None
    avg_transcript = mean(transcript_values) if transcript_values else None
    avg_both = mean(both_pairs) if both_pairs else None

    return {
        "audio_hamming_distance": audio_hamming_distance,
        "results": results,
        "overall_correct": total_correct,
        "overall_total": total_calibrations,
        "overall_rate": total_correct / total_calibrations if total_calibrations else 0,
        "avg_audio": avg_audio,
        "avg_transcript": avg_transcript,
        "avg_both": avg_both
    }


def find_optimal_threshold(hamming_values):
    start_time = time.time()
    
    print(f"Calibrating audio Hamming thresholds: {hamming_values}")
    print("=" * 80)
    print()
    print("Creating base audio with speech...", end=" ", flush=True)
    base_path, duration = create_speech_audio("base.mp3", LOREM_IPSUM, speed=130)
    print(f"done ({duration:.1f}s)")
    
    print("Creating different audio...", end=" ", flush=True)
    different_path, diff_duration = create_speech_audio("different.mp3", DIFFERENT_TEXT, speed=160)
    print(f"done ({diff_duration:.1f}s)")
    print()

    all_results = []
    for hamming in hamming_values:
        print(f"Calibrating audio_hamming_distance={hamming}...", end=" ", flush=True)
        
        # Reset and index base audio for non-trim tests
        reset()
        with open(base_path, "rb") as f:
            r = requests.post(
                f"{BASE_URL}/hash",
                files={"file": ("base.mp3", f, "audio/mpeg")}
            )
        if r.status_code != 200:
            print(f"Hash failed: {r.json()}")
            continue
        
        result = run_calibrations_for_threshold(hamming, base_path, different_path)
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
        ("different", "Different audio (should NOT match)"),
    ]

    # Add trim start tests
    for pct in PERCENTAGES:
        key = f"trim_start_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Trim start {pct}% (should {expected})"
        test_display.append((key, name))

    # Add trim end tests
    for pct in PERCENTAGES:
        key = f"trim_end_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Trim end {pct}% (should {expected})"
        test_display.append((key, name))

    # Add trim middle tests
    for pct in PERCENTAGES:
        key = f"trim_middle_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Trim middle {pct}% (should {expected})"
        test_display.append((key, name))

    # Add noise tests
    for pct in PERCENTAGES:
        key = f"noise_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Noise {pct}% (should {expected})"
        test_display.append((key, name))

    # Add quality tests
    for pct in PERCENTAGES:
        key = f"quality_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Quality reduced {pct}% (should {expected})"
        test_display.append((key, name))

    # Add mono
    test_display.append(("mono", "Mono (should match)"))

    # Add volume down tests
    for pct in PERCENTAGES:
        key = f"volume_down_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Volume -{pct}% (should {expected})"
        test_display.append((key, name))

    # Add volume up tests
    for pct in PERCENTAGES:
        key = f"volume_up_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Volume +{pct}% (should {expected})"
        test_display.append((key, name))

    # Add speed down tests
    for pct in PERCENTAGES:
        key = f"speed_down_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Speed -{pct}% (should {expected})"
        test_display.append((key, name))

    # Add speed up tests
    for pct in PERCENTAGES:
        key = f"speed_up_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Speed +{pct}% (should {expected})"
        test_display.append((key, name))

    lines.append("")
    lines.append(f"{'Calibration':<40} | {'Pass':<6} | {'Audio':<8} | {'Trans':<8} | {'Hamming':<10} | {'Status':<12}")
    lines.append("-" * 100)

    for key, name in test_display:
        r = stats["results"].get(key)
        if r is None:
            continue
        pass_str = "✓" if r.get("correct") else "✗"
        audio_str = f"{r['audio']:.0f}%" if r.get('audio') is not None else "-"
        trans_str = f"{r['transcript']:.0f}%" if r.get('transcript') is not None else "-"
        hamming_str = f"{r['audio_hamming_distance']}" if r.get('audio_hamming_distance') is not None else "-"
        status_str = str(r.get("status")) if r.get("status") is not None else "-"
        lines.append(f"{name:<40} | {pass_str:<6} | {audio_str:<8} | {trans_str:<8} | {hamming_str:<10} | {status_str:<12}")

    lines.append("-" * 100)
    avg_audio = stats.get("avg_audio")
    avg_transcript = stats.get("avg_transcript")
    avg_both = stats.get("avg_both")
    avg_audio_str = f"{avg_audio:.1f}%" if avg_audio is not None else "-"
    avg_transcript_str = f"{avg_transcript:.1f}%" if avg_transcript is not None else "-"
    avg_both_str = f"{avg_both:.1f}%" if avg_both is not None else "-"
    lines.append(f"{'AVERAGES':<40} | {'':<6} | {avg_audio_str:<8} | {avg_transcript_str:<8} | {'':<10} | {'Both:'+avg_both_str:<12}")
    lines.append(f"{'OVERALL':<40} | {stats['overall_correct']}/{stats['overall_total']}  | {stats['overall_rate']*100:.0f}%")
    return "\n".join(lines)


def format_all_results(all_results):
    """Format all threshold results as a string."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("ALL AUDIO HAMMING THRESHOLDS")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"{'Hamming':<12} | {'Correct':<10} | {'Rate':<10} | {'AvgA':<8} | {'AvgT':<8} | {'AvgBoth':<8}")
    lines.append("-" * 70)
    for r in sorted(all_results, key=lambda x: -x["overall_rate"]):
        avg_a = f"{r['avg_audio']:.1f}%" if r.get("avg_audio") is not None else "-"
        avg_t = f"{r['avg_transcript']:.1f}%" if r.get("avg_transcript") is not None else "-"
        avg_b = f"{r['avg_both']:.1f}%" if r.get("avg_both") is not None else "-"
        lines.append(f"{r['audio_hamming_distance']:<12} | {r['overall_correct']}/{r['overall_total']:<7} | {r['overall_rate']*100:.0f}%      | {avg_a:<8} | {avg_t:<8} | {avg_b:<8}")
    return "\n".join(lines)


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


def print_results(stats):
    print(format_results(stats))


def print_all_results(all_results):
    print(format_all_results(all_results))


def export_results(best, all_results, elapsed_time, filename="./results/calibrate_audio.txt"):
    """Export the final results to a file."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    lines = []
    lines.append("=" * 80)
    lines.append("Audio Hamming Distance Calibration Results")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Duration: {format_duration(elapsed_time)}")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Calibration criteria (threshold = 85%):")
    lines.append("  - 12,14% modification: should MATCH (≤15%)")
    lines.append("  - 16,18% modification: should NOT MATCH (>15%)")
    lines.append("")
    lines.append("Test categories:")
    lines.append("  - Trim start/end/middle: pct% removed")
    lines.append("  - Noise: pct% noise mixed in")
    lines.append("  - Quality: bitrate = 128k * (1 - pct/100)^6")
    lines.append("  - Mono: always should match")
    lines.append("  - Volume: ±pct% volume change")
    lines.append("  - Speed: ±pct% speed change")
    lines.append("")
    lines.append("Note: Audio now uses Hamming distance (0-256 bits) instead of L2.")
    lines.append("Chromaprint fingerprints are converted to 256-bit binary vectors.")
    lines.append("")
    lines.append(format_all_results(all_results))
    lines.append("")
    lines.append("=" * 80)
    lines.append(f"BEST: audio_hamming_distance={best['audio_hamming_distance']}")
    lines.append("=" * 80)
    lines.append(format_results(best))
    lines.append("")
    lines.append(f"AUDIO_HAMMING_DISTANCE={best['audio_hamming_distance']}")
    lines.append("")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nResults exported to {filename}")


def main():
    print("=" * 80)
    print("Finding Optimal Audio Hamming Distance")
    print("=" * 80)
    print()
    print("Calibration criteria (threshold = 85%):")
    print("  - 12,14% modification: should MATCH")
    print("  - 16,18% modification: should NOT MATCH")
    print()
    print("Tests: Trim (start/end/middle), Noise, Quality, Mono, Volume (±), Speed (±)")
    print()
    print("Note: Audio now uses Hamming distance (0-256 bits) like video/image.")
    print()

    try:
        setup()
        # Audio hamming range: 0-256 bits, testing reasonable values
        # Lower = stricter, higher = more permissive
        best, all_results, elapsed_time = find_optimal_threshold(
            hamming_values=[28]
        )
        print_all_results(all_results)
        print()
        print("=" * 80)
        print(f"BEST: audio_hamming_distance={best['audio_hamming_distance']}")
        print("=" * 80)
        print_results(best)
        print()
        print(f"AUDIO_HAMMING_DISTANCE={best['audio_hamming_distance']}")
        print(f"\nCompleted in {format_duration(elapsed_time)}")
        export_results(best, all_results, elapsed_time, "./results/calibrate_audio.txt")
    finally:
        cleanup()


if __name__ == "__main__":
    main()