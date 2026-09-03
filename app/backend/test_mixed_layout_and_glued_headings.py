"""Regression tests for three real bugs found live-testing pasted CV content
with a mixed bulleted/unbulleted employment layout and a source CV written
in the MDX template itself (2026-09-02):

  1. "2023 to date" left the literal word "date" dangling in front of
     whatever text followed ("...to date Founder of a specialist..."), since
     YEAR_RANGE_RE's separator only consumed the connecting "to", and
     nothing recognised the bare word "date" as a complete open-ended
     marker (only "current date" / "present time" as qualified phrases were
     handled).
  2. A bare, unbulleted job-title line ("Lecturer - Sustainability...")
     interrupting a run of bulleted duty bullets welded onto the tail of
     the PREVIOUS entry's last bullet instead of starting its own entry --
     real CVs commonly mix an unbulleted title/employer header with
     bulleted duties underneath, and the grouping logic's bulleted-mode
     boundary rule only recognised a new bullet as starting an item.
  3. A source CV itself written in the MDX template, with several
     consecutive sections left completely empty, had those sections'
     official headings glued together on one physical line with no
     separator -- and because no single official heading matched that
     whole line, it read as ordinary content and got glued onto whatever
     real item preceded it (three empty sections' worth of boilerplate
     silently dressed up as an Awards bullet).

Run directly: python test_mixed_layout_and_glued_headings.py
"""
import rule_classifier as rc


# --- Bug 1: "to date" leaving "date" dangling --------------------------

def test_to_date_does_not_leave_date_dangling():
    fields = rc._extract_employment_fields(
        "TrueGreen Environmental Consultancy - Dubai, UAE | 2023 to date",
        "employer",
    )
    assert fields["is_current"] is True
    assert fields["start_date"] == "2023"
    assert "date" not in (fields.get("title") or "").lower().split()


def test_to_date_glued_to_following_line_no_longer_leaks():
    # Grouping legitimately produces one glued string here ("...to date
    # Founder of..." -- the two source lines really are adjacent with no
    # boundary between them); the bug was specifically that field
    # extraction then left "date" stuck to the FRONT of the parsed title,
    # rather than recognising "to date" as a complete open-ended marker.
    body_lines = [
        "TrueGreen Environmental Consultancy - Dubai, UAE | 2023 to date",
        "Founder of a specialist environmental consultancy.",
    ]
    grouped = rc._group_into_items(body_lines)
    assert len(grouped) == 1
    fields = rc._extract_employment_fields(grouped[0], "employer")
    assert fields["is_current"] is True
    title = (fields.get("title") or "") + " " + (fields.get("employer") or "")
    assert not title.strip().lower().startswith("date")


def test_ordinary_to_present_and_to_current_still_work():
    fields = rc._extract_employment_fields("Acme Inc | 2020 to present", "employer")
    assert fields["is_current"] is True
    fields2 = rc._extract_employment_fields("Acme Inc | 2020 to current", "employer")
    assert fields2["is_current"] is True


# --- Bug 2: bare title line interrupting bulleted duties ---------------

def test_bare_title_line_starts_new_entry_in_bulleted_mode():
    body_lines = [
        "Founder & Managing Director",
        "TrueGreen Environmental Consultancy - Dubai, UAE | 2023 to date",
        "•\tAdvise corporate clients on environmental management.",
        "•\tLead stakeholder engagement with government authorities.",
        "Lecturer – Sustainability, Environmental Governance & Critical Thinking",
        "Middlesex University Dubai - Dubai, UAE | 2024 to date",
        "•\tDeliver interdisciplinary modules linking environmental science.",
    ]
    grouped = rc._group_into_items(body_lines)
    # The last duty bullet of the first entry must not have the second
    # entry's title welded onto its tail.
    assert not any("Lecturer" in g and "Lead stakeholder" in g for g in grouped)
    assert any(g.startswith("Lecturer") for g in grouped)


def test_bulleted_duty_text_does_not_spuriously_split():
    # A real duty bullet that happens to contain title-keyword-ish words
    # must not be mistaken for a new bare title line -- it has its own
    # bullet marker, so the has_bullets primary rule already handles it;
    # this just confirms the new condition doesn't ALSO fire redundantly
    # in a way that breaks anything.
    body_lines = [
        "•\tManaged a team of consultants and advisors on strategy.",
        "•\tTrained and supervised teams of interns and junior staff.",
    ]
    grouped = rc._group_into_items(body_lines)
    assert len(grouped) == 2


def test_full_pipeline_separates_all_three_employment_entries():
    cv_text = (
        "Relevant Professional Experience\n"
        "Founder & Managing Director\n"
        "TrueGreen Environmental Consultancy - Dubai, UAE | 2023 to date\n"
        "•\tAdvise corporate clients on environmental management.\n"
        "Lecturer – Sustainability, Environmental Governance & Critical Thinking\n"
        "Middlesex University Dubai - Dubai, UAE | 2024 to date\n"
        "•\tDeliver interdisciplinary modules linking environmental science.\n"
        "Executive Education & Operations Director\n"
        "Thunderbird School of Global Management - Dubai, UAE | 2015 - 2019\n"
        "•\tConducted organisational needs assessments for corporate clients.\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    titles = {
        (it["fields"].get("title") or "").split(",")[0].split(" Middlesex")[0].split(" Thunderbird")[0]
        for it in items
        if it["section"] in ("present_employment", "previous_employment")
        and it["fields"].get("title")
    }
    assert any(t.startswith("Founder") for t in titles)
    assert any(t.startswith("Lecturer") for t in titles)
    assert any(t.startswith("Executive Education") for t in titles)


# --- Bug 3: concatenated official headings with no content -------------

def test_concatenated_headings_line_is_recognised():
    line = (
        "CONTRIBUTION TO MDX CENTRES OF EXCELLENCE/RESEARCH LAB "
        "RESEARCH GRANTS, FUNDING AND CONSULTANCY PROJECTS "
        "EDITORIAL BOARD MEMBERSHIPS, REVIEW, AND EXAMINER ROLES"
    )
    assert rc._is_concatenated_headings_line(line)
    assert rc._is_junk_line(line)


def test_single_real_heading_is_not_flagged_as_concatenated():
    assert not rc._is_concatenated_headings_line("QUALIFICATIONS")
    assert not rc._is_concatenated_headings_line("CAREER DETAILS – PRESENT EMPLOYMENT")


def test_ordinary_content_is_not_flagged_as_concatenated():
    assert not rc._is_concatenated_headings_line(
        "Managed a portfolio of 300+ international clients across jurisdictions."
    )


def test_glued_empty_headings_do_not_attach_to_a_real_item():
    cv_text = (
        "Awards\n"
        "•\tOutstanding Educator of the Year Award 2025.\n"
        "CONTRIBUTION TO MDX CENTRES OF EXCELLENCE/RESEARCH LAB "
        "RESEARCH GRANTS, FUNDING AND CONSULTANCY PROJECTS "
        "EDITORIAL BOARD MEMBERSHIPS, REVIEW, AND EXAMINER ROLES\n"
        "SELECT RESEARCH PUBLICATIONS\n"
        "•\tSome Publication Title, Journal Name, 2024.\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    assert not any("CENTRES OF EXCELLENCE" in it["source_text"] for it in items)


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
