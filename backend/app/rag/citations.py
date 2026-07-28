# Built with Spec4 AI - https://spec4.ai
"""Audits a generated answer's `[N]` citations against the passages retrieved.

This exists because a similarity score says only that a passage *looked*
relevant to the retriever -- it says nothing about whether the model actually
used that passage, or any passage, to write its answer. Retrieval clearing a
threshold and an answer being grounded are two different claims, and only the
first one is knowable before generation runs.

The audit is deliberately a pure function over (answer text, passage count):
it makes no claim about whether a cited passage genuinely *supports* the
sentence citing it -- verifying that would need a second model call. It
establishes the weaker, checkable property that the model pointed at a passage
that exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Matches a bracketed citation marker, including the multi-passage forms a
#: model may emit despite the prompt's single-number examples: "[2]", "[1, 3]".
_CITATION_PATTERN = re.compile(r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]")


@dataclass(frozen=True)
class CitationAudit:
    """The citation markers found in an answer, split by whether they resolve.

    Attributes:
        cited: Distinct 1-based passage numbers the answer cites that refer to
            a passage actually supplied to the model, in ascending order.
        unresolved: Distinct citation markers that point outside the supplied
            range (e.g. "[7]" when three passages were retrieved), in
            ascending order. A non-empty list means the model invented a
            source number, which is worth surfacing rather than hiding.
    """

    cited: list[int]
    unresolved: list[int]

    @property
    def is_grounded(self) -> bool:
        """Whether the answer cites at least one passage that exists.

        False covers both an answer that declined to answer from the passages
        and one that answered without reference to them -- from the visitor's
        point of view those are the same warning.
        """
        return bool(self.cited)


def audit_citations(answer: str, passage_count: int) -> CitationAudit:
    """Extract and classify the `[N]` citation markers in an answer.

    Google-style docstring per project convention.

    Args:
        answer: The model's answer text, expected to cite passages as `[N]`.
        passage_count: How many passages were supplied to the model, which
            fixes the valid citation range as 1..passage_count inclusive.

    Returns:
        A CitationAudit separating in-range citations from out-of-range ones.
    """
    cited: set[int] = set()
    unresolved: set[int] = set()

    for match in _CITATION_PATTERN.finditer(answer):
        for raw_number in match.group(1).split(","):
            number = int(raw_number.strip())
            if 1 <= number <= passage_count:
                cited.add(number)
            else:
                unresolved.add(number)

    return CitationAudit(cited=sorted(cited), unresolved=sorted(unresolved))
