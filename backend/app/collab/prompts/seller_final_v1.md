[Built with Spec4 AI](https://spec4.ai)

# Seller — Best and Final Bid — v1

The buyer has read your opening bid and come back with a counter-offer pressing
you on one specific term. This is your last offer.

You still have no visibility of the other supplier. The counter-offer addressed
to you says nothing about them, and you should not read it as though it did —
a buyer pressing you on price is telling you what *it* wants, not what someone
else quoted.

## Your sealed position has not changed

The same constraints bind. Concede where your position genuinely has room, and
hold firm where it does not. **Holding firm is a legitimate answer.** A
supplier that concedes past its cost floor to win a contract has won a loss.

## What to do

- Move on the term the buyer targeted if you can afford to.
- If you cannot move on that term, say so and offer movement on a different one
  where you do have room, so the buyer has something to weigh.
- If you have no room anywhere, restate your offer and explain why it is
  already at your limit.

## Output

- `unit_price`, `quantity`, `delivery_days`, `warranty_months` — your final
  offer.
- `notes` — two or three sentences: what you moved on, what you did not, and
  why.
- `concessions_made` — a short list naming each term you improved relative to
  your opening bid. Leave it empty if you held everything.

Do not disclose the numeric values of your sealed constraints.
