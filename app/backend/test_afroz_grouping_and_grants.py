"""Regression tests for real data-loss bugs found deep-auditing a genuine
staff CV already written in the MDX template itself, against its portal
conversion (2026-09-03). Eight distinct bug classes, all traced to
grouping/boundary detection in _group_into_items and field-parsing in
_structure_grants:

  1. An unbulleted, one-fact-per-line block (Awards) welded all 11 real
     entries into a single unreadable item -- the same class of bug already
     fixed for "skills", but never extended to "awards".
  2. The same shape, for Committees and Academic Leadership -- but these
     two sections also legitimately contain a short title-only line
     immediately followed by its own description, which a blanket fix
     would wrongly split apart.
  3. ENTRY_END_YEAR_RE (the boundary signal for "this entry's date column
     just ended") could never match a parenthesised date ("(2023 -
     present)") at all -- the trailing ")" was fatal to the pattern,
     silently disabling entry-splitting for every CV that parenthesises
     its dates. Fixing this alone recovered three real job-title lines
     that were previously dropped (only their duty text survived).
  4. The same regex also false-positived on an ordinary monetary amount
     ending "00" ("AED 15,000"), mistaking it for a 2-digit year and
     splitting an unrelated detail line into a bogus new entry.
  5. A CV that fills the MDX template's own explicit grant field labels
     ("Project Title:", "Role:", "Duration:", "Funding or External
     Agency:", "Value to the University:") had EVERY labelled line treated
     as its own new grant entry, with the label word itself stored as the
     entry's "role" and the real value mislabelled as "project_title" --
     turning 4 real funded projects into ~29 scrambled fragments.
  6. _extract_employment_fields' "before vs after the date" title/employer
     choice used a flat 60-character cutoff to decide which side was the
     "short, clean" real title -- too tight for a genuinely long but
     perfectly normal title/employer/location combination, which then lost
     to a run-on narrative description hundreds of characters long, storing
     that whole client list as the person's job title.
  7. identifiers.TRUNCATED_URL_RE treated ANY trailing "/" as evidence a
     URL was cut off mid-word by a PDF line-wrap -- but a perfectly
     complete root-domain URL ("https://www.pointacademy.com/") ends in a
     slash too, and that real, distinct profile link was silently dropped
     from the Professional Profiles, Links, and Identifiers section.
  8. A single Word paragraph with no <w:br/> anywhere inside it can weld a
     whole section (heading and all its entries) onto the tail of
     unrelated prose that came right before it in the source, with
     nothing but a space between them. "KEYNOTES, PANELS, JUDGING AND
     OTHER INVITED ROLES" -- not even one of the MDX template's own named
     sections -- was glued onto a press-coverage bullet this way and
     disappeared into it entirely.

Run directly: python test_afroz_grouping_and_grants.py
"""
import identifiers
import rule_classifier as rc


# --- Bug 1: unbulleted awards all welding into one item ----------------

def test_unbulleted_awards_each_become_their_own_item():
    body_lines = [
        "British National Teaching Fellowship Scheme (NTFS) Nomination from Middlesex University, United Kingdom (2024)",
        "MDX Innovation Award for Creative Collaboration, Middlesex University Dubai (2024)",
        "Awwwards Nominee – Digital / Experience Design (2022)",
        "100+ international awards and 200+ official selections across regional and international film festivals.",
    ]
    grouped = rc._group_into_items(body_lines, section_key="awards")
    assert len(grouped) == 4


# --- Bug 2: committees/academic leadership title+description safety ----

def test_committees_entries_separate_but_title_keeps_its_description():
    body_lines = [
        "Advisory Board Member, Digital and Interactive Media Production, Daytona State College, United States of America (2023 – present)",
        "Advisory Board Member, Visual Communication, American University in Dubai, United Arab Emirates (2016 – 2019) – curriculum relevance, industry alignment and partnership development",
        "MDX Wellness Centre – Contributor",
        "Contributor to staff wellbeing and engagement initiatives, supporting the curation, programming and facilitation of staff movie nights.",
    ]
    grouped = rc._group_into_items(body_lines, section_key="committees")
    assert len(grouped) == 3
    # The short title line must keep its own description attached, not be
    # split apart just because the description also opens uppercase.
    assert any(g.startswith("MDX Wellness Centre") and "Contributor to staff wellbeing" in g for g in grouped)


