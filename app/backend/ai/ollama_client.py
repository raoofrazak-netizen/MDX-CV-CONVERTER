"""Local Ollama implementation of AIProvider.

Talks to Ollama's HTTP API directly via the standard library (no new
dependency added to requirements.txt for this -- Ollama itself is the only
new thing this feature needs installed). Every failure mode -- Ollama not
running, model not pulled, a slow response past AI_TIMEOUT, a response that
isn't valid JSON, a response whose JSON doesn't match the expected shape --
returns None rather than raising, so a caller can always fall back to "AI
unavailable" without a try/except of its own.
"""
import json
import re
import urllib.error
import urllib.request
from typing import Any

from config import AI_TIMEOUT, OLLAMA_HOST, OLLAMA_MODEL

from . import knowledge_base
from .provider import AIReview, AISegmentation, AISuggestion, Segment

SYSTEM_PROMPT = """You are a classification assistant for an official \
university faculty CV. You are given one block of text extracted from a \
CV and a list of valid destination sections. Your ONLY job is to say which \
section this text belongs in, or say you are not sure.

Rules:
- Choose a section ONLY from the provided list of valid section keys. Never \
invent a section name.
- Do not rewrite, summarise, or add to the text. You are classifying it, \
not editing it.
- If the text is genuinely ambiguous or does not clearly fit any listed \
section, set "status" to "REVIEW_REQUIRED" and leave "section" null. Do \
not force a guess.
- Reply with ONLY a JSON object, no other text, in exactly this shape:
{"status": "CLASSIFY" or "REVIEW_REQUIRED", "section": "<one of the valid \
keys, or null>", "confidence": <0.0 to 1.0>, "reasoning": "<one short \
sentence>"}
"""

# Deliberately does not repeat the classifier's own reasoning or confidence
# back to it -- see AIReview's docstring in provider.py for why: a reviewer
# fed the first pass's justification tends to just agree with it, which
# defeats the point of a second, independent opinion.
REVIEWER_SYSTEM_PROMPT = """You are an independent quality reviewer for an \
official university faculty CV classification system. Another process has \
proposed filing one block of CV text under a specific section. Your job is \
to independently judge whether that placement is correct -- not to explain \
why it might be, not to rubber-stamp it.

Rules:
- Judge the text on its own merits against the proposed section. Do not \
assume the proposal is correct just because it was made.
- If you agree, set "verdict" to "ACCEPT".
- If you disagree and a different section from the valid list is clearly \
more correct, set "verdict" to "CHANGE" and name that section.
- If you are not confident either way, set "verdict" to "REVIEW_REQUIRED" \
and leave "section" null. Do not force a guess.
- Reply with ONLY a JSON object, no other text, in exactly this shape:
{"verdict": "ACCEPT" or "CHANGE" or "REVIEW_REQUIRED", "section": "<one of \
the valid keys, or null>", "confidence": <0.0 to 1.0>, "reasoning": "<one \
short sentence>"}
"""

SEGMENTATION_SYSTEM_PROMPT = """You are a content-segmentation assistant \
for an official university faculty CV. You are given one block of text \
extracted from a CV that may describe SEVERAL DIFFERENT KINDS of \
information mixed together (for example a job title, teaching duties, a \
publication, and a grant, all written as one paragraph).

Rules:
- Your job is ONLY to decide where to cut the text and which section each \
piece belongs to. You may NEVER add, remove, reorder, paraphrase, \
summarise, or correct a single word of the original text.
- Every piece you return, concatenated back together in the order given, \
must reconstruct the ENTIRE original text exactly, character for \
character, including whitespace and punctuation. If you cannot do this, do \
not attempt a split.
- If the text is genuinely one single fact that belongs in one section, \
set "status" to "NO_SPLIT" and return no segments -- do not invent a split \
just to have one.
- If it's ambiguous whether or how to split it, set "status" to \
"REVIEW_REQUIRED" and return no segments. Do not force a split.
- If it is clearly several distinct facts, set "status" to "SEGMENT" and \
return each piece, in original order, tagged with a section from the \
provided valid list.
- Reply with ONLY a JSON object, no other text, in exactly this shape:
{"status": "SEGMENT" or "NO_SPLIT" or "REVIEW_REQUIRED", "segments": \
[{"text": "<exact excerpt, verbatim>", "section": "<valid key>"}, ...], \
"reasoning": "<one short sentence>"}
"""


