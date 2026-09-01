"""Loads the MDX section knowledge base -- build spec §15: "a structured
configuration representing the complete MDX Faculty CV template... Do not
embed the complete knowledge base directly inside Python prompts. Load it
from structured configuration."

Two sources are merged at load time rather than duplicated by hand:
- `mdx_knowledge_base.json` carries what nothing else in the codebase
  already knows: description, examples, inclusion/exclusion rules, related
  sections.
- Heading synonyms are NOT duplicated here. They're read live from
  `rule_classifier.SYNONYM_HEADINGS` (the actual, tested vocabulary the
  rule engine matches against) and `config.SECTIONS`' own `heading_text`,
  so the AI's controlled vocabulary can never drift out of sync with what
  the deterministic classifier already recognises -- a synonym added to
  one is a synonym known to both without a second place to edit.

Every section in `config.SECTION_KEYS` that main.py actually offers to AI
(see `_AI_VALID_SECTIONS`) must have a JSON entry; a missing one fails
loudly at import time (see `_validate_coverage`), not silently with a
thinner prompt for that one section.
"""
import json
from pathlib import Path
from typing import Any

_KB_PATH = Path(__file__).resolve().parent / "mdx_knowledge_base.json"


def _load_raw() -> dict[str, Any]:
    with open(_KB_PATH, encoding="utf-8") as f:
        return json.load(f)


def _build_knowledge_base() -> tuple[int, dict[str, dict[str, Any]]]:
    raw = _load_raw()
    version = raw["schema_version"]

    # Imported here, not at module top, to avoid a circular import: main.py
    # imports from ai.*, and rule_classifier/config sit below it in the
    # dependency graph -- importing them at ai/knowledge_base.py's own
    # module level is safe (this module doesn't get imported BY either of
    # them), but kept local anyway so this file's own import order stays
    # obviously one-directional to a future reader.
    import rule_classifier
    from config import SECTIONS

    heading_text_by_key = {s["key"]: s["heading_text"] for s in SECTIONS}

    sections: dict[str, dict[str, Any]] = {}
    for key, entry in raw["sections"].items():
        synonyms = list(rule_classifier.SYNONYM_HEADINGS.get(key, []))
        official = heading_text_by_key.get(key)
        if official and official not in synonyms:
            synonyms.insert(0, official)
        sections[key] = {**entry, "heading_synonyms": synonyms}
    return version, sections


def _validate_coverage(sections: dict[str, dict[str, Any]]) -> None:
    from config import SECTIONS

    ai_offered_keys = {
        s["key"] for s in SECTIONS if s["heading_text"] or s["key"] in ("skills", "language_proficiency")
    }
    missing = ai_offered_keys - sections.keys()
    if missing:
        raise RuntimeError(
            f"ai/mdx_knowledge_base.json is missing entries for: {sorted(missing)}. "
            "Every section main.py offers to AI must have a knowledge-base entry -- "
            "a thinner prompt for one section silently, rather than a loud failure, "
            "is exactly the kind of drift this module exists to prevent."
        )


KB_VERSION, _SECTIONS = _build_knowledge_base()
_validate_coverage(_SECTIONS)


def get_section_context(key: str) -> dict[str, Any] | None:
    return _SECTIONS.get(key)


def all_section_keys() -> list[str]:
    return list(_SECTIONS.keys())


def format_section_for_prompt(key: str, label: str) -> str:
    """One section's knowledge rendered as prompt text -- description,
    heading synonyms actually seen on real CVs, a worked example, and what
    NOT to file here. Deliberately compact: a full dump of every example
    and rule for all 17 sections in every single prompt would burn context
    and latency for no benefit on a model this small; one example and the
    sharpest exclusion rule carry most of the signal."""
    ctx = _SECTIONS.get(key)
    if not ctx:
        return f"- {key}: {label}"
    lines = [f"- {key} ({label}): {ctx['description']}"]
    if ctx.get("examples"):
        lines.append(f"    e.g. \"{ctx['examples'][0]}\"")
    if ctx.get("exclude"):
        lines.append(f"    NOT: {ctx['exclude'][0]}")
    return "\n".join(lines)
