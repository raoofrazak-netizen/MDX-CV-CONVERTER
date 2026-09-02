"""End-to-end regression harness across a corpus of real CVs.

Run it after any change to extraction, classification or generation:

    python test_corpus.py

Every fix to this pipeline has so far been prompted by one CV failing, and
fixing that CV in isolation is how the same class of bug keeps reappearing
in a different guise. This harness asserts the invariants that must hold for
EVERY CV -- whatever its layout, template or wording -- and fails loudly with
the offending value, so a regression is visible immediately rather than on
the next upload.

Invariants checked per CV:
  1. Text is extracted at all.
  2. A meaningful number of items is classified (not just the letterhead).
  3. A full name is found, and is a name -- not a job title, heading,
     section label or contact string.
  4. An email is found whenever the source contains one.
  5. No item is an orphaned date fragment ("2025-26" on its own).
  6. No body item is just an echo of the person's name.
  7. No employment line renders as bare dates with no role.
  8. Generation produces a valid, non-empty DOCX.

Conformance to the current document-generation policy (HR's explicit
instruction, overriding the conversion spec's original §2/§9 -- see
FIXLOG.md): a management-facing document must never show a section whose
title doesn't correspond to real content:
  9.  A section with approved content keeps its heading; a section with none
      does not appear in the document at all -- heading included. (An
      earlier version of this policy required the opposite -- every official
      heading present, empty ones reading "Information not provided" -- and
      an earlier version of this suite enforced that. It now enforces the
      current decision.)
  10. The UNMAPPED INFORMATION note is never written into the generated
      document. The safety net itself -- reconciliation against the source
      text, and every unmapped item visible in the review screen before
      generation unlocks -- is unchanged; only the appendix in the finished
      DOCX is gone.
  11. Extracted identifiers are usable addresses, not truncated fragments.
  12. Structured qualification fields are self-consistent: a stored year is
      a real year, and a rendered line never loses the degree.
"""
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import template_engine
import unmapped
from classifier import _validate_against_source, classify
from config import SECTIONS
from extraction import ExtractionError, blocks_to_plain_text, extract
from formatting import format_item
from rule_classifier import (
    CALENDAR_YEAR_RE, ORG_KEYWORDS, TITLE_KEYWORDS, _find_heading_key,
    classify_rule_based,
)
from unmapped import UNMAPPED_HEADING

CORPUS_DIRS = [
    Path(r"C:\Users\test\Downloads"),
    Path(r"C:\Users\test\Downloads\testnew"),
    Path(r"C:\Users\test\Downloads\testnew\New folder"),
    Path(r"C:\Users\test\Downloads\testnew\new folder cv"),
    Path(r"C:\Users\test\Downloads\testnew\Staff CV"),
]
# Generated outputs and the blank template are inputs to nothing.
SKIP_PATTERNS = (
    "MDX CV", "Template", "portal output", "~$", "(v2)", "(v3)",
    "Day1 Pack",  # course material, not a CV -- see NON_CV note below
)
# Uploading a non-CV is a real user error and the app must fail gracefully
# on it, but it is not a classification target, so it is not asserted here.

MIN_ITEMS = 5
ORPHAN_FRAGMENT_RE = re.compile(r"^[\s\d\-–—|,()]{2,14}$")
# A rendered employment line carrying no words at all -- only digits and
# punctuation, e.g. "26 (2024)". Must not match a line that merely OPENS
# with a bracket, such as "(UNDP supported programme) Department of...".
BARE_DATE_LINE_RE = re.compile(r"^[\s\d\-–—|,.()]+$")
WELDED_WORDS_RE = re.compile(r"[A-Z]{4,}[A-Z][a-z]{3,}")

# Blank sample templates ship with placeholder contact details and no real
# person in them. They are valid uploads to survive without crashing, but
# there is no name to find, so the name assertion does not apply.
PLACEHOLDER_MARKERS = (
    "your@email", "xxx-xxx", "(xxx)", "your address", "city, state, zip",
    "lorem ipsum", "firstname lastname", "[insert",
    # A vendor sample resume addressed to a hypothetical candidate, not a
    # real person's CV -- same class of no-real-name file as the other
    # markers above, just signed off differently (rule_classifier.py's
    # VENDOR_BOILERPLATE_RE recognises the same text for the same reason).
    "dear job seeker", "per resume", "youremail@",
)


