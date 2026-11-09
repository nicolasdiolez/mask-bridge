"""
Tests for MaskBridgeEngine.merge_rgb_mask_to_rgba()
PNG Alpha (Transparency) Export feature
"""
import os
import sys
import tempfile
import numpy as np
import cv2
import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from inference_engine import MaskBridgeEngine


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as d:
        yield d


def _write_image(path, image):
    """Write an image to disk (BGR or grayscale)."""
    cv2.imwrite(path, image)


class TestMergeRgbMaskToRgba:
    """Tests for merge_rgb_mask_to_rgba static method."""

    def test_basic_merge_full_opacity(self, tmp_dir):
        """Red image + white mask → RGBA with full opacity."""
        # Create 100x100 red image (BGR)
        rgb = np.zeros((100, 100, 3), dtype=np.uint8)
        rgb[:, :, 2] = 255  # Red channel

        # White mask (fully opaque)
        mask = np.ones((100, 100), dtype=np.uint8) * 255

        rgb_path = os.path.join(tmp_dir, "red.png")
        mask_path = os.path.join(tmp_dir, "white_mask.png")
        output_path = os.path.join(tmp_dir, "output_rgba.png")

        _write_image(rgb_path, rgb)
        _write_image(mask_path, mask)

        MaskBridgeEngine.merge_rgb_mask_to_rgba(rgb_path, mask_path, output_path)

        assert os.path.exists(output_path), "Output file should exist"

        result = cv2.imread(output_path, cv2.IMREAD_UNCHANGED)
        assert result is not None, "Output should be readable"
        assert result.shape[2] == 4, "Output should have 4 channels (RGBA)"
        assert result.shape[:2] == (100, 100), "Output dimensions should match input"

        # The mask is copied as is (no blur): opaque red everywhere
        assert (result[:, :, 2] == 255).all()
        assert (result[:, :, 3] == 255).all()

    def test_transparent_areas(self, tmp_dir):
        """Red image + half-black mask → half transparent."""
        rgb = np.zeros((100, 100, 3), dtype=np.uint8)
        rgb[:, :, 2] = 255  # Red

        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[:50, :] = 255  # Top half white (opaque)
        # Bottom half black (transparent)

        rgb_path = os.path.join(tmp_dir, "red.png")
        mask_path = os.path.join(tmp_dir, "half_mask.png")
        output_path = os.path.join(tmp_dir, "output_half.png")

        _write_image(rgb_path, rgb)
        _write_image(mask_path, mask)

        MaskBridgeEngine.merge_rgb_mask_to_rgba(rgb_path, mask_path, output_path)

        result = cv2.imread(output_path, cv2.IMREAD_UNCHANGED)
        assert result is not None

        # Top area (y=10) should be opaque
        assert result[10, 50, 3] > 200, "Top half should be opaque"

        # Bottom area (y=90) should be transparent
        assert result[90, 50, 3] < 50, "Bottom half should be transparent"

    def test_dimension_mismatch(self, tmp_dir):
        """RGB 200x100 + mask 100x50 → output should be 200x100 RGBA."""
        rgb = np.zeros((100, 200, 3), dtype=np.uint8)
        rgb[:, :, 1] = 128  # Green-ish

        mask = np.ones((50, 100), dtype=np.uint8) * 255  # Smaller mask

        rgb_path = os.path.join(tmp_dir, "wide.png")
        mask_path = os.path.join(tmp_dir, "small_mask.png")
        output_path = os.path.join(tmp_dir, "output_resized.png")

        _write_image(rgb_path, rgb)
        _write_image(mask_path, mask)

        MaskBridgeEngine.merge_rgb_mask_to_rgba(rgb_path, mask_path, output_path)

        result = cv2.imread(output_path, cv2.IMREAD_UNCHANGED)
        assert result is not None
        assert result.shape[:2] == (100, 200), "Output should match RGB dimensions"
        assert result.shape[2] == 4, "Should have 4 channels"

    def test_invalid_rgb_path_raises(self, tmp_dir):
        """Should raise ValueError for non-existent RGB image."""
        mask = np.ones((10, 10), dtype=np.uint8) * 255
        mask_path = os.path.join(tmp_dir, "mask.png")
        _write_image(mask_path, mask)

        with pytest.raises(ValueError, match="Cannot read RGB image"):
            MaskBridgeEngine.merge_rgb_mask_to_rgba(
                os.path.join(tmp_dir, "nonexistent.png"),
                mask_path,
                os.path.join(tmp_dir, "out.png")
            )

    def test_invalid_mask_path_raises(self, tmp_dir):
        """Should raise ValueError for non-existent mask image."""
        rgb = np.zeros((10, 10, 3), dtype=np.uint8)
        rgb_path = os.path.join(tmp_dir, "rgb.png")
        _write_image(rgb_path, rgb)

        with pytest.raises(ValueError, match="Cannot read mask image"):
            MaskBridgeEngine.merge_rgb_mask_to_rgba(
                rgb_path,
                os.path.join(tmp_dir, "nonexistent_mask.png"),
                os.path.join(tmp_dir, "out.png")
            )