def _call_ollama_json(system_prompt: str, prompt: str) -> dict | None:
    """Shared HTTP call for both passes. Every failure mode -- Ollama not
    running, model not pulled, a slow response past AI_TIMEOUT, a response
    that isn't valid JSON at either the transport or model-output layer --
    returns None rather than raising, so neither pass needs its own
    try/except."""
    payload = {
        "model": OLLAMA_MODEL,
        "system": system_prompt,
        "prompt": prompt,
        "format": "json",  # Ollama enforces syntactically valid JSON output.
        "stream": False,
        "options": {"temperature": 0.1},
    }
    try:
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None

    try:
        return json.loads(body.get("response", ""))
    except json.JSONDecodeError:
        return None


class OllamaProvider:
    def is_available(self) -> bool:
        return bool(OLLAMA_HOST and OLLAMA_MODEL)

    def health_check(self) -> bool:
        if not self.is_available():
            return False
        try:
            req = urllib.request.Request(f"{OLLAMA_HOST}/api/version")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def analyze_content(
        self, source_text: str, current_section: str, valid_sections: list[dict]
    ) -> AISuggestion | None:
        if not self.health_check():
            return None

        section_list = "\n".join(
            knowledge_base.format_section_for_prompt(s["key"], s["label"]) for s in valid_sections
        )
        prompt = (
            f"Currently filed under: {current_section}\n\n"
            f"Valid destination sections:\n{section_list}\n\n"
            f"CV text to classify:\n{source_text}"
        )
        parsed = _call_ollama_json(SYSTEM_PROMPT, prompt)
        if parsed is None:
            return None
        return _validate_suggestion(parsed, valid_sections)

    def review_classification(
        self, source_text: str, original_heading: str, proposed_section: str,
        valid_sections: list[dict],
    ) -> AIReview | None:
        if not self.health_check():
            return None

        section_list = "\n".join(
            knowledge_base.format_section_for_prompt(s["key"], s["label"]) for s in valid_sections
        )
        proposed_label = next(
            (s["label"] for s in valid_sections if s["key"] == proposed_section), proposed_section,
        )
        prompt = (
            f"Original heading in the source CV: {original_heading}\n\n"
            f"Proposed section: {proposed_label}\n\n"
            f"Valid destination sections:\n{section_list}\n\n"
            f"CV text being classified:\n{source_text}"
        )
        parsed = _call_ollama_json(REVIEWER_SYSTEM_PROMPT, prompt)
        if parsed is None:
            return None
        return _validate_review(parsed, valid_sections)

    def segment_content(
        self, source_text: str, current_section: str, valid_sections: list[dict]
    ) -> AISegmentation | None:
        if not self.health_check():
            return None

        section_list = "\n".join(
            knowledge_base.format_section_for_prompt(s["key"], s["label"]) for s in valid_sections
        )
        prompt = (
            f"Currently filed under: {current_section}\n\n"
            f"Valid destination sections:\n{section_list}\n\n"
            f"CV text to consider splitting:\n{source_text}"
        )
        parsed = _call_ollama_json(SEGMENTATION_SYSTEM_PROMPT, prompt)
        if parsed is None:
            return None
        return _validate_segmentation(parsed, source_text, valid_sections)


def _resolve_section_key(raw: Any, valid_sections: list[dict]) -> str | None:
    """Match a model-returned section string against the controlled
    vocabulary, case-insensitively, against either the canonical key
    ("qualifications") or the human-readable label ("Qualifications"), and
    always returns the canonical key. Found necessary via live testing: the
    §15 knowledge base's enriched prompt shows the label prominently right
    next to the key on every line ("- qualifications (Qualifications):
    ..."), and a small local model started echoing the label's casing back
    instead of the key ("Qualifications" instead of "qualifications") --
    an accurate, well-reasoned answer that the OLD exact-match check
    rejected outright as if it were gibberish. This still refuses anything
    outside the controlled vocabulary; it only tolerates how a real, in-
    vocabulary answer gets capitalised."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = raw.strip().casefold()
    for s in valid_sections:
        if candidate == s["key"].casefold() or candidate == s["label"].casefold():
            return s["key"]
    return None


def _validate_suggestion(parsed: dict, valid_sections: list[dict]) -> AISuggestion | None:
    """Strict schema check -- a response that almost matches is still
    rejected. A model that names a section outside the controlled
    vocabulary, or skips a required field, is treated the same as no
    response at all; guessing at what it "probably meant" is exactly the
    kind of silent trust the build spec forbids."""
    if not isinstance(parsed, dict):
        return None
    status = parsed.get("status")
    if status not in ("CLASSIFY", "REVIEW_REQUIRED"):
        return None
    if status == "CLASSIFY":
        section = _resolve_section_key(parsed.get("section"), valid_sections)
        if section is None:
            return None
    else:
        section = None
    confidence = parsed.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        return None
    reasoning = parsed.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        return None
    return AISuggestion(
        status=status, section=section, confidence=float(confidence),
        reasoning=reasoning.strip(),
    )


def _validate_review(parsed: dict, valid_sections: list[dict]) -> AIReview | None:
    """Same strict-schema philosophy as _validate_suggestion, for the
    reviewer's response shape instead."""
    if not isinstance(parsed, dict):
        return None
    verdict = parsed.get("verdict")
    if verdict not in ("ACCEPT", "CHANGE", "REVIEW_REQUIRED"):
        return None
    if verdict == "CHANGE":
        section = _resolve_section_key(parsed.get("section"), valid_sections)
        if section is None:
            return None
    else:
        section = None
    confidence = parsed.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        return None
    reasoning = parsed.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        return None
    return AIReview(
        verdict=verdict, section=section, confidence=float(confidence),
        reasoning=reasoning.strip(),
    )


