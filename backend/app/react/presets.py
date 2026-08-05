# Built with Spec4 AI - https://spec4.ai
"""The five curated multi-hop preset questions, as typed Python literals.

Following `collab/scenarios.py` and `orchestrated/roster.py` rather than a YAML
or JSON fixture: mypy checks these nested structures, a redeploy replaces them
with no migration, and there is no serialisation dependency to add.

## THIS CATALOGUE STORES QUESTIONS AND HOP METADATA ONLY. IT NEVER STORES AN
## ANSWER TO ANY PRESET, AND NOTHING MAY ADD ONE.

That is not tidiness, it is the maintenance story. Three of these five turn on
facts that change -- the most recent Women's World Cup winner and that team's
current coach, the most recent Nobel laureate in Literature, the current
employer of a named researcher, the tallest building in a given city. A stored
answer would be stale within a year and would then be *wrong on screen* while
looking authoritative. Keeping questions only means every answer refreshes from
live search on every run, and maintenance is an occasional read-through asking
whether each question still parses sensibly -- not a fact-checking pass.

It is also what keeps the demonstration honest. The app's headline claim is that
the trace shows real observations doing real work; a catalogue holding the
answers is a catalogue something could quietly answer from.
`test_react_presets.py` asserts no field named for an answer exists on either
dataclass, and that the endpoint's payload carries none.

## What the hop metadata is for, and what it is not

`expected_hops` describes the *shape* of the chain -- what each hop must
establish, whether it can be established from parametric knowledge, and why.
It is maintainer metadata: it never reaches a model, never reaches the browser
beyond the hop count, and is never compared against what a run produced. It
exists so the preset set can be argued about, and so Phase 6's hop-source
annotation has something to be checked against by a human reading the file.

## Why these five

Every preset must chain at least two facts where the later query cannot be
written until the earlier result is read, and must contain at least one hop that
defeats memorised knowledge -- either time-variable ("current", "most recent")
or genuinely obscure. p1-p3 are the guaranteed fully-observed demonstrations:
every hop in them needs an observation. p4 and p5 are the approachable entry
points, and their first hop is *expected* to come from the model's own
knowledge. That is correct ReAct behaviour rather than a defect -- an agent that
searches for what it already knows is wasting its budget -- and the trace
showing the model choosing where observation is genuinely required is itself
teaching content. The overview says so, and Phase 6's annotation labels it hop
by hop.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

#: Bumped by adding a new catalogue alongside this one, never by editing a
#: shipped entry in place -- the same convention as `rag/prompts/answer_vN.md`
#: and `single_call/presets.py`. A run's trace records which questions it was
#: offered by recording the preset id, and an id whose wording changed
#: underneath it would make past runs unreproducible.
PRESET_SET_VERSION: Final[str] = "v1"

#: What `react_runs.question_origin` carries when the visitor wrote the
#: question themselves. Never the question text.
CUSTOM_ORIGIN: Final[str] = "custom"


class HopSource(StrEnum):
    """Why a hop does or does not defeat the model's memorised knowledge.

    The distinction the preset set is curated around. `TIME_VARIABLE` and
    `OBSCURE` are the two ways a hop forces a search; `PARAMETRIC` marks a hop
    the model is expected to answer from training, which is permitted only
    where a later hop in the same question forces observation anyway.
    """

    #: "current" / "most recent" -- the answer moves, so training data is stale.
    TIME_VARIABLE = "time_variable"
    #: Stable, but too specific to be reliably memorised.
    OBSCURE = "obscure"
    #: Well-known and stable. The model may state it from its own knowledge.
    PARAMETRIC = "parametric"


@dataclass(frozen=True)
class PresetHop:
    """One link in a preset's chain of facts.

    Describes what the hop must *establish*, never what it establishes to --
    see the module docstring. `fact` is a noun phrase naming the unknown, and a
    reviewer should be able to read it without learning the answer.

    Attributes:
        index: 1-based position in the chain. Hop `n + 1`'s query cannot be
            written until hop `n`'s result has been read.
        fact: What this hop must establish, phrased as the unknown itself.
        requires_observation: True when a correct run has to search for it.
            False marks a hop the model may legitimately state from memory.
        source: Why this hop does or does not defeat memorised knowledge.
        reason: One sentence of maintainer rationale for `source`.
    """

    index: int
    fact: str
    requires_observation: bool
    source: HopSource
    reason: str


@dataclass(frozen=True)
class Preset:
    """One curated multi-hop question, and the maintainer notes behind it.

    Attributes:
        id: Stable identifier, `p1`..`p5`. Written to
            `react_runs.question_origin`, so it must not be reused for
            different wording.
        label: Short chip text for the selector. Deliberately does not leak a
            hop's answer -- naming the director of *Spirited Away* in p5's chip
            would resolve its first hop before the run began.
        question: The question put to the model, verbatim.
        expected_hops: The chain, in order.
        guaranteed_fully_observed: True for the three presets curated so that
            every hop needs an observation. Maintainer metadata; published to
            the client so the selector can say which presets guarantee a fully
            observed demonstration.
    """

    id: str
    label: str
    question: str
    expected_hops: tuple[PresetHop, ...]
    guaranteed_fully_observed: bool

    @property
    def hop_count(self) -> int:
        """Return how many facts this question chains.

        Returns:
            The number of hops in the chain.
        """
        return len(self.expected_hops)


PRESETS: Final[tuple[Preset, ...]] = (
    Preset(
        id="p1",
        label="Highest mountain in the newest UN member",
        question=(
            "How tall is the highest mountain in the country that most "
            "recently joined the United Nations?"
        ),
        expected_hops=(
            PresetHop(
                index=1,
                fact="which country most recently joined the United Nations",
                requires_observation=True,
                source=HopSource.OBSCURE,
                reason=(
                    "Stable for years at a time, but not front-of-mind: a model "
                    "asked to recall it tends to name a plausible recent "
                    "accession rather than the actual latest one."
                ),
            ),
            PresetHop(
                index=2,
                fact="that country's highest mountain, and its height",
                requires_observation=True,
                source=HopSource.OBSCURE,
                reason=(
                    "Genuinely obscure -- the answer depends entirely on hop 1, "
                    "and the elevation of a small country's high point is not "
                    "reliably memorised."
                ),
            ),
        ),
        guaranteed_fully_observed=True,
    ),
    Preset(
        id="p2",
        label="Coach of the reigning Women's World Cup winners",
        question=(
            "Who is the current head coach of the national team that won the "
            "most recent FIFA Women's World Cup?"
        ),
        expected_hops=(
            PresetHop(
                index=1,
                fact="which national team won the most recent Women's World Cup",
                requires_observation=True,
                source=HopSource.TIME_VARIABLE,
                reason=(
                    "'Most recent' moves every four years, so any answer from "
                    "training data is one tournament behind sooner or later."
                ),
            ),
            PresetHop(
                index=2,
                fact="that team's current head coach",
                requires_observation=True,
                source=HopSource.TIME_VARIABLE,
                reason=(
                    "Volatile: national-team coaches change between "
                    "tournaments and often within months of one."
                ),
            ),
        ),
        guaranteed_fully_observed=True,
    ),
    Preset(
        id="p3",
        label="Population of a Nobel laureate's birthplace",
        question=(
            "What is the population of the birthplace of the most recent "
            "Nobel laureate in Literature?"
        ),
        expected_hops=(
            PresetHop(
                index=1,
                fact="who most recently won the Nobel Prize in Literature",
                requires_observation=True,
                source=HopSource.TIME_VARIABLE,
                reason=(
                    "Refreshes every October. Literature rather than Peace "
                    "because the Literature laureate is always an individual, "
                    "so a birthplace always exists -- the Peace prize is "
                    "regularly awarded to an organisation, which would leave "
                    "hop 2 with nothing to resolve."
                ),
            ),
            PresetHop(
                index=2,
                fact="that laureate's birthplace",
                requires_observation=True,
                source=HopSource.OBSCURE,
                reason=(
                    "Unknowable before hop 1 resolves, and often a small town "
                    "rather than a capital."
                ),
            ),
            PresetHop(
                index=3,
                fact="the population of that place",
                requires_observation=True,
                source=HopSource.TIME_VARIABLE,
                reason=(
                    "Census figures move, and the place is not known until hop "
                    "2 resolves. The one three-hop preset."
                ),
            ),
        ),
        guaranteed_fully_observed=True,
    ),
    Preset(
        id="p4",
        label="Current employer of the Transformer paper's lead author",
        question=(
            "Which company currently employs the lead author of the paper that "
            "introduced the Transformer architecture?"
        ),
        expected_hops=(
            PresetHop(
                index=1,
                fact="the paper that introduced the Transformer, and its lead author",
                requires_observation=False,
                source=HopSource.PARAMETRIC,
                reason=(
                    "Famous enough that a model will usually state it straight "
                    "from its own knowledge. Permitted here because hop 2 "
                    "forces observation regardless, and the trace showing the "
                    "model spending its searches where they are needed is "
                    "itself the teaching content."
                ),
            ),
            PresetHop(
                index=2,
                fact="that author's current employer",
                requires_observation=True,
                source=HopSource.TIME_VARIABLE,
                reason=(
                    "Has changed repeatedly and recently, which reliably "
                    "defeats memory even where hop 1 does not."
                ),
            ),
        ),
        guaranteed_fully_observed=False,
    ),
    Preset(
        id="p5",
        label="Tallest building in a famous director's birthplace",
        question=(
            "What is the tallest building in the birthplace of the director of "
            "Spirited Away?"
        ),
        expected_hops=(
            PresetHop(
                index=1,
                fact="the director of Spirited Away, and their birthplace",
                requires_observation=False,
                source=HopSource.PARAMETRIC,
                reason=(
                    "The approachable pop-culture entry point: a model will "
                    "usually know the director, though the birthplace is less "
                    "certain than the name."
                ),
            ),
            PresetHop(
                index=2,
                fact="the tallest building in that city",
                requires_observation=True,
                source=HopSource.TIME_VARIABLE,
                reason=(
                    "Tallest-building answers change as construction "
                    "completes, so this hop needs a live observation."
                ),
            ),
        ),
        guaranteed_fully_observed=False,
    ),
)

#: Preset ids, for cheap membership checks at the request boundary.
PRESET_IDS: Final[frozenset[str]] = frozenset(preset.id for preset in PRESETS)

#: The canonical question strings, byte-for-byte. The shared moderation gate
#: recognises curated text by matching against the app's own canonical strings
#: rather than by accepting an id -- a preset id is a claim, and a gate that
#: trusted one could be skipped by attaching an id to arbitrary text. Consumed
#: from Phase 3, declared here beside the questions it mirrors.
PRESET_QUESTIONS: Final[frozenset[str]] = frozenset(
    preset.question for preset in PRESETS
)


def get_preset(preset_id: str) -> Preset | None:
    """Look up one preset by id.

    Args:
        preset_id: The id from the request, unvalidated.

    Returns:
        The preset, or None when no preset carries that id.
    """
    for preset in PRESETS:
        if preset.id == preset_id:
            return preset
    return None
