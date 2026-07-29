# Built with Spec4 AI - https://spec4.ai
"""The preconfigured_text_examples dataset: the curated TextExample set the
embeddings example app plots.

Bundled as a Python data file rather than JSON so each TextExample carries a
type and the module can be imported without file IO -- the set is small,
fixed, and read at process start.

Curation notes, since the app's whole point is that the plot is legible:

* **Four categories, deliberately far apart in meaning** (animals, emotions,
  technology, food). PCA to two dimensions discards most of a 384-dimension
  space, so only categories that are *strongly* separated survive the
  projection. Near-neighbour categories (say "food" and "cooking") would
  overlap in 2D and the demo would teach the opposite of its lesson.
* **Each category mixes single words, short phrases, and full sentences**,
  per the feature's Inputs. This is the more interesting demonstration: a
  whole sentence about penguins lands near the word "dog", showing the
  representation encodes meaning rather than length or surface form.
* Six per category, 24 total, matching the design mock's
  "24 curated texts across 4 categories".

**This set was measured, not guessed, and three entries were changed because
of what the measurement showed.** With the obvious first draft, 4 of 24
points landed nearer another category's centroid in the 2D projection:

* "chocolate" (Food) landed among the Emotions -- affect-laden food words
  really do sit closer to feeling than to eating in this model.
* "quiet contentment" (Emotions) landed among the Food.
* "The server crashed under heavy load during peak traffic." (Technology)
  landed among the Food; "crashed"/"heavy"/"peak" carry little technical
  signal on their own.

Replacing those three (chocolate -> cheddar cheese, quiet contentment ->
a quiet sense of calm, and the server sentence -> a compiler sentence) puts
all 24 points nearest their own category centroid and widens the narrowest
category-pair margin from +0.148 to +0.359. "pizza" was flagged in the same
first draft but placed correctly once "chocolate" no longer pulled the Food
centroid toward the Emotions, so it stayed.

Every replacement is an ordinary member of its category, not a text chosen
to game the metric. If you edit this list, re-run the clustering tests in
backend/tests/embeddings/ -- a plausible-looking swap can quietly break the
"visibly cluster by category" criterion the whole demo rests on.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextExample:
    """One curated text plotted in the semantic space.

    Attributes:
        label: The text itself, embedded verbatim and shown on the point.
        category: The semantic group it belongs to, used for the plot's
            colour/legend and for the clustering assertions in the tests.
    """

    label: str
    category: str


CATEGORY_ANIMALS = "Animals"
CATEGORY_EMOTIONS = "Emotions"
CATEGORY_TECHNOLOGY = "Technology"
CATEGORY_FOOD = "Food"

PRESET_TEXT_EXAMPLES: list[TextExample] = [
    # --- Animals ---
    TextExample("dog", CATEGORY_ANIMALS),
    TextExample("cat", CATEGORY_ANIMALS),
    TextExample("elephant", CATEGORY_ANIMALS),
    TextExample("a golden retriever puppy", CATEGORY_ANIMALS),
    TextExample("a herd of wild horses", CATEGORY_ANIMALS),
    TextExample(
        "Penguins huddle together to survive the Antarctic winter.",
        CATEGORY_ANIMALS,
    ),
    # --- Emotions ---
    TextExample("joy", CATEGORY_EMOTIONS),
    TextExample("grief", CATEGORY_EMOTIONS),
    TextExample("anger", CATEGORY_EMOTIONS),
    TextExample("a sudden wave of anxiety", CATEGORY_EMOTIONS),
    TextExample("a quiet sense of calm", CATEGORY_EMOTIONS),
    TextExample(
        "She felt overwhelming relief when the results came back clear.",
        CATEGORY_EMOTIONS,
    ),
    # --- Technology ---
    TextExample("database", CATEGORY_TECHNOLOGY),
    TextExample("algorithm", CATEGORY_TECHNOLOGY),
    TextExample("neural network", CATEGORY_TECHNOLOGY),
    TextExample("open source software", CATEGORY_TECHNOLOGY),
    TextExample("distributed computing cluster", CATEGORY_TECHNOLOGY),
    TextExample(
        "The compiler rejected the program with a type error.",
        CATEGORY_TECHNOLOGY,
    ),
    # --- Food ---
    TextExample("pizza", CATEGORY_FOOD),
    TextExample("cheddar cheese", CATEGORY_FOOD),
    TextExample("sourdough bread", CATEGORY_FOOD),
    TextExample("a steaming bowl of ramen", CATEGORY_FOOD),
    TextExample("fresh strawberries", CATEGORY_FOOD),
    TextExample(
        "He simmered the tomato sauce for three hours before serving.",
        CATEGORY_FOOD,
    ),
]
