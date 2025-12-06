# tests/calibrate_image.py
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import io
import os
import shutil
import time
import sys
from datetime import datetime
from pathlib import Path

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
TMP_DIR = "./tmp/image_threshold_calibration"
REQUEST_TIMEOUT = 60

# Percentages for all tests
# 6,8,10 should MATCH (≤10%)
# 12,14 should NOT MATCH (>10%)
PERCENTAGES = [6, 8, 10, 12, 14]
MATCH_THRESHOLD = 10  # ≤10% should match


def setup():
    os.makedirs(TMP_DIR, exist_ok=True)


def cleanup():
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    parent = Path(TMP_DIR).parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()


def check_health():
    """Check if the service is healthy before starting tests."""
    print(f"Checking service health at {BASE_URL}...", end=" ", flush=True)
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=10)
        if r.status_code == 200:
            print("OK")
            return True
        else:
            print(f"FAILED (status {r.status_code})")
            return False
    except requests.exceptions.ConnectionError:
        print("FAILED (connection refused)")
        return False
    except Exception as e:
        print(f"FAILED ({e})")
        return False


def reset():
    try:
        r = requests.post(f"{BASE_URL}/reset", timeout=30)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception as e:
        print(f"Reset failed: {e}")
        return None


def hash_file(file_path, mime_type="image/png"):
    """Hash and index a file."""
    try:
        with open(file_path, "rb") as f:
            r = requests.post(
                f"{BASE_URL}/hash",
                files={"file": (os.path.basename(file_path), f, mime_type)},
                timeout=REQUEST_TIMEOUT
            )
        if r.status_code == 200:
            return r.json()
        else:
            print(f"Hash failed ({r.status_code}): {r.text}")
            return None
    except Exception as e:
        print(f"Hash error: {e}")
        return None


def create_pattern_image(seed=42, width=640, height=480):
    np.random.seed(seed)

    arr = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)

    for y in range(height):
        for x in range(width):
            arr[y, x, 0] = np.clip(arr[y, x, 0] * (x / width), 0, 255)
            arr[y, x, 1] = np.clip(arr[y, x, 1] * (y / height), 0, 255)

    img = Image.fromarray(arr)
    draw = ImageDraw.Draw(img)

    for _ in range(50):
        x1 = np.random.randint(0, width)
        y1 = np.random.randint(0, height)
        x2 = np.random.randint(0, width)
        y2 = np.random.randint(0, height)
        color = tuple(np.random.randint(0, 256, 3).tolist())
        line_width = np.random.randint(1, 5)
        draw.line([(x1, y1), (x2, y2)], fill=color, width=line_width)

    for _ in range(20):
        x1 = np.random.randint(0, width)
        y1 = np.random.randint(0, height)
        x2 = np.random.randint(0, width)
        y2 = np.random.randint(0, height)
        color = tuple(np.random.randint(0, 256, 3).tolist())
        draw.rectangle([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)], outline=color)

    for _ in range(15):
        x = np.random.randint(50, width - 50)
        y = np.random.randint(50, height - 50)
        r = np.random.randint(10, 80)
        color = tuple(np.random.randint(0, 256, 3).tolist())
        draw.ellipse([x - r, y - r, x + r, y + r], outline=color, width=2)

    return np.array(img)


def create_different_image(seed=9999, width=640, height=480):
    np.random.seed(seed)

    arr = np.zeros((height, width, 3), dtype=np.uint8)
    bg_color = np.random.randint(0, 256, 3)
    arr[:, :] = bg_color

    img = Image.fromarray(arr)
    draw = ImageDraw.Draw(img)

    for _ in range(10):
        x1 = np.random.randint(0, width)
        y1 = np.random.randint(0, height)
        x2 = np.random.randint(0, width)
        y2 = np.random.randint(0, height)
        color = tuple(np.random.randint(0, 256, 3).tolist())
        draw.rectangle([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)], fill=color)

    for _ in range(5):
        x = np.random.randint(50, width - 50)
        y = np.random.randint(50, height - 50)
        r = np.random.randint(20, 50)
        color = tuple(np.random.randint(0, 256, 3).tolist())
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)

    return np.array(img)


