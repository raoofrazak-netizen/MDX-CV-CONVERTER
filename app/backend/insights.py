"""Cross-CV, read-only aggregations for the operator-facing dashboard.

Pure functions over data that's already stored. This module never extracts,
classifies, or writes anything -- it only summarizes what unmapped.py
already produced for each CV individually. Nothing here can change what a
single CV's review screen shows or what a generated document contains.
"""
import json
from typing import Any


def summarize_unmapped_headings(
    rows: list[dict[str, Any]],
    taught_headings: set[str],
    limit: int = 30,
) -> list[dict[str, Any]]:
    """rows: [{cv_id, fields}] from storage.list_unmapped_items_with_cv().
    taught_headings: lowercased, stripped heading_text values already
    taught via /api/heading-mappings, so the dashboard doesn't keep
    recommending something HR already fixed.
    """
    by_context: dict[str, dict[str, Any]] = {}
    for row in rows:
        fields = json.loads(row["fields"])
        context = (fields.get("context") or "").strip()
        # "Top of document" is unmapped.py's default context for a line
        # with no heading above it at all -- not a heading anyone could
        # teach, so it has no place on a heading-teaching dashboard.
        if not context or context == "Top of document":
            continue
        entry = by_context.setdefault(context, {
            "context": context,
            "occurrences": 0,
            "cv_ids": set(),
            "example": fields.get("value", ""),
        })
        entry["occurrences"] += 1
        entry["cv_ids"].add(row["cv_id"])

    out = [
        {
            "context": v["context"],
            "occurrences": v["occurrences"],
            "cv_count": len(v["cv_ids"]),
            "example": v["example"],
        }
        for v in by_context.values()
        # Once HR has taught a heading it stops being something to act on:
        # dropped here rather than kept-and-flagged, otherwise a fixed
        # heading would sit at the top of this list (highest cv_count)
        # forever. Existing unmapped items on already-processed CVs are
        # untouched by this -- they still live in those CVs' own review
        # screens; teaching is forward-looking, same as everywhere else.
        if v["context"].casefold() not in taught_headings
    ]
    # Headings seen on the most DIFFERENT CVs first -- that's the signal
    # that teaching it once has the widest payoff, which is the whole
    # point of this dashboard over the existing per-CV teach panel.
    out.sort(key=lambda e: (-e["cv_count"], -e["occurrences"]))
    return out[:limit]


# A pattern needs at least this many CVs behind it before it's suggested --
# "HR repeatedly maps X to Y" (build spec §14) means repeatedly, not once.
# A single correction could easily be a one-off judgement call for that
# specific CV, not a rule that should apply to every future upload.
MIN_CV_COUNT_FOR_SUGGESTION = 2
# A pattern is only suggested when this fraction of HR's actual corrections
# for a heading agree on the same destination section. Below this, HR has
# filed the same heading text differently more than once -- real evidence
# that it needs case-by-case judgement, not a blanket mapping -- and
# suggesting one anyway would be exactly the "force a guess" behaviour the
# whole AI feature set is built to avoid.
MIN_AGREEMENT_RATIO = 0.7


def suggest_heading_mappings(
    rows: list[dict[str, Any]],
    taught_headings: set[str],
    min_cv_count: int = MIN_CV_COUNT_FOR_SUGGESTION,
    min_agreement: float = MIN_AGREEMENT_RATIO,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """rows: [{cv_id, section, fields}] from
    storage.list_resolved_formerly_unmapped_items() -- items HR has
    already, individually, corrected out of Unmapped Information. Turns
    that history into "HR has mapped similar headings to X -- save this
    mapping?" suggestions (build spec §14), never a mapping written
    automatically: this function only ever returns candidates for
    main.py's endpoint to show a reviewer, exactly like every other AI
    suggestion in this codebase. Saving one still goes through the
    existing, unchanged /api/heading-mappings endpoint (§5g) -- this is a
    smarter way to arrive at that same explicit-approval step, not a new
    storage mechanism.
    """
    # context -> section -> {occurrences, cv_ids}
    by_context: dict[str, dict[str, dict[str, Any]]] = {}
    examples: dict[str, str] = {}
    for row in rows:
        fields = json.loads(row["fields"])
        context = (fields.get("context") or "").strip()
        if not context or context == "Top of document":
            continue
        section = row["section"]
        by_section = by_context.setdefault(context, {})
        entry = by_section.setdefault(section, {"occurrences": 0, "cv_ids": set()})
        entry["occurrences"] += 1
        entry["cv_ids"].add(row["cv_id"])
        examples.setdefault(context, fields.get("value", ""))

    out = []
    for context, by_section in by_context.items():
        if context.casefold() in taught_headings:
            continue
        total_cv_ids: set[str] = set()
        for entry in by_section.values():
            total_cv_ids |= entry["cv_ids"]
        if len(total_cv_ids) < min_cv_count:
            continue

        total_occurrences = sum(e["occurrences"] for e in by_section.values())
        dominant_section, dominant_entry = max(
            by_section.items(), key=lambda kv: kv[1]["occurrences"],
        )
        agreement = dominant_entry["occurrences"] / total_occurrences
        if agreement < min_agreement:
            continue

        out.append({
            "context": context,
            "suggested_section": dominant_section,
            "cv_count": len(dominant_entry["cv_ids"]),
            "occurrences": dominant_entry["occurrences"],
            "agreement": round(agreement, 2),
            "example": examples.get(context, ""),
        })

    out.sort(key=lambda e: (-e["cv_count"], -e["occurrences"]))
    return out[:limit]
