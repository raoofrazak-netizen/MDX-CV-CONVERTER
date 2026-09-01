"""Regression tests for ai/knowledge_base.py -- build spec §15's MDX
template knowledge base. Deterministic and offline: no live Ollama needed,
since this only tests that the config loads, is complete, and stays in
sync with rule_classifier's real heading vocabulary.

Run directly: python test_ai_knowledge_base.py
"""
import ai.knowledge_base as kb
import rule_classifier
from config import SECTIONS

AI_OFFERED_KEYS = {
    s["key"] for s in SECTIONS if s["heading_text"] or s["key"] in ("skills", "language_proficiency")
}


def test_version_is_set():
    assert isinstance(kb.KB_VERSION, int)
    assert kb.KB_VERSION >= 1


def test_every_ai_offered_section_has_an_entry():
    covered = set(kb.all_section_keys())
    missing = AI_OFFERED_KEYS - covered
    assert not missing, f"missing knowledge-base entries: {missing}"


def test_every_entry_has_required_fields():
    for key in kb.all_section_keys():
        ctx = kb.get_section_context(key)
        assert ctx["description"].strip(), f"{key} has an empty description"
        assert isinstance(ctx["examples"], list), key
        assert isinstance(ctx["exclude"], list), key
        assert isinstance(ctx["heading_synonyms"], list), key


def test_heading_synonyms_mirror_rule_classifier_not_duplicated_by_hand():
    # The whole point of merging at load time instead of hand-copying: this
    # test would catch the synonym lists silently drifting apart if anyone
    # ever pastes a static copy into the JSON instead of relying on the merge.
    for key in kb.all_section_keys():
        ctx = kb.get_section_context(key)
        rule_synonyms = set(rule_classifier.SYNONYM_HEADINGS.get(key, []))
        assert rule_synonyms.issubset(set(ctx["heading_synonyms"])), (
            f"{key}: knowledge base is missing rule_classifier synonyms {rule_synonyms - set(ctx['heading_synonyms'])}"
        )


def test_official_heading_text_included_when_present():
    heading_text_by_key = {s["key"]: s["heading_text"] for s in SECTIONS}
    for key in kb.all_section_keys():
        official = heading_text_by_key.get(key)
        if official:
            assert official in kb.get_section_context(key)["heading_synonyms"], key


def test_format_section_for_prompt_handles_unknown_key_gracefully():
    # A key with no knowledge-base entry (shouldn't happen given the
    # coverage check above, but the formatter must not crash if it does)
    # falls back to a bare label instead of raising.
    text = kb.format_section_for_prompt("not_a_real_key", "Some Label")
    assert "Some Label" in text


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
