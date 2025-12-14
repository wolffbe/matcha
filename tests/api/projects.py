# tests/api/test_project_isolation.py
"""
Test project-based isolation for media matching.

Tests that:
1. Items saved without project are in default (None) project
2. Items saved with project are isolated to that project
3. Items in one project don't match items in another project
4. Items in default don't match items in named projects and vice versa
"""
import subprocess
import os
import shutil
import requests
import pytest
import time

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
TMP_DIR = "./tmp/tests/api/project_isolation"
REQUEST_TIMEOUT = 300

# Test projects
PROJECT_A = "project_alpha"
PROJECT_B = "project_beta"
DEFAULT_PROJECT = None  # No project specified


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


@pytest.fixture(scope="module", autouse=True)
def setup_teardown():
    wait_for_service()
    os.makedirs(TMP_DIR, exist_ok=True)
    
    # Reset all projects before tests
    requests.post(f"{BASE_URL}/reset", timeout=30)
    requests.post(f"{BASE_URL}/reset", params={"project": PROJECT_A}, timeout=30)
    requests.post(f"{BASE_URL}/reset", params={"project": PROJECT_B}, timeout=30)
    time.sleep(0.5)
    
    yield
    
    # Cleanup
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    requests.post(f"{BASE_URL}/reset", timeout=30)
    requests.post(f"{BASE_URL}/reset", params={"project": PROJECT_A}, timeout=30)
    requests.post(f"{BASE_URL}/reset", params={"project": PROJECT_B}, timeout=30)


def reset_all():
    """Reset all projects."""
    requests.post(f"{BASE_URL}/reset", timeout=30)
    requests.post(f"{BASE_URL}/reset", params={"project": PROJECT_A}, timeout=30)
    requests.post(f"{BASE_URL}/reset", params={"project": PROJECT_B}, timeout=30)
    time.sleep(0.3)


# =============================================================================
# Test Media Creation
# =============================================================================

def create_test_image(filename, color="red"):
    """Create a simple test image."""
    path = os.path.join(TMP_DIR, filename)
    colors = {"red": "0xff0000", "green": "0x00ff00", "blue": "0x0000ff"}
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c={colors.get(color, '0xff0000')}:s=64x64:d=1",
        "-frames:v", "1",
        path
    ], capture_output=True, check=True)
    return path


def create_test_audio(filename, freq=440):
    """Create a simple test audio file."""
    path = os.path.join(TMP_DIR, filename)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration=5",
        "-c:a", "libmp3lame", "-q:a", "2",
        path
    ], capture_output=True, check=True)
    return path


def create_test_video(filename, pattern="testsrc"):
    """Create a simple test video file."""
    path = os.path.join(TMP_DIR, filename)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"{pattern}=duration=3:size=64x64:rate=10",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
        path
    ], capture_output=True, check=True)
    return path


# =============================================================================
# API Helpers
# =============================================================================

def hash_file(path, project=None):
    """Hash a file and add to index."""
    params = {"skip_transcript": "true"}
    if project is not None:
        params["project"] = project
    
    with open(path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/hash",
            files={"file": (os.path.basename(path), f)},
            params=params,
            timeout=REQUEST_TIMEOUT
        )
    assert r.status_code == 200, f"Hash failed: {r.status_code} - {r.text}"
    return r.json()


def match_file(path, project=None):
    """Match a file against index."""
    params = {"skip_transcript": "true"}
    if project is not None:
        params["project"] = project
    
    with open(path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/match",
            files={"file": (os.path.basename(path), f)},
            params=params,
            timeout=REQUEST_TIMEOUT
        )
    assert r.status_code == 200, f"Match failed: {r.status_code} - {r.text}"
    return r.json()


def get_stats(project=None):
    """Get stats for a project."""
    params = {}
    if project is not None:
        params["project"] = project
    
    r = requests.get(f"{BASE_URL}/stats", params=params, timeout=5)
    assert r.status_code == 200
    return r.json()


# =============================================================================
# Image Tests
# =============================================================================

