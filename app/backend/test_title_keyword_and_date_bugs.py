"""Regression tests for three real bugs found live-testing a real uploaded
CV (a psychology-department résumé with a scrambled two-column layout,
2026-09-02):

  1. TITLE_KEYWORDS' substring check false-positived: "intern" (meant to
     catch the job title "Intern") matched inside "international",
     turning an ordinary duty sentence ("...at national and international
     conferences...") into a fake job-title candidate that overwrote the
     real one -- and also fed a bogus "current role" promotion.
  2. A middle initial with a period ("Seada A. Kassie") broke name
     detection completely: NAME_LINE_RE's token pattern couldn't consume
     the trailing period on "A.", so the whole line failed to match and
     full_name came up entirely empty rather than just lower-confidence.
  3. normalize_date_range fabricated impossible years: "2020-09" (meant as
     September 2020, ISO year-month) is shape-identical to a genuine short
     year range ("1999-02" -> "1999-2002"), and the century-wraparound
     logic that correctly handles the latter produced "2020-2109" for the
     former -- 89 years in the future.

Run directly: python test_title_keyword_and_date_bugs.py
"""
import rule_classifier as rc


# --- Bug 1: TITLE_KEYWORDS substring false positive --------------------

def test_intern_does_not_match_inside_international():
    text = (
        "Present research findings at national and international "
        "conferences, raising awareness on pertinent psychological topics."
    )
    assert not rc._has_title_keyword(text)


def test_intern_still_matches_as_a_real_word():
    assert rc._has_title_keyword("Marketing Intern at Acme Corp")


def test_real_title_keywords_still_match_word_boundary():
    assert rc._has_title_keyword("Senior Lecturer in Psychology")
    assert rc._has_title_keyword("Assistant Professor of Psychology")
    assert rc._has_title_keyword("Head of Centre for Academic Success")
    # Word-boundary matching cuts both ways: "professor" has no trailing
    # boundary inside "Professorship" (no break between "professor" and
    # "ship"), so this must NOT match either -- the same mechanism that
    # fixes the "intern"/"international" false positive.
    assert not rc._has_title_keyword("Professorship Committee")


def test_looks_like_job_title_rejects_a_single_terminal_sentence():
    # The original check only caught sentence punctuation FOLLOWED BY more
    # text; a single sentence ending in one period at the very end had
    # nothing after it to catch, and sailed through untouched.
    text = (
        "Present research findings at national and international "
        "conferences, raising awareness on pertinent psychological topics."
    )
    assert not rc._looks_like_job_title(text)


def test_looks_like_job_title_still_accepts_a_real_title():
    assert rc._looks_like_job_title("Assistant Professor of Psychology")
    assert rc._looks_like_job_title("Senior Lecturer, International and Comparative Education")


def test_full_pipeline_does_not_misfile_job_title_as_a_duty_sentence():
    # Multiple duty bullets, same shape as the real live-tested CV -- a
    # single glued duty sentence with no other bullets to anchor the
    # title/employer comma-split is a separate, narrower quality gap (see
    # test_title_employer_split_is_imperfect_with_only_one_duty_line
    # below), not the bug this test is guarding against.
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
    value = title_items[0]["fields"]["value"]
    assert value.startswith("Assistant Professor/Senior Lecturer")
    assert "Present research findings" not in value
    assert "Publish several peer-reviewed" not in value


def test_title_employer_split_is_imperfect_with_only_one_duty_line():
    # Documents a known, narrow quality gap rather than asserting a fix:
    # with only ONE duty sentence and no comma boundary to split on,
    # _extract_employment_fields' title/employer split has nothing to
    # anchor on and the duty sentence bleeds into the title. Not a
    # fabrication (every word is still a real quote from the CV), and not
    # the "intern"/"international" misfiling bug -- just a real CV whose
    # current-role entry is this sparse would need HR's review anyway.
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
        "Present research findings at national and international "
        "conferences, raising awareness on pertinent psychological topics.\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    title_items = [it for it in items if it["section"] == "job_title"]
    assert len(title_items) == 1
    value = title_items[0]["fields"]["value"]
    assert value.startswith("Assistant Professor/Senior Lecturer")
    # Confidence must reflect the imperfection: never auto-approved as if
    # it were a clean, certain extraction.
    assert title_items[0]["confidence"] <= 0.7


# --- Bug 2: middle initial with a period breaking name detection -------

def test_name_line_matches_a_middle_initial_with_a_period():
    assert bool(rc.NAME_LINE_RE.match("Seada A. Kassie"))


def test_looks_like_person_name_accepts_middle_initial():
    assert rc._looks_like_person_name("Seada A. Kassie")


def test_ordinary_two_word_names_still_match():
    assert bool(rc.NAME_LINE_RE.match("Dimo Valev"))
    assert bool(rc.NAME_LINE_RE.match("Camilla Hadi Chaudhary"))


def test_full_pipeline_recovers_name_with_middle_initial():
    cv_text = (
        "Seada A. Kassie\n"
        "Assistant Professor of Psychology\n"
        "Address: Dubai, UAE\n"
        "Phone: 00971551764000\n"
        "E-mail: sdkassie@gmail.com\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    name_items = [it for it in items if it["section"] == "full_name"]
    assert len(name_items) == 1
    assert name_items[0]["fields"]["value"] == "Seada A. Kassie"


# --- Bug 3: date fabrication from ISO year-month vs short year range ---

def test_iso_year_month_is_left_unexpanded():
    assert rc.normalize_date_range("2020-09") == "2020-09"
    assert rc.normalize_date_range("2016-08") == "2016-08"


def test_iso_year_month_glued_to_a_title_is_left_unexpanded():
    assert rc.normalize_date_range("2020-09 -  Lecturer in Psychology") == (
        "2020-09 -  Lecturer in Psychology"
    )
    assert "2109" not in rc.normalize_date_range("2020-09 -  Lecturer in Psychology")


def test_genuine_short_year_range_still_expands():
    # The real, already-shipped case this feature exists for -- must not
    # regress while fixing the false-positive above.
    assert rc.normalize_date_range("1999 - 02") == "1999-2002"
    assert rc.normalize_date_range("2025-26") == "2025-2026"


def test_extract_employment_fields_does_not_fabricate_end_year():
    # Same fabrication, a second, independent implementation of the exact
    # same century-wraparound logic in _extract_employment_fields's
    # structured start_date/end_date -- not routed through
    # normalize_date_range at all, so fixing that function alone left this
    # one still producing "end_date": "2109" for a real live-tested CV.
    fields = rc._extract_employment_fields(
        "2020-09 -  Lecturer in Psychology", "employer"
    )
    assert fields["start_date"] == "2020"
    assert fields["end_date"] != "2109"
    assert fields["end_date"] == ""


def test_extract_employment_fields_still_handles_genuine_short_range():
    fields = rc._extract_employment_fields(
        "KIMEP University - Almaty | 1999 - 02", "employer"
    )
    assert fields["start_date"] == "1999"
    assert fields["end_date"] == "2002"


def test_bare_date_only_line_with_current_marker_is_recognised():
    # DATE_ONLY_RE previously required \d{4} alone for the start year --
    # "2023-09 - Current" (a month-qualified start date) fell through
    # unrecognised and was treated as ordinary content, eventually
    # fabricating a fake job-title item ("title": "Current").
    assert rc.DATE_ONLY_RE.match("2023-09 - Current")
    assert rc.DATE_ONLY_RE.match("2023-09 - Present")
    assert rc.DATE_ONLY_RE.match("2020 - 2023")


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
