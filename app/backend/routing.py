"""Route individual items to MDX sections by what they say, not by the
heading they happened to sit under.

The problem this solves: a CV commonly gathers unlike things under one
heading. A real example -- a single "SELECTED LEADERSHIP ROLES" heading
containing eleven entries that the university's own HR reviewer distributed
across FIVE different MDX sections:

    Associate Editor, Cambridge Journal of Education   -> Editorial Roles
    Member, Advisory Group, Parliamentarians Caucus    -> Committees
    Co-convenor, CASES Seminar Series                  -> Knowledge Exchange
    Co-founder and Convenor, SAARE Network             -> Academic Leadership
    Member, Executive Committee, BAICE                 -> Academic Leadership

Heading-based classification cannot do this: the eleven items share one
heading, so they all land in one section, leaving four sections empty and
one overfull.

The safeguard that makes this safe: routing NEVER overrides a heading the CV
states explicitly. If a document says "AWARDS AND RECOGNITIONS", everything
beneath it stays in Awards no matter what the words look like. Re-routing
applies only where the heading was generic, inferred, or absent -- which is
exactly where the classifier had no real information to begin with.
"""
import re
from typing import Any

# (compiled pattern, destination section). Order is priority: the first
# match wins, so the more decisive signal must come first. "Co-founder and
# Convenor, SAARE Network" is leadership rather than an event series, so
# founder outranks convenor; "Member, Executive Committee" is leadership
# rather than a committee seat, so it outranks the generic committee rule.
ROUTING_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:co-)?founder\b|\bfounded\b", re.I), "academic_leadership"),
    (re.compile(r"\bexecutive (?:committee|team|board)\b", re.I), "academic_leadership"),

    (re.compile(r"\b(?:associate |guest |co-|managing |executive )?editor\b"
                r"|\beditorial board\b|\breviewer\b|\brefereed?\b|\bexaminer\b",
                re.I), "editorial_roles"),

    (re.compile(r"\badvisory (?:group|board|panel|role)\b|\bworking group\b"
                r"|\bsteering (?:group|committee)\b|\btask ?force\b"
                r"|\bboard member\b|\bcommittee\b", re.I), "committees"),

    (re.compile(r"\bconven[eo]r\b|\bconvening\b|\bseminar\b|\bwebinar\b"
                r"|\bworkshop\b|\bpanel(?:l?ist|\s+discussion)\b|\bkeynote\b"
                r"|\borganis(?:ing|ation) committee\b|\bconference organis"
                r"|\boutreach\b|\bpublic engagement\b|\bprogramme on\b"
                r"|\bmedia interview\b|\bjudge\b|\bjudging\b", re.I), "knowledge_exchange"),

    (re.compile(r"\bcentre (?:of|for)\b|\bcenter (?:of|for)\b"
                r"|\bresearch (?:group|lab|laboratory|centre|center)\b",
                re.I), "centres_of_excellence"),

    (re.compile(r"\baward\b|\bprize\b|\bscholarship\b|\bmedal\b|\bhonou?r(?:s|ed)?\b"
                r"|\bwinner\b|\bfinalist\b|\bnominee\b|\bnominated\b"
                r"|\bhighly commended\b|\bdistinction\b|\bdean'?s list\b",
                re.I), "awards"),

    (re.compile(r"\bfellow(?:ship)?\b|\bchartered\b|\bmember(?:ship)? of\b"
                r"|\blife member\b", re.I), "associations"),

    (re.compile(r"\bgrant\b|\bfunded by\b|\bfunding agency\b|\bconsultancy\b",
                re.I), "grants"),

    # Listed last by priority, but position wins over priority (see
    # route_item): an entry opening "Lecturer/Examiner (PG): ..." is a
    # teaching role that also examines, not an examiner who also lectures.
    (re.compile(r"\blecturer\b|\bteaching\b|\btutor\b|\bmodule\b|\btripos\b"
                r"|\bsupervis(?:or|ed|ing|ion)\b|\bcurriculum\b|\bdissertation\b",
                re.I), "teaching_learning"),
]

