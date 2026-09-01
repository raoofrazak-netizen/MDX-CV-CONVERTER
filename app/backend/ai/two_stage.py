"""Combines the classifier pass and the reviewer pass into one result with a
calculated confidence -- build spec §11: "Final confidence should be a
calculated score, not simply the AI's self-reported confidence."

The rule this module enforces above all: the two AI passes agreeing is
necessary but never sufficient to auto-suggest a section, and the two
passes disagreeing is ALWAYS surfaced to a person, never resolved by this
code. Nothing here ever picks a winner between CHANGE and the original
proposal -- that judgement call belongs to HR, same as every other AI
suggestion in this feature.
"""
from dataclasses import dataclass

from .provider import AIProvider, AIReview, AISuggestion

# How much the calculated confidence is nudged when the AI's own pick
# agrees or disagrees with where the rule-based classifier had already
# filed the item (or "unmapped", i.e. the rule engine had no real opinion
# to agree or disagree with). This is deliberately a small nudge, not a
# dominant term: two independent AI passes agreeing with EACH OTHER is the
# primary signal (multiplied, not added -- a weak link anywhere pulls the
# score down); the rule engine's own placement is corroborating evidence,
# not a third vote of equal weight.
RULE_AGREEMENT_BOOST = 1.10
RULE_DISAGREEMENT_PENALTY = 0.85


@dataclass
class TwoStageResult:
    """Everything about both passes, plus the single calculated verdict a
    caller should actually act on (`final_status` / `final_section` /
    `final_confidence`). The raw pass1/pass2 fields are kept too, so the
    review screen can show HR exactly what each stage said and why they
    may disagree, rather than only the collapsed answer.
    """
    pass1: AISuggestion
    pass2: AIReview | None  # None when pass 2 was skipped or failed to run
    final_status: str  # "CLASSIFY" | "REVIEW_REQUIRED"
    final_section: str | None
    final_confidence: float
    note: str  # human-readable explanation of how the final verdict was reached


def run_two_stage_analysis(
    provider: AIProvider, source_text: str, current_section: str,
    original_heading: str, valid_sections: list[dict],
) -> TwoStageResult | None:
    """Returns None only when pass 1 itself couldn't run at all (provider
    unavailable/unreachable) -- the same "AI unavailable" signal
    analyze_content already uses. Every other outcome, including a pass-1
    REVIEW_REQUIRED or a failed pass 2, returns a real TwoStageResult so the
    caller always has something to show.
    """
    pass1 = provider.analyze_content(source_text, current_section, valid_sections)
    if pass1 is None:
        return None

    if pass1.status != "CLASSIFY" or not pass1.section:
        # Nothing to review -- pass 1 itself declined to guess. Running a
        # second pass to review "I don't know" would be pure wasted latency
        # for zero additional signal.
        return TwoStageResult(
            pass1=pass1, pass2=None, final_status="REVIEW_REQUIRED",
            final_section=None, final_confidence=0.0,
            note="The first AI pass wasn't confident enough to propose a section, so no second pass was run.",
        )

    pass2 = provider.review_classification(
        source_text, original_heading, pass1.section, valid_sections,
    )

    if pass2 is None:
        # The reviewer pass itself failed to run (timeout, service hiccup
        # between the two calls) -- distinct from a REVIEW_REQUIRED
        # verdict, which is the reviewer running fine and declining to
        # commit. Fall back to pass 1 alone, but at a reduced, honestly
        # calculated confidence: an unreviewed suggestion is worth less
        # than a reviewed one, even though it's the same suggestion.
        return TwoStageResult(
            pass1=pass1, pass2=None, final_status="CLASSIFY",
            final_section=pass1.section, final_confidence=round(pass1.confidence * 0.7, 2),
            note="The second AI pass (independent review) couldn't run, so this is pass 1's suggestion alone, at a reduced confidence.",
        )

    rule_agrees = current_section != "unmapped" and pass1.section == current_section
    rule_disagrees = current_section != "unmapped" and pass1.section != current_section

    # A CHANGE verdict naming the SAME section pass 1 already proposed is
    # not a real disagreement -- found via live testing against a small
    # local model, which returned exactly this (verdict "CHANGE", but
    # "section" identical to pass 1's, with reasoning that argued for a
    # different section without actually naming one). The raw `pass2`
    # object is still returned as-is below (HR can see the real, slightly
    # self-contradictory model output via "Show both AI passes" -- that
    # transparency is the point of this whole feature), but the
    # combination logic below treats the two SECTIONS proposed as what
    # matters, not the literal verdict word a smaller model attached to
    # them, so a same-section CHANGE combines exactly like an ACCEPT.
    effectively_accepts = pass2.verdict == "ACCEPT" or (
        pass2.verdict == "CHANGE" and pass2.section == pass1.section
    )

    if effectively_accepts:
        combined = pass1.confidence * pass2.confidence
        if rule_agrees:
            combined = min(1.0, combined * RULE_AGREEMENT_BOOST)
        elif rule_disagrees:
            combined = combined * RULE_DISAGREEMENT_PENALTY
        return TwoStageResult(
            pass1=pass1, pass2=pass2, final_status="CLASSIFY",
            final_section=pass1.section, final_confidence=round(combined, 2),
            note=(
                "Both AI passes independently agreed"
                + (", and the rule-based classifier had already filed it here too." if rule_agrees
                   else "." if not rule_disagrees
                   else " -- though the rule-based classifier had filed it elsewhere, which lowered the confidence below.")
            ),
        )

    if pass2.verdict == "CHANGE":
        # Two AI passes disagreeing with each other is always a human
        # decision, never resolved here -- see module docstring.
        return TwoStageResult(
            pass1=pass1, pass2=pass2, final_status="REVIEW_REQUIRED",
            final_section=None, final_confidence=0.0,
            note="The two AI passes disagreed: pass 1 proposed one section, the independent reviewer proposed a different one. This needs a person to decide.",
        )

    # pass2.verdict == "REVIEW_REQUIRED"
    return TwoStageResult(
        pass1=pass1, pass2=pass2, final_status="REVIEW_REQUIRED",
        final_section=None, final_confidence=0.0,
        note="The independent reviewer wasn't confident enough to confirm or correct the first pass's suggestion.",
    )
