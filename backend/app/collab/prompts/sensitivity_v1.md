[Built with Spec4 AI](https://spec4.ai)

# Priority-Sensitivity Counterfactual — v1

Given the award that was made and the priority weighting that produced it, say
which supplier would likely have won under a different weighting, and which
single term dimension flipped the result.

Be concrete about the dimension. "It would have been closer" is not an answer;
"the warranty gap outweighs the price gap once warranty is weighted above 40"
is.

## The arithmetic is already done

The re-scoring was computed in code before you were asked, and you are given
the result. **Narrate it. Do not re-derive it, and do not disagree with it.**
Your `likely_winner` must match the computed outcome; a different answer is
rejected.

Use only the figures you are given. Do not compute new ones.

## Write it as a projection

This is the same recorded bids re-scored under different weights — not a
second negotiation. Only an actual re-run would settle it, because suppliers
asked for different priorities would have bid differently from the start.

So: "would likely have won", not "would have won". Avoid *definitely*,
*certainly*, *guaranteed*, *proves*. The panel is checked for these.

`too_close` is a legitimate answer. When the computed outcome says the two
offers do not separate, say so rather than picking one.

Required fields: `likely_winner`, `decisive_dimensions` (the terms that moved
it), `narration`, `confidence`, and `caveat` stating this is a projection from
the recorded bids rather than a re-run.
