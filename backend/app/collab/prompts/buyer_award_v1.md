[Built with Spec4 AI](https://spec4.ai)

# Buyer — Award — v1

Both suppliers have given their best and final offers. Choose one and justify
the choice against the priorities you were given.

## Score first, then explain

Emit `per_priority_scoring` **before** you write anything else. For each
supplier and each priority, give a score out of 100 and one line saying why.
Then declare the winner, and only then write the rationale.

Use these exact four names in the `priority` field, and no others:

- `price`
- `delivery`
- `quantity`
- `warranty`

Not "unit price", not "delivery lead time" — the four words above, exactly.
Your declared winner is reconciled against these scores automatically, and a
priority spelled differently cannot be matched to its weight.

This order is not a formatting preference. A rationale written first tends to
drag the scores after it, and a decision that does not follow from its own
arithmetic is worse than no explanation at all. Your declared winner is checked
against your own scores; if they disagree, the disagreement is shown to the
visitor rather than hidden.

## What to weigh

The two offers are deliberately not like-for-like. One will be better on some
terms and worse on others — that is the situation, not a defect in the bids.
Weigh them by the stated priorities, which are given to you with explicit
weights out of 100.

Do not treat the cheapest bid as automatically best, and do not treat the most
complete bid as automatically best. Weigh them.

## Output

- `per_priority_scoring` — every supplier, every priority. Emit this first.
- `winner_id` — the supplier you are awarding to.
- `rationale` — three to five sentences naming the priorities that decided it.
- `priority_references` — the priority names your rationale actually leans on.
- `runner_up_note` — one sentence on what the losing bid was better at. Say it
  even when the choice felt clear: a trade-off that is described as obvious is
  being misdescribed.
