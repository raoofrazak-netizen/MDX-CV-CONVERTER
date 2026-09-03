"""Regression test for a job-title selection bug reported live by the user
against the Afroz Nawaf CV (2026-09-03): the letterhead stated FOUR
distinct titles directly under the person's name (a real, deliberate
multi-role presentation -- "Lecturer in Film, Digital Media and PG
Programmes" / "Head of MDX Studios (Film Programme)" / "Senior Fellow of
the Higher Education Academy (SFHEA)" / "Founder, point a.cademy") but the
generated document's job title showed "Founder, point a.cademy, Dubai" --
the LAST of the four, and an unrelated side venture rather than his
primary academic post.

Root cause: _promote_present_role always overrode whatever
_extract_letterhead found with the title from the CV's Present Employment
section -- taking simply the FIRST entry there, which for a person with
several genuinely concurrent "present" roles is an arbitrary pick, not a
more-authoritative one. The override exists for a real, different reason
(a single, more detailed current-role entry usually beats a vague
letterhead line for the SAME job -- see
test_full_pipeline_does_not_misfile_job_title_as_a_duty_sentence in
test_title_keyword_and_date_bugs.py, which this fix must not break), so
the fix is scoped narrowly: only defer to an already-found letterhead
title when there is genuine ambiguity -- more than one present_employment
entry.

Run directly: python test_multi_role_letterhead_title.py
"""
import rule_classifier as rc


def test_letterhead_title_wins_when_multiple_concurrent_roles_exist():
    cv_text = (
        "AFROZ NAWAF\n"
        "Lecturer in Film, Digital Media and PG Programmes\n"
        "Head of MDX Studios (Film Programme),\n"
        "Middlesex University Dubai\n"
        "Senior Fellow of the Higher Education Academy (SFHEA)\n"
        "Founder, point a.cademy, Middlesex University Dubai\n"
        "Contact: +971 58 5928347\n"
        "Email: a.nawaf@mdx.ac.ae\n"
        "CAREER DETAILS – PRESENT EMPLOYMENT\n"
        "Founder, point a.cademy, Dubai, United Arab Emirates (2025 – present)\n"
        "Head of MDX Studios (Film Programme), Middlesex University Dubai, "
        "United Arab Emirates (2021 – present)\n"
        "Lecturer in Film, Digital Media and Postgraduate Programmes, "
        "Middlesex University Dubai, United Arab Emirates (2021 – present)\n"
    )
    items = rc.classify_rule_based(cv_text, "cv.docx")
    title_items = [it for it in items if it["section"] == "job_title"]
    assert len(title_items) == 1
    assert title_items[0]["fields"]["value"] == "Lecturer in Film, Digital Media and PG Programmes"


def test_employment_derived_title_still_wins_with_only_one_present_role():
    # The behaviour this fix must NOT break: a single current-role entry's
    # own, more detailed title still beats a vaguer letterhead line for
    # what is clearly the SAME job.
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
