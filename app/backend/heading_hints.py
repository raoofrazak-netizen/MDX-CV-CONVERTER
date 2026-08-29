"""A second, independent read of a CV's own file -- not the plain-text
extraction pipeline everything else uses -- looking only at RELATIVE font
size, to hint that a line the text-based classifier didn't recognise might
still be a heading.

Why relative, not absolute: a spike across the real corpus found no single
font size or "is it bold" rule that held up across templates -- one PDF used
bold for its headings and plain weight for everything else; another used
bold for individual skill bullets and plain weight for its real headings,
the opposite convention. The one signal that held up everywhere checked was
size relative to the document's OWN body text: a real heading was always at
or above whatever size that specific document mostly used, regardless of
what the absolute number was or whether bold was involved at all.

This is deliberately a DEAD END, not an input to classification. Nothing in
rule_classifier.py, routing.py, or template_engine.py reads from this module
-- it only ever supplies a hint surfaced to a human next to an ALREADY
unrecognised heading candidate ("visually looks like a heading -- worth
teaching"). A wrong or missing hint here can never mislabel, move, or lose
a piece of real content, because nothing downstream depends on it.

Every entry point here fails soft: a corrupted file, a PDF with no
recoverable font metadata, an unexpected document structure -- all of it
means "no hint available", never a raised exception that could interrupt
the upload it's attached to.
"""
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

# A line's size has to clear the document's own body size by a real margin
# before it counts as an outlier -- not just a fraction of a point, which
# is noise (rounding, a slightly larger figure mid-sentence), but a
# genuine step up the way a heading actually reads on the page.
SIZE_OUTLIER_RATIO = 1.15
# A heading is a short label, never a paragraph -- caps how many words a
# line can have and still be considered, the same shape constraint
# `_looks_like_heading_line` already applies to the text-only check.
MAX_HEADING_WORDS = 10


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def _docx_line_sizes(path: Path) -> dict[str, float]:
    """{normalized paragraph text: representative font size in points}.

    Only paragraphs where a run actually carries an explicit size are
    included -- many real DOCX templates set size via the paragraph STYLE
    rather than per-run, which python-docx does not resolve automatically,
    and a paragraph with no discoverable size here is simply left out
    rather than guessed at.
    """
    import docx

    sizes: dict[str, float] = {}
    document = docx.Document(str(path))
    for para in document.paragraphs:
        text = _normalize(para.text)
        if not text:
            continue
        run_sizes = [r.font.size.pt for r in para.runs if r.font.size]
        if run_sizes:
            sizes[text] = max(run_sizes)
    return sizes


def _pdf_line_sizes(path: Path) -> dict[str, float]:
    """Same shape as `_docx_line_sizes`, built from a PDF's own content
    stream via pypdf's per-span visitor callback, which exposes the font
    size pypdf already parses out for rendering -- collected per line of
    text rather than per span, since a heading is judged as a whole line."""
    from pypdf import PdfReader

    line_sizes: dict[str, list[float]] = {}
    reader = PdfReader(str(path))
    for page in reader.pages:
        current_line: list[str] = []
        current_sizes: list[float] = []

        def visitor(text: str, cm: Any, tm: Any, font_dict: Any, font_size: float) -> None:
            nonlocal current_line, current_sizes
            if not text:
                return
            if text.endswith("\n"):
                stripped = text[:-1]
                if stripped:
                    current_line.append(stripped)
                    current_sizes.append(font_size)
                if current_line:
                    key = _normalize("".join(current_line))
                    if key:
                        line_sizes.setdefault(key, []).extend(current_sizes)
                current_line, current_sizes = [], []
            else:
                current_line.append(text)
                current_sizes.append(font_size)

        page.extract_text(visitor_text=visitor)
        if current_line:
            key = _normalize("".join(current_line))
            if key:
                line_sizes.setdefault(key, []).extend(current_sizes)

    return {k: max(v) for k, v in line_sizes.items() if v}


def heading_shaped_lines(path: Path) -> set[str]:
    """Normalized text of every line in this file whose font size is a
    real outlier against the document's own body size -- the raw material
    for a "may be a heading" hint. Returns an empty set on ANY failure or
    when the file's suffix isn't recognised; never raises."""
    try:
        suffix = path.suffix.lower()
        if suffix == ".docx":
            sizes = _docx_line_sizes(path)
        elif suffix == ".pdf":
            sizes = _pdf_line_sizes(path)
        else:
            return set()
    except Exception:
        return set()

    if len(sizes) < 4:
        # Too little size information to trust a "body size" estimate --
        # most likely a template that sets size via paragraph style
        # throughout, which this module cannot see. No hint is better than
        # a guess built on almost nothing.
        return set()

    # The mode is body text almost by definition: on any real CV, ordinary
    # paragraphs and bullet lines vastly outnumber headings, so whichever
    # size appears most often IS what "normal" looks like in this document
    # -- median is the fallback for the rare case for a tie or a
    # near-uniform document where mode is not meaningfully distinct.
    counts = Counter(sizes.values())
    body_size = counts.most_common(1)[0][0] if counts else median(sizes.values())
    if not body_size:
        return set()

    threshold = body_size * SIZE_OUTLIER_RATIO
    return {
        text for text, size in sizes.items()
        if size >= threshold and len(text.split()) <= MAX_HEADING_WORDS
    }
