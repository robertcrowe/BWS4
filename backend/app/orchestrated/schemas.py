# Built with Spec4 AI - https://spec4.ai
"""Wire shapes for the orchestrated-subagents roster and curated presets.

The field names here are **camelCase on purpose**. These are the design
entities' own names and they cross the wire to a TypeScript client, so matching
the client's casing keeps one spelling from the roster module all the way to the
column heading. The trade is a deliberate exception to this codebase's
snake_case convention, confined to the boundary models and flagged for the
linter in `pyproject.toml` rather than suppressed line by line.

Nothing here is a model output. The roster is a closed set the coordinator must
choose from and the presets are pre-vetted questions -- both are configuration a
redeploy replaces, which is what lets curated content change without a schema
migration.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Specialist(BaseModel):
    """One member of the fixed roster, as the frontend receives it.

    Only the four presentational fields travel. The system-prompt fragment, the
    angle-exclusion clause and the keyword affinities stay server-side in
    `roster.py`: they are how the coordinator and the specialists are
    instructed, and publishing them would put the prompt that governs a
    specialist in the hands of anyone shaping a question for it.
    """

    id: str
    displayName: str  # noqa: N815 - design entity name, mirrored by the TS client
    scope: str
    color: str


class Question(BaseModel):
    """One curated preset question and the pairing it was chosen to produce.

    `expectedPairing` is a **human label**, not a prediction the app checks at
    runtime. It exists so an offline eval can ask whether the coordinator's
    choice matches what a person reading the question would expect -- which is
    the only way to tell a genuinely question-sensitive coordinator from one
    that returns the same pair every time.
    """

    id: str
    text: str
    expectedPairing: list[str]  # noqa: N815 - design entity name, mirrored by the TS client


class RosterResponse(BaseModel):
    """Body of GET /api/orchestrated/roster."""

    specialists: list[Specialist]
    presets: list[Question]


class SpecialistId(StrEnum):
    """The closed set of roster ids the coordinator may choose from.

    An enum rather than a string, because it is the one anti-injection control
    here that does not depend on the model cooperating: a question telling the
    coordinator to "use the Legal specialist" cannot produce one, since no such
    value exists in the schema the provider is constrained by. Prompt wording
    asks; a closed type makes it impossible.

    Kept in step with `roster.SPECIALIST_ROSTER_CONFIG` by a test rather than by
    an import, so the wire schema does not depend on module import order.
    """

    TECHNICAL = "technical"
    FINANCIAL = "financial"
    HISTORICAL = "historical"
    PRACTICAL = "practical"


class FitQuality(StrEnum):
    """How well the question maps onto the two specialists chosen.

    Two values, deliberately. The capability asks the coordinator to say when a
    pairing is a stretch, and a coarse honest signal is worth more than a
    five-point scale a mid-tier free model would apply inconsistently.
    """

    STRONG = "strong"
    WEAK = "weak"


class Brief(BaseModel):
    """One specialist's instruction for this question.

    Fields are the design entity's own: `specialist_id` and `instruction`.
    """

    specialist_id: SpecialistId
    instruction: str


class CoordinatorDraft(BaseModel):
    """What the coordinator model returns, before anything has been checked.

    **Deliberately permissive about cardinality**, and this is the load-bearing
    decision in this file. The validated shape below requires exactly two
    distinct specialists -- but if that constraint lived here, a model returning
    three would fail Pydantic validation *inside* PydanticAI, which would
    re-prompt and spend a second provider request. The whole repair path exists
    to avoid exactly that.

    So the draft parses almost anything with the right field names, and
    `validator.py` turns it into a `DelegationDecision` deterministically. The
    enum still applies: an off-roster id cannot be expressed at all.

    The field names match `DelegationDecision` so the JSON Schema the provider
    is constrained by uses the design entity's vocabulary.
    """

    chosen_specialists: list[SpecialistId] = Field(default_factory=list)
    rationale: str = ""
    briefs: list[Brief] = Field(default_factory=list)
    fit_quality: FitQuality = FitQuality.STRONG


class DelegationDecision(BaseModel):
    """The checked decision: who answers, why, and what each was asked.

    The design entity, with its four fields and no others. Constructed only by
    `validator.validate_and_repair()`, which is what makes the constraints below
    safe to assert -- by the time this is built, the cardinality has already
    been repaired rather than rejected.

    Attributes:
        chosen_specialists: Exactly two distinct roster ids.
        rationale: Why this pairing, in at most a couple of sentences.
        briefs: One brief per chosen specialist, in the same order.
        fit_quality: Whether the pairing is a good match or a best-effort one.
    """

    chosen_specialists: list[SpecialistId] = Field(min_length=2, max_length=2)
    rationale: str
    briefs: list[Brief] = Field(min_length=2, max_length=2)
    fit_quality: FitQuality


class SpecialistStatus(StrEnum):
    """How one specialist's branch ended.

    `TIMED_OUT` is separate from `FAILED` for the reason the fan-out helper
    keeps them separate: "still thinking when we stopped waiting" and "broke"
    suggest different things to a visitor, and only one of them is worth
    retrying.
    """

    OK = "ok"
    FAILED = "failed"
    TIMED_OUT = "timeout"


class SpecialistAnswer(BaseModel):
    """What a specialist model returns.

    **Permissive on purpose**, exactly like `CoordinatorDraft` above and for the
    same arithmetic. The specification asks for three to five key points; if
    that bound lived here, a model returning two would fail validation *inside*
    PydanticAI, which re-prompts and spends a provider request the run's
    four-request ceiling has no room for. So the bound is applied afterwards, in
    `specialists.py`, where trimming is free.

    Two fields, both authored by the model. Which specialist this is and whether
    it succeeded are **stamped by the server** onto `SubagentResult` below --
    asking a model to report its own id or status would be asking it to assert
    something nothing had checked, the defect this project has now fixed three
    times.
    """

    answer: str = ""
    key_points: list[str] = Field(default_factory=list)


class SubagentResult(BaseModel):
    """One specialist's contribution to a run, as the visitor and Phase 5 see it.

    The design entity's own field names. `answer` and `key_points` carry what
    the model wrote; `specialist_id`, `status` and `error` are server-stamped
    facts about the branch.

    Attributes:
        specialist_id: Which roster member this column is.
        status: Whether the branch produced an answer, broke, or ran out of time.
        answer: The specialist's markdown answer. Empty unless `status` is OK.
        key_points: Three to five standalone sentences, trimmed to that range
            server-side. Empty unless `status` is OK.
        error: A visitor-readable explanation. Present only when `status` is not
            OK, and never the underlying exception text -- a provider's error
            string is for the operator's logs, not for the screen.
    """

    specialist_id: SpecialistId
    status: SpecialistStatus
    answer: str = ""
    key_points: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True when this column has an answer to show."""
        return self.status is SpecialistStatus.OK


