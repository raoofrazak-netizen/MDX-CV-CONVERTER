"""AI classification: raw CV text -> structured items mapped to the 20 MDX
Faculty CV sections.

Hard rule enforced by prompt AND by the calling code: every item must carry
a verbatim `source_text` quote from the CV. Nothing is accepted without one.
Confidence reflects the model's certainty about section placement, not
fluency of the source text.
"""
import json
from typing import Any

import anthropic

from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, SECTION_KEYS
from rule_classifier import _find_running_headers, classify_rule_based


class ClassificationError(Exception):
    """Raised with a message safe to show to an HR user."""


SECTION_GUIDE = """
- full_name, job_title, contact_info, email: from the letterhead / header area only. fields: {"value": "..."} holding just the plain value (no label prefix).
- biography: an existing self-description paragraph, if the CV has one (do not write a new one here).
- qualifications: degrees and academic/professional certifications. fields: degree, subject, institution, country, year.
- associations: professional body memberships and fellowships (not employment). fields: association_title, organisation, country, membership_no, since.
- present_employment: ONLY roles at Middlesex University (Dubai or otherwise) with no stated end date. fields: title, unit, start_date, end_date(null).
- previous_employment: any past role, including a past MDX role that has ended, and all non-MDX employers. fields: title, employer, start_date, end_date.
- teaching_learning: teaching responsibilities, module leadership, curriculum development, supervision. fields: description.
- committees: committee membership and advisory roles (internal or external), not editorial/review roles. fields: role, body, start_date, end_date.
- academic_leadership: formal leadership titles (CPC, CPL, Chair, Head, module leadership, journal editorship as an editor-in-chief role). fields: title, scope.
- knowledge_exchange: keynote talks, workshops led, media interviews, events organised/co-organised, panels, judging. NOT awards received. fields: description, role, event, year.
- awards: prizes and recognitions received BY the faculty member. fields: award_name, awarding_body, year.
- centres_of_excellence: membership/founding/leadership of an MDX centre, lab, or research group. fields: role, centre_name, since.
- grants: funded research, consultancy, or grant projects. fields: project_title, role, duration, funding_agency.
- editorial_roles: journal reviewer, editorial board member, examiner, quality-assurance external examiner roles. fields: role, publication_or_org, publisher.
- publications: research outputs. fields: citation, subgroup (one of: journal, book_chapter, industry_government).
- profiles_links: Scopus / ORCID / Google Scholar / LinkedIn / personal or lab website. fields: platform, url.

Disambiguation rules (apply exactly):
- A journal reviewer or examiner role -> editorial_roles, never associations.
- Keynote/media/workshop/event activity -> knowledge_exchange, never awards.
- Current MDX role with no end date -> present_employment. Same employer with an end date, or any non-MDX employer -> previous_employment. Never split one job across both.
- If you cannot confidently choose a section, still choose the closest one but set confidence below 0.7.
"""

TOOL_SCHEMA = {
    "name": "emit_cv_items",
    "description": "Return every discrete fact extracted from the CV, mapped to MDX Faculty CV sections.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section": {"type": "string", "enum": SECTION_KEYS},
                        "fields": {
                            "type": "object",
                            "description": "Structured fields appropriate to the section, per the section guide.",
                        },
                        "source_text": {
                            "type": "string",
                            "description": "Verbatim quote copied exactly from the CV text that this item was extracted from. Must be a real substring of the input, not a paraphrase.",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "0.0-1.0 confidence that this item belongs in this section.",
                        },
                        "rationale": {
                            "type": "string",
                            "description": "One short sentence: why this section.",
                        },
                    },
                    "required": ["section", "fields", "source_text", "confidence", "rationale"],
                },
            }
        },
        "required": ["items"],
    },
}

