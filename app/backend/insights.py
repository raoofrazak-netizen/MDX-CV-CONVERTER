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
