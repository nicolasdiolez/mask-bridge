"""Tests for the mask-refinement helpers in inference_engine.py.

These cover the pure post-processing functions (no ONNX model needed):
  - _guided_filter   edge-aware refinement (He et al. 2010)
  - _gate_alpha      class-gating of the BiRefNet alpha by the RF-DETR mask
  - _birefnet_coverage_ok  sanity guard against a collapsed gated alpha
"""
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inference_engine import MaskBridgeEngine


class TestGuidedFilter:
    def test_shape_type_and_range(self):
        guide = np.random.rand(64, 48).astype(np.float32)
        src = (np.random.rand(64, 48) > 0.5).astype(np.float32)
        out = MaskBridgeEngine._guided_filter(guide, src, radius=4)
        assert out.shape == src.shape
        assert out.dtype == np.float32
        # The filter can slightly over/undershoot; it must not explode
        assert out.min() > -0.5
        assert out.max() < 1.5

    def test_constant_src_preserved(self):
        # A constant mask must come out (nearly) unchanged whatever the guide
        guide = np.random.rand(64, 64).astype(np.float32)
        src = np.full((64, 64), 0.7, dtype=np.float32)
        out = MaskBridgeEngine._guided_filter(guide, src, radius=4)
        assert np.allclose(out, 0.7, atol=1e-3)

    def test_output_snaps_to_guide_edge(self):
        # Guide: sharp vertical edge. Src: soft horizontal ramp. The refined
        # mask must follow the guide's structure: clearly darker left of the
        # edge, clearly brighter right of it.
        guide = np.zeros((64, 64), dtype=np.float32)
        guide[:, 32:] = 1.0
        ramp = np.linspace(0.0, 1.0, 64, dtype=np.float32)
        src = np.tile(ramp, (64, 1))
        out = MaskBridgeEngine._guided_filter(guide, src, radius=8)
        assert out[:, 40:].mean() > out[:, :24].mean() + 0.2


class TestGateAlpha:
    def test_fine_alpha_kept_inside_detection(self):
        coarse = np.zeros((100, 100), dtype=np.float32)
        coarse[40:60, 40:60] = 1.0
        fine = np.ones((100, 100), dtype=np.float32)  # BiRefNet fired everywhere
        gated = MaskBridgeEngine._gate_alpha(coarse, fine)
        assert gated[50, 50] > 0.99

    def test_fine_alpha_suppressed_far_from_detection(self):
        # A salient object elsewhere in the frame must NOT leak into the mask
        coarse = np.zeros((100, 100), dtype=np.float32)
        coarse[40:60, 40:60] = 1.0
        fine = np.ones((100, 100), dtype=np.float32)
        gated = MaskBridgeEngine._gate_alpha(coarse, fine)
        assert gated[5, 5] < 0.01

    def test_no_detection_kills_everything(self):
        coarse = np.zeros((50, 50), dtype=np.float32)
        fine = np.ones((50, 50), dtype=np.float32)
        gated = MaskBridgeEngine._gate_alpha(coarse, fine)
        assert float(gated.max()) == 0.0

    def test_output_within_unit_range(self):
        coarse = (np.random.rand(80, 80) > 0.7).astype(np.float32)
        fine = np.random.rand(80, 80).astype(np.float32)
        gated = MaskBridgeEngine._gate_alpha(coarse, fine)
        assert gated.min() >= 0.0
        assert gated.max() <= 1.0


