"""Regression tests for real defects found deep-auditing a second real CV
(2026-09-03) -- a non-templated, professionally laid-out CV (John Siko's),
chosen specifically because its headings and layout convention differ
completely from the MDX template, stress-testing generic classification
rather than a CV already close to the template's own structure.

Four distinct bugs:

  1. identifiers.find_identifiers took the FIRST match for a platform,
     regardless of how good it was. A CV that spells its LinkedIn out
     twice -- once as visible text broken by a line-wrap ("linkedin.com/in/j
     ohn-siko-82a30921/", a stray space mid-username) and once as the
     intact address behind the actual hyperlink (see extraction.py's
     _hyperlink_targets) -- had the broken version win every time, purely
     because it happened to read first, discarding the real profile URL
     for a single truncated character.
  2. A two-column CV's sidebar (Languages, in this case) interleaves with
     the main column's Experience text in reading order: a genuine language
     entry ("French (B2, working proficiency)") sits directly beside the
     START of an unrelated job entry from the other column, with no bullet
     and no full stop between them. Grouping welded them into one
     unreadable item, and everything from that job entry onward kept
     accumulating under language_proficiency for several MORE entries
     until something else broke the streak by luck.
  3. A "CITIZENSHIP" side-heading -- not a heading the MDX template
     recognises at all, and with nowhere in the template it could
     correctly go -- silently became content of whatever Employment entry
     happened to precede it, reading as a bizarre non-sequitur inside a
     real job entry's text.
  4. A "SELECTED MEDIA" sub-heading, followed by a plain list of outlet
     names the person was interviewed by (not his own work), silently
     became Publications -- indistinguishable in the output from his
     actual peer-reviewed articles and books.

Run directly: python test_siko_language_and_identifiers.py
"""
import identifiers
import rule_classifier as rc


# --- Bug 1: first-match-wins picked a line-wrap-broken URL over the real one

def test_identifiers_prefers_the_intact_url_over_a_line_wrap_broken_one():
    text = (
        "https://www.linkedin.com/in/j ohn-siko-82a30921/\n"
        "EXPERIENCE\n"
        "https://www.linkedin.com/in/j: https://www.linkedin.com/in/john-siko-82a30921/\n"
    )
    found = identifiers.find_identifiers(text)
    linkedin = [f for f in found if f["platform"] == "LinkedIn"]
    assert len(linkedin) == 1
    assert linkedin[0]["url"] == "https://www.linkedin.com/in/john-siko-82a30921"


def test_identifiers_finds_the_correct_match_even_on_the_same_line_as_the_broken_one():
    # The broken (label) and intact (target) occurrences can sit on the
    # SAME line -- a synthetic hyperlink-target line always writes
    # "label: target" -- so a plain per-line .search() that stops at the
    # first hit within a line is not enough; every occurrence on every
    # line must be considered.
    text = "https://www.linkedin.com/in/j: https://www.linkedin.com/in/john-siko-82a30921/\n"
    found = identifiers.find_identifiers(text)
    assert found[0]["url"] == "https://www.linkedin.com/in/john-siko-82a30921"


# --- Bug 2: a language entry welded onto an unrelated interleaved job entry

def test_language_entry_does_not_absorb_a_following_unrelated_job_entry():
    body_lines = [
        "English (native)",
        "French (B2, working proficiency)",
        "Risk Advisory Group, London and Dubai - Deputy Head of Research and Innovation, Government Services Practice",
        "July 2018-January 2020",
    ]
    grouped = rc._group_into_items(body_lines, section_key="language_proficiency")
    assert "English (native)" in grouped
    assert "French (B2, working proficiency)" in grouped
    assert not any("Risk Advisory Group" in g and "French" in g for g in grouped)
    assert any(g.startswith("Risk Advisory Group") for g in grouped)


