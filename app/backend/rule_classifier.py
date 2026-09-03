"""Deterministic, non-AI classification: raw CV text -> structured items
mapped to the 20 MDX Faculty CV sections.

Used automatically when no Anthropic API key is configured (see
`classifier.classify`), and always available as a zero-cost, offline,
instant alternative to LLM classification -- no network call, no per-CV
spend, nothing leaves the machine.

Approach: locate section headings by matching against the same heading text
the official template uses (plus common synonyms), then take each bullet
item under a heading as one item, verbatim -- merging any wrapped
continuation lines (a PDF/DOCX line break mid-sentence, not a new bullet)
back into the item they belong to. This works well because HR's source CVs
are typically already organised close to the MDX template's own section
structure. It will not out-think an unlabelled, free-form CV the way an LLM
can -- that tradeoff is why every item still gets confidence < 0.90 and
goes through mandatory HR review, same as the AI path's medium/low-
confidence items.

Hard rule shared with the AI path: every item's `source_text` is a verbatim
substring of the CV text (guaranteed by construction here, since we only
ever trim or merge whitespace around real line content -- never rewrite it).
"""
import re
from collections import Counter
from datetime import date

import identifiers
import routing
from extraction import HEADER_FOOTER_MARKER
from formatting import _employment_line
from pathlib import Path
from typing import Any

BULLET_CHARS = "•●▪‣⁃�–—-"  # includes en/em dash: some PDF exporters
# (symbol/Wingdings bullet fonts mis-mapped by pypdf's text extraction) emit
# an en-dash codepoint for what is visually a bullet glyph. A leading dash
# at the very start of a trimmed line is not realistic as normal prose, so
# treating it as a bullet marker here is safe.
BULLET_START_RE = re.compile(r"^[ \t]*[" + BULLET_CHARS + r"]\s*")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Leading brackets are allowed on both sides of the "+": numbers are written
# "(04) 3753972" and "(+971) 55 529 8136". Matching from the first digit
# instead captures "04) 3753972" / "+971) 55 529 8136", with an unbalanced
# bracket left in the stored value.
PHONE_CANDIDATE_RE = re.compile(r"\(?\s*\+?\s*\(?\d[\d\s().\-]{7,}\d\)?")
MIN_PHONE_DIGITS = 9


def find_phone(text: str) -> re.Match | None:
    """A phone number in `text`, ignoring things that merely look like one.

    The permissive digits-and-punctuation pattern also matches a bracketed
    year range -- "(2012 - 2016)" is indistinguishable from a phone number by
    shape alone. That mattered in two places: date ranges were being picked up
    as a person's contact number, and, because a phone is treated as a hard
    "new entry starts here" signal, a qualification's wrapped date line was
    being split off from the degree it belongs to.

    Real numbers carry either an international prefix or at least nine
    digits; a YYYY-YYYY range has exactly eight and no '+'.
    """
    for match in PHONE_CANDIDATE_RE.finditer(text):
        candidate = match.group(0).strip()
        digits = sum(c.isdigit() for c in candidate)
        if candidate.startswith("+") or digits >= MIN_PHONE_DIGITS:
            return match
    return None
MONTH_WORD = (
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
)
# One end of a date range: a year, optionally preceded by a month name or a
# numeric month ("08/2020"). Without the numeric-month alternative, "08/" in
# "08/2020 - 12/2022" isn't part of the match at all -- it's just skipped --
# and the "12" of "12/2022" is then free to be misread by the caller as a
# 2-digit ABBREVIATED end year (the "2024-26" case), turning a real
# "12/2022" into a fabricated "2112" and leaving "/2022" behind as a bogus
# job title.
#
# The trailing "-MM" is the same fix for the OTHER common numeric-month
# convention ("2020-09"). Without it, "2023-09 - Current Assistant
# Professor..." matched group(1) as just "2023", leaving "-09" to be misread
# as a 2-digit end year (fabricating "2109" until _extract_employment_fields'
# own guard caught it) -- and because the real end marker "Current" was
# never reached, it was left stuck to the front of the job title instead of
# recognised as the open-ended marker it is.
_DATE_PART = rf"(?:{MONTH_WORD}\s+|\d{{1,2}}/)?\d{{4}}(?:-\d{{2}})?"
YEAR_RANGE_RE = re.compile(
    # Both ends must allow a leading month. CVs very often write
    # "June 2024 - July 2025", and a year-only pattern consumes just
    # "2024 - ", leaving "July 2025" to be mistaken for the job title.
    #
    # The 2-digit alternative on the right matters too: ranges are
    # abbreviated as "2024-26", and without it "26" is left behind the
    # same way.
    rf"({_DATE_PART})\s*(?:[-–—]|\bto\b)\s*"
    # "to present time", "to current date": CVs sometimes qualify "present"
    # with a trailing noun. Without matching it, "time"/"date" is left
    # dangling in front of the employer name on the role side. Bare "date"
    # is its own common phrasing too ("2023 to date") -- the connecting
    # "to" above is already consumed as the separator, so without this
    # alternative "date" itself was left dangling, glued onto the front of
    # whatever line followed ("...2023 to date Founder of a specialist...").
    rf"({_DATE_PART}|\d{{2}}|present(?:\s+time)?|current(?:\s+date)?|onwards?|date)?",
    re.IGNORECASE,
)
YEAR_IN_TEXT_RE = re.compile(r"\d{4}")
# Text left beside a date that is really just more date, not a role: a bare
# year fragment, or connective punctuation.
DATE_REMNANT_RE = re.compile(r"^[\s|,;:.\-–—()]*\d{0,4}[\s|,;:.\-–—()]*$")
# A whole line that carries only a date or date range, e.g. "2025-26",
# "2022 – 25", "| 2019-23". Such a line is always the wrapped tail of the
# entry above it, never the start of a new one.
DATE_ONLY_RE = re.compile(
    # A start year may itself carry a "-MM" month suffix ("2023-09") --
    # without \d{4}(?:-\d{2})? as one atomic unit, "2023-09 - Current" was
    # read as year "2023", separator, end-year "09", leaving " - Current"
    # unconsumed and the whole line unrecognised as a bare date at all. It
    # then fell through to ordinary employment-field parsing, which
    # fabricated a fake entry titled "Current" with a garbled end year.
    r"^[\s|,()\-–—]*\d{4}(?:-\d{2})?\s*"
    r"(?:[-–—]\s*(?:\d{4}(?:-\d{2})?|\d{2}|present|current|onwards?))?"
    r"[\s|,()\-–—.]*$",
    re.IGNORECASE,
)

# section_key -> extra heading synonyms beyond the official template text
# (pulled live from config.SECTIONS below). These match ONLY when a line is
# made up of just the synonym itself -- see _find_heading_key -- so a
# generic word like "education" or "awards" can safely be listed here
# without falsely matching when it merely appears inside a body sentence.
SYNONYM_HEADINGS: dict[str, list[str]] = {
    # "PROFILE" and "OBJECTIVE" head the summary paragraph on most résumés.
    # Without them the paragraph is orphaned and BIOGRAPHY prints "Information
    # not provided" on a CV that opens with a written professional summary --
    # which is exactly the biography the template asks for.
    "biography": [
        "PROFILE SUMMARY", "PERSONAL STATEMENT", "PROFESSIONAL SUMMARY", "SUMMARY",
        "PROFILE", "CAREER PROFILE", "CAREER SUMMARY", "EXECUTIVE SUMMARY",
        "ABOUT ME", "ABOUT", "OBJECTIVE", "CAREER OBJECTIVE", "PROFESSIONAL PROFILE",
        "PERSONAL PROFILE", "SUMMARY OF QUALIFICATIONS", "RESUME OBJECTIVE",
    ],
    "qualifications": [
        "EDUCATION", "CERTIFICATIONS", "CERTIFICATIONS AND TRAININGS",
        "EDUCATION AND QUALIFICATIONS", "ACADEMIC QUALIFICATIONS",
        "ACADEMIC CREDENTIALS", "CERTIFICATES", "CERTIFICATE",
    ],
    "associations": [
        "PROFESSIONAL MEMBERSHIPS", "MEMBERSHIPS AND FELLOWSHIPS", "ASSOCIATIONS",
        "PUBLIC SERVICE", "COMMUNITY SERVICE", "VOLUNTEER WORK", "VOLUNTEERING",
    ],
    "present_employment": ["PRESENT EMPLOYMENT", "CURRENT EMPLOYMENT", "CURRENT POSITION"],
    "previous_employment": ["PREVIOUS EMPLOYMENT", "PREVIOUS EXPERIENCE"],
    "teaching_learning": [
        "TEACHING RESPONSIBILITIES", "TEACHING EXPERIENCE", "TEACHING",
        "TEACHING AND SUPERVISION",
    ],
    "committees": ["COMMITTEES AND ADVISORY ROLES", "COMMITTEE MEMBERSHIPS", "COMMITTEES",
                    "ADVISORY ROLES"],
    "academic_leadership": ["ACADEMIC LEADERSHIP", "LEADERSHIP ROLES", "LEADERSHIP"],
    "knowledge_exchange": [
        "KNOWLEDGE EXCHANGE", "PUBLIC ENGAGEMENT", "INVITED TALKS",
        "PROFESSIONAL PRACTICE", "OUTREACH",
    ],
    "awards": ["AWARDS", "HONOURS", "ACHIEVEMENTS", "AWARDS AND HONOURS", "SCHOLARSHIPS"],
    "centres_of_excellence": ["CENTRES OF EXCELLENCE", "RESEARCH LAB", "RESEARCH CENTRES"],
    "grants": [
        "GRANTS AND FUNDING", "RESEARCH GRANTS", "FUNDING", "RESEARCH PROJECTS",
        "RESEARCH GRANTS AND PROJECTS", "CONSULTANCY PROJECTS", "PROJECTS",
    ],
    "editorial_roles": ["EDITORIAL ROLES", "REVIEWER ROLES", "EDITORIAL AND REVIEW ROLES"],
    "publications": [
        "RESEARCH PUBLICATIONS", "PUBLICATIONS",
        # sub-headings that appear *inside* a publications block: treating each
        # as a publications heading keeps the items filed correctly instead of
        # letting an unrecognised sub-heading silently end the section.
        "PEER-REVIEWED JOURNALS, BOOK CHAPTERS, AND BOOKS", "PEER-REVIEWED PUBLICATIONS",
        "JOURNAL ARTICLES", "BOOK CHAPTERS", "BOOKS",
        "ACADEMIC BLOGS, REPORTS, AND MEDIA PUBLICATIONS", "MEDIA PUBLICATIONS",
        "UPCOMING PEER-REVIEWED PUBLICATIONS", "FORTHCOMING PUBLICATIONS",
        # Conference papers are research outputs and belong with the rest of
        # the publication record (as the reference MDX CV files them), not
        # under Knowledge Exchange, which covers events run and talks given.
        "CONFERENCE PRESENTATIONS", "CONFERENCES", "PRESENTATIONS",
        "CONFERENCE PAPERS",
        # A creative or design academic's research record is exhibited and
        # commissioned work, not journal articles -- "Select Practice
        # Outputs" occupies exactly the structural position "Select Research
        # Publications" would on a text-based CV. Left unrecognised, its
        # entire content (real exhibition and client work) silently fell
        # into whatever section preceded it in the source -- one CV's design
        # portfolio was published as "Awards and Recognitions".
        "SELECT PRACTICE OUTPUTS", "PRACTICE OUTPUTS", "CREATIVE OUTPUTS",
        "SELECTED CREATIVE WORKS", "PORTFOLIO OF WORK", "SELECTED PROJECTS AND OUTPUTS",
        "EXHIBITED PRACTICE OUTPUTS", "SELECTED COMMERCIAL AND BRAND PRACTICE",
    ],
    "profiles_links": ["PROFILES AND LINKS", "ONLINE PROFILES", "PROFILES", "IDENTIFIERS"],
    # Not one of the 20 official MDX sections, but common and specific
    # enough on a CV to deserve a real, labelled section of its own in the
    # generated document rather than the generic unmapped note -- HR
    # explicitly asked that skills and language content read as "Skills" /
    # "Language Proficiency", not as an appendix.
    "skills": [
        "SKILLS", "KEY SKILLS", "CORE SKILLS", "TECHNICAL SKILLS", "IT SKILLS",
        "SOFT SKILLS", "PERSONAL SKILLS", "OTHER SKILLS", "TECHNICAL PROFICIENCY",
        "DIGITAL AND TECHNICAL SKILLS", "DIGITAL SKILLS", "AREAS OF EXPERTISE",
        "IT PROFICIENCY",
    ],
    "language_proficiency": [
        "LANGUAGES", "LANGUAGES KNOWN", "LANGUAGE PROFICIENCY", "LANGUAGE SKILLS",
    ],
    # generic catch-all heading that needs per-item present/previous splitting
    "_generic_employment": [
        "EMPLOYMENT HISTORY", "WORK EXPERIENCE", "CAREER HISTORY", "PROFESSIONAL EXPERIENCE",
        "ADDITIONAL WORK EXPERIENCE", "EMPLOYMENT", "PROFESSIONAL BACKGROUND", "EXPERIENCE",
    ],
    # recognised as a real section boundary, but has no home anywhere in the
    # 20 fixed MDX sections -- discarded rather than fabricated a place for
    # it. Crucially this still STOPS the heading from leaking into whatever
    # section came before it, which is the actual bug this fixes: without
    # this, a heading like "DECLARATION" or "INTERESTS" that has no mapping
    # is invisible to the parser, so everything under it -- hobbies, a
    # signature block, certifications, even the person's name repeated --
    # keeps getting appended to the LAST section that WAS recognised,
    # however unrelated (e.g. everything after "EDUCATION" ends up filed
    # as "qualifications" all the way to the end of the document).
    "_ignored": [
        "DECLARATION", "INTERESTS", "HOBBIES", "REFERENCES", "PERSONAL DETAILS",
        "PERSONAL PARTICULARS", "PERSONAL INFORMATION", "DETAILS",
        "CONTACT", "MY CONTACT", "CONTACT INFORMATION", "CONTACT DETAILS", "ADDRESS",
        # Common on a CV but not one of the 20 MDX sections, so per §8 their
        # content belongs in the unmapped note rather than being force-fit
        # into whichever real section happened to sit above them. (Skills
        # and language content have their own real sections above instead.)
        "PROFESSIONAL DEVELOPMENT",
        "PROFESSIONAL LINKS AND ADDITIONAL INFORMATION", "ADDITIONAL INFORMATION",
        "TRAINING AND DEVELOPMENT", "TRAINING AND CERTIFICATIONS",
        # Visa/passport/miscellaneous catch-alls. These matter more now that
        # Skills and Language Proficiency are real sections that render
        # directly in the document: without recognising this heading,
        # passport and visa details bled straight into whichever of those
        # two sections happened to sit above it in the source.
        "OTHER INFORMATION", "MISCELLANEOUS", "ADDITIONAL DETAILS",
        "VISA STATUS", "PASSPORT DETAILS",
    ],
}

TITLE_KEYWORDS = [
    "professor", "lecturer", "dean", "director", "head of", "chair",
    "coordinator", "researcher", "fellow", "instructor",
    # non-academic roles, so job-title detection isn't blind on a generic CV
    "engineer", "manager", "specialist", "administrator", "analyst",
    "consultant", "technician", "executive", "officer", "associate",
    "supervisor", "developer", "designer", "architect", "support",
    "teacher", "tutor", "nurse", "assistant", "intern", "clerk", "advisor",
]

# A plain "kw in text.lower()" substring check false-positives badly --
# "intern" (meant to catch the job title "Intern") matches inside
# "international", turning an ordinary duty sentence ("...at national and
# international conferences...") into a job-title candidate. Word-boundary
# matching is the general fix, used everywhere TITLE_KEYWORDS is checked
# against a candidate line rather than the bare substring test.
TITLE_KEYWORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in TITLE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def _has_title_keyword(text: str) -> bool:
    return bool(TITLE_KEYWORD_RE.search(text))

# Organisation and place words. A person is never called "Northwood
# Elementary School", but such a line passes every structural test a name
# does -- capitalised, no digits, two or three words -- so it has to be
# excluded by vocabulary.
ORG_KEYWORDS = (
    "school", "university", "college", "institute", "academy", "centre",
    "center", "department", "faculty", "hospital", "clinic", "laboratory",
    "foundation", "association", "society", "council", "ministry", "company",
    "corporation", "limited", "ltd", "inc", "llc", "consultancy", "group",
    "services", "solutions", "resume", "curriculum vitae",
)

# Lines that are universally personal-detail/boilerplate noise with no home
# in any of the 20 MDX sections, regardless of which section they end up
# grouped under (a heading mismatch or a scrambled PDF layout can land them
# almost anywhere -- see classify_rule_based's post-filter). Matched as a
# prefix on the normalised line, not a heading: these show up as ordinary
# body content, never as their own standalone heading.
JUNK_LINE_PREFIXES = (
    "DATE OF BIRTH", "BLOOD GROUP", "NATIONALITY", "MARITAL STATUS", "GENDER",
    "VISA STATUS", "PASSPORT NO", "PASSPORT NUMBER", "DRIVING LICENSE",
    "DRIVING LICENCE", "LANGUAGES KNOWN", "I HEREBY DECLARE",
    "DATE / PLACE OF BIRTH", "PLACE OF BIRTH",
)

# Advertising the résumé template's publisher embeds in the file itself.
# It is addressed to the candidate, not written by them, so it is not their
# information and does not belong in the unmapped note either -- one CV
# published "Hire one of our certified professional resume writers from
# $49.95 per resume" into MDX's Previous Employment section, and the vendor's
# order page into Professional Profiles.
VENDOR_BOILERPLATE_RE = re.compile(
    r"\bdear job seeker\b"
    r"|\bresume writ(?:er|ing) (?:service|from)\b"
    r"|\bcertified professional resume writer"
    r"|\bhire one of our\b"
    r"|\bstruggling to write your (?:resume|cv)\b"
    r"|\byou'?re in good company\b"
    r"|\bper resume\b"
    r"|\bresumethatworks\b|\bmoney-zine\b|\bresume\.io\b|\bzety\.com\b"
    r"|\bnovoresume\b|\bmyperfectresume\b|\bresumegenius\b|\bresumewriterdirect\b"
    r"|\bdownload (?:this|our) (?:template|resume)\b"
    r"|\b(?:template|resume) (?:designed|created) by\b"
    r"|\bfrom resume genius\b"
    r"|\binstall the font files\b"
    r"|\bfree resume builder\b|\bfree cover letter\b"
    r"|\bhow to write a (?:resume|cv|cover letter)\b"
    r"|\b(?:resume|cv|cover letter) (?:samples|examples) by industry\b"
    r"|\bcover letter builder\b"
    r"|\byou'?re also going to need a cover letter\b"
    r"|utm_source=word_doc|utm_medium=",
    re.IGNORECASE,
)


# Generous: a real academic title legitimately runs long ("Senior Lecturer,
# International and Comparative Education, and Head of Centre for Academic
# Success, Middlesex University, Dubai Campus"). Prose is rejected by the
# sentence-punctuation test below, which is the reliable discriminator --
# a tight length cap only ends up rejecting genuine titles.
MAX_JOB_TITLE_LEN = 170


def _looks_like_job_title(text: str) -> bool:
    """Shape guard for a job-title candidate. Containing a title keyword is
    not enough on its own: words like "supervisor" and "associate" also turn
    up mid-sentence in ordinary CV prose (a thesis line naming "Supervisor
    Prof. X", say), and without this the letterhead's Job title field ends
    up holding a fragment of a sentence."""
    stripped = text.strip()
    if not stripped or len(stripped) > MAX_JOB_TITLE_LEN:
        return False
    # A bare label is not a title. CVs written to the MDX template itself
    # carry the literal prompt "Job titles:" as a line, which otherwise gets
    # stored as the person's job title.
    if stripped.endswith(":") or _find_heading_key(stripped) is not None:
        return False
    # Real titles are noun phrases; sentence-like punctuation means prose.
    # Checked both mid-string ("...sentence. Another...") and at the very
    # end ("...topics.") -- a duty line that happens to be a single
    # sentence has no internal ". " to catch, only a full stop as its very
    # last character, which the mid-string-only check let straight through.
    return not re.search(r"[.;?!](?:\s|$)", stripped)


def _is_junk_line(text: str) -> bool:
    normalized = _normalize_heading(text)
    if any(normalized.startswith(p) for p in JUNK_LINE_PREFIXES):
        return True
    if VENDOR_BOILERPLATE_RE.search(text):
        return True
    if UNFILLED_PLACEHOLDER_LINE_RE.search(text):
        return True
    if CITY_STATE_ZIP_RE.match(text.strip()):
        return True
    if GLUED_ICON_TEXT_RE.match(text.strip()):
        return True
    stripped = text.strip()
    if BARE_DOB_RE.match(stripped):
        return True
    if BARE_COUNTRY_RE.match(stripped):
        return True
    if BARE_CITY_COUNTRY_RE.match(stripped):
        return True
    if BARE_EMPLOYMENT_TYPE_RE.match(stripped):
        return True
    # A letter-spaced heading fragment _merge_split_letter_spaced_headings
    # could not resolve to any known heading (so it was left as the
    # original, unmerged line) is still not real content -- genuine CV
    # content is never written one letter at a time. Left unfiltered, it
    # becomes its own bare, ugly bullet under whatever section it landed in
    # ("S T R E N G T H A N D") rather than being silently absorbed the way
    # a resolved heading fragment already is.
    if _is_whole_line_letter_spaced(stripped):
        return True
    if _is_concatenated_headings_line(stripped):
        return True
    return bool(HYPERLINK_TARGET_LINE_RE.match(stripped))


