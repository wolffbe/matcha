# tests/test_image_matching.py
import os
import shutil
import requests
import pytest
import time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
TMP_DIR = "./tmp/image_pytest"
REQUEST_TIMEOUT = 60

# Threshold settings
IMAGE_THRESHOLD = 0.90  # 90%
IMAGE_OFFSET = 0.015    # 1,5%


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
        if stats.get("total_image_hashes", 0) == 0:
            return
        time.sleep(0.2)


def create_pattern_image(filename, seed=42, width=640, height=480):
    """Create a complex pattern image with reproducible randomness."""
    np.random.seed(seed)
    arr = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
    
    for y in range(height):
        for x in range(width):
            arr[y, x, 0] = np.clip(arr[y, x, 0] * (x / width), 0, 255)
            arr[y, x, 1] = np.clip(arr[y, x, 1] * (y / height), 0, 255)
    
    img = Image.fromarray(arr)
    draw = ImageDraw.Draw(img)
    
    for _ in range(50):
        x1, y1 = np.random.randint(0, width), np.random.randint(0, height)
        x2, y2 = np.random.randint(0, width), np.random.randint(0, height)
        color = tuple(np.random.randint(0, 256, 3).tolist())
        draw.line([(x1, y1), (x2, y2)], fill=color, width=np.random.randint(1, 5))
    
    for _ in range(20):
        x1, y1 = np.random.randint(0, width), np.random.randint(0, height)
        x2, y2 = np.random.randint(0, width), np.random.randint(0, height)
        color = tuple(np.random.randint(0, 256, 3).tolist())
        draw.rectangle([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)], outline=color)
    
    for _ in range(15):
        x, y = np.random.randint(50, width - 50), np.random.randint(50, height - 50)
        r = np.random.randint(10, 80)
        color = tuple(np.random.randint(0, 256, 3).tolist())
        draw.ellipse([x - r, y - r, x + r, y + r], outline=color, width=2)
    
    path = os.path.join(TMP_DIR, filename)
    img.save(path, format="PNG")
    return path


def create_different_image(filename, seed=9999, width=640, height=480):
    """Create a completely different image."""
    np.random.seed(seed)
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    bg_color = np.random.randint(0, 256, 3)
    arr[:, :] = bg_color
    
    img = Image.fromarray(arr)
    draw = ImageDraw.Draw(img)
    
    for _ in range(10):
        x1, y1 = np.random.randint(0, width), np.random.randint(0, height)
        x2, y2 = np.random.randint(0, width), np.random.randint(0, height)
        color = tuple(np.random.randint(0, 256, 3).tolist())
        draw.rectangle([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)], fill=color)
    
    for _ in range(5):
        x, y = np.random.randint(50, width - 50), np.random.randint(50, height - 50)
        r = np.random.randint(20, 50)
        color = tuple(np.random.randint(0, 256, 3).tolist())
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
    
    path = os.path.join(TMP_DIR, filename)
    img.save(path, format="PNG")
    return path


def cutoff_image(input_path, output_name, cutoff_percent, side="right"):
    """Cut off a percentage from one side, fill with black."""
    img = Image.open(input_path)
    w, h = img.size
    output_path = os.path.join(TMP_DIR, output_name)
    
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
    
    new_img.save(output_path, format="PNG")
    return output_path


