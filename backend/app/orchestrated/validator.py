# Built with Spec4 AI - https://spec4.ai
"""Deterministic checking and repair of the coordinator's delegation decision.

The functional core: pure functions over Pydantic models, no I/O, no clock, and
-- most importantly -- **no access to an agent or an HTTP client of any kind**.

That absence is a design constraint, not an accident of what this file happened
to need. The obvious way to fix a malformed delegation is to ask the model
again, and doing so would spend a second provider request out of a run whose
entire budget is the thing the app exists to demonstrate. Repair here is
arithmetic on a parsed object. A re-prompt is not merely discouraged, it is
structurally impossible: nothing in this module's imports can reach a provider.

## One repair attempt, then stop

Every violation the capability names has a deterministic fix:

- **an off-roster id** cannot occur -- the enum forbids it -- but a *missing*
  selection can, and is filled from the keyword-affinity fallback
- **duplicate ids** lose the duplicate and gain a distinct partner
- **one selection** gains a partner
- **three or more** keeps the first two

If the result still fails after that single pass, the run is abandoned rather
than dispatched. A second pass would be a loop with no fixed point.

## The fan-in checks are lexical, and that is the right choice rather than a
## shortcut

Phase 5 adds four checks over the merge, and every one of them is deliberately
string arithmetic:

- **verbatim-run detection** asks whether text was *copied*, which is a question
  about characters;
- **claim traceability** asks whether a quoted claim actually appears in the
  answer it is attributed to -- again about the quote, since a paraphrase would
  make manufactured disagreement undetectable;
- **the banned-phrase lint** matches known filler;
- **the note/merge echo check** measures restatement.

The phase instruction offers the shared sentence-transformers embedder for "any
semantic overlap signal behind these checks". None of them needs one: a semantic
score cannot tell a quotation from a paraphrase, which is the exact distinction
the traceability check exists to make. Reaching for the embedder would also
break the property this module's tests assert -- that nothing here can reach a
model or a datastore -- and would load a model into the request path of a free
dyno to answer a question that is not being asked.

## Distinctness is a guard, not a verdict

Jaccard similarity over brief tokens measures *wording overlap*. Two briefs can
score low and still ask for the same thing in different words, and the guard
will not notice. What it reliably catches is the failure the capability names --
near-duplicate briefs producing near-duplicate columns -- and the fix appends
each specialist's angle-exclusion clause rather than re-prompting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.app.orchestrated.roster import (
    SPECIALIST_ROSTER_CONFIG,
    SPECIALISTS_PER_RUN,
    RosterEntry,
    find,
)
from backend.app.orchestrated.schemas import (
    Brief,
    Contradiction,
    CoordinatorDraft,
    DelegationDecision,
    FitQuality,
    SpecialistId,
)

#: Wording overlap at or above which the two briefs are treated as
#: near-duplicates. From the capability's own online guard.
JACCARD_THRESHOLD = 0.45

#: Minimum brief length before a brief is replaced rather than kept. A model
#: that returned an empty string technically satisfied the schema and gave the
#: specialist nothing to work from.
MIN_BRIEF_CHARS = 20

_TOKEN = re.compile(r"[a-z0-9']+")

#: Repair rules, named so telemetry can say which one fired rather than only
#: that something did.
RULE_TRIMMED_EXTRA = "trimmed_extra_selections"
RULE_DEDUPLICATED = "deduplicated_selections"
RULE_FILLED_MISSING = "filled_missing_selection"
RULE_REBUILT_BRIEFS = "rebuilt_missing_briefs"
RULE_APPENDED_EXCLUSIONS = "appended_angle_exclusions"


@dataclass
class DelegationCheck:
    """The verdict on one coordinator draft.

    Attributes:
        decision: The decision to dispatch, or None if it could not be repaired.
        rules_fired: Which repairs were applied, in order. Empty when the draft
            was already valid.
        jaccard: Wording overlap between the two briefs, after repair.
        errors: Why the draft was unusable, when `decision` is None.
    """

    decision: DelegationDecision | None
    rules_fired: list[str] = field(default_factory=list)
    jaccard: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when there is a decision to dispatch."""
        return self.decision is not None

    @property
    def repaired(self) -> bool:
        """True when the draft needed at least one deterministic fix."""
        return bool(self.rules_fired)


def tokenise(text: str) -> set[str]:
    """Reduce text to a set of lowercase word tokens.

    Args:
        text: The text to tokenise.

    Returns:
        The distinct tokens. A set rather than a list because Jaccard is a set
        measure -- a brief that repeats one word twenty times is not thereby
        more distinct from its partner.
    """
    return set(_TOKEN.findall(text.lower()))


