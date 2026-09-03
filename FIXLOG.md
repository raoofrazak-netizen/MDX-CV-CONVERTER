# Fix Log

A record of defects found in the converter, what actually caused each one, and
what changed. Kept separate from `HANDOVER.md` so the handover stays a
description of the system as it stands, and this stays the history.

Every entry here has a matching assertion in `app/backend/test_corpus.py`
wherever the bug class could recur. Run that suite after any change:

```bash
cd app/backend && python test_corpus.py
```

---

## 2026-09-03 (fifth pass) — A job-title selection bug found live-testing the Afroz Nawaf CV again, after re-uploading following the fourth audit's fixes

Reported live, with a screenshot of the source letterhead: the generated document's job title showed "Founder, point a.cademy, Dubai" -- an unrelated side venture, and the LAST of four distinct titles the CV states directly under the person's name ("Lecturer in Film, Digital Media and PG Programmes" / "Head of MDX Studios (Film Programme)" / "Senior Fellow of the Higher Education Academy (SFHEA)" / "Founder, point a.cademy"). Regression test in `app/backend/test_multi_role_letterhead_title.py`. Suite: 54/59 throughout. Live-tested via the real running portal.

| Defect | Cause | Fix |
|---|---|---|
| The letterhead job title showed an unrelated side venture instead of the person's primary, first-stated academic title | `_promote_present_role` always overrides whatever `_extract_letterhead` found with the title from the CV's Present Employment section -- taking simply the FIRST entry there. For a person with several genuinely concurrent "present" roles (three, here, all marked ongoing), no one of them is more "current" than the others, so that pick is arbitrary -- and it silently overrode a real, deliberately-stated multi-title letterhead with whichever one happened to be listed first in the Employment section | The override is now scoped to genuine ambiguity: it still always wins with exactly one present-employment entry (a single, more detailed current-role title correctly beats a vaguer letterhead line for what is clearly the same job -- the original reason this override exists, and a case this fix is careful not to break), but with more than one concurrent role, an already-found letterhead title is trusted instead of being overwritten by an arbitrary pick |
| A letterhead title carrying its own trailing date column ("Senior Lecturer... \| 2026 onwards") defeated the institution/campus-stripping check, leaving "Middlesex University, Dubai Campus \| 2026 onwards" stuck on the end of a split dual-title job value | Exposed by the fix above: `_clean_job_titles` never stripped a trailing "\| date" tail before running `TRAILING_INSTITUTION_RE`, which anchors on end-of-string -- previously masked because the old unconditional override routed this text through a DIFFERENT function that happened to strip it first | `_clean_job_titles` now strips a trailing pipe-delimited tail up front, the same way `_role_text_before_dates` already does elsewhere |

## 2026-09-03 (fourth audit) — A fourth real CV, reported directly by the user with screenshots from a live conversion: a whole new "Title (Date) Employer" convention corrupting every employment entry, plus two smaller gaps

Reported directly, with screenshots: every employment entry showed the employer's name as the job title, a qualification was missing its subject, and the letterhead job title was wrong as a result. Traced to a date convention neither of the first three audits' source CVs used -- the date wrapped in its own parentheses, sitting BETWEEN the title and the employer rather than after both or in a separate field. Regression tests in `app/backend/test_aatif_paren_dates_and_subjects.py`. Suite: 54/59 throughout. Live-tested via the real running portal against the actual CV.

| Defect | Cause | Fix |
|---|---|---|
| Every employment entry showed the employer's name as the job title ("Middlesex University Dubai" for all six roles), discarding the real titles ("Adjunct Faculty", "Consultant Software Developer", ...) entirely -- and since the letterhead's job title is promoted from the most recent entry's own parsed title, it was wrong too | `_extract_employment_fields`'s before/after split assumes ONE side of the date holds a comma-joined "Title, Employer" pair. This CV's convention -- "Title (Date Range) Employer" -- splits across the date itself, so neither side has a comma at all; the employer text on the "after" side (short, clean, no comma) looked exactly like the short role text the heuristic prefers | A new, narrowly-scoped check recognises this specific shape -- the date literally wrapped in "(" ")" in the source, with a single clean comma-free phrase on both sides -- and reads title from "before" and employer from "after" directly, bypassing the general (wrong-for-this-shape) comma-split logic entirely |
| Two consecutive roles welded into one item: "Student Learning Assistant..." absorbed "Digital Forensics Trainee..." whole, including ITS employer, as if they were one entry | `_is_title_with_date_line` (the check that recognises a bare title-with-its-own-date line as always starting a new entry) requires the title to contain a known keyword from `TITLE_KEYWORDS` -- and "trainee" was missing from that list, so "Digital Forensics Trainee" read as more of the previous entry's trailing text instead of a new one | Added "trainee" to `TITLE_KEYWORDS` |
| "BSc (Hons.) Information Technology" lost its subject entirely -- structured fields showed only degree, institution and year | `_is_plausible_subject` correctly rejects text with an unmatched bracket, as a mis-parse guard -- but the degree-classification parenthetical right after the degree name ("(Hons.)") was only ever trimmed from the OUTER edges of the extracted subject text, leaving the closing ")" stranded in the MIDDLE once the leading "(" was gone ("Hons.) Information Technology"), tripping that same guard and discarding a real, correctly-shaped subject | The classification parenthetical is now stripped as a whole unit immediately after the degree name, before the general edge-trim runs, so nothing is left dangling |

## 2026-09-03 (third audit) — A third real CV, chosen for a clean pipe-delimited employment convention: a field-splitting bug, a heading-coverage gap, and a typo-tolerance gap in the authoritative-heading check

Requested explicitly, source and reference both supplied: "check whats missing and fix the translation issue, conversion issue, classification issue, information missing issue." Found four distinct defects, none overlapping the first two audits' bug classes -- this CV's clean "Title, Employer | Date - Date | City, Country" convention and its own heading wording stress-tested different code paths. Regression tests in `app/backend/test_mukarram_fields_and_headings.py`. Suite: 54/59 throughout. Live-tested via the real running portal.

| Defect | Cause | Fix |
|---|---|---|
| A bare, un-bulleted entry with no duties of its own ("Intern, Schindler Group \| Jan 2018 - Jul 2018 \| Dubai, UAE") had "Dubai"/"UAE" stored as its title/employer, discarding the real ones | `_extract_employment_fields`'s before/after split assumes a TWO-part structure (date on one side, role on the other) -- but this convention has a THIRD pipe-delimited field for location. Once the date was removed, the short, non-narrative "Dubai, UAE" on the "after" side looked exactly like the short, clean role text the heuristic was built to prefer | A bare-location check (`BARE_CITY_COUNTRY_RE`, already used elsewhere for the same shape) now excludes a location-only "after" side from ever being chosen as the role, regardless of how short or clean it looks -- the real title/employer on the "before" side wins instead |
| "Select Academic Projects, Papers and Conference Outputs" -- a publications heading by any reasonable reading -- resolved to Grants instead, and 4 of 6 real conference papers were silently lost to Unmapped | "PROJECTS" (a grants synonym) was the longest single-word match found anywhere in the heading; the existing "CONFERENCE PAPERS" synonym needs its two words adjacent, and this heading reads them reversed with "AND" in between ("PAPERS AND CONFERENCE"). `_structure_grants`, built for a "Role: X" funding convention, could make sense of only 2 of the 6 entries once misfiled there | Added "CONFERENCE OUTPUTS", "ACADEMIC PROJECTS", and the exact full heading as publications synonyms -- the longest matching phrase now correctly comes from the publications list, and ordinary sentence-boundary grouping (not the funding-specific grants parser) correctly produces one clean item per paper |
| A CV that spelled "External" correctly in "Internal and External Academic Leadership" (almost every CV does) had that section's content re-routed elsewhere by content keywords -- "Module Leader, ..." moved to Teaching and Learning purely because it contains the word "Module" | The MDX template's own official heading text has a baked-in typo, "...EXERNAL...". `_find_heading_key` already tolerates typos via fuzzy matching and filed the section correctly -- but `is_authoritative_heading`, which tells routing.py "the CV explicitly named this section, never re-file its content by wording", checked ONLY exact official text. A correctly-spelled heading failed that exact check, so routing.py treated the section as unstated and re-routed it by content anyway | `is_authoritative_heading` now also accepts a fuzzy typo-tolerant match against the official heading phrases specifically (not synonyms, which are a looser "probably means this" signal) -- via new `_fuzzy_official_heading_key` |
| "ORCID Identifier: 0009-0009-7006-3510" was not recognised as an ORCID at all -- empty fields, filed as a bare, unstructured profile line | `BARE_ORCID_RE`'s allowance for the label between "ORCID" and the digits was capped at 12 characters; "ORCID Identifier: " (space + "Identifier:" + space) is 13, one character past the cap | Widened the gap allowance to 24 characters, comfortably covering this and similarly-phrased labels ("ORCID iD:", "ORCID No.:") |

## 2026-09-03 (second audit) — A second real CV, deliberately not close to the MDX template: a URL-priority bug and a two-column scramble welding Languages onto Experience

Requested explicitly, as a follow-up to the Afroz audit: "do a full audit
on another real CV." Chosen specifically for contrast with Afroz's CV
(which was already written directly in the MDX template, close to its own
structure) -- this one uses its own headings and a two-column layout with
no relationship to the template at all, stress-testing generic
classification rather than a near-template document. Two distinct bugs
found and fixed. Regression tests in
`app/backend/test_siko_language_and_identifiers.py`. Suite: 54/59 passing
throughout (5 pre-existing, unrelated failures). Live-tested via the real
running portal against the actual CV.

| Defect | Cause | Fix |
|---|---|---|
| The CV's real LinkedIn URL was replaced by a single truncated character (`https://www.linkedin.com/in/j`) | `identifiers.find_identifiers` took the FIRST match for a platform found while scanning line by line, with no way to prefer a better one found later. This CV's LinkedIn is written twice -- once as visible text broken by a line-wrap ("linkedin.com/in/**j ohn**-siko-..."), once as the intact address behind the actual Word hyperlink (see extraction.py's `_hyperlink_targets`) -- and the broken version, appearing first, always won. A second, compounding gap: the two occurrences can sit on the SAME synthesized line ("label: target"), and `.search()` only ever inspects the FIRST occurrence within a line, never reaching the correct one right next to it | Collects every candidate match for a platform across every line (via `.finditer()`, not `.search()`), and keeps the one with the longest captured identifier -- a truncated match is, by construction, shorter than the real one, regardless of which occurrence happened to come first |
| A real language entry ("French (B2, working proficiency)") welded onto the start of an entirely unrelated job entry from a different part of the CV, and everything from that job entry onward kept accumulating under Language Proficiency for several more entries | A two-column layout's sidebar (Languages) interleaves with the main column's Experience text once linearised, with no bullet and no full stop between them for any existing boundary check to catch. A stricter, related bug: the existing "real language entry" shape check (`SHORT_LABELLED_ENTRY_RE`) rejected ANY line containing a digit at all, which also blocked it from ever recognising "French (B2, ...)" as a genuine language entry in the first place, since a CEFR level like "B2" is an ordinary part of how a language section states its own proficiency | `SHORT_LABELLED_ENTRY_RE`'s parenthetical form now allows a digit or comma inside the parentheses, but still requires the parenthesis to OPEN on a letter -- so a real "(B2, working proficiency)" now matches while a bare "(2020-2022)" date range still doesn't. A new asymmetric boundary rule in `_group_into_items`, scoped to `language_proficiency`: once the line above already looks like a genuine, complete language entry, anything that does NOT ALSO look like one is never a continuation of it and always starts a new item -- stopping the run-on weld without needing to know what the unrelated content actually is |

One finding from the same audit was left as a documented, lower-severity limitation rather than fixed: the split-off job-entry items land under `language_proficiency`/`committees` instead of Previous Employment (no data is lost or merged -- each is now a complete, readable item HR can re-file with one click, but auto-routing them correctly would need a broad content-based reclassifier, and this codebase has already tried and rejected that class of general heuristic three times for misclassifying unrelated CVs elsewhere in the corpus -- see `_reclassify_resume_crosstalk`'s docstring).

## 2026-09-03 (third pass) — The CITIZENSHIP and SELECTED MEDIA findings from the second audit, chased on request

Two content-shaped defects from the second audit, left undone above because a broad "reclassify by content" heuristic was too risky: a "CITIZENSHIP" side-heading (not a section the MDX template has at all) was absorbed as content into whatever Previous Employment entry preceded it, and a "SELECTED MEDIA" sub-heading's list of outlet names (interviews and press mentions, not the person's own work) was absorbed into Publications, indistinguishable from his real peer-reviewed articles. Regression tests added to `app/backend/test_siko_language_and_identifiers.py`. Suite: 54/59 throughout. Live-tested via the real running portal.

| Defect | Cause | Fix |
|---|---|---|
| "CITIZENSHIP USA/France UAE Golden Visa holder" read as a bizarre non-sequitur glued into a real Employment entry | "CITIZENSHIP" is not a heading the MDX template recognises, and it names content the template has no section for at all -- but nothing forces a boundary or reroutes it just because it's unrecognised, so it silently became content of whatever section was open | New `_reroute_no_home_subheadings`, checking a small, CLOSED, exact-match vocabulary of personal-detail labels (`CITIZENSHIP`, `NATIONALITY`, `VISA STATUS`, `MARITAL STATUS`, `DATE OF BIRTH`, `PERSONAL DETAILS`, `GENDER`) with no home in the template. A match reroutes just that one item to Unmapped -- surfaced to HR during review (and counted in the quality report's `unmapped_count`), correctly absent from the final document since the template has no slot for it, rather than confidently mislabelled as something it isn't |
| A list of media outlets the person was interviewed by ("African Business Review", "BBC World Service", ...) appeared under Publications, indistinguishable from his actual books and journal articles | Same root cause as CITIZENSHIP -- "SELECTED MEDIA" is unrecognised and forces no boundary -- but this block spans SEVERAL following items with no marker of their own, unlike a single-fact label | A second, separate vocabulary (`SELECTED MEDIA`, `MEDIA COVERAGE`, `MEDIA APPEARANCES`, `MEDIA MENTIONS`, `PRESS COVERAGE`, `PRESS MENTIONS`, `IN THE MEDIA`) that instead carries the reroute FORWARD through subsequent items in the same section, stopping at a section change or at content that looks like a genuine citation (a quoted title, a "Volume" marker, or a trailing year -- `_CITATION_SHAPED_RE`), so a real, unheaded publication sitting right after a media block is never swept up by mistake. Deliberately a closed, exact-match list rather than a general "unrecognised heading" detector: "SELECTED ARTICLES" is unrecognised by the exact same test but is a genuine, wanted Publications subgroup (see `SUBGROUPED_SECTIONS`) and is correctly left untouched |

