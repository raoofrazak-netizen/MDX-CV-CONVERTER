"""Regression tests for defects found from a screenshot the user reported
directly (2026-09-04): a duty sentence split mid-phrase across two real
bullets in the source ("...student's graduation" / "projects."), and a
Wingdings-style arrow bullet ("➢ PERSONAL INFO") not recognised as a bullet
at all, gluing an entire unrelated heading onto the tail of a Skills line
("Languages: English | Arabic ➢ PERSONAL INFO").

Also covers a real regression caught mid-fix by the corpus suite: the fix
for the arrow glyphs above added new characters to BULLET_CHARS AFTER the
literal hyphen "-", which inside a regex character class turned "—-➢" into
an unintended Unicode RANGE (em dash through the arrow glyph) instead of
three literal characters -- silently breaking recognition of an ordinary
ASCII "-" bullet, which several real CVs in the corpus use. Fixed by moving
the hyphen back to a position with no ambiguity (the very end of the class).

Run directly: python test_wrapped_bullets_and_arrow_glyphs.py
"""
import rule_classifier as rc


# --- A duty sentence split mid-phrase across two real bullets -----------

def test_bullet_ending_mid_sentence_merges_with_its_own_continuation():
    body_lines = [
        "•\tDeveloping film program courses and syllabus.",
        "•\tAs well as supervising and evaluating student's graduation",
        "•\tprojects.",
    ]
    grouped = rc._group_into_items(body_lines, section_key="previous_employment")
    assert len(grouped) == 2
    assert grouped[1] == "As well as supervising and evaluating student's graduation projects."


def test_a_genuinely_new_short_bullet_is_not_merged():
    # A short bullet that opens CAPITALISED is a real, separate item, not
    # a wrapped continuation -- the capitalisation check must still gate
    # this.
    body_lines = [
        "•\tDeveloped course materials and syllabi.",
        "•\tSupervised final projects.",
    ]
    grouped = rc._group_into_items(body_lines, section_key="previous_employment")
    assert len(grouped) == 2


def test_a_long_lowercase_opening_bullet_is_not_wrongly_merged():
    # Guard against over-firing (the actual regression this test suite
    # caught): a long, substantial bullet that happens to open lowercase
    # is far more likely a real, separate duty than a wrapped fragment,
    # and merging it on produced text that no longer existed verbatim in
    # the source CV at all.
    body_lines = [
        "•\tSupervised training in the administration, scoring, and interpretation of clinical assessment instruments",
        "•\tincluding MMPI-2, MCMI-III/IV, SB-5, HAM-D, HARS, BDI, BAI, and Y-BOCS-II, with a focus on case formulation and professional report writing.",
    ]
    grouped = rc._group_into_items(body_lines, section_key="previous_employment")
    assert len(grouped) == 2


# --- Arrow-style bullet glyphs not recognised ----------------------------

def test_arrow_bullet_glyph_is_recognised():
    assert bool(rc.BULLET_START_RE.match("➢ PERSONAL INFO"))
    assert bool(rc.BULLET_START_RE.match("➤ Some other bullet"))


def test_arrow_bullet_separates_unrelated_content():
    body_lines = [
        "•\tLanguages: English | Arabic",
        "➢\tPERSONAL INFO",
    ]
    grouped = rc._group_into_items(body_lines, section_key="skills")
    assert len(grouped) == 2
    assert grouped[0] == "Languages: English | Arabic"
    assert grouped[1] == "PERSONAL INFO"


# --- The character-class regression this fix itself introduced ----------

def test_ascii_hyphen_bullet_still_recognised():
    assert bool(rc.BULLET_START_RE.match("-Co-convenor, Climate and Sustainability Education Seminar"))
    assert bool(rc.BULLET_START_RE.match("- A hyphen-bulleted line"))


def test_hyphen_and_arrow_bullets_coexist_in_one_document():
    body_lines = [
        "-Co-founder and Convenor, South Asian Approaches to Researching Education (SAARE) Network",
        "➢ Another entry entirely",
    ]
    grouped = rc._group_into_items(body_lines, section_key="academic_leadership")
    assert len(grouped) == 2


# --- A false-positive heading match on an ordinary sentence's last word -

def test_short_synonym_word_ending_a_sentence_is_not_a_heading():
    # "projects." (lowercase, period) must not be mistaken for the
    # "grants" section's "PROJECTS" synonym heading -- discovered because
    # it was forcing a spurious item boundary in the middle of a sentence.
    assert rc._find_heading_key("projects.") is None
    assert rc._find_heading_key("PROJECTS") == "grants"  # the real heading still works


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
        except Exception as exc:
            failures += 1
            print(f"ERROR {test.__name__}: {exc!r}")
    print("=" * 60)
    print(f"{len(tests) - failures} passed, {failures} failed, {len(tests)} total")
    if failures:
        raise SystemExit(1)
