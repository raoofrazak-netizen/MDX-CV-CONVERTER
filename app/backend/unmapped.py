"""Account for every line of the source CV, and collect what didn't make it.

§8 of the conversion spec calls this the safety net that makes "don't lose
anything" actually true: content from the raw CV that fits no official MDX
section must appear in an UNMAPPED INFORMATION note at the end of the
document, with enough context for HR to see where it came from -- never
dropped, and never force-fitted into the nearest-sounding section.

The check is done by reconciliation rather than by trusting the classifier to
report its own misses. Every non-trivial line of the source is compared
against the text of every item that was produced; a line no item accounts for
is, by definition, information that would otherwise vanish. That catches the
cases a classifier cannot self-report -- a line silently dropped as junk, a
section heading the matcher didn't recognise, content under a heading that
mapped to nothing.

What is deliberately NOT reported as unmapped:
  * lines already covered by an item (whole or in part -- items merge wrapped
    continuation lines, so a source line is often a substring of an item)
  * recognised section headings, which are structure rather than content
  * the letterhead, which is mapped into the template's own header fields
  * decorative and boilerplate lines carrying no information
"""
import re
from typing import Any

from rule_classifier import (
    _find_heading_key, _is_junk_line, _looks_like_heading_line, _normalize_heading,
)

# A line has to carry some actual information before its absence is worth
# reporting. Page numbers, single words like "Contact", and separator rules
# are structure, not content.
MIN_MEANINGFUL_CHARS = 12
MIN_MEANINGFUL_WORDS = 2

DECORATIVE_RE = re.compile(r"^[\s\-–—_=*.•●▪|/\\]+$")
PAGE_MARKER_RE = re.compile(r"^\s*(?:page\s*)?\d+\s*(?:of\s*\d+)?\s*$", re.I)
# Labels that introduce content rather than being content.
LABEL_ONLY_RE = re.compile(
    r"^\s*(?:contact|address|phone|tel|telephone|mobile|email|e-mail|nationality"
    r"|date of birth|dob|references?|curriculum vitae|cv|resume|personal details"
    r"|profile|objective)\s*:?\s*$",
    re.I,
)


BULLET_PREFIX_RE = re.compile(r"^[\s•●▪‣⁃*\-–—]+")
# Labels the letterhead strips before storing a value: the CV line reads
# "Contact: +971 4 367 8100" but the stored item is the number alone.
LETTERHEAD_LABEL_RE = re.compile(
    r"^\s*(?:job title|title|contact|phone|tel|telephone|mobile|email|e-mail"
    r"|address|name)\s*:\s*",
    re.I,
)
# Below this, a line is not meaningfully "covered" by an item that happens to
# sit inside it -- the rest of the line is real content that went nowhere.
COVERAGE_RATIO = 0.6


def _normalize(text: str) -> str:
    """Comparison form: whitespace collapsed, case folded, and the leading
    bullet glyph removed.

    The bullet matters. Item grouping strips it, so a source line reading
    "-Chaudhary, C.H., (2025) ..." normalises to something the stored item
    ("Chaudhary, C.H., (2025) ...") is not a substring of, and a correctly
    classified publication gets reported as unmapped.
    """
    return " ".join(BULLET_PREFIX_RE.sub("", text).split()).casefold()


