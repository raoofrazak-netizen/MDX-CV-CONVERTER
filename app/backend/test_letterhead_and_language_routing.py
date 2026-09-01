"""Regression tests for three real bugs found via live testing on a
decorative, letter-spaced-heading résumé template (build spec live-test
session, 2026-08-30):

  1. A letter-spaced full name ("D E V A P R A B H A A .") was never
     recognised as a name at all -- name detection only collapses letter
     spacing for known section headings, not for the name-plate line.
  2. Because (1) failed, the ENTIRE letterhead (job title, contact, email --
     all correctly extracted) was left showing the template's own "how to
     fill this in" placeholder text: template_engine's letterhead loop only
     advances past "FULL NAME" when a name was actually found, so one
     missing field silently blocked three unrelated, correctly-extracted
     ones.
  3. Job-duty sentences from a scrambled two-column layout landed under
     "Language Proficiency" (whose only real content should be a language
     list) with no heading of their own -- both because the section wasn't
     eligible for meaning-based re-routing at all, and because a short,
     unpunctuated language line ("English Malayalam") welded onto the very
     next sentence during item-grouping regardless of what that sentence
     said.
  4. (Found on a separate CV, same session) Two real posts glued into one
     job-title line by a coordinating "and" ("Senior Lecturer, ..., and
     Head of Centre for Academic Success, Middlesex University, Dubai
     Campus") were stored and printed as one garbled line, even though the
     template's own instructions ask for each title listed individually.

All four are deterministic rule-engine bugs; none involve the optional AI
layer. Run directly: python test_letterhead_and_language_routing.py
"""
import re

import rule_classifier as rc
import routing
import template_engine


# --- Bug 1: letter-spaced full name ----------------------------------

def test_letter_spaced_name_with_trailing_period_is_name_shaped():
    assert rc._is_name_shaped_letter_spacing("D E V A P R A B H A A .")


def test_ordinary_letter_spaced_heading_is_still_name_shaped_too():
    # Collapsing doesn't distinguish a heading from a name by itself --
    # _looks_like_person_name's own _find_heading_key guard is what keeps a
    # collapsed heading like "CAREER" from being mistaken for one.
    assert rc._is_name_shaped_letter_spacing("C A R E E R")


def test_short_run_is_not_treated_as_letter_spaced():
    # Below the minimum run length, single letters are noise, not a
    # deliberately spaced word -- same threshold the heading check uses.
    assert not rc._is_name_shaped_letter_spacing("A B")


def test_collapse_letter_spaced_name_strips_trailing_punctuation():
    assert rc._collapse_letter_spaced_name("D E V A P R A B H A A .") == "DEVAPRABHAA"


def test_collapse_letter_spaced_name_returns_none_for_normal_text():
    assert rc._collapse_letter_spaced_name("John Smith") is None


def test_collapsed_single_run_passes_relaxed_name_check():
    # NAME_LINE_RE (the ordinary path) requires >=2 words and can never
    # match a collapsed single run -- this is the dedicated relaxed check
    # used only for candidates recovered by collapsing.
    assert rc._looks_like_collapsed_name("DEVAPRABHAA")


def test_relaxed_name_check_still_rejects_a_collapsed_heading():
    # "L A N G U A G E S" collapses to "LANGUAGES", which resolves to a
    # real section heading -- must still be rejected as a name candidate.
    collapsed = rc._collapse_letter_spaced_name("L A N G U A G E S")
    assert collapsed == "LANGUAGES"
    assert not rc._looks_like_collapsed_name(collapsed)


def test_full_pipeline_recovers_letter_spaced_name_from_real_layout():
    cv_text = (
        "D E V A P R A B H A A .\n"
        "A D M I N I S T R A T I V E P R O F E S S I O N A L\n"
        "W O R K E X P E R I E N C E\n"
        "Sunrise Hospital, India\n"
        "Appointment Executive\n"
        "JAN 2024 - PRESENT\n"
        "Enhancing patient satisfaction by delivering exceptional customer "
        "service during check-in and check-out.\n"
        "C O N T A C T\n"
        "+91 7306007026\n"
        "devaprabhaa77@gmail.com\n"
    )
    items = rc.classify_rule_based(cv_text, "Resume - Devaprabha.docx")
    name_items = [it for it in items if it["section"] == "full_name"]
    assert len(name_items) == 1, "expected exactly one full_name item"
    assert name_items[0]["fields"]["value"] == "DEVAPRABHAA"
    # source_text must still point at the real, verbatim quote from the
    # document -- never at the collapsed stand-in used for matching.
    assert name_items[0]["source_text"] == "D E V A P R A B H A A ."


# --- Bug 2: one missing letterhead field must not block the others ----