def add_noise(input_path, output_name, level):
    """Add random noise to the image."""
    img = Image.open(input_path)
    arr = np.array(img)
    noise = np.random.randint(-level, level + 1, arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    output_path = os.path.join(TMP_DIR, output_name)
    Image.fromarray(arr).save(output_path, format="PNG")
    return output_path


def adjust_brightness(input_path, output_name, level):
    """Adjust brightness by adding a constant."""
    img = Image.open(input_path)
    arr = np.array(img)
    arr = np.clip(arr.astype(np.int16) + level, 0, 255).astype(np.uint8)
    output_path = os.path.join(TMP_DIR, output_name)
    Image.fromarray(arr).save(output_path, format="PNG")
    return output_path


def adjust_contrast(input_path, output_name, factor):
    """Adjust contrast by scaling around midpoint."""
    img = Image.open(input_path)
    arr = np.array(img)
    arr = np.clip((arr.astype(np.float32) - 128) * factor + 128, 0, 255).astype(np.uint8)
    output_path = os.path.join(TMP_DIR, output_name)
    Image.fromarray(arr).save(output_path, format="PNG")
    return output_path


def resize_image(input_path, output_name, scale_percent):
    """Resize image down then back up (lossy operation)."""
    img = Image.open(input_path)
    w, h = img.size
    new_w = max(1, int(w * scale_percent / 100.0))
    new_h = max(1, int(h * scale_percent / 100.0))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    img = img.resize((w, h), Image.LANCZOS)
    output_path = os.path.join(TMP_DIR, output_name)
    img.save(output_path, format="PNG")
    return output_path


def to_grayscale(input_path, output_name):
    """Convert to grayscale and back to RGB."""
    img = Image.open(input_path)
    img = img.convert("L").convert("RGB")
    output_path = os.path.join(TMP_DIR, output_name)
    img.save(output_path, format="PNG")
    return output_path


def jpeg_compress(input_path, output_name, quality):
    """Save as JPEG with specified quality."""
    img = Image.open(input_path)
    output_path = os.path.join(TMP_DIR, output_name)
    img.save(output_path, format="JPEG", quality=quality)
    return output_path


def blur_image(input_path, output_name, radius):
    """Apply Gaussian blur."""
    img = Image.open(input_path)
    img = img.filter(ImageFilter.GaussianBlur(radius=radius))
    output_path = os.path.join(TMP_DIR, output_name)
    img.save(output_path, format="PNG")
    return output_path


def hash_file(path):
    mime_type = "image/jpeg" if path.endswith(".jpg") else "image/png"
    with open(path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/hash",
            files={"file": (os.path.basename(path), f, mime_type)},
            timeout=REQUEST_TIMEOUT
        )
    if r.status_code != 200:
        print(f"Hash failed: {r.status_code} - {r.text}")
        return None
    return r.json()


def match_file(path, image_threshold=None, image_offset=None):
    params = {}
    if image_threshold is not None:
        params["image_threshold"] = image_threshold
    if image_offset is not None:
        params["image_offset"] = image_offset
    
    mime_type = "image/jpeg" if path.endswith(".jpg") else "image/png"
    with open(path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/match",
            files={"file": (os.path.basename(path), f, mime_type)},
            params=params,
            timeout=REQUEST_TIMEOUT
        )
    if r.status_code != 200:
        print(f"Match failed: {r.status_code} - {r.text}")
        return None
    return r.json()


def get_image_match(path, threshold=IMAGE_THRESHOLD, offset=IMAGE_OFFSET):
    """Get image match percentage and status."""
    # Get raw percentage (threshold=0 to get any match)
    raw_matches = match_file(path, image_threshold=0.0, image_offset=0.0)
    if raw_matches and len(raw_matches) >= 1:
        m = raw_matches[0]
        image_pct = m.get('image_match_percent', 0.0) or 0.0
        
        # Validate response structure
        item_id = m.get('item_id', '')
        assert len(item_id) == 64 and all(c in '0123456789abcdef' for c in item_id), \
            f"item_id should be SHA256 hash, got: {item_id}"
        assert m.get('audio_match_percent') is None, \
            f"audio_match_percent should be None for image, got: {m.get('audio_match_percent')}"
        assert m.get('video_match_percent') is None, \
            f"video_match_percent should be None for image, got: {m.get('video_match_percent')}"
        assert m.get('transcript_match_percent') is None, \
            f"transcript_match_percent should be None for image, got: {m.get('transcript_match_percent')}"
    else:
        image_pct = 0.0
    
    # Get status with actual thresholds
    real_matches = match_file(path, image_threshold=threshold, image_offset=offset)
    if real_matches and len(real_matches) >= 1:
        status = real_matches[0]['status']
        assert status in ("exact_match", "near_match"), \
            f"status should be 'exact_match' or 'near_match' when matched, got: {status}"
    else:
        status = "no_match"
    
    return image_pct, status


class TestExactMatch:
    def test_exact_match(self):
        """Same file should return 100% with exact_match status."""
        reset()
        base_path = create_pattern_image("exact.png", seed=42)
        hash_file(base_path)
        time.sleep(0.5)
        
        image_pct, status = get_image_match(base_path)
        print(f"Exact match: image={image_pct:.1f}%, status={status}")
        
        assert image_pct == 100.0, f"Expected image 100%, got {image_pct}"
        assert status == "exact_match", f"Expected exact_match, got {status}"


class TestNoMatch:
    def test_different_image_no_match(self):
        """Completely different image should not match."""
        reset()
        base_path = create_pattern_image("base_diff.png", seed=42)
        hash_file(base_path)
        time.sleep(0.5)
        
        different_path = create_different_image("different.png", seed=9999)
        image_pct, status = get_image_match(different_path)
        print(f"Different image: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 50, f"Expected image >= 50%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"


class TestCutoffRight:
    """Cutoff from right side - use same seed for all tests."""
    SEED = 100
    
    @pytest.fixture(autouse=True)
    def setup_base_image(self):
        reset()
        self.base_path = create_pattern_image("base_cutoff_right.png", seed=self.SEED)
        hash_file(self.base_path)
        time.sleep(0.5)
    
    def test_cutoff_right_6_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_r6.png", 6, "right")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff RIGHT 6%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"

    def test_cutoff_right_8_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_r8.png", 8, "right")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff RIGHT 8%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"

    def test_cutoff_right_10_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_r10.png", 10, "right")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff RIGHT 10%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"

    def test_cutoff_right_12_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_r12.png", 12, "right")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff RIGHT 12%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"
        
    def test_cutoff_right_14_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_r14.png", 14, "right")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff RIGHT 14%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"
        
    def test_cutoff_right_16_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_r16.png", 16, "right")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff RIGHT 16%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"

    def test_cutoff_right_18_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_r18.png", 18, "right")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff RIGHT 18%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"

    def test_cutoff_right_20_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_r20.png", 20, "right")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff RIGHT 20%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"


class TestCutoffLeft:
    """Cutoff from left side - use same seed for all tests."""
    SEED = 200
    
    @pytest.fixture(autouse=True)
    def setup_base_image(self):
        reset()
        self.base_path = create_pattern_image("base_cutoff_left.png", seed=self.SEED)
        hash_file(self.base_path)
        time.sleep(0.5)
    
    def test_cutoff_left_6_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_l6.png", 6, "left")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff LEFT 6%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"

    def test_cutoff_left_8_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_l8.png", 8, "left")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff LEFT 8%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"

    def test_cutoff_left_10_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_l10.png", 10, "left")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff LEFT 10%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"

    def test_cutoff_left_12_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_l12.png", 12, "left")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff LEFT 12%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 80, f"Expected image >= 80%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"
        
    def test_cutoff_left_14_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_l14.png", 14, "left")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff LEFT 14%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 80, f"Expected image >= 80%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"
        
    def test_cutoff_left_16_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_l16.png", 16, "left")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff LEFT 16%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 80, f"Expected image >= 80%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"

    def test_cutoff_left_18_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_l18.png", 18, "left")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff LEFT 18%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 80, f"Expected image >= 80%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"

    def test_cutoff_left_20_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_l20.png", 20, "left")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff LEFT 20%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 80, f"Expected image >= 80%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"


class TestCutoffTop:
    """Cutoff from top - use same seed for all tests."""
    SEED = 300
    
    @pytest.fixture(autouse=True)
    def setup_base_image(self):
        reset()
        self.base_path = create_pattern_image("base_cutoff_top.png", seed=self.SEED)
        hash_file(self.base_path)
        time.sleep(0.5)
    
    def test_cutoff_top_6_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_t6.png", 6, "top")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff TOP 6%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"

    def test_cutoff_top_8_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_t8.png", 8, "top")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff TOP 8%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"

    def test_cutoff_top_10_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_t10.png", 10, "top")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff TOP 10%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"

    def test_cutoff_top_12_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_t12.png", 12, "top")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff TOP 12%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"

    def test_cutoff_top_14_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_t14.png", 14, "top")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff TOP 14%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"

    def test_cutoff_top_16_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_t16.png", 16, "top")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff TOP 16%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"

    def test_cutoff_top_18_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_t18.png", 18, "top")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff TOP 18%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 80, f"Expected image >= 80%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"

    def test_cutoff_top_20_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_t20.png", 20, "top")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff TOP 20%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 80, f"Expected image >= 80%, got {image_pct}"
        assert status == "no_match", f"Expected no_match, got {status}"


class TestCutoffBottom:
    """Cutoff from bottom - use same seed for all tests."""
    SEED = 400
    
    @pytest.fixture(autouse=True)
    def setup_base_image(self):
        reset()
        self.base_path = create_pattern_image("base_cutoff_bottom.png", seed=self.SEED)
        hash_file(self.base_path)
        time.sleep(0.5)
    
    def test_cutoff_bottom_6_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_b6.png", 6, "bottom")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff BOTTOM 6%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"

    def test_cutoff_bottom_8_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_b8.png", 8, "bottom")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff BOTTOM 8%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected near_match, got {status}"

    def test_cutoff_bottom_10_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_b10.png", 10, "bottom")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff BOTTOM 10%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"
        
    def test_cutoff_bottom_12_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_b12.png", 12, "bottom")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff BOTTOM 12%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"
        
    def test_cutoff_bottom_14_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_b14.png", 14, "bottom")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff BOTTOM 14%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"
        
    def test_cutoff_bottom_16_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_b16.png", 16, "bottom")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff BOTTOM 16%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_cutoff_bottom_18_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_b18.png", 18, "bottom")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff BOTTOM 18%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "no_match", f"Expected match, got {status}"

    def test_cutoff_bottom_20_percent(self):
        modified = cutoff_image(self.base_path, "cutoff_b20.png", 20, "bottom")
        image_pct, status = get_image_match(modified)
        print(f"Cutoff BOTTOM 20%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "no_match", f"Expected match, got {status}"


class TestNoise:
    """Test noise addition - use same seed for all tests."""
    SEED = 500
    
    @pytest.fixture(autouse=True)
    def setup_base_image(self):
        reset()
        self.base_path = create_pattern_image("base_noise.png", seed=self.SEED)
        hash_file(self.base_path)
        time.sleep(0.5)
    
    def test_noise_6_percent(self):
        modified = add_noise(self.base_path, "noise_6.png", level=15)
        image_pct, status = get_image_match(modified)
        print(f"Noise 6%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct == 100, f"Expected image >= 90%, got {image_pct}"
        assert status == "exact_match", f"Expected match, got {status}"

    def test_noise_8_percent(self):
        modified = add_noise(self.base_path, "noise_8.png", level=20)
        image_pct, status = get_image_match(modified)
        print(f"Noise 8%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_noise_10_percent(self):
        modified = add_noise(self.base_path, "noise_10.png", level=25)
        image_pct, status = get_image_match(modified)
        print(f"Noise 10%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_noise_12_percent(self):
        modified = add_noise(self.base_path, "noise_12.png", level=30)
        image_pct, status = get_image_match(modified)
        print(f"Noise 12%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_noise_14_percent(self):
        modified = add_noise(self.base_path, "noise_14.png", level=35)
        image_pct, status = get_image_match(modified)
        print(f"Noise 14%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_noise_16_percent(self):
        modified = add_noise(self.base_path, "noise_16.png", level=40)
        image_pct, status = get_image_match(modified)
        print(f"Noise 16%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_noise_18_percent(self):
        modified = add_noise(self.base_path, "noise_18.png", level=45)
        image_pct, status = get_image_match(modified)
        print(f"Noise 18%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_noise_20_percent(self):
        modified = add_noise(self.base_path, "noise_20.png", level=50)
        image_pct, status = get_image_match(modified)
        print(f"Noise 20%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"


class TestBrightness:
    """Test brightness adjustment - use same seed for all tests."""
    SEED = 600
    
    @pytest.fixture(autouse=True)
    def setup_base_image(self):
        reset()
        self.base_path = create_pattern_image("base_brightness.png", seed=self.SEED)
        hash_file(self.base_path)
        time.sleep(0.5)
    
    def test_brightness_6_percent(self):
        modified = adjust_brightness(self.base_path, "brightness_6.png", level=15)
        image_pct, status = get_image_match(modified)
        print(f"Brightness 6%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_brightness_8_percent(self):
        modified = adjust_brightness(self.base_path, "brightness_8.png", level=20)
        image_pct, status = get_image_match(modified)
        print(f"Brightness 8%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_brightness_10_percent(self):
        modified = adjust_brightness(self.base_path, "brightness_10.png", level=25)
        image_pct, status = get_image_match(modified)
        print(f"Brightness 10%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_brightness_12_percent(self):
        modified = adjust_brightness(self.base_path, "brightness_12.png", level=30)
        image_pct, status = get_image_match(modified)
        print(f"Brightness 12%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_brightness_14_percent(self):
        modified = adjust_brightness(self.base_path, "brightness_14.png", level=35)
        image_pct, status = get_image_match(modified)
        print(f"Brightness 14%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_brightness_16_percent(self):
        modified = adjust_brightness(self.base_path, "brightness_16.png", level=40)
        image_pct, status = get_image_match(modified)
        print(f"Brightness 16%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_brightness_18_percent(self):
        modified = adjust_brightness(self.base_path, "brightness_18.png", level=45)
        image_pct, status = get_image_match(modified)
        print(f"Brightness 18%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_brightness_20_percent(self):
        modified = adjust_brightness(self.base_path, "brightness_20.png", level=50)
        image_pct, status = get_image_match(modified)
        print(f"Brightness 20%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"


class TestContrast:
    """Test contrast adjustment - use same seed for all tests."""
    SEED = 700
    
    @pytest.fixture(autouse=True)
    def setup_base_image(self):
        reset()
        self.base_path = create_pattern_image("base_contrast.png", seed=self.SEED)
        hash_file(self.base_path)
        time.sleep(0.5)
    
    def test_contrast_6_percent(self):
        modified = adjust_contrast(self.base_path, "contrast_6.png", factor=1.3)
        image_pct, status = get_image_match(modified)
        print(f"Contrast 6%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_contrast_8_percent(self):
        modified = adjust_contrast(self.base_path, "contrast_8.png", factor=1.4)
        image_pct, status = get_image_match(modified)
        print(f"Contrast 8%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_contrast_10_percent(self):
        modified = adjust_contrast(self.base_path, "contrast_10.png", factor=1.5)
        image_pct, status = get_image_match(modified)
        print(f"Contrast 10%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_contrast_12_percent(self):
        modified = adjust_contrast(self.base_path, "contrast_12.png", factor=1.6)
        image_pct, status = get_image_match(modified)
        print(f"Contrast 12%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_contrast_14_percent(self):
        modified = adjust_contrast(self.base_path, "contrast_14.png", factor=1.7)
        image_pct, status = get_image_match(modified)
        print(f"Contrast 14%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_contrast_16_percent(self):
        modified = adjust_contrast(self.base_path, "contrast_16.png", factor=1.8)
        image_pct, status = get_image_match(modified)
        print(f"Contrast 16%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_contrast_18_percent(self):
        modified = adjust_contrast(self.base_path, "contrast_18.png", factor=1.9)
        image_pct, status = get_image_match(modified)
        print(f"Contrast 18%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_contrast_20_percent(self):
        modified = adjust_contrast(self.base_path, "contrast_20.png", factor=2.0)
        image_pct, status = get_image_match(modified)
        print(f"Contrast 20%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 90, f"Expected image >= 90%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"


class TestResize:
    """Test resize down and back up - use same seed for all tests."""
    SEED = 800
    
    @pytest.fixture(autouse=True)
    def setup_base_image(self):
        reset()
        self.base_path = create_pattern_image("base_resize.png", seed=self.SEED)
        hash_file(self.base_path)
        time.sleep(0.5)
    
    def test_resize_6_percent(self):
        modified = resize_image(self.base_path, "resize_6.png", scale_percent=94)
        image_pct, status = get_image_match(modified)
        print(f"Resize 6%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_resize_8_percent(self):
        modified = resize_image(self.base_path, "resize_8.png", scale_percent=92)
        image_pct, status = get_image_match(modified)
        print(f"Resize 8%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_resize_10_percent(self):
        modified = resize_image(self.base_path, "resize_10.png", scale_percent=90)
        image_pct, status = get_image_match(modified)
        print(f"Resize 10%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_resize_12_percent(self):
        modified = resize_image(self.base_path, "resize_12.png", scale_percent=88)
        image_pct, status = get_image_match(modified)
        print(f"Resize 12%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_resize_14_percent(self):
        modified = resize_image(self.base_path, "resize_14.png", scale_percent=86)
        image_pct, status = get_image_match(modified)
        print(f"Resize 14%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_resize_16_percent(self):
        modified = resize_image(self.base_path, "resize_16.png", scale_percent=84)
        image_pct, status = get_image_match(modified)
        print(f"Resize 16%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_resize_18_percent(self):
        modified = resize_image(self.base_path, "resize_18.png", scale_percent=82)
        image_pct, status = get_image_match(modified)
        print(f"Resize 18%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_resize_20_percent(self):
        modified = resize_image(self.base_path, "resize_20.png", scale_percent=80)
        image_pct, status = get_image_match(modified)
        print(f"Resize 20%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"


class TestGrayscale:
    """Test grayscale conversion."""
    SEED = 900
    
    def test_grayscale(self):
        reset()
        base_path = create_pattern_image("base_gray.png", seed=self.SEED)
        hash_file(base_path)
        time.sleep(0.5)
        
        modified = to_grayscale(base_path, "grayscale.png")
        image_pct, status = get_image_match(modified)
        print(f"Grayscale: image={image_pct:.1f}%, status={status}")
        
        assert image_pct == 100.0, f"Expected image 100%, got {image_pct}"
        assert status == "exact_match", f"Expected exact_match, got {status}"


class TestJPEGCompression:
    """Test JPEG compression - use same seed for all tests."""
    SEED = 1000
    
    @pytest.fixture(autouse=True)
    def setup_base_image(self):
        reset()
        self.base_path = create_pattern_image("base_jpeg.png", seed=self.SEED)
        hash_file(self.base_path)
        time.sleep(0.5)
    
    def test_jpeg_6_percent(self):
        modified = jpeg_compress(self.base_path, "jpeg_6.jpg", quality=94)
        image_pct, status = get_image_match(modified)
        print(f"JPEG 6%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_jpeg_8_percent(self):
        modified = jpeg_compress(self.base_path, "jpeg_8.jpg", quality=92)
        image_pct, status = get_image_match(modified)
        print(f"JPEG 8%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_jpeg_10_percent(self):
        modified = jpeg_compress(self.base_path, "jpeg_10.jpg", quality=90)
        image_pct, status = get_image_match(modified)
        print(f"JPEG 10%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_jpeg_12_percent(self):
        modified = jpeg_compress(self.base_path, "jpeg_12.jpg", quality=88)
        image_pct, status = get_image_match(modified)
        print(f"JPEG 12%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_jpeg_14_percent(self):
        modified = jpeg_compress(self.base_path, "jpeg_14.jpg", quality=86)
        image_pct, status = get_image_match(modified)
        print(f"JPEG 14%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_jpeg_16_percent(self):
        modified = jpeg_compress(self.base_path, "jpeg_16.jpg", quality=84)
        image_pct, status = get_image_match(modified)
        print(f"JPEG 16%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_jpeg_18_percent(self):
        modified = jpeg_compress(self.base_path, "jpeg_18.jpg", quality=82)
        image_pct, status = get_image_match(modified)
        print(f"JPEG 18%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_jpeg_20_percent(self):
        modified = jpeg_compress(self.base_path, "jpeg_20.jpg", quality=80)
        image_pct, status = get_image_match(modified)
        print(f"JPEG 20%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"


class TestBlur:
    """Test Gaussian blur - use same seed for all tests."""
    SEED = 1100
    
    @pytest.fixture(autouse=True)
    def setup_base_image(self):
        reset()
        self.base_path = create_pattern_image("base_blur.png", seed=self.SEED)
        hash_file(self.base_path)
        time.sleep(0.5)
    
    def test_blur_6_percent(self):
        modified = blur_image(self.base_path, "blur_6.png", radius=1.2)
        image_pct, status = get_image_match(modified)
        print(f"Blur 6%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 95, f"Expected image >= 95%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_blur_8_percent(self):
        modified = blur_image(self.base_path, "blur_8.png", radius=1.6)
        image_pct, status = get_image_match(modified)
        print(f"Blur 8%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_blur_10_percent(self):
        modified = blur_image(self.base_path, "blur_10.png", radius=2.0)
        image_pct, status = get_image_match(modified)
        print(f"Blur 10%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_blur_12_percent(self):
        modified = blur_image(self.base_path, "blur_12.png", radius=2.4)
        image_pct, status = get_image_match(modified)
        print(f"Blur 12%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_blur_14_percent(self):
        modified = blur_image(self.base_path, "blur_14.png", radius=2.8)
        image_pct, status = get_image_match(modified)
        print(f"Blur 14%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "near_match", f"Expected match, got {status}"

    def test_blur_16_percent(self):
        modified = blur_image(self.base_path, "blur_16.png", radius=3.2)
        image_pct, status = get_image_match(modified)
        print(f"Blur 16%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "no_match", f"Expected match, got {status}"

    def test_blur_18_percent(self):
        modified = blur_image(self.base_path, "blur_18.png", radius=3.6)
        image_pct, status = get_image_match(modified)
        print(f"Blur 18%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "no_match", f"Expected match, got {status}"

    def test_blur_20_percent(self):
        modified = blur_image(self.base_path, "blur_20.png", radius=4.0)
        image_pct, status = get_image_match(modified)
        print(f"Blur 20%: image={image_pct:.1f}%, status={status}")
        
        assert image_pct >= 85, f"Expected image >= 85%, got {image_pct}"
        assert status == "no_match", f"Expected match, got {status}"