"""Regression tests for real defects found deep-auditing a fourth CV
(Mohamed Aatif Mohamed Shafi's, 2026-09-03) -- reported directly by the
user from a live conversion, with screenshots showing every employment
entry's job title replaced by the employer name, a qualification missing
its subject, and the letterhead job title wrong as a result.

Three distinct bugs, all traced to a convention neither of the first
three audits' source CVs used: "Title (Date Range) Employer", with the
date wrapped in its own parentheses sitting BETWEEN the title and the
employer, rather than after both (Afroz's CV) or in a separate
pipe-delimited field (Mukarram's CV).

  1. _extract_employment_fields' before/after split assumes ONE side of
     the date holds a comma-joined "Title, Employer" pair. In this
     convention neither side does -- the split falls across the date
     itself -- so "Middlesex University Dubai" (the employer, sitting
     after the date with no comma) looked exactly like short, clean role
     text and was taken whole as the title, discarding the real title
     entirely. This corrupted every employment entry, and since the
     letterhead's job title is promoted from the most recent employment
     entry's own parsed title, the letterhead was wrong too.
  2. Two consecutive entries welded into one item: "Digital Forensics
     Trainee (...)" never forced its own boundary because "trainee" was
     missing from TITLE_KEYWORDS, so _is_title_with_date_line (the check
     that recognises "a bare title-with-its-own-date line starts a new
     entry") never fired for it, and it read as a continuation of the
     previous entry's employer name instead.
  3. "BSc (Hons.) Information Technology" lost its subject entirely --
     _is_plausible_subject correctly rejects text with an unmatched
     bracket (a mis-parse signal), but the degree-classification
     parenthetical directly after the degree name ("(Hons.)") was only
     ever trimmed from the OUTER edges of the extracted text, leaving the
     closing ")" stranded in the middle once the leading "(" was gone --
     tripping that same guard and discarding a real, correctly-shaped
     subject.

Run directly: python test_aatif_paren_dates_and_subjects.py
"""
import rule_classifier as rc


# --- Bug 1: "Title (Date) Employer" -- date wrapped between the two -----

def test_title_paren_date_employer_convention_parses_correctly():
    cases = [
        ("Adjunct Faculty (Jan 2026-Present) Middlesex University Dubai",
         "Adjunct Faculty", "Middlesex University Dubai"),
        ("Consultant Software Developer (Jun 2024-Present) Middlesex University Dubai",
         "Consultant Software Developer", "Middlesex University Dubai"),
        ("CEI Lab Assistant (Oct 2023-Dec 2025) Middlesex University Dubai",
         "CEI Lab Assistant", "Middlesex University Dubai"),
        ("Data Analytics Intern (Jun 2022-Jul 2022) Crescar Partners",
         "Data Analytics Intern", "Crescar Partners"),
    ]
    for text, expected_title, expected_employer in cases:
        fields = rc._extract_employment_fields(text, "employer")
        assert fields["title"] == expected_title, (text, fields)
        assert fields["employer"] == expected_employer, (text, fields)


def test_paren_date_convention_does_not_break_other_conventions():
    # Guard against over-firing: a date NOT wrapped in its own parentheses
    # must still go through the ordinary before/after logic unaffected.
    text = "Business Development Manager, MILTEK Lifts LLC | Dec 2023 - Aug 2025 | Dubai, UAE"
    fields = rc._extract_employment_fields(text, "employer")
    assert fields["title"] == "Business Development Manager"
    assert fields["employer"] == "MILTEK Lifts LLC"


# --- Bug 2: "trainee" missing from the recognised title-keyword list ----

def test_trainee_is_a_recognised_title_keyword():
    assert rc._has_title_keyword("digital forensics trainee")


def test_trainee_entry_forces_its_own_item_boundary():
    body_lines = [
        "Student Learning Assistant (Oct 2022-Apr 2023) Middlesex University Dubai",
        "Digital Forensics Trainee (Jul 2022-Aug 2022) Trusted Systems Consultancy",
        "Data Analytics Intern (Jun 2022-Jul 2022) Crescar Partners",
    ]
    grouped = rc._group_into_items(body_lines, section_key="previous_employment")
    assert len(grouped) == 3
    assert not any("Assistant" in g and "Trainee" in g for g in grouped)


# --- Bug 3: a degree-classification parenthetical stranding a bracket ---

def test_hons_parenthetical_does_not_swallow_the_subject():
    text = "BSc (Hons.) Information Technology, Middlesex University, Dubai UAE (2023), First Class Honours"
    fields = rc._extract_qualification_fields(text)
    assert fields.get("subject") == "Information Technology"
    assert fields.get("degree") == "BSc"
    assert fields.get("institution") == "Middlesex University"


def test_plain_degree_without_classification_still_works():
    text = "MSc Data Science, Middlesex University, Dubai UAE (2025), Distinction"
    fields = rc._extract_qualification_fields(text)
    assert fields.get("subject") == "Data Science"


def test_genuinely_unbalanced_bracket_elsewhere_is_still_rejected():
    # The plausibility guard this fix works around must still catch a
    # REAL mis-parse -- only the specific "(Hons.)"-style classification
    # right after the degree is special-cased away.
    assert not rc._is_plausible_subject("Hons.) Information Technology")


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