def save_image(arr, filename, fmt="PNG"):
    path = os.path.join(TMP_DIR, filename)
    img = Image.fromarray(arr)
    img.save(path, format=fmt)
    return path


def create_cutoff_image(base_arr, output_name, cutoff_percent, side="right"):
    img = Image.fromarray(base_arr)
    w, h = img.size

    if side == "right":
        cut_x = int(w * (1.0 - cutoff_percent / 100.0))
        cropped = img.crop((0, 0, cut_x, h))
        new_img = Image.new("RGB", (w, h), (0, 0, 0))
        new_img.paste(cropped, (0, 0))
    elif side == "left":
        cut_x = int(w * cutoff_percent / 100.0)
        cropped = img.crop((cut_x, 0, w, h))
        new_img = Image.new("RGB", (w, h), (0, 0, 0))
        new_img.paste(cropped, (cut_x, 0))
    elif side == "top":
        cut_y = int(h * cutoff_percent / 100.0)
        cropped = img.crop((0, cut_y, w, h))
        new_img = Image.new("RGB", (w, h), (0, 0, 0))
        new_img.paste(cropped, (0, cut_y))
    elif side == "bottom":
        cut_y = int(h * (1.0 - cutoff_percent / 100.0))
        cropped = img.crop((0, 0, w, cut_y))
        new_img = Image.new("RGB", (w, h), (0, 0, 0))
        new_img.paste(cropped, (0, 0))
    else:
        new_img = img

    path = os.path.join(TMP_DIR, output_name)
    new_img.save(path, format="PNG")
    return path