class TestImageProjectIsolation:
    """Test image isolation between projects."""
    
    def test_image_in_default_not_in_project(self):
        """Image in default project should not match in named project."""
        reset_all()
        
        # Create and hash image in default project
        img_path = create_test_image("img_default.png", "red")
        hash_result = hash_file(img_path, project=None)
        assert hash_result["type"] == "image"
        assert hash_result.get("project") is None
        time.sleep(0.3)
        
        # Should match in default project
        matches = match_file(img_path, project=None)
        assert len(matches) >= 1, "Should find match in default project"
        assert matches[0]["status"] == "exact_match"
        
        # Should NOT match in project_alpha
        matches = match_file(img_path, project=PROJECT_A)
        assert len(matches) == 0, f"Should NOT find match in {PROJECT_A}"
        
        # Should NOT match in project_beta
        matches = match_file(img_path, project=PROJECT_B)
        assert len(matches) == 0, f"Should NOT find match in {PROJECT_B}"
        
        print("✓ Image in default not visible in named projects")
    
    def test_image_in_project_not_in_default(self):
        """Image in named project should not match in default project."""
        reset_all()
        
        # Create and hash image in project_alpha
        img_path = create_test_image("img_alpha.png", "green")
        hash_result = hash_file(img_path, project=PROJECT_A)
        assert hash_result["type"] == "image"
        assert hash_result.get("project") == PROJECT_A
        time.sleep(0.3)
        
        # Should match in project_alpha
        matches = match_file(img_path, project=PROJECT_A)
        assert len(matches) >= 1, f"Should find match in {PROJECT_A}"
        assert matches[0]["status"] == "exact_match"
        
        # Should NOT match in default project
        matches = match_file(img_path, project=None)
        assert len(matches) == 0, "Should NOT find match in default project"
        
        # Should NOT match in project_beta
        matches = match_file(img_path, project=PROJECT_B)
        assert len(matches) == 0, f"Should NOT find match in {PROJECT_B}"
        
        print("✓ Image in named project not visible in default or other projects")
    
    def test_image_isolation_between_projects(self):
        """Images in different projects should be isolated."""
        reset_all()
        
        # Create same image, hash in both projects
        img_path = create_test_image("img_shared.png", "blue")
        
        hash_a = hash_file(img_path, project=PROJECT_A)
        hash_b = hash_file(img_path, project=PROJECT_B)
        time.sleep(0.3)
        
        # Both should have same item_id (same file content)
        assert hash_a["item_id"] == hash_b["item_id"]
        
        # Match in project_alpha should only return project_alpha result
        matches = match_file(img_path, project=PROJECT_A)
        assert len(matches) >= 1
        assert matches[0].get("project") == PROJECT_A
        
        # Match in project_beta should only return project_beta result
        matches = match_file(img_path, project=PROJECT_B)
        assert len(matches) >= 1
        assert matches[0].get("project") == PROJECT_B
        
        print("✓ Same image in different projects is isolated")


# =============================================================================
# Audio Tests
# =============================================================================

class TestAudioProjectIsolation:
    """Test audio isolation between projects."""
    
    def test_audio_in_default_not_in_project(self):
        """Audio in default project should not match in named project."""
        reset_all()
        
        # Create and hash audio in default project
        audio_path = create_test_audio("audio_default.mp3", freq=440)
        hash_result = hash_file(audio_path, project=None)
        assert hash_result["type"] == "audio"
        time.sleep(0.3)
        
        # Should match in default project
        matches = match_file(audio_path, project=None)
        assert len(matches) >= 1, "Should find match in default project"
        
        # Should NOT match in project_alpha
        matches = match_file(audio_path, project=PROJECT_A)
        assert len(matches) == 0, f"Should NOT find match in {PROJECT_A}"
        
        print("✓ Audio in default not visible in named projects")
    
    def test_audio_in_project_not_in_default(self):
        """Audio in named project should not match in default project."""
        reset_all()
        
        # Create and hash audio in project_alpha
        audio_path = create_test_audio("audio_alpha.mp3", freq=880)
        hash_result = hash_file(audio_path, project=PROJECT_A)
        assert hash_result["type"] == "audio"
        time.sleep(0.3)
        
        # Should match in project_alpha
        matches = match_file(audio_path, project=PROJECT_A)
        assert len(matches) >= 1, f"Should find match in {PROJECT_A}"
        
        # Should NOT match in default project
        matches = match_file(audio_path, project=None)
        assert len(matches) == 0, "Should NOT find match in default project"
        
        print("✓ Audio in named project not visible in default")


# =============================================================================
# Video Tests
# =============================================================================

class TestVideoProjectIsolation:
    """Test video isolation between projects."""
    
    def test_video_in_default_not_in_project(self):
        """Video in default project should not match in named project."""
        reset_all()
        
        # Create and hash video in default project
        video_path = create_test_video("video_default.mp4", "testsrc")
        hash_result = hash_file(video_path, project=None)
        assert hash_result["type"] == "video"
        time.sleep(0.3)
        
        # Should match in default project
        matches = match_file(video_path, project=None)
        assert len(matches) >= 1, "Should find match in default project"
        
        # Should NOT match in project_alpha
        matches = match_file(video_path, project=PROJECT_A)
        assert len(matches) == 0, f"Should NOT find match in {PROJECT_A}"
        
        print("✓ Video in default not visible in named projects")
    
    def test_video_in_project_not_in_default(self):
        """Video in named project should not match in default project."""
        reset_all()
        
        # Create and hash video in project_beta
        video_path = create_test_video("video_beta.mp4", "testsrc2")
        hash_result = hash_file(video_path, project=PROJECT_B)
        assert hash_result["type"] == "video"
        time.sleep(0.3)
        
        # Should match in project_beta
        matches = match_file(video_path, project=PROJECT_B)
        assert len(matches) >= 1, f"Should find match in {PROJECT_B}"
        
        # Should NOT match in default project
        matches = match_file(video_path, project=None)
        assert len(matches) == 0, "Should NOT find match in default project"
        
        # Should NOT match in project_alpha
        matches = match_file(video_path, project=PROJECT_A)
        assert len(matches) == 0, f"Should NOT find match in {PROJECT_A}"
        
        print("✓ Video in named project not visible in default or other projects")


