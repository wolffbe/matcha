#!/usr/bin/env python3
"""
Example script demonstrating the Media Matching API.

Usage:
    # Start the service first
    make docker-run
    # or
    make dev

    # Run examples
    python examples/examples.py
"""

import os
import sys
import time
import requests

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
EXAMPLES_DIR = os.path.dirname(os.path.abspath(__file__))

# Project names
PROJECT = "examples"
PROJECT_OTHER = "examples2"

# Example files
AUDIO_DIR = os.path.join(EXAMPLES_DIR, "audio")
IMAGE_DIR = os.path.join(EXAMPLES_DIR, "image")
VIDEO_DIR = os.path.join(EXAMPLES_DIR, "video")


def print_header(title):
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


def print_result(label, response):
    print(f"\n{label}:")
    if isinstance(response, list):
        if not response:
            print("  No matches found")
        for r in response:
            print(f"  - item_id: {r.get('item_id', 'N/A')[:16]}...")
            print(f"    status: {r.get('status')}")
            for key in ['image_match_percent', 'video_match_percent', 'audio_match_percent', 'transcript_match_percent']:
                val = r.get(key)
                if val is not None:
                    print(f"    {key}: {val:.1f}%")
    else:
        for key, val in response.items():
            print(f"  {key}: {val}")


def hash_file(filepath, project=PROJECT):
    """Hash a file and add it to the index."""
    with open(filepath, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/hash",
            files={"file": (os.path.basename(filepath), f)},
            params={"project": project},
            timeout=300
        )
    r.raise_for_status()
    return r.json()


def match_file(filepath, project=PROJECT):
    """Match a file against the index."""
    with open(filepath, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/match",
            files={"file": (os.path.basename(filepath), f)},
            params={"project": project},
            timeout=300
        )
    r.raise_for_status()
    return r.json()


def reset(project):
    """Reset a specific project."""
    r = requests.post(f"{BASE_URL}/reset", params={"project": project}, timeout=30)
    r.raise_for_status()
    return r.json()


def get_stats(project=PROJECT):
    """Get index statistics."""
    r = requests.get(f"{BASE_URL}/stats", params={"project": project}, timeout=10)
    r.raise_for_status()
    return r.json()


def check_service():
    """Check if service is running, with retries."""
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE_URL}/stats", timeout=5)
            if r.status_code == 200:
                return True
        except:
            pass
        if attempt < 2:
            print(f"  Service not ready, retrying in 10 seconds... ({attempt + 1}/3)")
            import time
            time.sleep(10)
    return False


def cleanup():
    """Reset both example projects."""
    print(f"Resetting projects: {PROJECT}, {PROJECT_OTHER}")
    reset(PROJECT)
    reset(PROJECT_OTHER)


def run_image_examples():
    """Demonstrate image matching."""
    print_header("IMAGE MATCHING")
    
    jerusalem = os.path.join(IMAGE_DIR, "jerusalem.jpg")
    jerusalem_crop = os.path.join(IMAGE_DIR, "jerusalem_crop.jpg")
    jerusalem_logo = os.path.join(IMAGE_DIR, "jerusalem_logo.jpg")
    jerusalem_watermark = os.path.join(IMAGE_DIR, "jerusalem_watermark.jpg")
    dog = os.path.join(IMAGE_DIR, "dog.png")
    
    if not os.path.exists(jerusalem):
        print(f"  Skipping: {jerusalem} not found")
        return
    
    # Hash original
    print("\n1. Indexing jerusalem.jpg...")
    result = hash_file(jerusalem)
    print_result("Hash result", result)
    
    # Match exact same file
    print("\n2. Matching jerusalem.jpg (exact match expected)...")
    matches = match_file(jerusalem)
    print_result("Match result", matches)
    
    # Match cropped version
    if os.path.exists(jerusalem_crop):
        print("\n3. Matching jerusalem_crop.jpg (near match expected)...")
        matches = match_file(jerusalem_crop)
        print_result("Match result", matches)
    
    # Match logo version
    if os.path.exists(jerusalem_logo):
        print("\n4. Matching jerusalem_logo.jpg (near match expected)...")
        matches = match_file(jerusalem_logo)
        print_result("Match result", matches)
    
    # Match watermark version
    if os.path.exists(jerusalem_watermark):
        print("\n5. Matching jerusalem_watermark.jpg (near match expected)...")
        matches = match_file(jerusalem_watermark)
        print_result("Match result", matches)
    
    # Match different image
    if os.path.exists(dog):
        print("\n6. Matching dog.png (no match expected)...")
        matches = match_file(dog)
        print_result("Match result", matches)
    
    # Reset after image tests
    print("\n--- Resetting after image tests ---")
    reset(PROJECT)


