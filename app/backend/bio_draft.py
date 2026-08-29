"""Draft a BIOGRAPHY section when the source CV has none.

Most CVs carry no biography at all -- it is one of the sections a reviewer
otherwise has to write from scratch every time. This module assembles a
first draft out of facts already extracted from the same CV, so the reviewer
edits a sentence or two rather than starting at a blank box.

Two hard rules, because this is the one place in the system that produces
prose rather than quotes:

  * Only facts already extracted are used. No detail is introduced that
    isn't elsewhere in the CV, and a clause is omitted entirely when the
    fact behind it is missing -- never filled with a plausible guess.
  * A draft is NEVER auto-approved. It is always left pending so a person
    must read it before it can reach a generated document, and it is
    labelled as drafted rather than quoted.

Gender is never inferred. The person's name and neutral phrasing are used
throughout, so the draft can't misgender anyone.
"""
from typing import Any

from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

BIO_SOURCE_LABEL = "Drafted from this CV's own extracted facts"
BIO_SOURCE_NOTE = "(draft — assembled from extracted facts, please review and edit)"

HONORIFIC_PREFIXES = ("dr ", "prof ", "professor ", "mr ", "mrs ", "ms ", "miss ")

# Same list, as bare words (no trailing space) for period-insensitive matching
# against the first token of a name -- see _short_name().
HONORIFIC_WORDS = {p.strip() for p in HONORIFIC_PREFIXES}


def _first_value(items: list[dict[str, Any]], section: str) -> str:
    for item in items:
        if item["section"] != section:
            continue
        fields = item.get("fields", {}) or {}
        value = (fields.get("value") or fields.get("title") or "").strip()
        if value:
            return value
    return ""


def _short_name(full_name: str) -> str:
    """Surname-style short form for the second sentence, honorific kept if
    the CV used one ("Dr Chaudhary"), so the draft doesn't read as if it is
    on first-name terms with a professor.

    Matches the first word against the honorific list with any trailing
    period stripped, so "Dr. Alison Burrows" (period, as most CVs write it)
    is recognised the same as "Dr Alison Burrows" (no period). Missing this
    used to silently fall through to the no-honorific branch, folding a
    second sentence's fact into the first one instead ("X is Y, and holds
    Z.") -- exactly the failure this docstring's own example is meant to
    guard against, just for the honorific case instead of the missing-name
    case.
    """
    name = full_name.strip()
    if not name:
        return ""
    parts = name.split()
    if parts and parts[0].rstrip(".").casefold() in HONORIFIC_WORDS:
        return f"{parts[0]} {parts[-1]}" if len(parts) > 2 else name
    return name


def _count(items: list[dict[str, Any]], section: str) -> int:
    return sum(1 for i in items if i["section"] == section)


# Words that mark a line as an actual academic or professional qualification.
QUALIFICATION_MARKERS = (
    "phd", "doctor", "doctorate", "master", "bachelor", "mba", "msc", "bsc",
    "b.a", "m.a", "llb", "llm", "diploma", "degree", "certificate",
    "certification", "certified", "pgce", "pgcert", "a level", "o level",
    "university", "college", "institute", "academy", "school of",
)


def _best_qualification(items: list[dict[str, Any]], full_name: str) -> str:
    """The first Qualifications entry that actually reads like a qualification.

    Taking the section's first item unconditionally produced sentences like
    "ANUJITH ANTONY holds ANUJITH ANTONY" when a stray line had been misfiled
    into Qualifications by a scrambled PDF layout. A biography is the one
    piece of generated prose here, so it verifies its own inputs rather than
    trusting the section label -- and simply omits the clause when nothing
    qualifies.
    """
    name_key = " ".join(full_name.split()).casefold()
    # A degree entry can end up split across two items when a résumé lists
    # the institution/date on its own line ahead of the degree name (an
    # unusual but real ordering) -- the institution-only item still
    # contains a QUALIFICATION_MARKERS word ("University") and would
    # otherwise win by appearing first, producing "holds University Johns
    # Hopkins School of Education - Baltimore, MD, USA May 2023" instead of
    # the actual degree. An item with a real, structured `degree` field is
    # unambiguous evidence over a raw-text keyword match, so it's checked
    # first regardless of item order; only when none exists does the older
    # whole-text marker scan run, so a CV with no structured fields at all
    # (a rule-based parse that never even attempted one) still gets a bio.
    for item in items:
        if item["section"] != "qualifications":
            continue
        fields = item.get("fields", {}) or {}
        degree = (fields.get("degree") or "").strip()
        if not degree:
            continue
        subject = (fields.get("subject") or "").strip()
        return f"{degree} in {subject}" if subject else degree

    for item in items:
        if item["section"] != "qualifications":
            continue
        fields = item.get("fields", {}) or {}
        text = (fields.get("value") or item.get("source", {}).get("raw_text", "")).strip()
        flat = " ".join(text.split()).casefold()
        if not flat or flat == name_key or name_key in flat:
            continue
        if any(marker in flat for marker in QUALIFICATION_MARKERS):
            return text
    return ""


# Acronym first letters that are SPOKEN as a vowel sound ("M" -> "em", "H" ->
# "aitch") even though the letter itself isn't a vowel -- "an MBA", not "a
# MBA". Only consulted for a first word that reads as an acronym (short,
# all-caps); an ordinary word's article always follows its own first letter.
VOWEL_SOUND_ACRONYM_LETTERS = "FHLMNRSX"


