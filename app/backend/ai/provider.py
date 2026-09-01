"""Provider-agnostic interface for the optional local AI analysis stage.

This is deliberately narrow. The build spec this implements (see
`MDX FACULTY CV CONVERTER — LOCAL AI INTELLIGENCE INTEGRATION BUILD
SPECIFICATION.md`) describes a much larger system -- automatic semantic
segmentation, an MDX knowledge base config, HR-mapping suggestions. None of
that is implemented yet. What exists now is the smallest useful, safe slice
of it: given one already-extracted item the rule engine couldn't confidently
place, a first AI pass (`analyze_content`) suggests ONE MDX section, and an
optional second, independent pass (`review_classification`, §11 of the
spec) checks that suggestion before it's ever shown as trustworthy. Neither
pass ever touches text, runs automatically, or bypasses HR review -- see
`main.py`'s `/api/items/{id}/analyze-with-ai` for where this plugs into the
existing pipeline, and `ai/two_stage.py` for how the two passes combine into
one calculated confidence.

A future provider (a second local model, a different local runtime) only
needs to implement this same interface; nothing outside `ai/` needs to know
which one is active.
"""
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Segment:
    """One piece of a split item. `text` must be an exact, verbatim
    substring of the original item's source text -- the AI is classifying
    and cutting existing text, never writing new text (build spec §9 point
    4: "The AI must not rewrite facts during segmentation"). Enforced
    server-side in ai/ollama_client.py's validator, not merely requested by
    the prompt; a segment that fails this check invalidates the whole
    segmentation result, not just itself -- see AISegmentation's docstring."""
    text: str
    section: str


@dataclass
class AISegmentation:
    """The AI's opinion on whether one item is actually several facts
    filed together that belong in different sections -- build spec §9.

    `status` is "SEGMENT" (segments below are the proposed split),
    "NO_SPLIT" (the AI judged this is genuinely one fact, not several), or
    "REVIEW_REQUIRED" (ambiguous whether/how to split -- build spec §9
    point 3: "Complex splitting should be flagged for HR review").

    All-or-nothing validation: every segment must be an exact substring of
    the original text, AND the segments together must account for the
    entire original text (build spec §6's zero-content-loss policy applied
    to splitting -- a segmentation that quietly drops a clause is worse
    than not splitting at all). If either check fails for any segment, the
    whole AISegmentation is invalid and the provider returns None instead,
    exactly like any other unusable AI response.
    """
    status: str  # "SEGMENT" | "NO_SPLIT" | "REVIEW_REQUIRED"
    segments: list[Segment] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class AISuggestion:
    """The AI's opinion on where one item belongs, never its content.

    `status` is "CLASSIFY" when the model committed to a section, or
    "REVIEW_REQUIRED" when it declined to guess -- callers must not treat a
    REVIEW_REQUIRED result as a recommendation to act on, only to show the
    reviewer that AI analysis was inconclusive.
    """
    status: str  # "CLASSIFY" | "REVIEW_REQUIRED"
    section: str | None
    confidence: float
    reasoning: str


@dataclass
class AIReview:
    """A second, independent AI's opinion on a first AI's proposal --
    never on the source text directly. The reviewer is deliberately not
    told the classifier's confidence or reasoning, only its proposed
    section, so it can't just rubber-stamp the same chain of thought that
    produced it; see build spec §11.

    `verdict` is "ACCEPT" (the reviewer agrees), "CHANGE" (the reviewer
    proposes a different section -- `section` is that alternative), or
    "REVIEW_REQUIRED" (the reviewer isn't confident either way). A CHANGE
    is never applied automatically -- two AI passes disagreeing is exactly
    the case that must reach a person, not resolve itself; see
    ai/two_stage.py.
    """
    verdict: str  # "ACCEPT" | "CHANGE" | "REVIEW_REQUIRED"
    section: str | None
    confidence: float
    reasoning: str


class AIProvider(Protocol):
    def is_available(self) -> bool:
        """Whether this provider is configured at all (e.g. env vars set).
        Does not guarantee the service is actually reachable right now --
        see health_check() for that."""
        ...

    def health_check(self) -> bool:
        """Whether the service is reachable right now. Called before each
        analysis attempt so a provider that was up a minute ago but has
        since gone offline fails cleanly instead of hanging on a request."""
        ...

    def analyze_content(
        self, source_text: str, current_section: str, valid_sections: list[dict]
    ) -> AISuggestion | None:
        """Suggest where `source_text` belongs, choosing only from
        `valid_sections` (each a {"key": ..., "label": ...} dict -- the
        model is never free to invent a destination name). Returns None on
        any failure (timeout, unreachable, invalid response) -- callers
        must treat None exactly like "AI unavailable", never like an error
        that should propagate and disrupt anything else."""
        ...

    def review_classification(
        self, source_text: str, original_heading: str, proposed_section: str,
        valid_sections: list[dict],
    ) -> AIReview | None:
        """Independently review a proposed classification -- pass 2 of
        build spec §11. Returns None on any failure, exactly like
        analyze_content; a failed review must never be treated as either
        an ACCEPT or a REVIEW_REQUIRED, only as "the second pass could not
        run" (see ai/two_stage.py, which falls back to pass 1 alone with a
        lower calculated confidence when this happens)."""
        ...

    def segment_content(
        self, source_text: str, current_section: str, valid_sections: list[dict]
    ) -> AISegmentation | None:
        """Suggest splitting `source_text` into several MDX-section-tagged
        pieces if it reads as mixed content ("Senior Lecturer / Taught
        courses / Published research / Received a grant" all filed
        together) -- build spec §9. Returns None on any failure OR on any
        segmentation whose segments don't verbatim-reconstruct the
        original text; callers must treat that identically to "AI
        unavailable", never partially apply an invalid split."""
        ...
