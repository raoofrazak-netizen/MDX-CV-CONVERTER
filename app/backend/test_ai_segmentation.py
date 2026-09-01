"""Regression tests for ai/ollama_client.py's segmentation validator --
build spec §9's semantic segregation, and specifically the §6 zero-content-
loss policy applied to splitting: a segmentation is only ever accepted
all-or-nothing.

Deterministic and offline -- constructs the raw parsed-JSON shape a model
response would produce and feeds it straight to the validator, so this
runs the same whether or not Ollama is installed. Live end-to-end
verification against a real model happens separately (see HANDOVER.md).

Run directly: python test_ai_segmentation.py
"""
from ai.ollama_client import _validate_segmentation

VALID_SECTIONS = [
    {"key": "previous_employment", "label": "Previous Employment"},
    {"key": "teaching_learning", "label": "Teaching"},
    {"key": "publications", "label": "Publications"},
    {"key": "grants", "label": "Grants"},
]

ORIGINAL = (
    "Senior Lecturer, University X, 2018-2023. Taught undergraduate courses. "
    "Published research papers. Received a research grant."
)

VALID_SEGMENTS = [
    {"text": "Senior Lecturer, University X, 2018-2023.", "section": "previous_employment"},
    {"text": "Taught undergraduate courses.", "section": "teaching_learning"},
    {"text": "Published research papers.", "section": "publications"},
    {"text": "Received a research grant.", "section": "grants"},
]


def test_valid_full_coverage_split_accepted():
    parsed = {"status": "SEGMENT", "segments": VALID_SEGMENTS, "reasoning": "four distinct facts"}
    result = _validate_segmentation(parsed, ORIGINAL, VALID_SECTIONS)
    assert result is not None
    assert result.status == "SEGMENT"
    assert len(result.segments) == 4


def test_non_verbatim_text_rejects_whole_result():
    segments = list(VALID_SEGMENTS)
    segments[0] = {"text": "Senior Lecturer, University X, 2018-2025.", "section": "previous_employment"}
    parsed = {"status": "SEGMENT", "segments": segments, "reasoning": "x"}
    assert _validate_segmentation(parsed, ORIGINAL, VALID_SECTIONS) is None


def test_content_loss_rejects_whole_result():
    # Missing the publications and grants clauses entirely.
    segments = VALID_SEGMENTS[:2]
    parsed = {"status": "SEGMENT", "segments": segments, "reasoning": "partial"}
    assert _validate_segmentation(parsed, ORIGINAL, VALID_SECTIONS) is None


def test_invalid_section_key_rejects_whole_result():
    segments = list(VALID_SEGMENTS)
    segments[2] = {"text": "Published research papers.", "section": "made_up_section"}
    parsed = {"status": "SEGMENT", "segments": segments, "reasoning": "x"}
    assert _validate_segmentation(parsed, ORIGINAL, VALID_SECTIONS) is None


def test_no_split_passes_through_with_empty_segments():
    parsed = {"status": "NO_SPLIT", "reasoning": "one fact only"}
    result = _validate_segmentation(parsed, ORIGINAL, VALID_SECTIONS)
    assert result is not None
    assert result.status == "NO_SPLIT"
    assert result.segments == []


def test_review_required_passes_through_with_empty_segments():
    parsed = {"status": "REVIEW_REQUIRED", "reasoning": "ambiguous"}
    result = _validate_segmentation(parsed, ORIGINAL, VALID_SECTIONS)
    assert result is not None
    assert result.status == "REVIEW_REQUIRED"
    assert result.segments == []


def test_single_segment_is_not_a_real_split():
    parsed = {"status": "SEGMENT", "segments": [{"text": ORIGINAL, "section": "previous_employment"}], "reasoning": "x"}
    assert _validate_segmentation(parsed, ORIGINAL, VALID_SECTIONS) is None


def test_malformed_status_rejected():
    assert _validate_segmentation({"status": "MAYBE"}, ORIGINAL, VALID_SECTIONS) is None
    assert _validate_segmentation("not a dict", ORIGINAL, VALID_SECTIONS) is None


def test_negligible_punctuation_between_segments_does_not_count_as_loss():
    # A bullet separator consumed as a cut point, not repeated in either
    # segment, must not be treated as lost content.
    original = "• Taught courses • Published papers"
    parsed = {
        "status": "SEGMENT",
        "segments": [
            {"text": "Taught courses", "section": "teaching_learning"},
            {"text": "Published papers", "section": "publications"},
        ],
        "reasoning": "x",
    }
    result = _validate_segmentation(parsed, original, VALID_SECTIONS)
    assert result is not None
    assert len(result.segments) == 2


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"pass  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print("=" * 60)
    print(f"{len(tests) - failures} passed, {failures} failed, {len(tests)} total")
    if failures:
        raise SystemExit(1)
