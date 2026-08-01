# Built with Spec4 AI - https://spec4.ai
"""The fan-in: one closing coordinator turn that produces the merged answer.

## One provider request, and the disagreement note rides on it

The note is **fields on this response**, not a call of its own. That is the
whole reason the sub-feature exists without changing the run's arithmetic: the
merge already has to work out how the two answers relate in order to integrate
them, so asking for that relationship as structured output costs nothing. A
second call would make the run four visitor-facing calls to say something the
merge had already decided. `MergedAnswer` declares `disagreement_note` first so
the model settles the relationship *before* writing the synthesis -- a merge
written first tends to smooth a genuine conflict away, and a note written
afterwards then describes the smoothed version rather than the answers.

## "The same coordinator session" is not literally reachable here, and why

The phase asks for the synthesis as a closing turn on the coordinator agent
session opened in Phase 3. It cannot be: the human-in-the-loop gate splits the
run across **two HTTP requests**, and nothing persists a message history between
them -- `/run` returns the delegation and closes; `/dispatch` arrives later,
possibly at a different process. Threading a session through would mean either
shipping the coordinator's raw message history to the browser and trusting it
back, or building the run store this app deliberately does not have.

What that instruction is protecting is preserved exactly: the synthesis is a
**coordinator** turn (same persona lineage, same prompt directory, given the
question, its own rationale, and both answers), and it is the run's fourth and
final provider request. The invariant is about the call count and who is
speaking, and both hold.

## Checks are deterministic, and only one of them can change what is shown

Four run over the response. Three -- the verbatim-run flag, the note/merge echo
score, and the banned-phrase lint -- report into telemetry without altering the
output, because a merge that quotes too freely or a summary that reads as filler
is a weaker demonstration rather than a broken one, and spending the run to
display an error about writing style would be worse than showing it.

The fourth, claim traceability, **does** drop items, because a fabricated
contradiction is not a quality problem: it is the app telling a visitor two
specialists disagreed when they did not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import structlog
from pydantic_ai.settings import ModelSettings

from backend.app.orchestrated import validator
from backend.app.orchestrated.roster import find as find_specialist
from backend.app.orchestrated.runtime import RunBudget, run_agent_step
from backend.app.orchestrated.schemas import (
    ComparisonNote,
    DelegationDecision,
    MergedAnswer,
    SpecialistId,
    SubagentResult,
)
from backend.app.services.agent_runtime import AgentLaneError
from backend.app.services.prompt_loader import load_prompt
from backend.app.services.untrusted import untrusted_block

logger = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent / "prompts"

MERGE_PROMPT_VERSION = "merge_v1"

#: Sampling temperature for the synthesis turn, from the capability's own
#: `structured_outputs.temperature`. The retry drops to 0.
MERGE_TEMPERATURE: Final[float] = 0.3
RETRY_TEMPERATURE: Final[float] = 0.0

#: Caps applied after the response arrives rather than in the schema, on the
#: same reasoning as `SpecialistAnswer`: this is the run's last permitted
#: provider request, so a bound that made PydanticAI re-prompt would have
#: nothing left to re-prompt with.
MAX_NOTE_ITEMS: Final[int] = 3
MAX_SUMMARY_WORDS: Final[int] = 60

#: Shown in place of the note when the synthesis could not be parsed. The
#: capability's own wording.
FALLBACK_NOTE_COPY: Final[str] = "Comparison unavailable for this run."

#: Shown when only one specialist answered. Fixed application copy, never the
#: model's -- a prompt asked to handle this branch will occasionally write a
#: two-sided comparison from one answer.
DEGRADED_NOTE_COPY: Final[str] = (
    "Only one specialist returned an answer, so there was nothing to compare."
)

_USER_TEMPLATE = """{question_block}

Why you paired these two specialists:
{rationale}

