"""Turn an approved, structured item into the single line of text that gets
written into the generated DOCX. Falls back to the verbatim source text if a
section has no dedicated formatter or the expected fields are missing --
never fabricates a field that isn't there.
"""
import re
from typing import Any


def _employment_line(fields: dict[str, Any], employer_key: str, is_present: bool) -> str:
    title = fields.get("title", "").strip()
    employer = fields.get(employer_key, "").strip()
    start = fields.get("start_date", "").strip()
    # "present" is only ever true for an actually-ongoing role -- defaulting
    # a missing end date to "present" on a PAST role would fabricate that
    # the person still holds it, which this tool must never do. It is shown
    # when the section itself is Present Employment, or when the CV said
    # "Present"/"Current" in so many words (fields["is_current"]).
    ongoing = is_present or bool(fields.get("is_current"))
    end = fields.get("end_date", "").strip() or ("present" if (start and ongoing) else "")
    parts = [p for p in (title, employer) if p]
    line = ", ".join(parts)
    if not line:
        # Nothing but dates was parsed out. Returning " (2024 - 2026)" here
        # would look like a real entry while saying nothing, so report the
        # failure by returning empty and let format_item fall back to the
        # verbatim source line, which at least carries the full information.
        return ""
    if start or end:
        line += f" ({start} – {end})" if start and end else f" ({start or end})"
    return line


CALENDAR_YEAR_IN_TEXT_RE = re.compile(r"\b(?:19\d{2}|20[0-4]\d)\b")
# A subject that trails off in a month has been cut mid-date.
TRAILING_MONTH_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?$", re.I
)


def _qualification_line(fields: dict[str, Any], source_text: str = "") -> str:
    """Degree, subject, institution, country and year as one readable line.

    Returns empty -- which makes format_item fall back to the verbatim source
    -- whenever the parse is not demonstrably complete. The structured fields
    are worth extracting either way, because the reviewer edits and the
    profile store both use them, but a rebuilt line is only an improvement on
    the source when it has lost nothing. A half-parsed line such as
    "Bachelor of Science, with Honours (BSc Hons), Information Technology Jun
    — Middlesex University" reads as finished while having dropped the year,
    which is worse than simply printing what the CV said.
    """
    degree = fields.get("degree", "").strip()
    institution = fields.get("institution", "").strip()
    if not (degree and institution):
        return ""

    # The source states a year but the parse didn't capture one: incomplete.
    if CALENDAR_YEAR_IN_TEXT_RE.search(source_text) and not str(fields.get("year", "")).strip():
        return ""
    if TRAILING_MONTH_RE.search(fields.get("subject", "").strip()):
        return ""

    subject = fields.get("subject", "").strip()
    head = f"{degree}, {subject}" if subject else degree

    tail_parts = [institution, fields.get("country", "").strip()]
    tail = ", ".join(p for p in tail_parts if p)

    line = f"{head} — {tail}"
    year = str(fields.get("year", "")).strip()
    if year:
        line += f" ({year})"
    return line


# Fields that describe an item rather than forming part of its text. The
# generic formatter joins every string field it finds, so without this an
# entry tagged kind="Membership" would be REPLACED by the word "Membership"
# and the actual entry would be lost from the document.
METADATA_FIELDS = {"kind", "subgroup", "context", "provenance"}


# Display names for the publication sub-groups the classifier tags items
# with. Rendering-only concern, so it lives here rather than in the
# classifier, which needs the keys but never the prose.
PUBLICATION_SUBGROUP_LABELS = {
    "journal": "Peer-reviewed journals, book chapters, and books",
    "book_chapter": "Book chapters and books",
    "industry_government": "Academic blogs, reports, and media publications",
    "conference": "Selected conference presentations",
    "forthcoming": "Upcoming and forthcoming publications",
}

# The `kind` field on an editorial_roles item (set by rule_classifier's
# _role_kind) doubles as its sub-group: an editorial board member, a
# reviewer and an external examiner are three different appointments, and
# the spec asks that they read as three different lists rather than one
# undifferentiated one -- the same treatment Publications already gets.
# Order here is the print order in the document, not discovery order in the
# CV, so entries group cleanly even when the source interleaves them.
EDITORIAL_KIND_ORDER = [
    "Editor-in-Chief", "Editor", "Editorial board member",
    "Reviewer", "Examiner", "External examiner",
]
EDITORIAL_SUBGROUP_LABELS = {
    "Editor-in-Chief": "Editor-in-Chief roles",
    "Editor": "Editor roles",
    "Editorial board member": "Editorial board memberships",
    "Reviewer": "Reviewer roles",
    "Examiner": "Examiner roles",
    "External examiner": "External examiner roles",
}

GRANT_FIELD_LABELS = [
    ("project_title", "Project Title"),
    ("role", "Role"),
    ("duration", "Duration"),
    ("funding_agency", "Funding Agency"),
]


def _grant_line(fields: dict[str, Any]) -> str:
    """One labelled line per populated field, newline-separated. The caller
    renders each line as its own paragraph, which is how the MDX template
    presents funded projects -- a single run-on line loses the structure
    that makes a grant record readable."""
    lines = [
        f"{label}: {fields[key].strip()}"
        for key, label in GRANT_FIELD_LABELS
        if isinstance(fields.get(key), str) and fields.get(key, "").strip()
    ]
    return "\n".join(lines)


def _publication_line(fields: dict[str, Any], source_text: str) -> str:
    return fields.get("citation") or source_text


def _profile_link_line(fields: dict[str, Any]) -> str:
    platform = fields.get("platform", "").strip()
    url = fields.get("url", "").strip()
    if platform and url:
        return f"{platform}: {url}"
    return platform or url


def format_item(section: str, fields: dict[str, Any], source_text: str) -> str:
    fields = fields or {}
    if fields.get("_line_override"):
        return fields["_line_override"]
    try:
        if section == "present_employment":
            line = _employment_line(fields, "unit", is_present=True)
        elif section == "previous_employment":
            line = _employment_line(fields, "employer", is_present=False)
        elif section == "qualifications":
            line = _qualification_line(fields, source_text)
        elif section == "grants":
            line = _grant_line(fields)
        elif section == "publications":
            line = _publication_line(fields, source_text)
        elif section == "profiles_links":
            line = _profile_link_line(fields)
        elif section == "unmapped":
            line = fields.get("value") or source_text
        elif section in ("teaching_learning", "knowledge_exchange", "committees",
                          "academic_leadership", "awards", "centres_of_excellence",
                          "editorial_roles", "associations"):
            line = fields.get("description") or " — ".join(
                v for k, v in fields.items()
                if k not in METADATA_FIELDS and isinstance(v, str) and v.strip()
            )
        else:
            line = " — ".join(
                v for k, v in fields.items()
                if k not in METADATA_FIELDS and isinstance(v, str) and v.strip()
            )
    except Exception:
        line = ""

    return line.strip() if line and line.strip() else source_text