def create_noise_image(base_arr, output_name, level=30):
    arr = base_arr.copy()
    noise = np.random.randint(-level, level + 1, arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    path = os.path.join(TMP_DIR, output_name)
    Image.fromarray(arr).save(path, format="PNG")
    return path


def create_brightness_image(base_arr, output_name, level=50):
    arr = np.clip(base_arr.astype(np.int16) + level, 0, 255).astype(np.uint8)
    path = os.path.join(TMP_DIR, output_name)
    Image.fromarray(arr).save(path, format="PNG")
    return path


def create_contrast_image(base_arr, output_name, factor=1.5):
    arr = np.clip((base_arr.astype(np.float32) - 128) * factor + 128, 0, 255).astype(np.uint8)
    path = os.path.join(TMP_DIR, output_name)
    Image.fromarray(arr).save(path, format="PNG")
    return path


def create_resized_image(base_arr, output_name, scale_percent):
    img = Image.fromarray(base_arr)
    w, h = img.size
    new_w = max(1, int(w * scale_percent / 100.0))
    new_h = max(1, int(h * scale_percent / 100.0))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    img = img.resize((w, h), Image.LANCZOS)
    path = os.path.join(TMP_DIR, output_name)
    img.save(path, format="PNG")
    return path


def create_grayscale_image(base_arr, output_name):
    img = Image.fromarray(base_arr)
    img = img.convert("L").convert("RGB")
    path = os.path.join(TMP_DIR, output_name)
    img.save(path, format="PNG")
    return path


def create_jpeg_image(base_arr, output_name, quality=30):
    img = Image.fromarray(base_arr)
    path = os.path.join(TMP_DIR, output_name)
    img.save(path, format="JPEG", quality=quality)
    return path


def create_blur_image(base_arr, output_name, radius=2):
    img = Image.fromarray(base_arr)
    img = img.filter(ImageFilter.GaussianBlur(radius=radius))
    path = os.path.join(TMP_DIR, output_name)
    img.save(path, format="PNG")
    return path


def query_match(query_path, image_hamming_distance):
    """Query against already-indexed base image."""
    try:
        mime_type = "image/jpeg" if query_path.endswith(".jpg") else "image/png"
        with open(query_path, "rb") as f:
            r = requests.post(
                f"{BASE_URL}/match?image_hamming_distance={image_hamming_distance}",
                files={"file": (os.path.basename(query_path), f, mime_type)},
                timeout=REQUEST_TIMEOUT
            )

        if r.status_code != 200:
            return {
                "matched": False,
                "item_id": None,
                "status": None,
                "image_match_percent": None,
                "image_hamming_distance": None
            }

        matches = r.json()

        if isinstance(matches, dict):
            if "detail" in matches:
                return {
                    "matched": False,
                    "item_id": None,
                    "status": None,
                    "image_match_percent": None,
                    "image_hamming_distance": None
                }
            best = matches
        elif isinstance(matches, list) and len(matches) > 0:
            best = matches[0]
        else:
            return {
                "matched": False,
                "item_id": None,
                "status": None,
                "image_match_percent": None,
                "image_hamming_distance": None
            }

        matched = best.get("status") != "no_match"
        returned_item_id = best.get("item_id") if matched else None

        return {
            "matched": matched,
            "item_id": returned_item_id,
            "status": best.get("status"),
            "image_match_percent": best.get("image_match_percent"),
            "image_hamming_distance": best.get("image_hamming_distance")
        }
    except Exception as e:
        print(f"Match error: {e}")
        return {
            "matched": False,
            "item_id": None,
            "status": None,
            "image_match_percent": None,
            "image_hamming_distance": None
        }


def run_calibrations_for_hamming(image_hamming_distance, base_path, base_item_id, different_path):
    """Run all calibrations for a given hamming distance. Base image already indexed."""
    results = {}
    total_correct = 0
    total_calibrations = 0

    base_arr = np.array(Image.open(base_path))

    test_cases = [
        ("exact", "Exact match", True, lambda: base_path),
        ("different", "Different image", False, lambda: different_path),
    ]

    for side in ["right", "left", "top", "bottom"]:
        for pct in PERCENTAGES:
            expected = pct <= MATCH_THRESHOLD
            key = f"cutoff_{side}_{pct}"
            name = f"Cutoff {side} {pct}%"
            test_cases.append((key, name, expected,
                lambda p=pct, s=side: create_cutoff_image(base_arr, f"cutoff_{s}_{p}.png", p, s)))

    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"noise_{pct}"
        name = f"Noise {pct}%"
        level = int(pct * 2.5)
        test_cases.append((key, name, expected, lambda l=level, p=pct: create_noise_image(base_arr, f"noise_{p}.png", level=l)))

    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"brightness_{pct}"
        name = f"Brightness {pct}%"
        level = int(pct * 2.5)
        test_cases.append((key, name, expected, lambda l=level, p=pct: create_brightness_image(base_arr, f"brightness_{p}.png", level=l)))

    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"contrast_{pct}"
        name = f"Contrast {pct}%"
        factor = 1 + pct * 0.05
        test_cases.append((key, name, expected, lambda f=factor, p=pct: create_contrast_image(base_arr, f"contrast_{p}.png", factor=f)))

    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"resize_{pct}"
        name = f"Resize {pct}%"
        scale = 100 - pct
        test_cases.append((key, name, expected, lambda s=scale, p=pct: create_resized_image(base_arr, f"resize_{p}.png", s)))

    test_cases.append(("grayscale", "Grayscale", True, lambda: create_grayscale_image(base_arr, "grayscale.png")))

    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"jpeg_{pct}"
        name = f"JPEG {pct}%"
        quality = 100 - pct
        test_cases.append((key, name, expected, lambda q=quality, p=pct: create_jpeg_image(base_arr, f"jpeg_{p}.jpg", quality=q)))

    for pct in PERCENTAGES:
        expected = pct <= MATCH_THRESHOLD
        key = f"blur_{pct}"
        name = f"Blur {pct}%"
        radius = pct / 5
        test_cases.append((key, name, expected, lambda r=radius, p=pct: create_blur_image(base_arr, f"blur_{p}.png", radius=r)))

    for key, name, expected_match, create_fn in test_cases:
        query_path = create_fn()
        result = query_match(query_path, image_hamming_distance)
        correct = result["matched"] == expected_match

        results[key] = {
            "name": name,
            "expected": expected_match,
            "matched": result["matched"],
            "correct": correct,
            "item_id": result["item_id"],
            "item_id_correct": result["item_id"] == base_item_id if result["matched"] else True,
            "status": result["status"],
            "image_match_percent": result["image_match_percent"],
            "image_hamming_distance": result["image_hamming_distance"]
        }

        if correct:
            total_correct += 1
        total_calibrations += 1

    return {
        "image_hamming_distance": image_hamming_distance,
        "base_item_id": base_item_id,
        "results": results,
        "overall_correct": total_correct,
        "overall_total": total_calibrations,
        "overall_rate": total_correct / total_calibrations if total_calibrations > 0 else 0
    }


def find_optimal_hamming(min_hamming=1, max_hamming=20):
    start_time = time.time()

    print(f"Calibrating image hamming distances from {min_hamming} to {max_hamming}")
    print("=" * 80)
    print()

    print("Creating base image...", end=" ", flush=True)
    base_arr = create_pattern_image(seed=42)
    base_path = save_image(base_arr, "base.png")
    print("done")

    print("Creating different image...", end=" ", flush=True)
    different_arr = create_different_image(seed=9999)
    different_path = save_image(different_arr, "different.png")
    print("done")
    print()

    all_results = []

    for hamming in range(min_hamming, max_hamming + 1):
        print(f"Calibrating image_hamming_distance={hamming}...", end=" ", flush=True)

        reset()
        hash_result = hash_file(base_path)
        if not hash_result:
            print("Hash failed, skipping")
            continue

        base_item_id = hash_result.get("item_id")

        result = run_calibrations_for_hamming(hamming, base_path, base_item_id, different_path)
        all_results.append(result)

        print(f"{result['overall_correct']}/{result['overall_total']} ({result['overall_rate']*100:.0f}%)")

    elapsed_time = time.time() - start_time
    best = max(all_results, key=lambda x: x["overall_rate"]) if all_results else None

    return best["image_hamming_distance"] if best else None, all_results, best, elapsed_time


def format_results(stats):
    lines = []

    test_display = [
        ("exact", "Exact match (should match)"),
        ("different", "Different image (should NOT match)"),
    ]

    for side in ["right", "left", "top", "bottom"]:
        for pct in PERCENTAGES:
            key = f"cutoff_{side}_{pct}"
            expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
            name = f"Cutoff {side} {pct}% (should {expected})"
            test_display.append((key, name))

    for pct in PERCENTAGES:
        key = f"noise_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Noise {pct}% (should {expected})"
        test_display.append((key, name))

    for pct in PERCENTAGES:
        key = f"brightness_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Brightness {pct}% (should {expected})"
        test_display.append((key, name))

    for pct in PERCENTAGES:
        key = f"contrast_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Contrast {pct}% (should {expected})"
        test_display.append((key, name))

    for pct in PERCENTAGES:
        key = f"resize_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Resize {pct}% (should {expected})"
        test_display.append((key, name))

    test_display.append(("grayscale", "Grayscale (should match)"))

    for pct in PERCENTAGES:
        key = f"jpeg_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"JPEG {pct}% (should {expected})"
        test_display.append((key, name))

    for pct in PERCENTAGES:
        key = f"blur_{pct}"
        expected = "match" if pct <= MATCH_THRESHOLD else "NOT match"
        name = f"Blur {pct}% (should {expected})"
        test_display.append((key, name))

    lines.append("")
    lines.append(f"Base image item_id: {stats['base_item_id']}")
    lines.append("")
    lines.append(f"{'Calibration':<45} | {'Pass':<6} | {'Match':<8} | {'Hamming':<8} | {'Status':<12} | {'Item ID':<14}")
    lines.append("-" * 115)

    for key, name in test_display:
        r = stats["results"].get(key)
        if r:
            pass_str = "✓" if r["correct"] else "✗"
            video_str = f"{r['image_match_percent']:.0f}%" if r.get('image_match_percent') is not None else "-"
            hamming_str = str(r.get("image_hamming_distance")) if r.get("image_hamming_distance") is not None else "-"
            status_str = r.get("status") or "-"
            item_id_str = r.get("item_id", "")[:12] + "..." if r.get("item_id") else "-"
            lines.append(f"{name:<45} | {pass_str:<6} | {video_str:<8} | {hamming_str:<8} | {status_str:<12} | {item_id_str:<14}")

    lines.append("-" * 115)
    lines.append(f"{'OVERALL':<45} | {stats['overall_correct']}/{stats['overall_total']}  | {stats['overall_rate']*100:.0f}%")
    return "\n".join(lines)


def format_all_results(all_results):
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("ALL IMAGE HAMMING DISTANCES")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"{'Hamming':<12} | {'Correct':<10} | {'Rate':<10}")
    lines.append("-" * 40)
    for r in sorted(all_results, key=lambda x: -x["overall_rate"]):
        lines.append(f"{r['image_hamming_distance']:<12} | {r['overall_correct']}/{r['overall_total']:<7} | {r['overall_rate']*100:.0f}%")
    return "\n".join(lines)