class TestGateAlphaAtExportResolution:
    """The gate is built at a reduced working size (GATE_WORK_SIZE).

    Two things must hold: frames small enough not to be resized keep their exact
    previous result, and frames that ARE resized keep the same behaviour — the
    gate is a blurred blob, so the reduction has to be invisible in the mask.
    """

    @staticmethod
    def _full_resolution_reference(coarse, fine, dilate_frac=0.02):
        """What _gate_alpha did before the reduction, kept as the yardstick."""
        h, w = coarse.shape
        k = max(3, int(round(dilate_frac * max(h, w))) | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        gate = cv2.dilate((coarse > 0.3).astype(np.uint8), kernel)
        gate = cv2.GaussianBlur(gate.astype(np.float32), (k, k), 0)
        return fine * np.clip(gate, 0.0, 1.0)

    @staticmethod
    def _scene(long_edge):
        h, w = int(long_edge * 2 / 3), long_edge
        coarse = np.zeros((h, w), dtype=np.float32)
        cv2.ellipse(coarse, (w // 2, h // 2), (w // 5, h // 3), 0, 0, 360, 1.0, -1)
        fine = np.ones((h, w), dtype=np.float32)
        return coarse, fine

    @pytest.mark.parametrize('long_edge', [128, 512, MaskBridgeEngine.GATE_WORK_SIZE])
    def test_frames_at_or_below_work_size_are_bit_identical(self, long_edge):
        """No resize path: these must not change at all from the old behaviour."""
        coarse, fine = self._scene(long_edge)
        assert np.array_equal(MaskBridgeEngine._gate_alpha(coarse, fine),
                              self._full_resolution_reference(coarse, fine))

    @pytest.mark.parametrize('long_edge', [2048, 3000])
    def test_large_frames_match_the_full_resolution_result(self, long_edge):
        """The reduction only nudges the gate's soft ramp, never the decision.

        A single global tolerance would be arbitrary here, so this asserts the
        actual claim instead. The gate is a wide blurred ramp; rebuilding it
        smaller and stretching it back shifts that ramp by a sub-pixel amount,
        which shows up ONLY inside the ramp. Where the mask is solid and where
        it is empty — the two regions that decide whether a pixel belongs to
        the mask — must stay put.
        """
        coarse, fine = self._scene(long_edge)
        got = (np.clip(MaskBridgeEngine._gate_alpha(coarse, fine), 0, 1) * 255).astype(np.uint8)
        ref = (np.clip(self._full_resolution_reference(coarse, fine), 0, 1) * 255).astype(np.uint8)
        delta = np.abs(got.astype(int) - ref.astype(int))

        solid, empty = ref >= 247, ref <= 8
        assert delta[solid].max() <= 10, "the solid interior of the mask moved"
        assert delta[empty].max() <= 10, "the background outside the mask moved"

        # Everything else is the ramp itself: bounded, and a thin band.
        assert delta.max() <= 32
        assert delta.mean() < 1.0
        band = ~(solid | empty)
        assert band.mean() < 0.05, "the transition band should stay a thin ribbon"

    def test_still_suppresses_saliency_far_from_the_detection(self):
        """The gate's whole purpose, checked at an export-sized frame."""
        coarse, fine = self._scene(2048)
        gated = MaskBridgeEngine._gate_alpha(coarse, fine)
        h, w = coarse.shape
        assert gated[h // 2, w // 2] > 0.99   # inside the detection
        assert gated[5, 5] < 0.01             # opposite corner

    def test_coverage_stays_proportional_to_the_frame(self):
        """dilate_frac is a fraction of the long edge: same shape, same coverage.

        Without this, a change to the working size could silently make the gate
        tighter or looser depending on the user's export resolution.
        """
        small = MaskBridgeEngine._gate_alpha(*self._scene(1500))
        large = MaskBridgeEngine._gate_alpha(*self._scene(3000))
        assert abs(float((small > 0.5).mean()) - float((large > 0.5).mean())) < 0.01

    def test_unit_range_preserved_after_upsampling(self):
        coarse, fine = self._scene(2048)
        gated = MaskBridgeEngine._gate_alpha(coarse, fine)
        assert gated.min() >= 0.0 and gated.max() <= 1.0


class TestBirefnetCoverageGuard:
    def _square(self, size, lo, hi, value=1.0):
        m = np.zeros((size, size), dtype=np.float32)
        m[lo:hi, lo:hi] = value
        return m

    def test_full_coverage_passes(self):
        coarse = self._square(100, 40, 60)
        gated = self._square(100, 40, 60)
        assert MaskBridgeEngine._birefnet_coverage_ok(coarse, gated) is True

    def test_collapsed_alpha_fails(self):
        # BiRefNet matted a different (salient) subject: the gated alpha keeps
        # almost nothing of the detected object -> guard must reject it
        coarse = self._square(100, 20, 80)          # 3600 px detected
        gated = self._square(100, 49, 52)           # 9 px survived the gate
        assert MaskBridgeEngine._birefnet_coverage_ok(coarse, gated) is False

    def test_empty_coarse_fails(self):
        coarse = np.zeros((50, 50), dtype=np.float32)
        gated = np.ones((50, 50), dtype=np.float32)
        assert MaskBridgeEngine._birefnet_coverage_ok(coarse, gated) is False

    def test_partial_coverage_above_ratio_passes(self):
        coarse = self._square(100, 20, 80)          # 60×60 = 3600 px
        gated = self._square(100, 30, 68)           # 38×38 = 1444 px ≈ 40%
        assert MaskBridgeEngine._birefnet_coverage_ok(coarse, gated) is True

    def test_partial_coverage_below_ratio_fails(self):
        coarse = self._square(100, 20, 80)          # 3600 px
        gated = self._square(100, 40, 60, value=1.0)  # 400 px ≈ 11%
        assert MaskBridgeEngine._birefnet_coverage_ok(coarse, gated) is False

    def test_soft_values_use_half_threshold(self):
        # Pixels at alpha <= 0.5 must not count as covered
        coarse = self._square(100, 20, 80)
        gated = self._square(100, 20, 80, value=0.4)
        assert MaskBridgeEngine._birefnet_coverage_ok(coarse, gated) is False


class TestBirefnetRoiPlanning:
    """BiRefNet always sees BIREFNET_SIZE² pixels; the ROI plan decides how much
    of that budget lands on the subject instead of the background."""

    def _frame(self, h=2000, w=3000):
        return np.zeros((h, w), dtype=np.float32)

    def test_single_subject_gets_one_box_containing_it(self):
        coarse = self._frame()
        coarse[800:1200, 1400:1700] = 1.0
        boxes = MaskBridgeEngine.plan_birefnet_rois(coarse)
        assert len(boxes) == 1
        x0, y0, x1, y1 = boxes[0]
        assert x0 <= 1400 and y0 <= 800 and x1 >= 1700 and y1 >= 1200

    def test_box_adds_margin_for_context(self):
        """Hair extends past the coarse box; too tight a crop clips it to zero."""
        coarse = self._frame()
        coarse[800:1200, 1400:1700] = 1.0  # 300 wide, 400 tall
        x0, y0, x1, y1 = MaskBridgeEngine.plan_birefnet_rois(coarse)[0]
        m = MaskBridgeEngine.BIREFNET_ROI_MARGIN
        assert x0 == 1400 - int(300 * m) and x1 == 1700 + int(300 * m)
        assert y0 == 800 - int(400 * m) and y1 == 1200 + int(400 * m)

    def test_box_is_clamped_to_the_frame(self):
        coarse = self._frame(1000, 1000)
        coarse[0:200, 0:200] = 1.0  # flush against the top-left corner
        x0, y0, x1, y1 = MaskBridgeEngine.plan_birefnet_rois(coarse)[0]
        assert x0 == 0 and y0 == 0
        assert x1 <= 1000 and y1 <= 1000

    def test_cropping_actually_raises_the_detail_budget(self):
        """The whole point: the subject must reach the model at a higher density."""
        coarse = self._frame()
        coarse[800:1200, 1400:1700] = 1.0
        x0, y0, x1, y1 = MaskBridgeEngine.plan_birefnet_rois(coarse)[0]
        full = MaskBridgeEngine.BIREFNET_SIZE / max(coarse.shape)
        roi = MaskBridgeEngine.BIREFNET_SIZE / max(x1 - x0, y1 - y0)
        assert roi / full > 3.0

    def test_two_subjects_get_two_boxes(self):
        coarse = self._frame()
        coarse[300:700, 200:600] = 1.0
        coarse[300:700, 2200:2600] = 1.0
        assert len(MaskBridgeEngine.plan_birefnet_rois(coarse)) == 2

    def test_specks_below_keep_fraction_are_ignored(self):
        coarse = self._frame()
        coarse[800:1200, 1400:1700] = 1.0  # subject
        coarse[10:14, 10:14] = 1.0         # noise blob, far below 10% of it
        assert len(MaskBridgeEngine.plan_birefnet_rois(coarse)) == 1

    def test_scattered_subject_falls_back_to_full_frame(self):
        """More blobs than the cost ceiling: one full-frame pass beats N crops."""
        coarse = self._frame()
        for cx in (300, 1000, 1700, 2400):
            coarse[800:1200, cx:cx + 300] = 1.0
        assert MaskBridgeEngine.plan_birefnet_rois(coarse) == []

    def test_large_subject_falls_back_to_full_frame(self):
        """Cropping buys nothing once the box covers most of the frame."""
        coarse = self._frame()
        coarse[100:1900, 150:2850] = 1.0
        assert MaskBridgeEngine.plan_birefnet_rois(coarse) == []

    def test_no_detection_falls_back_to_full_frame(self):
        assert MaskBridgeEngine.plan_birefnet_rois(self._frame()) == []

    def test_soft_mask_uses_half_threshold(self):
        coarse = self._frame()
        coarse[800:1200, 1400:1700] = 0.4  # below 0.5 -> not a detection
        assert MaskBridgeEngine.plan_birefnet_rois(coarse) == []


class TestBirefnetRoiCompositing:
    """_birefnet_alpha_roi must paste crops back at the right place, leaving the
    rest at zero (which the class gate would have zeroed anyway).

    The crop path ships disabled (BIREFNET_ROI_ENABLED), so the tests that
    exercise the mechanism turn it on explicitly, and one test pins the shipped
    default: Fine detail must always take the full-frame pass.
    """

    def _engine_with_stub(self, recorder, roi_enabled=True):
        engine = MaskBridgeEngine("/nonexistent")
        engine.birefnet_session = object()
        engine.BIREFNET_ROI_ENABLED = roi_enabled

        def fake_alpha(patch_bgr):
            recorder.append(patch_bgr.shape[:2])
            return np.ones(patch_bgr.shape[:2], dtype=np.float32)

        engine._birefnet_alpha = fake_alpha
        return engine

    def test_ships_disabled_so_every_image_takes_the_full_frame_pass(self):
        """The 1.0 guarantee: with the shipped default nothing is ever cropped,
        however croppable the detection looks."""
        assert MaskBridgeEngine.BIREFNET_ROI_ENABLED is False

        calls = []
        engine = self._engine_with_stub(calls, roi_enabled=False)
        image = np.zeros((2000, 3000, 3), dtype=np.uint8)
        coarse = np.zeros((2000, 3000), dtype=np.float32)
        coarse[800:1200, 1400:1700] = 1.0  # a blob the planner would happily crop
        assert engine.plan_birefnet_rois(coarse), "planner should still find a box"

        alpha = engine._birefnet_alpha_roi(image, coarse)
        assert alpha.shape == (2000, 3000)
        assert calls == [(2000, 3000)]

    def test_alpha_lands_inside_the_roi_only(self):
        calls = []
        engine = self._engine_with_stub(calls)
        image = np.zeros((2000, 3000, 3), dtype=np.uint8)
        coarse = np.zeros((2000, 3000), dtype=np.float32)
        coarse[800:1200, 1400:1700] = 1.0

        alpha = engine._birefnet_alpha_roi(image, coarse)
        assert alpha.shape == (2000, 3000)
        assert alpha[1000, 1550] == 1.0   # inside the subject
        assert alpha[50, 50] == 0.0       # far outside the ROI
        # One inference, on the crop rather than the full frame
        assert len(calls) == 1
        assert calls[0] != (2000, 3000)

    def test_full_frame_fallback_runs_one_inference_on_everything(self):
        calls = []
        engine = self._engine_with_stub(calls)
        image = np.zeros((800, 800, 3), dtype=np.uint8)
        coarse = np.zeros((800, 800), dtype=np.float32)  # no detection

        alpha = engine._birefnet_alpha_roi(image, coarse)
        assert alpha.shape == (800, 800)
        assert calls == [(800, 800)]

    def test_two_subjects_are_both_composited(self):
        calls = []
        engine = self._engine_with_stub(calls)
        image = np.zeros((2000, 3000, 3), dtype=np.uint8)
        coarse = np.zeros((2000, 3000), dtype=np.float32)
        coarse[300:700, 200:600] = 1.0
        coarse[300:700, 2200:2600] = 1.0

        alpha = engine._birefnet_alpha_roi(image, coarse)
        assert len(calls) == 2
        assert alpha[500, 400] == 1.0
        assert alpha[500, 2400] == 1.0
        assert alpha[500, 1400] == 0.0  # the gap between them stays empty


class TestBirefnetIdleUnload:
    def _engine_with_fake_session(self):
        engine = MaskBridgeEngine("/nonexistent")
        engine.birefnet_session = object()  # stands in for an ORT session
        return engine

    def test_unloads_after_idle_period(self):
        engine = self._engine_with_fake_session()
        engine._birefnet_last_used = 0.0  # long ago
        assert engine.maybe_unload_birefnet(idle_seconds=600) is True
        assert engine.birefnet_session is None

    def test_keeps_recently_used_session(self):
        import time
        engine = self._engine_with_fake_session()
        engine._birefnet_last_used = time.time()
        assert engine.maybe_unload_birefnet(idle_seconds=600) is False
        assert engine.birefnet_session is not None

    def test_noop_when_not_loaded(self):
        engine = MaskBridgeEngine("/nonexistent")
        assert engine.maybe_unload_birefnet(idle_seconds=0) is False

    def test_default_idle_seconds_is_one_hour(self):
        import time
        engine = self._engine_with_fake_session()
        # Idle for 30 minutes (1800s) -> should NOT unload with default 3600s
        engine._birefnet_last_used = time.time() - 1800
        assert engine.maybe_unload_birefnet() is False
        assert engine.birefnet_session is not None

        # Idle for 65 minutes (3900s) -> should unload with default 3600s
        engine._birefnet_last_used = time.time() - 3900
        assert engine.maybe_unload_birefnet() is True
        assert engine.birefnet_session is None

    def test_warmup_birefnet_handles_exception_gracefully(self):
        engine = MaskBridgeEngine("/nonexistent")
        class FailingSession:
            def get_inputs(self):
                raise RuntimeError("Simulated warm-up failure")
        engine.birefnet_session = FailingSession()
        # Non-fatal: exception caught and logged
        engine._warmup_birefnet()
