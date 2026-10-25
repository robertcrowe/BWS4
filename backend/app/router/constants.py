# Built with Spec4 AI - https://spec4.ai
"""Named constants for the Router slice: route ids, cost order, thresholds.

Every value a visitor can see on the page -- the decision margin, the cost
order, the five-observation rule, the run limit -- is defined here once and
read from here everywhere, so the page, the decision rules and the histories
cannot disagree about a number.

The four route ids are spelled exactly as the stack spec spells them. They are
persisted (agreement and latency history rows carry them) and published (the
presets endpoint carries each preset's expected route), so they are part of
the wire and storage contract rather than display text.
"""

from __future__ import annotations

from typing import Final, Literal

#: The no-model expression evaluator. Cost rank 0: no model call at all.
DETERMINISTIC_EVALUATOR: Final = "deterministic_evaluator"
#: One call through the shared generation service. Cost rank 1.
SINGLE_CALL: Final = "single_call"
#: The RAG example's existing retriever plus its answer call. Cost rank 2.
RETRIEVAL: Final = "retrieval"
#: Shared Exa web search followed by one generation call. Cost rank 3, and the
#: "no router" baseline the cost strip compares every run against.
SEARCH_GENERATION: Final = "search_generation"

#: The closed set of route ids, for typing anything that carries one.
RouteId = Literal[
    "deterministic_evaluator",
    "single_call",
    "retrieval",
    "search_generation",
]

#: The fixed cost order, cheapest first. A low-confidence run dispatches to
#: whichever of its two torn routes appears earlier in this tuple. Defined in
#: code and printed on the page; never inferred from a model's output.
ROUTE_COST_ORDER: Final[tuple[RouteId, ...]] = (
    DETERMINISTIC_EVALUATOR,
    SINGLE_CALL,
    RETRIEVAL,
    SEARCH_GENERATION,
)

#: Display names for the four routes, used on the page and the decision card.
ROUTE_LABELS: Final[dict[RouteId, str]] = {
    DETERMINISTIC_EVALUATOR: "Deterministic evaluator",
    SINGLE_CALL: "Single call",
    RETRIEVAL: "RAG over the space dataset",
    SEARCH_GENERATION: "Search + generate",
}

#: A run is low-confidence when the top two of the four route scores differ by
#: no more than this.
#:
#: 0.15 is chosen because the scores are the model's uncalibrated self-report on
#: a 0-1 scale: small free models jitter by a few hundredths between identical
#: calls, so a margin much below 0.1 would let noise decide between two routes
#: the model rates as near-equal, while a margin much above 0.2 would flag
#: ordinary clear-but-not-certain decisions (0.7 against 0.5) as torn and send
#: too many runs down the tie-break path, hiding the router's actual choice. It
#: matches the value the design mock prints beside the route descriptions.
DECISION_MARGIN: Final[float] = 0.15

#: How many of the most recent search_generation runs the cost strip's
#: "typical" baseline time is the rolling median of. Wide enough that one slow
#: Exa response cannot move the median, narrow enough to track a provider whose
#: latency has genuinely changed. Consumed by the latency history (Phase 8).
LATENCY_MEDIAN_WINDOW_N: Final[int] = 50

#: Below this many observations a history cell shows counts only: no rate in
#: the agreement panel, and no typical time in the cost strip.
MIN_OBSERVATIONS: Final[int] = 5

#: Runs a visitor gets per visit, comparison re-runs included.
ROUTER_RUN_LIMIT: Final[int] = 5

#: Longest expression the deterministic evaluator will look at, in characters.
#: A real conversion or sum fits in a few dozen; the cap bounds tokenizer work
#: on hostile input before any parsing starts.
MAX_EXPRESSION_CHARS: Final[int] = 200

#: Deepest nesting the evaluator's recursive descent will enter, counting both
#: parentheses and chained unary signs. Bounds recursion on hostile input well
#: below Python's own limit.
MAX_NESTING_DEPTH: Final[int] = 8
