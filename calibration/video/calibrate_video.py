#!/usr/bin/env python3
# calibration/calibrate_video.py
"""
Video threshold calibration script.

Tests video matching across different hamming thresholds and modification levels.
Focuses on: crop (all 4 sides), trim (start/end/middle), speed (+/-)

Criteria:
- 100% identical = exact_match
- ≤15% modification = near_match  
- >15% modification = no_match

Usage:
    python tests/calibrate_video.py

Outputs:
    results/calibrate_video.txt - Full results
    results/calibrate_video.png - Chart of best results
"""
import requests
import subprocess
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
import matplotlib.pyplot as plt

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
TMP_DIR = "./tmp/video_threshold_calibration"
VIDEO_DURATION = 30  # seconds

# Percentages for all tests
# 10,12,14 should MATCH (≤15%)
# 16,18,20 should NOT MATCH (>15%)
PERCENTAGES = [10, 12, 14, 16, 18, 20]
MATCH_THRESHOLD = 15  # ≤15% should match

# Hamming distances to test: 0 to 200 in steps of 2
# 0 = strictest, 200 = loosest (78% bit difference)
VIDEO_HAMMING_VALUES = list(range(0, 201, 2))  # 0, 2, 4, ..., 200 (101 values)

# Fixed threshold, no offset
VIDEO_THRESHOLD = 0.85
VIDEO_OFFSET = 0.0


def setup():
    os.makedirs(TMP_DIR, exist_ok=True)


def cleanup():
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    parent = Path(TMP_DIR).parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()


def reset():
    requests.post(f"{BASE_URL}/reset", timeout=30)
    for _ in range(20):
        try:
            r = requests.get(f"{BASE_URL}/stats", timeout=5)
            if r.status_code == 200:
                stats = r.json()
                if stats.get("total_video_hashes", 0) == 0:
                    return
        except:
            pass
        time.sleep(0.2)


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
    for tool in ["ffmpeg", "ffprobe"]:
        result = subprocess.run(["which", tool], capture_output=True)
        if result.returncode != 0:
            print(f"ERROR: {tool} not installed")
            sys.exit(1)
    print("Dependencies OK: ffmpeg, ffprobe")


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
    duration = get_duration(path)
    return path, duration


def create_different_video(filename):
    """Create a completely different video."""
    path = os.path.join(TMP_DIR, filename)
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"cellauto=s=640x480:rate=24:rule=110:random_seed=42,trim=duration={VIDEO_DURATION}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-an",
        path
    ], capture_output=True, check=True)
    return path


# =============================================================================
# CROP MODIFICATIONS
# =============================================================================

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


# =============================================================================
# TRIM MODIFICATIONS
# =============================================================================

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
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", part1
    ], capture_output=True, check=True)
    
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-ss", str(second_half_start),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", part2
    ], capture_output=True, check=True)
    
    with open(concat_file, "w") as f:
        f.write(f"file '{os.path.abspath(part1)}'\n")
        f.write(f"file '{os.path.abspath(part2)}'\n")
    
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path
    ], capture_output=True, check=True)
    
    for f_path in [part1, part2, concat_file]:
        if os.path.exists(f_path):
            os.remove(f_path)
    
    return path


# =============================================================================
# SPEED MODIFICATIONS
# =============================================================================

def create_speed_change(input_path, output_name, speed_factor):
    path = os.path.join(TMP_DIR, output_name)
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"setpts={1/speed_factor}*PTS",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path
    ], capture_output=True, check=True)
    return path


# =============================================================================
# MATCHING FUNCTIONS
# =============================================================================

def hash_video(video_path):
    with open(video_path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/hash",
            files={"file": ("video.mp4", f, "video/mp4")},
            timeout=300
        )
        if r.status_code != 200:
            print(f"Hash failed: {r.status_code} - {r.text}")
            return None
        return r.json()


