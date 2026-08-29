"""Plain-English command bar for the review screen.

Deliberately a deterministic parser rather than an LLM call. The commands
reviewers actually need are a small, closed set -- approve a section, reject
a section, add a missing item, correct a letterhead field -- and matching
them with rules keeps the review screen working offline, instantly, and
without a per-keystroke API cost.

It also fails honestly: an unrecognised command reports what it did not
understand and lists what it can do, rather than guessing at intent and
silently doing the wrong thing to someone's CV.
"""
import re
from typing import Any

from config import SECTIONS

# Extra words reviewers naturally use for a section, beyond its official label.
SECTION_ALIASES: dict[str, list[str]] = {
    "publications": ["publications", "papers", "research outputs"],
    "grants": ["grants", "funding", "projects", "consultancy"],
    "awards": ["awards", "prizes", "honours", "recognitions"],
    "qualifications": ["qualifications", "education", "degrees"],
    "teaching_learning": ["teaching", "teaching and learning"],
    "present_employment": ["present employment", "current job", "current role"],
    "previous_employment": ["previous employment", "past jobs", "work history"],
    "associations": ["memberships", "associations", "fellowships"],
    "committees": ["committees", "advisory roles"],
    "academic_leadership": ["leadership", "academic leadership"],
    "knowledge_exchange": ["knowledge exchange", "public engagement"],
    "editorial_roles": ["editorial", "editorial roles", "reviewer roles"],
    "centres_of_excellence": ["centres", "research lab", "centres of excellence"],
    "profiles_links": ["profiles", "links", "identifiers", "orcid", "linkedin"],
    "biography": ["biography", "bio"],
    "full_name": ["name", "full name"],
    "job_title": ["job title", "title", "role"],
    "contact_info": ["contact", "phone", "telephone", "desk phone"],
    "email": ["email", "e-mail"],
}


class CommandError(Exception):
    """Raised with a message safe to show directly to the reviewer."""


def _resolve_section(text: str) -> str | None:
    """Longest alias wins, so "previous employment" is not shadowed by the
    shorter "employment" appearing inside it."""
    lowered = text.lower()
    best: tuple[int, str] | None = None
    for key, aliases in SECTION_ALIASES.items():
        for alias in aliases:
            if alias in lowered and (best is None or len(alias) > best[0]):
                best = (len(alias), key)
    if best:
        return best[1]
    for section in SECTIONS:
        if section["label"].lower() in lowered:
            return section["key"]
    return None


HELP = (
    "Try: “approve all”, “approve publications”, “reject teaching”, "
    "“add Best Paper Award 2025 to awards”, or “set email to a.b@mdx.ac.ae”."
)


def parse(text: str) -> dict[str, Any]:
    """Turn a typed instruction into a structured action.

    Returns a dict with an `action` key: bulk_status, add_item, set_field.
    Raises CommandError with guidance when the intent isn't clear.
    """
    raw = " ".join((text or "").split())
    if not raw:
        raise CommandError("Type a command first. " + HELP)
    lowered = raw.lower()

    # set <field> to <value>
    set_match = re.match(
        r"^(?:set|change|update)\s+(?:the\s+)?(email|e-mail|phone|telephone|contact|job title|title|role|name|full name)"
        r"\s*(?:to|=|as)?\s*[:\-]?\s*(.+)$",
        raw, re.IGNORECASE,
    )
    if set_match:
        label, value = set_match.group(1), set_match.group(2).strip().strip('"“”')
        section = _resolve_section(label)
        if not section or not value:
            raise CommandError(f"Couldn't tell which field to set from “{raw}”. " + HELP)
        return {"action": "set_field", "section": section, "value": value}

    # add <text> to <section>
    add_match = re.match(r"^(?:add|insert)\s+(.+?)\s+(?:to|under|in|into)\s+(.+)$", raw, re.IGNORECASE)
    if add_match:
        content, target = add_match.group(1).strip().strip('"“”'), add_match.group(2)
        section = _resolve_section(target)
        if not section:
            raise CommandError(f"Couldn't find a section called “{target}”.")
        if not content:
            raise CommandError("Nothing to add — include the text for the new item.")
        return {"action": "add_item", "section": section, "line": content}

    # approve / reject [all | <section>]
    verb_match = re.match(r"^(approve|accept|reject|remove)\b(.*)$", raw, re.IGNORECASE)
    if verb_match:
        verb, rest = verb_match.group(1).lower(), verb_match.group(2).strip()
        status = "approved" if verb in ("approve", "accept") else "rejected"
        if not rest or re.fullmatch(r"(all|everything)( items| pending)?", rest, re.IGNORECASE):
            return {"action": "bulk_status", "status": status, "section": None}
        section = _resolve_section(rest)
        if not section:
            raise CommandError(f"Couldn't find a section called “{rest}”.")
        return {"action": "bulk_status", "status": status, "section": section}

    raise CommandError(f"Didn't understand “{raw}”. " + HELP)


def describe(result: dict[str, Any]) -> str:
    """Human confirmation of what actually happened, so a mis-parsed command
    is obvious immediately rather than discovered in the generated document."""
    action = result.get("action")
    if action == "bulk_status":
        verb = "Approved" if result["status"] == "approved" else "Rejected"
        where = result.get("section_label") or "all sections"
        return f"{verb} {result.get('updated', 0)} pending item(s) in {where}."
    if action == "add_item":
        return f"Added a new item to {result.get('section_label')}."
    if action == "set_field":
        return f"Set {result.get('section_label')} to “{result.get('value')}”."
    return "Done."
