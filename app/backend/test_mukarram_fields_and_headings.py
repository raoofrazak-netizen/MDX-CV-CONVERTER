"""Regression tests for real defects found deep-auditing a third CV
(Mukarram Ahmed's, 2026-09-03) -- chosen for its clean, consistent
"Title, Employer | Date - Date | City, Country" pipe-delimited employment
convention, which stress-tested a different part of the pipeline than
either of the first two audits: field-splitting on a THIRD pipe-delimited
part, heading-vocabulary coverage, and the authoritative-heading check's
own typo-tolerance gap.

Three distinct bugs:

  1. _extract_employment_fields' before/after split assumes a TWO-part
     structure (date on one side, role on the other). A bare, un-bulleted
     entry with a THIRD pipe-delimited field ("Title, Employer | Date |
     City, Country") left a short, non-narrative location on the "after"
     side once the date was removed -- and the heuristic, built to prefer
     a short clean side over a long narrative one, had no way to tell a
     short LOCATION apart from a short TITLE. "Intern, Schindler Group |
     Jan 2018 - Jul 2018 | Dubai, UAE" stored "Dubai"/"UAE" as the
     title/employer, discarding the real ones.
  2. "Select Academic Projects, Papers and Conference Outputs" -- a
     publications heading by any reasonable reading -- resolved to
     `grants` instead, because "PROJECTS" (a grants synonym) was the
     longest single-word match found anywhere in the heading, while the
     existing "CONFERENCE PAPERS" synonym needs its two words adjacent and
     this heading reads "PAPERS AND CONFERENCE" (reversed, with "AND" in
     between). _structure_grants, built for a "Role: X" funding
     convention, could make sense of only 2 of 6 real conference papers
     and silently lost the other 4 to Unmapped.
  3. is_authoritative_heading checked ONLY exact official heading text,
     never a typo-tolerant fuzzy match -- unlike _find_heading_key, which
     already does. The template's own official heading has a baked-in
     typo, "INTERNAL AND EXERNAL ACADEMIC LEADERSHIP" (missing the T in
     "External") -- so a CV spelling it correctly, as almost every real CV
     does, was classified correctly by _find_heading_key but NOT
     recognised as "the CV explicitly named this section" by routing.py,
     which then re-routed its content elsewhere by wording alone ("Module
     Leader, ..." moved to Teaching and Learning on the word "Module").

Run directly: python test_mukarram_fields_and_headings.py
"""
import identifiers
import rule_classifier as rc


# --- Bug 1: a bare location on the far side of the date mistaken for a role

def test_bare_location_after_date_does_not_become_the_title():
    text = "Intern, Schindler Group | Jan 2018 - Jul 2018 | Dubai, UAE"
    fields = rc._extract_employment_fields(text, "employer")
    assert fields["title"] == "Intern"
    assert fields["employer"] == "Schindler Group"


def test_bare_location_fix_does_not_break_the_slash_titled_entry():
    text = "Marketing Consultant / Student Advisor, Freelance Consultant | Jan 2022 - May 2023 | Dubai, UAE"
    fields = rc._extract_employment_fields(text, "employer")
    assert fields["title"] == "Marketing Consultant / Student Advisor"
    assert fields["employer"] == "Freelance Consultant"


def test_real_narrative_after_the_date_still_wins_over_a_short_title():
    # Guard against over-firing: BARE_CITY_COUNTRY_RE must reject anything
    # that isn't JUST a location, so genuine duty text after the date is
    # unaffected by this fix.
    text = (
        "Jan 2013 - Present, New York, New York Deutsche Bank is a German global banking and "
        "financial services company. As a Sr Business Analyst, my core activities include: "
        "requirements gathering, stakeholder management, and process design."
    )
    fields = rc._extract_employment_fields(text, "employer")
    assert "New York" in fields.get("title", "") or "New York" in fields.get("employer", "")


# --- Bug 2: a conference-papers heading resolving to Grants instead of Publications

def test_conference_outputs_heading_resolves_to_publications():
    assert rc._find_heading_key(
        "SELECT ACADEMIC PROJECTS, PAPERS AND CONFERENCE OUTPUTS"
    ) == "publications"


def test_official_grants_heading_still_resolves_to_grants():
    # The fix must not steal "PROJECTS" away from a real grants heading.
    assert rc._find_heading_key("RESEARCH GRANTS, FUNDING AND CONSULTANCY PROJECTS") == "grants"


# --- Bug 3: a correctly-spelled heading not recognised as authoritative --

def test_correctly_spelled_academic_leadership_heading_is_authoritative():
    assert rc.is_authoritative_heading("INTERNAL AND EXTERNAL ACADEMIC LEADERSHIP")


def test_the_templates_own_typo_variant_is_still_authoritative():
    assert rc.is_authoritative_heading("INTERNAL AND EXERNAL ACADEMIC LEADERSHIP")


def test_academic_leadership_content_stays_put_once_authoritative():
    body_lines = [
        "Module Leader, Project Management: Applications and Technologies - undergraduate level, Middlesex University Dubai.",
        "Module Leader, Project Management for Global Business Management - postgraduate level, Middlesex University Dubai.",
    ]
    items = [
        {"section": "academic_leadership", "fields": {}, "confidence": 0.8, "source_text": t}
        for t in body_lines
    ]
    authoritative = {"academic_leadership"}
    routed = __import__("routing").apply_routing(items, authoritative)
    assert all(it["section"] == "academic_leadership" for it in routed)


# --- Bug 4: "ORCID Identifier: " one character past the old gap allowance

def test_orcid_identifier_label_is_recognised():
    found = identifiers.find_identifiers("ORCID Identifier: 0009-0009-7006-3510")
    orcid = [f for f in found if f["platform"] == "ORCID"]
    assert len(orcid) == 1
    assert orcid[0]["url"] == "https://orcid.org/0009-0009-7006-3510"


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