def match_video(query_path, video_max_hamming):
    with open(query_path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/match",
            files={"file": ("query.mp4", f, "video/mp4")},
            params={
                "video_threshold": VIDEO_THRESHOLD,
                "video_offset": VIDEO_OFFSET,
                "video_max_hamming": video_max_hamming
            },
            timeout=300
        )
    
    if r.status_code != 200:
        return {"matched": False, "video": None, "status": None, "item_id": None}
    
    matches = r.json()
    if not matches:
        return {"matched": False, "video": None, "status": "no_match", "item_id": None}
    
    best = matches[0]
    status = best.get("status", "no_match")
    matched = status in ["exact_match", "near_match"]
    
    return {
        "matched": matched,
        "video": best.get("video_match_percent"),
        "status": status,
        "item_id": best.get("item_id")
    }


# =============================================================================
# TEST RUNNER
# =============================================================================

def run_tests_for_hamming(video_max_hamming, base_path, base_item_id, different_path):
    """Run all tests for a specific hamming threshold."""
    results = {}
    total_correct = 0
    total_tests = 0
    
    test_cases = []
    
    # Controls
    test_cases.append(("exact", "Exact match", "exact_match", lambda: base_path, "query"))
    test_cases.append(("different", "Different video", "no_match", lambda: different_path, "query"))
    
    # Crop tests
    for side, create_fn in [
        ("right", create_crop_right),
        ("left", create_crop_left),
        ("top", create_crop_top),
        ("bottom", create_crop_bottom)
    ]:
        for pct in PERCENTAGES:
            expected = "near_match" if pct <= MATCH_THRESHOLD else "no_match"
            test_cases.append((
                f"crop_{side}_{pct}",
                f"Crop {side} {pct}%",
                expected,
                lambda p=pct, s=side, fn=create_fn: fn(base_path, f"crop_{s}_{p}.mp4", p),
                "query"
            ))
    
    # Trim tests
    for location, create_fn in [
        ("start", create_trim_start),
        ("end", create_trim_end),
        ("middle", create_trim_middle)
    ]:
        for pct in PERCENTAGES:
            expected = "near_match" if pct <= MATCH_THRESHOLD else "no_match"
            test_cases.append((
                f"trim_{location}_{pct}",
                f"Trim {location} {pct}%",
                expected,
                lambda p=pct, l=location, fn=create_fn: fn(base_path, f"trim_{l}_{p}.mp4", p),
                "index"
            ))
    
    # Speed tests
    for pct in PERCENTAGES:
        expected = "near_match" if pct <= MATCH_THRESHOLD else "no_match"
        speed_down = 1.0 - pct / 100.0
        speed_up = 1.0 + pct / 100.0
        
        test_cases.append((
            f"speed_down_{pct}",
            f"Speed -{pct}%",
            expected,
            lambda s=speed_down, p=pct: create_speed_change(base_path, f"speed_down_{p}.mp4", s),
            "query"
        ))
        test_cases.append((
            f"speed_up_{pct}",
            f"Speed +{pct}%",
            expected,
            lambda s=speed_up, p=pct: create_speed_change(base_path, f"speed_up_{p}.mp4", s),
            "query"
        ))
    
    # Run all tests
    for key, name, expected_status, create_fn, test_type in test_cases:
        if test_type == "query":
            query_path = create_fn()
            result = match_video(query_path, video_max_hamming)
        else:
            modified_path = create_fn()
            reset()
            hash_result = hash_video(modified_path)
            if not hash_result:
                result = {"matched": False, "video": None, "status": "error", "item_id": None}
            else:
                result = match_video(base_path, video_max_hamming)
            reset()
            hash_video(base_path)
        
        actual_status = result.get("status", "no_match")
        
        if expected_status == "exact_match":
            correct = actual_status == "exact_match"
        elif expected_status == "near_match":
            correct = actual_status in ["exact_match", "near_match"]
        else:
            correct = actual_status == "no_match"
        
        results[key] = {
            "name": name,
            "expected": expected_status,
            "actual": actual_status,
            "correct": correct,
            "video_pct": result.get("video"),
            "item_id": result.get("item_id")
        }
        
        if correct:
            total_correct += 1
        total_tests += 1
    
    return {
        "video_max_hamming": video_max_hamming,
        "results": results,
        "correct": total_correct,
        "total": total_tests,
        "rate": total_correct / total_tests if total_tests > 0 else 0
    }