def test_missing_full_name_does_not_block_other_letterhead_fields():
    doc_xml = (
        "<w:tbl>"
        "<w:p><w:r><w:t>FULL NAME</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Job title: List each title individually...</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Contact: Please list your office desk phone number...</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Email: Dubai Campus Email Address</w:t></w:r></w:p>"
        "</w:tbl>"
    )
    items_by_section = {
        # full_name deliberately absent/empty -- the exact condition that
        # previously left every other field's placeholder text untouched.
        "job_title": [{"fields": {"value": "Appointment Executive"}}],
        "contact_info": [{"fields": {"value": "+91 7306007026"}}],
        "email": [{"fields": {"value": "devaprabhaa77@gmail.com"}}],
    }
    result = template_engine._populate_letterhead(doc_xml, items_by_section)
    assert "Job title: Appointment Executive" in result
    assert "Contact: +91 7306007026" in result
    assert "Email: devaprabhaa77@gmail.com" in result
    # The template's own instructional placeholder text must never survive.
    assert "List each title individually" not in result
    assert "office desk phone number" not in result
    assert "Dubai Campus Email Address" not in result


def test_present_full_name_still_fills_in_as_before():
    doc_xml = (
        "<w:tbl>"
        "<w:p><w:r><w:t>FULL NAME</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Job title: List each title individually...</w:t></w:r></w:p>"
        "</w:tbl>"
    )
    items_by_section = {
        "full_name": [{"fields": {"value": "Jane Doe"}}],
        "job_title": [{"fields": {"value": "Lecturer"}}],
    }
    result = template_engine._populate_letterhead(doc_xml, items_by_section)
    assert "Jane Doe" in result
    assert "Job title: Lecturer" in result


# --- Bug 3: language proficiency must not absorb job-duty content -----

def test_job_duty_sentence_regex_matches_real_examples():
    assert rc.JOB_DUTY_SENTENCE_RE.match(
        "Coordinated and streamlined hospital services, contributing to "
        "efficient workflows and improved patient care delivery."
    )
    assert rc.JOB_DUTY_SENTENCE_RE.match(
        "Acted as a liaison between departments, fostering collaboration "
        "and effective communication across teams."
    )


def test_job_duty_sentence_regex_does_not_match_a_language_list():
    assert not rc.JOB_DUTY_SENTENCE_RE.match("English Malayalam")


def test_language_line_no_longer_absorbs_following_duty_sentence():
    body_lines = [
        "English Malayalam",
        "Coordinated and streamlined hospital services, contributing to "
        "efficient workflows and improved patient care delivery.",
    ]
    grouped = rc._group_into_items(body_lines, section_key="language_proficiency")
    assert "English Malayalam" in grouped
    assert not any(item.startswith("English Malayalam Coordinated") for item in grouped)


def test_language_proficiency_is_routable_and_scoped_rule_covers_it():
    assert "language_proficiency" in routing.ROUTABLE_SOURCE_SECTIONS
    scoped_sources = next(
        sources for pattern, dest, sources in routing.SCOPED_RULES
        if pattern is routing.ACTION_VERB_RE
    )
    assert "language_proficiency" in scoped_sources


def test_duty_sentence_under_language_heading_reroutes_to_previous_employment():
    items = [{
        "section": "language_proficiency",
        "fields": {},
        "source_text": "Acted as a liaison between departments, fostering "
                        "collaboration and effective communication across teams.",
        "confidence": 0.8,
    }]
    routed = routing.apply_routing(items, authoritative_sections=set())
    assert routed[0]["section"] == "previous_employment"


def test_genuine_language_list_is_never_rerouted():
    items = [{
        "section": "language_proficiency",
        "fields": {},
        "source_text": "English Malayalam",
        "confidence": 0.8,
    }]
    routed = routing.apply_routing(items, authoritative_sections=set())
    assert routed[0]["section"] == "language_proficiency"