def is_placeholder_template(text: str) -> bool:
    low = text.casefold()
    return sum(1 for m in PLACEHOLDER_MARKERS if m in low) >= 2


def corpus_files() -> list[Path]:
    seen, files = set(), []
    for directory in CORPUS_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*")):
            if path.suffix.lower() not in (".pdf", ".docx"):
                continue
            if any(pattern in path.name for pattern in SKIP_PATTERNS):
                continue
            if path.name.lower() in seen:
                continue
            seen.add(path.name.lower())
            files.append(path)
    return files


def check(path: Path) -> list[str]:
    """Returns a list of failure messages; empty means the CV passed."""
    failures: list[str] = []

    try:
        text = blocks_to_plain_text(extract(path))
    except ExtractionError as exc:
        # Refusing a file is a correct outcome, not a failure, when the file
        # genuinely cannot be read: a scan with no text layer, or a document
        # whose embedded font scrambles every word. What must never happen is
        # a refusal that reads like a crash, so the message is checked instead.
        message = str(exc)
        if len(message) < 60 or not message.rstrip().endswith("."):
            return [f"extraction refused the file with an unhelpful message: {message!r}"]
        return []
    if len(text.strip()) < 200:
        failures.append(f"only {len(text.strip())} chars extracted — text is not being read")

    placeholder = is_placeholder_template(text)

    # The verbatim-quote guard must never have to fire. It exists to catch a
    # fabricated quote, but it also silently discards an item the classifier
    # assembled from non-adjacent source lines -- which is data loss wearing
    # a safety check's clothing. One CV lost an entire degree that way. If
    # this fires, fix the grouping; do not relax the guard.
    unvalidated = classify_rule_based(text, path.name)
    validated = _validate_against_source(unvalidated, text)
    if len(validated) < len(unvalidated):
        lost = next(
            (i for i in unvalidated if i not in validated), {"source_text": "?"}
        )
        failures.append(
            f"{len(unvalidated) - len(validated)} item(s) discarded by the verbatim "
            f"guard — grouping built text not present in the CV: {lost['source_text'][:70]!r}"
        )

    items = classify(text, path.name)
    if len(items) < MIN_ITEMS and not placeholder:
        failures.append(f"only {len(items)} items classified (expected >= {MIN_ITEMS})")

    by_section: dict[str, list[dict]] = {}
    for item in items:
        by_section.setdefault(item["section"], []).append(item)

    # 3. name present, and actually a name
    name_items = by_section.get("full_name", [])
    if not name_items:
        if not placeholder:
            failures.append("no full name found")
    elif not placeholder:
        name = (name_items[0]["fields"].get("value") or "").strip()
        if not name:
            failures.append("full name item has an empty value")
        elif any(kw in name.lower() for kw in TITLE_KEYWORDS):
            failures.append(f"full name looks like a job title: {name!r}")
        elif _find_heading_key(name) is not None:
            failures.append(f"full name looks like a section heading: {name!r}")
        elif "@" in name or any(c.isdigit() for c in name):
            failures.append(f"full name contains contact data: {name!r}")
        elif any(kw in name.lower() for kw in ORG_KEYWORDS):
            failures.append(f"full name looks like an organisation: {name!r}")
        else:
            # A name that is a fragment of the job title is a slice of the
            # wrong line, not a person ("FIFTH GRADE" out of "FIFTH GRADE
            # TEACHER").
            title = next(
                (j["fields"].get("value") or "" for j in by_section.get("job_title", [])), ""
            )
            if title and name.lower() in title.lower() and name.lower() != title.lower():
                failures.append(f"full name is a fragment of the job title: {name!r}")

    # Letterhead values must not carry unbalanced brackets -- a sign the
    # value was sliced out of its surrounding text at the wrong offset.
    for section in ("contact_info", "email", "full_name", "job_title"):
        for entry in by_section.get(section, []):
            value = str(entry["fields"].get("value") or "")
            if value.count("(") != value.count(")"):
                failures.append(f"unbalanced brackets in {section}: {value!r}")

    # A job title must be a title, not the template's own prompt label.
    for job in by_section.get("job_title", []):
        value = (job["fields"].get("value") or "").strip()
        if value.endswith(":") or _find_heading_key(value) is not None:
            failures.append(f"job title is a label, not a title: {value!r}")

    # Words welded together across a line break, e.g. "TEACHERNorthwood".
    # Narrowly targeted at an ALL-CAPS run running straight into a Title-case
    # word: a looser test flags legitimate CamelCase ("RandomizedSearchCV",
    # "StreetLaw") and URLs, and a suite that cries wolf gets ignored.
    for item in items:
        candidate = item["source_text"]
        if "@" in candidate or "://" in candidate:
            continue
        if WELDED_WORDS_RE.search(candidate):
            failures.append(f"run-together words in {item['section']}: {candidate[:60]!r}")
            break

    # A section heading must never be published as an item of content.
    # Publications legitimately keep their internal group headings.
    for item in items:
        if item["section"] in ("publications", "biography"):
            continue
        if _find_heading_key(item["source_text"]) is not None:
            failures.append(
                f"heading leaked in as content in {item['section']}: {item['source_text'][:60]!r}"
            )
            break

    # 4. email present when the source has one
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text) and not placeholder:
        if not by_section.get("email"):
            failures.append("source contains an email address but none was extracted")

    name_value = ""
    if name_items:
        name_value = " ".join((name_items[0]["fields"].get("value") or "").split()).casefold()

    for item in items:
        source_text = item["source_text"]
        # 5. orphaned date fragments. Letterhead fields are exempt: a phone
        # number is legitimately all digits and punctuation.
        if item["section"] not in ("contact_info", "email") and ORPHAN_FRAGMENT_RE.match(
            source_text.strip()
        ):
            failures.append(f"orphan fragment item in {item['section']}: {source_text!r}")
        # 6. name echoed as body content
        if (
            name_value
            and item["section"] not in ("full_name", "job_title", "contact_info", "email")
            and " ".join(source_text.split()).casefold() == name_value
        ):
            failures.append(f"name echoed as content in {item['section']}")
        # 7. employment lines that render as dates only
        if item["section"] in ("present_employment", "previous_employment"):
            rendered = format_item(item["section"], item["fields"], source_text)
            if BARE_DATE_LINE_RE.match(rendered):
                failures.append(f"employment line has no role: {rendered!r}")

    # 10. unmapped content must be verbatim and traceable, like every other
    # item. A paraphrased "unmapped" entry would be a fabrication wearing a
    # safety net's clothing.
    normalized_source = " ".join(text.split()).casefold()
    orphans = unmapped.find_unmapped(text, items)
    for orphan in orphans:
        if " ".join(orphan["text"].split()).casefold() not in normalized_source:
            failures.append(f"unmapped entry is not verbatim from the CV: {orphan['text'][:60]!r}")
            break
    # An orphan that duplicates a classified item means the reconciliation is
    # miscounting, and HR would see the same content twice.
    for orphan in orphans:
        flat = " ".join(orphan["text"].split()).casefold()
        if any(flat in " ".join(i["source_text"].split()).casefold() for i in items):
            failures.append(f"content reported as unmapped is already classified: {orphan['text'][:60]!r}")
            break

    # 11. identifiers must be addresses someone can actually follow
    for link in by_section.get("profiles_links", []):
        url = (link["fields"].get("url") or "").strip()
        if not url:
            continue  # verbatim fallback for a line with no parseable address
        if not url.lower().startswith(("http://", "https://")):
            failures.append(f"profile URL is not a usable address: {url!r}")
        elif url.endswith(("-", "_")) or len(url) < 12:
            failures.append(f"profile URL looks truncated: {url!r}")

    # 12. structured qualifications must be self-consistent
    for qual in by_section.get("qualifications", []):
        fields = qual["fields"]
        year = str(fields.get("year") or "")
        if year and not CALENDAR_YEAR_RE.fullmatch(year):
            failures.append(f"qualification year is not a real year: {year!r}")
        degree = (fields.get("degree") or "").strip()
        if degree:
            rendered = format_item("qualifications", fields, qual["source_text"])
            if degree.lower() not in rendered.lower():
                failures.append(f"rendered qualification lost its degree: {rendered[:70]!r}")
                break

    # 8. generation produces a valid document
    payload = {
        section: [{"fields": i["fields"], "source_text": i["source_text"]} for i in group]
        for section, group in by_section.items()
    }
    # The pipeline adds these after classification, so the harness reproduces
    # that step -- otherwise the generated document under test is not the one
    # a reviewer would receive.
    if orphans:
        payload["unmapped"] = [
            {"fields": {"value": o["text"], "context": o["context"]}, "source_text": o["text"]}
            for o in orphans
        ]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.docx"
            template_engine.populate(payload, photo_path=None, output_path=out)
            if out.stat().st_size < 10_000:
                failures.append("generated DOCX is suspiciously small")
            failures.extend(_check_generated_document(out, payload))
    except Exception as exc:
        failures.append(f"generation failed: {type(exc).__name__}: {exc}")

    return failures


