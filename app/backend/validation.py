"""Deterministic, non-AI validation. Runs independently of the LLM's own
confidence score so a second, rule-based check exists on the same data.
"""
import re
from datetime import date
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL_RE = re.compile(r"^(https?://|www\.)[^\s]+\.[a-z]{2,}", re.IGNORECASE)


def confidence_band(confidence: float) -> str:
    if confidence >= 0.90:
        return "high"
    if confidence >= 0.70:
        return "medium"
    return "low"


def _parse_partial_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for fmt_len, parser in (
        (7, lambda v: date(int(v[:4]), int(v[5:7]), 1)),  # YYYY-MM
        (4, lambda v: date(int(v[:4]), 1, 1)),  # YYYY
        (10, lambda v: date.fromisoformat(v)),  # YYYY-MM-DD
    ):
        try:
            if fmt_len == 10 and len(value) == 10:
                return parser(value)
            if fmt_len == 7 and len(value) == 7:
                return parser(value)
            if fmt_len == 4 and len(value) == 4:
                return parser(value)
        except (ValueError, IndexError):
            continue
    return None


def validate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mutates and returns items with validation_flags populated."""
    for item in items:
        flags: list[str] = list(item.get("validation_flags", []))
        section = item["section"]
        fields = item.get("fields", {})

        if item["confidence"] < 0.70:
            flags.append("low_confidence")
        elif item["confidence"] < 0.90:
            flags.append("medium_confidence")

        if section == "email":
            value = fields.get("value") or item["source"].get("raw_text", "")
            if value and not EMAIL_RE.match(value.strip()):
                flags.append("invalid_email_format")

        if section == "profiles_links":
            url = fields.get("url", "")
            if url and not URL_RE.match(url.strip()):
                flags.append("invalid_url_format")

        if section in ("present_employment", "previous_employment"):
            start = _parse_partial_date(fields.get("start_date"))
            end = _parse_partial_date(fields.get("end_date"))
            if start and end and end < start:
                flags.append("end_date_before_start_date")
            if section == "present_employment" and fields.get("end_date"):
                flags.append("present_employment_has_end_date_review_section")

        item["validation_flags"] = sorted(set(flags))

    _flag_overlapping_employment(items)
    _flag_duplicate_publications(items)
    return items


def _flag_overlapping_employment(items: list[dict[str, Any]]) -> None:
    employment = [
        it for it in items
        if it["section"] in ("present_employment", "previous_employment")
    ]
    ranges = []
    for it in employment:
        start = _parse_partial_date(it["fields"].get("start_date"))
        end = _parse_partial_date(it["fields"].get("end_date")) or date.max
        if start:
            ranges.append((start, end, it))

    for i, (s1, e1, it1) in enumerate(ranges):
        for s2, e2, it2 in ranges[i + 1:]:
            if s1 <= e2 and s2 <= e1:
                for it in (it1, it2):
                    if "overlapping_employment_dates" not in it["validation_flags"]:
                        it["validation_flags"] = sorted(
                            set(it["validation_flags"] + ["overlapping_employment_dates"])
                        )


def _flag_duplicate_publications(items: list[dict[str, Any]]) -> None:
    pubs = [it for it in items if it["section"] == "publications"]
    seen: dict[str, dict[str, Any]] = {}
    for it in pubs:
        citation = (it["fields"].get("citation") or "").lower()
        key = " ".join(citation.split())[:120]
        if not key:
            continue
        if key in seen:
            for target in (it, seen[key]):
                if "possible_duplicate_publication" not in target["validation_flags"]:
                    target["validation_flags"] = sorted(
                        set(target["validation_flags"] + ["possible_duplicate_publication"])
                    )
        else:
            seen[key] = it


# Flags that merely describe how sure the classifier was. They are shown to
# the reviewer but do not, on their own, oblige anyone to touch the item --
# unlike a real data problem such as a malformed email or overlapping dates.
ADVISORY_FLAGS = {"low_confidence", "medium_confidence"}

# Below this, an item is never auto-approved: the classifier was guessing
# (a job title inferred from an employment line, an entry recovered from an
# unlabelled block) and a human should look before it reaches the document.
AUTO_APPROVE_MIN_CONFIDENCE = 0.75


def needs_human_review(item: dict[str, Any]) -> bool:
    """True when an item must be actioned by a person before generation.

    Everything else is auto-approved on ingest. The alternative -- making a
    reviewer click every one of the 90+ items a long academic CV produces --
    is data entry, not review: it buries the handful of entries that are
    genuinely uncertain in a sea of ones that are obviously right.
    """
    if item.get("confidence", 0.0) < AUTO_APPROVE_MIN_CONFIDENCE:
        return True
    return bool(set(item.get("validation_flags", [])) - ADVISORY_FLAGS)


def apply_auto_approval(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pre-approve the confident, unflagged items; leave the rest pending.

    Runs after validate_items so flags are already populated. Items keep an
    audit trail entry recording that approval was automatic, so the action
    is never mistaken for a human decision.
    """
    for item in items:
        if item.get("status") != "pending_review":
            continue
        if needs_human_review(item):
            continue
        item["status"] = "approved"
        item["edit_history"] = list(item.get("edit_history", [])) + [
            {"at": _now_iso(), "action": "auto_approved", "previous_fields": None}
        ]
    return items


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


MANDATORY_SECTIONS = {"full_name", "email"}


def missing_mandatory_sections(items: list[dict[str, Any]]) -> list[str]:
    present = {it["section"] for it in items}
    return sorted(MANDATORY_SECTIONS - present)