SYSTEM_PROMPT = f"""You are an information-extraction engine for Middlesex University \
Dubai HR. You read a faculty member's CV and extract every relevant fact into \
one of 20 fixed sections of the official MDX Faculty CV template.

CRITICAL RULE, overrides everything else: you must NEVER invent, infer, \
exaggerate, complete, or guess any fact not literally present in the CV text. \
Do not fill gaps, do not assume typical values, do not "improve" wording into \
a claim the CV doesn't make. If a value is missing, omit that field rather \
than guessing it. Every single item you return must include a `source_text` \
field that is a verbatim, exact substring of the CV text provided -- not a \
paraphrase or summary. If you cannot find an exact quote to support an item, \
do not emit that item.

Section guide:
{SECTION_GUIDE}

Call the emit_cv_items tool exactly once with every item you found. Do not \
return prose outside the tool call.
"""


# Set on every item classify() returns via the rule-engine fallback (an AI
# key IS configured but the call itself failed or came back unusable), so
# a caller can tell the two success paths apart without classify() having
# to change its return type. Never set on the "no key configured at all"
# path above -- that one is the deliberate, expected default, not a failure.
AI_FALLBACK_FLAG = "ai_unavailable_used_rule_fallback"


def classify(cv_text: str, source_document: str) -> list[dict[str, Any]]:
    if not ANTHROPIC_API_KEY:
        return _validate_against_source(classify_rule_based(cv_text, source_document), cv_text)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            tools=[TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "emit_cv_items"},
            messages=[
                {
                    "role": "user",
                    "content": f"CV text (source document: {source_document}):\n\n{cv_text}",
                }
            ],
        )
    except anthropic.APIError:
        # A configured key that can't be used right now -- no credit, an
        # outage, a rate limit -- used to fail the whole CV with nothing to
        # show for it. The rule engine processed every CV before the AI path
        # existed and is still sitting right here; falling back to it keeps
        # HR moving (a coarser first pass, same as always) instead of a dead
        # end over an outage that has a working offline alternative. Every
        # item is flagged so it can never quietly look like a full AI pass
        # -- see AI_FALLBACK_FLAG, and needs_human_review()'s flag-based
        # check means a fallback item can never auto-approve either.
        return _mark_ai_fallback(_validate_against_source(
            classify_rule_based(cv_text, source_document), cv_text
        ))

    for block in response.content:
        if block.type == "tool_use" and block.name == "emit_cv_items":
            raw_items = block.input.get("items", [])
            return _validate_against_source(raw_items, cv_text)

    # The call itself succeeded but didn't return the structured result it
    # was told to -- treated the same as an outright failure above, for the
    # same reason: a working offline path exists, so this doesn't need to
    # fail the CV either.
    return _mark_ai_fallback(_validate_against_source(
        classify_rule_based(cv_text, source_document), cv_text
    ))


def _mark_ai_fallback(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in items:
        flags = list(item.get("validation_flags", []))
        if AI_FALLBACK_FLAG not in flags:
            flags.append(AI_FALLBACK_FLAG)
        item["validation_flags"] = flags
    return items


def _validate_against_source(raw_items: list[dict[str, Any]], cv_text: str) -> list[dict[str, Any]]:
    """Drop any item whose source_text is not an actual substring of the CV.

    This is the code-level backstop for the no-fabrication rule: even if the
    model hallucinates a fact, an item that can't be traced back to real
    source text is discarded rather than surfaced to HR as if it were real.
    """
    normalized_source = " ".join(cv_text.split())
    # A second reference copy with the page header/footer lines taken out.
    # Those lines are removed before classification, so a citation or a role
    # that wraps across a page boundary is legitimately reassembled from
    # lines that had the running header between them. Checking only against
    # the raw text rejects that item as unquotable and DISCARDS it -- data
    # loss dressed up as a safety check. Both copies preserve the source's
    # own text and order, so nothing fabricated can pass either one.
    running_headers = _find_running_headers(cv_text.splitlines())
    normalized_body = " ".join(
        " ".join(
            line for line in cv_text.splitlines()
            if " ".join(line.split()) not in running_headers
        ).split()
    )

    validated = []
    for item in raw_items:
        source_text = (item.get("source_text") or "").strip()
        if not source_text:
            continue
        if source_text not in cv_text:
            normalized_quote = " ".join(source_text.split())
            if (
                normalized_quote not in normalized_source
                and normalized_quote not in normalized_body
            ):
                continue
        if item.get("section") not in SECTION_KEYS:
            continue
        validated.append(item)
    return validated