def run_calibration():
    """Run calibration across all hamming values."""
    start_time = time.time()
    
    print(f"Testing video_max_hamming values: {VIDEO_HAMMING_VALUES[0]} to {VIDEO_HAMMING_VALUES[-1]} (step 2)")
    print(f"Total values to test: {len(VIDEO_HAMMING_VALUES)}")
    print(f"Video threshold: {VIDEO_THRESHOLD} (no offset)")
    print("=" * 80)
    print()
    
    print("Creating base video...", end=" ", flush=True)
    base_path, duration = create_base_video("base.mp4")
    print(f"done ({duration:.1f}s)")
    
    print("Creating different video...", end=" ", flush=True)
    different_path = create_different_video("different.mp4")
    print("done")
    print()
    
    all_results = []
    
    for i, hamming in enumerate(VIDEO_HAMMING_VALUES):
        print(f"[{i+1}/{len(VIDEO_HAMMING_VALUES)}] Testing video_max_hamming={hamming}...", end=" ", flush=True)
        
        reset()
        hash_result = hash_video(base_path)
        if not hash_result:
            print("Failed to hash base video")
            continue
        base_item_id = hash_result.get("item_id")
        
        result = run_tests_for_hamming(hamming, base_path, base_item_id, different_path)
        all_results.append(result)
        
        print(f"{result['correct']}/{result['total']} ({result['rate']*100:.0f}%)")
    
    elapsed_time = time.time() - start_time
    
    return all_results, elapsed_time


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_summary(all_results):
    lines = []
    lines.append("")
    lines.append("=" * 100)
    lines.append("HAMMING THRESHOLD COMPARISON")
    lines.append("=" * 100)
    lines.append("")
    lines.append(f"{'Hamming':<10} | {'Correct':<12} | {'Rate':<8} | {'Crop':<12} | {'Trim':<12} | {'Speed':<12}")
    lines.append("-" * 100)
    
    for r in sorted(all_results, key=lambda x: -x["rate"]):
        crop_correct = sum(1 for k, v in r["results"].items() if k.startswith("crop_") and v["correct"])
        crop_total = sum(1 for k in r["results"] if k.startswith("crop_"))
        
        trim_correct = sum(1 for k, v in r["results"].items() if k.startswith("trim_") and v["correct"])
        trim_total = sum(1 for k in r["results"] if k.startswith("trim_"))
        
        speed_correct = sum(1 for k, v in r["results"].items() if k.startswith("speed_") and v["correct"])
        speed_total = sum(1 for k in r["results"] if k.startswith("speed_"))
        
        lines.append(
            f"{r['video_max_hamming']:<10} | "
            f"{r['correct']}/{r['total']:<9} | "
            f"{r['rate']*100:>5.1f}%  | "
            f"{crop_correct}/{crop_total:<9} | "
            f"{trim_correct}/{trim_total:<9} | "
            f"{speed_correct}/{speed_total:<9}"
        )
    
    return "\n".join(lines)