class Contradiction(BaseModel):
    """One place the two answers cannot both be acted on.

    The claims are quoted rather than paraphrased because that is what makes the
    item **checkable**: `validator.traceable_contradictions()` drops any
    contradiction whose quotes do not actually appear in the answer they are
    attributed to. Manufactured disagreement is the top-rated failure mode for
    this step, and a paraphrase would make it undetectable.

    Attributes:
        claim_a: Near-verbatim wording from `specialist_a`'s answer.
        claim_b: Near-verbatim wording from `specialist_b`'s answer.
        specialist_a: Who made the first claim.
        specialist_b: Who made the second.
    """

    claim_a: str = ""
    claim_b: str = ""
    specialist_a: SpecialistId | None = None
    specialist_b: SpecialistId | None = None


class ComparisonNote(BaseModel):
    """How the two independent answers relate to each other.

    Rides on the synthesis response rather than costing a call of its own --
    which is the entire reason the sub-feature preserves the run's three-call
    invariant. A separate model call for this would be a fourth visitor-facing
    call to say something the merge already had to work out.

    Attributes:
        summary: One to three sentences on the *relationship*, not the content.
        agreements: Specific claims both answers land on.
        complements: What each supplied that the other did not.
        contradictions: Genuine conflicts, each with quotable evidence.
        comparable: False when only one specialist answered. Set by the
            application, never taken from the model -- see
            `merge.apply_degraded_mode()`.
    """

    summary: str = ""
    agreements: list[str] = Field(default_factory=list)
    complements: list[str] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    comparable: bool = True


class MergedAnswer(BaseModel):
    """The run's final output: one answer, plus how it was arrived at.

    **`disagreement_note` is declared first on purpose.** Structured decoding
    emits fields in declaration order, so the model has to characterise the
    relationship between the two answers *before* it writes the synthesis. The
    specification names this as the mitigation for a real failure -- a merge
    written first tends to smooth a genuine conflict away, and a note written
    afterwards then describes the smoothed version rather than the answers.

    Permissive on cardinality, like `CoordinatorDraft` and `SpecialistAnswer`
    before it, and for the same arithmetic: this call is the run's *last*
    permitted provider request, so a bound that made PydanticAI re-prompt would
    have nothing to re-prompt with. Trimming happens in `merge.py`.

    Attributes:
        disagreement_note: The comparison, decoded first.
        text: The merged answer, in markdown.
        sources_used: Which specialists it drew on.
    """

    disagreement_note: ComparisonNote = Field(default_factory=ComparisonNote)
    text: str = ""
    sources_used: list[SpecialistId] = Field(default_factory=list)