def run_audio_examples():
    """Demonstrate audio matching."""
    print_header("AUDIO MATCHING")
    
    armstrong = os.path.join(AUDIO_DIR, "armstrong.mp3")
    armstrong_trim = os.path.join(AUDIO_DIR, "armstrong_trim.mp3")
    armstrong_pitch = os.path.join(AUDIO_DIR, "armstrong_pitch.mp3")
    house = os.path.join(AUDIO_DIR, "house.mp3")
    
    if not os.path.exists(armstrong):
        print(f"  Skipping: {armstrong} not found")
        return
    
    # Hash original
    print("\n1. Indexing armstrong.mp3...")
    result = hash_file(armstrong)
    print_result("Hash result", result)
    
    # Match exact same file
    print("\n2. Matching armstrong.mp3 (exact match expected)...")
    matches = match_file(armstrong)
    print_result("Match result", matches)
    
    # Match trimmed version
    if os.path.exists(armstrong_trim):
        print("\n3. Matching armstrong_trim.mp3 (near match expected)...")
        matches = match_file(armstrong_trim)
        print_result("Match result", matches)
    
    # Match pitch-shifted version
    if os.path.exists(armstrong_pitch):
        print("\n4. Matching armstrong_pitch.mp3 (near match expected)...")
        matches = match_file(armstrong_pitch)
        print_result("Match result", matches)
    
    # Match different audio
    if os.path.exists(house):
        print("\n5. Matching house.mp3 (no match expected)...")
        matches = match_file(house)
        print_result("Match result", matches)
    
    # Reset after audio tests
    print("\n--- Resetting after audio tests ---")
    reset(PROJECT)


def run_video_examples():
    """Demonstrate video matching."""
    print_header("VIDEO MATCHING")
    
    armstrong = os.path.join(VIDEO_DIR, "armstrong.mp4")
    armstrong_trim = os.path.join(VIDEO_DIR, "armstrong_trim.mp4")
    armstrong_crop = os.path.join(VIDEO_DIR, "armstrong_crop.mp4")
    armstrong_logo = os.path.join(VIDEO_DIR, "armstrong_logo.mp4")
    smith = os.path.join(VIDEO_DIR, "smith.mp4")
    
    if not os.path.exists(armstrong):
        print(f"  Skipping: {armstrong} not found")
        return
    
    # Hash original
    print("\n1. Indexing armstrong.mp4...")
    result = hash_file(armstrong)
    print_result("Hash result", result)
    
    # Match exact same file
    print("\n2. Matching armstrong.mp4 (exact match expected)...")
    matches = match_file(armstrong)
    print_result("Match result", matches)
    
    # Match trimmed version
    if os.path.exists(armstrong_trim):
        print("\n3. Matching armstrong_trim.mp4 (near match expected)...")
        matches = match_file(armstrong_trim)
        print_result("Match result", matches)
    
    # Match cropped version
    if os.path.exists(armstrong_crop):
        print("\n4. Matching armstrong_crop.mp4 (near match expected)...")
        matches = match_file(armstrong_crop)
        print_result("Match result", matches)
    
    # Match logo version
    if os.path.exists(armstrong_logo):
        print("\n5. Matching armstrong_logo.mp4 (near match expected)...")
        matches = match_file(armstrong_logo)
        print_result("Match result", matches)
    
    # Match different video
    if os.path.exists(smith):
        print("\n6. Matching smith.mp4 (no match expected)...")
        matches = match_file(smith)
        print_result("Match result", matches)
    
    # Reset after video tests
    print("\n--- Resetting after video tests ---")
    reset(PROJECT)


def run_cross_project_example():
    """Demonstrate project isolation."""
    print_header("PROJECT ISOLATION")
    
    jerusalem = os.path.join(IMAGE_DIR, "jerusalem.jpg")
    
    if not os.path.exists(jerusalem):
        print(f"  Skipping: {jerusalem} not found")
        return
    
    # Hash to main project
    print(f"\n1. Indexing jerusalem.jpg to project '{PROJECT}'...")
    result = hash_file(jerusalem, project=PROJECT)
    print_result("Hash result", result)
    
    # Match against different project (should find nothing)
    print(f"\n2. Matching jerusalem.jpg against project '{PROJECT_OTHER}' (no match expected)...")
    matches = match_file(jerusalem, project=PROJECT_OTHER)
    print_result("Match result", matches)
    
    # Match against same project (should find match)
    print(f"\n3. Matching jerusalem.jpg against project '{PROJECT}' (exact match expected)...")
    matches = match_file(jerusalem, project=PROJECT)
    print_result("Match result", matches)


def main():
    print_header("MEDIA MATCHING API EXAMPLES")
    
    # Check service
    if not check_service():
        print(f"\nError: Service not available at {BASE_URL}")
        print("Start the service with: make docker-run")
        sys.exit(1)
    
    print(f"\nService running at {BASE_URL}")
    print(f"Using project: {PROJECT}")
    
    # Cleanup before
    print("\n--- CLEANUP BEFORE ---")
    cleanup()
    
    # Run examples (each resets after completion)
    run_image_examples()
    run_audio_examples()
    run_video_examples()
    run_cross_project_example()
    
    # Cleanup after
    print("\n--- CLEANUP AFTER ---")
    cleanup()
    
    print_header("EXAMPLES COMPLETE")


if __name__ == "__main__":
    main()