def format_detailed_results(result):
    lines = []
    lines.append("")
    lines.append(f"Detailed results for video_max_hamming={result['video_max_hamming']}")
    lines.append("-" * 80)
    lines.append(f"{'Test':<30} | {'Expected':<12} | {'Actual':<12} | {'Video %':<10} | {'Pass'}")
    lines.append("-" * 80)
    
    categories = [
        ("Controls", ["exact", "different"]),
        ("Crop Right", [f"crop_right_{p}" for p in PERCENTAGES]),
        ("Crop Left", [f"crop_left_{p}" for p in PERCENTAGES]),
        ("Crop Top", [f"crop_top_{p}" for p in PERCENTAGES]),
        ("Crop Bottom", [f"crop_bottom_{p}" for p in PERCENTAGES]),
        ("Trim Start", [f"trim_start_{p}" for p in PERCENTAGES]),
        ("Trim End", [f"trim_end_{p}" for p in PERCENTAGES]),
        ("Trim Middle", [f"trim_middle_{p}" for p in PERCENTAGES]),
        ("Speed Down", [f"speed_down_{p}" for p in PERCENTAGES]),
        ("Speed Up", [f"speed_up_{p}" for p in PERCENTAGES]),
    ]
    
    for cat_name, keys in categories:
        lines.append(f"\n{cat_name}:")
        for key in keys:
            if key not in result["results"]:
                continue
            r = result["results"][key]
            video_str = f"{r['video_pct']:.1f}%" if r['video_pct'] is not None else "-"
            pass_str = "✓" if r["correct"] else "✗"
            lines.append(
                f"  {r['name']:<28} | {r['expected']:<12} | {r['actual']:<12} | {video_str:<10} | {pass_str}"
            )
    
    return "\n".join(lines)


def export_txt(all_results, best, elapsed_time, filename):
    parent_dir = os.path.dirname(filename)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    
    lines = []
    lines.append("=" * 100)
    lines.append("Video Threshold Calibration Results")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Duration: {format_duration(elapsed_time)}")
    lines.append("=" * 100)
    lines.append("")
    lines.append(f"Video threshold: {VIDEO_THRESHOLD} (no offset)")
    lines.append("")
    lines.append("Calibration criteria:")
    lines.append("  - Exact match (100% identical) = exact_match")
    lines.append("  - ≤15% modification (10%, 12%, 14%) = near_match")
    lines.append("  - >15% modification (16%, 18%, 20%) = no_match")
    lines.append("")
    lines.append("Test categories:")
    lines.append("  - Crop: right, left, top, bottom (4 sides × 6 percentages = 24 tests)")
    lines.append("  - Trim: start, end, middle (3 locations × 6 percentages = 18 tests)")
    lines.append("  - Speed: increase, decrease (2 directions × 6 percentages = 12 tests)")
    lines.append("  - Controls: exact match, different video (2 tests)")
    lines.append("  - Total: 56 tests per hamming value")
    lines.append("")
    lines.append(f"Hamming values tested: {VIDEO_HAMMING_VALUES[0]} to {VIDEO_HAMMING_VALUES[-1]} (step 2)")
    lines.append(f"Total configurations: {len(VIDEO_HAMMING_VALUES)}")
    lines.append("")
    
    lines.append(format_summary(all_results))
    
    lines.append("")
    lines.append("=" * 100)
    lines.append(f"BEST: video_max_hamming={best['video_max_hamming']} ({best['rate']*100:.1f}% correct)")
    lines.append("=" * 100)
    lines.append(format_detailed_results(best))
    
    lines.append("")
    lines.append("=" * 100)
    lines.append("RECOMMENDATION")
    lines.append("=" * 100)
    lines.append(f"video_max_hamming = {best['video_max_hamming']}")
    lines.append("")
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    print(f"Results exported to {filename}")


# =============================================================================
# PLOTTING
# =============================================================================