def jaccard(left: str, right: str) -> float:
    """Token-level Jaccard similarity between two pieces of text.

    Args:
        left: The first text.
        right: The second text.

    Returns:
        Intersection over union, from 0.0 to 1.0. Two empty briefs score 0.0
        rather than 1.0 -- they are not "identical", they are absent, and the
        length guard is what catches that.
    """
    a, b = tokenise(left), tokenise(right)
    if not a or not b:
        return 0.0

    union = a | b
    return len(a & b) / len(union)


def fallback_partner(question: str, exclude: frozenset[SpecialistId]) -> SpecialistId:
    """Pick a specialist by keyword affinity, avoiding those already chosen.

    The rules-based fallback the capability calls for, used only to complete a
    delegation the model left short. It is a weak signal and never overrides a
    valid choice.

    Args:
        question: The visitor's question, lowercased internally.
        exclude: Ids already selected.

    Returns:
        The best-scoring available specialist, or the first available one when
        nothing matches -- a partner chosen arbitrarily is still better than a
        run refused for want of a second column.
    """
    lowered = question.lower()
    available = [
        entry
        for entry in SPECIALIST_ROSTER_CONFIG
        if SpecialistId(entry.id) not in exclude
    ]
    if not available:  # pragma: no cover - the roster is larger than any pairing
        return SpecialistId(SPECIALIST_ROSTER_CONFIG[0].id)

    def score(entry: RosterEntry) -> int:
        return sum(1 for keyword in entry.keyword_affinities if keyword in lowered)

    best = max(available, key=score)
    return SpecialistId(best.id)


def _brief_for(specialist_id: SpecialistId, briefs: list[Brief]) -> Brief | None:
    """Find the brief written for one specialist.

    Args:
        specialist_id: The specialist to look for.
        briefs: The draft's briefs.

    Returns:
        The matching brief, or None.
    """
    for brief in briefs:
        if brief.specialist_id == specialist_id:
            return brief
    return None


def _default_brief(specialist_id: SpecialistId, question: str) -> Brief:
    """Build a brief for a specialist the model did not write one for.

    Assembled from the roster's own prompt fragment and exclusion clause, so a
    generated brief and a repaired one instruct the specialist in the same
    terms.

    Args:
        specialist_id: The specialist needing a brief.
        question: The visitor's question.

    Returns:
        A usable brief.
    """
    entry = find(specialist_id.value)
    fragment = entry.system_prompt_fragment if entry else ""
    exclusion = entry.angle_exclusion if entry else ""
    return Brief(
        specialist_id=specialist_id,
        instruction=(
            f"Answer this question in your own mode of reasoning: {question} "
            f"{fragment} {exclusion}"
        ).strip(),
    )


def validate_and_repair(draft: CoordinatorDraft, *, question: str) -> DelegationCheck:
    """Check a coordinator draft and deterministically repair what it can.

    Google-style docstring per project convention. **Makes no model call and
    cannot**: this module imports nothing that reaches a provider.

    Args:
        draft: The coordinator's parsed output.
        question: The visitor's question, used only by the keyword fallback.

    Returns:
        A check carrying either a dispatchable decision or the reasons it could
        not be repaired.
    """
    rules: list[str] = []
    chosen = list(draft.chosen_specialists)

    # Duplicates first: deduplicating a three-item list may already leave two,
    # in which case nothing needs trimming.
    deduped: list[SpecialistId] = []
    for specialist_id in chosen:
        if specialist_id not in deduped:
            deduped.append(specialist_id)
    if len(deduped) != len(chosen):
        rules.append(RULE_DEDUPLICATED)
    chosen = deduped

    if len(chosen) > SPECIALISTS_PER_RUN:
        chosen = chosen[:SPECIALISTS_PER_RUN]
        rules.append(RULE_TRIMMED_EXTRA)

    while len(chosen) < SPECIALISTS_PER_RUN:
        chosen.append(fallback_partner(question, exclude=frozenset(chosen)))
        rules.append(RULE_FILLED_MISSING)

    # Every id is a roster member by construction: the schema's enum makes any
    # other value unrepresentable. Asserted rather than assumed, because that
    # guarantee is the app's structural defence against a question naming a
    # specialist that does not exist.
    off_roster = [
        specialist_id for specialist_id in chosen if find(specialist_id.value) is None
    ]
    if off_roster:  # pragma: no cover - unreachable while the enum matches the roster
        return DelegationCheck(
            decision=None,
            rules_fired=rules,
            errors=[f"Not on the roster: {', '.join(sorted(off_roster))}"],
        )

    briefs: list[Brief] = []
    for specialist_id in chosen:
        existing = _brief_for(specialist_id, draft.briefs)
        if existing is None or len(existing.instruction.strip()) < MIN_BRIEF_CHARS:
            briefs.append(_default_brief(specialist_id, question))
            if RULE_REBUILT_BRIEFS not in rules:
                rules.append(RULE_REBUILT_BRIEFS)
        else:
            briefs.append(existing)

    briefs, overlap, appended = enforce_distinctness(briefs)
    if appended:
        rules.append(RULE_APPENDED_EXCLUSIONS)

    decision = DelegationDecision(
        chosen_specialists=chosen,
        rationale=draft.rationale.strip() or _default_rationale(chosen),
        briefs=briefs,
        fit_quality=draft.fit_quality,
    )
    return DelegationCheck(decision=decision, rules_fired=rules, jaccard=overlap)