def test_full_pipeline_keeps_only_languages_under_language_proficiency():
    cv_text = (
        "D E V A P R A B H A A .\n"
        "L A N G U A G E S\n"
        "English Malayalam\n"
        "Coordinated and streamlined hospital services, contributing to "
        "efficient workflows and improved patient care delivery.\n"
        "Acted as a liaison between departments, fostering collaboration "
        "and effective communication across teams.\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    lang_items = [it for it in items if it["section"] == "language_proficiency"]
    assert len(lang_items) == 1
    assert lang_items[0]["source_text"] == "English Malayalam"
    duty_sections = {
        it["section"] for it in items
        if "Coordinated" in it["source_text"] or "Acted as a liaison" in it["source_text"]
    }
    assert duty_sections == {"previous_employment"}


# --- Bug 4: two posts glued into one job-title line -------------------

def test_admin_title_connector_finds_the_real_boundary():
    value = (
        "Senior Lecturer, International and Comparative Education, and "
        "Head of Centre for Academic Success, Middlesex University, Dubai Campus"
    )
    match = rc.ADMIN_TITLE_CONNECTOR_RE.search(value)
    assert match is not None
    assert match.group(1) == (
        "Head of Centre for Academic Success, Middlesex University, Dubai Campus"
    )


def test_ordinary_and_inside_a_department_name_is_not_mistaken_for_a_split():
    # "International and Comparative Education" must survive intact --
    # only a recognised leadership-title keyword after "and" is a boundary.
    value = "Senior Lecturer, International and Comparative Education"
    assert rc.ADMIN_TITLE_CONNECTOR_RE.search(value) is None


def test_split_dual_title_job_title_produces_two_lines_with_institution_stripped():
    # Real feedback after the split first shipped: the trailing university/
    # campus name reads as an address glued onto the title, not part of it.
    items = [{
        "section": "job_title",
        "fields": {"value": (
            "Senior Lecturer, International and Comparative Education, and "
            "Head of Centre for Academic Success, Middlesex University, Dubai Campus"
        )},
        "source_text": "irrelevant",
        "confidence": 0.7,
    }]
    result = rc._clean_job_titles(items)
    value = result[0]["fields"]["value"]
    lines = value.split("\n")
    assert lines == [
        "Senior Lecturer, International and Comparative Education",
        "Head of Centre for Academic Success",
    ]
    assert "Middlesex" not in value
    assert "Campus" not in value
    assert "multi_title_split" in result[0]["validation_flags"]
    assert result[0]["confidence"] <= 0.65


def test_trailing_institution_stripped_from_a_single_title_too():
    items = [{
        "section": "job_title",
        "fields": {"value": "Senior Lecturer, Middlesex University, Dubai Campus"},
        "source_text": "irrelevant",
        "confidence": 0.7,
    }]
    result = rc._clean_job_titles(items)
    assert result[0]["fields"]["value"] == "Senior Lecturer"
    assert "institution_stripped_from_title" in result[0]["validation_flags"]


def test_department_name_with_no_institution_keyword_survives_intact():
    # "Education" is not an institution keyword -- must not be mistaken
    # for one just because it follows a comma at the end of the line.
    items = [{
        "section": "job_title",
        "fields": {"value": "Senior Lecturer, International and Comparative Education"},
        "source_text": "irrelevant",
        "confidence": 0.7,
    }]
    result = rc._clean_job_titles(items)
    assert result[0]["fields"]["value"] == "Senior Lecturer, International and Comparative Education"
    assert "institution_stripped_from_title" not in result[0].get("validation_flags", [])


def test_single_title_is_left_alone():
    items = [{
        "section": "job_title",
        "fields": {"value": "Senior Lecturer"},
        "source_text": "Senior Lecturer",
        "confidence": 0.7,
    }]
    result = rc._clean_job_titles(items)
    assert result[0]["fields"]["value"] == "Senior Lecturer"
    assert "multi_title_split" not in result[0].get("validation_flags", [])


def test_letterhead_renders_a_multi_line_job_title_as_two_paragraphs():
    doc_xml = (
        "<w:tbl>"
        "<w:p><w:r><w:t>FULL NAME</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Job title: List each title individually...</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Contact: Please list your office desk phone number...</w:t></w:r></w:p>"
        "</w:tbl>"
    )
    items_by_section = {
        "full_name": [{"fields": {"value": "Dr Camilla Hadi Chaudhary"}}],
        "job_title": [{"fields": {"value": "Senior Lecturer\nHead of Centre for Academic Success"}}],
        "contact_info": [{"fields": {"value": "+971 4 000 0000"}}],
    }
    result = template_engine._populate_letterhead(doc_xml, items_by_section)
    assert "Job title: Senior Lecturer" in result
    assert "Head of Centre for Academic Success" in result
    # The second title must be its own paragraph, not glued onto the first.
    assert "Senior LecturerHead of" not in result
    assert result.count("<w:p>") == 4  # name, 2 title lines, contact
    assert "Contact: +971 4 000 0000" in result


def test_full_pipeline_splits_dual_title_letterhead_line():
    cv_text = (
        "Dr Camilla Hadi Chaudhary\n"
        "Job title: Senior Lecturer, International and Comparative Education, "
        "and Head of Centre for Academic Success, Middlesex University, "
        "Dubai Campus | 2026 onwards\n"
        "camilla.chaudhary@mdx.ac.ae\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    title_items = [it for it in items if it["section"] == "job_title"]
    assert len(title_items) == 1
    value = title_items[0]["fields"]["value"]
    assert "\n" in value
    assert value.startswith("Senior Lecturer")
    assert "Head of Centre for Academic Success" in value
    assert "Middlesex" not in value
    assert "Campus" not in value


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