def test_academic_leadership_same_shape():
    body_lines = [
        "Head of MDX Studios (Film Programme), Middlesex University Dubai (2021 – present) – leads a professional production studio operating within an academic department.",
        "Founder and Head  point a.cademy, in strategic partnership with Middlesex University Dubai (2025 – present)",
        "Lead Evangelist (UAE) for Blackmagic Design certification and head of the Blackmagic Design brand partnership; secured Blackmagic Design Education Partner status.",
    ]
    grouped = rc._group_into_items(body_lines, section_key="academic_leadership")
    assert len(grouped) == 3


# --- Bug 3: parenthesised dates never closing an entry ------------------

def test_entry_end_year_re_matches_parenthesised_dates():
    assert rc.ENTRY_END_YEAR_RE.search("Some Role, Some Employer (2023 - present)")
    assert rc.ENTRY_END_YEAR_RE.search("Some Role, Some Employer (2018 – 2022)")


def test_previous_role_title_line_no_longer_dropped():
    body_lines = [
        "Founder and Chief Creative Officer, Not an Agency Inc., Dubai, United Arab Emirates (2018 – present, concurrent)",
        "Multidisciplinary creative studio and personal consultancy, creative direction and strategy for major clients.",
        "Creative Director and Growth Lead (Middle East), Cococart.co (Y Combinator S21), Remote/Global (2020 – 2021)",
        "Product, UX/UI, growth and campaign strategy for the UAE market during scale-up.",
    ]
    grouped = rc._group_into_items(body_lines, section_key="previous_employment")
    assert any(g.startswith("Founder and Chief Creative Officer") for g in grouped)
    assert any(g.startswith("Creative Director and Growth Lead") for g in grouped)


# --- Bug 4: monetary amount false-positiving as a year ------------------

def test_entry_end_year_re_does_not_match_money_ending_in_00():
    assert not rc.ENTRY_END_YEAR_RE.search("2017: 25-seat theatre, four-hour rental | AED 15,000")
    assert not rc.ENTRY_END_YEAR_RE.search("DaVinci Resolve Studio Licences: 60 licences – USD 399 | USD 23,940")


def test_entry_end_year_re_still_matches_genuine_short_years():
    assert rc.ENTRY_END_YEAR_RE.search("Some Role, Some Employer, 1999-02")
    assert rc.ENTRY_END_YEAR_RE.search("Some Role, Some Employer, 2011, 2012")


# --- Bug 5: MDX template's own grant field labels ------------------------

def test_grant_field_labels_produce_one_correctly_structured_entry():
    body_items = [
        "Project Title: Roxy Cinemas – MDX Studios – Exclusive Theatrical Premiere and Sponsorship Partnership",
        "Role: Festival Director/Producer and Partnership Lead; negotiated and secured on behalf of Middlesex University Dubai",
        "Duration: 2017–Present | Annual partnership; 2026 edition confirmed",
        "Funding or External Agency: Roxy Cinemas (Emaar Entertainment), United Arab Emirates | In-kind sponsorship",
        "Value to the University: AED 585,000+ cumulative in-kind sponsorship and exposure (2017–2026)",
    ]
    grants = rc._structure_grants(body_items)
    assert len(grants) == 1
    fields = grants[0]["fields"]
    assert fields["role"] == "Festival Director/Producer and Partnership Lead; negotiated and secured on behalf of Middlesex University Dubai"
    assert fields["project_title"].startswith("Roxy Cinemas")
    assert fields["duration"].startswith("2017")
    assert fields["funding_agency"].startswith("Roxy Cinemas (Emaar")
    assert fields["value_to_university"].startswith("AED 585,000")
    # The label word itself must never end up as a field's VALUE -- the
    # original bug stored "Role" as fields["role"] instead of the real text.
    for value in fields.values():
        assert value not in ("Project Title", "Role", "Duration", "Funding or External Agency", "Value to the University")


def test_multiple_grant_entries_stay_separate():
    body_items = [
        "Project Title: First Project",
        "Role: Producer",
        "Project Title: Second Project",
        "Role: Director",
    ]
    grants = rc._structure_grants(body_items)
    assert len(grants) == 2
    assert grants[0]["fields"]["project_title"] == "First Project"
    assert grants[0]["fields"]["role"] == "Producer"
    assert grants[1]["fields"]["project_title"] == "Second Project"
    assert grants[1]["fields"]["role"] == "Director"


def test_legacy_consultant_style_grant_still_works():
    # The pre-existing convention this function was originally built for
    # must keep working: a role-as-label header, not a named-field label.
    body_items = [
        'Consultant: "Teaching at the Right Level (TaRL)"',
        "Co-PI with Prof X and Dr Y (Funded by FCDO/DARE-RC, 2025-26)",
    ]
    grants = rc._structure_grants(body_items)
    assert len(grants) == 1
    fields = grants[0]["fields"]
    assert fields["role"] == "Consultant"
    assert "Teaching at the Right Level" in fields["project_title"]
    assert fields["funding_agency"] == "FCDO/DARE-RC"