def _is_concatenated_headings_line(text: str) -> bool:
    """A line made up of two or more official section headings glued
    together with no separator at all. Happens when the source CV is
    itself written in the MDX template and several consecutive sections
    were left completely empty -- whatever produced the source file merged
    their headings onto one physical line ("CONTRIBUTION TO MDX CENTRES OF
    EXCELLENCE/RESEARCH LAB RESEARCH GRANTS, FUNDING AND CONSULTANCY
    PROJECTS EDITORIAL BOARD MEMBERSHIPS..."). Left unfiltered, this reads
    as ordinary content and gets glued onto whatever real item happened to
    precede it -- three empty sections' worth of boilerplate silently
    dressed up as one bullet under Awards. Recognised by peeling a known
    heading off the front, repeatedly, until nothing or an unrecognised
    remainder is left; a single recognised heading is left alone (that is
    just an ordinary, real heading, handled elsewhere)."""
    remaining = _normalize_heading(text)
    matches = 0
    while remaining:
        matched_phrase = next(
            (p for p in _HEADINGS_BY_LENGTH_DESC if remaining.startswith(p)),
            None,
        )
        if not matched_phrase:
            return False
        remaining = remaining[len(matched_phrase):].strip()
        matches += 1
    return matches >= 2


# "142 Your Address Blvd." -- a candidate filled in their real name, skills
# and job history but never replaced the template's own placeholder address
# line. Narrower than `is_placeholder_template` (which asks "is this WHOLE
# document still blank"): this catches a single unfilled field inside an
# otherwise genuinely completed CV.
UNFILLED_PLACEHOLDER_LINE_RE = re.compile(
    r"\byour address\b|\byour city\b|\byour state\b|\byour zip\b|\byour phone\b"
    r"|\byour email\b|\byour company\b",
    re.IGNORECASE,
)
# A bare "City, ST, ZIP" line -- the second half of a two-line address block
# whose first line already gave it away as an unfilled placeholder
# ("142 Your Address Blvd."). A standalone 5-digit ZIP code is the
# discriminator: a job entry's location ("Pasadena, CA") never carries one,
# so requiring it keeps this from ever catching a genuine employer location.
CITY_STATE_ZIP_RE = re.compile(r"^[A-Za-z .]{2,40},\s*[A-Z]{2},?\s*\d{5}(-\d{4})?$")

# A decorative text box in a designed template (a small icon/badge graphic)
# can render as a single nonsense "word" once extracted as plain text --
# "educationCV" was a lowercase run immediately followed by an uppercase
# run, with no space, sitting in a centred text box using a custom display
# font. Narrow on purpose: a lowercase block of 4+ letters running straight
# into an uppercase block of 2+ with nothing else on the line. A genuine
# camelCase brand name standing alone on its own line ("PayPal", "iPhone")
# is rare enough, and the cost of missing one skill/tool mention is low
# enough, that this is a safe trade against publishing "educationCV" as a
# bullet under Previous Employment.
GLUED_ICON_TEXT_RE = re.compile(r"^[a-z]{4,}[A-Z]{2,}$")

# A line that is nothing but a Word hyperlink's target address, synthesised
# by extraction.py's _hyperlink_targets for a link whose visible text names
# the platform but never spells out the URL ("MDX Studios 2025 Premiere
# Celebrates..." with the address only in the relationship, not the text).
# extraction.py always appends every such line at the very end of the
# document's text -- after the real body, after headers and footers -- so
# whichever section heading happens to be LAST in the CV silently inherits
# every hyperlink in the entire document as if it were that section's own
# content. On one real CV this put five unrelated press-article links (from
# a "Media coverage" bullet under Knowledge Exchange, nowhere near Profiles)
# into "Professional Profiles, Links, and Identifiers" -- not because they
# were actually links to the person's own profiles, but purely because that
# heading came last.
#
# identifiers.find_identifiers already exists specifically to scan the whole
# document for exactly these addresses, with the position-aware and
# exclusion logic this ad-hoc physical placement has none of (see that
# module's docstring). Junking the line here removes it from ordinary
# heading-based body classification without removing it from identifiers'
# own scan, which reads the untouched original text separately -- so the
# link is still found, just only through the mechanism built to judge it
# correctly instead of by an accident of where it landed on the page.
HYPERLINK_TARGET_LINE_RE = re.compile(r"^(?:.*:\s*)?https?://\S+$", re.IGNORECASE)

# A personal-details field that has lost its own label. On a scrambled
# text-box layout the label ("Date of Birth:") and its value can land in
# different reading-order positions entirely -- the label gets caught by
# JUNK_LINE_PREFIXES where it sits, but the bare value surfaces elsewhere as
# its own stray line/bullet with nothing to identify it. Anchored to the
# WHOLE line so a genuine date range or a country mentioned in real prose is
# never touched -- only a line that is nothing else.
#
# A bare "City, ST" pattern was tried here too and reverted: it also matches
# "Branson University, NV" and "Rutgers University New Brunswick, NJ" --
# an institution/employer name immediately followed by its state, which is
# ordinary, legitimate content in an Education or Employment entry on
# nearly every US-style CV. Confirmed against the full corpus (it broke two
# real files by deleting the university name out of a qualification entry).
# There is no shape-only way to tell "just an address fragment" apart from
# "an institution name that happens to end in a state abbreviation", so this
# is left alone rather than shipped unsafe.
BARE_DOB_RE = re.compile(r"^\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)\d{2}$")
BARE_COUNTRY_RE = re.compile(
    r"^(?:USA|U\.S\.A\.?|United States(?: of America)?"
    r"|UK|U\.K\.?|United Kingdom"
    r"|UAE|U\.A\.E\.?|United Arab Emirates"
    r"|India|Canada|Australia|Pakistan)$",
    re.IGNORECASE,
)
BARE_EMPLOYMENT_TYPE_RE = re.compile(
    r"^(?:Full|Part|Full[\s-]?[Tt]ime|Part[\s-]?[Tt]ime"
    r"|Contract|Freelance|Permanent|Temporary|Full-Time|Part-Time)$"
)


# A line that is nothing but a contact detail. On a text-box or two-column
# layout the contact block often extracts AFTER the first section heading,
# so a bare phone number becomes an entry under Previous Employment -- one
# CV published "(123) 456-7890" as a job. These values are already picked up
# by the letterhead extractor, which searches the whole document, so nothing
# is lost by keeping them out of section bodies.
CONTACT_LABEL_ONLY = {
    "LINKEDIN", "EMAIL", "PHONE", "MOBILE", "TEL", "TELEPHONE", "CONTACT",
    "ADDRESS", "WEBSITE", "PORTFOLIO", "GITHUB",
}


def _is_bare_contact_line(text: str) -> bool:
    # Two passes are needed, not one: "(+971) 55 529 8136 |" strips its
    # trailing "|" but leaves the space that sat before it, so a phone-only
    # line with a separator glyph on the end ("... 8136 |") never matched --
    # the leftover trailing space broke the exact-equality check below and
    # the phone number survived as a fragment stuck to whatever content
    # followed it in the source.
    stripped = text.strip().strip("|·•,;").strip()
    if not stripped:
        return False
    if _normalize_heading(stripped) in CONTACT_LABEL_ONLY:
        return True
    match = EMAIL_RE.search(stripped)
    if match and match.group(0) == stripped:
        return True
    match = find_phone(stripped)
    if match and match.group(0).strip() == stripped:
        return True
    return False

# Common resume section labels that are NOT known MDX headings/synonyms but
# must still never be mistaken for a person's name (the failure mode this
# guards against: a preamble line like "Core Competencies" or "Key Skills"
# sitting above the CV's first recognised heading, picked as "the name"
# just because it came first).
NAME_BLOCKLIST = {
    "CORE COMPETENCIES", "KEY SKILLS", "SKILLS", "COMPETENCIES", "PROFILE",
    "SUMMARY", "OBJECTIVE", "CAREER OBJECTIVE", "CONTACT", "CONTACT INFORMATION",
    "PERSONAL DETAILS", "PERSONAL INFORMATION", "DECLARATION", "REFERENCES",
    "ACHIEVEMENTS", "INTERESTS", "HOBBIES", "LANGUAGES KNOWN", "ADDRESS",
    "IT SKILLS", "TECHNICAL SKILLS", "CURRICULUM VITAE", "RESUME", "CV",
}

# [^\W\d_] is "any Unicode letter": names carry accents, and an ASCII-only
# class silently rejects them. "César Cabal" failed this test, so the name
# was taken from a later shape-match instead -- an employer, "Santa Clara
# Elementary". Anyone whose name is not spelled in plain ASCII was affected.
#
# Each token also allows an internal hyphen or apostrophe ("Al-Mansoori",
# "O'Brien", "D'Souza") -- a hyphenated or apostrophe'd surname is ordinary,
# common on this system's own CVs, and the previous pattern rejected the
# WHOLE name over it, silently falling back to a worse-guessed name (once,
# from the person's own email address) instead.
#
# A trailing period is also allowed on any token, for a middle initial
# ("Seada A. Kassie") -- without it the whole line failed to match at all
# (the period sits right after "A" with no token able to consume it), so
# the real name was never even offered as a candidate, and full_name came
# up completely empty rather than just lower-confidence.
_NAME_TOKEN = r"[^\W\d_]+(?:['\-][^\W\d_]+)*\.?"
NAME_LINE_RE = re.compile(
    rf"^{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{1,2}}$", re.UNICODE
)
HONORIFIC_RE = re.compile(
    r"^(?:DR|PROF|PROFESSOR|MR|MRS|MS|MISS|SIR|DAME)\.?\s+", re.IGNORECASE
)


def _looks_like_person_name(line: str) -> bool:
    """A line is a plausible name only if it survives every check below --
    this is the guard that stops a section label like "Core Competencies"
    from being mistaken for a name just because it appears early in the
    document (see NAME_BLOCKLIST docstring)."""
    text = line.strip()
    if not text or len(text) > 60:
        return False
    if _find_heading_key(text) is not None:
        return False
    if _normalize_heading(text) in NAME_BLOCKLIST:
        return False
    if EMAIL_RE.search(text) or find_phone(text):
        return False
    if any(ch.isdigit() for ch in text) or ":" in text or "@" in text:
        return False
    # An occupation is not a name. Résumé templates often print the target
    # role in the same prominent position a name would occupy ("FIRST GRADE
    # TEACHER"), where it passes every shape test a real name would.
    lowered = text.lower()
    if _has_title_keyword(lowered):
        return False
    if any(kw in lowered for kw in ORG_KEYWORDS):
        return False
    # An honorific doesn't count toward the word budget -- "Dr Camilla Hadi
    # Chaudhary" is a perfectly ordinary name, while an un-prefixed 5-word
    # ALL-CAPS line is far more likely an employer ("HYATT REGENCY CREEK
    # HEIGHTS DUBAI"). Stripping the title first lets the budget stay tight
    # enough to reject the latter without rejecting the former.
    text = HONORIFIC_RE.sub("", text, count=1).strip()
    if not text or not NAME_LINE_RE.match(text):
        return False
    # A real name is conventionally either ALL CAPS or Title Case on a CV --
    # this is what rejects a generic mixed-case phrase like "Decision
    # making" (a soft-skill list entry, all lowercase after its first
    # letter) from being mistaken for a name just because it sits near a
    # found email/phone and is grammatically shaped like one.
    words = text.split()
    is_all_caps = text == text.upper()
    is_title_case = all(w[:1].isupper() for w in words)
    return is_all_caps or is_title_case


# Leading qualifier words an academic CV puts in front of a section name
# ("SELECTED PUBLICATIONS", "KEY RESEARCH PROJECTS"). Stripped only as a
# second-chance match in _find_heading_key, never in the first pass, so an
# official template heading always wins on its exact text first.
QUALIFIER_PREFIX_RE = re.compile(
    r"^(?:SELECTED|SELECT|KEY|MAIN|MAJOR|RECENT|ADDITIONAL|OTHER|RELEVANT|CORE|NOTABLE)\s+"
)
# A trailing year or year range on a heading, e.g. "... PUBLICATIONS 2026-27"
# (parentheses are already gone by the time _normalize_heading is done).
TRAILING_YEARS_RE = re.compile(r"[\s,/-]*\d{2,4}\s*[-–—]?\s*\d{0,4}\s*$")


def _normalize_heading(line: str) -> str:
    line = line.upper()
    line = line.replace("–", "-").replace("—", "-")
    line = re.sub(r"[^\w\s,/-]", "", line)
    return " ".join(line.split())


def _official_headings() -> dict[str, str]:
    """normalized official template heading text -> section key, pulled
    live from config.SECTIONS so this always matches the real template
    (including its known typo, e.g. 'EXERNAL') rather than a hand-copied
    guess that could drift out of sync."""
    from config import SECTIONS

    return {
        _normalize_heading(s["heading_text"]): s["key"]
        for s in SECTIONS
        if s["heading_text"] and s["key"] != "full_name"
    }


_OFFICIAL_HEADINGS = _official_headings()
# Longest phrase first, so greedy prefix-matching in
# _is_concatenated_headings_line never stops at a shorter heading that
# happens to also be a prefix of a longer one.
_HEADINGS_BY_LENGTH_DESC = sorted(_OFFICIAL_HEADINGS, key=len, reverse=True)
_SYNONYM_LOOKUP: list[tuple[str, str]] = [
    (phrase, key) for key, phrases in SYNONYM_HEADINGS.items() for phrase in phrases
]

# HR-taught heading -> section mappings, loaded from storage at process
# startup and updated live as HR adds them from the review screen -- no code
# change, no restart. Keyed by normalised heading text so "Volunteer Work"
# and "volunteer work:" resolve the same way. A plain module-level dict is
# enough here: this process is single-process and synchronous (see
# pipeline.py), the same assumption ANTHROPIC_API_KEY and every other
# load-once module constant in this file already relies on.
_CUSTOM_HEADINGS: dict[str, str] = {}


def register_custom_heading(heading_text: str, section_key: str) -> None:
    """Teach the classifier one more heading, effective immediately for
    every CV processed after this call -- including ones already in
    progress, since classification re-reads this dict on every upload
    rather than caching it."""
    _CUSTOM_HEADINGS[_normalize_heading(heading_text)] = section_key


def load_custom_headings(mappings: list[dict]) -> None:
    """Replace the live set with what storage currently holds. Called once
    at startup, and again after any add/delete so the in-memory table never
    drifts from what a reviewer sees listed."""
    _CUSTOM_HEADINGS.clear()
    for m in mappings:
        _CUSTOM_HEADINGS[_normalize_heading(m["heading_text"])] = m["section_key"]


SUMMARY_OPENER_RE = re.compile(
    r"^(?:SUMMARY|PROFILE|OBJECTIVE|ABOUT|CAREER SUMMARY|CAREER OBJECTIVE"
    r"|CAREER PROFILE|PERSONAL PROFILE|PERSONAL STATEMENT|EXECUTIVE SUMMARY)\b"
)

MIN_BIOGRAPHY_ITEM_WORDS = 10


def _is_biography_prose(text: str) -> bool:
    """A written sentence, not a bare skill or trait fragment.

    A CV's summary heading commonly introduces one real paragraph followed by
    a bulleted skills list under the same heading -- "Highly talented
    laboratory technologist with huge experience in..." versus "Fluent in
    English." Both are short-ish lines by CV standards, but only the first
    reads as prose describing the person; the second is a bare trait with no
    home in the MDX template. Word count is the distinguishing signal: a real
    biography sentence describing someone's background runs long, a skill
    bullet does not.
    """
    words = text.split()
    if len(words) < MIN_BIOGRAPHY_ITEM_WORDS:
        return False
    # A contact/address block can accidentally clear the word-count bar --
    # odd PDF spacing splits a phone number into several "words" ("890
    # -555 -0401"), and an address line is easily 8-10 tokens once the
    # country name and a separator glyph are counted. Neither is a
    # sentence about the person, so reject anything phone/email-shaped or
    # dominated by uppercase letters (an address/contact line is written in
    # caps; real prose is not) before trusting the word count alone.
    if find_phone(text) or EMAIL_RE.search(text):
        return False
    letters = [c for c in text if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) >= 0.6:
        return False
    return True

HEADING_MAX_WORDS = 10
FUZZY_HEADING_RATIO = 0.86


def _looks_like_heading_line(raw: str, normalized: str) -> bool:
    """Whether a line is *structurally* a heading, before asking what it says.

    This is what makes loose phrase matching safe. Matching a synonym
    anywhere inside any line would fire on ordinary prose ("...Higher
    Education Academy..."), which is why matching used to be exact-only --
    and why a real heading like "SUMMARY OF SKILLS AND QUALIFICATIONS:" or
    "WORK EXPERIENCE / EMPLOYMENT HISTORY:" matched nothing at all.

    Checking shape first separates the two cases: headings are short, are
    capitalised or colon-terminated, and don't read as sentences.
    """
    text = raw.strip()
    if not text or len(text) > 100:
        return False
    if len(normalized.split()) > HEADING_MAX_WORDS:
        return False
    if text.rstrip().endswith((".", "!", "?", ",", ";")):
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    if text.rstrip().endswith(":"):
        return True
    if sum(1 for c in letters if c.isupper()) / len(letters) >= 0.7:
        return True
    return False


def _fuzzy_heading_key(normalized: str) -> str | None:
    """Nearest known heading, tolerating misspellings.

    Headings are typed by hand and often wrong -- one real CV reads
    "ACADAMIC QUALIFCATIONS", two typos in two words. An exact lookup
    discards the section entirely and dumps its content into whatever
    section was open before it.
    """
    from difflib import SequenceMatcher

    best_key, best_ratio = None, 0.0
    for phrase, key in list(_OFFICIAL_HEADINGS.items()) + _SYNONYM_LOOKUP:
        ratio = SequenceMatcher(None, normalized, phrase).ratio()
        if ratio > best_ratio:
            best_key, best_ratio = key, ratio
    return best_key if best_ratio >= FUZZY_HEADING_RATIO else None


def is_authoritative_heading(line: str) -> bool:
    """Whether the CV states this section outright, using the template's own
    heading text. Content under such a heading is never re-filed by wording:
    the document has already said where it belongs."""
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return False
    normalized = _normalize_heading(stripped)
    return any(
        normalized == phrase
        or (normalized.startswith(phrase) and len(normalized) <= len(phrase) + 3)
        for phrase in _OFFICIAL_HEADINGS
    )


