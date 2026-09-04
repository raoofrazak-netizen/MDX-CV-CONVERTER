"""Regression tests for two qualification-parsing defects the user reported
directly (2026-09-04), pasting the actual before/after text: a PhD entry's
country was silently dropped for the Bachelor's degree only, and its
thesis title/supervisor line vanished from Qualifications entirely.

  1. "Syria" was simply missing from COUNTRY_NAMES -- not a parsing bug so
     much as an incomplete list, but the effect is the same: "Bachelor of
     Science, Economics — Damascus University (2007)" silently dropped
     ", Syria" while the three other degrees on the same CV, all at UK
     institutions, kept their country correctly.
  2. A thesis title/supervisor line sitting on its own physical line right
     under a doctoral or master's degree ("Thesis Title: '...'. Supervised
     by Prof. ...") has no degree/institution/year signal of its own, so
     the qualifications section's "no qualification signal -> reroute to
     Skills" check (added earlier this session for a differently-shaped
     problem -- see test_aatif_paren_dates_and_subjects.py) swept it out
     of Qualifications and into an unrelated Skills bullet with no
     connection to the degree it was describing.

Run directly: python test_qualification_country_and_thesis.py
"""
import rule_classifier as rc


# --- Bug 1: Syria (and a few obviously-missing neighbours) -------------

def test_syria_is_recognised_as_a_country():
    text = "Bachelor of Science in Economics | Damascus University, Syria September 2003 - November 2007"
    fields = rc._extract_qualification_fields(text)
    assert fields.get("country") == "Syria"
    assert fields.get("institution") == "Damascus University"


def test_other_previously_missing_middle_east_countries_recognised():
    for country in ("Yemen", "Palestine", "Libya", "Sudan"):
        assert rc.COUNTRY_RE.search(f"Example University, {country}")


# --- Bug 2: a thesis detail line swept out of Qualifications -----------

def test_thesis_title_line_stays_attached_to_its_degree():
    cv_text = (
        "EDUCATION\n"
        "Doctor of Philosophy (PhD) in Economics | University of Southampton (AACSB-Accredited), UK\n"
        "December 2012 – October 2017\n"
        "Thesis Title: 'Bank Size, Locality, SME Lending and Local Economies'. Supervised by Prof. Richard Werner\n"
        "Master of Science in Applied Econometrics | Kingston University London (AACSB-Accredited), UK\n"
        "September 2011 – October 2012\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    qual_items = [it for it in items if it["section"] == "qualifications"]
    assert len(qual_items) == 2
    phd_item = next(it for it in qual_items if it["fields"].get("degree") == "Doctor of Philosophy")
    override = phd_item["fields"].get("_line_override", "")
    assert "Thesis Title" in override
    assert "Supervised by Prof. Richard Werner" in override
    # The clean, structured summary line must still lead -- the thesis
    # detail is an ADDITIONAL line, not a replacement for it.
    assert override.startswith("Doctor of Philosophy, Economics")
    # And it must never leak into an unrelated section.
    assert not any("Thesis Title" in it["source_text"] for it in items if it["section"] != "qualifications")


def test_supervised_by_alone_also_stays_attached():
    cv_text = (
        "EDUCATION\n"
        "Master of Science in Applied Econometrics | Kingston University London, UK\n"
        "September 2011 – October 2012\n"
        "Supervised by Dr. Jane Smith\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    qual_items = [it for it in items if it["section"] == "qualifications"]
    assert len(qual_items) == 1
    assert "Supervised by Dr. Jane Smith" in qual_items[0]["fields"].get("_line_override", "")


def test_bare_gpa_line_still_merges_and_still_renders():
    # The pre-existing case this shares its merge logic with must keep
    # working, and -- since the fix touched the SAME code path -- must now
    # also actually render, not just sit unrendered in source_text.
    cv_text = (
        "EDUCATION\n"
        "Bachelor of Engineering in Mechanical | Example University, UK\n"
        "2010 – 2014\n"
        "GPA: 7.4 / 10\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    qual_items = [it for it in items if it["section"] == "qualifications"]
    assert len(qual_items) == 1
    assert "GPA: 7.4 / 10" in qual_items[0]["fields"].get("_line_override", "")


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