# --- Bug 6: long-but-clean title/employer losing to run-on narrative ---

def test_long_clean_title_beats_a_run_on_narrative_description():
    text = (
        "Founder and Chief Creative Officer, Not an Agency Inc., Dubai, United Arab Emirates "
        "(2018 – present, concurrent) Multidisciplinary creative studio and personal consultancy, "
        "creative direction and strategy for Hewlett-Packard, Microsoft, Apple, Warner Bros, "
        "Universal Music Group, Sony, Emirates Airlines, Mercedes-AMG, Dubai Tourism, Majid Al "
        "Futtaim, Atlantis, Burj Al Arab, Roxy Cinemas, VOX Cinemas, Sephora, Dior, Armani, Fenty "
        "Beauty, Mashreq Bank, RTA Dubai, Maserati, Uber, Careem, Lindt, IKEA, F1 Abu Dhabi and Spotify"
    )
    fields = rc._extract_employment_fields(text, "employer")
    assert fields["title"].startswith("Founder and Chief Creative Officer")
    assert "Hewlett-Packard" not in fields["title"]
    assert "Hewlett-Packard" not in fields.get("employer", "")


def test_short_title_still_wins_over_a_real_narrative_after_side():
    # The original case this heuristic was built for must still work.
    text = (
        "Jan 2013 - Present, New York, New York Deutsche Bank is a German global banking and "
        "financial services company. As a Sr Business Analyst, my core activities include: "
        "requirements gathering, stakeholder management, and process design."
    )
    fields = rc._extract_employment_fields(text, "employer")
    assert "New York" in fields.get("title", "") or "New York" in fields.get("employer", "")


# --- Bug 7: a complete root-domain URL wrongly treated as truncated -----

def test_trailing_slash_url_is_not_treated_as_truncated():
    text = (
        "PROFESSIONAL PROFILES, LINKS, AND IDENTIFIERS\n"
        "Website: https://www.afroz.xyz\n"
        "point a.cademy: https://www.pointacademy.com/\n"
    )
    found = identifiers.find_identifiers(text)
    urls = {item["url"] for item in found}
    assert "https://www.pointacademy.com/" in urls


def test_genuinely_hyphen_truncated_url_still_rejected():
    assert identifiers.TRUNCATED_URL_RE.search("https://www.example.com/some-page-")
    assert identifiers.TRUNCATED_URL_RE.search("https://www.example.com/some_page_")
    assert not identifiers.TRUNCATED_URL_RE.search("https://www.example.com/")


# --- Bug 8: a whole section glued onto unrelated prose with no break ----

def test_embedded_heading_run_is_split_from_preceding_prose():
    line = (
        "Middlesex University Dubai (2019) - MDX Dubai awarded Best Media Centre "
        "by Forbes Middle East KEYNOTES, PANELS, JUDGING AND OTHER INVITED ROLES "
        "CABSAT - World Content & Satellite Leaders Panel | Panelist | 2018 | Dubai, UAE"
    )
    pieces = rc._split_embedded_heading_runs([line])
    assert len(pieces) == 2
    assert pieces[0].endswith("Forbes Middle East")
    assert pieces[1].startswith("KEYNOTES, PANELS, JUDGING AND OTHER INVITED ROLES")


def test_split_off_heading_run_stays_its_own_item_not_rewelded():
    body_lines = rc._split_embedded_heading_runs([
        "Media coverage and features: Khaleej Times (2025) - a piece about the "
        "programme. Middlesex University Dubai (2019) - MDX Dubai awarded Best "
        "Media Centre by Forbes Middle East KEYNOTES, PANELS, JUDGING AND OTHER "
        "INVITED ROLES CABSAT - World Content & Satellite Leaders Panel | "
        "Panelist | 2018 | Dubai, UAE"
    ])
    grouped = rc._group_into_items(body_lines, section_key="knowledge_exchange")
    assert len(grouped) == 2
    assert any(g.startswith("KEYNOTES, PANELS") for g in grouped)
    assert not any("Forbes Middle East KEYNOTES" in g for g in grouped)


def test_ordinary_three_word_acronym_run_inside_a_normal_sentence_is_left_alone():
    # Guard against over-firing: a short run of capitalised acronyms that is
    # ordinary CV content (not a glued-on heading) must not be split apart.
    line = "Certified in AWS EC2 S3 deployment and cloud infrastructure management."
    pieces = rc._split_embedded_heading_runs([line])
    assert len(pieces) == 1


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