# =============================================================================
# Stats Tests
# =============================================================================

class TestProjectStats:
    """Test stats are correctly scoped to projects."""
    
    def test_stats_per_project(self):
        """Stats should reflect only items in that project."""
        reset_all()
        
        # Verify all empty
        assert get_stats(project=None)["total_image_hashes"] == 0
        assert get_stats(project=PROJECT_A)["total_image_hashes"] == 0
        
        # Add image to default
        img1 = create_test_image("stats_default.png", "red")
        hash_file(img1, project=None)
        time.sleep(0.3)
        
        # Default should have 1, project_alpha should have 0
        assert get_stats(project=None)["total_image_hashes"] >= 1
        assert get_stats(project=PROJECT_A)["total_image_hashes"] == 0
        
        # Add image to project_alpha
        img2 = create_test_image("stats_alpha.png", "green")
        hash_file(img2, project=PROJECT_A)
        time.sleep(0.3)
        
        # Both should now have items
        assert get_stats(project=None)["total_image_hashes"] >= 1
        assert get_stats(project=PROJECT_A)["total_image_hashes"] >= 1
        
        print("✓ Stats correctly scoped to projects")


# =============================================================================
# Reset Tests
# =============================================================================

class TestProjectReset:
    """Test reset is correctly scoped to projects."""
    
    def test_reset_only_affects_target_project(self):
        """Reset should only clear the specified project."""
        reset_all()
        
        # Add items to both projects
        img1 = create_test_image("reset_default.png", "red")
        img2 = create_test_image("reset_alpha.png", "green")
        
        hash_file(img1, project=None)
        hash_file(img2, project=PROJECT_A)
        time.sleep(0.3)
        
        # Verify both have items
        assert get_stats(project=None)["total_image_hashes"] >= 1
        assert get_stats(project=PROJECT_A)["total_image_hashes"] >= 1
        
        # Reset only project_alpha
        requests.post(f"{BASE_URL}/reset", params={"project": PROJECT_A}, timeout=30)
        time.sleep(0.3)
        
        # Default should still have items, project_alpha should be empty
        assert get_stats(project=None)["total_image_hashes"] >= 1
        assert get_stats(project=PROJECT_A)["total_image_hashes"] == 0
        
        print("✓ Reset correctly scoped to target project")


# =============================================================================
# Combined Test
# =============================================================================

class TestMixedMediaProjectIsolation:
    """Test all media types together across projects."""
    
    def test_full_isolation(self):
        """Test complete isolation with all media types across all projects."""
        reset_all()
        
        # Create test files
        img_path = create_test_image("mixed_img.png")
        audio_path = create_test_audio("mixed_audio.mp3")
        video_path = create_test_video("mixed_video.mp4")
        
        # Hash all in default project
        hash_file(img_path, project=None)
        hash_file(audio_path, project=None)
        hash_file(video_path, project=None)
        time.sleep(0.3)
        
        # All should match in default
        assert len(match_file(img_path, project=None)) >= 1, "Image should match in default"
        assert len(match_file(audio_path, project=None)) >= 1, "Audio should match in default"
        assert len(match_file(video_path, project=None)) >= 1, "Video should match in default"
        
        # None should match in project_alpha
        assert len(match_file(img_path, project=PROJECT_A)) == 0, "Image should NOT match in project_alpha"
        assert len(match_file(audio_path, project=PROJECT_A)) == 0, "Audio should NOT match in project_alpha"
        assert len(match_file(video_path, project=PROJECT_A)) == 0, "Video should NOT match in project_alpha"
        
        # Now hash same files in project_alpha
        hash_file(img_path, project=PROJECT_A)
        hash_file(audio_path, project=PROJECT_A)
        hash_file(video_path, project=PROJECT_A)
        time.sleep(0.3)
        
        # All should now match in project_alpha too
        assert len(match_file(img_path, project=PROJECT_A)) >= 1, "Image should match in project_alpha"
        assert len(match_file(audio_path, project=PROJECT_A)) >= 1, "Audio should match in project_alpha"
        assert len(match_file(video_path, project=PROJECT_A)) >= 1, "Video should match in project_alpha"
        
        # Reset project_alpha
        requests.post(f"{BASE_URL}/reset", params={"project": PROJECT_A}, timeout=30)
        time.sleep(0.3)
        
        # Default should still match, project_alpha should not
        assert len(match_file(img_path, project=None)) >= 1, "Image should still match in default"
        assert len(match_file(img_path, project=PROJECT_A)) == 0, "Image should NOT match in reset project_alpha"
        
        print("✓ Full isolation test passed for all media types")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])