# Sections whose contents may be re-routed. Deliberately excludes the
# letterhead fields, publications and biography: those are either
# structurally identified or long prose that would trip many patterns by
# coincidence.
# Rules that only apply to items currently sitting in a particular section.
# Used where a signal is decisive in one context and misleading in another:
# a line opening "Developed session foci and content" is teaching material
# on an academic CV, but the same opening under Qualifications is a job
# responsibility that a scrambled multi-column PDF dropped in the wrong
# place. Scoping by source section keeps the useful case without the
# collateral damage.
ACTION_VERB_RE = re.compile(
    r"^(?:designed|developed|implemented|diagnosed|managed|assisted|supported"
    r"|improved|optimi[sz]ed|gathered|identified|created|built|maintained"
    r"|configured|installed|troubleshot|resolved|delivered|coordinated"
    r"|performed|conducted|provided|prepared|established|automated|migrated"
    r"|deployed|tested|documented|monitored|handled|operated)\b",
    re.I,
)
SCOPED_RULES: list[tuple[re.Pattern, str, set[str]]] = [
    (ACTION_VERB_RE, "previous_employment", {"qualifications"}),
]

ROUTABLE_SOURCE_SECTIONS = {
    "academic_leadership", "committees", "knowledge_exchange", "associations",
    "centres_of_excellence", "editorial_roles", "awards", "teaching_learning",
    "qualifications", "present_employment", "previous_employment",
}

# Never move an item OUT of a section the CV named explicitly, and never
# move one INTO a place where employment/teaching clearly belongs.
PROTECTED_TARGETS = {"present_employment", "previous_employment", "publications"}


# A CV entry names its role first: "Associate Editor, Cambridge Journal...",
# "Member, Advisory Group, ...". Only this opening span is examined.
# Searching the whole entry misfires badly -- "Senior Lecturer, International
# and Comparative Education, and Head of Centre for Academic Success" would
# be filed under Centres of Excellence because "Centre" appears late in the
# job title, and a thesis abstract mentioning a research group would move
# out of Qualifications.
ROLE_SPAN_CHARS = 60


def route_item(text: str) -> str | None:
    """The section this text's wording points to, or None if nothing matches.

    Where several role words appear, the EARLIEST one wins -- a CV entry
    leads with its primary role and qualifies it afterwards. "Supervisor and
    Examiner, U/G Tripos" is a supervision role; "Examiner, MPhil in
    Architecture" is an examiner role. Rule order only breaks ties at the
    same position.
    """
    role_span = text[:ROLE_SPAN_CHARS]
    best: tuple[int, int, str] | None = None
    for priority, (pattern, section) in enumerate(ROUTING_RULES):
        match = pattern.search(role_span)
        if match and (best is None or (match.start(), priority) < (best[0], best[1])):
            best = (match.start(), priority, section)
    return best[2] if best else None


def apply_routing(
    items: list[dict[str, Any]], authoritative_sections: set[str]
) -> list[dict[str, Any]]:
    """Re-file items whose wording clearly indicates a different section.

    `authoritative_sections` are those whose heading matched an official MDX
    heading exactly -- the CV said where this content belongs, so it is left
    alone. Everything else is a guess from a generic heading and is open to
    correction by content.

    A moved item keeps its verbatim source text and is marked so the reviewer
    can see it was re-filed; its confidence is capped below the auto-approval
    threshold, because a moved item is exactly the kind of judgement a person
    should confirm.
    """
    for item in items:
        section = item["section"]
        if section not in ROUTABLE_SOURCE_SECTIONS:
            continue
        if section in authoritative_sections:
            continue

        target = route_item(item["source_text"])
        if not target or target == section:
            if not target:
                # Fall back to a rule scoped to this specific source section.
                target = next(
                    (
                        dest
                        for pattern, dest, sources in SCOPED_RULES
                        if section in sources and pattern.match(item["source_text"].strip())
                    ),
                    None,
                )
            if not target or target == section:
                continue
        elif target in PROTECTED_TARGETS or section in PROTECTED_TARGETS:
            continue

        item["section"] = target
        item["confidence"] = min(item.get("confidence", 0.8), 0.7)
        item["validation_flags"] = sorted(
            set(item.get("validation_flags", [])) | {"rerouted_by_content"}
        )
    return items