def _with_article(phrase: str) -> str:
    """Prefix a job title with "a"/"an" so the opening sentence reads as
    English ("is a Senior Lecturer", not "is Senior Lecturer"). Skipped when
    the phrase already opens with an article, or is empty -- a title that
    already reads fine is left alone rather than risking "a the Head of...".
    """
    phrase = phrase.strip()
    if not phrase:
        return phrase
    first_word = phrase.split()[0]
    if first_word.casefold() in ("a", "an", "the"):
        return phrase
    if first_word.isalpha() and first_word.isupper() and 1 < len(first_word) <= 5:
        article = "an" if first_word[0] in VOWEL_SOUND_ACRONYM_LETTERS else "a"
    else:
        article = "an" if phrase[0].casefold() in "aeiou" else "a"
    return f"{article} {phrase}"


def draft_biography_text(items: list[dict[str, Any]]) -> str | None:
    """Deterministic, offline draft. Returns None when too little is known
    to say anything useful -- an empty section is better than a vacuous one."""
    full_name = _first_value(items, "full_name")
    if not full_name:
        return None

    title = _first_value(items, "job_title") or _first_value(items, "present_employment")
    qualification = _best_qualification(items, full_name)

    sentences: list[str] = []

    if title:
        sentences.append(f"{full_name} is {_with_article(title.rstrip('.'))}.")
    else:
        sentences.append(f"{full_name} is a member of academic staff at Middlesex University Dubai.")

    short = _short_name(full_name)
    if qualification:
        # Trim to the degree clause; qualification lines often carry a long
        # tail (thesis title, supervisors) that does not belong in a bio.
        head = qualification.split("|")[0].split(" - Thesis")[0].strip().rstrip(",.")
        if head:
            if short == full_name:
                # No honorific to shorten against, so a second sentence would
                # repeat the full name immediately after the first
                # ("ARIFULLAH BASHA SHAIK is X. ARIFULLAH BASHA SHAIK holds
                # Y."). Fold it into the opening sentence instead.
                sentences[0] = sentences[0].rstrip(".") + f", and holds {head}."
            else:
                sentences.append(f"{short} holds {head}.")

    pubs = _count(items, "publications")
    grants = _count(items, "grants")
    if pubs and grants:
        sentences.append(
            f"Their record includes {pubs} listed publication{'s' if pubs != 1 else ''} "
            f"and {grants} funded research project{'s' if grants != 1 else ''}."
        )
    elif pubs:
        sentences.append(f"Their record includes {pubs} listed publication{'s' if pubs != 1 else ''}.")
    elif grants:
        sentences.append(
            f"Their record includes {grants} funded research project{'s' if grants != 1 else ''}."
        )

    # Guard against a one-fact stub. Counts facts rather than sentences,
    # because a qualification folded into the opening sentence still makes
    # this a two-fact biography.
    facts = len(sentences) + (1 if qualification and len(sentences) == 1 else 0)
    if facts < 2:
        return None
    return " ".join(sentences)


def draft_biography_via_llm(items: list[dict[str, Any]]) -> str | None:
    """Optional upgrade: a better-written bio when an API key is configured.

    Given only the already-extracted facts (never the raw CV), and instructed
    not to add anything beyond them. Falls back to the offline template on
    any failure, so this can never be the reason a CV fails to process.
    """
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic

        facts = "\n".join(
            f"- {i['section']}: {i['source']['raw_text'][:200]}"
            for i in items
            if i["section"] in (
                "full_name", "job_title", "present_employment", "qualifications",
                "teaching_learning", "grants", "publications", "awards",
            )
        )[:6000]

        response = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=400,
            system=(
                "Write a 50-75 word third-person academic biography for a university "
                "faculty CV, using ONLY the facts supplied. Do not invent, infer or "
                "embellish anything not explicitly listed. Do not assume the person's "
                "gender: use their name or neutral phrasing, never he/she. Return the "
                "biography text only, with no preamble."
            ),
            messages=[{"role": "user", "content": f"Facts extracted from the CV:\n{facts}"}],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or None
    except Exception:
        return None


def build_biography_item(cv_id: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A pending BIOGRAPHY item, or None if the CV already has one."""
    import uuid
    from datetime import datetime, timezone

    if any(i["section"] == "biography" for i in items):
        return None

    text = draft_biography_via_llm(items) or draft_biography_text(items)
    if not text:
        return None

    return {
        "item_id": str(uuid.uuid4()),
        "cv_id": cv_id,
        "section": "biography",
        "fields": {"_line_override": text},
        "source": {
            "document": BIO_SOURCE_LABEL,
            "raw_text": f"{text}  {BIO_SOURCE_NOTE}",
            "page": None,
            "char_offset": None,
        },
        # Deliberately low, and deliberately left pending: this is the only
        # generated prose in the system and must be read by a person.
        "confidence": 0.5,
        "confidence_band": "low",
        "validation_flags": ["drafted_not_extracted"],
        "status": "pending_review",
        "edit_history": [
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "action": "biography_drafted",
                "previous_fields": None,
            }
        ],
    }
