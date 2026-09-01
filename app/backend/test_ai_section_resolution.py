"""Regression tests for ai/ollama_client.py's _resolve_section_key --
found via live end-to-end testing while wiring in the §15 knowledge base:
enriching prompts with each section's human-readable label right next to
its key made a real local model (llama3.2) start echoing the label's
casing back ("Qualifications") instead of the machine key
("qualifications") -- an accurate, well-reasoned answer that the original
exact-match check rejected outright as unusable.

Deterministic and offline.

Run directly: python test_ai_section_resolution.py
"""
from ai.ollama_client import _resolve_section_key

VALID_SECTIONS = [
    {"key": "qualifications", "label": "Qualifications"},
    {"key": "previous_employment", "label": "Career Details – Previous Employment"},
]


def test_exact_key_match():
    assert _resolve_section_key("qualifications", VALID_SECTIONS) == "qualifications"


def test_label_cased_response_resolves_to_key():
    # The real failure found live: model echoed the label's casing, not the key.
    assert _resolve_section_key("Qualifications", VALID_SECTIONS) == "qualifications"


def test_label_text_response_resolves_to_key():
    assert _resolve_section_key("Career Details – Previous Employment", VALID_SECTIONS) == "previous_employment"


def test_case_insensitive_label_also_resolves():
    assert _resolve_section_key("QUALIFICATIONS", VALID_SECTIONS) == "qualifications"


def test_unrelated_word_does_not_resolve():
    # Must still refuse anything outside the controlled vocabulary --
    # tolerating casing is not the same as accepting an invented section.
    assert _resolve_section_key("Awards", VALID_SECTIONS) is None
    assert _resolve_section_key("made_up_section", VALID_SECTIONS) is None


def test_non_string_and_empty_input_rejected():
    assert _resolve_section_key(None, VALID_SECTIONS) is None
    assert _resolve_section_key("", VALID_SECTIONS) is None
    assert _resolve_section_key(42, VALID_SECTIONS) is None
    assert _resolve_section_key("   ", VALID_SECTIONS) is None


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