def test_short_labelled_entry_allows_a_cefr_style_level_with_a_digit():
    # This is the specific shape that broke: a proficiency level commonly
    # carries a CEFR code ("B2") right beside the descriptor. The bare
    # digit guard this used to have was strictly broader than needed --
    # it rejected this real, common shape along with the date ranges it
    # was actually meant to guard against.
    assert rc._is_short_labelled_entry("French (B2, working proficiency)")
    assert rc._is_short_labelled_entry("English (native)")
    assert rc._is_short_labelled_entry("German (C1)")


def test_short_labelled_entry_still_rejects_a_bare_date_range():
    # The parenthesis must still open on a letter -- a bare numeric date
    # range must never be mistaken for a proficiency level.
    assert not rc._is_short_labelled_entry("Some Role (2020-2022)")


def test_two_genuine_language_entries_still_split_apart():
    # Before this fix, "French (B2, ...)" following "English (native)"
    # welded together because the digit in "B2" disqualified it from ever
    # being recognised as a language entry at all.
    grouped = rc._group_into_items(
        ["English (native)", "French (B2, working proficiency)"],
        section_key="language_proficiency",
    )
    assert len(grouped) == 2


# --- Bug 3: a no-home personal-detail heading absorbed into Employment ---

def test_citizenship_heading_content_rerouted_to_unmapped():
    items = [
        {"section": "previous_employment", "fields": {}, "source_text": "Some real duty sentence.", "confidence": 0.7},
        {"section": "previous_employment", "fields": {}, "source_text": "CITIZENSHIP USA/France UAE Golden Visa holder", "confidence": 0.7},
        {"section": "previous_employment", "fields": {}, "source_text": "Managed a multinational team across the region.", "confidence": 0.7},
    ]
    result = rc._reroute_no_home_subheadings(items)
    assert result[0]["section"] == "previous_employment"
    assert result[1]["section"] == "unmapped"
    assert result[1]["fields"]["value"] == "CITIZENSHIP USA/France UAE Golden Visa holder"
    # A different section right after the marker must not be swept up too --
    # the reroute is scoped to the SAME section as the marker itself.
    assert result[2]["section"] == "previous_employment"


# --- Bug 4: a media-mentions list absorbed into Publications --------------

def test_selected_media_block_rerouted_but_selected_articles_left_alone():
    items = [
        {"section": "publications", "fields": {}, "confidence": 0.8, "source_text":
            'SELECTED ARTICLES "A Real Article Title", Some Journal (Somewhere), Volume 1, No. 2, 2020'},
        {"section": "publications", "fields": {}, "confidence": 0.8, "source_text":
            "SELECTED MEDIA Outlets for interviews and published articles include:"},
        {"section": "publications", "fields": {}, "confidence": 0.8, "source_text":
            "African Business Review The Cipher Brief (US) News24 (South Africa)"},
        {"section": "publications", "fields": {}, "confidence": 0.8, "source_text":
            "BBC World Service Voice of America"},
    ]
    result = rc._reroute_no_home_subheadings(items)
    # A genuine subgroup of Publications must never be touched.
    assert result[0]["section"] == "publications"
    # The whole media-mentions block, marker plus every following bare
    # outlet-name line, must move.
    assert result[1]["section"] == "unmapped"
    assert result[2]["section"] == "unmapped"
    assert result[3]["section"] == "unmapped"


def test_a_real_citation_after_a_media_block_is_not_swept_up():
    # A safety valve: if a media list is somehow followed by a real,
    # unheaded citation with no new section in between, the citation's own
    # shape (a quoted title, in this case) must stop the reroute.
    items = [
        {"section": "publications", "fields": {}, "confidence": 0.8, "source_text":
            "SELECTED MEDIA Outlets for interviews include:"},
        {"section": "publications", "fields": {}, "confidence": 0.8, "source_text":
            "African Business Review The Cipher Brief (US)"},
        {"section": "publications", "fields": {}, "confidence": 0.8, "source_text":
            '"A Later Real Article", Some Journal, Volume 3, No. 1, 2021'},
    ]
    result = rc._reroute_no_home_subheadings(items)
    assert result[0]["section"] == "unmapped"
    assert result[1]["section"] == "unmapped"
    assert result[2]["section"] == "publications"


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
