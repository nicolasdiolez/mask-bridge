"""Regression tests for prompt → COCO class mapping coverage.

Guards the product promise of DETECTION_CLASSES_*.md: every COCO class is
addressable by its exact name, and every keyword documented in the EN class
list resolves to at least one class.
"""
import os
import re
import sys
import unicodedata

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inference_engine import COCO_91_TO_80, COCO_CLASSES, PROMPT_TO_CLASSES, MaskBridgeEngine

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCocoCoverage:
    def test_every_coco_class_has_identity_mapping(self):
        missing = [c for c in COCO_CLASSES if c not in PROMPT_TO_CLASSES]
        assert missing == [], f"COCO classes without a 1:1 prompt mapping: {missing}"

    def test_identity_mappings_point_to_own_index(self):
        for idx, name in enumerate(COCO_CLASSES):
            assert idx in PROMPT_TO_CLASSES[name], (
                f"'{name}' must map to its own index {idx}, got {PROMPT_TO_CLASSES[name]}"
            )

    def test_model_91_class_ids_map_to_the_80_classes(self):
        # RF-DETR emits the 91 COCO ids, with gaps for the unused ones.
        assert COCO_91_TO_80[1] == 0      # person
        assert COCO_91_TO_80[13] == 11    # stop sign, after the gap at 12
        assert COCO_91_TO_80[27] == 24    # backpack, after the gap at 26
        assert COCO_91_TO_80[90] == 79    # toothbrush
        assert 12 not in COCO_91_TO_80 and 26 not in COCO_91_TO_80
        assert sorted(COCO_91_TO_80.values()) == list(range(len(COCO_CLASSES)))

    def test_all_mapped_indices_are_valid(self):
        for key, indices in PROMPT_TO_CLASSES.items():
            for i in indices:
                assert 0 <= i < len(COCO_CLASSES), f"'{key}' maps to invalid index {i}"


class TestDocumentedKeywords:
    """Every keyword listed in docs/DETECTION_CLASSES_en.md must be mapped."""

    def _doc_keywords(self):
        doc_path = os.path.join(PLUGIN_ROOT, 'docs', 'DETECTION_CLASSES_en.md')
        with open(doc_path, encoding='utf-8') as f:
            text = f.read()
        keywords = set()
        # Table rows: "| class name | keyword, keyword |" (skips headers,
        # separator rows and the bold macro table at the bottom)
        for m in re.finditer(r'^\|\s*([a-z][a-z ]*?)\s*\|\s*([a-z ,\-]+?)\s*\|$', text, re.M):
            for kw in m.group(2).split(','):
                kw = kw.strip()
                if kw:
                    keywords.add(kw)
        return keywords

    def test_doc_parsing_finds_keywords(self):
        assert len(self._doc_keywords()) > 50

    def test_every_documented_keyword_is_mapped(self):
        unmapped = sorted(k for k in self._doc_keywords() if k not in PROMPT_TO_CLASSES)
        assert unmapped == [], f"Keywords promised by DETECTION_CLASSES_en.md but not mapped: {unmapped}"


class TestResolveTargetClasses:
    def test_simple_class(self):
        assert MaskBridgeEngine.resolve_target_classes(['person']) == {0}

    def test_case_and_whitespace_insensitive(self):
        assert MaskBridgeEngine.resolve_target_classes(['  Teddy Bear ']) == {77}

    def test_faq_example_teddy_bear(self):
        # The FAQ explicitly tells users to type "teddy bear"
        assert MaskBridgeEngine.resolve_target_classes(['teddy bear']) == {77}

    def test_group_macro(self):
        assert MaskBridgeEngine.resolve_target_classes(['vehicle']) == {2, 3, 5, 6, 7}

    def test_nfd_accents_normalized(self):
        # macOS UI text can arrive NFD-decomposed
        nfd = unicodedata.normalize('NFD', 'véhicule')
        assert MaskBridgeEngine.resolve_target_classes([nfd]) == {2, 3, 5, 6, 7}

    def test_mixed_known_and_unknown(self):
        assert MaskBridgeEngine.resolve_target_classes(['licorne', 'dog']) == {16}

    def test_unknown_prompt_raises_actionable_error(self):
        with pytest.raises(ValueError, match='licorne'):
            MaskBridgeEngine.resolve_target_classes(['licorne'])

    def test_empty_prompts_raise(self):
        with pytest.raises(ValueError):
            MaskBridgeEngine.resolve_target_classes([])
