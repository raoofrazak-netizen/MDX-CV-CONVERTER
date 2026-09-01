"""Regression tests for insights.suggest_heading_mappings -- build spec
§14: "use HR corrections as structured knowledge." Deterministic and
offline: constructs the raw {cv_id, section, fields} rows
storage.list_resolved_formerly_unmapped_items() would return and checks
the aggregation directly.

Run directly: python test_heading_mapping_suggestions.py
"""
import json

from insights import suggest_heading_mappings


def _row(cv_id, section, context, value="some text"):
    return {"cv_id": cv_id, "section": section, "fields": json.dumps({"context": context, "value": value})}


def test_repeated_agreeing_correction_is_suggested():
    rows = [
        _row("cv1", "previous_employment", "Professional Journey"),
        _row("cv2", "previous_employment", "Professional Journey"),
        _row("cv3", "previous_employment", "Professional Journey"),
    ]
    result = suggest_heading_mappings(rows, taught_headings=set())
    assert len(result) == 1
    assert result[0]["context"] == "Professional Journey"
    assert result[0]["suggested_section"] == "previous_employment"
    assert result[0]["cv_count"] == 3
    assert result[0]["agreement"] == 1.0


def test_single_occurrence_is_not_suggested():
    # Below MIN_CV_COUNT_FOR_SUGGESTION -- one correction could be a
    # one-off judgement call, not a repeatable pattern.
    rows = [_row("cv1", "previous_employment", "Professional Journey")]
    result = suggest_heading_mappings(rows, taught_headings=set())
    assert result == []


def test_inconsistent_corrections_are_not_suggested():
    # HR filed the same heading under two DIFFERENT sections about evenly
    # -- real evidence this needs case-by-case judgement, not a blanket rule.
    rows = [
        _row("cv1", "previous_employment", "Career Details"),
        _row("cv2", "academic_leadership", "Career Details"),
        _row("cv3", "previous_employment", "Career Details"),
        _row("cv4", "academic_leadership", "Career Details"),
    ]
    result = suggest_heading_mappings(rows, taught_headings=set())
    assert result == []


def test_dominant_pattern_survives_a_minority_disagreement():
    # 3 of 4 agree (75%) -- above the 70% agreement threshold, so this
    # still surfaces, using the majority section.
    rows = [
        _row("cv1", "previous_employment", "Career Details"),
        _row("cv2", "previous_employment", "Career Details"),
        _row("cv3", "previous_employment", "Career Details"),
        _row("cv4", "academic_leadership", "Career Details"),
    ]
    result = suggest_heading_mappings(rows, taught_headings=set())
    assert len(result) == 1
    assert result[0]["suggested_section"] == "previous_employment"
    assert result[0]["agreement"] == 0.75


def test_already_taught_heading_is_excluded():
    rows = [
        _row("cv1", "previous_employment", "Professional Journey"),
        _row("cv2", "previous_employment", "Professional Journey"),
    ]
    result = suggest_heading_mappings(rows, taught_headings={"professional journey"})
    assert result == []


def test_top_of_document_context_is_excluded():
    rows = [
        _row("cv1", "biography", "Top of document"),
        _row("cv2", "biography", "Top of document"),
    ]
    result = suggest_heading_mappings(rows, taught_headings=set())
    assert result == []


def test_multiple_contexts_ranked_by_cv_count():
    rows = (
        [_row(f"cv{i}", "previous_employment", "Career History") for i in range(4)]
        + [_row(f"cv{i}", "biography", "About Me") for i in range(2)]
    )
    result = suggest_heading_mappings(rows, taught_headings=set())
    assert [r["context"] for r in result] == ["Career History", "About Me"]


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