def _is_reportable(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < MIN_MEANINGFUL_CHARS:
        return False
    if len(stripped.split()) < MIN_MEANINGFUL_WORDS:
        return False
    if DECORATIVE_RE.match(stripped) or PAGE_MARKER_RE.match(stripped):
        return False
    if LABEL_ONLY_RE.match(stripped):
        return False
    if _is_junk_line(stripped):
        return False
    return True


def find_unmapped(
    cv_text: str, items: list[dict[str, Any]], max_entries: int = 60
) -> list[dict[str, str]]:
    """[{text, context}] for source lines no item accounts for.

    `context` is the section heading the line appeared under -- the "enough
    context that HR can see where it came from" §8 asks for. A line before any
    heading is reported under the source's own top-of-document area.
    """
    covered: list[str] = []
    values: list[str] = []
    for item in items:
        source = item.get("source_text")
        if source is None:
            source = (item.get("source") or {}).get("raw_text", "")
        normalized = _normalize(source)
        if normalized:
            covered.append(normalized)
        # Stored FIELD VALUES count as coverage too, not just the source
        # quote. A structured item can carry information the quote does not:
        # a funded project is assembled from several source lines into one
        # item whose quote is the project title, with the role, duration and
        # funding agency held as fields. Matching on the quote alone would
        # report those other lines as lost when they are in the output.
        for field_value in (item.get("fields") or {}).values():
            if isinstance(field_value, str) and len(field_value.strip()) >= MIN_MEANINGFUL_CHARS:
                normalized_value = _normalize(field_value)
                covered.append(normalized_value)
                values.append(normalized_value)
    covered_blob = "\n".join(covered)

    unmapped: list[dict[str, str]] = []
    seen: set[str] = set()
    context = "Top of document"

    for raw_line in cv_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        heading_key = _find_heading_key(line)
        if heading_key:
            # A heading is structure, not content -- so it is never reported.
            # But it only becomes the CONTEXT LABEL if it reads like a real
            # heading: a wrapped sentence ending "... prepared for open-source
            # robotics education." matches the Qualifications synonyms and
            # would otherwise label everything below it 'From "education."'.
            if _looks_like_heading_line(line, _normalize_heading(line)):
                context = " ".join(line.split()).rstrip(":")
            continue
        if _looks_like_heading_line(line, _normalize_heading(line)):
            # An informal heading with no MDX equivalent -- "LANGUAGE
            # PROFICIENCY", "PROFESSIONAL DEVELOPMENT". rule_classifier
            # treats this the same as a recognised-but-unmapped heading
            # (`_ignored`), so nothing under it is ever turned into an item;
            # matching that here means the unmapped entries that follow are
            # labelled with the heading the source CV actually used, rather
            # than inheriting whatever real MDX heading happened to precede
            # it -- and the heading line itself is structure, not a fact to
            # report as its own orphaned bullet.
            context = " ".join(line.split()).rstrip(":")
            continue

        if not _is_reportable(line):
            continue

        normalized = _normalize(line)
        if normalized in seen:
            continue
        # Substring rather than equality: items merge wrapped continuation
        # lines, so a source line is frequently only part of the item that
        # carries it. Equality here would report most of a well-classified
        # CV as unmapped.
        if normalized in covered_blob:
            continue
        # The reverse direction, for lines that were stored with a label
        # stripped off the front ("Contact: +971 ..." -> "+971 ...").
        unlabelled = _normalize(LETTERHEAD_LABEL_RE.sub("", line))
        if unlabelled != normalized and unlabelled in covered_blob:
            continue
        # A stored value that accounts for most of the line means the line
        # was mapped; one that accounts for a fraction of it does not, and
        # the remainder is genuinely unaccounted for.
        if any(
            value in normalized and len(value) >= len(normalized) * COVERAGE_RATIO
            for value in values
        ):
            continue

        seen.add(normalized)
        unmapped.append({"text": line, "context": context})

    return unmapped[:max_entries]


UNMAPPED_HEADING = "UNMAPPED INFORMATION"
UNMAPPED_PREAMBLE = (
    "The following content was found in the source CV but did not map to an "
    "official MDX section. It is reproduced here for HR review rather than "
    "being discarded or placed in an approximate section."
)


def build_unmapped_items(cv_id: str, cv_text: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Storage items for the unmapped note, one per orphaned line.

    Left pending rather than auto-approved: whether a line genuinely belongs
    nowhere is a judgement, and the reviewer may well recognise it as content
    for a section the classifier missed. Confidence is not a claim about
    correctness here -- the item is a report of a gap, so it is banded low so
    it always surfaces.
    """
    import uuid
    from datetime import datetime, timezone

    entries = find_unmapped(cv_text, items)
    out: list[dict[str, Any]] = []
    for entry in entries:
        out.append({
            "item_id": str(uuid.uuid4()),
            "cv_id": cv_id,
            "section": "unmapped",
            "fields": {"value": entry["text"], "context": entry["context"]},
            "source": {
                "document": f"Source section: {entry['context']}",
                "raw_text": entry["text"],
                "page": None,
                "char_offset": None,
            },
            "confidence": 0.4,
            "confidence_band": "low",
            "validation_flags": ["unmapped_content"],
            "status": "pending_review",
            "edit_history": [
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "action": "flagged_unmapped",
                    "previous_fields": None,
                }
            ],
        })
    return out