def enforce_distinctness(briefs: list[Brief]) -> tuple[list[Brief], float, bool]:
    """Append angle-exclusion clauses when two briefs overlap too much.

    The capability's mitigation for near-duplicate briefs, and it is
    deliberately *additive*: the model's own wording is kept and the boundary is
    added to it, so a repaired brief still says whatever was useful in the
    original.

    Args:
        briefs: Exactly two briefs.

    Returns:
        The briefs (possibly extended), their overlap score, and whether the
        clauses were appended.
    """
    if len(briefs) != SPECIALISTS_PER_RUN:  # pragma: no cover - caller guarantees two
        return briefs, 0.0, False

    overlap = jaccard(briefs[0].instruction, briefs[1].instruction)
    if overlap < JACCARD_THRESHOLD:
        return briefs, overlap, False

    extended: list[Brief] = []
    for brief in briefs:
        entry = find(brief.specialist_id.value)
        clause = entry.angle_exclusion if entry else ""
        instruction = brief.instruction.rstrip()
        if clause and clause not in instruction:
            instruction = f"{instruction} {clause}"
        extended.append(
            Brief(specialist_id=brief.specialist_id, instruction=instruction)
        )

    return extended, overlap, True


def _default_rationale(chosen: list[SpecialistId]) -> str:
    """Build a rationale when the model returned none.

    Args:
        chosen: The two selected ids.

    Returns:
        A plain statement of the pairing. Deliberately flat: inventing a
        persuasive reason the coordinator never gave would be putting words in
        its mouth.
    """
    names = [find(specialist_id.value) for specialist_id in chosen]
    labels = [entry.display_name if entry else "a specialist" for entry in names]
    return (
        f"Paired {labels[0]} with {labels[1]}. The coordinator did not give a "
        "rationale for this pairing."
    )


def is_weak_fit(decision: DelegationDecision) -> bool:
    """Whether the coordinator judged this pairing a stretch.

    Args:
        decision: The validated decision.

    Returns:
        True when the fit was reported as weak.
    """
    return decision.fit_quality is FitQuality.WEAK


# --------------------------------------------------------------------------
# The fan-in checks
# --------------------------------------------------------------------------

#: Longest run of tokens the merged answer may share verbatim with a specialist
#: answer before the run is flagged. From the capability's own "no verbatim run
#: of >30 contiguous tokens copied from either specialist answer".
#:
#: Flagged in telemetry, **not blocked**. The capability says so, and it is the
#: right call: a merge that quotes 31 tokens is worse than one that does not,
#: but it is still an answer, and refusing to show it would spend the whole run
#: to display an error about writing style.
MAX_VERBATIM_RUN_TOKENS = 30

#: Trigram containment at or above which a quoted claim counts as genuinely
#: drawn from its source answer. From the capability's own 0.6.
CLAIM_TRACEABILITY_THRESHOLD = 0.6

#: Overlap between the note's summary and the merged answer above which the
#: note is judged to be restating rather than describing. Flagged, not blocked.
NOTE_ECHO_THRESHOLD = 0.5

#: Filler that says nothing about two specific answers. Drawn from the
#: capability's second failure mode, which rates vacuous boilerplate a
#: high-likelihood outcome for exactly the mid-tier free models this runs on.
BANNED_SUMMARY_PHRASES: tuple[str, ...] = (
    "complementary perspectives",
    "broadly agree",
    "both provide valuable",
)


def token_sequence(text: str) -> list[str]:
    """Reduce text to an ordered list of lowercase word tokens.

    The ordered counterpart of `tokenise()`. Order is the whole point here:
    copying is a claim about a *sequence*, and a set cannot express it.

    Args:
        text: The text to tokenise.

    Returns:
        Tokens in the order they appear, repeats included.
    """
    return _TOKEN.findall(text.lower())