def _find_heading_key(line: str) -> str | None:
    """The MDX section a heading line refers to, or None if it isn't a heading.

    Matching runs strictest-first: an exact official heading, then an exact
    synonym, then -- only for lines that *look* like headings -- a contained
    synonym phrase, then a fuzzy match for typos.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return None
    normalized = _normalize_heading(stripped)

    for phrase, key in _OFFICIAL_HEADINGS.items():
        if normalized == phrase or (
            normalized.startswith(phrase) and len(normalized) <= len(phrase) + 3
        ):
            return key

    # HR-taught mappings (see custom_headings.py) take priority over every
    # built-in guess below: they are an explicit human decision about a
    # heading the built-in rules don't recognise, made once from the review
    # screen, and apply to every CV uploaded afterward.
    if normalized in _CUSTOM_HEADINGS:
        return _CUSTOM_HEADINGS[normalized]

    # Try the raw heading, then again with leading qualifier words removed.
    # Academic CVs almost always write "SELECTED PUBLICATIONS", "KEY RESEARCH
    # PROJECTS", "MAIN CONFERENCE PRESENTATIONS" rather than the bare noun --
    # without this, an exact-match-only synonym lookup misses every one of
    # them and dumps the entire section into whichever heading matched last.
    # Try the heading as-is, without a leading qualifier, and without a
    # trailing year range -- CVs label groups like "SELECTED UPCOMING
    # PEER-REVIEWED PUBLICATIONS (2026-27)", and an exact-match lookup would
    # otherwise miss it and emit the heading itself as a content line.
    bases = {normalized, QUALIFIER_PREFIX_RE.sub("", normalized, count=1).strip()}
    candidates = set(bases) | {TRAILING_YEARS_RE.sub("", b).strip() for b in bases}
    for candidate in candidates:
        if not candidate:
            continue
        for phrase, key in _SYNONYM_LOOKUP:
            if candidate == phrase:
                return key

    # Everything below is gated on the line looking like a heading, which is
    # what keeps loose matching from firing inside ordinary body text.
    if not _looks_like_heading_line(stripped, normalized):
        return None

    # A heading that OPENS with a narrative-summary word is a profile
    # paragraph, whatever else it names afterward. "SUMMARY OF SKILLS AND
    # QUALIFICATIONS" mechanically contains both "SUMMARY" and the longer
    # "QUALIFICATIONS" -- and the longest-match rule just below would file
    # the profile paragraph beneath it as a degree list, because
    # "QUALIFICATIONS" is the longer string. But the heading is naming what
    # KIND of section this is (a summary), not what facts follow; here
    # "qualifications" means general suitability for the role, not academic
    # credentials. Checked first so it can't lose to a longer but less
    # relevant phrase found later in the same heading.
    if SUMMARY_OPENER_RE.match(normalized):
        return "biography"

    # A heading that contains a known section name among other words:
    # "SUMMARY OF SKILLS AND QUALIFICATIONS", "WORK EXPERIENCE / EMPLOYMENT
    # HISTORY". Longest phrase wins so a compound heading resolves to its
    # most specific match rather than an incidental short word.
    best_key, best_len = None, 0
    for phrase, key in _SYNONYM_LOOKUP:
        if len(phrase) > best_len and re.search(rf"\b{re.escape(phrase)}\b", normalized):
            best_key, best_len = key, len(phrase)
    for phrase, key in _OFFICIAL_HEADINGS.items():
        if len(phrase) > best_len and re.search(rf"\b{re.escape(phrase)}\b", normalized):
            best_key, best_len = key, len(phrase)
    if best_key:
        return best_key

    return _fuzzy_heading_key(normalized)


SENTENCE_END_RE = re.compile(r"[.!?]\s*$")
ENTRY_END_YEAR_RE = re.compile(
    # A trailing ")" is common ("(2023 - present)") and was previously fatal
    # to this match: the pattern had to reach end-of-string right after the
    # year/marker, with no allowance for the closing bracket the date was
    # written inside. That silently disabled this entry-boundary signal for
    # every CV that parenthesises its dates, welding each new entry onto
    # the tail of the one before it.
    #
    # The leading (?<!\d) matters too: without it, a plain monetary amount
    # ending "...00" ("AED 15,000") had its last two digits mistaken for a
    # 2-digit year, turning an ordinary detail line into a bogus new entry.
    r"(?<!\d)(?:\d{4}|\d{2})\s*(?:[-–—]\s*(?:\d{4}|\d{2}|present|current|onwards))?\s*\)?\s*$",
    re.IGNORECASE,
)
PRESENT_ROLE_RE = re.compile(r"\b(?:onwards?|present|current(?:ly)?|to date)\b", re.IGNORECASE)
TRAILING_MONTH_RE = re.compile(
    r"[\s,]*(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?"
    r"|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s*$",
    re.IGNORECASE,
)
# A short capitalised label followed by a colon and content, e.g.
# "Consultant: ...", "Research Associate: ...", "Key responsibilities: ...".
# Ordinary prose almost never opens a line this way, so it is a dependable
# "new entry starts here" marker.
ENTRY_LABEL_RE = re.compile(r"^[A-Z][A-Za-z]{1,20}(?:[ /&-][A-Za-z.]{1,20}){0,3}:\s*\S")
DATE_ANCHOR_RE = re.compile(
    r"^[ \t]*(?:\d{4}|[A-Za-z]{3,9}['’]?\d{2,4})\s*[-–—]"
)


# A bare "TITLE, MM/YYYY - MM/YYYY" job-title line with its own date range
# folded in (as opposed to the title-alone-then-employer-with-date layout
# _employment_body_entries already handles) and no bullet glyph in front of
# it. Nothing else in _forces_new_item catches this shape -- it isn't a
# name/email/phone, doesn't open with the date, isn't a bare short-caps
# label (the date's digits rule that check out) -- so without this it reads
# as more of the previous job's last responsibility bullet and welds a new
# job's title onto the tail of an unrelated sentence.
def _is_title_with_date_line(text: str) -> bool:
    match = YEAR_RANGE_RE.search(text)
    if not match:
        return False
    head = text[: match.start()].strip(" ,-–—")
    if not head or not _looks_like_job_title(head):
        return False
    return _has_title_keyword(head.lower())


def _forces_new_item(line: str) -> bool:
    """Hard boundary signals that are trustworthy even with zero bullet
    markers to go on: a line that IS a person's name, contains an email,
    contains a phone number, or opens with a date range essentially can
    never be the tail end of the previous sentence -- so treat it as a
    fresh item regardless of what the prior line ended with. This is what
    stops a name/email/phone that appears mid-document (a PDF layout
    artifact) from being swallowed into an unrelated job description."""
    stripped = line.strip()
    # A line holding nothing but a date is the tail of the entry above it --
    # a wrapped date column, not a new entry. Without this exception the
    # date-anchor rule below fires on it and strands "2025-26" as its own
    # bullet in the finished CV, orphaned from the role it belongs to.
    if DATE_ONLY_RE.match(stripped):
        return False
    return bool(
        _looks_like_person_name(line)
        or EMAIL_RE.search(line)
        or find_phone(line)
        or DATE_ANCHOR_RE.match(stripped)
        or _opens_with_degree(stripped)
        or _is_short_caps_label(stripped)
        or _is_title_with_date_line(stripped)
    )


# A standalone short ALL-CAPS line with no sentence punctuation reads as an
# informal sub-heading a CV author invented ("CONTRIBUATIONS", a misspelling
# of "CONTRIBUTIONS") -- structurally a heading, but not one that resolves to
# any known MDX section or synonym, so `_split_into_sections` never catches
# it and it silently welds onto the end of whatever item came before it
# ("...reporting patient reports. CONTRIBUATIONS"). Forcing a boundary here
# doesn't drop the line -- it just stops it, and whatever follows, from being
# absorbed into an unrelated entry; the line still becomes its own item and
# is fully traceable, or is picked up by the unmapped-content safety net if
# nothing better claims it.
SHORT_CAPS_LABEL_RE = re.compile(r"^[A-Z][A-Z '&/-]{1,40}$")


def _is_short_caps_label(line: str) -> bool:
    words = line.split()
    if not (1 <= len(words) <= 4):
        return False
    if any(c.isdigit() for c in line):
        return False
    return bool(SHORT_CAPS_LABEL_RE.match(line))


# A responsibility line as CVs actually write them: "Answering phone calls",
# "Maintaining an internal contact list", "Overseeing a team of six".
GERUND_START_RE = re.compile(r"^[A-Z][a-z]{2,}ing\b")
LIST_INTRO_RE = re.compile(r":\s*$")

# A short "Title - Provider" or "Course - Type" line, one per certification
# or short course, as a bullet-free CERTIFICATIONS block commonly writes them
# ("React.Js Course - Udemy", "Google Flutter - Internship"). Excludes a
# digit so a genuine "Role - 2010 - 2013" date-range entry, already handled
# elsewhere, is never double-claimed by this check.
# A period is allowed mid-word (product names like "React.Js", "Node.js",
# "ASP.NET" are common in this exact list pattern); only a SENTENCE-ending
# period, comma, colon or semicolon rules a line out.
SHORT_DASH_ENTRY_RE = re.compile(r"^[^-–—:;]{2,40}[-–—][^-–—:;]{2,40}$")
MAX_DASH_ENTRY_WORDS = 8


# A single-line "Languages Known: English, Hindi and Arabic" fact, of the
# kind that commonly sits inside an otherwise-junk "Personal Details" block
# alongside date of birth, nationality and driving licence. Unlike the
# section-heading synonyms, this matches mid-block, on the line itself.
LANGUAGE_LIST_LINE_RE = re.compile(
    r"^languages?(?:\s+known)?\s*:\s*[A-Za-z].{2,80}$", re.IGNORECASE
)

# A short "Name : Level" or "Name (Level)" line, one per language or skill,
# as a bullet-free LANGUAGES/SKILLS block commonly writes them ("English :
# Proficient", "Bulgarian (Fluent)", "French (B2, working proficiency)").
# The parenthetical form allows a digit or comma inside the parentheses (a
# CEFR level, "B2", commonly sits right beside the descriptor) but the
# parenthesis must still OPEN on a letter -- a bare "(2020-2022)" date range
# starts on a digit and is never mistaken for a proficiency level. The
# colon form stays letters-only throughout: unlike the parenthetical form,
# nothing about it structurally rules out a "Role : 2020-2022" date line.
SHORT_LABELLED_ENTRY_RE = re.compile(
    r"^[A-Za-z][A-Za-z .]{0,24}(?:\s*:\s*[A-Za-z][A-Za-z /]{0,24}"
    r"|\s*\([A-Za-z][A-Za-z0-9 /,]{0,40}\))$"
)
MAX_LABELLED_ENTRY_WORDS = 5


def _is_short_labelled_entry(line: str) -> bool:
    text = line.strip()
    if not (1 < len(text.split()) <= MAX_LABELLED_ENTRY_WORDS):
        return False
    return bool(SHORT_LABELLED_ENTRY_RE.match(text))


def _is_short_dash_entry(line: str) -> bool:
    text = line.strip()
    if any(c.isdigit() for c in text):
        return False
    if text.rstrip().endswith((".", ",", ":", ";")):
        return False
    if not (1 < len(text.split()) <= MAX_DASH_ENTRY_WORDS):
        return False
    return bool(SHORT_DASH_ENTRY_RE.match(text))


def _starts_list_item(line: str, previous: str | None) -> bool:
    """A new entry in a list that lost its bullet glyphs.

    Some documents -- especially résumés converted from PDF -- carry no bullet
    characters at all. Sentence-boundary grouping then merges an entire
    employment history into one runaway paragraph, because none of the lines
    end in a full stop. One résumé produced a single bullet holding three
    different jobs and eighteen responsibilities, with two job titles and
    their date ranges buried inside it.

    The reliable signal is the shape CVs use for these lists: an introductory
    line ending in a colon, followed by lines each opening with a gerund. Both
    halves are required to start the chain, so an ordinary sentence that
    happens to wrap before an "-ing" word is not split.
    """
    if previous is None:
        return False
    text = line.strip()
    previous = previous.strip()
    if GERUND_START_RE.match(text):
        return bool(LIST_INTRO_RE.search(previous) or GERUND_START_RE.match(previous))
    # The list also has to END. A capitalised line that is not another gerund
    # closes it -- otherwise the next job's title, employer and dates weld
    # onto the tail of the last responsibility, and §5's requirement that
    # career progression appear as separate entries is lost. A wrapped
    # continuation of a responsibility starts lowercase, so it is unaffected.
    return bool(GERUND_START_RE.match(previous) and text[:1].isupper())


def _opens_with_degree(line: str) -> bool:
    """A line beginning with a degree name is a new qualification.

    §5 of the conversion spec is explicit that multiple degrees must not
    collapse into one line. Without this, a qualifications block whose
    entries carry no bullet glyph merges the lot: one CV produced a single
    item reading "Master of Arts ... Bulgaria (1998) Postgraduate Certificate
    in Education (PGCE) ...", which then reported the wrong year and the
    wrong country because both were read out of the degree that came after.
    """
    if not DEGREE_RE.match(line):
        return False
    # A degree name at the start of a line is not enough on its own --
    # "Masters students were supervised through to submission" opens with one
    # and is a sentence about teaching. A real qualification entry also
    # states when it was awarded or who awarded it.
    lowered = line.casefold()
    return bool(
        CALENDAR_YEAR_RE.search(line)
        or any(keyword in lowered for keyword in QUALIFICATION_AWARDER_KEYWORDS)
    )


QUALIFICATION_AWARDER_KEYWORDS = (
    "university", "college", "institute", "academy", "polytechnic",
    "school of", "expected", "in progress", "awarded", "ongoing",
)


MAX_AFFILIATION_WORDS = 12


def _is_bare_affiliation_line(text: str) -> bool:
    """A line that is nothing but an organisation and where it is.

    Deliberately narrow. It must name an organisation, be short enough to be
    a name rather than a description, carry no dates of its own, and end
    without sentence punctuation -- so a bulleted responsibility that happens
    to mention a university, or a sentence about one, is not swept up.
    """
    stripped = text.strip()
    if BULLET_START_RE.match(stripped):
        return False
    if not stripped or len(stripped.split()) > MAX_AFFILIATION_WORDS:
        return False
    if SENTENCE_END_RE.search(stripped) or CALENDAR_YEAR_RE.search(stripped):
        return False
    if EMAIL_RE.search(stripped) or find_phone(stripped):
        return False
    lowered = stripped.casefold()
    if not any(keyword in lowered for keyword in ORG_KEYWORDS):
        return False
    # A heading that happens to contain an organisation word is structure.
    return _find_heading_key(stripped) is None


# A category label opening a skills list line, glued directly onto its own
# content with no separator: "ROBOTICS ROS 2 (Jazzy), ros2_control...",
# "CAD & FABRICATION SolidWorks, Onshape...". Scoped to firing only within a
# section already identified as "skills" -- unlike a general heading
# detector, misfiring here can only split one skills bullet into two, never
# misattribute content to the wrong top-level section, so it can safely be
# far more aggressive than anything tried for section-boundary detection.
#
# Requires the leading ALL-CAPS run to be substantial (>=6 letters total, or
# 2+ words) specifically so it doesn't fire on an ordinary short acronym
# opening a genuine list item ("GPU acceleration...", "SQL and NoSQL...") --
# those are content, not a new category.
SKILL_CATEGORY_TOKEN = r"(?:[A-Z][A-Z0-9/]*|&)"
SKILL_CATEGORY_RE = re.compile(
    rf"^({SKILL_CATEGORY_TOKEN}(?:\s+{SKILL_CATEGORY_TOKEN}){{0,4}})\s+(?=\S)"
)
MIN_SKILL_CATEGORY_LETTERS = 6

# A full job-duty sentence ("Coordinated and streamlined hospital
# services..."): opens with a Title-Case gerund/past-tense verb and ends in
# real sentence punctuation. Shape-based rather than a fixed verb list --
# it only needs to recognise "this is a sentence", not classify which duty
# it describes; routing.py's ACTION_VERB_RE (a fixed vocabulary) is the one
# that decides where a re-routed item like this ends up.
JOB_DUTY_SENTENCE_RE = re.compile(r"^[A-Z][a-z]+(?:ing|ed)\b.*[.!?]$")

# The tail half of a scrambled employment-entry header ("Didier Sachs / Los
# Santos, CA / 2008-2011") when it has landed on its own physical line,
# split away from the bare job title above it ("SALESMAN") by the
# skills-section line-per-item rule below. That rule must NOT also force a
# break here, or the title and its employer/location/date end up as two
# separate items and _reclassify_resume_crosstalk's employment-header match
# (which needs both halves on one line) never fires -- silently turning a
# job entry back into loose skills-section fragments instead of fixing it.
EMPLOYER_LOCATION_YEAR_TAIL_RE = re.compile(
    r"^[A-Z][\w .&'-]*?\s*/\s*[A-Za-z .]+,\s*[A-Z]{2}\s*/\s*(?:19|20)\d{2}"
)


def _starts_skill_category(line: str) -> bool:
    match = SKILL_CATEGORY_RE.match(line.strip())
    if not match:
        return False
    label = match.group(1)
    tokens = label.split()
    letters = sum(c.isalpha() for c in label)
    return letters >= MIN_SKILL_CATEGORY_LETTERS or len(tokens) >= 2


def _group_into_items(body_lines: list[str], section_key: str | None = None) -> list[str]:
    """Merge wrapped continuation lines back into the item they belong to.

    Two strategies, chosen per-section based on what evidence is actually
    present in the text:
      * If ANY line in the section has a visible bullet marker, a new
        bullet always starts a new item (the common, reliable case).
      * If NONE do -- some PDF exports lose bullet glyphs entirely for a
        given block of text, which would otherwise merge an entire
        section into one runaway item -- fall back to sentence-boundary
        grouping: a new item starts after the previous line ended with
        real sentence punctuation, or wherever _forces_new_item fires.
    Either way, _forces_new_item can always force a boundary, since some
    signals (a name, an email, a date range) are reliable regardless of
    which strategy is active.
    """
    stripped = [l for l in body_lines if l.strip()]
    has_bullets = any(BULLET_START_RE.match(l) for l in stripped if l != SEGMENT_BREAK)

    items: list[str] = []
    current: list[str] = []
    for line in stripped:
        if line == SEGMENT_BREAK:
            # A gap in the source. Whatever follows cannot be a continuation
            # of what came before, because they are not adjacent in the CV.
            if current:
                items.append(" ".join(current))
                current = []
            continue
        text = line.strip()
        if has_bullets:
            starts_new = bool(BULLET_START_RE.match(line)) or not current
        else:
            starts_new = (
                not current
                or bool(SENTENCE_END_RE.search(current[-1]))
            )
        if bool(current) and (
            # An entry that ends with its date column terminates that entry,
            # in BOTH modes. A mixed block -- unbulleted entry headers with
            # bulleted detail underneath, which is how most CVs lay out
            # employment and funded projects -- otherwise glues each new
            # header onto the tail of the previous entry's last bullet.
            (
                ENTRY_END_YEAR_RE.search(current[-1])
                # ...unless what follows is the organisation that entry
                # belongs to. CVs lay a degree or a role out as a header line
                # ending in its dates, with the awarding university or the
                # employer on the line beneath. Treating the date as the end
                # of the entry detaches every degree from its university and
                # every role from its employer -- the exact relationship §4
                # of the conversion spec requires be kept intact.
                and not _is_bare_affiliation_line(text)
            )
            # A "Role: ..." / "Project Title: ..." label likewise always
            # opens a new entry rather than continuing the previous one.
            or ENTRY_LABEL_RE.match(text)
            # A sub-heading kept inside its own section ("Academic blogs,
            # reports, and media publications") must stand alone too --
            # merged into the citation above it, the group divider is lost
            # and every entry below inherits the wrong sub-group.
            or _find_heading_key(text) is not None
            # A line that opens with a heading-shaped run of 3+ consecutive
            # ALL-CAPS words is what a heading glued mid-paragraph onto
            # unrelated content looks like once _split_embedded_heading_runs
            # has separated it out (see that function's docstring) -- it
            # must start its own item here or the split is undone.
            or STARTS_WITH_HEADING_RUN_RE.match(text)
            # And the reverse: once a sub-heading line HAS become its own
            # `current` entry, it must never accept a continuation either.
            # Under sentence-boundary grouping (no bullet glyphs in this
            # section), a heading with no trailing full stop -- "Exhibited
            # practice outputs" -- doesn't trip the sentence-end check, so
            # the very next content line was welding onto it: "Exhibited
            # practice outputs Piet Mondrian and Wassily Kandinsky:...".
            or _find_heading_key(current[-1]) is not None
            # And the same symmetry for the OTHER forced-boundary signals: a
            # line that was itself a bare contact fragment ("(+971) 55 529
            # 8136 |", stranded there by a scrambled two-column PDF's reading
            # order) must not accept a continuation either. Without this, the
            # phone number becomes the head of an item and the real content
            # after it -- an unrelated certification -- welds onto the front
            # of it: "(+971) 55 529 8136 | Core Digital Marketing Academy...".
            or EMAIL_RE.search(current[-1]) or find_phone(current[-1])
            or _forces_new_item(line)
            or _starts_list_item(text, current[-1])
            # A bare (non-bulleted) job-title line interrupting a run of
            # bulleted duties must still start a new entry. Real CVs
            # commonly mix the two: an unbulleted "Job Title" / "Employer,
            # dates" header pair, with bulleted duties underneath -- and
            # without this, an unbulleted title line right after the
            # PREVIOUS entry's last bullet (with no date column of its own
            # for ENTRY_END_YEAR_RE above to catch) welds onto that bullet's
            # tail instead of opening its own entry. Scoped to bulleted mode
            # specifically: there, only a new bullet is normally allowed to
            # start an item, so an unbulleted line shaped like a title is
            # never itself a continuation of one.
            or (
                has_bullets and not BULLET_START_RE.match(line)
                and _has_title_keyword(text) and _looks_like_job_title(text)
            )
            # Both neighbours must match, not just this line -- a one-off
            # sentence that happens to contain a single dash ("Led the
            # Q3 rollout - on time and under budget.") must not split on
            # its own; only a genuine RUN of short dash-entries (a
            # certifications block with no bullet glyphs) should.
            or (_is_short_dash_entry(text) and _is_short_dash_entry(current[-1]))
            or (_is_short_labelled_entry(text) and _is_short_labelled_entry(current[-1]))
            or (section_key == "skills" and _starts_skill_category(text))
            # A skills list with no bullet glyphs at all commonly extracts as
            # one physical line per skill ("Analytics", "Requirement
            # Gathering", "Market Research"). Under the sentence-boundary
            # fallback above, none of those lines end in punctuation, so
            # without this they all weld into one runaway item -- "Analytics
            # Requirement Gathering Project Management..." -- that reads as
            # gibberish. Scoped to "skills" with no bullets detected only:
            # the blast radius is one section splitting into more (correct)
            # items, never a misattribution to the wrong section. A line
            # that opens lowercase is left alone, since that shape is a
            # wrapped continuation of the previous skill, not a new one.
            or (
                section_key in ("skills", "awards") and not has_bullets
                # Not "isupper()" specifically -- a real new entry can also
                # open with a digit ("100+ international awards..."), which
                # isn't upper OR lower case. Only an actual lowercase start
                # is the wrapped-continuation shape this must stay silent on.
                and not text[:1].islower()
                and not EMPLOYER_LOCATION_YEAR_TAIL_RE.match(text)
            )
            # Same shape, same fix, for committees and academic leadership --
            # but these two sections also legitimately contain a SHORT title
            # line with no date at all ("MDX Wellness Centre - Contributor")
            # immediately followed by ITS OWN description sentence. That
            # description also opens uppercase, so the plain rule above would
            # wrongly split a title from its own description. Gated on
            # current[-1] already being substantial (a real, complete entry
            # is never this short) -- a short title-only line stays silent,
            # letting the ordinary sentence-boundary fallback correctly weld
            # its description onto it instead.
            or (
                section_key in ("committees", "academic_leadership") and not has_bullets
                and not text[:1].islower()
                and not EMPLOYER_LOCATION_YEAR_TAIL_RE.match(text)
                and len(current[-1]) > 50
            )
            # A "LANGUAGES" heading with no bullet glyphs extracts its real
            # content as one short, unpunctuated line ("English Malayalam").
            # Under sentence-boundary grouping that line never ends in
            # punctuation, so without this the very next line -- however
            # unrelated -- welds onto it: a two-column template's job-duty
            # text box, whose reading-order position happens to land right
            # after the language list, produced "English Malayalam
            # Coordinated and streamlined hospital services...". A line
            # shaped like a full descriptive sentence (opens with a
            # Title-Case gerund/past-tense verb, ends in real punctuation)
            # is never itself part of a language list, so it always starts
            # a new item here regardless of what the previous line ended in.
            or (section_key == "language_proficiency" and JOB_DUTY_SENTENCE_RE.match(text))
            # A two-column CV's sidebar (Languages, Citizenship) commonly
            # interleaves with the main column's Experience text in reading
            # order -- a short, genuinely-a-language line ("French (B2,
            # working proficiency)") sits directly beside the START of an
            # unrelated job entry from the other column ("Risk Advisory
            # Group, London -- Deputy Head of..."), with neither a bullet
            # nor a full stop between them for the checks above to catch.
            # Unlike JOB_DUTY_SENTENCE_RE (a positive match on ONE specific
            # shape, a duty sentence), this is a purely negative signal:
            # once the entry ABOVE already looks exactly like a real,
            # complete language entry, anything that does NOT ALSO look
            # like one is never a continuation of it, whatever shape that
            # something else turns out to be. The item that starts here
            # still lands under language_proficiency, same as before this
            # rule -- it is no longer welded onto real language content and
            # unreadable, which is the immediate loss this fixes; getting
            # it filed under the RIGHT section is a separate step.
            or (
                section_key == "language_proficiency"
                and _is_short_labelled_entry(current[-1])
                and not _is_short_labelled_entry(text)
            )
        ):
            starts_new = True

        if starts_new:
            if current:
                items.append(" ".join(current))
            current = [BULLET_START_RE.sub("", line).strip()]
        else:
            current.append(text)
    if current:
        items.append(" ".join(current))

    cleaned = [" ".join(item.split()) for item in items if item.strip()]

    # Final sweep: fold any item that turned out to be nothing but a date
    # back into the entry beside it. Layout-heavy documents (text boxes,
    # multi-column PDFs) emit a bare "2012" as its own run of text, and on
    # its own it is meaningless -- it belongs to the qualification or role
    # it sits beside.
    #
    # An OPEN-ENDED date stranded at the very start (nothing above it yet)
    # is held and attached FORWARD instead of dropped: a two-column layout
    # commonly puts the date column ahead of the title/employer column for
    # the section's first entry ("2023-09 - Current" / "Assistant
    # Professor, Middlesex University..."), and that first entry is very
    # often the person's CURRENT role -- silently losing its date range,
    # and with it the only signal that marks it as ongoing, is worse than
    # the old "drop it" behaviour was trying to avoid.
    #
    # Deliberately narrow to the open-ended case (present/current/onwards):
    # a bare closed year like "2012" carries no such signal and is far more
    # likely orphaned qualification-year debris than a role's start date --
    # attaching it forward unconditionally glued a stray "2012" onto a
    # completely unrelated item several lines later on a real CV, which
    # the verbatim guard then rightly discarded as non-adjacent, fabricated
    # text. A closed bare date at the very start is still just dropped, as
    # before.
    merged: list[str] = []
    pending_lead_date: str | None = None
    for item in cleaned:
        if DATE_ONLY_RE.match(item):
            if merged:
                merged[-1] = f"{merged[-1]} {item}".strip()
            elif PRESENT_ROLE_RE.search(item):
                pending_lead_date = (
                    f"{pending_lead_date} {item}".strip() if pending_lead_date else item
                )
            continue
        if pending_lead_date:
            item = f"{pending_lead_date} {item}".strip()
            pending_lead_date = None
        merged.append(item)
    return merged


PIPE_SPLIT_RE = re.compile(r"\s*[|•·]\s*")
# Marks a discontinuity inside one section's body: the same section heading
# appeared twice in the document, so the lines either side of this are not
# neighbours in the source and must not be merged into one item. Chosen to be
# a string no CV can contain.
SEGMENT_BREAK = "\x00SEGMENT_BREAK\x00"

MIN_RUNNING_HEADER_REPEATS = 3
# Sections whose own sub-headings carry meaning worth keeping in the body.
SUBGROUPED_SECTIONS = {"publications"}


def _find_running_headers(lines: list[str]) -> set[str]:
    """Lines repeated verbatim enough times to be a page header/footer that
    the PDF repeats on every page, rather than real CV content.

    These matter twice over: left in place they inject the same line into
    the middle of several unrelated sections (pure noise in the output),
    and when the header is a contact strip -- very common on academic CVs,
    e.g. "Dr Jane Doe | j.doe@uni.ac.uk | +44..." -- it is simultaneously
    the single most reliable source of the letterhead fields. So we strip
    them from the body and mine them separately (see _extract_letterhead).
    """
    counts = Counter(" ".join(l.split()) for l in lines if len(l.strip()) > 12)
    return {
        t for t, n in counts.items()
        if n >= MIN_RUNNING_HEADER_REPEATS and not _repeats_as_content(t)
    }


def _repeats_as_content(text: str) -> bool:
    """True when a repeated line repeats because it is genuinely used several
    times, not because the page furniture reprints it.

    A CV written entirely at one institution names that institution under
    every degree and every post: "Middlesex University Dubai, United Arab
    Emirates" appeared four times on one CV and was stripped as a header,
    which detached each degree from the university that awarded it and each
    role from its employer -- exactly the relationship §4 of the conversion
    spec says must be preserved.

    Page furniture is a name, a contact strip or a page marker. An
    organisation with a location is a fact about the entry it sits under.
    """
    if EMAIL_RE.search(text) or find_phone(text):
        return False  # a contact strip really is a running header
    if _find_heading_key(text):
        return False  # a heading repeated across pages is page furniture
    lowered = text.casefold()
    if not any(keyword in lowered for keyword in ORG_KEYWORDS):
        return False
    # A bare organisation name repeated as a footer is still furniture; one
    # written with its location is the "Organisation, Country" form the MDX
    # template asks for, and belongs to the entry above it.
    return "," in text


# A PDF two-column or side-by-side layout can place a section heading and
# the first piece of its own body content on what extraction sees as ONE
# line -- "EXPERIENCE  MARKETING MANAGER, 01/2023 - 11/2025" or
# "AREAS OF EXPERTISE  • Performance marketing" (no line break exists in
# the extracted text where a person reading the page would see one). Left
# alone, the merged line fails every heading check (it is far longer than
# the heading phrase alone) and silently welds an entire section's worth of
# content onto whatever section was already open -- one real CV lost its
# whole Skills list and Experience section into Biography this way.
# Splitting at the same seam a real line break would have left -- a run of
# 2+ spaces, or a bullet glyph -- and heading-testing only the left-hand
# side recovers both the heading and the content that follows it.
# Bullet glyphs only (not BULLET_CHARS' dashes -- a hyphen inside an
# ordinary heading-shaped line, e.g. "CO-ORDINATOR", is not a seam).
_GLUED_HEADING_SEAM_RE = re.compile(r"\s{2,}|[•●▪‣⁃�·]\s*")


def _split_glued_heading(line: str) -> tuple[str, str, str] | None:
    """(heading_text, section_key, remainder) if `line` is a heading glued to
    its own first line of content with no break between them; else None.

    Only the first seam is tried, and only the left-hand side is required to
    resolve to a known heading -- an ordinary sentence that happens to
    contain a wide gap or a bullet character deep inside its wording is
    never mistaken for one, because `_find_heading_key` is exactly as strict
    on this shorter left-hand text as it already is everywhere else.
    """
    match = _GLUED_HEADING_SEAM_RE.search(line)
    if not match:
        return None
    head = line[: match.start()].strip()
    rest = line[match.end() :].strip()
    if not head or not rest:
        return None
    key = _find_heading_key(head)
    if not key:
        return None
    return head, key, rest


WRAPPED_HEADING_LOOKAHEAD = 2


def _merge_wrapped_headings(lines: list[str]) -> list[str]:
    """Reunite a heading whose words wrapped onto separate physical lines --
    a narrow sidebar column commonly breaks "PERSONAL INFORMATION" into
    "PERSONAL" then "INFORMATION" two lines later, each an ordinary single
    word with no letter-spacing at all. _find_heading_key only ever looks
    at one line at a time, so a heading split this way is invisible to it,
    and everything beneath it silently joins whatever section was still
    open above -- one CV's Language Proficiency section absorbed a wrapped
    "PERSONAL INFORMATION" heading's own age/nationality/visa details this
    way, because the actual language list was the last real content before
    the wrap.

    Tries joining the current heading-shaped line with the next one, then
    the next two, accepting a merge only when the combined text resolves to
    a real known heading via _exact_heading_key -- the same "only accept a
    match against actual vocabulary" guard used everywhere else in this
    module. Two ordinary short lines that simply happen to sit next to each
    other (a bullet-free skills list, say) essentially never combine into
    anything _exact_heading_key recognises, so they are left untouched.
    """
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        normalized = _normalize_heading(stripped)
        if not _looks_like_heading_line(stripped, normalized):
            out.append(line)
            i += 1
            continue
        merged_at = None
        for extra in range(1, WRAPPED_HEADING_LOOKAHEAD + 1):
            if i + extra >= n:
                break
            candidates = [stripped] + [lines[i + k].strip() for k in range(1, extra + 1)]
            if not all(
                _looks_like_heading_line(c, _normalize_heading(c)) for c in candidates
            ):
                break
            key = _exact_heading_key(_normalize_heading(" ".join(candidates)))
            if key is not None:
                out.append(" ".join(candidates))
                merged_at = i + extra
                break
        if merged_at is not None:
            i = merged_at + 1
            continue
        out.append(line)
        i += 1
    return out


# A heading a template letter-spaces for visual effect ("C A R E E R",
# "A C A D E M I C") extracts as one line per word, each word a run of
# single-letter tokens. Mirrors extraction.py's own garble-check threshold:
# short of this length a run reads as noise, not a deliberately spaced word.
_LETTER_SPACED_LINE_RUN_MIN = 6
LETTER_SPACED_HEADING_LOOKAHEAD = 6


def _is_whole_line_letter_spaced(line: str) -> bool:
    tokens = line.split()
    return len(tokens) >= _LETTER_SPACED_LINE_RUN_MIN and all(
        len(t) == 1 and t.isalpha() for t in tokens
    )


def _collapse_letter_spaced(line: str) -> str:
    return "".join(line.split())


def _is_name_shaped_letter_spacing(line: str) -> bool:
    """Like _is_whole_line_letter_spaced, but tolerant of a trailing
    decorative punctuation mark ("D E V A P R A B H A A ." for a
    letter-spaced name followed by a full stop) that the heading check
    correctly treats as disqualifying -- a heading is never punctuated like
    that, but a name-plate flourish routinely is."""
    tokens = line.split()
    while tokens and len(tokens[-1]) == 1 and not tokens[-1].isalpha():
        tokens = tokens[:-1]
    return len(tokens) >= _LETTER_SPACED_LINE_RUN_MIN and all(
        len(t) == 1 and t.isalpha() for t in tokens
    )


def _looks_like_collapsed_name(text: str) -> bool:
    """A relaxed shape check used only for a candidate recovered by
    collapsing letter-spacing (see _collapse_letter_spaced_name). Unlike an
    ordinary candidate, this one is by construction always a single run
    with no recoverable word boundaries -- NAME_LINE_RE's multi-word
    requirement (the guard _looks_like_person_name relies on) can never be
    satisfied by it and isn't a meaningful signal here. Still guarded by
    the same heading/blocklist checks that protect the ordinary path."""
    if not text or len(text) > 40 or not text.isalpha():
        return False
    if _find_heading_key(text) is not None:
        return False
    if _normalize_heading(text) in NAME_BLOCKLIST:
        return False
    return text.isupper()


def _collapse_letter_spaced_name(line: str) -> str | None:
    """Collapse a letter-spaced name-plate line ("D E V A P R A B H A A .")
    to its plain form ("DEVAPRABHAA"), or None if the line isn't shaped like
    one. Unlike heading collapsing there's no known-word list to recover
    multi-word boundaries from, so this only ever produces a single run --
    good enough to make an otherwise name-shaped line visible to the
    ordinary shape-based candidate check, not a full name parser."""
    if not _is_name_shaped_letter_spacing(line):
        return None
    tokens = line.split()
    while tokens and len(tokens[-1]) == 1 and not tokens[-1].isalpha():
        tokens = tokens[:-1]
    return "".join(tokens)


def _exact_heading_key(normalized: str) -> str | None:
    """Same lookup _find_heading_key starts with, minus every looser
    fallback after it (qualifier-stripping, substring-contains, fuzzy
    typo-tolerance). Used where trying many candidate strings in a loop
    makes the looser stages actively dangerous rather than just unhelpful:
    fuzzy matching at 0.86 similarity is safe against one real heading
    line, but run across every possible split point of a squashed-together
    word, it will happily match splits that land it at the WRONG boundary
    ("PE RSONALDETAILS" fuzzy-matched something before the real "PERSONAL
    DETAILS" split further along was ever tried).
    """
    if normalized in _OFFICIAL_HEADINGS:
        return _OFFICIAL_HEADINGS[normalized]
    if normalized in _CUSTOM_HEADINGS:
        return _CUSTOM_HEADINGS[normalized]
    for phrase, key in _SYNONYM_LOOKUP:
        if normalized == phrase:
            return key
    return None


def _split_letter_spaced_words(collapsed: str) -> str | None:
    """A collapsed run with no recoverable word-boundary spacing might still
    BE exactly two known words squashed together -- "PERSONALDETAILS" for
    "PERSONAL DETAILS", where the letter-spacing gap between every letter is
    the same whether it's inside a word or between two words, so no larger
    gap ever marked where one word ends and the next begins. Tries
    inserting one space at each position and keeps the first split whose
    two-word form resolves to a real known heading -- checked with
    _exact_heading_key, not the full _find_heading_key, so a run that isn't
    really two heading words squashed together never matches anything by
    chance (see that function's docstring for why).
    """
    for i in range(2, len(collapsed) - 1):
        candidate = f"{collapsed[:i]} {collapsed[i:]}"
        if _exact_heading_key(candidate) is not None:
            return candidate
    return None


def _merge_split_letter_spaced_headings(lines: list[str]) -> list[str]:
    """Reunite a two-word letter-spaced heading whose words were separated
    onto different lines by the document's own layout, with unrelated
    content sitting between them in extraction order.

    A résumé built on a layout TABLE can place each word of a stacked
    heading in its own cell, sharing a row with a fragment of nearby body
    text in the adjacent cell -- "CAREER" paired with the first half of the
    objective paragraph in one row, "OBJECTIVE" paired with the second half
    in the next. Walking the document in raw paragraph order (extraction.py
    has to: templates route real content through text boxes and table cells
    just as often as the body) then interleaves "CAREER" / paragraph-half-1
    / "OBJECTIVE" / paragraph-half-2 -- so neither the heading nor the
    paragraph beneath it is ever recognisable as a whole.

    Only merges when the traditional constraint holds regardless: the two
    collapsed words, joined with a space, must resolve to a real known
    heading. Two unrelated single-word letter-spaced headings that simply
    happen to sit within a few lines of each other (a short "SKILLS"
    section followed shortly by "LANGUAGES") do not combine into anything
    _find_heading_key recognises, so they are left exactly as they were.
    A collapsed word that already resolves on its own ("S K I L L S" ->
    "SKILLS") is never held back waiting for a partner that isn't coming.
    """
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not _is_whole_line_letter_spaced(line):
            out.append(line)
            i += 1
            continue
        collapsed = _collapse_letter_spaced(line)
        if _find_heading_key(collapsed) is not None:
            out.append(collapsed)
            i += 1
            continue
        split = _split_letter_spaced_words(collapsed)
        if split is not None:
            out.append(split)
            i += 1
            continue
        merged_at = None
        for j in range(i + 1, min(n, i + 1 + LETTER_SPACED_HEADING_LOOKAHEAD)):
            if not _is_whole_line_letter_spaced(lines[j]):
                continue
            combined = f"{collapsed} {_collapse_letter_spaced(lines[j])}"
            if _find_heading_key(combined) is not None:
                out.append(combined)
                out.extend(lines[i + 1 : j])
                merged_at = j
                break
        if merged_at is not None:
            i = merged_at + 1
            continue
        # Neither the line alone nor any combination with a nearby fragment
        # resolves to a real heading -- leave the ORIGINAL line untouched,
        # not the collapsed guess. Emitting a collapsed word here can lose a
        # real word boundary within it ("R E S U M E S U M M A R Y", one
        # continuous run with no gap marking where "RESUME" ends and
        # "SUMMARY" begins, collapses to "RESUMESUMMARY") -- text that
        # matches nothing _find_heading_key would ever resolve anyway, and
        # that the verbatim-quote guard downstream then discards outright
        # because it no longer appears in the source CV at all.
        out.append(line)
        i += 1
    return out


# A CV paragraph occasionally glues a real section heading onto the tail of
# unrelated prose with no separator at all: the whole physical line is one
# single Word paragraph with no <w:br/> anywhere inside it (see
# extraction.py's _own_text docstring), so extraction correctly hands the
# classifier one giant run-on line rather than several. One CV welded an
# entire "KEYNOTES, PANELS, JUDGING AND OTHER INVITED ROLES" section --
# heading and all six entries -- onto the end of the press-coverage bullet
# that came right before it in the source: "...MDX Dubai awarded Best Media
# Centre by Forbes Middle East KEYNOTES, PANELS, JUDGING AND OTHER INVITED
# ROLES CABSAT..." as one unbroken sentence. Left alone, that swallows the
# whole keynotes section into whatever unrelated item happened to precede
# it, so it never appears as a section of its own -- silent, total loss of
# a real block of the CV even though the words are technically still
# present somewhere in the document.
#
# Recognised by shape alone (a run of 3+ consecutive ALL-CAPS words,
# appearing after ordinary lower-case prose, not at the very start of the
# line) rather than by name: the heading itself is not always one the MDX
# template lists by name (this one isn't), so the fix here is only to stop
# it fusing onto content it has nothing to do with, not to classify it --
# classification runs as normal afterward on the now-separated line.
EMBEDDED_HEADING_RUN_RE = re.compile(
    r"(?<=[a-z\)])\s+(?=(?:[A-Z][A-Z&/,.'-]*\s+){2,}[A-Z][A-Z&/,.'-]*(?:\s|$))"
)


def _split_embedded_heading_runs(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        for piece in EMBEDDED_HEADING_RUN_RE.split(line):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out


# The same shape check as EMBEDDED_HEADING_RUN_RE's lookahead, anchored to
# the START of a line instead of a mid-line split point. A line that begins
# this way is exactly what _split_embedded_heading_runs produces -- and
# _group_into_items must never weld it back onto the item before it just
# because the two lines don't otherwise look like separate entries (an
# unbulleted, unnamed section such as this CV's own "Keynotes, Panels,
# Judging..." block has no bullet glyphs and its opening line doesn't end in
# real sentence punctuation, so without this the split achieved above is
# immediately undone one stage later).
STARTS_WITH_HEADING_RUN_RE = re.compile(
    r"^(?:[A-Z][A-Z&/,.'-]*\s+){2,}[A-Z][A-Z&/,.'-]*(?:\s|$)"
)


def _split_into_sections(
    lines: list[str],
) -> tuple[list[str], dict[str, list[str]], set[str]]:
    """Returns (preamble_lines, {section_key: [raw_body_lines]}, authoritative).

    `authoritative` holds the sections whose heading was the template's own
    wording, so content-based re-routing knows to leave them alone.
    """
    sections: dict[str, list[str]] = {}
    authoritative: set[str] = set()
    preamble: list[str] = []
    current_key: str | None = None
    for line in lines:
        if not line.strip():
            continue
        if line.strip().upper() == "CURRICULUM VITAE":
            continue
        # A wrapped sentence that happens to END in a word spelling out an
        # official heading exactly ("...prepared for open-source robotics
        # education.") normalizes, once its trailing period is stripped, to
        # the literal heading text -- and matches it exactly. A genuine
        # heading essentially never ends in sentence-final punctuation, so
        # this alone (not the fuller "looks like a heading" shape test,
        # which would also reject a legitimate Title-Case heading with no
        # colon) is enough to tell the two apart without new false
        # rejections. Unguarded, this silently truncated whatever section
        # was open -- one CV lost every project after the first because a
        # sentence ending in "...education." was read as a new EDUCATION
        # heading partway through its Research Projects section.
        stripped_line = line.strip()
        glued_rest: str | None = None
        heading_source = line
        heading_key = None
        if not stripped_line.endswith((".", "!", "?")):
            # Tried before matching the line whole: `_find_heading_key`'s own
            # loose "contains a known phrase anywhere" fallback (for a
            # legitimate compound heading like "SUMMARY OF SKILLS AND
            # QUALIFICATIONS") is just as happy to match that same phrase
            # inside a heading GLUED to its own first line of content --
            # "EXPERIENCE  MARKETING MANAGER, 01/2023 - 11/2025" resolves via
            # that fallback too, and matching it whole would swallow the
            # entire line as "just a heading", silently discarding the job
            # title and dates that follow it. Skipped for a line that is
            # already a complete, official heading verbatim -- nothing to
            # recover there, and a legitimately double-spaced official
            # heading should never be carved up.
            if not is_authoritative_heading(line):
                glued = _split_glued_heading(line)
                if glued:
                    heading_source, heading_key, glued_rest = glued
            if not heading_key:
                heading_key = _find_heading_key(line)
                heading_source = line
                glued_rest = None
        if heading_key:
            if (
                heading_key == current_key
                and current_key in sections
                and current_key in SUBGROUPED_SECTIONS
            ):
                # Publications are the one section with meaningful internal
                # divisions ("Peer-reviewed journals", "Academic blogs and
                # media"). Keeping such a line in the body preserves the
                # sub-group it introduces for the items beneath it.
                sections[current_key].append(line)
                continue
            # Anywhere else, a second heading resolving to the section we are
            # already in is simply another heading -- a CV may carry both
            # "SUMMARY OF SKILLS AND QUALIFICATIONS" and "ACADEMIC
            # QUALIFICATIONS". Retaining it would publish the heading itself
            # as a bullet of content.
            current_key = heading_key
            if current_key in sections and sections[current_key]:
                # This section is being re-entered from a different part of
                # the document. Its earlier content and its new content are
                # not adjacent in the source, so they must never merge into
                # one item: doing so builds text that appears nowhere in the
                # CV, which the verbatim-quote guard then discards -- losing
                # the content silently. One CV lost a whole degree that way,
                # its last education line welded to the first project line
                # two pages later.
                sections[current_key].append(SEGMENT_BREAK)
            sections.setdefault(current_key, [])
            if is_authoritative_heading(heading_source):
                authoritative.add(current_key)
            if glued_rest:
                # The heading was glued to its own first line of content
                # (see _split_glued_heading) -- that content still belongs
                # to the section it introduces, not nowhere.
                sections[current_key].append(glued_rest)
            continue
        if current_key is None:
            preamble.append(line)
        else:
            sections[current_key].append(line)
    return preamble, sections, authoritative


FILENAME_NOISE_TOKENS = {
    "cv", "cvs", "resume", "resumé", "curriculum", "vitae", "profile", "bio",
    "final", "draft", "updated", "update", "new", "copy", "latest", "version",
    "doc", "docx", "pdf", "signed", "revised",
}
MONTH_PREFIX_RE = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.IGNORECASE)


def _filename_name_tokens(source_document: str) -> list[str]:
    """Word-ish tokens from the uploaded file's name, with the obvious
    non-name noise removed ("CV", "Final", dates, version numbers)."""
    stem = Path(source_document).stem
    stem = re.sub(r"\(.*?\)", " ", stem)
    stem = re.sub(r"[._\-]+", " ", stem)
    tokens: list[str] = []
    for raw in stem.split():
        token = raw.strip(".,")
        low = token.lower()
        if len(token) < 2 or low in FILENAME_NOISE_TOKENS:
            continue
        if any(ch.isdigit() for ch in token) or MONTH_PREFIX_RE.match(low):
            continue
        tokens.append(token)
    return tokens


def _name_corroborated_by_filename(cv_text: str, source_document: str) -> str | None:
    """Locate the person's name in the CV using the uploaded filename as the
    search key, returning the name *as written in the document*.

    HR names these files after the person ("Anuradha Vyas CV.docx"), which
    makes the filename a reliable anchor -- but the value returned is still
    read out of the CV text itself, never from the filename, so it stays a
    verbatim quote and keeps its exact in-document form ("Dr Camilla Hadi
    Chaudhary", "ANUJITH ANTONY").

    This matters most for CVs already written in the MDX template layout:
    they open straight at BIOGRAPHY with no letterhead at all, so the name
    exists only inside prose ("Dimo Valev is a Lecturer in...") where no
    whole-line name check can ever find it.
    """
    for token in _filename_name_tokens(source_document):
        if len(token) < 3:
            continue
        # [^\S\n] is "whitespace but not a newline": a name never spans a
        # line break, and allowing one lets the match run past the end of the
        # name into whatever the next line begins with ("AMAN MISHRA" +
        # "Job title:" -> "AMAN MISHRA Job").
        pattern = re.compile(
            r"\b((?:(?:Dr|Prof|Professor|Mr|Mrs|Ms|Miss)\.?[^\S\n]+)?"
            r"(?i:" + re.escape(token) + r")"
            r"(?:[^\S\n]+[A-Z][A-Za-z.'\-]*){1,3})"
        )
        match = pattern.search(cv_text)
        if not match:
            continue
        candidate = " ".join(match.group(1).split())
        if _find_heading_key(candidate) is not None or len(candidate) > 60:
            continue
        # A file named for a role rather than a person ("Elementary-Teacher-
        # Resume-Sample.docx") anchors on an occupation, and the phrase it
        # finds in the document is a job title, not a name. No one is called
        # "Elementary Teacher".
        if _has_title_keyword(candidate.lower()):
            continue
        return candidate
    return None


EMAIL_NAME_SPLIT_RE = re.compile(r"[._\-]+|(?<=[a-z])(?=[A-Z])")


def _name_from_email(cv_text: str) -> str | None:
    """Recover a name from the email address when the document never spells
    it out -- some templates put the name in an image, leaving the address
    as the only place it survives ("SophiaRobinson@gmail.com").

    Deliberately conservative: every part must be a real word-length run of
    letters, so initials and role addresses ("a.kashi@", "hr@", "info@")
    are rejected rather than turned into a fake name. The result is a
    derivation rather than a quote, so it is emitted at low confidence and
    always lands in the review queue.
    """
    match = EMAIL_RE.search(cv_text)
    if not match:
        return None
    local = match.group(0).split("@", 1)[0]
    parts = [p for p in EMAIL_NAME_SPLIT_RE.split(local) if p]
    if len(parts) < 2 or not all(p.isalpha() and len(p) >= 3 for p in parts):
        return None
    if any(p.lower() in ("info", "admin", "contact", "mail", "hello", "office") for p in parts):
        return None
    return " ".join(p.capitalize() for p in parts[:3])


def _names_agree(a: str, b: str) -> bool:
    """Two renderings of the same person: they share a real name word.

    "Dr Sophia Robinson" and "Sophia Robinson" agree; "Risk Management" and
    "Fatima Arain" do not. Honorifics and initials are too short to count.
    """
    def parts(name: str) -> set[str]:
        return {w.strip(".,").casefold() for w in name.split() if len(w.strip(".,")) >= 3}
    return bool(parts(a) & parts(b))


HEADER_LINE_MAX_CHARS = 60
CONTACT_LABEL_RE = re.compile(
    r"\b(?:phone|tel(?:ephone)?|mob(?:ile)?|cell|e-?mail|address|contact)\b\s*:?",
    re.IGNORECASE,
)


def _letterhead_segments(line: str) -> list[str]:
    """Pieces of a line that might each be a separate letterhead field.

    Compact CV headers put several fields on one physical line --
    "ARIFULLAH BASHA SHAIK PHONE :(UAE) +971554481437" holds a name and a
    phone number with no separator between them. Tested whole, such a line
    can never be a name (it has digits and a colon), so the name is lost.

    Split on explicit separators, on contact-field labels, and at the point
    where an email or phone number begins, then offer every piece.
    """
    segments = [line]
    segments += [s for s in PIPE_SPLIT_RE.split(line) if s.strip()]
    segments += [s for s in CONTACT_LABEL_RE.split(line) if s and s.strip()]

    for pattern_match in (EMAIL_RE.search(line), find_phone(line)):
        if pattern_match and pattern_match.start() > 0:
            segments.append(line[: pattern_match.start()])

    # A run of three or more spaces is a COLUMN GAP, not a word gap: it is
    # what a tab or a table cell boundary collapses to. "John Smith
    # Secondary Teacher History Department" is two fields laid out side by
    # side, and without this split the whole line is rejected as a name and
    # something else in the document wins.
    segments += [s for s in WIDE_GAP_RE.split(line) if s.strip()]

    # Deliberately NOT splitting on job-title words to salvage a name from
    # "<Name> <Job Title>" lines. Tried and reverted: it turns "FIFTH GRADE
    # TEACHER" into the name "FIFTH GRADE" and slices "Resourceful Math" out
    # of a summary sentence, losing correct email-derived names in the
    # process. Deriving the name from the email address is both more
    # reliable and honest about being a derivation. The whitespace split
    # above is different in kind -- it uses layout the author put there,
    # not a guess about which words are a job title.

    return [" ".join(s.split()) for s in segments if s and s.strip()]


WIDE_GAP_RE = re.compile(r"\s{3,}|	")

LETTERHEAD_WINDOW = 6  # lines to look either side of the email/phone anchor


def _anchor_window(lines: list[str], anchor_idx: int | None) -> list[str]:
    """Lines around a found anchor (email or phone), in original order.
    Resumes reliably cluster name+title+email+phone together visually, even
    when a PDF's text-extraction order scatters that cluster away from the
    very start of the document (e.g. a sidebar/header box in the original
    layout) -- anchoring on whichever contact detail we DID find is far more
    reliable than assuming the letterhead is always "whatever comes first"."""
    if anchor_idx is None:
        return []
    lo = max(0, anchor_idx - LETTERHEAD_WINDOW)
    hi = min(len(lines), anchor_idx + LETTERHEAD_WINDOW + 1)
    return lines[lo:hi]


def _extract_letterhead(
    preamble: list[str], full_text: str, source_document: str = ""
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    lines = full_text.splitlines()

    email_match = EMAIL_RE.search(full_text)
    email_line_idx = None
    if email_match:
        source = email_match.group(0)
        for i, line in enumerate(lines):
            if email_match.group(0) in line:
                email_line_idx = i
                source = line.strip()
                break
        items.append({
            "section": "email", "fields": {"value": email_match.group(0)},
            "source_text": source, "confidence": 0.95,
        })

    phone_line_idx = None
    for i, line in enumerate(lines):
        if find_phone(line):
            phone_line_idx = i
            break

    # Candidate pool for name/title: a window around wherever the email/phone
    # actually landed, checked FIRST -- a name/title sitting right next to a
    # found contact detail is far more trustworthy than "whatever line came
    # first in the document" -- with the preamble kept only as a fallback
    # for CVs where no email/phone was found at all.
    candidates: list[str] = []
    # Maps a candidate that was DERIVED (rather than quoted as-is) back to
    # the real line it came from, so source_text can still point at the
    # true verbatim quote even when the candidate used for matching isn't
    # it -- same idea as the existing email-derived-name handling below.
    candidate_source: dict[str, str] = {}

    def _add_candidate(line: str) -> None:
        if line not in candidates:
            candidates.append(line)
        # A contact strip packs several fields onto one physical line
        # ("Dr Jane Doe | j.doe@uni.ac.uk | +44 123"). The whole line can
        # never match a name (it holds an @ and digits), so also offer each
        # delimited segment as its own candidate.
        for segment in _letterhead_segments(line):
            if segment and segment not in candidates:
                candidates.append(segment)
        # A name a template letter-spaces for visual effect
        # ("D E V A P R A B H A A .") extracts as a run of single-letter
        # tokens no shape check can recognise as a name -- the same
        # rendering artifact _merge_split_letter_spaced_headings already
        # normalises for section headings, just not caught there because a
        # name-plate line is never itself a recognised heading.
        collapsed = _collapse_letter_spaced_name(line)
        if collapsed and collapsed not in candidates:
            candidates.append(collapsed)
            candidate_source[collapsed] = line

    for anchor_idx in (email_line_idx, phone_line_idx):
        for line in _anchor_window(lines, anchor_idx):
            _add_candidate(line)
    for line in preamble:
        _add_candidate(line)

    # A real name conventionally appears more than once in a CV (header +
    # signature block, header + declaration, etc.) -- a candidate that
    # repeats is a much stronger signal than "merely shaped like a name",
    # which a Title-Case skill-list entry (e.g. "Fast Learning") can also
    # satisfy by coincidence. Prefer a repeated candidate; only fall back
    # to the first single-occurrence match if nothing repeats.
    name_counts = Counter(
        line.strip() for line in lines if _looks_like_person_name(line)
    )
    # Filename-corroborated match first: it is the only signal that also
    # works on a CV with no letterhead block, and it cannot be fooled by a
    # stray Title-Case phrase the way a pure shape check can.
    name_line = _name_corroborated_by_filename(full_text, source_document)
    confidence = 0.9

    if not name_line:
        for line in candidates:
            if _looks_like_person_name(line) and name_counts[line.strip()] >= 2:
                name_line = line.strip()
                confidence = 0.85
                break
    # An address is stronger evidence than an uncorroborated Title-Case
    # phrase. Shape matching alone picked "Risk Management" and "Coursework
    # Design" as people's names on CVs whose top block is a skills list,
    # while the address sitting right there said fatima.arain@gmail.com.
    # _name_from_email is already strict -- both parts must be real words and
    # role addresses (hr@, info@, admin@) are rejected -- so when it returns
    # something, it is worth more than a guess from layout.
    email_name = _name_from_email(full_text)

    if not name_line:
        shape_name = next(
            ((line.strip(), 0.75 if line in preamble else 0.8)
             for line in candidates
             if _looks_like_person_name(line)
             or (line in candidate_source and _looks_like_collapsed_name(line))),
            None,
        )
        if shape_name and (not email_name or _names_agree(shape_name[0], email_name)):
            # The two agree, or there is no address to check against: the
            # line the CV actually prints is the better quote.
            name_line, confidence = shape_name
        elif email_name:
            name_line, confidence = email_name, 0.7
        elif shape_name:
            name_line, confidence = shape_name

    # A name derived from an address, or collapsed from letter-spacing, is
    # not a quote from the CV in that exact form, so its source is the real
    # line it came from -- keeping the "every item traces back to real
    # text" guarantee intact even when `value` itself is a cleaned-up form.
    if name_line and name_line == email_name:
        name_source = next((l.strip() for l in lines if EMAIL_RE.search(l)), name_line)
    else:
        name_source = candidate_source.get(name_line, name_line)

    if name_line:
        items.append({
            "section": "full_name", "fields": {"value": name_line},
            "source_text": name_source or name_line, "confidence": confidence,
        })

    # Only trust a title keyword match right next to the letterhead (the
    # anchor window) -- searching the whole preamble for any line containing
    # a word like "support" or "manager" is too loose: on a CV whose top
    # section is a bullet list of skills/competencies (e.g. "IT Technical
    # Support" as a skill, not a title), that noise wins over silence. A
    # real title with no explicit label near the contact block instead
    # falls back to the most recent job's title -- see classify_rule_based.
    job_title_line = None
    anchor_only = [
        line for anchor_idx in (email_line_idx, phone_line_idx)
        for line in _anchor_window(lines, anchor_idx)
    ]
    for line in anchor_only:
        # "Job titles:" and its actual value are commonly on two separate
        # physical lines, with the value itself bulleted ("Job titles:" /
        # "•  Lecturer in Graphic Design..."). Without stripping the bullet
        # here, it survives into the stored value and renders as
        # "Job title: •  Lecturer in..." in the finished document.
        text = BULLET_START_RE.sub("", line).strip()
        # The name and the title are commonly printed on one physical line
        # with no field of their own ("Rachel Zane, Business Analyst"). Left
        # whole, that line becomes the stored job title WITH the person's
        # name glued onto the front of it -- the name already has its own
        # field, so strip it back off here rather than storing it twice,
        # once correctly and once as noise prefixed onto the title.
        if name_line and text.casefold().startswith(name_line.casefold()):
            remainder = text[len(name_line):].lstrip(" ,:-–—").strip()
            if remainder:
                text = remainder
        low = text.lower()
        if low.startswith("job title"):
            # Handles the plural the MDX template itself uses ("Job titles:").
            # If nothing follows the label it is an unfilled prompt, not a
            # title -- keep looking rather than storing the label itself.
            stripped_label = re.sub(r"(?i)^job\s*titles?\s*:?\s*", "", text).strip()
            if stripped_label:
                job_title_line = stripped_label
                break
            continue
        if (
            text != name_line
            and _has_title_keyword(low)
            and not EMAIL_RE.search(text)
            and _looks_like_job_title(text)
        ):
            job_title_line = text
            break
    if job_title_line:
        items.append({
            "section": "job_title", "fields": {"value": job_title_line},
            "source_text": job_title_line, "confidence": 0.7,
        })

    contact_line = None
    for line in candidates:
        text = line.strip()
        if text.lower().startswith("contact"):
            # Same trap as the job-title label: a bare "Contact" heading with
            # nothing after it is a prompt, not a phone number. Keep looking
            # rather than storing the word "contact" as someone's number.
            stripped_label = re.sub(r"(?i)^contact(?:\s+(?:details|info(?:rmation)?|number))?\s*:?\s*", "", text).strip()
            if stripped_label:
                contact_line = stripped_label
                break
            continue
        phone_match = find_phone(text)
        if phone_match and "job title" not in text.lower():
            contact_line = phone_match.group(0).strip()
            break
    if contact_line:
        items.append({
            "section": "contact_info", "fields": {"value": contact_line},
            "source_text": contact_line, "confidence": 0.75,
        })

    return items


TRAILING_CITY_STATE_RE = re.compile(r",\s*[A-Za-z .]+,\s*[A-Z]{2,4}\s*$")
CORP_SUFFIX_RE = re.compile(r"^(?:Inc|LLC|L\.L\.C|Ltd|Corp|Co|LLP|PLC)\.?$", re.IGNORECASE)

# A bare job title sitting alone on its own line, with the employer, city,
# state and dates on the line directly after it ("Advertising Manager" /
# "Clearpoint, Buffalo, NY (2008 - present)") -- a different, comma-based
# layout from the slash-delimited one EMPLOYMENT_ENTRY_HEADER_RE handles.
# Narrow on purpose: no comma, no digit, and shaped like a title, so it
# can't accidentally swallow a real "Employer, City, ST" line on its own.
BARE_TITLE_LINE_RE = re.compile(r"^[A-Z][A-Za-z .&'-]{1,50}$")
# The trailing region code is a US state ("NY") most often, but a CV
# outside the US just as often writes a 3-letter country code ("UAE",
# "USA") in the same position -- narrower than accepting any 2-4 letter
# run (which would also swallow a genuine 3-4 letter employer abbreviation
# used AS the last comma part) would mean re-litigating this per country,
# so the cap stays at 4 letters, all uppercase, same as a code always is.
EMPLOYER_CITY_STATE_DATE_RE = re.compile(
    r"^(?P<employer>[A-Z][\w&'.-]*(?:\s+[A-Z][\w&'.-]*){0,2}),\s*"
    r"(?P<city>[A-Za-z .]+),\s*(?P<state>[A-Z]{2,4})\s*"
    r"[\(\s]*\s*(?P<start>(?:19|20)\d{2})"
    r"(?:\s*[-–—]\s*(?P<end>(?:19|20)\d{2}|[Pp]resent|[Pp]resent [Tt]ime|[Cc]urrent))?"
)


# A label a CV uses to introduce a run of public-engagement activity
# (conferences organised, keynote talks given) inside the SAME heading as
# its actual job entries, with no heading of its own the classifier would
# otherwise recognise. Narrow to the two concrete phrasings seen -- this is
# a content-based signal, not a shape-based one, so it can't misfire the
# way a general "this looks like a new heading" detector already proved it
# does (see FIXLOG.md's three rejected attempts).
KNOWLEDGE_EXCHANGE_MARKER_RE = re.compile(
    r"^(?:Special Projects and Conferences|Conference Presentations|Keynote Speeches)\b",
    re.IGNORECASE,
)


def _split_employment_and_practice_zones(
    raw_lines: list[str],
) -> list[tuple[str, list[str]]]:
    """Partition an Employment section's raw lines into ('employment', […])
    and ('knowledge_exchange', […]) runs.

    A CV spanning many years commonly folds public-engagement work into the
    same "Professional Experience" heading as actual jobs, introduced by a
    label like "Special Projects and Conferences" rather than a heading of
    its own. Content after such a label is professional practice, not
    employment, until a REAL job restarts -- recognised the same way a
    job's own header is recognised elsewhere in this module: an "Employer,
    City, ST/Country (dates)" line immediately followed by a bare job-title
    line (see `_employment_body_entries`). That symmetry is what keeps this
    safe: the boundary is content the CV itself wrote in a job's own shape,
    not a guess about layout.
    """
    zones: list[tuple[str, list[str]]] = []
    kind = "employment"
    current: list[str] = []
    i, n = 0, len(raw_lines)
    while i < n:
        line = raw_lines[i]
        stripped = line.strip()
        if kind == "employment" and KNOWLEDGE_EXCHANGE_MARKER_RE.match(stripped):
            if current:
                zones.append((kind, current))
            current, kind = [line], "knowledge_exchange"
            i += 1
            continue
        if kind == "knowledge_exchange":
            next_line = raw_lines[i + 1].strip() if i + 1 < n else ""
            # A real job restarting is recognised by a YEAR RANGE (not a
            # single date -- a one-off conference never has a range) paired
            # with a bare title-shaped line right after it. Deliberately
            # looser than EMPLOYER_CITY_STATE_DATE_RE's exact shape: a real
            # employer line here is often untidy in ways that pattern
            # doesn't cover ("Super Sprowtz, Nutrition Edutainment - New
            # York, NY"), and missing the restart silently swallows every
            # later real job into this zone too, which is a worse outcome
            # than the one this whole fix exists to correct.
            restarts_job = (
                YEAR_RANGE_RE.search(stripped)
                and BARE_TITLE_LINE_RE.match(next_line)
                and _has_title_keyword(next_line.lower())
            )
            if restarts_job:
                if current:
                    zones.append((kind, current))
                current, kind = [], "employment"
                continue  # re-process this line under the new zone
        current.append(line)
        i += 1
    if current:
        zones.append((kind, current))
    return zones


def _employment_body_entries(
    body_items: list[str], employer_key: str
) -> list[tuple[str, dict[str, Any]]]:
    """One (source_text, fields) pair per employment entry in this section.

    Ordinarily each entry is its own item and _extract_employment_fields
    parses it directly. But a résumé commonly prints a job's title alone on
    one line and its employer/location/dates on the very next ("Advertising
    Manager" / "Clearpoint, Buffalo, NY (2008 - present)"), with no shared
    punctuation tying them together for the grouper to catch. Read
    separately, the title line renders as a bare, date-less bullet, and the
    employer line's own field-parser has no way to know a title exists --
    it reads "Clearpoint, Buffalo, NY" as a title/employer pair and stores
    the state abbreviation as the employer.
    #
    # Fields are built directly from the two known pieces here rather than
    # by gluing the lines into one string and re-parsing it: a synthetic
    # separator inserted between them (to mark where the title ends) would
    # not exist in the source document, and the verbatim-quote guard would
    # then discard the whole item as unquotable, silently losing it. The
    # displayed source_text is instead the two original lines joined with a
    # plain space -- exactly how the guard's own whitespace-normalised
    # comparison reads two adjacent physical lines, so it stays verifiable.
    """
    entries: list[tuple[str, dict[str, Any]]] = []
    skip_next = False
    for i, text in enumerate(body_items):
        if skip_next:
            skip_next = False
            continue
        stripped = text.strip()
        if i + 1 < len(body_items):
            match = EMPLOYER_CITY_STATE_DATE_RE.match(body_items[i + 1].strip())
            # Requiring an actual title keyword (not just the shape) keeps
            # this from misfiring on a short, punctuation-free responsibility
            # bullet ("Provided excellent customer service") that happens to
            # sit directly above the next job's employer line -- a bare noun
            # phrase without one of these is far more likely a fragment of
            # prose than someone's job title.
            if (
                match and BARE_TITLE_LINE_RE.match(stripped)
                and _looks_like_job_title(stripped)
                and _has_title_keyword(stripped.lower())
            ):
                next_stripped = body_items[i + 1].strip()
                end_raw = (match.group("end") or "").strip()
                ongoing = end_raw.lower() in ("present", "present time", "current")
                fields: dict[str, Any] = {
                    "title": stripped,
                    employer_key: match.group("employer").strip(),
                    "start_date": match.group("start"),
                    "end_date": "" if ongoing else end_raw,
                }
                if ongoing:
                    fields["is_current"] = True
                entries.append((f"{stripped} {next_stripped}", fields))
                skip_next = True
                continue
        entries.append((text, _extract_employment_fields(text, employer_key)))
    return entries


def _extract_employment_fields(line: str, employer_key: str) -> dict[str, Any]:
    m = YEAR_RANGE_RE.search(line)
    if not m:
        return {}
    # Each side may carry a month ("June 2024"); only the year is stored.
    start_match = YEAR_IN_TEXT_RE.search(m.group(1) or "")
    if not start_match:
        return {}
    start = start_match.group(0)

    end_raw = (m.group(2) or "").strip()
    ongoing = end_raw.lower() in (
        "present", "present time", "current", "current date", "onward", "onwards", "date",
    )
    end_year_match = YEAR_IN_TEXT_RE.search(end_raw)
    if ongoing or not end_raw:
        end = ""
    elif end_year_match:
        end = end_year_match.group(0)
    elif len(end_raw) == 2 and end_raw.isdigit():
        # "2024-26" -> 2026, carried across a century boundary if needed
        # ("1999-02" is 1999-2002, not 1999-1902). Same fabrication risk as
        # normalize_date_range's identical logic: "2020-09" (ISO year-month,
        # "09" = September) is shape-identical to a short end year, and
        # wrapping it a century forward produces a nonsense year decades in
        # the future ("2109"). Guarded the same way -- see that function's
        # comment for the full reasoning.
        century, start_year = int(start) // 100, int(start)
        end_year = century * 100 + int(end_raw)
        if end_year < start_year:
            wrapped = end_year + 100
            end = str(wrapped) if wrapped <= date.today().year + 5 else ""
        else:
            end = str(end_year)
    else:
        end = ""

    # CVs put the date column on either side of the role, and both are
    # common:
    #     "2013 - 2016 - Part-time Lecturer in Law, Middlesex University"
    #     "Consultant, Oxford Policy Management, Oxford, UK, 2024-2026"
    # Reading only what follows the date silently produced an entry with no
    # title or employer at all for the second form -- the generated document
    # showed a bare "(2024 - 2026)". Take whichever side actually has text.
    # "|" is included: CVs commonly use it as the separator before the date
    # column ("...KIMEP University - Almaty | 1999 - 02"), and leaving it on
    # renders as "…Almaty | (1999 - 2002)".
    # Brackets are stripped too: a parenthesised date ("...Dubai (2018 -
    # 2025)") leaves its opening bracket dangling on the role otherwise.
    # ":" is stripped too: "December 2015 to August 2025: Rashid Hospital..."
    # otherwise leaves a dangling ": Rashid Hospital" as the stored employer.
    before = line[:m.start()].strip(" ,:|()[]-–—")
    after = line[m.end():].strip(" ,:|()[]-–—")
    # "…, August 2010 - Present" leaves the month stranded on the role side
    # once the year match is removed; it belongs to the date, not the employer.
    before = TRAILING_MONTH_RE.sub("", before).strip(" ,-–—")
    # Whichever side holds the role, ignoring a side that is only leftover
    # date debris -- otherwise a stray "26" becomes the person's job title.
    # But a merged item can carry the ENTIRE narrative paragraph after the
    # date too ("...Jan 2013 - Present, New York, New York Deutsche Bank is
    # a German global banking and financial services company. As a Sr
    # Business Analyst, my core activities include:") -- reading that side
    # unconditionally produces a "title" that is actually a run-on sentence,
    # with "my core activities include" left stored as the employer. When
    # the date-remnant side is prose (a real sentence, or simply long) AND
    # the other side is a short, clean fragment, the short side is the
    # actual title/employer pair and is preferred instead.
    after_is_narrative = bool(re.search(r"[.!?]\s+\S", after)) or len(after) > 60
    # 60 was too tight for a genuinely long but clean title/employer/location
    # combination ("Founder and Chief Creative Officer, Not an Agency Inc.,
    # Dubai, United Arab Emirates" -- 90 chars, no sentence-shaped prose
    # anywhere in it) -- it was losing to a run-on narrative side hundreds of
    # characters long purely because "before" ran a little past 60. Raised
    # to 100, which a real title/employer/location line rarely exceeds,
    # while genuine narrative prose (checked separately, right below) still
    # gets excluded regardless of length once it actually reads like a
    # sentence.
    before_is_usable = (
        bool(before) and not DATE_REMNANT_RE.match(before) and len(before) <= 100
        and not re.search(r"[.!?]\s+\S", before)
    )
    if after and not DATE_REMNANT_RE.match(after) and not (after_is_narrative and before_is_usable):
        rest = after
    else:
        rest = before

    # A trailing "City, ST" is the entry's location, not a third field in
    # the title/employer split -- left in, "Advertising Manager, Clearpoint,
    # Buffalo, NY" reads as three comma parts and the split below takes the
    # LAST one as "employer", storing the state abbreviation ("NY") as the
    # employer and "Clearpoint, Buffalo" as the title. Stripped first, only
    # the genuine title/employer pair is left to split on.
    rest = TRAILING_CITY_STATE_RE.sub("", rest).strip()

    parts = [p.strip() for p in rest.split(",") if p.strip()]
    # A corporate suffix ("Carhartt, Inc.") is written with its own comma,
    # which otherwise reads as a THIRD field and knocks the split off by
    # one -- "Inc." becomes the stored employer and "Associate Advertising
    # Manager Carhartt" becomes the title. Folded back onto the part before
    # it first, the suffix stays attached to the employer name it belongs to.
    if len(parts) > 2 and CORP_SUFFIX_RE.match(parts[-1]):
        parts[-2:] = [f"{parts[-2]}, {parts[-1]}"]
    if not parts:
        return {"start_date": start, "end_date": end}
    # The usual convention is "Title, Employer" (title first) -- but plenty
    # of CVs instead write "Employer, City Country" on one line and "Title
    # <tabs> Date" on the next ("Middlesex University, Dubai UAE" / "Senior
    # Lecturer   September 2023 - Present"), which grouping glues into one
    # comma-poor blob with the title stuck on the END, not the start. Taking
    # the last comma part as "employer" unconditionally then stores the
    # employer's own name as the job title. A title keyword found in the
    # LAST part but not the first is the signal this is the reversed
    # convention; only the immediately preceding word is folded in too
    # (covers "Senior Lecturer", "Assistant Director" -- the common
    # one-modifier case), not an open-ended backward search.
    last_has_title_kw = len(parts) > 1 and _has_title_keyword(parts[-1])
    first_has_title_kw = len(parts) > 1 and _has_title_keyword(parts[0])
    if last_has_title_kw and not first_has_title_kw:
        tail_words = parts[-1].split()
        kw_idx = next(
            (i for i, w in enumerate(tail_words)
             if _has_title_keyword(w.lower())),
            None,
        )
        title_start = max(0, kw_idx - 1) if kw_idx and re.match(r"^[A-Z][a-z]+$", tail_words[kw_idx - 1]) else kw_idx
        location_prefix = " ".join(tail_words[:title_start])
        title = " ".join(tail_words[title_start:])
        employer = ", ".join(parts[:-1]) + (f", {location_prefix}" if location_prefix else "")
    else:
        employer = parts[-1] if len(parts) > 1 else ""
        title = ", ".join(parts[:-1]) if len(parts) > 1 else parts[0]
    # Grouping sometimes fuses a title-only line straight onto the
    # following "Employer, City, ST (dates)" line with no punctuation
    # between them at all ("Senior Marketing Executive Falcon Media House,
    # Amman, JO") before this function ever sees it -- there is then no
    # comma left to split "title" from "employer" on once the city/state
    # tail above is stripped, and the whole glued phrase is stored as the
    # title with no employer. A job-title keyword marks the most plausible
    # boundary: split right after its last occurrence, so "Senior Marketing
    # Executive" (title) separates from "Falcon Media House" (employer).
    if len(parts) == 1 and not employer:
        kw_end = None
        for kw in TITLE_KEYWORDS:
            for kw_match in re.finditer(r"\b" + re.escape(kw) + r"\b", title, re.IGNORECASE):
                kw_end = kw_match.end()
        if kw_end and kw_end < len(title):
            candidate_employer = title[kw_end:].strip(" ,-")
            if candidate_employer:
                title, employer = title[:kw_end].strip(), candidate_employer
    fields = {"title": title, "start_date": start, "end_date": end}
    # Record that the CV said "Present"/"Current" explicitly, so the renderer
    # can show an ongoing role as "(2010 - present)" rather than a bare
    # "(2010)" that reads as a one-year post. Without this the marker is lost:
    # an open end date and an unknown end date look identical in the fields.
    if ongoing:
        fields["is_current"] = True
    fields[employer_key] = employer
    return fields


def _guess_title_from_employment_text(text: str) -> str | None:
    """Fallback when no title sits near the letterhead at all: pull a
    title-shaped fragment out of the most recent employment line itself
    (e.g. "...CONSOL GULF SOFTWARE SOLUTION, Dubai, IT TECHNICAL SUPPORT
    ENGINEER" -> "IT TECHNICAL SUPPORT ENGINEER"). Still a verbatim
    substring of that line -- just a comma-delimited segment of it -- so
    the no-fabrication rule holds; the low confidence this gets called
    with is what flags it for HR to confirm rather than trust outright."""
    for kw in TITLE_KEYWORDS:
        kw_re = re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
        if kw_re.search(text):
            for segment in text.split(","):
                if kw_re.search(segment):
                    # A merged item can drag a whole paragraph of duties
                    # into one "segment" when the source CV has no bullet
                    # marker on its responsibility lines -- stop at the
                    # first sentence boundary so we only ever take the
                    # title phrase itself, never the prose that follows it.
                    cleaned = re.split(r"[.\n]", segment.strip(" ."), maxsplit=1)[0].strip()
                    if cleaned and len(cleaned) <= 60:
                        return cleaned
                    return None
    return None


FUNDED_RE = re.compile(
    r"\(\s*Funded by\s+(.+?)(?:,\s*(\d{4}[^)]*?))?\s*\)", re.IGNORECASE
)
SHORT_YEAR_RANGE_RE = re.compile(r"\b(\d{2})(\d{2})\s*([-–—])\s*(\d{2})\b")


def normalize_date_range(text: str) -> str:
    """Expand a two-digit end year against the century of the start year:
    "2025-26" -> "2025-2026", "1999 - 02" -> "1999 - 2002". Purely a
    formatting normalisation of digits already present -- no date is
    invented, and a range already written in full is left untouched."""
    def _expand(m: re.Match) -> str:
        century, start_yy, dash, end_yy = m.groups()
        start_year = int(century + start_yy)
        end_year = int(century) * 100 + int(end_yy)
        if end_year < start_year:  # e.g. 1999-02 spans the century boundary
            wrapped = end_year + 100
            # This same 4+2-digit shape is indistinguishable from an ISO
            # "YYYY-MM" date ("2020-09" = September 2020) using local text
            # alone -- and wrapping THAT by a century produces a nonsense
            # year like 2109, decades in the future. A genuine short-year
            # range never legitimately wraps past a few years from today
            # (the "1999-02" -> "2002" case lands in the past, not the
            # future); when it would, this is almost certainly a month
            # suffix, not a year -- leave the original text untouched
            # rather than fabricate a date.
            if wrapped > date.today().year + 5:
                return m.group(0)
            end_year = wrapped
        return f"{start_year}{dash}{end_year}"

    return SHORT_YEAR_RANGE_RE.sub(_expand, text)


# Degree names, longest first so "Master of Science" wins over "Master" and
# the abbreviation forms are not swallowed by a shorter prefix.
DEGREE_PATTERNS = [
    r"Doctor of Philosophy", r"Doctor of Education", r"Doctor of Business Administration",
    r"Doctor of Psychology", r"Ph\.?\s?D\.?", r"D\.?Phil\.?", r"Ed\.?D\.?",
    r"Doctorate", r"Master of Business Administration", r"M\.?B\.?A\.?",
    r"Master of Philosophy", r"M\.?Phil\.?", r"Master of Science",
    r"Master of Arts", r"Master of Education", r"Master of Engineering",
    r"Master of Laws", r"M\.?Sc\.?", r"M\.?Res\.?", r"M\.?Eng\.?", r"M\.?Ed\.?",
    r"M\.?Tech\.?", r"M\.?Com\.?", r"LL\.?M\.?", r"M\.?A\.?", r"Masters?",
    r"Bachelor of Technology", r"Bachelor of Engineering", r"Bachelor of Science",
    r"Bachelor of Arts", r"Bachelor of Laws", r"Bachelor of Commerce",
    r"Bachelor of Education", r"Bachelor of Business Administration",
    r"B\.?Sc\.?", r"B\.?Eng\.?", r"B\.?Tech\.?", r"B\.?Com\.?", r"LL\.?B\.?",
    r"B\.?A\.?", r"Bachelors?",
    r"Associate of Science", r"Associate of Arts", r"Associate Degree",
    r"Higher Secondary Education", r"Secondary School Certificate",
    r"PGCHE", r"PGCert", r"PGCE", r"PGDip",
    r"Postgraduate Certificate", r"Postgraduate Diploma", r"Advanced Diploma",
    r"Diploma", r"Higher National Diploma", r"HND",
]
DEGREE_RE = re.compile(r"\b(" + "|".join(DEGREE_PATTERNS) + r")\b", re.IGNORECASE)

# The words before the keyword are matched greedily so the full name is
# taken -- "National Academy of Arts", not "Academy of Arts" with "National"
# left stranded on the end of the subject. Over-reach is caught by
# _is_plausible_institution rather than by making the pattern timid.
INSTITUTION_RE = re.compile(
    r"\b([A-Z][\w.&'-]*(?:\s+[\w.&'-]+){0,6}\s+"
    r"(?:University|College|Institute|Institution|Academy|Polytechnic|School)"
    r"(?:\s+of\s+[\w.&'-]+(?:\s+[\w.&'-]+){0,3})?)\b"
)
# "University of X" written the other way round.
INSTITUTION_LEADING_RE = re.compile(
    r"\b((?:University|Institute|College|Academy|School)\s+of\s+"
    r"[A-Z][\w.&'-]*(?:\s+[\w.&'-]+){0,3})\b"
)

# Countries that actually appear on the CVs this tool handles. A general
# country list would match "Georgia" inside an American university name and
# "Chad" inside a person's name; this stays deliberately narrow, and a
# country that isn't matched is simply left unset rather than guessed.
COUNTRY_NAMES = [
    "United Arab Emirates", "United Kingdom", "United States of America",
    "United States", "Saudi Arabia", "South Africa", "New Zealand",
    "Sri Lanka", "South Korea", "Hong Kong", "Netherlands", "Switzerland",
    "Singapore", "Australia", "Bangladesh", "Malaysia", "Pakistan",
    "Indonesia", "Germany", "Ireland", "Nigeria", "Denmark", "Belgium",
    "Sweden", "Norway", "Finland", "Austria", "Canada", "France", "Italy",
    "Spain", "Japan", "China", "India", "Egypt", "Kenya", "Ghana", "Qatar",
    "Oman", "Jordan", "Turkey", "Poland", "Greece", "Brazil", "Mexico",
    "Russia", "Bulgaria", "Romania", "Hungary", "Portugal", "Czech Republic",
    "Ukraine", "Philippines", "Thailand", "Vietnam", "Nepal", "Lebanon",
    "Kuwait", "Bahrain", "Iraq", "Iran", "Morocco", "Tunisia", "Algeria",
    "Ethiopia", "Tanzania", "Uganda", "Zimbabwe", "Argentina", "Chile",
    "Colombia", "Cyprus", "Malta", "Iceland", "Croatia", "Serbia", "Slovakia",
    "Slovenia", "Estonia", "Latvia", "Lithuania", "Luxembourg", "Scotland",
    "Wales", "England", "Northern Ireland",
    "Dubai", "Abu Dhabi", "Sharjah", "UAE", "UK", "USA", "U.K.", "U.S.A.",
]
COUNTRY_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in COUNTRY_NAMES) + r")\b")

# A bare "City, Country" line -- a geographic sub-heading a CV uses to group
# a list of entries underneath it ("PUBLIC SERVICE" followed by "Dubai,
# UAE" then several Dubai-based entries, later "New York, USA" for the New
# York ones), not content in its own right. Matched only against a full
# country NAME (this curated list), never a bare 2-4 letter state/country
# CODE -- that narrower version was tried and reverted (FIXLOG.md) because
# it also deleted real institution names ending in a US state abbreviation
# ("Branson University, NV"). A full country name is unambiguous enough
# that this doesn't recur.
BARE_CITY_COUNTRY_RE = re.compile(
    r"^[A-Za-z .]{2,40},\s*(" + "|".join(re.escape(c) for c in COUNTRY_NAMES) + r")$"
)

# Cities that stand in for a country on a CV line ("... , Dubai").
CITY_TO_COUNTRY = {
    "dubai": "United Arab Emirates", "abu dhabi": "United Arab Emirates",
    "sharjah": "United Arab Emirates", "uae": "United Arab Emirates",
    "uk": "United Kingdom", "u.k.": "United Kingdom",
    "usa": "United States", "u.s.a.": "United States",
}


# Years a CV can plausibly refer to. Deliberately not \d{4}: that matches a
# course code, a room number or a page reference just as readily.
CALENDAR_YEAR_RE = re.compile(r"\b(19\d{2}|20[0-4]\d)\b")


# Ordered most-specific first: "Editor-in-Chief" must not be reported as the
# generic "Editorial board member", and "Visiting Professor" is an
# appointment rather than a membership.
ROLE_KIND_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\beditor[- ]in[- ]chief\b|\bmanaging editor\b", re.I), "Editor-in-Chief"),
    (re.compile(r"\b(?:associate|guest|section|co-)\s*editor\b", re.I), "Editor"),
    (re.compile(r"\beditorial (?:board|advisory board)\b", re.I), "Editorial board member"),
    (re.compile(r"\beditor\b", re.I), "Editor"),
    (re.compile(r"\bexternal examiner\b", re.I), "External examiner"),
    (re.compile(r"\bexaminer\b", re.I), "Examiner"),
    (re.compile(r"\breviewer\b|\brefere+\b|\bpeer review\b", re.I), "Reviewer"),
    (re.compile(r"\bvisiting (?:professor|fellow|scholar|lecturer|researcher)\b", re.I),
     "Visiting appointment"),
    (re.compile(r"\b(?:senior |principal |life |honorary )?fellow(?:ship)?\b", re.I), "Fellowship"),
    (re.compile(r"\bchartered\b", re.I), "Chartered status"),
    (re.compile(r"\bmember(?:ship)?\b|\baffiliate\b", re.I), "Membership"),
]


def _role_kind(text: str) -> str | None:
    """The specific kind of appointment a line describes, or None.

    Read from the opening of the entry only, for the same reason routing
    does: a CV names its role first and qualifies it afterwards, so a
    reviewer entry that mentions a journal it also sits on the board of is
    still a reviewer entry.
    """
    head = text[:routing.ROLE_SPAN_CHARS]
    for pattern, kind in ROLE_KIND_PATTERNS:
        if pattern.search(head):
            return kind
    return None


# A grade/GPA fact printed on its own wrapped line, one CV entry's trailing
# detail rather than a whole fact of its own -- "Bachelor of Engineering...
# / 2010 - 2014 / GPA: 7.4 / 10" wraps across three physical lines with the
# GPA landing last. Read alone it carries no degree, institution, or year of
# its own, so the "no qualification signal" check just below would file it
# under Skills as if it were a stray trait sentence -- moving a grade that
# plainly belongs to the qualification right above it into an unrelated
# section instead of onto the end of that qualification's own line.
BARE_GPA_LINE_RE = re.compile(r"^(?:GPA|CGPA)\s*:?\s*[\d.]+(?:\s*/\s*[\d.]+)?\.?$", re.IGNORECASE)

# Where a subject name stops. Everything from here on is a grade, a thesis,
# a skills list or the start of the next entry -- never part of the subject.
SUBJECT_STOP_RE = re.compile(
    r"\b(?:GPA|CGPA|Grade|Grades|Percentage|Marks|Thesis|Dissertation|Skills?"
    r"|Knowledge|Modules?|Coursework|Distinction|Merit|Pass|First Class"
    r"|Supervisor|Awarded|Expected|Completed)\b|[|/]|\s{3,}",
    re.IGNORECASE,
)
MAX_SUBJECT_WORDS = 8


MONTH_ANYWHERE_RE = re.compile(MONTH_WORD, re.IGNORECASE)
# How far past the institution name a country may sit and still belong to it.
COUNTRY_WINDOW_CHARS = 40


def _is_plausible_institution(name: str) -> bool:
    """An institution's name, not a run of text that happens to end in one.

    INSTITUTION_RE anchors on the word "University"/"College" and takes up to
    six words before it, which on a wrapped line reaches back into the
    previous fact: "Robotics Expected Oct 2026 Middlesex University" was
    captured whole and rendered as the awarding body. A real institution name
    carries no dates and no degree, so those are the tests.
    """
    name = " ".join(name.split()).strip(" ,-–—")
    if not name or len(name.split()) > 8:
        return False
    if CALENDAR_YEAR_RE.search(name) or MONTH_ANYWHERE_RE.search(name):
        return False
    # "Master of Science, London School of Economics" -- the degree must not
    # be swallowed into the institution, in either position.
    if DEGREE_RE.search(name):
        return False
    return True


def _is_plausible_subject(subject: str) -> bool:
    """A subject is a short noun phrase of words. Anything longer, or mostly
    punctuation and digits, is a mis-parse -- and a mis-parsed subject is
    worse than none, because the verbatim fallback would have been correct."""
    subject = subject.strip()
    # A bracket left dangling means the parse cut through a parenthesis --
    # "Doctor of Philosophy (PhD) in Education" leaves ") in Education", and
    # "Bachelor of Education (Mathematics and Science)" leaves an open one.
    if subject.count("(") != subject.count(")"):
        return False
    if not (2 < len(subject) <= 80):
        return False
    words = subject.split()
    if not (1 <= len(words) <= MAX_SUBJECT_WORDS):
        return False
    letters = sum(c.isalpha() or c.isspace() for c in subject)
    if letters / len(subject) < 0.85:
        return False
    # Only an exact heading is rejected, not any phrase containing one.
    # _find_heading_key matches contained phrases, so "Education (Mathematics
    # and Science)" -- a real subject -- resolves to the Qualifications
    # heading and the subject is thrown away.
    return _normalize_heading(subject) not in _official_headings()


def _extract_qualification_fields(text: str) -> dict[str, Any]:
    """Pull degree / institution / country / year out of one qualification line.

    §5 of the conversion spec requires these kept as separate facts rather
    than one opaque string, so a reviewer can correct the institution without
    retyping the degree, and so two degrees never collapse into one line.

    Every field is optional and nothing is inferred: a line that names no
    institution simply has no institution. `format_item` falls back to the
    verbatim source whenever too little was parsed to build a better line, so
    a partial parse can never lose information from the output.
    """
    fields: dict[str, Any] = {}

    degree_match = DEGREE_RE.search(text)
    if degree_match:
        fields["degree"] = degree_match.group(1).strip()

    # Both patterns are tried and the one starting EARLIEST wins, because the
    # earlier start is the fuller name. Preferring either pattern outright
    # truncates the other's case: "University of Technology" is taken out of
    # "Anna University of Technology", and "Academy of Arts" out of "National
    # Academy of Arts" -- each leaving the dropped first word stranded on the
    # end of the subject.
    candidates = [
        m for m in (INSTITUTION_LEADING_RE.search(text), INSTITUTION_RE.search(text))
        if m and _is_plausible_institution(m.group(1))
    ]
    institution = min(candidates, key=lambda m: m.start()) if candidates else None
    if institution:
        fields["institution"] = " ".join(institution.group(1).split()).strip(" ,-–—")

    # The country belongs to the institution, so it is looked for after the
    # institution's name rather than anywhere in the line. A line reading
    # "... LinkedIn Learning, Dubai, UAE" that also names a Bulgarian academy
    # earlier would otherwise take whichever country came first and attach it
    # to the wrong place.
    # Bounded to the words immediately following the institution: a country
    # further away belongs to the next entry, not to this one.
    country_match = None
    if institution:
        window = text[institution.end():institution.end() + COUNTRY_WINDOW_CHARS]
        country_match = COUNTRY_RE.search(window)
    country_match = country_match or COUNTRY_RE.search(text)
    if country_match:
        raw = country_match.group(1)
        fields["country"] = CITY_TO_COUNTRY.get(raw.casefold(), raw)

    # Restricted to real calendar years. A bare four-digit run matches things
    # like a "0101" course code and stores it as the year of the degree.
    years = CALENDAR_YEAR_RE.findall(text)
    if years:
        # The completion year is the one that matters on a qualification, so
        # a range reports its end.
        fields["year"] = years[-1]

    # The subject is what sits between the degree name and the institution --
    # "PhD in Education, University of Cambridge" -> "Education".
    if degree_match:
        # Bounded by real offsets, not by searching for the institution's
        # matched text inside the remainder: INSTITUTION_RE can match a
        # shorter span than the name as written ("Academy of Arts" out of
        # "National Academy of Arts"), and searching leaves the missing words
        # ("... Art Teacher, National") dangling on the end of the subject.
        end = institution.start() if institution and institution.start() > degree_match.end() else len(text)
        after = text[degree_match.end():end]
        subject = after.strip(" ,;:.-–—()")
        # "Bachelor's degree in X": the possessive "'s" sits between the
        # matched degree word and the apostrophe, which \b treats as a word
        # boundary, so DEGREE_RE stops at "Bachelor" and leaves "'s degree
        # in X" as the remainder. Strip the possessive and the repeated
        # word "degree" before the normal connector strip runs, or the
        # rendered line reads "Bachelor, 's degree in X".
        subject = re.sub(r"^['’]s\s+degree\s+", "", subject, flags=re.I)
        subject = re.sub(r"^(?:in|of|,)\s+", "", subject, flags=re.I)
        # A qualification line usually runs on past the subject into grades,
        # thesis titles and the next block of the CV. Cut at the first thing
        # that cannot be part of a subject name; without this, "Bachelors,
        # Arts in History" absorbs "GPA 3.5/4.0 Teaching Skills / Knowledge"
        # and the rendered line reads as nonsense.
        subject = SUBJECT_STOP_RE.split(subject)[0]
        subject = YEAR_RANGE_RE.sub("", subject)
        subject = re.sub(r"\b\d{4}\b", "", subject).strip(" ,;:.-–—()")
        if _is_plausible_subject(subject):
            fields["subject"] = subject

    return fields


# The MDX template's own grants section literally prompts for these five
# fields by name ("Project title, Role, Duration, Funding or External
# Agency" -- plus "Value to the University" some CVs add themselves). A CV
# that fills the template directly writes ONE of these exact label words
# per line, e.g. "Role: Producer and Studio Liaison, MDX Studios" -- a
# completely different shape from the free-form "Consultant: <project
# title>" header _structure_grants was originally built for, where the
# label IS the role rather than naming a field. Checked first, and more
# specifically, so this never gets misread by the older, looser fallback:
# without it, EVERY labelled line was treated as its own new grant entry
# with the label word itself stored as the "role" and the real value
# mislabelled as "project_title" -- five entries per real project, each
# scrambled ("Role: Project Title" / "Project Title: <actual role text>").
GRANT_FIELD_LABEL_RE = re.compile(
    r"^(Project\s*Title|Role|Duration|Funding(?:\s+or\s+External\s+Agency)?|"
    r"Value\s+to\s+the\s+University)\s*:\s*(.*)$",
    re.IGNORECASE,
)
_GRANT_FIELD_NAMES = {
    "project title": "project_title",
    "role": "role",
    "duration": "duration",
    "funding": "funding_agency",
    "funding or external agency": "funding_agency",
    "value to the university": "value_to_university",
}


def _structure_grants(body_items: list[str]) -> list[dict[str, Any]]:
    """Turn a funded-projects block into one structured item per project.

    Two source shapes, checked in order:

    1. The MDX template's own explicit field labels -- see
       GRANT_FIELD_LABEL_RE above. "Project Title:" opens a new entry;
       "Role:", "Duration:", "Funding...:" and "Value to the University:"
       add a field to whichever entry is currently open.

    2. CVs that instead write a titled header followed by loose detail
       lines:
           Consultant: "Teaching at the Right Level (TaRL)..."
           - Co-PI with Prof X and Dr Y (Funded by FCDO/DARE-RC, 2025-26)
           - Qualitative research lead and project manager
       Here the header supplies the role and title, and the "(Funded by
       ..., dates)" parenthetical -- wherever it appears among the detail
       lines -- supplies the funder and duration.

    `source_text` stays a verbatim line from the CV: the detail lines
    commonly carry bullet markers in the original, so stitching several
    together would no longer be an exact substring and would (correctly)
    be dropped by the no-fabrication check.
    """
    grants: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for text in body_items:
        field_match = GRANT_FIELD_LABEL_RE.match(text)
        if field_match:
            label = " ".join(field_match.group(1).split()).lower()
            value = field_match.group(2).strip().strip('“”"“”')
            field_name = _GRANT_FIELD_NAMES.get(label)
            if field_name == "project_title" or current is None:
                current = {"fields": {}, "source_text": text}
                grants.append(current)
            if field_name and value:
                current["fields"][field_name] = value
            continue

        label_match = ENTRY_LABEL_RE.match(text)
        if label_match and ":" in text:
            role, _, title = text.partition(":")
            current = {
                "fields": {
                    "role": role.strip(),
                    "project_title": title.strip().strip('“”"“”'),
                },
                "source_text": text,
            }
            grants.append(current)
            continue

        if current is None:
            current = {"fields": {"project_title": text}, "source_text": text}
            grants.append(current)
            continue

        funded = FUNDED_RE.search(text)
        if funded:
            current["fields"]["funding_agency"] = funded.group(1).strip(" .,")
            if funded.group(2):
                current["fields"]["duration"] = normalize_date_range(funded.group(2).strip(" .,"))
            continue

        # A CV listing personal/academic projects rather than externally
        # funded ones commonly gives each its own header with no "Role:" /
        # "Project Title:" label and no "(Funded by ...)" line at all --
        # just the project name (and often a context clause) ending in its
        # own date range, the same shape used elsewhere in this module to
        # recognise a job or qualification entry's own header line. Without
        # this, only the FIRST such project (matched by pure luck if its
        # name happened to contain a colon) was ever captured -- every
        # later one was silently discarded, not even reaching the Unmapped
        # safety net as its own reviewable line, because nothing here ever
        # created an item for it.
        if ENTRY_END_YEAR_RE.search(text):
            # Guard against a line that is nothing BUT date debris (a PDF's
            # own line-wrap can split a project's own header mid-phrase,
            # leaving a orphaned "2023 - Apr 2025" fragment behind) --
            # require real content to remain once the trailing date and any
            # dangling month name are stripped, the same "is this actually
            # a title or just date remnant" check used for employment dates.
            head = TRAILING_MONTH_RE.sub("", ENTRY_END_YEAR_RE.sub("", text)).strip(" ,-–—")
            if len(head) >= 10:
                current = {"fields": {"project_title": text}, "source_text": text}
                grants.append(current)
    return grants


# Checked in order -- a heading like "SELECTED UPCOMING PEER-REVIEWED
# PUBLICATIONS" names two of these, and the earlier entry is the one that
# actually characterises the group.
PUBLICATION_SUBGROUP_RULES: list[tuple[tuple[str, ...], str]] = [
    (("upcoming", "forthcoming", "in preparation", "submitted"), "forthcoming"),
    (("conference", "presentation", "symposium", "panel"), "conference"),
    (("blog", "media", "report", "online", "industry", "government"), "industry_government"),
    (("journal", "peer-review", "peer review"), "journal"),
    (("book chapter", "chapters", "books"), "book_chapter"),
]

def _publication_subgroup(line: str) -> str | None:
    low = line.lower()
    for needles, subgroup in PUBLICATION_SUBGROUP_RULES:
        if any(n in low for n in needles):
            return subgroup
    return None


LETTERHEAD_SECTIONS = {"full_name", "job_title", "contact_info", "email"}

# Two real, separate posts glued into one CV line by a coordinating "and"
# ("Senior Lecturer, International and Comparative Education, and Head of
# Centre for Academic Success, Middlesex University, Dubai Campus"). The
# template's own instructions ask for these as separate title lines ("List
# each title individually... Administrative titles should follow the
# format 'Title, Centre or Institute Name.'"), but nothing upstream ever
# split the source line apart.
#
# Narrow, curated list of real academic/administrative leadership titles --
# deliberately not a bare "\band\b" split, which would just as happily
# break "International and Comparative Education" (a department name, not
# a second post) in the middle.
ADMIN_TITLE_CONNECTOR_RE = re.compile(
    r",?\s+and\s+((?:Head|Director|Dean|Chair|Provost|Vice[- ]Provost"
    r"|Vice[- ]Chancellor|Pro[- ]Vice[- ]Chancellor|Assistant Dean"
    r"|Associate Dean|Convenor|Coordinator)\s+of\b.*)$",
    re.I,
)

# A job title line commonly ends with the institution -- and, at a branch
# campus, the named campus too -- the person holds it at ("...Head of
# Centre for Academic Success, Middlesex University, Dubai Campus"). That
# tail reads as an address fragment glued onto the title, not part of it,
# and Present Employment already states the employer in full -- keeping it
# here is redundant as well as visually wrong (real feedback: "job title
# shows as an address"). Stripped only from the END of the line, and only
# when it resolves to a real institution keyword, so a genuine department
# name with no institution word in it ("International and Comparative
# Education") is never touched.
TRAILING_INSTITUTION_RE = re.compile(
    r",\s*[A-Z][\w.&'-]*(?:\s+[\w.&'-]+){0,6}\s+"
    r"(?:University|College|Institute|Institution|Academy|Polytechnic|School)"
    # The trailing campus/city name is commonly NOT its own comma-separated
    # fragment -- "Middlesex University Dubai" and "Middlesex University,
    # Dubai Campus" are both real forms seen live, so the comma before it
    # has to be optional, not required.
    r"(?:\s*,?\s*[A-Z][\w.&'-]*(?:\s+[\w.&'-]+){0,3}(?:\s+Campus)?)?"
    r"\s*$"
)


def _strip_trailing_institution(text: str) -> str:
    return TRAILING_INSTITUTION_RE.sub("", text).strip()


def _clean_job_titles(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clean up a job_title value: split two real posts glued together by a
    coordinating "and" into two lines (joined by "\\n" -- template_engine
    renders each as its own paragraph under the same "Job title:" field,
    matching how a multi-line formatter result is already handled for body
    content), and strip a trailing institution/campus tail from each
    resulting line. Both changes are flagged at reduced confidence for
    review rather than presented as clean and certain, since the split
    point and the institution boundary -- while strong, curated signals --
    are still judgement calls about where a title actually ends.
    """
    for item in items:
        if item["section"] != "job_title":
            continue
        value = item["fields"].get("value", "")
        if not isinstance(value, str) or "\n" in value:
            continue
        match = ADMIN_TITLE_CONNECTOR_RE.search(value)
        if match:
            first = _strip_trailing_institution(value[:match.start()].rstrip(" ,"))
            second = _strip_trailing_institution(match.group(1).strip())
            if not (first and second):
                continue
            item["fields"]["value"] = f"{first}\n{second}"
            item["confidence"] = min(item.get("confidence", 0.7), 0.65)
            item["validation_flags"] = sorted(
                set(item.get("validation_flags", [])) | {"multi_title_split"}
            )
        else:
            stripped = _strip_trailing_institution(value)
            if stripped and stripped != value:
                item["fields"]["value"] = stripped
                item["confidence"] = min(item.get("confidence", 0.7), 0.65)
                item["validation_flags"] = sorted(
                    set(item.get("validation_flags", [])) | {"institution_stripped_from_title"}
                )
    return items


def _drop_name_echoes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove body items that are nothing but the person's own name.

    A CV prints its owner's name in several places -- a page header, a
    signature under a declaration, a repeated letterhead. When the source
    document's layout scrambles during extraction, those copies land inside
    whatever content section was open at the time, and "ANUJITH ANTONY"
    shows up as a line item under Qualifications.

    The name is never legitimate body content: it already has its own
    letterhead field. Dropping these echoes also stops the drafted biography
    reading "X holds X", since it would otherwise treat the stray line as
    the person's highest qualification.
    """
    name_item = next((i for i in items if i["section"] == "full_name"), None)
    if not name_item:
        return items
    name = " ".join(
        ((name_item.get("fields", {}) or {}).get("value") or "").split()
    ).casefold()
    if not name:
        return items

    stripped_name = HONORIFIC_RE.sub("", name).strip()
    variants = {name, stripped_name}

    kept = []
    for item in items:
        if item["section"] in LETTERHEAD_SECTIONS:
            kept.append(item)
            continue
        text = " ".join(item.get("source_text", "").split()).casefold().strip(" ,.;:-")
        if text in variants:
            continue
        kept.append(item)
    return kept


# "SALESMAN Didier Sachs / Los Santos, CA / 2008–2011" -- a full job entry's
# header (title, employer, location, start year) glued onto one line with no
# space between the title and what follows. Precise enough to be a safe
# signal on its own: requires a slash-separated "Employer / City, ST / Year"
# tail, which nothing except a real employment entry writes. Validated
# against the full corpus with zero false positives before being wired in.
# Title and employer are told apart by CASE, not just position: this
# template (and most US-style résumés using the same convention) prints the
# job title in ALL CAPS and the employer name in Title Case ("SALESMAN
# Didier Sachs", "ACCOUNT CONSULTANT Legal Genius"). A single lazy/greedy
# word-run can't find the right split point on its own -- it either grabs
# only the first word of a two-word title ("ACCOUNT" / "CONSULTANT Legal
# Genius") or bleeds one letter of the employer's name into the title.
# Requiring the title run to be entirely uppercase and the employer run to
# be entirely Title Case makes the boundary unambiguous.
_CAPS_WORD = r"[A-Z][A-Z'&]*"
_TITLECASE_WORD = r"[A-Z][a-z'&]*"
EMPLOYMENT_ENTRY_HEADER_RE = re.compile(
    rf"^(?P<title>{_CAPS_WORD}(?:\s+{_CAPS_WORD}){{0,4}})\s+"
    rf"(?P<employer>{_TITLECASE_WORD}(?:[\s&.,'-]+{_TITLECASE_WORD})*)\s*/\s*"
    r"(?P<city>[A-Za-z .]+),\s*(?P<state>[A-Z]{2})\s*/\s*"
    r"(?P<start>(?:19|20)\d{2})"
    r"(?:\s*[-–—]\s*(?P<end>(?:19|20)\d{2}|[Pp]resent|[Pp]resent [Tt]ime|[Cc]urrent))?"
)


def _reclassify_resume_crosstalk(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fix Skills/Awards catching content that belongs elsewhere.

    A résumé template built from a table or side-by-side text boxes commonly
    extracts with its reading order scrambled -- a heading ends up paired
    with the WRONG column's content. One real CV had an "awards" heading
    immediately followed by a list of software tools and soft skills, and a
    "key skills" heading followed by a degree, two real awards, and two full
    job entries. Section-boundary detection can't fix this (that class of
    general heuristic was tried three times this session and rejected each
    time for misclassifying unrelated CVs -- see FIXLOG.md); this instead
    re-examines items ALREADY filed under the two sections most exposed to
    this scramble, using signals precise enough to have zero false positives
    across the full test corpus.

    Deliberately narrow to two directions, not four. A third direction --
    moving stray skill/tool names back out of Awards -- was tried and
    dropped: without a positive "this looks like a skill" signal, the only
    available proxy (short, no year, no award keyword) also caught a
    genuine sales-ranking achievement and a stray sentence fragment. Content
    that doesn't match one of the two signals below is left exactly where
    the heading put it, same as before this function existed.
    """
    for item in items:
        if item["section"] not in ("skills", "awards"):
            continue
        text = item["source_text"]

        if DEGREE_RE.search(text):
            item["section"] = "qualifications"
            item["fields"] = _extract_qualification_fields(text)
            item["confidence"] = min(item.get("confidence", 0.8), 0.7)
            item["validation_flags"] = sorted(
                set(item.get("validation_flags", [])) | {"rerouted_by_content"}
            )
            continue

        match = EMPLOYMENT_ENTRY_HEADER_RE.match(text)
        if match:
            end_raw = (match.group("end") or "").strip()
            ongoing = end_raw.lower() in ("present", "present time", "current")
            target = "present_employment" if ongoing else "previous_employment"
            employer_key = "unit" if target == "present_employment" else "employer"
            item["section"] = target
            # The header packs title, employer, city/state and year(s) onto
            # one glued line with no separator ("SALESMAN Didier Sachs / Los
            # Santos, CA / 2008-2011") -- named groups pull title and
            # employer apart directly rather than re-parsing the header text,
            # which used to put the person's own responsibility sentences
            # on the wrong side of the split and, worse, could leave the
            # employer's name sitting inside what was shown as the job
            # title. Grouping upstream sometimes also welds the header to
            # the job's own responsibility bullets into the same item; those
            # are real content and must not be dropped, so they are kept as
            # a separate, indented continuation line rather than lost or
            # left glued onto the header.
            fields: dict[str, Any] = {
                "title": match.group("title").strip(),
                employer_key: match.group("employer").strip(),
                "start_date": match.group("start"),
                "end_date": "" if ongoing else end_raw,
            }
            if ongoing:
                fields["is_current"] = True
            header_line = _employment_line(fields, employer_key, is_present=(target == "present_employment"))
            trailing = text[match.end():].strip(" ,-–—")
            if trailing and header_line:
                fields["_line_override"] = f"{header_line}\n{trailing}"
            item["fields"] = fields
            item["confidence"] = min(item.get("confidence", 0.8), 0.7)
            item["validation_flags"] = sorted(
                set(item.get("validation_flags", [])) | {"rerouted_by_content"}
            )

    return items


def _role_text_before_dates(text: str) -> str:
    """The role/title part of an entry, i.e. everything before the trailing
    date column. Still a verbatim prefix of the source line."""
    head = PIPE_SPLIT_RE.split(text)[0].strip()
    return head or text.strip()


def _promote_present_role(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find the CV's *current* post and file it under Present Employment.

    Academic CVs rarely have a "Present Employment" heading -- the current
    role is normally just the first entry under Teaching/Experience, marked
    by "2026 onwards", "present", or "current". Without this the MDX
    template's Present Employment section comes out empty even when the CV
    plainly states the person's current job, and the letterhead's Job title
    falls back to whatever fragment happened to sit near the email.
    """
    # A present_employment item can already exist without ever going
    # through the "promotion" path below -- e.g. _generic_employment's own
    # "is_current and the employer name matches" check routes it there
    # directly. That item's own parsed title is still more trustworthy than
    # whatever the letterhead scan guessed from nearby text (a nearby
    # fellowship or scholarship line matching a title keyword by
    # coincidence, say), so the same override applies even when nothing
    # here needs to be "promoted" -- only the job_title guess is fixed.
    existing_present = next((it for it in items if it["section"] == "present_employment"), None)
    if existing_present:
        title = (existing_present.get("fields") or {}).get("title", "").strip()
        if title:
            items = [i for i in items if i["section"] != "job_title"]
            items.append({
                "section": "job_title", "fields": {"value": title},
                "source_text": existing_present["source_text"], "confidence": 0.7,
            })
        return items

    # An entry already filed under Previous Employment (because its section
    # heading was a plain "EMPLOYMENT HISTORY" with no separate "Present"
    # heading) can already carry a cleanly parsed title/employer in its
    # `fields` -- reuse that directly rather than re-deriving a role from
    # raw text. The old text-only re-derivation below (`_role_text_before_
    # dates`) only ever strips a "|"-separated tail; against a merged item
    # whose verbatim source_text runs title + employer + a full
    # responsibility paragraph together, it returned the ENTIRE blob as the
    # "role" and that blob became both the letterhead's job title and a
    # bogus duplicate Present Employment entry, sitting alongside the
    # already-correct Previous Employment one.
    for it in items:
        if it["section"] != "previous_employment":
            continue
        fields = it.get("fields") or {}
        title = fields.get("title", "").strip()
        if not (title and fields.get("is_current") and PRESENT_ROLE_RE.search(it["source_text"])):
            continue
        it["section"] = "present_employment"
        if "employer" in fields:
            fields["unit"] = fields.pop("employer")
        items = [i for i in items if i["section"] != "job_title"]
        items.append({
            "section": "job_title", "fields": {"value": title},
            "source_text": it["source_text"], "confidence": 0.7,
        })
        return items

    for it in items:
        text = it["source_text"]
        if not PRESENT_ROLE_RE.search(text):
            continue
        role = _role_text_before_dates(text)
        if not _has_title_keyword(role.lower()):
            continue
        if not _looks_like_job_title(role):
            continue
        items.append({
            "section": "present_employment",
            "fields": {"title": role, "end_date": ""},
            "source_text": text,
            "confidence": 0.6,
        })
        # The title on the CV's own current-role line beats anything the
        # letterhead scan guessed from text near the email address, so it
        # replaces an earlier guess rather than deferring to it.
        items = [i for i in items if i["section"] != "job_title"]
        items.append({
            "section": "job_title", "fields": {"value": role},
            "source_text": text, "confidence": 0.7,
        })
        break
    return items


# A letterhead label the CV itself writes out ("Job title: Senior
# Lecturer..."), matching the same set _extract_letterhead already strips
# before storing a value -- so a raw preamble line still carrying its label
# can be recognised as "the same fact already captured", not new content.
_PREAMBLE_LETTERHEAD_LABEL_RE = re.compile(
    r"^\s*(?:job\s*titles?|title|contact|phone|tel|telephone|mobile|email|e-mail"
    r"|address|name)\s*:\s*",
    re.IGNORECASE,
)


def _biography_from_preamble(
    preamble: list[str], letterhead_items: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """An unlabeled summary paragraph sitting between the contact block and
    the CV's first recognised heading -- no "SUMMARY"/"PROFILE"/"ABOUT"
    heading above it at all, just prose right under the name.

    This is a common, ordinary CV shape, and it used to be a silent loss:
    nothing here classifies preamble CONTENT into a section -- the preamble
    is only ever scanned for name/title/contact candidates -- so the
    person's own hand-written biography fell all the way through to the
    Unmapped safety net, which does not appear in the generated document.
    A much thinner, auto-drafted biography (bio_draft.py) then took its
    place, because that drafter only runs when no real biography item
    exists at all -- it had no way to know a real one was sitting right
    there, misfiled.

    Scoped narrowly: the same prose-shape test biography content already
    gets under a real heading (`_is_biography_prose` -- long enough to read
    as a sentence, not phone/email-shaped, not dominated by uppercase), and
    never a line the letterhead scan already claimed as the name, title,
    contact number, or email.
    """
    used = {(i.get("source_text") or "").strip() for i in letterhead_items}
    for line in preamble:
        text = line.strip()
        if not text or text in used:
            continue
        # _extract_letterhead stores a label-STRIPPED value ("Senior
        # Lecturer...", not "Job title: Senior Lecturer..."), so a raw
        # preamble line that still carries its own label never matched the
        # exact-string check above -- it read as 15 words of prose and
        # became a second, bogus "biography", right alongside the real one,
        # once a CV happened to spell its title out long enough to clear
        # the word-count bar. Stripped the same way here, it correctly
        # collapses onto the value already captured.
        unlabelled = _PREAMBLE_LETTERHEAD_LABEL_RE.sub("", text).strip()
        if unlabelled != text and unlabelled in used:
            continue
        if _is_biography_prose(text):
            return {
                "section": "biography", "fields": {},
                "source_text": text, "confidence": 0.75,
            }
    return None


def classify_rule_based(cv_text: str, source_document: str) -> list[dict[str, Any]]:
    raw_lines = cv_text.splitlines()

    # A line extraction.py tagged as sourced from a DOCX header/footer (see
    # HEADER_FOOTER_MARKER's docstring) is page furniture by construction,
    # not body content -- but unlike a PDF's repeated running header, it
    # was only ever read once, so _find_running_headers' repeat-count check
    # can never recognise it on its own. Folded into the SAME running_headers
    # set _find_running_headers already produces: stripped from body_lines
    # exactly like any other running header, and still offered to
    # _extract_letterhead below, so a genuine identifier or contact detail
    # that happens to sit in a footer is not lost, only kept out of whatever
    # section heading happens to be physically last in the document.
    header_footer_lines = {
        " ".join(l[len(HEADER_FOOTER_MARKER):].split())
        for l in raw_lines if l.startswith(HEADER_FOOTER_MARKER)
    }
    lines = [
        l[len(HEADER_FOOTER_MARKER):] if l.startswith(HEADER_FOOTER_MARKER) else l
        for l in raw_lines
    ]
    cv_text = "\n".join(lines)

    running_headers = _find_running_headers(lines) | header_footer_lines
    body_lines = [l for l in lines if " ".join(l.split()) not in running_headers]
    body_lines = _merge_wrapped_headings(body_lines)
    body_lines = _merge_split_letter_spaced_headings(body_lines)
    body_lines = _split_embedded_heading_runs(body_lines)
    preamble, sections, authoritative = _split_into_sections(body_lines)

    # The running header goes in front of the letterhead candidates: on an
    # academic CV it is usually the contact strip, and it is the one line we
    # know the author intended as identifying information.
    items: list[dict[str, Any]] = _extract_letterhead(
        sorted(running_headers, key=len, reverse=True) + preamble, cv_text, source_document
    )

    preamble_bio = _biography_from_preamble(preamble, items)
    if preamble_bio:
        items.append(preamble_bio)

    current_pub_subgroup: str | None = None
    for key, raw_body_lines in sections.items():
        if key == "_ignored":
            # Recognised as a boundary, but has no MDX section to hold it --
            # see SYNONYM_HEADINGS. Its lines are otherwise dropped
            # entirely, without even a junk-line check -- correct for a
            # block that really is nothing but visa/passport/personal
            # trivia, but a "Personal Details" block commonly embeds one
            # genuine fact among the junk: "Languages Known: English, Hindi
            # and Arabic" sitting next to Date of Birth and Driving Licence.
            # Dropping the whole block wholesale silently threw that away
            # too. Rescue only this one specific, unambiguous pattern before
            # discarding the rest -- not a general "scan ignored blocks for
            # anything useful" rule, which would just reopen the same
            # force-fit risk this bucket exists to avoid.
            for raw_line in raw_body_lines:
                match = LANGUAGE_LIST_LINE_RE.match(raw_line.strip())
                if match:
                    items.append({
                        "section": "language_proficiency", "fields": {},
                        "source_text": raw_line.strip(), "confidence": 0.75,
                    })
            continue
        def _group(lines: list[str]) -> list[str]:
            # Junk is filtered BEFORE grouping, not after. Filtering
            # afterwards discards a whole merged item because part of it
            # was junk: one CV lost the real responsibility "Answering the
            # phone and directing calls" because the vendor's advertising
            # ran on directly after it and the two merged into one item.
            # A junk line becomes a SEGMENT_BREAK rather than simply
            # vanishing. Removing it outright makes its neighbours adjacent
            # when they were not, and grouping then merges them into text
            # that appears nowhere in the CV -- discarded by the verbatim
            # guard, losing a real item.
            return _group_into_items(
                [SEGMENT_BREAK if (_is_junk_line(l) or _is_bare_contact_line(l)) else l
                 for l in lines],
                section_key=key,
            )

        if key in ("_generic_employment", "present_employment", "previous_employment"):
            # A block under one Employment-type heading can fold in
            # public-engagement content (conferences organised, keynote
            # talks) with no heading of its own -- split that out first, so
            # it never even reaches employment field-parsing.
            for zone_kind, zone_lines in _split_employment_and_practice_zones(raw_body_lines):
                if zone_kind == "knowledge_exchange":
                    for text in _group(zone_lines):
                        if KNOWLEDGE_EXCHANGE_MARKER_RE.match(text):
                            continue  # the label line itself, not content
                        items.append({
                            "section": "knowledge_exchange", "fields": {},
                            "source_text": text, "confidence": 0.6,
                            "validation_flags": ["rerouted_by_content"],
                        })
                    continue
                body_items = _group(zone_lines)
                if key == "_generic_employment":
                    for text, fields in _employment_body_entries(body_items, "employer"):
                        employer = fields.get("employer", "").lower()
                        is_current = not fields.get("end_date")
                        target = "present_employment" if (is_current and "middlesex" in employer) else "previous_employment"
                        if target == "present_employment" and "employer" in fields:
                            fields["unit"] = fields.pop("employer")
                        items.append({
                            "section": target, "fields": fields,
                            "source_text": text, "confidence": 0.65,
                        })
                else:
                    employer_key = "unit" if key == "present_employment" else "employer"
                    for text, fields in _employment_body_entries(body_items, employer_key):
                        items.append({
                            "section": key, "fields": fields,
                            "source_text": text, "confidence": 0.8,
                        })
            continue

        body_items = _group(raw_body_lines)

        if key == "grants":
            for grant in _structure_grants(body_items):
                items.append({
                    "section": "grants", "fields": grant["fields"],
                    "source_text": grant["source_text"], "confidence": 0.75,
                })
            continue

        for text in body_items:
            if key == "publications":
                # Only a line the heading matcher itself recognises counts as
                # a sub-heading. Keying off keyword presence alone would
                # misread an ordinary citation (which naturally contains the
                # word "Journal") as a group divider and swallow it.
                if _find_heading_key(text) == "publications":
                    current_pub_subgroup = _publication_subgroup(text) or current_pub_subgroup
                    continue
                fields = {"subgroup": current_pub_subgroup} if current_pub_subgroup else {}
                items.append({
                    "section": "publications", "fields": fields,
                    "source_text": text, "confidence": 0.8,
                })
                continue

            if key == "profiles_links":
                # Content under a "Profiles and Links" heading still needs
                # its platform and address separated, both so the generated
                # line reads "ORCID: https://..." and so the whole-document
                # scan below can tell it has already captured this link.
                parsed = identifiers.find_identifiers(text)
                # No recognisable address in the line: keep it verbatim
                # rather than labelling the whole line as a "platform", which
                # would render as its own name with nothing after it.
                fields = (
                    {"platform": parsed[0]["platform"], "url": parsed[0]["url"]}
                    if parsed else {}
                )
                items.append({
                    "section": key, "fields": fields,
                    "source_text": text, "confidence": 0.8,
                })
                continue

            if key == "biography":
                # A heading like "SUMMARY OF SKILLS AND QUALIFICATIONS" holds
                # more than a biography paragraph: a résumé commonly follows
                # its narrative summary with a bare skills/traits list under
                # the same heading. §5 wants biography to be a written
                # paragraph, not a bullet dump -- and neither a skill trait
                # ("Fluent in English.") nor a stray degree mention belongs
                # there, so each line is sorted before being accepted.
                #
                # Prose is checked FIRST, degree-mention checked only for
                # what's left. A real biography sentence often names a degree
                # in passing ("Dr Camilla holds a PhD in Education from the
                # University of Cambridge.") -- checking DEGREE_RE first
                # rerouted that whole sentence to Qualifications and left
                # BIOGRAPHY empty, which is a worse outcome than the polluted
                # section this was meant to fix. Only a SHORT line -- one
                # that reads as a bare fact, not a sentence about the person
                # -- is treated as a qualification stranded under the wrong
                # heading.
                if _is_biography_prose(text):
                    items.append({
                        "section": "biography", "fields": {},
                        "source_text": text, "confidence": 0.8,
                    })
                    continue
                if DEGREE_RE.search(text):
                    items.append({
                        "section": "qualifications", "fields": _extract_qualification_fields(text),
                        "source_text": text, "confidence": 0.7,
                    })
                    continue
                # Not a sentence, not a qualification -- most likely a bare
                # skill or trait ("Active, Self-motivated."). There is no MDX
                # section for a skills list, so per §8 it is left
                # unclassified here and picked up by the unmapped-content
                # safety net rather than being force-fit into Biography just
                # because it shared a heading with one.
                continue

            if key == "qualifications":
                # A résumé's "SUMMARY OF QUALIFICATIONS" heading is not the
                # same thing as the MDX template's Qualifications section --
                # it commonly introduces a paragraph of skills/traits
                # ("Huge experience in managing all marketing and
                # advertising...", "Excellent skills to identify and resolve
                # problems...") with the person's actual degree tucked in as
                # just one line among them. Left as-is, that prose gets
                # published under Qualifications, which the spec reserves
                # for actual credentials. A line with no qualification
                # signal at all -- no degree name, no institution, not even
                # a year -- almost certainly isn't one, and reads as a
                # skill/summary sentence instead; same treatment biography
                # already gets when its heading is shared with a skills list.
                if (
                    BARE_GPA_LINE_RE.match(text.strip())
                    and items and items[-1]["section"] == "qualifications"
                ):
                    prev = items[-1]
                    prev["source_text"] = f"{prev['source_text']} {text.strip()}".strip()
                    continue
                # A short bare line ("Fusion VFX", "Dolby Atmos
                # Certification") directly following an already-genuine
                # qualification item is a continuation of THAT item's own
                # certification list, not stray skills prose -- prose long
                # enough to be the false positive this whole check exists
                # for ("Huge experience in managing all marketing and
                # advertising...") never happens to also be this short.
                # Without this, a certification list that a PDF export
                # rendered one item per line got scattered: some items
                # rescued back to Qualifications only by chance (this one
                # also happening to contain the word "Certification",
                # tripping an unrelated routing rule), others -- with no
                # such lucky word match -- left stranded under Skills.
                # A short, bare noun-phrase item from a certification list
                # ("Fusion VFX", "Dolby Atmos Certification", "Advanced
                # Editing") has none of the degree/institution/year signals
                # below either, but it is nothing like the false positive
                # this whole check exists to catch: real skills/trait prose
                # ("Huge experience in managing all marketing and
                # advertising...", "Excellent skills to identify and resolve
                # problems...") is always a full sentence, comfortably
                # longer than this. Checking length alone, independent of
                # whatever the previous item ended up classified as, matters
                # specifically because a PDF export commonly puts one
                # certification per line with nothing to visually group
                # them -- each line hits this same check in isolation, so
                # even the item directly before this one may itself already
                # be sitting in the wrong section at this point in the
                # pipeline, before routing's later, unrelated rescue (a
                # coincidental keyword match) gets a chance to run.
                if len(text) <= 40 and not re.search(r"[.!?]\s*$", text):
                    items.append({
                        "section": "qualifications", "fields": {},
                        "source_text": text, "confidence": 0.7,
                    })
                    continue
                if not (
                    DEGREE_RE.search(text) or INSTITUTION_RE.search(text)
                    or INSTITUTION_LEADING_RE.search(text) or CALENDAR_YEAR_RE.search(text)
                ):
                    items.append({
                        "section": "skills", "fields": {},
                        "source_text": text, "confidence": 0.6,
                        "validation_flags": ["rerouted_by_content"],
                    })
                    continue
                items.append({
                    "section": key, "fields": _extract_qualification_fields(text),
                    "source_text": text, "confidence": 0.8,
                })
                continue

            if key in ("associations", "editorial_roles"):
                # The template groups these, but §5 asks that the kinds stay
                # distinguishable: a fellowship is not a membership, and an
                # editor, a board member, a reviewer and an external examiner
                # are four different roles. The distinction is carried as a
                # field so the reviewer sees it without it changing where the
                # item is filed.
                fields: dict[str, Any] = {}
                kind = _role_kind(text)
                if kind:
                    fields["kind"] = kind
                items.append({
                    "section": key, "fields": fields,
                    "source_text": text, "confidence": 0.8,
                })
                continue

            items.append({
                "section": key, "fields": {},
                "source_text": text, "confidence": 0.8,
            })

    # Scholarly profiles and identifiers are found by scanning the whole
    # document rather than by looking under a heading: almost no source CV
    # has a "Profiles and Identifiers" heading, but many carry an ORCID in
    # the letterhead, a Scholar link in a footer, or a LinkedIn address that
    # exists only as a Word hyperlink target.
    already_linked = {
        (it["fields"].get("url") or "").rstrip("/").casefold()
        for it in items if it["section"] == "profiles_links"
    }
    for found in identifiers.find_identifiers(cv_text):
        if found["url"].rstrip("/").casefold() in already_linked:
            continue
        items.append({
            "section": "profiles_links",
            "fields": {"platform": found["platform"], "url": found["url"]},
            "source_text": found["source_text"],
            "confidence": 0.9,  # a URL's shape identifies its platform unambiguously
        })

    items = _drop_name_echoes(items)
    # Re-file items whose wording points elsewhere. Sections the CV named
    # with the template's own heading text are left untouched.
    items = routing.apply_routing(items, authoritative)
    items = _reclassify_resume_crosstalk(items)
    items = _promote_present_role(items)
    items = _clean_job_titles(items)

    if not any(it["section"] == "job_title" for it in items):
        for target_section in ("present_employment", "previous_employment"):
            for it in items:
                if it["section"] != target_section:
                    continue
                guess = _guess_title_from_employment_text(it["source_text"])
                if guess:
                    items.append({
                        "section": "job_title", "fields": {"value": guess},
                        "source_text": it["source_text"], "confidence": 0.5,
                    })
                    break
            else:
                continue
            break
        items = _clean_job_titles(items)

    return items