{degraded_notice}{answer_blocks}"""

#: Prepended when one specialist failed. The prompt is written for two answers,
#: so a run that has one must say so -- otherwise the model is being asked to
#: compare something that is not there, and a live run showed it responding by
#: returning nothing at all. The application still overrides the note fields
#: afterwards; this is about getting a usable *answer* out of the turn.
_DEGRADED_NOTICE = (
    "NOTE: only one specialist answered this time. There is nothing to compare, "
    "so do not write a comparison. Write the best single answer you can from the "
    "one below, and leave every list in the note empty.\n\n"
)


def _answer_blocks(results: list[SubagentResult]) -> str:
    """Render each usable specialist answer as a delimited untrusted block.

    A specialist answer is model output built partly from visitor text, so it
    reaches the coordinator as data rather than as prose in the prompt. The
    display name travels with it so the note can name specialists in the
    visitor's own vocabulary.

    Args:
        results: The settled specialist results.

    Returns:
        One block per usable answer, separated by blank lines.
    """
    blocks = []
    for result in results:
        if not result.ok:
            continue
        entry = find_specialist(result.specialist_id.value)
        label = entry.display_name if entry else result.specialist_id.value
        blocks.append(
            untrusted_block(
                f"answer from {label} (id: {result.specialist_id.value})",
                result.answer,
            )
        )
    return "\n\n".join(blocks)


def trim_note(note: ComparisonNote) -> ComparisonNote:
    """Bound the note's lists and summary to what the capability specifies.

    Truncation, never padding -- there is nothing honest to invent an agreement
    from.

    Args:
        note: The note as returned.

    Returns:
        A note with at most `MAX_NOTE_ITEMS` per list and a summary of at most
        `MAX_SUMMARY_WORDS` words.
    """
    words = note.summary.split()
    summary = (
        note.summary
        if len(words) <= MAX_SUMMARY_WORDS
        else " ".join(words[:MAX_SUMMARY_WORDS]) + "…"
    )
    return ComparisonNote(
        summary=summary,
        agreements=[item for item in note.agreements if item.strip()][:MAX_NOTE_ITEMS],
        complements=[item for item in note.complements if item.strip()][
            :MAX_NOTE_ITEMS
        ],
        contradictions=note.contradictions[:MAX_NOTE_ITEMS],
        comparable=note.comparable,
    )


def apply_degraded_mode(
    answer: MergedAnswer, survivors: list[SubagentResult]
) -> MergedAnswer:
    """Override the note when only one specialist answered.

    An **application-layer short-circuit**, not a prompt instruction. The
    capability rates "degraded run produces a two-sided note despite only one
    answer existing" a real failure, and the reason is that a model given one
    answer and asked about a comparison will sometimes produce one anyway. So
    every list field the model returned is discarded rather than inspected, and
    the summary is fixed copy.

    Args:
        answer: The synthesis response.
        survivors: The specialist results that produced an answer.

    Returns:
        The answer unchanged when both specialists ran, or with a forced
        incomparable note when only one did.
    """
    if len(survivors) > 1:
        return answer

    return MergedAnswer(
        disagreement_note=ComparisonNote(
            summary=DEGRADED_NOTE_COPY,
            agreements=[],
            complements=[],
            contradictions=[],
            comparable=False,
        ),
        text=answer.text,
        sources_used=[result.specialist_id for result in survivors],
    )


def fallback_answer(text: str, survivors: list[SubagentResult]) -> MergedAnswer:
    """Build the answer shown when the synthesis could not be parsed.

    The merged text still reaches the visitor; only the note panel is replaced.
    Failing the whole run here would throw away three provider requests' worth
    of work over a malformed final field.

    Args:
        text: Whatever merged text is available, possibly empty.
        survivors: The specialists that contributed.

    Returns:
        The answer with the capability's fallback note copy.
    """
    return MergedAnswer(
        disagreement_note=ComparisonNote(summary=FALLBACK_NOTE_COPY, comparable=False),
        text=text,
        sources_used=[result.specialist_id for result in survivors],
    )


def check_merge(
    answer: MergedAnswer, results: list[SubagentResult]
) -> tuple[MergedAnswer, dict[str, object]]:
    """Run the deterministic fan-in checks and return the cleaned answer.

    Args:
        answer: The synthesis response, already trimmed.
        results: The specialist results the merge drew on.

    Returns:
        The answer with untraceable contradictions removed, and the telemetry
        those checks produced.
    """
    answers: dict[SpecialistId, str] = {
        result.specialist_id: result.answer for result in results if result.ok
    }
    kept, dropped = validator.traceable_contradictions(
        answer.disagreement_note.contradictions, answers
    )
    verbatim = validator.verbatim_run_flag(answer.text, list(answers.values()))
    echo = validator.note_echoes_merge(answer.disagreement_note.summary, answer.text)
    banned = validator.banned_phrase_hits(answer.disagreement_note.summary)

    cleaned = answer.model_copy(
        update={
            "disagreement_note": answer.disagreement_note.model_copy(
                update={"contradictions": kept}
            ),
            # Attribution is what the run actually produced, not what the model
            # claimed to have used.
            "sources_used": [result.specialist_id for result in results if result.ok],
        }
    )
    telemetry: dict[str, object] = {
        "agreements": len(cleaned.disagreement_note.agreements),
        "complements": len(cleaned.disagreement_note.complements),
        "contradictions": len(kept),
        "contradictions_dropped": dropped,
        "comparable": cleaned.disagreement_note.comparable,
        "summary_words": len(cleaned.disagreement_note.summary.split()),
        "banned_phrase_hits": banned,
        "verbatim_run_tokens": verbatim,
        "verbatim_run_flagged": verbatim > validator.MAX_VERBATIM_RUN_TOKENS,
        "note_echo": round(echo, 3),
        "note_echo_flagged": echo > validator.NOTE_ECHO_THRESHOLD,
    }
    return cleaned, telemetry


async def synthesise(
    *,
    question: str,
    decision: DelegationDecision,
    results: list[SubagentResult],
    budget: RunBudget,
) -> tuple[MergedAnswer, dict[str, object]]:
    """Run the coordinator's closing turn and return the merged answer.

    Google-style docstring per project convention.

    Spends the run's fourth and final provider request. A lint hit or a parse
    failure buys **one** regeneration at temperature 0 -- but only if the budget
    has room, which at the shipped ceiling of four it does not, since delegation
    and both specialists have already spent three. The guard is real rather than
    decorative: a run whose specialist failed before issuing its request leaves
    slack, and a raised ceiling makes it routine.

    Args:
        question: The visitor's question.
        decision: The delegation, for its rationale.
        results: Both specialist results, settled.
        budget: The run's provider-request counter.

    Returns:
        The merged answer and the fan-in telemetry.

    Raises:
        AgentLaneError: If the first attempt fails and no retry is affordable.
            The caller reports this without discarding the specialist columns.
    """
    survivors = [result for result in results if result.ok]
    instructions = load_prompt(PROMPTS_DIR, MERGE_PROMPT_VERSION)
    user_prompt = _USER_TEMPLATE.format(
        question_block=untrusted_block("visitor question", question),
        rationale=decision.rationale,
        degraded_notice="" if len(survivors) > 1 else _DEGRADED_NOTICE,
        answer_blocks=_answer_blocks(results),
    )

    async def attempt(temperature: float) -> MergedAnswer:
        step = await run_agent_step(
            label="coordinator-synthesis",
            instructions=instructions,
            user_prompt=user_prompt,
            output_type=MergedAnswer,
            budget=budget,
            model_settings=ModelSettings(temperature=temperature),
        )
        return step.output

    retries = 0
    try:
        answer = await attempt(MERGE_TEMPERATURE)
    except AgentLaneError:
        # A parse or schema failure arrives as a lane error, the framework
        # having already walked the whole chain.
        if not _retry_affordable(budget):
            raise
        retries = 1
        logger.info("orchestrated_synthesis_retried", reason="parse_failure")
        answer = await attempt(RETRY_TEMPERATURE)

    if not answer.text.strip():
        # An empty merge validates -- every field on `MergedAnswer` has a
        # default, which is what buys the no-re-prompt guarantee -- so nothing
        # upstream rejects it. Showing it would end the run with a blank panel
        # under two filled columns, which reads as the app breaking rather than
        # the model returning nothing. Seen live on a degraded run.
        logger.warning("orchestrated_synthesis_returned_no_text", retries=retries)
        if retries == 0 and _retry_affordable(budget):
            retries = 1
            answer = await attempt(RETRY_TEMPERATURE)
        if not answer.text.strip():
            raise AgentLaneError(
                "coordinator-synthesis",
                "The synthesis turn returned no merged answer.",
            )

    if validator.banned_phrase_hits(answer.disagreement_note.summary) and retries == 0:
        # Exactly one regeneration, whatever triggered it: the parse retry and
        # the lint retry share this budget rather than each holding their own.
        if _retry_affordable(budget):
            retries = 1
            logger.info("orchestrated_synthesis_retried", reason="banned_phrase")
            try:
                answer = await attempt(RETRY_TEMPERATURE)
            except AgentLaneError:
                # The first answer is still usable; a bland summary is not
                # grounds for discarding a merge.
                logger.info(
                    "orchestrated_synthesis_retry_failed", reason="banned_phrase"
                )

    trimmed = trim_note(answer.disagreement_note)
    cleaned, telemetry = check_merge(
        answer.model_copy(update={"disagreement_note": trimmed}), results
    )
    cleaned = apply_degraded_mode(cleaned, survivors)
    telemetry["retries"] = retries
    telemetry["comparable"] = cleaned.disagreement_note.comparable
    return cleaned, telemetry


def _retry_affordable(budget: RunBudget) -> bool:
    """Whether a regeneration fits inside the run's ceiling.

    The parse-failure retry and the lint retry are guarded by the same check and
    share one budget, so they cannot compound into a run that exceeds four
    provider requests -- the compounding the phase's own risk assessment names.

    Args:
        budget: The run's counter.

    Returns:
        True only when at least one request remains.
    """
    return budget.remaining() > 0
