# Built with Spec4 AI - https://spec4.ai
"""The deterministic evaluator's accepted language, defined once.

Everything the evaluator will accept is listed here: the operators and their
spellings, the keywords, and the three unit families with each unit's names
and conversion to the family's base unit. Three consumers read it and nothing
else:

- the tokenizer in `evaluator.py`, which rejects any word not listed here;
- the evaluator itself, which converts using the conversions listed here;
- `render_supported_operations_line`, which produces the deterministic route's
  one-line description the router is told and the page displays.

Because all three read this table, the route description cannot claim a unit
the evaluator rejects, and the evaluator cannot accept one the router was
never told about. Nothing here is executable text: conversions are pairs of
plain functions written in this file.

Temperature is the reason conversions are functions rather than factors.
Celsius and Fahrenheit share no zero with kelvin, so a pure ratio would turn
0 degC into 0 K. Every unit converts *to* its family's base unit and *from* it,
and a conversion is `from_base(target, to_base(source, value))`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from backend.app.router.constants import MAX_EXPRESSION_CHARS, MAX_NESTING_DEPTH


class Operator(StrEnum):
    """The arithmetic operators the evaluator accepts."""

    ADD = "+"
    SUBTRACT = "-"
    MULTIPLY = "*"
    DIVIDE = "/"
    PERCENT = "%"
    OPEN_PAREN = "("
    CLOSE_PAREN = ")"


#: Every spelling the tokenizer accepts for each operator. Single characters
#: only, matched before any word. `x` and `of` are words, listed in
#: `OPERATOR_WORDS` below.
OPERATOR_SYMBOLS: Final[dict[str, Operator]] = {
    "+": Operator.ADD,
    "-": Operator.SUBTRACT,
    "−": Operator.SUBTRACT,  # minus sign
    "*": Operator.MULTIPLY,
    "×": Operator.MULTIPLY,  # multiplication sign
    "/": Operator.DIVIDE,
    "÷": Operator.DIVIDE,  # division sign
    "%": Operator.PERCENT,
    "(": Operator.OPEN_PAREN,
    ")": Operator.CLOSE_PAREN,
}

#: Word spellings of operators. `x` reads as multiplication ("3 x 4"), and
#: `of` reads as multiplication so "18% of 2450" means 0.18 * 2450.
OPERATOR_WORDS: Final[dict[str, Operator]] = {
    "x": Operator.MULTIPLY,
    "of": Operator.MULTIPLY,
}

#: The one conversion keyword: `<quantity> <unit> to <unit>`.
CONVERSION_KEYWORD: Final[str] = "to"


class UnitFamily(StrEnum):
    """The three unit families. Conversion never crosses a family."""

    LENGTH = "length"
    SPEED = "speed"
    TEMPERATURE = "temperature"


@dataclass(frozen=True)
class Unit:
    """One unit: its display symbol, accepted spellings and base conversion.

    Attributes:
        symbol: Canonical display symbol, used in results and descriptions.
        family: The family it belongs to.
        aliases: Every spelling accepted in an expression, lower-case. The
            symbol's lower-case form is always among them.
        to_base: Converts a value in this unit to the family's base unit.
        from_base: Converts a value in the family's base unit to this unit.
    """

    symbol: str
    family: UnitFamily
    aliases: tuple[str, ...]
    to_base: Callable[[float], float]
    from_base: Callable[[float], float]


def _linear(symbol: str, family: UnitFamily, factor: float, *aliases: str) -> Unit:
    """Build a unit that converts to its base by a pure factor.

    Args:
        symbol: Canonical display symbol.
        family: The unit's family.
        factor: How many base units one of this unit is.
        *aliases: Further accepted spellings, lower-case.

    Returns:
        The unit.
    """
    return Unit(
        symbol=symbol,
        family=family,
        aliases=(symbol.lower(), *aliases),
        to_base=lambda value: value * factor,
        from_base=lambda value: value / factor,
    )


_KELVIN_OFFSET: Final[float] = 273.15

#: Every unit, grouped by family in display order. Base units: metre, metre per
#: second, kelvin.
UNITS: Final[tuple[Unit, ...]] = (
    # Length, base metre.
    _linear("m", UnitFamily.LENGTH, 1.0, "metre", "metres", "meter", "meters"),
    _linear(
        "km",
        UnitFamily.LENGTH,
        1000.0,
        "kilometre",
        "kilometres",
        "kilometer",
        "kilometers",
    ),
    _linear(
        "cm",
        UnitFamily.LENGTH,
        0.01,
        "centimetre",
        "centimetres",
        "centimeter",
        "centimeters",
    ),
    _linear(
        "mm",
        UnitFamily.LENGTH,
        0.001,
        "millimetre",
        "millimetres",
        "millimeter",
        "millimeters",
    ),
    _linear("mi", UnitFamily.LENGTH, 1609.344, "mile", "miles"),
    _linear("yd", UnitFamily.LENGTH, 0.9144, "yard", "yards"),
    _linear("ft", UnitFamily.LENGTH, 0.3048, "foot", "feet"),
    _linear("in", UnitFamily.LENGTH, 0.0254, "inch", "inches"),
    # Speed, base metre per second.
    _linear(
        "m/s",
        UnitFamily.SPEED,
        1.0,
        "mps",
        "metres per second",
        "meters per second",
        "metre per second",
        "meter per second",
    ),
    _linear(
        "km/h",
        UnitFamily.SPEED,
        1000.0 / 3600.0,
        "kph",
        "kmh",
        "km/hr",
        "kilometres per hour",
        "kilometers per hour",
        "kilometre per hour",
        "kilometer per hour",
    ),
    _linear("mph", UnitFamily.SPEED, 0.44704, "miles per hour", "mile per hour"),
    _linear("kn", UnitFamily.SPEED, 1852.0 / 3600.0, "knot", "knots"),
    _linear(
        "ft/s", UnitFamily.SPEED, 0.3048, "fps", "feet per second", "foot per second"
    ),
    # Temperature, base kelvin. Affine, never a pure factor.
    Unit(
        symbol="°C",
        family=UnitFamily.TEMPERATURE,
        aliases=("°c", "c", "degc", "celsius", "degrees celsius"),
        to_base=lambda value: value + _KELVIN_OFFSET,
        from_base=lambda value: value - _KELVIN_OFFSET,
    ),
    Unit(
        symbol="°F",
        family=UnitFamily.TEMPERATURE,
        aliases=("°f", "f", "degf", "fahrenheit", "degrees fahrenheit"),
        to_base=lambda value: (value - 32.0) * 5.0 / 9.0 + _KELVIN_OFFSET,
        from_base=lambda value: (value - _KELVIN_OFFSET) * 9.0 / 5.0 + 32.0,
    ),
    Unit(
        symbol="K",
        family=UnitFamily.TEMPERATURE,
        aliases=("k", "kelvin", "kelvins"),
        to_base=lambda value: value,
        from_base=lambda value: value,
    ),
)

#: Every accepted unit spelling, lower-case, mapped to its unit.
UNIT_ALIASES: Final[dict[str, Unit]] = {
    alias: unit for unit in UNITS for alias in unit.aliases
}

#: Unit spellings longest first, so the tokenizer's longest match finds
#: "km/h" before "km" and "metres per second" before "metres".
UNIT_ALIASES_LONGEST_FIRST: Final[tuple[str, ...]] = tuple(
    sorted(UNIT_ALIASES, key=len, reverse=True)
)

#: The families in display order.
FAMILIES: Final[tuple[UnitFamily, ...]] = tuple(UnitFamily)

#: Re-exported caps, so the table states the whole accepted language.
EXPRESSION_CHAR_CAP: Final[int] = MAX_EXPRESSION_CHARS
NESTING_DEPTH_CAP: Final[int] = MAX_NESTING_DEPTH


def units_in(family: UnitFamily) -> tuple[Unit, ...]:
    """Return the units of one family, in table order.

    Args:
        family: The family.

    Returns:
        Its units.
    """
    return tuple(unit for unit in UNITS if unit.family is family)


def render_supported_operations_line() -> str:
    """Render the deterministic route's one-line description from this table.

    The only place that line is produced. It names every operator and every
    unit symbol the evaluator accepts and states the expression form, so the
    router writes expressions the evaluator can parse.

    Returns:
        One line, no trailing newline.
    """
    families = "; ".join(
        f"{family.value} ({', '.join(unit.symbol for unit in units_in(family))})"
        for family in FAMILIES
    )
    return (
        "No-model evaluator for arithmetic (+, -, *, /, parentheses, "
        "percentages such as '18% of 2450') and unit conversions within one "
        f"family -- {families} -- written as '<number> <unit> "
        f"{CONVERSION_KEYWORD} <unit>', e.g. '72 km/h {CONVERSION_KEYWORD} m/s'."
    )