def longest_verbatim_run(merged: str, source: str) -> int:
    """Length of the longest token run the merged answer copied from a source.

    Args:
        merged: The merged answer.
        source: One specialist's answer.

    Returns:
        The number of contiguous tokens in the longest shared run, or 0 if
        nothing is shared. A rolling comparison rather than a full suffix
        structure: both texts are a few thousand tokens at most, and a clear
        implementation is worth more here than an asymptotic one.
    """
    a, b = token_sequence(merged), token_sequence(source)
    if not a or not b:
        return 0

    # Standard longest-common-substring DP, kept to one row of state.
    previous = [0] * (len(b) + 1)
    best = 0
    for token in a:
        current = [0] * (len(b) + 1)
        for j, other in enumerate(b, start=1):
            if token == other:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def verbatim_run_flag(merged: str, answers: list[str]) -> int:
    """The worst verbatim run between the merged answer and any specialist.

    Args:
        merged: The merged answer.
        answers: Every specialist answer that fed the merge.

    Returns:
        The longest run found, in tokens. Compare against
        `MAX_VERBATIM_RUN_TOKENS` to decide whether to flag the run.
    """
    return max((longest_verbatim_run(merged, answer) for answer in answers), default=0)


def trigrams(text: str) -> set[tuple[str, str, str]]:
    """Word trigrams of a text.

    Args:
        text: The text.

    Returns:
        The distinct trigrams. A text of fewer than three tokens has none, which
        is why `trigram_containment` treats a short quote separately rather than
        scoring it 0.0 and dropping a legitimate three-word claim.
    """
    tokens = token_sequence(text)
    return {(tokens[i], tokens[i + 1], tokens[i + 2]) for i in range(len(tokens) - 2)}


def trigram_containment(quote: str, source: str) -> float:
    """How much of a quote's trigrams appear in the source it is attributed to.

    Containment rather than similarity: a two-sentence quote lifted from a
    two-thousand-word answer should score 1.0, and Jaccard would score it near
    zero because the union is dominated by the source.

    Args:
        quote: The claim as quoted.
        source: The answer it is attributed to.

    Returns:
        The fraction of the quote's trigrams found in the source, 0.0 to 1.0.
        A quote too short to have trigrams falls back to substring containment,
        so a genuine short claim is not dropped for being short.
    """
    quote_grams = trigrams(quote)
    if not quote_grams:
        stripped = " ".join(token_sequence(quote))
        if not stripped:
            return 0.0
        return 1.0 if stripped in " ".join(token_sequence(source)) else 0.0

    return len(quote_grams & trigrams(source)) / len(quote_grams)


def traceable_contradictions(
    contradictions: list[Contradiction], answers: dict[SpecialistId, str]
) -> tuple[list[Contradiction], int]:
    """Keep only contradictions whose quotes really came from the named answers.

    The deterministic answer to the capability's highest-rated failure: a model
    inventing a conflict to look insightful when the two specialists were simply
    briefed onto different sub-topics. A fabricated contradiction has to quote
    something, and an invented quotation does not appear in the source -- so the
    check is a lookup rather than a judgement.

    An item is dropped when either side is unattributed, when the two sides name
    the same specialist, when a named specialist did not run, or when either
    quote falls below `CLAIM_TRACEABILITY_THRESHOLD` against its own source.

    Args:
        contradictions: The contradictions as reported.
        answers: The answer text each specialist actually produced.

    Returns:
        The surviving contradictions and how many were dropped.
    """
    kept: list[Contradiction] = []
    for item in contradictions:
        left, right = item.specialist_a, item.specialist_b
        if left is None or right is None or left == right:
            continue
        if left not in answers or right not in answers:
            # Attribution to a roster member that did not run. The enum permits
            # all four ids; only the run knows which two are legal.
            continue
        if (
            trigram_containment(item.claim_a, answers[left])
            < CLAIM_TRACEABILITY_THRESHOLD
        ):
            continue
        if (
            trigram_containment(item.claim_b, answers[right])
            < CLAIM_TRACEABILITY_THRESHOLD
        ):
            continue
        kept.append(item)

    return kept, len(contradictions) - len(kept)


def banned_phrase_hits(summary: str) -> list[str]:
    """Filler phrases found in the note's summary.

    Args:
        summary: The summary as written.

    Returns:
        The banned phrases present, in the order they are listed. A hit is
        grounds for one regeneration at a lower temperature -- not for
        rejecting the run, since a bland summary beside a good merged answer is
        still worth showing.
    """
    lowered = summary.lower()
    return [phrase for phrase in BANNED_SUMMARY_PHRASES if phrase in lowered]


def note_echoes_merge(summary: str, merged: str) -> float:
    """How much the summary restates the merged answer rather than describing it.

    Args:
        summary: The note's summary.
        merged: The merged answer.

    Returns:
        The fraction of the summary's trigrams that also appear in the merged
        answer. Above `NOTE_ECHO_THRESHOLD` the panel is redundant with the
        answer beside it; flagged in telemetry rather than blocked, because a
        redundant note is a weaker demo, not a broken one.
    """
    return trigram_containment(summary, merged)
