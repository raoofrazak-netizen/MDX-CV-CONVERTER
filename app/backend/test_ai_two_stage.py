"""Regression tests for ai/two_stage.py's combination logic (build spec
§20's "AI unavailable", "AI timeout", "rule and AI disagreement" cases).

Deterministic and offline -- uses mock providers, not live Ollama, so it
runs the same in CI as on a machine with no AI installed at all. Live
end-to-end verification against a real model happens separately (see
HANDOVER.md); this file exists to lock in the exact branch behaviour a live
model's non-determinism can't be relied on to re-exercise on every run --
most notably case 6, a real inconsistency an actual small local model
produced during manual testing (a "CHANGE" verdict naming the same section
pass 1 already proposed).

Run directly: python test_ai_two_stage.py
"""
from ai.provider import AIReview, AISuggestion
from ai.two_stage import run_two_stage_analysis

VALID_SECTIONS = [{"key": "awards", "label": "Awards"}, {"key": "qualifications", "label": "Qualifications"}]


class MockProvider:
    def __init__(self, suggestion, review):
        self.suggestion = suggestion
        self.review = review

    def analyze_content(self, source_text, current_section, valid_sections):
        return self.suggestion

    def review_classification(self, source_text, original_heading, proposed_section, valid_sections):
        return self.review


class DeadProvider:
    def analyze_content(self, *a, **kw):
        return None

    def review_classification(self, *a, **kw):
        return None


def test_genuine_disagreement_requires_review():
    provider = MockProvider(
        AISuggestion(status="CLASSIFY", section="awards", confidence=0.9, reasoning="r1"),
        AIReview(verdict="CHANGE", section="qualifications", confidence=0.9, reasoning="r2"),
    )
    result = run_two_stage_analysis(provider, "text", "unmapped", "Heading", VALID_SECTIONS)
    assert result.final_status == "REVIEW_REQUIRED"
    assert result.final_section is None


def test_rule_agreement_boosts_confidence():
    provider = MockProvider(
        AISuggestion(status="CLASSIFY", section="awards", confidence=0.9, reasoning="r1"),
        AIReview(verdict="ACCEPT", section=None, confidence=0.9, reasoning="r2"),
    )
    result = run_two_stage_analysis(provider, "text", "awards", "Heading", VALID_SECTIONS)
    assert result.final_confidence == round(min(1.0, 0.9 * 0.9 * 1.10), 2)


def test_rule_disagreement_penalises_confidence():
    provider = MockProvider(
        AISuggestion(status="CLASSIFY", section="awards", confidence=0.9, reasoning="r1"),
        AIReview(verdict="ACCEPT", section=None, confidence=0.9, reasoning="r2"),
    )
    result = run_two_stage_analysis(provider, "text", "qualifications", "Heading", VALID_SECTIONS)
    assert result.final_confidence == round(0.9 * 0.9 * 0.85, 2)


def test_pass2_failure_falls_back_to_pass1_at_reduced_confidence():
    provider = MockProvider(
        AISuggestion(status="CLASSIFY", section="awards", confidence=0.9, reasoning="r1"), None,
    )
    result = run_two_stage_analysis(provider, "text", "unmapped", "Heading", VALID_SECTIONS)
    assert result.final_status == "CLASSIFY"
    assert result.final_confidence == round(0.9 * 0.7, 2)
    assert result.pass2 is None


def test_pass1_unavailable_returns_none():
    result = run_two_stage_analysis(DeadProvider(), "text", "unmapped", "Heading", VALID_SECTIONS)
    assert result is None


def test_same_section_change_is_not_treated_as_disagreement():
    # Regression case: a real local model (llama3.2) returned exactly this
    # during manual testing -- verdict "CHANGE" with reasoning arguing for
    # a different section, but "section" left identical to pass 1's own
    # pick. Must combine as agreement (the two SECTIONS match), while the
    # raw pass2 verdict stays visible in the result for transparency.
    provider = MockProvider(
        AISuggestion(status="CLASSIFY", section="awards", confidence=0.8, reasoning="r1"),
        AIReview(verdict="CHANGE", section="awards", confidence=0.8, reasoning="r2 self-contradictory"),
    )
    result = run_two_stage_analysis(provider, "text", "unmapped", "Heading", VALID_SECTIONS)
    assert result.final_status == "CLASSIFY"
    assert result.final_section == "awards"
    assert result.pass2.verdict == "CHANGE"  # raw pass2 unchanged, for the UI's "show both passes"


def test_pass1_review_required_skips_pass2():
    provider = MockProvider(
        AISuggestion(status="REVIEW_REQUIRED", section=None, confidence=0.0, reasoning="unsure"),
        AIReview(verdict="ACCEPT", section=None, confidence=0.9, reasoning="should never be reached"),
    )
    result = run_two_stage_analysis(provider, "text", "unmapped", "Heading", VALID_SECTIONS)
    assert result.final_status == "REVIEW_REQUIRED"
    assert result.pass2 is None  # pass 2 was never called


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