def _document_text(path: Path) -> str:
    """The document's visible text, one line per paragraph.

    Runs within a paragraph are joined with nothing between them: Word splits
    a heading across runs wherever formatting changes, so
    "PROFESSIONAL ASSOCIATION MEMBERSHIPS" + " AND FELLOWSHIPS" is one
    heading, and joining the runs with a space invents a second one that
    matches nothing.
    """
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    lines = []
    for para in re.findall(r"<w:p(?:\s[^>]*)?>.*?</w:p>", xml, re.DOTALL):
        text = "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", para))
        if text.strip():
            lines.append(" ".join(text.split()))
    return "\n".join(lines)


def _check_generated_document(path: Path, payload: dict[str, list[dict]]) -> list[str]:
    """9 + 10, checked against the finished DOCX rather than the item list.

    Reading the generated file is the only way to verify what a reviewer will
    actually receive; asserting on the payload only proves what was meant to
    be written.
    """
    failures: list[str] = []
    body = _document_text(path)

    # 9. a section with approved content must keep its heading; a section
    # with none must not appear at all -- heading included. Reversed from
    # this suite's earlier behaviour (which required the opposite: every
    # official heading present, empty ones reading "Information not
    # provided") on HR's explicit instruction that a management-facing CV
    # must never show a section with nothing behind its title. See
    # FIXLOG.md for the change; this suite is written to the CURRENT
    # decision, not the earlier one.
    for section in SECTIONS:
        heading = section.get("heading_text")
        if not heading or section["key"] == "full_name":
            continue
        has_content = bool(payload.get(section["key"]))
        present = heading in body
        if has_content and not present:
            failures.append(f"section has approved content but its heading is missing: {heading!r}")
            break
        if not has_content and present:
            failures.append(f"empty section was not removed, heading still present: {heading!r}")
            break

    # 10. the UNMAPPED INFORMATION note is never written into the generated
    # document -- HR's explicit instruction. The underlying safety net (the
    # reconciliation in unmapped.py, and the review screen showing every
    # unmapped item before "Generate" unlocks) is unchanged; only the
    # appendix that used to render at the end of the DOCX is gone.
    if UNMAPPED_HEADING in body:
        failures.append("UNMAPPED INFORMATION note was written into the generated document")

    # The template's own instructions must never survive into a real document.
    if "While not all academics may have information to provide" in body:
        failures.append("template instructional text leaked into the output")

    return failures


def main() -> int:
    files = corpus_files()
    if not files:
        print("No CVs found in the corpus directories.")
        return 1

    passed, failed = 0, 0
    print(f"Running {len(files)} CVs through the full pipeline\n" + "=" * 72)
    for path in files:
        failures = check(path)
        if failures:
            failed += 1
            print(f"\nFAIL  {path.name}")
            for f in failures:
                print(f"        - {f}")
        else:
            passed += 1
            print(f"pass  {path.name}")

    print("=" * 72)
    print(f"{passed} passed, {failed} failed, {len(files)} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