def plot_results(best, output_path):
    """Generate chart for the best hamming results."""
    hamming = best['video_max_hamming']
    threshold = VIDEO_THRESHOLD * 100
    
    fig, axes = plt.subplots(3, 4, figsize=(18, 13))
    fig.suptitle(f'Video Matching Calibration Results\n'
                 f'video_max_hamming={hamming}, threshold={threshold:.0f}%', 
                 fontsize=14, fontweight='bold')
    
    # Prepare data by category
    categories_data = {
        'crop_right': [],
        'crop_left': [],
        'crop_top': [],
        'crop_bottom': [],
        'trim_start': [],
        'trim_end': [],
        'trim_middle': [],
        'speed_down': [],
        'speed_up': [],
        'special': []
    }
    
    for key, r in best['results'].items():
        if key == 'exact':
            categories_data['special'].append({
                'name': 'Exact Match',
                'pct': 0,
                'video': r['video_pct'] or 100,
                'status': r['actual'],
                'pytest_passed': r['correct']
            })
        elif key == 'different':
            categories_data['special'].append({
                'name': 'Different Video',
                'pct': 0,
                'video': r['video_pct'] or 0,
                'status': r['actual'],
                'pytest_passed': r['correct']
            })
        else:
            # Extract category and percentage
            parts = key.rsplit('_', 1)
            if len(parts) == 2:
                cat = parts[0]
                try:
                    pct = int(parts[1])
                except ValueError:
                    continue
                
                if cat in categories_data:
                    categories_data[cat].append({
                        'pct': pct,
                        'video': r['video_pct'] or 0,
                        'status': r['actual'],
                        'pytest_passed': r['correct']
                    })
    
    # Sort by percentage
    for cat in categories_data:
        if cat != 'special':
            categories_data[cat].sort(key=lambda x: x['pct'])
    
    # Row 1: Crop tests
    crop_plots = [
        ('Crop RIGHT', categories_data['crop_right']),
        ('Crop LEFT', categories_data['crop_left']),
        ('Crop TOP', categories_data['crop_top']),
        ('Crop BOTTOM', categories_data['crop_bottom']),
    ]
    
    for ax, (title, data) in zip(axes[0], crop_plots):
        plot_subplot(ax, title, data, threshold)
    
    # Row 2: Trim tests + Special
    trim_plots = [
        ('Trim START', categories_data['trim_start']),
        ('Trim END', categories_data['trim_end']),
        ('Trim MIDDLE', categories_data['trim_middle']),
    ]
    
    for ax, (title, data) in zip(axes[1][:3], trim_plots):
        plot_subplot(ax, title, data, threshold)
    
    plot_special_cases(axes[1][3], categories_data['special'], threshold)
    
    # Row 3: Speed tests
    speed_plots = [
        ('Speed Decrease (-)', categories_data['speed_down']),
        ('Speed Increase (+)', categories_data['speed_up']),
    ]
    
    for ax, (title, data) in zip(axes[2][:2], speed_plots):
        plot_subplot(ax, title, data, threshold)
    
    axes[2][2].axis('off')
    axes[2][3].axis('off')
    
    plt.tight_layout()
    plt.subplots_adjust(top=0.92, hspace=0.35, wspace=0.25)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Chart saved to {output_path}")


def plot_subplot(ax, title, data, threshold):
    if not data:
        ax.set_title(f'{title} (no data)')
        ax.set_ylim(0, 100)
        ax.set_xlim(0, 100)
        return
    
    pcts = [d['pct'] for d in data]
    video_vals = [d['video'] for d in data]
    pytest_results = [d.get('pytest_passed', True) for d in data]
    
    pass_count = sum(1 for p in pytest_results if p)
    
    min_video = min(video_vals) if video_vals else 0
    if min_video > 75:
        ylim = (min(min_video - 5, 75), 100)
    else:
        ylim = (0, 100)
    
    ax.plot(pcts, video_vals, 'b-', linewidth=2, label='Video Match %')
    
    for pct, video, passed in zip(pcts, video_vals, pytest_results):
        color = '#22c55e' if passed else '#ef4444'
        ax.plot(pct, video, 'o', markersize=10, color=color, zorder=5)
        indicator = '✓' if passed else '✗'
        ax.annotate(indicator, (pct, video), textcoords="offset points", 
                    xytext=(0, 8), ha='center', fontsize=8, fontweight='bold', color=color)
    
    ax.axhline(y=threshold, color='blue', linestyle='--', alpha=0.7, linewidth=1,
               label=f'Threshold: {threshold:.0f}%')
    
    if pcts:
        min_pct = min(pcts) - 1
        max_pct = max(pcts) + 1
        
        match_pcts = [d['pct'] for d in data if d['status'] in ['near_match', 'exact_match']]
        no_match_pcts = [d['pct'] for d in data if d['status'] == 'no_match']
        
        if match_pcts and no_match_pcts:
            last_match = max(match_pcts)
            first_no_match = min(no_match_pcts)
            boundary = (last_match + first_no_match) / 2
            ax.axvspan(min_pct, boundary, alpha=0.1, color='green')
            ax.axvspan(boundary, max_pct, alpha=0.1, color='red')
        elif match_pcts:
            ax.axvspan(min_pct, max_pct, alpha=0.1, color='green')
        elif no_match_pcts:
            ax.axvspan(min_pct, max_pct, alpha=0.1, color='red')
    
    ax.set_title(f'{title} ({pass_count}/{len(data)})', fontsize=10, fontweight='bold')
    ax.set_ylim(ylim[0], ylim[1])
    ax.set_xlim(min(pcts) - 1, max(pcts) + 1)
    ax.set_xticks(pcts)
    ax.set_xlabel('Modification %', fontsize=8)
    ax.set_ylabel('Match %', fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis='both', labelsize=8)
    ax.legend(loc='lower left', fontsize=6)