def format_duration(seconds):
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


def print_best_result(best):
    print(format_results(best))
    print()
    print("=" * 80)
    print(f"RECOMMENDED: image_hamming_distance={best['image_hamming_distance']}")
    print("=" * 80)
    print(f"\nIMAGE_HAMMING_DISTANCE={best['image_hamming_distance']}")


def export_results(best, all_results, elapsed_time, filename="./results/calibrate_image.txt"):
    parent_dir = os.path.dirname(filename)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    lines = []
    lines.append("=" * 80)
    lines.append("Image Hamming Distance Calibration Results")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Duration: {format_duration(elapsed_time)}")
    lines.append(f"Service URL: {BASE_URL}")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Calibration criteria (threshold = 90%):")
    lines.append("  - 6,8,10% modification: should MATCH (≤10%)")
    lines.append("  - 12,14% modification: should NOT MATCH (>10%)")
    lines.append("")
    lines.append("Test mappings:")
    lines.append("  - Cutoff (right/left/top/bottom): pct% cut off from each side")
    lines.append("  - Noise: level = pct * 2.5 (10% = 25, 20% = 50)")
    lines.append("  - Brightness: level = pct * 2.5")
    lines.append("  - Contrast: factor = 1 + pct * 0.05 (10% = 1.5, 20% = 2.0)")
    lines.append("  - Resize: scale = 100 - pct (10% = 90% scale)")
    lines.append("  - JPEG: quality = 100 - pct (10% = quality 90)")
    lines.append("  - Blur: radius = pct / 5 (10% = 2, 20% = 4)")
    lines.append("  - Grayscale: binary (always should match)")
    lines.append("")
    lines.append(format_all_results(all_results))
    lines.append("")
    lines.append("=" * 80)
    lines.append(f"BEST: image_hamming_distance={best['image_hamming_distance']}")
    lines.append("=" * 80)
    lines.append(format_results(best))
    lines.append("")
    lines.append(f"IMAGE_HAMMING_DISTANCE={best['image_hamming_distance']}")
    lines.append("")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nResults exported to {filename}")


def main():
    print("=" * 80)
    print("Finding Optimal Image Hamming Distance")
    print("=" * 80)
    print()

    if not check_health():
        print(f"\nService not available at {BASE_URL}")
        print("Start the service with: docker-compose up -d")
        sys.exit(1)

    print()
    print("Calibration criteria (threshold = 90%):")
    print("  - 6,8,10% modification: should MATCH")
    print("  - 12,14% modification: should NOT MATCH")
    print()
    print("Tests: Cutoff (right/left/top/bottom), Noise, Brightness, Contrast, Resize, Grayscale, JPEG, Blur")
    print()

    try:
        setup()
        optimal, all_results, best, elapsed_time = find_optimal_hamming(
            min_hamming=0,
            max_hamming=30
        )

        if not best:
            print("No results collected")
            sys.exit(1)

        print(format_all_results(all_results))
        print()
        print("=" * 80)
        print(f"BEST: image_hamming_distance={best['image_hamming_distance']}")
        print("=" * 80)
        print_best_result(best)
        print(f"\nCompleted in {format_duration(elapsed_time)}")

        export_results(best, all_results, elapsed_time, "./results/calibrate_image.txt")
    finally:
        cleanup()


if __name__ == "__main__":
    main()