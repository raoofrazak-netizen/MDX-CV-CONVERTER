"""Regression tests for real defects found on a sixth CV, reported directly
by the user pasting the full raw Experience section alongside the portal's
generated output (2026-09-04) -- an academic/consultant CV using a
"Title | Employer | Location" convention (both separators literal pipes)
with the date on its own following line, under one single, undifferentiated
"EXPERIENCE" heading covering both present and previous roles.

Five distinct bugs, all in employment parsing:

  1. _extract_employment_fields had no concept of a pipe-delimited
     "Title | Employer | Location" line at all -- only comma-based
     splitting. "Senior Lecturer | Middlesex University Dubai | Dubai,
     UAE" has exactly one comma, right before the country, so the
     comma-split logic took everything up to "Dubai" as the "title" and
     "UAE" alone as the "employer" -- the real title and employer were
     silently fused into one fabricated field on every single entry in
     the document.
  2. A work-arrangement tag ("...September 2019|Contract") sitting right
     after a date, with nothing else on the "after" side, looked exactly
     like the short, clean role text the "before vs after the date"
     heuristic prefers -- so "Contract" itself was stored as a fabricated
     job title, with the real title/employer (sitting before the date,
     never considered) discarded.
  3. _starts_list_item's "a capitalised line ends a gerund list" check
     only looks at the SHAPE of the previous line's first word, not what
     it means -- "Teaching Fellow | Queen Mary University of London |
     London, UK" starts with "Teaching", a job title, not a duty
     sentence, and was read as "the gerund list just ended", splitting
     the title clean away from its own date line right below it.
  4. "Economist" was missing from TITLE_KEYWORDS, so the previous entry's
     last duty bullet welded onto the front of "Economist | Local First
     CIC | Winchester, UK" instead of it starting its own new entry --
     the same class of gap "trainee" had (see
     test_aatif_paren_dates_and_subjects.py).
  5. Under one undifferentiated "EXPERIENCE" heading covering both present
     and previous roles (no separate headings to lean on), a duty bullet
     carries no date or employer of its own -- _extract_employment_fields
     returns {} for it -- so the present/previous-employer check, run
     against each entry's OWN fields in isolation, could never see the
     employer name its OWN title line had just established two lines
     above it. A person's current role showed correctly under Present
     Employment as a bare title with NO duties at all -- every one of
     which silently reappeared under Previous Employment instead, mixed
     in with unrelated past jobs.

Run directly: python test_pipe_delimited_employment.py
"""
import rule_classifier as rc


# --- Bug 1: "Title | Employer | Location" title/employer fusion ---------

def test_pipe_delimited_title_employer_location_splits_correctly():
    text = "Senior Lecturer | Middlesex University Dubai | Dubai, UAE September 2026 – Present"
    fields = rc._extract_employment_fields(text, "unit")
    assert fields["title"] == "Senior Lecturer"
    assert fields["unit"] == "Middlesex University Dubai, Dubai, UAE"
    assert fields["is_current"] is True


def test_pipe_delimited_previous_role_also_splits_correctly():
    text = "Lecturer | University of Winchester | Winchester, UK October 2019 – July 2025"
    fields = rc._extract_employment_fields(text, "employer")
    assert fields["title"] == "Lecturer"
    assert fields["employer"] == "University of Winchester, Winchester, UK"
    assert fields["start_date"] == "2019"
    assert fields["end_date"] == "2025"


# --- Bug 2: a "|Contract" tag fabricated as the job title ---------------

def test_contract_tag_is_not_mistaken_for_the_role():
    text = "Consultant | United Nations Economic and Social Commission for Western Asia (UN-ESCWA) | Beirut, Lebanon September 2021 – November 2021|Contract"
    fields = rc._extract_employment_fields(text, "employer")
    assert fields["title"] == "Consultant"
    assert "UN-ESCWA" in fields["employer"]
    assert fields["title"] != "Contract"


def test_other_work_arrangement_tags_also_stripped():
    for tag in ("Full-time", "Part-time", "Freelance", "Permanent", "Temporary"):
        text = f"Analyst | Example Corp | London, UK January 2020 – March 2021|{tag}"
        fields = rc._extract_employment_fields(text, "employer")
        assert fields["title"] == "Analyst", (tag, fields)


# --- Bug 3: a job title starting with a gerund-shaped word ---------------

def test_gerund_shaped_title_does_not_wrongly_close_a_list():
    body_lines = [
        "•\tFormulated concrete policy actions to reduce export guarantee gaps.",
        "Teaching Fellow | Queen Mary University of London | London, UK",
        "January 2019 – September 2019|Contract",
        "•\tDesigned and delivered four Economics and Finance modules for undergraduate students.",
    ]
    grouped = rc._group_into_items(body_lines, section_key="previous_employment")
    assert len(grouped) == 3
    title_item = next(g for g in grouped if g.startswith("Teaching Fellow"))
    assert "January 2019" in title_item


def test_genuine_gerund_list_still_splits_correctly():
    # The original behaviour this check exists for must still work: a real
    # gerund-style duty list (no bullets) still splits when a new
    # capitalised line follows it.
    body_lines = [
        "Managing daily operations and budgets:",
        "Coordinating with vendors and suppliers",
        "Overseeing staff schedules and payroll",
        "Regional Sales Director",
    ]
    grouped = rc._group_into_items(body_lines, section_key="previous_employment")
    assert grouped[-1] == "Regional Sales Director"


# --- Bug 4: "Economist" missing from the recognised title-keyword list --

def test_economist_is_a_recognised_title_keyword():
    assert rc._has_title_keyword("economist")


def test_economist_entry_starts_its_own_item():
    body_lines = [
        "Supported students in their research projects and assignments, especially in data analysis.",
        "Economist | Local First CIC | Winchester, UK",
        "November 2014 – December 2018",
    ]
    grouped = rc._group_into_items(body_lines, section_key="previous_employment")
    assert len(grouped) == 2
    assert grouped[1].startswith("Economist")


# --- Bug 5: duty bullets not inheriting their title's present/previous --

def test_present_role_duties_inherit_present_employment_not_previous():
    cv_text = (
        "EXPERIENCE\n"
        "Senior Lecturer | Middlesex University Dubai | Dubai, UAE\n"
        "September 2026 – Present\n"
        "•\tLead and deliver Economics and Finance modules for undergraduate students.\n"
        "•\tContribute to taught programme design and development.\n"
        "Assistant Professor | United Arab Emirates University (UAEU) | Al Ain, UAE\n"
        "August 2025 – August 2026\n"
        "•\tDesigned and delivered four Economics courses for undergraduate students.\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    present = [it for it in items if it["section"] == "present_employment"]
    previous = [it for it in items if it["section"] == "previous_employment"]
    assert len(present) == 3  # title + its 2 duty bullets
    assert not any("Lead and deliver" in it["source_text"] for it in previous)
    assert not any("Contribute to taught" in it["source_text"] for it in previous)
    assert any("Designed and delivered four Economics courses" in it["source_text"] for it in previous)


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
