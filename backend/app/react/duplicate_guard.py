# Built with Spec4 AI - https://spec4.ai
"""The near-duplicate query guard: pure functions, no I/O of any kind.

The capability's highest-likelihood failure after "answers from memory" is the
loop *wandering* — reissuing near-identical queries until the budget is gone and
the run ends with nothing. A cap alone does not fix that: it bounds how long the
circling lasts, not whether it happens.

## Why this module opens no session, calls no model, and reaches no network

Every input arrives as an argument, including the candidate's embedding. That is
not fastidiousness — it is what makes the threshold *testable in both
directions*, which is the phase's named tuning risk. Set the threshold too low
and a genuine follow-up is blocked, which breaks multi-hop questions outright,
because hop two is by design closely related to hop one. Set it too high and
rephrased repeats sail through. Only a function with no hidden inputs can be
asserted against both cases cheaply enough that a mis-tuned value fails a test
instead of degrading the demonstration silently.

The caller embeds. `service.py` calls the shared in-process MiniLM service and
hands the vector in. That model spends local CPU and nobody's third-party quota,
which is precisely why every candidate can be checked rather than only the
suspicious ones.

## Two stages, because they catch different things

1. **Normalised exact match.** Lowercase, strip punctuation, drop stopwords.
   Catches "the tallest building in Tokyo" against "Tallest building in Tokyo?"
   for the price of a set comparison, and catches it with certainty.
2. **Cosine similarity** against the embeddings of queries already issued in
   this run, rejecting at or above the configured threshold. Catches the
   rewording that stage 1 cannot — "Tokyo's highest skyscraper" — and is the
   only stage with a tunable number in it.

## What the guard is scoped to

One run. `IssuedQueries` is created when a run starts and dropped when it ends,
and **nothing here is ever persisted**. A visitor's query text is not retained
past the run that produced it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, Literal

import numpy as np

#: Punctuation and whitespace normalisation for stage 1. Anything that is not a
#: letter, a digit or a space becomes a space, so "Tokyo's" and "Tokyos" and
#: "Tokyo s" all collapse together.
_NON_WORD = re.compile(r"[^a-z0-9\s]+")

#: Stopwords dropped before the exact-match comparison.
#:
#: Deliberately short and closed. A large linguistic stoplist would start
#: erasing words that carry the *hop* -- "current", "most", "recent" and "first"
#: are exactly the words that distinguish one query from another here, and none
#: of them appears below. What is here is the grammatical scaffolding two
#: phrasings of the same request differ by.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "s",
        "that",
        "the",
        "to",
        "was",
        "what",
        "which",
        "who",
        "with",
    }
)

#: Why a candidate was refused, or that it was not.
DuplicateReason = Literal["novel", "exact_match", "near_duplicate"]


@dataclass(frozen=True)
class DuplicateDecision:
    """The guard's verdict on one candidate query.

    Attributes:
        allowed: Whether the query may be issued. When False it must not reach
            Exa at all -- the whole point is that a refused query costs no
            search quota.
        reason: Which stage refused it, or `novel`.
        matched_index: 1-based index of the observation whose query this
            duplicates, or None when allowed. 1-based because it is the number
            the model sees in the transcript and the number the re-prompt note
            quotes back at it.
        similarity: The highest cosine similarity against any prior query, or
            None when no prior queries existed. Reported even when allowed, so
            an operator can see how close the guard came.
        note: The re-prompt to feed the model, or None when allowed.
    """

    allowed: bool
    reason: DuplicateReason
    matched_index: int | None = None
    similarity: float | None = None
    note: str | None = None


@dataclass
class IssuedQueries:
    """The queries one run has already issued, and their embeddings.

    In-process, per run, never persisted -- see the module docstring. Mutable
    because a run accumulates; it holds no handles and touches nothing outside
    itself, so it stays as testable as the functions around it.

    Attributes:
        queries: Each issued query, verbatim, in issue order.
        embeddings: One row per query, in the same order. Empty until the first
            query is remembered.
    """

    queries: list[str] = field(default_factory=list)
    embeddings: list[list[float]] = field(default_factory=list)

    def remember(self, query: str, embedding: list[float]) -> None:
        """Record a query that was actually issued.

        Called only for queries that reached Exa. A refused query is *not*
        remembered: it was never issued, so nothing should be measured against
        it, and remembering it would let one rejection poison the next cycle's
        comparison.

        Args:
            query: The query text, verbatim.
            embedding: Its vector, from the shared embedding service.
        """
        self.queries.append(query)
        self.embeddings.append(embedding)

    def matrix(self) -> np.ndarray:
        """Return the issued embeddings as one array for the cosine comparison.

        Returns:
            A `(n, dim)` float array, or an empty `(0, 0)` array when nothing
            has been issued yet.
        """
        if not self.embeddings:
            return np.empty((0, 0), dtype=np.float32)
        return np.asarray(self.embeddings, dtype=np.float32)

    def __len__(self) -> int:
        """Return how many queries have been issued in this run."""
        return len(self.queries)


def normalise(query: str) -> frozenset[str]:
    """Reduce a query to the content words two phrasings of it would share.

    Args:
        query: The raw query text.

    Returns:
        The lowercased, punctuation-stripped, stopword-free token set. A set
        rather than a list, so word order does not distinguish two queries that
        ask for the same thing.
    """
    cleaned = _NON_WORD.sub(" ", query.lower())
    return frozenset(
        token for token in cleaned.split() if token and token not in _STOPWORDS
    )


def _max_similarity(
    candidate_embedding: list[float], prior: np.ndarray
) -> tuple[float | None, int | None]:
    """Find the closest prior query by cosine similarity.

    The shared embedding service L2-normalises its output, so cosine similarity
    is a dot product and no renormalisation is needed here. Normalising again
    would be harmless but would hide a real defect if that ever stopped being
    true, so the assumption is stated rather than defended against.

    Args:
        candidate_embedding: The candidate's vector.
        prior: One row per already-issued query.

    Returns:
        The highest similarity and the 0-based row it came from, or
        `(None, None)` when there are no prior queries.
    """
    if prior.size == 0:
        return None, None

    scores = prior @ np.asarray(candidate_embedding, dtype=np.float32)
    best = int(np.argmax(scores))
    return float(scores[best]), best


def duplicate_note(matched_index: int, matched_query: str) -> str:
    """Build the re-prompt the model is given when its query is refused.

    Says three things, all of which the specification's mitigation names: that
    the query was already issued, *which* observation already covers it, and
    what to do instead. The last matters most -- a refusal with no alternative
    invites the model to rephrase again and spend the retry for nothing.

    Args:
        matched_index: The 1-based observation that already covers this ground.
        matched_query: The query that produced it, verbatim.

    Returns:
        The note to append to the next prompt.
    """
    return (
        f'That query was already issued as "{matched_query}" — observation '
        f"{matched_index} already covers it. Ask for something different, or "
        f"answer from the observations you have."
    )


def evaluate_query(
    candidate: str,
    candidate_embedding: list[float],
    issued: IssuedQueries,
    threshold: float,
) -> DuplicateDecision:
    """Decide whether a candidate query may be issued.

    Pure: every input is an argument and nothing is read from the environment,
    a database, a model or the network. Both stages run against the run's own
    already-issued queries only.

    Args:
        candidate: The query the model chose, verbatim.
        candidate_embedding: Its vector, from the shared embedding service.
        issued: What this run has already sent.
        threshold: Cosine similarity at or above which a candidate counts as a
            near-duplicate. Injected rather than read from settings so the
            tuning risk is testable from both directions.

    Returns:
        The verdict, carrying the re-prompt note when the query is refused.
    """
    if len(issued) == 0:
        return DuplicateDecision(allowed=True, reason="novel")

    # Stage 1: normalised exact match. Certain, and cheaper than the vectors.
    candidate_tokens = normalise(candidate)
    for position, prior_query in enumerate(issued.queries):
        if candidate_tokens and candidate_tokens == normalise(prior_query):
            index = position + 1
            return DuplicateDecision(
                allowed=False,
                reason="exact_match",
                matched_index=index,
                similarity=1.0,
                note=duplicate_note(index, prior_query),
            )

    # Stage 2: the rewording stage 1 cannot see.
    similarity, row = _max_similarity(candidate_embedding, issued.matrix())
    if similarity is not None and row is not None and similarity >= threshold:
        index = row + 1
        return DuplicateDecision(
            allowed=False,
            reason="near_duplicate",
            matched_index=index,
            similarity=similarity,
            note=duplicate_note(index, issued.queries[row]),
        )

    return DuplicateDecision(allowed=True, reason="novel", similarity=similarity)
