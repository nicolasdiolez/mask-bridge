"""Tests for the shared validation helpers (validation.py)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation import parse_exclude, normalize_manifest, MAX_BATCH_SIZE


class TestParseExclude:
    def test_none_and_empty(self):
        assert parse_exclude(None) is None
        assert parse_exclude('') is None
        assert parse_exclude([]) is None
        assert parse_exclude(' , ,') is None

    def test_csv_with_spaces(self):
        # Natural Dashboard input: "bench, chair" must exclude BOTH classes
        assert parse_exclude('bench, chair') == ['bench', 'chair']

    def test_csv_lowercased(self):
        assert parse_exclude('Bench,CHAIR') == ['bench', 'chair']

    def test_list_input(self):
        assert parse_exclude([' Bench ', 'chair']) == ['bench', 'chair']

    def test_single_value(self):
        assert parse_exclude('dog') == ['dog']


class TestNormalizeManifest:
    def test_refine_defaults_match_product(self):
        # Product default is the fast hard mask: both refinement modes opt-in
        cfg = normalize_manifest({})
        assert cfg['edge_refine'] is False
        assert cfg['birefnet_refine'] is False

    def test_refine_flags_pass_through(self):
        cfg = normalize_manifest({'edge_refine': True, 'birefnet_refine': True})
        assert cfg['edge_refine'] is True
        assert cfg['birefnet_refine'] is True

    def test_threshold_clamped_to_probability_range(self):
        assert normalize_manifest({'threshold': 5.0})['threshold'] == 1.0
        assert normalize_manifest({'threshold': -1.0})['threshold'] == 0.0

    def test_threshold_nan_inf_fall_back_to_default(self):
        assert normalize_manifest({'threshold': float('nan')})['threshold'] == 0.35
        assert normalize_manifest({'threshold': float('inf')})['threshold'] == 0.35
        assert normalize_manifest({'threshold': float('-inf')})['threshold'] == 0.35

    def test_threshold_bad_type_raises(self):
        with pytest.raises(ValueError):
            normalize_manifest({'threshold': 'high'})

    def test_smoothing_clamped(self):
        assert normalize_manifest({'smoothing': 99})['smoothing'] == 15
        assert normalize_manifest({'smoothing': -3})['smoothing'] == 0

    def test_manifest_batch_size_limit(self):
        # Exceeding MAX_BATCH_SIZE raises ValueError
        oversized = [{'input': f'/tmp/in_{i}.jpg', 'output': f'/tmp/out_{i}.png'} for i in range(MAX_BATCH_SIZE + 1)]
        with pytest.raises(ValueError, match="Batch exceeds maximum limit"):
            normalize_manifest({'images': oversized})