# A cut is allowed to fall on whitespace/punctuation the model doesn't
# repeat verbatim in either neighbouring segment (a bullet glyph consumed
# as a separator, a line break collapsed to a space) without that counting
# as lost content -- only alphanumeric characters going missing is treated
# as an unsafe segmentation. Mirrors the same spirit as the bullet/segment-
# break handling already used throughout rule_classifier.py.
_NEGLIGIBLE_CHARS_RE = re.compile(r"[\s,.;:•●▪‣⁃\-–—\"'()\[\]]")


def _validate_segmentation(
    parsed: dict, original_text: str, valid_sections: list[dict]
) -> AISegmentation | None:
    """All-or-nothing: either every segment is real and the split accounts
    for the whole original text, or the entire result is rejected (see
    AISegmentation's docstring in provider.py for why this can't be a
    partial acceptance)."""
    if not isinstance(parsed, dict):
        return None
    status = parsed.get("status")
    if status not in ("SEGMENT", "NO_SPLIT", "REVIEW_REQUIRED"):
        return None
    if status != "SEGMENT":
        return AISegmentation(status=status, segments=[], reasoning=str(parsed.get("reasoning") or "").strip())

    raw_segments = parsed.get("segments")
    if not isinstance(raw_segments, list) or len(raw_segments) < 2:
        # A "split" into fewer than two pieces isn't a split.
        return None

    segments: list[Segment] = []
    remaining = original_text
    for raw in raw_segments:
        if not isinstance(raw, dict):
            return None
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        section = _resolve_section_key(raw.get("section"), valid_sections)
        if section is None:
            return None
        # Consume the FIRST remaining occurrence, in order -- enforces both
        # "verbatim" (it must be found at all) and "in original order"
        # (later segments can only match what's left after earlier ones
        # are removed, so a model can't satisfy the check by reusing the
        # same span for two different segments).
        idx = remaining.find(text)
        if idx == -1:
            return None
        remaining = remaining[:idx] + remaining[idx + len(text):]
        segments.append(Segment(text=text, section=section))

    leftover = _NEGLIGIBLE_CHARS_RE.sub("", remaining)
    if leftover:
        # Something with real content wasn't accounted for by any segment
        # -- exactly the silent-content-loss case build spec §6 forbids.
        # Reject the whole segmentation rather than accept a partial one.
        return None

    reasoning = parsed.get("reasoning")
    return AISegmentation(
        status="SEGMENT", segments=segments,
        reasoning=reasoning.strip() if isinstance(reasoning, str) else "",
    )


def validate_segments(
    segments: list[dict], original_text: str, valid_sections: list[dict]
) -> list[Segment] | None:
    """Public re-entry point into the exact same all-or-nothing safety
    check _validate_segmentation already applies to a fresh AI response --
    used by main.py's accept-ai-segments endpoint to re-verify
    client-submitted segments server-side before ever writing them to the
    database. Never trust that a client echoing back what it was shown is
    the same thing it was actually shown; re-validating against the item's
    real, freshly-fetched source text is what actually enforces the
    verbatim guarantee, not the client's word for it."""
    result = _validate_segmentation(
        {"status": "SEGMENT", "segments": segments, "reasoning": ""}, original_text, valid_sections,
    )
    return result.segments if result is not None else None