def plot_special_cases(ax, data, threshold):
    if not data:
        ax.axis('off')
        return
    
    names = [s.get('name', 'Unknown') for s in data]
    values = [s.get('video', 0) for s in data]
    pytest_results = [s.get('pytest_passed', True) for s in data]
    colors = ['#22c55e' if p else '#ef4444' for p in pytest_results]
    
    bars = ax.bar(names, values, color=colors, edgecolor='black', linewidth=1)
    ax.axhline(y=threshold, color='blue', linestyle='--', alpha=0.7, linewidth=1,
              label=f'Threshold: {threshold:.0f}%')
    ax.set_ylim(0, 105)
    ax.set_ylabel('Match %', fontsize=8)
    ax.set_title('Special Cases', fontsize=10, fontweight='bold')
    ax.tick_params(axis='x', labelsize=8, rotation=15)
    ax.tick_params(axis='y', labelsize=8)
    ax.grid(True, alpha=0.3, axis='y')
    ax.legend(loc='lower right', fontsize=6)
    
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, 
               f'{val:.1f}%', ha='center', va='bottom', fontsize=8)


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 80)
    print("Video Threshold Calibration")
    print("=" * 80)
    print()
    
    setup()
    check_dependencies()
    print()
    
    print("Calibration criteria:")
    print("  - 100% identical = exact_match")
    print("  - ≤15% modification (10%, 12%, 14%) = near_match")
    print("  - >15% modification (16%, 18%, 20%) = no_match")
    print()
    print(f"Video threshold: {VIDEO_THRESHOLD} (no offset)")
    print()
    print("Tests per hamming value:")
    print("  - Crop (right/left/top/bottom) × 6 pct = 24 tests")
    print("  - Trim (start/end/middle) × 6 pct = 18 tests")
    print("  - Speed (+/-) × 6 pct = 12 tests")
    print("  - Controls (exact, different) = 2 tests")
    print("  - Total: 56 tests")
    print()
    
    try:
        all_results, elapsed_time = run_calibration()
        
        print()
        print(format_summary(all_results))
        
        best = max(all_results, key=lambda x: x["rate"])
        
        print()
        print("=" * 80)
        print(f"BEST: video_max_hamming={best['video_max_hamming']} ({best['rate']*100:.1f}% correct)")
        print("=" * 80)
        print(format_detailed_results(best))
        print()
        print(f"Completed in {format_duration(elapsed_time)}")
        
        # Export results to same directory as script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        export_txt(all_results, best, elapsed_time, os.path.join(script_dir, "calibrate_video.txt"))
        plot_results(best, os.path.join(script_dir, "calibrate_video.png"))
        
    finally:
        cleanup()


if __name__ == "__main__":
    main()