## 2026-09-03 (fourth pass) — Two regressions and one further data-loss bug found live-testing the third pass against the real Afroz CV

The user ran their own live test of the actual portal and reported a discrepancy against the reference CV. Investigating it surfaced that the SELECTED MEDIA fix above (third pass) had itself just broken a DIFFERENT, unrelated fix from the first pass -- the entire "KEYNOTES, PANELS, JUDGING AND OTHER INVITED ROLES" section vanished from the generated document a second time, for a new reason. A further, separate data-loss bug was found in the same pass. Regression tests added to `app/backend/test_afroz_grouping_and_grants.py`. Suite: 54/59 throughout. Live-tested via the real running portal against the actual CV.

| Defect | Cause | Fix |
|---|---|---|
| The Keynotes/Panels section disappeared from the generated document again, immediately after the third pass had just fixed it | `NO_HOME_BLOCK_RE` (built for Siko's ALL-CAPS "SELECTED MEDIA" label) was matched against `_normalize_heading`'s UPPERCASED form of the text -- so "Media coverage and features: Khaleej Times (2025)...", an ordinary Title-Case sentence opening a real Knowledge Exchange bullet, matched "MEDIA COVERAGE" just as readily as a genuine ALL-CAPS heading would. Being a BLOCK-type marker, it then carried the reroute FORWARD into the very next item in the same section -- the real Keynotes/Panels content -- deleting both | Matched against the CV's own actual casing instead (whitespace-collapsed but not case-folded), rather than a normalized-to-uppercase form -- a genuine sub-heading label is written in the CV's own heading style (ALL CAPS); ordinary sentence-case prose that happens to share the same words no longer qualifies |
| Two of the person's most substantive career achievements -- "...company raised USD 4.2M seed led by Forerunner Ventures and Sequoia Capital" and "...portfolio exceeding USD 200M in combined enterprise value..." -- never appeared anywhere in the generated document, even though the title/employer/dates parsed from the same two entries were completely correct | `_extract_employment_fields`'s "before vs after the date" heuristic (fixed in the first pass to prefer a short, clean title over a long narrative on the other side of the date) correctly picked the short side as the title -- but then simply discarded the long narrative side rather than keeping it anywhere. The fields were right; the sentence describing what the person actually DID in that role was thrown away | The discarded narrative is now reattached as a second line via the same `_line_override` mechanism `_reclassify_resume_crosstalk` already uses for an identically-shaped case -- the parsed header stays exactly as correct as before, with the real achievement sentence preserved beneath it instead of silently dropped |

## 2026-09-03 (fifth pass) — A dangling ", concurrent)" qualifier, found live-testing the fourth pass's own fix

The user's next live test surfaced a fresh artifact introduced by the fourth pass's discarded-narrative fix itself: two entries now showed a real sentence, but prefixed with a broken, dangling `concurrent)` fragment. Regression test added to `app/backend/test_afroz_grouping_and_grants.py`. Suite: 54/59 throughout. Live-tested via the real running portal.

| Defect | Cause | Fix |
|---|---|---|
| "Founder, point a.cademy... (2025 - present)" followed by a second line reading "concurrent) Independent studio, academy and creative community..." -- a dangling, unmatched `)` at the very start, reading as though the real sentence had been cut off mid-word | The source states the date as `(2025 - present, concurrent)` -- a role held simultaneously with another -- but `YEAR_RANGE_RE`'s match ended right after "present", leaving `, concurrent)` as leftover text on the content side. The fourth pass's own new `_line_override` fix then dutifully preserved that leftover exactly as found, dangling closing paren and all | `YEAR_RANGE_RE` now consumes an optional trailing `, concurrent`/`, concurrently` as part of the date match itself, the same way it already consumes "present"/"onwards"/"to date" -- the qualifier is absorbed into the date column it belongs to, so the content after it starts cleanly at the real sentence with nothing dangling in front of it |

## 2026-09-03 — A genuine staff CV written directly in the MDX template: ten real data-loss defects found by deep-auditing source vs. converted output

Requested explicitly: a side-by-side audit of a real converted CV against
its source, checking for missing/corrupted data rather than waiting for it
to surface CV-by-CV. Found ten distinct bugs — six in grouping/boundary
detection and grants field-parsing, one in qualifications/skills routing,
one in profile-link recognition, one in how a heading glued mid-paragraph
onto unrelated content was (not) separated back out, and one where a
DOCX-only footer landed under the wrong section — none in extraction
itself, which read every byte of the source correctly. Regression tests in
`app/backend/test_afroz_grouping_and_grants.py`. Suite: 54/59 passing
throughout (5 pre-existing failures, confirmed via `git stash` to predate
this session's changes, unrelated to any of these fixes).

| Defect | Cause | Fix |
|---|---|---|
| All 11 Awards entries welded into one unreadable item | An unbulleted, one-fact-per-line block has no punctuation for sentence-boundary grouping to split on — the same class of bug already fixed for `skills`, never extended to `awards` | Extended the existing skills-only boundary rule to `awards` too; also broadened it from `isupper()` to "not lowercase" so an entry starting with a digit ("100+ international awards...") is caught as well |
| Committees and Academic Leadership each missing 2 of 3 real entries | Same shape as above, but these two sections also legitimately contain a short title-only line ("MDX Wellness Centre – Contributor") immediately followed by its own description — a blanket fix would wrongly split a title from its own description, since the description also opens uppercase | New rule scoped to these two sections specifically, gated on the accumulated text already being substantial (`len(current[-1]) > 50`) before treating an uppercase-starting line as a new entry — a short title-only line stays silent, letting it correctly absorb its own following description |
| Three previous-employment title lines silently dropped (only their duty text survived) | `ENTRY_END_YEAR_RE` (the "this entry's date column just ended" boundary signal) required end-of-string immediately after the year/marker — a trailing `)` from a parenthesised date ("(2023 - present)") was fatal to the match, silently disabling entry-splitting for every CV that parenthesises its dates | Added an optional trailing `\)?` to the pattern |
| An unrelated detail line ("2017: 25-seat theatre... \| AED 15,000") became its own bogus entry | The same regex fix above made it newly reachable — but it then false-positived on an ordinary amount ending "00", mistaking the last two digits for a 2-digit year | Added `(?<!\d)` before the year pattern, so a digit immediately before it disqualifies the match |
| Research Grants: 4 real funded projects turned into ~29 scrambled fragments, field labels and values swapped (`"Role: Project Title"` / `"Project Title: <actual role text>"`) | `_structure_grants` was built for a CV that writes a single combined header ("Consultant: <project title>") — it had no concept of a CV that instead labels every field explicitly, the way the blank MDX template itself prompts for them ("Project Title:", "Role:", "Duration:", "Funding or External Agency:", "Value to the University:"). Every one of those labelled lines was read as its own new grant, with the label word stored as `role` and the real value mislabelled `project_title` | New `GRANT_FIELD_LABEL_RE`, checked first and more specifically: recognises the five real field-label words, opens a new entry only on "Project Title:", and adds every other labelled line as a field on whichever entry is currently open. The older single-header convention still works unchanged for CVs that use it |
| A long-but-clean title/employer/location line ("Founder and Chief Creative Officer, Not an Agency Inc., Dubai, United Arab Emirates") lost to a 300+ character client-list description, which got stored as the person's job title | `_extract_employment_fields`'s "which side of the date is the real title" heuristic used a flat 60-character cutoff — too tight for a legitimately long but normal title/employer/location combination | Raised the cutoff to 100 and added an explicit check that the "before" side doesn't itself read as a sentence (`[.!?]\s+\S`), so the fix targets long-but-clean text specifically rather than just any long text |
| A bare certification ("Fusion VFX") wrongly filed under a phantom "Skills" section instead of staying in Qualifications alongside its siblings | The per-item qualifications classification check required a degree, institution, or year signal before keeping an item in `qualifications` — a short, bare certification-list entry has none of those, so it fell through to `skills`. A near-identical sibling ("Dolby Atmos Certification") only survived by coincidence, via an unrelated `routing.py` keyword rule that happened to trip on the literal word "Certification" | Added a standalone exception ahead of the degree/institution/year check: a short line (≤40 chars) that doesn't end in sentence punctuation stays in `qualifications` — the shape of a real bare list entry, distinct from the much longer genuine skills/trait sentences documented elsewhere in the same code |
| The second, real profile link ("point a.cademy: https://www.pointacademy.com/") was missing from Professional Profiles, Links, and Identifiers | `identifiers.TRUNCATED_URL_RE` treated ANY URL ending in `/`, `-`, or `_` as evidence of a PDF line-wrap truncation — but a root-domain URL normally, correctly ends in `/`; that was never truncation, and the check silently discarded a complete, valid link | Narrowed the pattern to `-`/`_` only — a genuine mid-word PDF-wrap truncation cuts on a hyphen or underscore, never cleanly at a slash |
| An entire "KEYNOTES, PANELS, JUDGING AND OTHER INVITED ROLES" section (heading and all six entries) disappeared, fused onto the tail of an unrelated press-coverage bullet that preceded it in the source, with the words "...Forbes Middle East KEYNOTES, PANELS..." running on with no separator at all | The whole block is one single Word paragraph in the source docx with no `<w:br/>` anywhere inside it (confirmed via the raw XML — 0 `<w:br>`, 0 `<w:tab>` elements), so extraction correctly handed the classifier one giant run-on line. `_group_into_items` then had no way to know a new item started partway through it | New `_split_embedded_heading_runs`, run as a preprocessing pass: splits a line wherever a run of 3+ consecutive ALL-CAPS words appears after ordinary lower-case prose (shape-based, since "Keynotes, Panels..." isn't even one of the MDX template's own named headings — the fix only needed to stop the fusion, not classify it). A matching `STARTS_WITH_HEADING_RUN_RE` boundary rule in `_group_into_items` keeps the split from being immediately undone by the section's own unbulleted-prose grouping |
| Five unrelated press-article links got filed as the person's own entries under "Professional Profiles, Links, and Identifiers" | A Word hyperlink whose visible text names the source but never spells out the URL ("MDX Studios 2025 Premiere Celebrates...") is emitted by extraction.py as a synthetic `"label: target"` line, and ALL such lines are appended at the very end of the document's text — after the real body, headers and footers. Whatever heading is physically LAST in the CV therefore silently inherits every hyperlink in the whole document as its own content, regardless of what the link actually points to | New `HYPERLINK_TARGET_LINE_RE` junks any line that is nothing but an optional label followed by a bare URL, removing it from ordinary heading-based body classification. `identifiers.find_identifiers`, which already scans the untouched original text with the correct position- and exclusion-aware logic, remains the sole path these links are found through — so the two real profile links are unaffected, only the position-accidental misfiling is removed |
| A page footer ("AFROZ NAWAF \| ACADEMIC CV — 1") showed up as an empty-fields item under Profiles, and the wrong-URLs fix above initially looked "already resolved" only because the wrong source file was tested against | Same root cause as the hyperlink-target bug, but with no fix possible by shape alone: `_find_running_headers` recognises page furniture by counting exact repeats (a PDF genuinely re-emits its header on every extracted page), but python-docx reads a DOCX section's header/footer XML exactly ONCE regardless of how many pages the document actually has — the repeat-count check can never fire, so the footer is indistinguishable from ordinary body text and lands under whatever heading is physically last | extraction.py now tags every header/footer-sourced line with a private-use Unicode marker (`HEADER_FOOTER_MARKER`) invisible to everything else. `classify_rule_based` strips the marker and folds those lines into the SAME `running_headers` set a repeated PDF header already uses — stripped from body classification, but still offered to `_extract_letterhead` so a genuine identifier sitting in a footer is not lost, only kept out of whatever section happens to sit last |

## 2026-09-02 — A psychology-department résumé with a scrambled two-column layout: seven code defects, plus one standing data-integrity issue

Live-tested against a real requested conversion. Suite: **36/38 passing**
throughout (the 2 failures are the same pre-existing, unrelated ones —
generic résumés, not faculty CVs; see 2026-08-29 entry). Note: the corpus
grew to 38 CVs because `test_corpus.py`'s `CORPUS_DIRS` needed updating —
the user had reorganised `Downloads`, not a code change.

| Defect | Cause | Fix |
|---|---|---|
| Job title stored as a job-DUTY sentence ("Present research findings at national and international conferences...") | `TITLE_KEYWORDS`' `kw in text.lower()` substring check false-positived: "intern" (meant for the title "Intern") matched inside "**intern**ational". A second, independent gap let it through: `_looks_like_job_title`'s sentence-punctuation guard only caught punctuation followed by MORE text, not a single sentence ending in one terminal period | New `_has_title_keyword()` uses word-boundary regex matching, replacing all 9 call sites that used the bare substring check; `_looks_like_job_title` now also rejects a trailing terminal period with nothing after it |
| `full_name` came up completely empty | A middle initial with a period ("Seada A. Kassie") broke `NAME_LINE_RE`'s token pattern entirely — it had no way to consume the period on "A.", so the whole line failed to match at all, not just at lower confidence | `_NAME_TOKEN` now allows an optional trailing period on any token |
| Impossible fabricated years: `"end_date": "2109"`, printed as `"Lecturer, in Psychology (2020 – 2109)"` | An ISO year-month date ("2020-09" = September 2020) is shape-identical to a genuine short year-range end ("1999-02" → "1999-2002"), and the SAME century-wraparound logic existed independently, twice, in two different places (`normalize_date_range` and `_extract_employment_fields`) — both misread "09" as an abbreviated end year and wrapped it a century forward | Both now guarded: a century-wraparound is only trusted when it lands within a few years of today; a resulting date decades in the future is rejected and left unexpanded (or blank) rather than fabricated |
| The same fabrication also reached `YEAR_RANGE_RE`/`_DATE_PART` (used to parse a date GLUED to a title on one line, not just a bare date line) | `_DATE_PART` didn't treat "2023-09" as one atomic date either — it split off "2023" and mistook the "-09" for the same short-year shape, which additionally stranded "Current" inside the job title text instead of being recognised as the open-ended end marker | `_DATE_PART` now allows an optional trailing "-MM" suffix as part of one date token, mirroring the exact fix already shipped for the "08/2020" slash-month convention |
| A bare `"2023-09 - Current"` date line (month-qualified start + open marker) wasn't recognised as a date-only line at all, and fell through to ordinary parsing, fabricating a fake entry titled `"Current"` | `DATE_ONLY_RE` required a plain 4-digit start year; a "-MM" suffix broke the match | `DATE_ONLY_RE` now allows the same optional "-MM" suffix on the start year |
| The CV's CURRENT role was filed under Previous Employment with no date shown at all, instead of Present Employment | A two-column layout put the date column ("2023-09 - Current") on its own line ahead of the title/employer column. The existing "fold a stray date back into the entry above it" logic only ever looked backward — a date stranded at the very start of a section (nothing above it yet) was silently dropped, discarding the only signal that marked the role as current | The final sweep in `_group_into_items` now holds a leading date-only line and attaches it FORWARD to the next real entry — but only when the date carries an open-ended marker (present/current/onwards). A bare closed year at the start (e.g. orphaned qualification-year debris) is still dropped as before; broadening this to bare years too was tried and reverted after it glued an unrelated `"2012"` onto unrelated content several lines later on a real CV in the regression corpus, discarded by the verbatim guard |
| **Standing data-integrity issue, not a code bug**: every CV with a "Summary" heading had its whole summary paragraph filed as `full_name` with empty fields, corrupting the letterhead | A custom heading mapping taught during this session's own earlier live-testing (2026-08-30) incorrectly pointed `"SUMMARY" → full_name` instead of `biography` — silently active in the database ever since, affecting every CV processed in between (6 found; most were stale corpus/test artifacts, but at least one, a live re-upload of this same CV, was freshly corrupted by it) | Deleted via `DELETE /api/heading-mappings/{id}` — the built-in synonym table already correctly resolves "Summary" → biography on its own; the custom mapping was redundant as well as wrong |

## 2026-08-30 — A decorative letter-spaced résumé: name detection, a cascading letterhead bug, and job-duty text under "Languages"

Found live-testing a real uploaded CV (a medical-admin résumé whose whole
layout letter-spaces every heading AND the person's own name for visual
effect, plus a scrambled two-column reading order). Suite: **33/35
passing** throughout (the 2 failures are pre-existing and unrelated — see
below). Regression tests for these three live in
`app/backend/test_letterhead_and_language_routing.py` rather than being
added to `test_corpus.py`'s real-file corpus: the triggering CV carries a
real person's name, email, and phone number, and reconstructing the same
structural shape with synthetic data avoids keeping that PII around
indefinitely as a permanent test fixture.

| Defect | Cause | Fix |
|---|---|---|
| A letter-spaced name ("D E V A P R A B H A A .") was never recognised as a name at all | Letter-spacing collapse only ever ran for known section headings (matched against an official/synonym vocabulary); nothing collapsed the name-plate line, and even collapsed, "DEVAPRABHAA" is a single run with no recoverable word boundaries, which the ordinary name-shape check (`NAME_LINE_RE`, requires >=2 words) can never pass | New `_collapse_letter_spaced_name()` (tolerant of a trailing decorative period the heading check correctly rejects) offers the collapsed form as an extra letterhead candidate; a new relaxed check `_looks_like_collapsed_name()` accepts a single all-caps run for candidates known to come from this path only, still guarded against resolving to a real heading |
| The entire letterhead (job title, contact, email — all three correctly extracted) still showed the template's own "Job title: List each title individually…" placeholder instructions | `_populate_letterhead()`'s replacement loop only advanced past the name line when a name was actually *found* — one missing field silently blocked three unrelated, already-correct ones from ever being written | The loop now always advances past the "FULL NAME" line; only whether the name text itself gets written stays conditional, matching how the other three fields already handle a missing value |
| Job-duty sentences from a scrambled two-column layout ("Coordinated and streamlined hospital services…", "Acted as a liaison between departments…") ended up filed under Language Proficiency, whose only real content should be the language list | Two compounding gaps: (1) `language_proficiency` wasn't in `routing.ROUTABLE_SOURCE_SECTIONS` at all, so meaning-based re-routing never even looked at its contents; (2) even after fixing that, a short unpunctuated language line ("English Malayalam") welded onto the very next sentence during item-grouping regardless of what that sentence said, since sentence-boundary grouping only splits on trailing punctuation | Added `language_proficiency` to `ROUTABLE_SOURCE_SECTIONS` and to the existing action-verb `SCOPED_RULES` entry (mirrors the identical fix already shipped for `skills`); added `acted` to `ACTION_VERB_RE`'s vocabulary; new `JOB_DUTY_SENTENCE_RE` shape check forces an item boundary in `_group_into_items` when the *next* line is itself a full duty-style sentence, regardless of whether the previous line ended in punctuation |

Found immediately after, on a different real CV (an academic with two simultaneous posts) — same live-test session, same date:

| Defect | Cause | Fix |
|---|---|---|
| Job title stored and printed as one garbled line: `"Senior Lecturer, International and Comparative Education, and Head of Centre for Academic Success, Middlesex University, Dubai Campus"` | The source CV genuinely lists two real posts on one physical line, joined by "and" — nothing recognised this as two separate titles needing the template's own documented format ("List each title individually... Administrative titles should follow the format 'Title, Centre or Institute Name.'") | New `ADMIN_TITLE_CONNECTOR_RE`: a narrow, curated list of real leadership-title keywords (Head/Director/Dean/Chair/Provost/…) following "and" — deliberately not a bare `\band\b` split, which would also break an ordinary department name like "International and Comparative Education" in half. `_clean_job_titles()` splits the value at that boundary into two lines (joined by `\n`), flagged `multi_title_split` at reduced confidence for review; `template_engine._populate_letterhead()` renders a multi-line job title as one paragraph per line under the same "Job title:" label, instead of the single-run-per-field logic every other letterhead field still uses |
| **Immediate follow-up, same CV, real HR feedback**: "job title again shows as an address" — the split above still left the trailing `"Middlesex University, Dubai Campus"` on the second line | The MDX template's own placeholder text literally instructs "Title, Centre or Institute Name" — the code followed that instruction, but it wasn't actually what HR wanted: the institution/campus name reads as an address fragment glued onto a title, and it's redundant with what Present Employment already states in full | New `TRAILING_INSTITUTION_RE` (reuses the University/College/Institute/Academy/… keyword vocabulary `INSTITUTION_RE` already uses elsewhere) strips a trailing institution+campus tail from the END of every job_title line — applied to both lines of a dual-title split and to an ordinary single-line title alike, via `_clean_job_titles()` (renamed from `_split_dual_title_job_title`, now doing both jobs). Scoped to only ever strip from the end and only when it resolves to a real institution keyword, so "International and Comparative Education" (a department name with no institution word in it) is untouched |

## 2026-08-29 — Résumé-shaped employment lines, a global extraction bug, and hyphenated names

Two rounds, both triggered by HR testing real/reconstructed CVs and asking for
each defect to be traced to a general cause rather than patched per file.
Suite: **32/34 passing** throughout (corpus grew from 25 to 34 as more sample
résumés were dropped into `Downloads/`; the 2 failures are pre-existing,
unrelated blank vendor templates with literal `NAME`/`ADDRESS` placeholder
text — not real CVs, nothing to extract).

### Round 1 — job title glued to the person's name; DOB/nationality/driving
license leaking into Career Details; Skills' first line merging four
unrelated skills into one; Biography including the address/phone block

| Defect | Cause | Fix |
|---|---|---|
| Letterhead job title stored as `"Rachel Zane, Business Analyst"` | The line holds name + title with no field of its own; nothing stripped the name back off | If the candidate title line starts with the already-found name, that prefix is stripped before storing |
| Address/phone line published as a BIOGRAPHY bullet | Odd PDF spacing (`"890 -555 -0401"`) split the phone into 3 "words", accidentally clearing the 10-word prose threshold | `_is_biography_prose` now also rejects anything phone/email-shaped or dominated by uppercase letters |
| `05/10/1983`, `USA`, `Full` (driving-license status) published as Career Details bullets | These are personal-detail VALUES whose LABEL landed elsewhere after a scrambled layout — only the labelled form was filtered | New junk-line patterns for a bare date, a bare country name (narrow, curated list), and a bare employment-type word |
| A "SUMMARY OF QUALIFICATIONS"-style heading's skills/traits paragraph published inside MDX's Qualifications section, alongside the real degree line | Every line under a recognised heading was accepted wholesale | A Qualifications body line with no degree name, institution, or year is rerouted to Skills instead — same treatment Biography already gets |
| `SALESMAN Didier Sachs / Los Santos, CA / 2008–2011` split as title=`"Didier"`, employer=`"Sachs"` (a 2-word title split at the wrong point); `ACCOUNT CONSULTANT` similarly truncated to `"ACCOUNT"` | A single lazy word-run can't find the real title/employer boundary | Title read as a run of ALL-CAPS words, employer as a run of Title-Case words — the casing convention itself marks the boundary |
| "Bare `City, ST`" filter tried and **reverted** | Also matched `"Branson University, NV"` and `"Rutgers University … NJ"` — an institution name ending in a state abbreviation is ordinary content, indistinguishable by shape alone from a stray address fragment | Confirmed via full-corpus run (deleted two real university names); dropped rather than shipped |
| A skills list with no bullet glyphs ran four unrelated skills into one line (`"Analytics Requirement Gathering Project Management…"`) | Sentence-boundary grouping fallback has no signal to split on when nothing ends in punctuation | Scoped to the `skills` section only: each new capitalised line starts a new item, unless it's actually the employer/date tail of a job header that got split apart by this very rule (`EMPLOYER_LOCATION_YEAR_TAIL_RE` guard) |

### Round 2 — the same employment-field-splitting bug, chased further; then a genuinely fresh CV surfaced two more general bugs

Explicitly asked for after Round 1: *"fix that employment field parsing bug
too"*, referring to a case flagged during testing (not yet reported):
`"Clearpoint, Buffalo, NY (2008 – present)"` on the line under a bare title
line (`"Advertising Manager"`) parsed as title=`"Clearpoint, Buffalo"`,
employer=`"NY"`.

| Defect | Cause | Fix |
|---|---|---|
| Title-only line + `"Employer, City, ST (dates)"` line read as one field pair with the state abbreviation stored as the employer | The generic parser only ever sees one line at a time and has no way to know the previous line was a title | `_employment_body_entries()`: when a bare title-shaped line (contains a real title keyword) is immediately followed by an `Employer, City, ST(-country) (dates)` line, fields are built directly from the two known pieces, not re-parsed from a glued string |
| `"Associate Advertising Manager Carhartt, Inc., Buffalo, NY"` → employer stored as `"Inc."` alone | A corporate suffix carries its own comma, which reads as a third field | `CORP_SUFFIX_RE` folds a trailing `Inc./LLC/Ltd/Corp/…` back onto the employer part before it |
| Grouping sometimes fuses the title line onto the employer line **before** the two-line check above ever runs (`"Senior Marketing Executive Falcon Media House, Amman, JO…"` as one string, no title/employer boundary left) | No punctuation ties them together, so the sentence-boundary grouping fallback merges them like any other wrapped line | A job-title keyword's last occurrence marks the most plausible title/employer boundary within an already-merged single string, as a second-line fallback |
| A country code (`"UAE"`, 3 letters) wasn't recognised as a location tail at all, so `"Dubai, UAE"` was never stripped | The tail pattern required exactly 2 letters (US states only) | Widened to 2–4 uppercase letters |

**Then, testing a genuinely fresh, previously-untouched CV surfaced two
general bugs neither of the above chased for:**

| Defect | Cause | Fix |
|---|---|---|
| A person's current job title silently missing from their most recent Employment History entry whenever it also appears in the letterhead — a **document-wide** bug, not specific to any one file | `_docx_paragraph_texts()` deduplicates any paragraph whose text repeats verbatim anywhere earlier in the document (meant to catch a heading duplicated between a decorative shape and the body flow), applied indiscriminately to ALL text — and "current job title repeated as the title of the current role" is one of the most ordinary CV patterns there is | Dedup scoped to heading-SHAPED text only (`_is_heading_shaped`: short, and either ALL CAPS or colon-terminated); ordinary content that happens to repeat is no longer silently deleted. Fixed in both dedup layers (`_docx_paragraph_texts` and the outer `extract_docx` merge with header/footer/hyperlink lines) |
| `"Sarah Al-Mansoori"` rejected as a name outright; a worse, email-derived guess (`"Sarah Almansoori"`, hyphen dropped) used instead, and the real name line landed in the Unmapped safety net | `NAME_LINE_RE`'s per-word character class excluded hyphens and apostrophes entirely — the whole line fails to match over ONE punctuation mark inside ONE word | Each name token now allows an internal hyphen or apostrophe (`Al-Mansoori`, `O'Brien`, `D'Souza`) |
| A duplicate, garbled Present Employment entry, and the letterhead job title overwritten with a 170-character run-on string | `_promote_present_role()` (which files the CV's own current role under Present Employment when there's no separate heading for it) re-derives a "role" from raw verbatim text using only a `"|"`-split, with no real date/narrative stripping — exposed once the job-title dedup fix above meant more real text reached this stage | Now checks first for an already-classified `previous_employment` item with a clean parsed title and `is_current` set, and **promotes it in place** (moves the existing item, doesn't fabricate a second one from crude text-splitting) |

Both new-CV bugs are corpus-wide, not file-specific: the extraction dedup bug
could have been silently deleting real content on any DOCX where a job title,
or any other short-ish line, happened to repeat; the hyphenated-name bug
affected every name written with an internal hyphen or apostrophe. Neither
was caught earlier because the existing 34-CV corpus happened not to exercise
either pattern — reinforces that a synthetic, deliberately-varied test CV is
worth running occasionally alongside the corpus, not just real files as they
arrive.

---

## 2026-08-28 — Conformance pass against the conversion spec

Worked from `mdx-faculty-cv-conversion-prompt.md`. Most of the spec was
already met; this records the gaps that were not, and the defects found while
closing them. Suite: **15/15 passing**, with four new invariant classes.

### Gaps closed

| Spec | Was | Now |
|---|---|---|
| §2 empty sections keep their heading | Section deleted entirely | Heading kept, reads "Information not provided." |
| §8 UNMAPPED INFORMATION note | **Missing entirely** — unclassified lines were dropped | Reconciliation pass + note appended to the document |
| §3 headers and footers | Never read — separate package parts | Read for every section of the document |
| §3 hyperlinks embedded as Word relationships | Only the visible text was read | Targets resolved from `document.xml.rels` |
| §5 Profiles & Identifiers | No URL detection at all | Whole-document scan for 9 platforms + websites |
| §5 qualification fields kept separate | Fields were always `{}` | degree / subject / institution / country / year |
| §5 fellowship ≠ membership; editor ≠ board member ≠ reviewer ≠ examiner | Not distinguished | `kind` field, kept out of display text |
| §9 verify before handing back | Confidence only | Coverage + discarded-item count in the quality report |

### Defects found while building the above

Every one of these was found by inspecting real output, not by the spec.

| Defect | Cause | Fix |
|---|---|---|
| An entry tagged `kind="Membership"` would render **as the word "Membership"**, losing the entry | The generic formatter joins every string field | `METADATA_FIELDS` excluded from display |
| Institution repeated under each degree deleted as a "running header" | It appeared 4× on a CV written entirely at one university — detaching every degree from its awarding body and every role from its employer (§4) | Repeated **content** distinguished from page furniture |
| Two degrees merged into one item, then reporting the *second* one's year and country (§5 forbids) | Nothing forced a new item at a degree name | `_opens_with_degree`, gated on a year or an awarding body also being present |
| Degree detached from the institution on the line below | "Entry ends with its date column" closed the entry | Exception for a bare organisation-and-location line |
| `Master of Arts … (0101)` | Year matched as bare `\d{4}` — a course code qualifies | `CALENDAR_YEAR_RE` (19xx / 20xx) |
| `Academy of Arts, United Arab Emirates` for a Bulgarian degree | Country taken from anywhere in the line | Searched in a 40-char window after the institution |
| `Robotics Expected Oct 2026 Middlesex University` stored as the institution | `INSTITUTION_RE` reaches back six words, across a wrapped line | An institution containing a year, month or degree is rejected |
| `University of Technology` out of "**Anna** University of Technology"; `Academy of Arts` out of "**National** Academy of Arts" | The "University of X" pattern was tried first and won | Both patterns tried; earliest start wins |
| Subject swallowing `GPA 3.5/4.0 Teaching Skills / Knowledge` | Nothing bounded the subject | `SUBJECT_STOP_RE` + plausibility check (word count, letter ratio, balanced brackets) |
| A real subject "Education (Mathematics and Science)" thrown away | `_find_heading_key` matches *contained* phrases, so it resolved to the Qualifications heading | Only an exact official heading rejects a subject |
| Eleven of an academic's own blog and article URLs filed as her "profiles" | Any `http` link counted as a personal website | Generic URLs only from the letterhead or a profiles heading; publisher/DOI hosts excluded |
| Truncated URLs (`https://doi-`, `https://www.inclusive-education-`) | PDF line-wrapping breaks URLs on a hyphen | Rejected, and asserted against in the suite |
| `linkedin.com/in/name` stored with no scheme — not a followable link | Only `www.`-prefixed addresses got one | Bare domains get `https://` |
| `C.Chaudhary@mdx.ac.ae: mailto:C.Chaudhary@mdx.ac.ae` | Redundant mailto hyperlink | Skipped when the address is already the visible text |
| Correctly classified publications reported as **unmapped** | Item grouping strips the leading bullet, so the source line was no longer a substring of the item | Bullet stripped in the comparison form too |
| Letterhead lines (`Contact: +971…`) reported as unmapped | The label is stripped before storing the value | Label-stripped comparison, plus field values count as coverage |
| Grant detail lines reported as unmapped | A funded project's role/duration/funder are held as *fields*, not in the quote | All string field values count as coverage |
| Everything below a wrapped sentence labelled `From "education."` | The sentence ended "…for open-source robotics education.", which matches a Qualifications synonym | Context label requires the line to look like a heading |

## 2026-08-28 (there is no truly final) — Skills/Awards content-based reclassification, for any résumé, not just this one

Directly requested after the previous entry's honest disclosure: "fix the
skills and awards misclassification for all résumé style" — not just the
one file that surfaced it.

### Why this is a different move from the three rejected general fixes

Every earlier attempt at a general fix this session operated on RAW TEXT
SHAPE to guess where a SECTION BOUNDARY was — and each one, however
narrowed, ended up misreading something on a different CV (an employer
name, a job title, a person's own name). This is structurally different: it
re-examines items that are **already classified** into `skills` or
`awards` — sections a heading match already put them in, not a shape
guess — and moves out only what matches a signal precise enough to be
validated with **zero false positives across the full 25-CV corpus** before
being wired in. It reuses the same "re-file by content, only from a
non-authoritative section" pattern `routing.py` already established and
proved safe earlier the same day.

### Two signals shipped

1. **A real degree name** (`DEGREE_RE`, already used throughout
   Qualifications parsing) found in a `skills`/`awards` item → moved to
   `qualifications`. Caught, correctly: `BA BUSINESS ADMINISTRATION
   University of Southern California 2005–2009` (Account Manager), `DIPLOMA
   IN SOUND ENGINEERING`, `DIPLOMA NAUTICAL SCIENCE` (Anujith's CV).
2. **A full job-entry header** — `"JOB TITLE Employer / City, ST /
   Year"`, glued onto one line with no separator (`EMPLOYMENT_ENTRY_HEADER_RE`)
   → moved to `previous_employment` or `present_employment`. Caught:
   `SALESMAN Didier Sachs / Los Santos, CA / 2008–2011...` and `ACCOUNT
   CONSULTANT Legal Genius / Pasadena, CA / 2011–2015`, both of which had
   been sitting in Skills.

### A defect in the fix itself, caught before shipping

Extracting structured fields (title/employer/dates) from the FULL matched
item broke on the `SALESMAN` case specifically: its responsibility bullets
had been merged onto the same item as the header (upstream grouping is
inconsistent about this — the `ACCOUNT CONSULTANT` entry didn't have this
problem). Fed the whole blob, `_extract_employment_fields` hunted for a
title/employer on the wrong side of the date match and produced a
fluent-*looking* but wrong field set — `title: "Networked effectively with
clients"`, `employer: "increasing revenue by 47%..."` — that silently
dropped both the real header and the responsibility text, since a
formatter shows parsed fields OR verbatim text, never both.

Fixed by checking how much text follows the matched header: if there's more
than a trace, the parse is abandoned and the item renders fully verbatim
(nothing dropped) rather than through a wrong-looking structured line — the
same "a rebuilt line is only used when the parse is demonstrably complete"
principle already applied to qualification parsing. Only a clean,
header-only match gets the nicer structured rendering.

### A third direction tried and dropped: rescuing stray skills out of Awards

`Oracle E-Business Suite`, `Microsoft Dynamics`, `Active Listening` sit
under `AWARDS AND RECOGNITIONS` on the Account Manager résumé — clearly
wrong, and the reverse of the two directions above. A rule was tried:
reroute an Awards item to Skills when it has no "award"/"recognition"
keyword and no year attached. Checked against the full corpus before
shipping, and it produced real false positives: a genuine sales-ranking
achievement (`TOP 6% OF NEVADA SALES`), a vendor template's placeholder job
line (`Accounting & Finance Manager (20XX – 20XX)`), and a stray sentence
fragment (`hardware.`) were all misrouted. There is no reliable positive
signal for "this is a skill" the way there is for a degree or a job-entry
header — skills are too heterogeneous in shape. **Dropped rather than
shipped anyway.** This specific cross-contamination direction remains a
known, stated limitation; the two directions that validated cleanly were
kept.

Verified against the full 25-CV corpus: identical item and unmapped counts
on every file except the ones whose skills/awards content actually moved
(Account Manager, Anujith). 25/25 suite passing throughout.

---

## 2026-08-28 (past truly final) — Profile Photo status bug, Unmapped clutter in the checklist, six skills categories merged into one blob

Triggered by two screenshots (a "Profile Photo — MISSING" badge and an
"Unmapped Information — NEEDS REVIEW" badge, both in the review screen's
top-of-page checklist) plus a direct instruction to study `Aman Mishra
CV.pdf`'s headers against the master template.

### A real, always-reproducing bug: Profile Photo showing "missing" even when found

`build_quality_report()` determined every section's status, including
Profile Photo, by checking `items` for a `section == "profile_photo"` entry.
**No such item has ever existed** — a photo is stored on the CV record
(`cv.photo_path`), never as a row in the items table, because there's
nothing to approve/reject about an image the way there is for an extracted
fact. This meant the checklist's Profile Photo row read "missing" on
**every CV that has ever gone through this tool**, even when the photo was
correctly detected and was already displaying in the photo widget one
scroll down the same page.

Confirmed directly: `extract_photo()` on `Aman Mishra CV.pdf` in isolation
returns a real 241KB PNG, and a fresh upload through the live server
correctly set `cv.photo_path` — the extraction was never broken. Only the
checklist's status calculation was wrong.

Fixed: `build_quality_report()` takes a `has_photo` parameter now,
threaded from `cv.get("photo_path")` at both call sites in `main.py`, and
the Profile Photo row uses it directly instead of consulting the (always
empty) items list.

### Unmapped Information removed from the summary checklist

Not a data-integrity issue like the photo bug — the underlying safety net
(reconciliation, the full Unmapped Information review section further down
the page, teach-a-heading) is untouched. But showing "Unmapped Information"
in the SAME at-a-glance checklist grid as the 20 real MDX sections, styled
identically with "missing" / "needs review" pills, reads as if it's part of
the CV's structure and something is broken — exactly backwards, since (as of
the previous entry) it never appears in the generated document at all.
Filtered out of that one grid client-side; the full section with its
content, move-to-section controls, and teach-heading panel is unchanged.

### Six skills categories merged into one 815-character blob

`Aman Mishra CV.pdf`'s skills block reads `ROBOTICS ROS 2 (Jazzy),
ros2_control... EMBEDDED Arduino... CAD & FABRICATION SolidWorks... AI &
VISION OpenCV... SOFTWARE Python... PROFESSIONAL Team leadership...` — six
category labels, each glued directly onto its own comma-separated list with
no bullet, no colon, no line-end punctuation anywhere. Sentence-boundary
grouping merged the entire block into one item. Nothing was actually lost
— checked and confirmed every category, including `PROFESSIONAL` at the very
end, was present in that one giant string — but reading it as one 815-
character run-on sentence effectively hides the leadership/management
skills at the tail from a reviewer skimming the document.

Fixed with `_starts_skill_category()`, a new grouping-boundary signal
**explicitly scoped to fire only within a section already identified as
`skills`**: a leading run of 1-5 ALL-CAPS tokens (letters, digits, `&`, `/`)
totalling at least 6 letters or 2+ words, immediately followed by more
content on the same line. The `>=6 letters or 2+ words` threshold exists
specifically so it doesn't fire on an ordinary short acronym opening a
genuine list item ("GPU acceleration...", "SQL and NoSQL...") — those are
content, not a new category.

**Why scoping to "skills" specifically made this safe to ship**, unlike
every general section-boundary heuristic tried and rejected earlier the same
day: misfiring here can only split one skills bullet into two extra bullets
within a section already correctly identified. It can never misattribute
content to the wrong top-level section — the exact failure mode that sank
all three earlier general-heading attempts (an employer name, a bare job
title, a person's own name each mistaken for a section boundary). Low blast
radius by construction, not by luck.

Verified against the full 25-CV corpus: `Aman Mishra CV.pdf` split cleanly
into the intended 6 categories. On `Anujith_Av_Technician_Cv_2025
Cv (4)-6.pdf` — a résumé whose skills block interleaves brand names
(CHRISTIE, BENQ, PIONEER, AVOLITES) through an unstructured equipment list
with no clean category structure at all — the same rule over-splits into
more, smaller bullets than ideal. Not wrong: nothing lost, nothing
misclassified, just more granular than a human would choose. Left as-is
rather than adding a second heuristic to distinguish "brand name" from
"category label" without the validation budget that would deserve. 25/25
suite passing throughout.

---

## 2026-08-28 (truly final) — Empty sections and Unmapped Information removed from the generated document; a real "Languages Known" loss fixed

Three explicit instructions in one message, triggered by two screenshots:
empty sections showing "Information not provided." should not appear at
all; "Unmapped Information" must never exist in any generated CV; and a
"Languages Known: English, Hindi and Arabic" line, visibly present in the
source, was missing entirely from the output.

### Two policy reversals, on direct instruction

**Empty sections.** Earlier in this session, empty sections were changed
from *deleted* to *kept, reading "Information not provided."* — reasoning
that a visible gap proves the section was checked. HR's instruction reverses
this back: **removed entirely, heading included**, matching the very first
version of this behaviour. `template_engine.py`'s `_populate_sections`
change is a straight revert of the earlier change, `EMPTY_SECTION_TEXT` and
its import removed as dead code.

**Unmapped Information.** Raised three times over the course of the day,
each time more directly, ending with "its not something to exist in any
CV." The underlying safety net — reconciliation against the source text,
and every unmapped item visible in the review screen before "Generate"
unlocks — is **unchanged**. What changed: `populate()` no longer calls an
unmapped-appendix function at all (the function itself, and its now-unused
`UNMAPPED_HEADING`/`UNMAPPED_PREAMBLE` imports, deleted). An item still
sitting in Unmapped Information at generation time simply does not appear
in the downloaded file. The review screen's copy was rewritten to say this
explicitly, since "approve" no longer means "will be in the document" for
that one section — it means "reviewed."

This is a genuine, stated tradeoff, not swept under the rug: the tool's
data-integrity guarantee is now scoped to the *review process* (nothing a
reviewer can't see and act on), not the *final file* (a reviewer can now
choose, by not moving an item, to leave it out of what HR sends). Documented
plainly in `HANDOVER.md` §5c rather than left implicit.

### The real bug this exposed

A CV's `Personal Details` block routinely bundles one genuine fact — a
language list — among things that are correctly junk (date of birth,
driving licence, visa status, nationality, address). `PERSONAL DETAILS`
resolves to `_ignored`, and `_ignored` sections were dropped **wholesale**,
without even a per-line check — so `Languages Known: English, Hindi and
Arabic` never had a chance to be rescued, regardless of how obviously
extractable it was.

Fixed with a narrow, targeted rescue: before an `_ignored` section's lines
are discarded, each is checked against one specific, unambiguous pattern —
`^Languages?(?:\s+Known)?\s*:\s*...` — and a match is emitted to
`language_proficiency` verbatim, unsplit (no attempt to break "English,
Hindi and Arabic" into three separate facts, which would risk inventing
structure the source doesn't state). Everything else in the block — DOB,
driving licence, nationality, visa status — is still correctly discarded.
This is deliberately not a general "scan ignored content for anything
useful" rule, which would reopen the exact force-fit risk `_ignored` exists
to prevent; it targets one specific, well-understood, high-value pattern.

Verified against a synthetic CV matching the screenshot's exact shape
(name, email, "Personal Details" heading, DOB, "Languages known: English,
Hindi and Arabic", driving licence, nationality, visa status, address):
only the language line is extracted, everything else correctly dropped.

### Test suite updated to match, not just the product

Two invariants added earlier this session asserted the *previous* policy
(§9: every section present with a placeholder if empty; §10: the unmapped
note present exactly when there's content). Both rewritten to assert the
*current* policy instead — an empty section's heading must be **absent**,
and `UNMAPPED INFORMATION` must **never** appear in the generated document,
full stop. The suite is written to today's decision, not treated as a
historical record of a decision that no longer holds.

25/25 passing. Verified on a real CV (`Devapriya_CV.pdf`, whose generated
document previously showed 12 empty official sections and an Unmapped
Information appendix) that the output is now: letterhead, Biography,
Qualifications, Previous Employment, Skills, Language Proficiency — nothing
else, no placeholders, no appendix.

---

## 2026-08-28 (the actual final) — HR-taught headings, so the fix doesn't need to come from a developer

Triggered by a direct, reasonable question: with new CVs uploaded
continuously, why can't every heading-recognition bug be fixed once and for
all instead of one file at a time?

**The honest structural answer, given first:** it can't, for the same reason
no natural-language classifier of open-ended human writing ever reaches
one-shot completeness — CV authors have unlimited freedom in how they title
a section, and a system that recognises known phrasings can only know what
it has been taught. This isn't a flaw specific to this codebase; the same
session already spent three separate attempts (§ "Trying, and rejecting, a
fully general fix for unknown headings", above) proving that no *general*
detection rule can safely stand in for that judgement without breaking
something else.

**What was actually built in response:** rather than another round of
"add this one heading and hope," the fix is now something HR does directly,
with no code change and no restart:

- `custom_heading_mappings` table (`storage.py`) persists HR-taught rules.
- `rule_classifier.register_custom_heading()` / `load_custom_headings()`
  keep a live, in-memory lookup that `_find_heading_key` checks — ranked
  right after an exact official template heading (which always wins first,
  so a mapping can never override the template's own structure) and ahead
  of every built-in fuzzy/synonym guess.
- `GET/POST /api/heading-mappings`, `DELETE /api/heading-mappings/{id}`.
- The review screen: every distinct heading behind that CV's *unmapped*
  content gets a row at the bottom of the Unmapped Information section — a
  section dropdown (all 20 official sections plus Skills and Language
  Proficiency) and a "Teach this heading" button. One click, and every CV
  uploaded afterward with that same heading classifies correctly.

**Verified end-to-end, not just unit-level:** a synthetic CV with a heading
("VOLUNTEER WORK") that exists nowhere in the corpus or the built-in synonym
tables was uploaded, correctly landed in the unmapped note, taught via a
live `POST /api/heading-mappings` call against the running server (no
restart), and a **second, fresh upload immediately after** — same process,
no code change — classified it correctly into the chosen section. Confirmed
in the browser too: the review screen's Unmapped Information section
renders the teach panel with the right heading text and the right dropdown
options.

25/25 suite passing (the feature is inert — zero registered mappings — for
every CV already in the corpus, so nothing regressed).

**What this doesn't solve:** a mapping is forward-looking. The CV that
exposed the new heading still needs its *own* unmapped items moved by hand
this one time (the existing move-to-section dropdown on each item already
does that) — teaching the heading means the *next* CV with that wording
needs no such manual step.

---

## 2026-08-28 (final) — Skills and Language Proficiency promoted to real sections

An explicit, repeated product decision, not a bug fix: after three separate
CVs raised the same complaint, HR stated directly that Skills and Language
content must never appear as "Unmapped Information" — if it's skills, it
must read "Skills"; if it's languages, "Language Proficiency". This
overrides the earlier recommendation to keep strict §8 compliance (never
create a section the master template doesn't have); HR's decision was
reaffirmed after that tradeoff was explained, so it was implemented as given.

### What changed

Two new appended sections, `skills` and `language_proficiency`
(`config.py`), populated the same way `UNMAPPED INFORMATION` already was —
present only when there is content for them, styled by cloning a real
section heading's formatting so they read as part of the document rather
than as an afterthought. `SELECT PRACTICE OUTPUTS`-style curated-heading
recognition (`SYNONYM_HEADINGS`) now routes `SKILLS`, `KEY SKILLS`,
`TECHNICAL SKILLS`, `DIGITAL AND TECHNICAL SKILLS`, `LANGUAGES`, `LANGUAGE
PROFICIENCY` and close variants into these instead of the generic `_ignored`
bucket. `quality.py`'s coverage calculation counts them as mapped, the same
as an official section, since they are no longer part of the safety net.

### Two defects this promotion exposed, both fixed

Content landing in `_ignored` was low-stakes before — wherever it ended up,
it read as generic unmapped noise either way. Once Skills and Language
Proficiency became real, prominently-rendered sections, the same bleed-
through became a visible, embarrassing defect instead of a cosmetic one:

1. **Visa/passport details bleeding into "Language Proficiency".** A heading
   the classifier didn't recognise (`OTHER INFORMATION`) no longer stopped
   the section, so `Issue Date: 02/08/2024` and similar visa content were
   about to render directly under a Language Proficiency heading in the
   generated document. Fixed by adding `OTHER INFORMATION`,
   `MISCELLANEOUS`, `ADDITIONAL DETAILS`, `VISA STATUS`, `PASSPORT DETAILS`
   to `_ignored`.
2. **Three separate languages merging into one bullet** — `English :
   Proficient Hindi : Fluent Tamil : Intermediate` as a single line, because
   none of the three source lines end in sentence punctuation and none use a
   bullet glyph. Fixed with `_is_short_labelled_entry` — a pair-gated
   detector for short "Name : Level" / "Name (Level)" lines (both the
   current and the previous line must match, the same conservative gating
   validated safe for the dash-entry fix earlier the same day), so an
   isolated sentence containing a colon can never trip it on its own.

### Full-corpus effect

Verified against all 25 CVs, not just the ones that prompted this. The
result is a broad reduction in unmapped content across nearly the whole
corpus — not just the files that were complained about, because Skills and
Languages are near-universal CV sections:

| File | Unmapped before | Unmapped after |
|---|---|---|
| Account-Manager-Resume-Sample_Westminster-Blue.docx | 35 | 15 |
| Anujith_Av_Technician_Cv_2025 Cv (4)-6.pdf | 32 | 13 |
| Aman Mishra CV.pdf | 26 | 12 |
| Anuradha Vyas CV.docx | 19 | 11 |
| Devapriya_CV.pdf | 19 | 6 |
| Dimo Stefanov Valev CV.docx | 7 | 1 |
| Real-Estate-Resume-Sample.docx | 5 | 1 |

25/25 suite passing throughout.

### Known residual, stated honestly

On Devapriya's CV, three originally-separate skill categories (`Backend:
Node.js, Express.js, Django`, `PC / Laptop Installation & Troubleshooting`,
`Excellent Communication (verbal, written, digital)`) still merge into one
bullet under Skills. None of the pair-gated list detectors built today catch
this specific shape (a colon-labelled category line followed by an
unlabelled skill line with no colon of its own). The content is present and
readable, just under-split. Left as a known limitation rather than adding a
fourth heuristic without the same full-corpus validation the other three
received.

---

## 2026-08-28 (still yet later) — Devapriya's résumé: two real grouping bugs, and a lot of correct behaviour mistaken for bugs

Triggered by three screenshots of the generated document. Two real defects
found in `Devapriya_CV.pdf` (the two-column IT-support résumé, previously
fixed for its date-range and reading-order bugs on 2026-08-26).

### Bug 1 — a phone number welding onto an unrelated certification

`(+971) 55 529 8136 | Core Digital Marketing Academy Certified Digital
Marketing Manager course2025` — one qualification item combining a stranded
phone number with a real certification. Root cause: `_is_bare_contact_line`
already exists specifically to keep a stray contact fragment out of section
content, but its cleanup was `text.strip().strip("|·•,;")` — stripping the
trailing `|` character left the space that had been in front of it
(`"...8136 "`), and the exact-equality check against the phone regex's own
match (which has no trailing space) then failed by one character. The line
survived as ordinary content instead of being dropped. Fixed with a second
`.strip()` pass.

Generalised beyond the filter fix: once a line consisting only of a phone
number or email becomes the head of a grouped item, the *next* line must
never be accepted as its continuation either — the same symmetry already
applied to headings earlier this session (`_find_heading_key(current[-1])`)
now also covers `EMAIL_RE`/`find_phone` on `current[-1]`. This is what
stopped the phone number from becoming the anchor a real fact welded onto,
for any future CV where a scrambled layout strands a phone number next to
unrelated content.

### Bug 2 — a certifications list with no bullets, merged into one line

Four certifications (`React.Js Course - Udemy`, `Google Flutter -
Internship`, `AI Dashboards using Microsoft Power BI - Certification`,
`Certified Digital Marketing Manager - Certification Course`) merged into
one bullet, because the source has no bullet glyphs and none of the four
lines end in sentence punctuation, so sentence-boundary grouping ran them
together.

Fixed with a narrow, symmetric-pair-gated rule: a short "Title - Provider"
line (`_is_short_dash_entry` — 2-8 words, one dash, no digit, no sentence
punctuation) only forces a new item when the line *before* it ALSO matches
the same shape. Pair-gating deliberately keeps this from firing on an
isolated sentence that happens to contain one dash ("Led the Q3 rollout -
on time and under budget."), which would need only one match, not two, to
trip a looser version of this rule.

Verified against the full 25-CV corpus: identical item and unmapped counts
on every file except Devapriya's own (20 → 23 items, all from the two real
fixes above, not from misfiring elsewhere). 25/25 suite passing.

### What was checked and found correct — not bugs

Three more things were flagged in the screenshots and checked individually
against the actual source text:

- **Nine sections reading "Information not provided"** (Grants, Editorial,
  Publications, Teaching, Committees, Academic Leadership, Awards, Centres of
  Excellence, Profiles/Links). Checked line by line: **this candidate's
  résumé contains none of that content.** She is a junior IT support
  candidate with two years' prior experience, not an academic — the MDX
  Faculty CV template's research/teaching/editorial sections have nothing to
  draw from for this kind of CV, and correctly say so rather than inventing
  content. This is a structural property of using an academic template for a
  non-academic candidate, not a classification failure.
- **"Skills" and "Languages" content in the UNMAPPED INFORMATION note.**
  There is no "Skills" or "Languages" section among the MDX template's 20
  official sections. Per §8 of the conversion spec this project was built
  against, content with no official-section home is required to go to the
  unmapped note rather than being force-fit into the nearest-sounding
  section — this is the system doing exactly what its own spec asks, not a
  classification failure. Raised as an explicit product question back to the
  user rather than silently reinterpreted, since changing it would mean
  overriding the spec's own §2 "never force-fit" rule.

---

## 2026-08-28 (yet later) — Trying, and rejecting, a fully general fix for unknown headings

Prompted directly: make sure the classes of bug just fixed (an unrecognised
section heading's content bleeding into whatever section precedes it) don't
recur on a CV nobody has tested yet, not just the specific files fixed so
far.

The honest answer required actually trying to build that, not just
asserting it. Three attempts, each rejected on real evidence:

**Attempt 1** — treat any line that structurally reads as a heading
(`_looks_like_heading_line`: short, all-caps or colon-terminated) but
resolves to no known section as an automatic boundary. Broke immediately:
ALL-CAPS employer names are a standard résumé convention ("THE HAVERFORD
SCHOOL, Haverford, PA"), and a Publications sub-heading phrased slightly
differently from its registered synonym ("Selected conference presentation"
missing the "s") triggered it too. `Math-Teacher-Resume-Dark-Blue.docx`
dropped from 9 items to 2; Anita Shrivastava lost six real citations.

**Attempt 2** — narrowed with exclusions for a comma, a digit, or an
organisation keyword (same signals `_repeats_as_content` already uses
safely elsewhere). Fixed the employer-name case, but a bare résumé sub-label
like **"Responsibilities:"** — extremely common, ends in a colon, is not an
org name — still tripped it, pulling real job duties out of Previous
Employment. `Raoof.Razak.CP_Resume.pdf` dropped from the already-correct 30
items to 19.

**Attempt 3** — dropped the colon-terminated path entirely (every confirmed
real case — "PROFESSIONAL DEVELOPMENT", "LANGUAGE PROFICIENCY", "SELECT
PRACTICE OUTPUTS", "CONTRIBUATIONS" — is colon-free), and raised the
uppercase threshold to 90%. Still broke: a **bare job title written in caps
with no comma** ("FINANCE INTERN", "FINANCIAL ANALYST" on their own line) is
structurally identical to a genuine section divider, and a CV that repeats
the candidate's own name as a running header hit it too.
`Financial-Analyst-Resume-Sample-Hybrid-Blue.docx` dropped from 15 items to
5; `Raoof.Razak.CP_Resume.pdf` from 30 back to 19.

**Conclusion, reverted for good:** a genuinely unknown section heading
cannot be reliably distinguished from an entry-level label (employer name,
job title, a person's own name, "Responsibilities:") using structural shape
alone. Every signal tried — capitalisation, colon-termination, length,
punctuation, organisation keywords — is shared by real, common CV content
that must never be excluded from classification. This was validated against
the full 25-CV corpus after each attempt, not just the file that motivated
it; every one of the three regressions above was caught this way before
being shipped, not discovered later by a user.

**What actually generalises, and why it's still a real answer to "any type
of raw CV":**

1. **Curated exact-heading additions are unbounded in reach and carry zero
   regression risk**, because they only fire on an exact string match (see
   `SYNONYM_HEADINGS["_ignored"]` and the `publications` synonym list). Every
   fix in this session — `PROFESSIONAL DEVELOPMENT`, `LANGUAGE PROFICIENCY`,
   `SELECT PRACTICE OUTPUTS` and its variants — applies to *any* future CV
   that uses that same wording, uploaded by anyone, not just the specific
   file that surfaced it. The list only grows; it never needs to be reverted.
2. **Nothing is ever silently lost, for any CV, regardless of whether its
   heading wording has been seen before.** A heading this system has never
   encountered will still misfile its content into an adjacent section — the
   defect Dimo's and Anuradha's CVs demonstrated — but the content is never
   deleted, is always traceable to the exact source text, and (per §9's
   pre-handback checks and the reviewer's own eyes) remains visible and
   movable rather than vanishing. That is the actual, permanent guarantee:
   **misfiled, never missing.** It held for every CV in this session before
   any of today's specific fixes existed, and it will hold for the next CV
   whose heading wording is new too.

The forward path is to keep extending the curated list as real uploads
surface new phrasings — which is exactly what today's three fixes did, and
what running `test_corpus.py` against every new upload is for.

---

## 2026-08-28 (still later) — Dimo Valev: a design portfolio filed as "Awards"

Triggered by screenshots of the generated document alongside the official
master template, comparing headings side by side.

### The real defect

Dimo is a graphic design lecturer; his CV's research-record heading reads
**"SELECT PRACTICE OUTPUTS"**, not "Select Research Publications" — the
standard term for a creative/design academic's exhibited and commissioned
work, sitting in exactly the structural position Publications occupies on a
text-based CV. Unrecognised, its entire content — seven real facts: an
exhibited poster, and client work for Kraft Foods, Unilever, the UAE General
Civil Aviation Authority and others — fell through to whichever section
happened to precede it: **AWARDS AND RECOGNITIONS**. A design portfolio
being published as a list of prizes is exactly the kind of thing that would
not survive HR review.

Fixed: `SELECT PRACTICE OUTPUTS` and seven close variants (`PRACTICE
OUTPUTS`, `CREATIVE OUTPUTS`, `PORTFOLIO OF WORK`, etc.) added as synonyms
for `publications`.

### A second, smaller defect found while verifying

`Job title: •  Lecturer in Graphic Design...` — a bullet glyph leaking into
the letterhead. Cause: the CV puts the "Job titles:" label and its bulleted
value on two separate physical lines. The label-stripping code only strips
the bullet when label and value share one line; when they don't, the code
falls through to a second branch (matching the title by keyword) that never
stripped it. Fixed by stripping a leading bullet from the candidate line
before either branch runs.

### A structural fix that generalises beyond this one CV

Fixing the first defect exposed a second: once "SELECT PRACTICE OUTPUTS" was
recognised, its own internal sub-heading ("Exhibited practice outputs")
welded onto the first citation beneath it — same root cause as the
publications sub-heading bug fixed earlier this session, but from the
opposite direction. A sub-heading line, once grouped as its own entry, would
still accept the *next* line as a continuation under sentence-boundary
grouping, because the heading itself carries no trailing full stop to trip
the sentence-end check. Fixed generally: once the most recently grouped line
resolves via `_find_heading_key` (i.e. it IS a recognised heading or
sub-heading), the line after it is now always a new entry, never a
continuation — this closes the same failure mode for any future heading
added to `SYNONYM_HEADINGS`, not just this one.

Verified against the full 25-CV corpus (item counts identical to the
pre-fix baseline except Dimo's, where content moved to the correct section
rather than changing in volume) — 25/25 suite passing.

### What was checked and found correct, not a bug

The user also flagged `EDITORIAL BOARD MEMBERSHIPS`, `RESEARCH GRANTS`,
`INTERNAL/EXTERNAL COMMITTEES`, `ACADEMIC LEADERSHIP`, and `CONTRIBUTION TO
MDX CENTRES OF EXCELLENCE` all reading "Information not provided." Checked
against the actual source text line by line: **none of that content exists
anywhere in the CV.** No grant, no editorial role, no committee membership,
no leadership title, no centre affiliation is mentioned. Those sections are
correctly empty — the classifier has nothing to have missed. This is the
same pattern as Anuradha's Editorial Board Memberships question in the
previous entry: an empty section reads as a defect to someone scanning the
document, but is the correct output when the source genuinely has nothing to
say there.

The "Bulgarian (Fluent)" / language-proficiency content the user flagged as
"tagged wrong": there is no MDX section for language proficiency (it is not
one of the 20), so per §8 all five language lines correctly land in the
UNMAPPED INFORMATION note under their own "LANGUAGES" context label — not
force-fit into a section that doesn't fit them. Confirmed all five lines
(Bulgarian, French, English, Russian, German) are present, not just the one
visible in the screenshot's cropped view.

---

## 2026-08-28 (even later) — Anuradha Vyas: informal sub-headings, and a real regression caught before shipping

Triggered by the user attaching the portal's generated document alongside
their HR's own manually-organised version of the same CV and comparing them
side by side. HR's document uses two headings with no MDX equivalent —
**"PROFESSIONAL DEVELOPMENT"** and **"LANGUAGE PROFICIENCY"** — that the
portal didn't recognise.

### The real defect

Because those headings weren't recognised, `_split_into_sections` never
treated them as boundaries: everything under "PROFESSIONAL DEVELOPMENT"
(seven genuine training/workshop facts) was absorbed into whichever real
section came immediately before it — **Knowledge Exchange and Professional
Practice** — purely because that was the last heading the classifier
recognised, and the heading's own text ("PROFESSIONAL DEVELOPMENT") was
published as a nonsense bullet inside that section. "LANGUAGE PROFICIENCY"'s
three lines were similarly swallowed, ending up in the unmapped note but
mislabelled under a *different* preceding heading ("DIGITAL AND TECHNICAL
SKILLS") — not itself.

### The Editorial Board Memberships question

The user separately asked why `EDITORIAL BOARD MEMBERSHIPS, REVIEW, AND
EXAMINER ROLES` read "Information not provided." **Checked against HR's own
source document: it contains zero editorial, reviewer, or examiner content
anywhere.** This was the classifier being correct, not a defect — there was
nothing to classify.

### First attempt, caught before shipping: a broad heuristic that broke worse things

The first fix generalised the pattern: any line that structurally reads as a
heading (`_looks_like_heading_line`) but resolves to no known section became
an automatic boundary. It fixed Anuradha's CV — but a full-corpus item-count
sweep (not just re-checking the one file being fixed) showed real damage:

| File | Before | After the broad heuristic |
|---|---|---|
| Math-Teacher-Resume-Dark-Blue.docx | 9 items | **2 items** |
| Real-Estate-Resume-Sample.docx | 8 items | 6 items |
| Raoof.Razak.CP_Resume.pdf | — | 14 items, 48 unmapped |
| Anita Shrivastava CV.docx | 3 unmapped | **11 unmapped** |

Cause: **ALL-CAPS employer/school names are a standard résumé convention**
("THE HAVERFORD SCHOOL, Haverford, PA", "UNIVERSITY OF SOUTH ALABAMA, Mobile,
AL") and pass exactly the same structural heading test a genuine informal
sub-heading does. Treating every one as a section boundary discarded entire
jobs — dates, employer, every responsibility bullet — into the unmapped
note. Separately, Anita's CV lost six real conference-presentation citations
because "Selected conference presentation:" (missing the plural a synonym
expects) was mistaken for an unrelated topic change rather than a
Publications sub-group divider. And in `Raoof.Razak.CP_Resume.pdf`, the
common résumé sub-label **"Responsibilities"** triggered the same false
boundary, pulling real job duties out of Previous Employment.

**Reverted.** In its place: the same safe, zero-risk mechanism already used
for `DIGITAL AND TECHNICAL SKILLS` — a curated addition to the `_ignored`
synonym list (`SYNONYM_HEADINGS`), which only fires on an *exact* heading
match. `PROFESSIONAL DEVELOPMENT`, `LANGUAGE PROFICIENCY`,
`PROFESSIONAL LINKS AND ADDITIONAL INFORMATION`, and a few common variants
were added this way. `unmapped.py`'s context-labelling was separately fixed
to recognise these same unresolved-but-heading-shaped lines when relabelling
what follows — that change only affects the *label* on content already
excluded from classification, never what gets excluded, so it carried no
equivalent risk and was kept.

**Verified against the full 25-CV corpus by item count, not just pass/fail**,
specifically because a general heuristic had just proven the invariant suite
alone wasn't going to catch a "content moved to the wrong bucket, still
technically present" class of regression. Raoof recovered from 14 to 30
items; Real Estate from 6 to 14; Financial Analyst from 5 to 15 — all
recovering content the broad heuristic had wrongly excluded. 25/25 suite
passing throughout.

---

## 2026-08-28 (later still) — ARIF CV.docx: five defects in one screenshot

Triggered by a screenshot of `ARIF CV.docx`'s generated document. Skills and
traits were published inside QUALIFICATIONS, employment lines carried leaked
label fragments, and a heading with no MDX equivalent welded itself onto an
unrelated entry.

| Defect | Cause | Fix |
|---|---|---|
| Six skill/trait bullets ("Fluent in English.", "Active, Self-motivated.") published inside **QUALIFICATIONS** | The heading `SUMMARY OF SKILLS AND QUALIFICATIONS:` contains both "SUMMARY" (7 chars) and "QUALIFICATIONS" (14 chars) as known phrases; the compound-heading resolver picks whichever known phrase is textually **longest**, so the longer word won regardless of which one actually describes the section | A heading that **opens** with a summary/profile word (`SUMMARY OF...`, `PROFILE...`, `OBJECTIVE...`) now resolves to biography before the longest-match tier ever runs |
| That fix's own regression, caught before shipping: **Camilla's entire biography paragraph disappeared** | Content now routed to `biography` was filtered per-line; a check for a degree keyword ran *before* the "is this a real sentence" check, so "Dr Camilla holds a **PhD** in Education from the University of Cambridge." — an ordinary biography sentence that happens to name a degree — was rerouted to Qualifications, leaving Biography empty | Reordered: prose-length checked first (≥10 words keeps it as biography regardless of mentioning a degree); only a **short** fragment is then checked for a bare degree mention |
| `: Rashid Hospital-Dubai Health Authority...` — leading colon leaked into a stored employer name | `.strip(" ,|()[]-–—")` after the date match didn't include `:` | Added to the strip set |
| `time: First Stem Cell and Genomics Laboratory...` — stray word leaked in front of an employer | Source reads "to present **time**:"; the date regex matched "to present" and stopped, leaving "time:" as leftover text | Date regex extended to recognise "present time" / "current date" as a single ongoing-marker phrase |
| `Bachelor, ’s degree in medical laboratory Technologist` — garbled qualification line | `DEGREE_RE`'s word-boundary match stops at "Bachelor", before the apostrophe in "Bachelor's" — the possessive and the repeated word "degree" were left as the "subject" | Strip a leading `'s degree` before the normal subject-connector strip |
| `...reporting patient reports. CONTRIBUATIONS` — a duty line welded to a misspelled, unrecognised heading | "CONTRIBUATIONS" (misspelling of "Contributions") is not a known MDX section or synonym, so `_split_into_sections` never treats it as a boundary — it just becomes body text of whatever came before | A standalone short ALL-CAPS line with no punctuation now forces a new-item boundary during grouping even when it resolves to no section, so it can't be absorbed into an unrelated item |

**Where the dropped skill bullets went:** not lost. Per §8, a line with no
real MDX home (a skills list isn't one of the 20 sections) now falls to the
UNMAPPED INFORMATION note instead of being force-fit into Biography just
because it shared a heading with one. Verified: "Advanced level of computer
literacy...", "Active, Self-motivated.", "Fluent in English." all appear
under `From "Summary Of Skills And Qu..."` in the unmapped note.

25/25 suite passing throughout, including through the mid-fix regression
(caught by re-running the full corpus before considering the change done,
not by trusting the one file being looked at).

---

## 2026-08-28 (later) — Editorial roles sub-grouped in the document

A separate rebuild of this project done in another session (its own
`README.md`, working from an old handover doc) described editorial roles
grouped into Editor / Editorial Board Member / Reviewer / Examiner
sub-headings in the finished document — matching how Publications already
groups journal vs. conference entries. That module structure doesn't apply
here, but the missing capability was real, so it was added directly.

**Not a straight copy of Publications' approach.** Publications' items are
contiguous by sub-group in the source (a heading physically separates
"Peer-reviewed journals" from "Conference presentations"), so printing a new
sub-heading whenever the tag changes naturally produces one clean group per
kind. Editorial items are not reliably contiguous — a CV commonly interleaves
"Guest Editor, Journal A", "Reviewer, Journal B", "Guest Editor, Journal C" —
so the same approach would print "Editor" / "Reviewer" / "Editor" three
times. Editorial items are instead bucketed into a fixed print order
(`_grouped_by_kind` in `template_engine.py`) before rendering, using the
`kind` field already set by `_role_kind()` at classification time. An item
whose kind doesn't resolve to one of the four buckets is appended after the
recognised groups with no sub-heading, rather than dropped for not fitting.

Verified on Daphne's CV (Editor + Examiner, correctly separated) and checked
against two CVs where an editorial-section item's `kind` doesn't resolve
cleanly (a committee-style entry that landed under Editorial by heading
proximity, pre-existing and unrelated to this change) — it renders verbatim
in the unclassified bucket rather than being lost or mislabeled.

25/25 suite passing, no regressions.

---

### Round 2 — a converted résumé exposed eight more

Triggered by `Administrative-Assistant-Resume-2-converted.docx` generating a
document with an empty BIOGRAPHY, three jobs welded into single paragraphs,
and the résumé vendor's advertising published as MDX employment history.
Adding the new files in `Downloads` grew the corpus from 15 CVs to **25** and
five of them failed immediately.

| Defect | Cause | Fix |
|---|---|---|
| **BIOGRAPHY empty** on a CV that opens with a written professional summary | `PROFILE` / `OBJECTIVE` / `ABOUT ME` were not biography synonyms, so the paragraph was orphaned | 12 synonyms added |
| **Three jobs and eighteen responsibilities merged into three paragraphs**, with two job titles and their date ranges buried inside | The file has no bullet characters at all, so sentence-boundary grouping merged everything — no line ends in a full stop | List structure recognised: a colon-terminated line followed by gerund-opening lines; a capitalised non-gerund line ends the list |
| **Vendor advertising published as employment** — "Hire one of our certified professional resume writers from $49.95 per resume", and the order page filed under Professional Profiles | Résumé templates embed advertising addressed to the candidate | `VENDOR_BOILERPLATE_RE`; vendor hosts excluded from identifiers |
| A **real responsibility lost** with the advertising | Junk was filtered *after* grouping, so one merged item containing both was discarded whole | Junk filtered before grouping |
| **A regression I introduced doing that**: an Anuradha Vyas item discarded by the verbatim guard | Removing junk lines made their neighbours adjacent when they were not — the same class as the two bugs below | Junk lines become a `SEGMENT_BREAK`, not a deletion |
| **`César Cabal` rejected as a name**, so an employer ("Santa Clara Elementary") was used instead | `NAME_LINE_RE` was ASCII-only — **every non-ASCII name was affected** | Unicode letter class |
| **`(123) 456-7890` published as a job** under Previous Employment | A text-box layout extracts the contact block *after* the first heading | A bare contact line never becomes a section entry |
| **`Risk Management` and `Coursework Design` used as people's names** | An uncorroborated Title-Case phrase outranked the email address sitting beside it | An address now beats a shape guess: `fatima.arain@gmail.com` → Fatima Arain |
| **`John Smith` missed** on "John Smith␣␣␣␣␣␣Secondary Teacher History Department" | Wide whitespace is a column gap, not a word gap | Split on 3+ spaces or a tab |

Name detection across the readable corpus went from 19/23 to **22/23**.

### Files that cannot be read, now said so plainly

Two of the new files (`Administrative-Assistant-Resume-3`/`-5`) extract text
that is not words: a subsetted font with a damaged character map turns
`Orlando` into `zrlando`, `example@email.com` into `ePample/email.com`, and
`NATIONALITY` into `N AT I z N A 9 I T B`. The file is neither empty nor a
scan, so no existing check caught it, and every stage downstream then worked
confidently on nonsense.

Detected by the share of tokens that are a single stray letter. The two
broken files score **0.21–0.22**; the highest legitimate CV scores **0.049**
(a design-heavy résumé with letter-spaced headings). Threshold 0.12, with a
wide margin either side. The upload is now refused with an explanation and a
suggested fix, rather than producing a garbled CV.

### Two silent-loss bugs the safety net exposed

The most valuable thing the unmapped note did was find data loss that had been
invisible. Both were the **verbatim-quote guard discarding real items** —
a safety check causing the exact harm it exists to prevent.

**1. A section appearing twice in one CV.** `_split_into_sections` collects
every region under a heading into one list. Item grouping then merged the last
line of the first region with the first line of the second — building text
that appears nowhere in the CV. The guard rejected it and an entire degree
vanished:

```
Associate of Science (AS), Computer Science Dec 2021
Chandler-Gilbert Community College, Chandler, Arizona, United States
                                       ← two pages of employment in between
Pickerbot — Industrial Pick-and-Place for PCB Kit Assembly Jan 2026
```

Fixed with a `SEGMENT_BREAK` sentinel inserted when a section is re-entered;
grouping treats it as a hard boundary.

**2. A citation wrapping across a page.** Running headers are removed before
classification, which correctly lets a citation broken across a page be
reassembled — but the reassembled text is then not a substring of the raw CV,
because the header sat between the halves. The guard discarded a publication.

Fixed by validating against the header-stripped text as well as the raw text.
Both copies preserve the source's own words and order, so nothing fabricated
passes either — the anti-fabrication property is intact.

**Now a permanent invariant:** if the verbatim guard fires on any corpus CV,
the suite fails. The instruction in the test is explicit — *fix the grouping,
do not relax the guard.*

### A defect in the new tests, caught immediately

The first run reported *"official section is missing from the output:
'PROFESSIONAL ASSOCIATION MEMBERSHIPS AND FELLOWSHIPS'"* on **all 15 CVs**.
The section was fine. Word splits that heading across two runs
(`…MEMBERSHIPS` + ` AND FELLOWSHIPS`), and the test joined runs with a space,
inventing a heading with a double space that matched nothing. Runs within a
paragraph are now joined with nothing between them.

Worth recording because it is the same class of mistake as the earlier
`BARE_DATE_LINE_RE` false positive: **a wrong assertion is as expensive as a
wrong fix**, and a suite that cries wolf gets ignored.

### Known limitation, unchanged

A CV whose layout defeats the classifier now produces a **large** unmapped
note rather than a short document — 29 lines for one two-column résumé.
Nothing is lost, and the coverage figure states the position honestly, but
that is a reviewer's afternoon, not a click. Multi-column PDF reading order
remains the root cause (see the entry below).

---

## 2026-08-26 — `Devapriya_CV.pdf` (two-column IT résumé)

Three defects, found from one uploaded file. Suite: **15/15 passing** after.

### 1. Employment lines rendered as `July 2025 (2024)`

**Symptom.** An employment entry showed a date where the job title should be,
and only a single year in the date field.

**Cause.** `YEAR_RANGE_RE` recognised only *bare* years. On the source line:

```
Software Developer June 2024 - July 2025
```

it matched just `2024 - ` and stopped. `_extract_employment_fields()` then
applied its "take whichever side of the date carries text" rule, saw
`July 2025` sitting after the match, and stored that as the role — producing
`July 2025 (2024)`.

**Fix.** The date pattern is now month-aware and consumes the whole range:

```python
MONTH_WORD = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_PART = rf"(?:{MONTH_WORD}\s+)?\d{{4}}"
```

Years are then pulled out of the matched span with `YEAR_IN_TEXT_RE`, so a
month-bearing group still yields clean years. Result:

```
Software Developer (2024 – 2025)
Web Developer      (2023 – 2024)
```

Fixed alongside it: a parenthesised date left a dangling `(` on the role.

**Guarded by:** invariant 7 — no employment line may render as dates only.

### 2. Fourteen job responsibilities filed under Qualifications

**Symptom.** Qualifications held 14 items; employment held 2. Content was
present but in the wrong section.

**Cause.** Not a classification bug — a **PDF reading-order** one. This CV is
two-column, and the text stream emerges out of visual order: the job
responsibility bullets physically follow the `EDUCATION` heading in the
extracted text. Heading-based classification therefore filed them, correctly
by its own logic, as qualifications.

**Fixes attempted at the PDF level first, both rejected:**

| Approach | Result |
|---|---|
| pypdf `extraction_mode="layout"` | Returned **0 characters** for this file |
| Coordinate-based column reconstruction | `tm[4]`/`tm[5]` give *relative*, not absolute, positions — x range came back 0–101 on a 595pt page |

**Fix that worked.** A routing rule **scoped to its source section**, added to
`routing.py` as `SCOPED_RULES`:

```python
ACTION_VERB_RE = re.compile(r"^(?:designed|developed|implemented|diagnosed|...)\b", re.I)
SCOPED_RULES = [(ACTION_VERB_RE, "previous_employment", {"qualifications"})]
```

A line opening with a past-tense action verb *while sitting in Qualifications*
is a job responsibility that a scrambled layout misplaced.

**Why the scoping matters.** The same opening is legitimate content under a
teaching heading — "Developed session foci and content" is teaching material on
an academic CV. An unscoped rule would strip such lines out of Teaching &
Learning on every academic CV in the corpus. Restricting the rule by source
section keeps the useful case without the collateral damage.

**Result:** qualifications 14 → 5, employment 2 → 11.

### 3. Unbalanced phone bracket (found while verifying, not reported)

**Symptom.** Phone stored as `+971) 55 529 8136` — a closing bracket with no
opener, meaning the value had been sliced out of its line at the wrong offset.

**Cause.** `PHONE_CANDIDATE_RE` allowed a bracket *after* the `+` but not
before it. This CV writes `(+971)`.

**Fix.** Brackets are now permitted on both sides:

```python
PHONE_CANDIDATE_RE = re.compile(r"\(?\s*\+?\s*\(?\d[\d\s().\-]{7,}\d\)?")
```

**Guarded by:** a new permanent invariant — any letterhead value
(`contact_info`, `email`, `full_name`, `job_title`) whose brackets don't
balance fails the suite.

### Remaining limitation on this file — stated honestly

The first employment entry reads:

```
Spaar Environmental Technologies P LTD, Thrissur, Kerala Software Developer (2024 – 2025)
```

Company and role are merged, because the scrambled column order put them on
adjacent lines. The entry is complete and readable, but not in the ideal order.
**Multi-column PDF reading order is the one thing that cannot be fixed
reliably at source** — see the two rejected approaches above. 12 of the 21
items on this CV are flagged for review precisely because the classifier is
uncertain here, which is the review step doing its job.

---

## Earlier fixes, by bug class

Grouped rather than dated, because several were found in the same pass. Each
was originally prompted by one CV failing — which is exactly the pattern that
led to building `test_corpus.py`.

### Extraction

| Defect | Cause | Fix |
|---|---|---|
| Text-box content invisible (Westminster CV: 246 of 4,019 chars read) | python-docx `.paragraphs` doesn't see text boxes | Walk `word/document.xml` directly |
| Every paragraph doubled | `<mc:Fallback>` duplicates content for older Word versions | Strip `mc:Fallback` before walking |
| Welded words — `TEACHERNorthwood` | `<w:br/>` soft breaks ignored | Honour `w:br` as a newline, split on `.splitlines()` |
| Scanned PDFs produced garbage | No OCR | Reject with a clear message instead |

### Letterhead

| Defect | Cause | Fix |
|---|---|---|
| Year ranges matched as phone numbers — `(2012 - 2016)` split qualifications mid-entry | No digit-count validation | Reject 8-digit, no-`+` candidates; require ≥9 digits |
| `Job titles:` / `contact` stored as values | Template prompt labels treated as data | Plural-aware regex; skip when the value is empty |
| Name echoed into Qualifications | Letterhead line re-classified as body content | `_drop_name_echoes()` |
| Name detected as `FIFTH GRADE` out of `FIFTH GRADE TEACHER` | **Self-inflicted** — a prefix-before-job-keyword "salvage" rule I added | **Reverted**, with an explanatory comment in `_letterhead_segments` so it isn't retried |

### Classification

| Defect | Cause | Fix |
|---|---|---|
| Heading `ACADAMIC QUALIFCATIONS :` published as a qualification | Sub-heading retention applied to all sections | Scoped to `SUBGROUPED_SECTIONS = {"publications"}` |
| `(2024 – 2026)` with no role | Parser assumed date-first layout | Read whichever side of the date carries text |
| `26 (2024)` | `YEAR_RANGE_RE` had no 2-digit end year | Added, plus `DATE_REMNANT_RE` guard |
| Eleven leadership entries all in one section | Heading-based classification can't split one heading | Meaning-based routing (`routing.py`, handover §5a) |

### Generation

| Defect | Cause | Fix |
|---|---|---|
| Wrong image embedded — a banner, not the headshot | A 74×2218 sidebar strip beat a 114×177 headshot on area | Aspect ratio made a **hard filter**, not a soft penalty |
| Template instructions in the finished document | Boilerplate copied with the section | `_strip_instructional_boilerplate()` |
| Empty dangling headings | Heading emitted before knowing the section was empty | Remove heading *and* body when no items are approved |
| One giant merged blob | Source CV had no bullet glyphs | Sentence-boundary fallback + `_forces_new_item()` |
| Every line of a multi-line grant bulleted | Bullet applied per paragraph | Only the first line carries the bullet; continuations keep the indent |
| Biography read "X holds X" | First Qualifications item taken unconditionally | `_best_qualification()` validates against `QUALIFICATION_MARKERS` |

### The test harness itself

Two of its own checks were wrong and had to be narrowed:

- `BARE_DATE_LINE_RE` was too loose and flagged
  `(UNDP supported programme) Department of…` because the line opens with a
  bracket.
- The welded-words check flagged legitimate CamelCase — `RandomizedSearchCV`,
  `StreetLaw`.

Both narrowed. **A suite that cries wolf gets ignored**, so a false positive in
the harness is treated as seriously as a defect in the pipeline.
