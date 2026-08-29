from typing import Any

from config import SECTIONS, TEMPLATE_SECTION_KEYS

# Structured fields that should never realistically be this short -- a
# genuine job title, employer, or institution is always more than a couple
# of characters. A value this short is almost always a parsing artifact (a
# stray fragment left behind when a line got split in the wrong place), not
# real content. Deliberately excludes date-like fields ("2020",
# "start_date") and free-text "value" fields (an email or phone number can
# legitimately be short), which are not evidence of anything wrong.
# "degree" is excluded too, for a different reason: it is only ever set
# from a DEGREE_RE match against a known list of real degree names/
# abbreviations, several of which ARE this short on purpose ("BA", "MA",
# "MS") -- already-vetted content, not a candidate for this check.
SHORT_FIELD_KEYS = {
    "title", "employer", "unit", "institution", "subject",
    "project_title", "role", "funding_agency",
}
SHORT_FIELD_MAX_CHARS = 2


def _find_short_field_flags(items: list[dict[str, Any]]) -> list[str]:
    """Items whose value the reviewer has accepted (approved or edited)
    that still carry a suspiciously short structured field.

    Purely observational: this never changes an item's section, fields, or
    status, and never blocks generation -- it only surfaces something worth
    a second look, the same way `duplicate_flags` and `discarded_flags`
    already do below.
    """
    flags = []
    for item in items:
        if item["status"] not in ("approved", "edited"):
            continue
        fields = item.get("fields") or {}
        for key in SHORT_FIELD_KEYS:
            value = fields.get(key)
            if isinstance(value, str) and 0 < len(value.strip()) <= SHORT_FIELD_MAX_CHARS:
                flags.append(f"{item['section']}.{key}: {value.strip()!r}")
    return flags


def build_quality_report(
    cv_id: str, items: list[dict[str, Any]], has_photo: bool = False
) -> dict[str, Any]:
    by_section: dict[str, list[dict]] = {}
    for it in items:
        by_section.setdefault(it["section"], []).append(it)

    sections_report = []
    for section in SECTIONS:
        key = section["key"]
        section_items = by_section.get(key, [])
        approved = [i for i in section_items if i["status"] in ("approved", "edited")]
        flagged = [i for i in section_items if i["validation_flags"] or i["status"] == "pending_review"]

        if key == "profile_photo":
            # A photo is never an "item" -- it's stored on the CV record
            # (cv.photo_path), not the items table, because there's nothing
            # to approve/reject/edit about it the way there is for an
            # extracted fact. Checking `section_items` here always finds
            # nothing, so this row showed "missing" on every single CV, even
            # one whose photo was correctly detected and was already
            # displaying in the photo widget below it.
            status = "verified" if has_photo else "missing"
        elif not section_items:
            status = "missing"
        elif flagged:
            status = "needs_review"
        else:
            status = "verified"

        sections_report.append({
            "section": key,
            "label": section["label"],
            "item_count": len(section_items),
            "approved_count": len(approved),
            "flagged_count": len(flagged),
            "status": status,
        })

    # Confidence describes how well the extraction went, so it counts every
    # item the reviewer has not thrown out -- including ones still awaiting
    # review. Averaging only over already-actioned items meant a freshly
    # uploaded CV always reported 0%, which reads as "nothing was extracted"
    # at exactly the moment the reviewer is deciding whether to trust it.
    # Rejected items are excluded: the reviewer has said those are wrong.
    scored_items = [i for i in items if i["status"] != "rejected"]
    if scored_items:
        overall_confidence = sum(i["confidence"] for i in scored_items) / len(scored_items)
    else:
        overall_confidence = 0.0

    duplicate_flags = [
        f"{i['section']}: {i['source']['raw_text'][:80]}"
        for i in items if "possible_duplicate_publication" in i["validation_flags"]
    ]

    short_field_flags = _find_short_field_flags(items)

    unresolved_low_confidence = any(
        i["status"] == "pending_review" and i["confidence_band"] == "low" for i in items
    )
    any_pending = any(i["status"] == "pending_review" for i in items)

    pending_count = sum(1 for i in items if i["status"] == "pending_review")
    auto_approved = sum(
        1 for i in items
        if i["status"] == "approved"
        and any(e.get("action") == "auto_approved" for e in i.get("edit_history", []))
    )

    unmapped_items = by_section.get("unmapped", [])
    live_unmapped = [i for i in unmapped_items if i["status"] != "rejected"]

    # Content the reviewer threw out is the one way information leaves the
    # process entirely -- it is not in a section and it is not in the
    # unmapped note. That is a legitimate decision, but it should be a
    # visible one, so it is counted here rather than passing silently.
    discarded = [
        f"{i['section']}: {i['source']['raw_text'][:80]}"
        for i in items if i["status"] == "rejected"
    ]

    # Skills and Language Proficiency aren't official template sections, but
    # they are real, labelled, first-class sections in the generated
    # document -- not the safety net -- so they count as "mapped" for
    # coverage the same way an official section does. Only content that
    # lands in the generic unmapped note counts against coverage.
    mapped_section_keys = set(TEMPLATE_SECTION_KEYS) | {"skills", "language_proficiency"}
    mapped_items = [
        i for i in items
        if i["section"] in mapped_section_keys and i["status"] != "rejected"
    ]
    total_accounted = len(mapped_items) + len(live_unmapped)
    coverage = len(mapped_items) / total_accounted if total_accounted else 0.0

    return {
        "cv_id": cv_id,
        "overall_confidence": round(overall_confidence, 3),
        "sections": sections_report,
        "duplicate_flags": duplicate_flags,
        "short_field_flags": short_field_flags,
        "formatting_status": "ok",
        "total_items": len(items),
        "pending_count": pending_count,
        "auto_approved_count": auto_approved,
        # §9: how much of the source reached an official section, versus how
        # much only reached the unmapped note. A low figure does not mean the
        # conversion failed -- nothing was lost either way -- but it means
        # the reviewer should expect to re-file a lot by hand, and it is the
        # honest signal that this CV's layout defeated the classifier.
        "mapped_count": len(mapped_items),
        "unmapped_count": len(live_unmapped),
        "coverage": round(coverage, 3),
        "discarded_flags": discarded,
        "ready_to_download": not any_pending and not unresolved_low_confidence and bool(items),
    }
