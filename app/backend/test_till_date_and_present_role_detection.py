"""Regression tests for defects found comparing two versions of a real CV
the user provided directly (2026-09-04): one produced by ChatGPT, one by
the portal, with the portal's version missing an entire present-employment
section, showing the wrong job title in the letterhead, and -- as a direct
consequence -- an auto-drafted biography built from that wrong title
("Dr Afiya Thaha is an Administrator Mar 2019 - Apr 2020, with over 8
years of experience...").

Four distinct bugs, all in ongoing-role detection:

  1. "Till date" (as opposed to "to date") was not a recognised separator
     at all in YEAR_RANGE_RE, so an entry dated only this way ("September
     2024 till date") never matched a date range in the first place --
     with no date, it could never be recognised as the person's current,
     ongoing role.
  2. The date's start year and its open-ended marker landed on two
     different physical lines ("Executive, Director (2024)" / "till date
     Spearheaded the international expansion...") -- a shape
     ENTRY_END_YEAR_RE's own "this entry ends with its date column" check
     read as a complete, CLOSED single-year date, forcing the open-ended
     marker on the next line to start a bogus new entry instead of
     completing the same one.
  3. Once merged onto one line, "(2024) till date" still failed to parse:
     the closing paren right after the start year broke YEAR_RANGE_RE's
     match immediately, before it ever reached the separator.
  4. Present-vs-previous classification under one undifferentiated
     "EXPERIENCE" heading required an entry's employer name to literally
     contain "middlesex" -- a hard-coded assumption that broke down for
     anyone holding more than one genuinely concurrent role, only one of
     them at Middlesex: every other current role fell through to Previous
     Employment regardless of what the CV itself said.

Also covers a regression this uncovered and fixed in the same pass: fixing
present/previous classification to be based on fields["is_current"]
correctly propagated a role's own duty bullets into Present Employment
too (via the existing duty-inheritance logic) -- which then inflated the
"how many present-employment ENTRIES are there" ambiguity count used to
decide whether the letterhead's own job title should win, counting every
duty bullet as if it were a separate concurrent role.

Run directly: python test_till_date_and_present_role_detection.py
"""
import rule_classifier as rc


# --- Bug 1: "till date" not recognised as a separator -------------------

def test_till_date_is_recognised_as_an_ongoing_date_range():
    text = "Executive, Director | PMS College of Dental Science & Research | Kerala, India | September 2024 till date"
    fields = rc._extract_employment_fields(text, "unit")
    assert fields["start_date"] == "2024"
    assert fields["is_current"] is True


def test_to_date_still_works_unchanged():
    text = "Consultant | Example Corp | Dubai, UAE | January 2020 to date"
    fields = rc._extract_employment_fields(text, "employer")
    assert fields["start_date"] == "2020"
    assert fields["is_current"] is True


# --- Bug 2: start year and open-ended marker split across two lines -----

def test_year_in_parens_followed_by_till_date_on_next_line_merges():
    body_lines = [
        "PMS COLLEGE OF DENTAL SCIENCE & RESEARCH Kerala, India",
        "Executive, Director (2024)",
        "till date Spearheaded the international expansion strategy.",
    ]
    grouped = rc._group_into_items(body_lines, section_key="previous_employment")
    assert len(grouped) == 1
    assert "till date" in grouped[0]


def test_a_genuinely_closed_single_year_entry_still_splits_normally():
    # The check this fix narrows must not stop recognising an ENTRY that
    # really did end that year, with an unrelated new entry right after.
    body_lines = [
        "Lecturer, Department of Pathology (2019)",
        "Encouraged active student participation through group discussions.",
    ]
    grouped = rc._group_into_items(body_lines, section_key="previous_employment")
    assert len(grouped) == 2


# --- Bug 3: closing paren right after the start year breaks the match ---

def test_paren_wrapped_start_year_then_till_date_parses():
    text = "Executive, Director (2024) till date Spearheaded the international expansion strategy."
    fields = rc._extract_employment_fields(text, "employer")
    assert fields.get("start_date") == "2024"
    assert fields.get("is_current") is True


# --- Bug 4: present/previous required "middlesex" in the employer -------

def test_present_role_at_a_non_middlesex_employer_is_recognised():
    cv_text = (
        "EXPERIENCE\n"
        "Executive Director | PMS College of Dental Science & Research | Kerala, India\n"
        "September 2024 till date\n"
        "Spearheads the international expansion strategy.\n"
        "General Practitioner | Aspen Medical | Abu Dhabi, UAE\n"
        "January 2021 - November 2022\n"
        "Managed more than 40 patients per day.\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    present = [it for it in items if it["section"] == "present_employment"]
    previous = [it for it in items if it["section"] == "previous_employment"]
    assert any("Executive Director" in it["source_text"] for it in present)
    assert any("Aspen Medical" in it["source_text"] for it in previous)
    assert not any("Aspen Medical" in it["source_text"] for it in present)


# --- Regression this fix surfaced: duty bullets inflating the role count

def test_multiple_duty_bullets_under_one_present_role_still_count_as_one_role():
    cv_text = (
        "Seada A. Kassie\n"
        "Assistant Professor of Psychology\n"
        "Address: Dubai, UAE\n"
        "Phone: 00971551764000\n"
        "E-mail: sdkassie@gmail.com\n"
        "Professional Experience\n"
        "2023-09 - Current\n"
        "Assistant Professor/Senior Lecturer, Psychology\n"
        "Middlesex University, Dubai, UAE\n"
        "Develop innovative teaching methods that foster critical thinking "
        "and problem-solving skills among students.\n"
        "Present research findings at national and international "
        "conferences, raising awareness on pertinent psychological topics.\n"
        "Publish several peer-reviewed articles, contributing to the "
        "advancement of the field of psychology.\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    title_items = [it for it in items if it["section"] == "job_title"]
    assert len(title_items) == 1
    # A single role with three duty bullets must still be treated as ONE
    # role for the letterhead-vs-employment-title decision, not as if the
    # person held three concurrent jobs.
    assert title_items[0]["fields"]["value"].startswith("Assistant Professor/Senior Lecturer")


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
