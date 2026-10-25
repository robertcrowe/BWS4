# Built with Spec4 AI - https://spec4.ai
"""The deterministic route: a no-model evaluator over a closed grammar.

The router may hand this module an expression it wrote. That text is
untrusted model output and is **never executed**: there is no `eval`, no
`exec`, no `ast`, no dynamic-evaluation library anywhere in this file, and a
test scans the source to keep it that way. Instead:

1. **Tokenizer allow-list first.** Every character must be an ASCII digit, a
   space, an ASCII letter, a decimal point, a thousands comma, the degree sign
   or an operator spelling from `unit_table.OPERATOR_SYMBOLS`. Every word must
   be a unit spelling from the table, an operator word, or the conversion
   keyword. Anything else -- identifiers, quotes, semicolons, underscores,
   brackets other than parentheses, unicode lookalike letters or digits -- is
   rejected before a parser sees it. The length cap applies before that.
2. **Hand-written recursive descent** over the tokens, evaluating as it goes.
   The nesting cap bounds the recursion.

## Grammar

    expression := sum [ UNIT "to" UNIT ]
    sum        := term ( ("+" | "-") term )*
    term       := unary ( ("*" | "/") unary )*       # "x" and "of" mean "*"
    unary      := ("+" | "-") unary | postfix
    postfix    := primary [ "%" ]
    primary    := NUMBER | "(" sum ")"

Standard precedence: `%` binds tightest, then unary signs, then `*` `/`, then
`+` `-`; binary operators are left-associative.

## Percent semantics

- `n%` on its own is `n / 100`. So `18% of 2450` is `0.18 * 2450 = 441`, and
  `50 * 10%` is `5`.
- **Calculator semantics for `+` and `-`:** when the right operand of `+` or
  `-` is itself a percentage term (`b%`, optionally signed, with no `*` or `/`
  applied to it), it is taken relative to the left operand:
  `a + b% = a * (1 + b/100)` and `a - b% = a * (1 - b/100)`. So
  `200 + 10%` is `220` and `80 - 25%` is `60`.
- Parentheses end a percentage: `(10%)` is the plain number `0.1`, so
  `200 + (10%)` is `200.1`.
- A percentage on its own (`15%`) evaluates to `0.15`.

## Conversions

`<quantity> <unit> to <unit>`, where the quantity is any arithmetic sum and
both units belong to the same family. Temperature is affine (via kelvin), not
a ratio. A unit with no `to <unit>` after it, a unit inside arithmetic, and a
conversion across families are all rejected.

## Contract

`evaluate` and `validate` never raise on bad input; every failure is a
`Rejected` with a machine-readable reason. Division by zero and a non-finite
result are rejections.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from backend.app.router.unit_table import (
    CONVERSION_KEYWORD,
    EXPRESSION_CHAR_CAP,
    NESTING_DEPTH_CAP,
    OPERATOR_SYMBOLS,
    OPERATOR_WORDS,
    UNIT_ALIASES,
    UNIT_ALIASES_LONGEST_FIRST,
    Operator,
    Unit,
)

_DIGITS: Final[frozenset[str]] = frozenset("0123456789")
_LETTERS: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)
_DEGREE: Final[str] = "°"
#: Every character the tokenizer will look at. Checked before tokenizing.
_ALLOWED_CHARS: Final[frozenset[str]] = (
    _DIGITS | _LETTERS | frozenset(" .,") | {_DEGREE} | frozenset(OPERATOR_SYMBOLS)
)
#: Significant digits in the display string.
_DISPLAY_DIGITS: Final[int] = 10


class RejectionReason(StrEnum):
    """Why the evaluator would not compute an expression."""

    EMPTY = "empty"
    TOO_LONG = "too_long"
    DISALLOWED_CHARACTER = "disallowed_character"
    UNKNOWN_WORD = "unknown_word"
    INVALID_NUMBER = "invalid_number"
    SYNTAX_ERROR = "syntax_error"
    TOO_DEEP = "too_deep"
    DIVISION_BY_ZERO = "division_by_zero"
    NON_FINITE = "non_finite"
    UNIT_WITHOUT_TARGET = "unit_without_target"
    CROSS_FAMILY = "cross_family"


@dataclass(frozen=True)
class Accepted:
    """The evaluator computed the expression.

    Attributes:
        expression: The expression as given.
        value: The computed value.
        unit: The target unit's canonical symbol, or None for plain arithmetic.
        display: The value (and unit) as shown to a visitor, e.g. `20 m/s`.
    """

    expression: str
    value: float
    unit: str | None
    display: str


@dataclass(frozen=True)
class Rejected:
    """The evaluator would not compute the expression.

    Attributes:
        expression: The expression as given.
        reason: Machine-readable reason.
        detail: One plain sentence for logs and the decision card.
    """

    expression: str
    reason: RejectionReason
    detail: str


EvaluationResult = Accepted | Rejected


class _Kind(StrEnum):
    NUMBER = "number"
    OPERATOR = "operator"
    UNIT = "unit"
    TO = "to"


@dataclass(frozen=True)
class _Token:
    kind: _Kind
    number: float = 0.0
    operator: Operator | None = None
    unit: Unit | None = None


class _RejectError(Exception):
    """Internal control flow only; never escapes this module."""

    def __init__(self, reason: RejectionReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _read_number(text: str, start: int) -> tuple[float, int]:
    """Read an ASCII decimal number, with optional thousands commas.

    Args:
        text: The normalised expression.
        start: Index of the first digit or decimal point.

    Returns:
        The value and the index just past it.

    Raises:
        _RejectError: On a malformed number.
    """
    end = start
    while end < len(text) and (text[end] in _DIGITS or text[end] in ".,"):
        end += 1
    raw = text[start:end]
    whole, _, fraction = raw.partition(".")
    if "." in fraction or "," in fraction:
        raise _RejectError(RejectionReason.INVALID_NUMBER, f"Malformed number {raw!r}.")
    if "," in whole:
        groups = whole.split(",")
        if (
            not 1 <= len(groups[0]) <= 3
            or any(len(group) != 3 for group in groups[1:])
            or not all(groups)
        ):
            raise _RejectError(
                RejectionReason.INVALID_NUMBER, f"Malformed number {raw!r}."
            )
        whole = "".join(groups)
    if not whole and not fraction:
        raise _RejectError(RejectionReason.INVALID_NUMBER, f"Malformed number {raw!r}.")
    if raw.endswith("."):
        raise _RejectError(RejectionReason.INVALID_NUMBER, f"Malformed number {raw!r}.")
    # Built from validated ASCII digit groups only, so this conversion cannot
    # see anything but digits and at most one decimal point.
    return float(f"{whole or '0'}.{fraction or '0'}"), end


def _read_word(text: str, start: int) -> tuple[_Token, int]:
    """Read a unit spelling, operator word or the conversion keyword.

    Unit spellings are matched longest first, so `km/h` wins over `km` and
    `metres per second` over `metres`. A match must end at a word boundary.

    Args:
        text: The normalised, lower-cased expression.
        start: Index of the first letter or degree sign.

    Returns:
        The token and the index just past it.

    Raises:
        _RejectError: When the word is not in the table.
    """
    for alias in UNIT_ALIASES_LONGEST_FIRST:
        end = start + len(alias)
        if text.startswith(alias, start) and (
            end >= len(text) or text[end] not in _LETTERS
        ):
            return _Token(_Kind.UNIT, unit=UNIT_ALIASES[alias]), end
    end = start
    while end < len(text) and text[end] in _LETTERS:
        end += 1
    word = text[start:end]
    if word == CONVERSION_KEYWORD:
        return _Token(_Kind.TO), end
    if word in OPERATOR_WORDS:
        return _Token(_Kind.OPERATOR, operator=OPERATOR_WORDS[word]), end
    shown = word or text[start]
    raise _RejectError(
        RejectionReason.UNKNOWN_WORD, f"{shown!r} is not an operator or a known unit."
    )


def _tokenize(expression: str) -> list[_Token]:
    """Turn an expression into tokens, rejecting anything off the allow-list.

    Args:
        expression: The raw expression.

    Returns:
        The tokens.

    Raises:
        _RejectError: On an empty, over-long or disallowed input.
    """
    if len(expression) > EXPRESSION_CHAR_CAP:
        raise _RejectError(
            RejectionReason.TOO_LONG,
            f"Expressions are limited to {EXPRESSION_CHAR_CAP} characters.",
        )
    for char in expression:
        if char not in _ALLOWED_CHARS:
            raise _RejectError(
                RejectionReason.DISALLOWED_CHARACTER,
                f"Character {char!r} is not allowed in an expression.",
            )
    text = " ".join(expression.split()).lower()
    if not text:
        raise _RejectError(RejectionReason.EMPTY, "The expression is empty.")

    tokens: list[_Token] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == " ":
            index += 1
        elif char in _DIGITS or char == ".":
            number, index = _read_number(text, index)
            tokens.append(_Token(_Kind.NUMBER, number=number))
        elif char in _LETTERS or char == _DEGREE:
            token, index = _read_word(text, index)
            tokens.append(token)
        elif char in OPERATOR_SYMBOLS:
            tokens.append(_Token(_Kind.OPERATOR, operator=OPERATOR_SYMBOLS[char]))
            index += 1
        else:
            # Only a stray comma reaches here: every other allowed character
            # is handled above.
            raise _RejectError(
                RejectionReason.INVALID_NUMBER, f"Unexpected {char!r} outside a number."
            )
    return tokens


@dataclass(frozen=True)
class _Value:
    """An intermediate value, and whether it is a bare percentage term."""

    number: float
    is_percent: bool = False


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise _RejectError(RejectionReason.NON_FINITE, "The result is not finite.")
    return value


class _Parser:
    """Recursive descent over the token list, evaluating as it goes."""

    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._position = 0
        self._depth = 0

    def _peek(self) -> _Token | None:
        if self._position < len(self._tokens):
            return self._tokens[self._position]
        return None

    def _peek_operator(self, *operators: Operator) -> Operator | None:
        token = self._peek()
        if (
            token is not None
            and token.kind is _Kind.OPERATOR
            and token.operator in operators
        ):
            return token.operator
        return None

    def _enter(self) -> None:
        self._depth += 1
        if self._depth > NESTING_DEPTH_CAP:
            raise _RejectError(
                RejectionReason.TOO_DEEP,
                f"Nesting is limited to {NESTING_DEPTH_CAP} levels.",
            )

    def _leave(self) -> None:
        self._depth -= 1

    def parse(self) -> tuple[float, Unit | None]:
        """Parse and evaluate the whole token list.

        Returns:
            The value, and the target unit for a conversion (else None).

        Raises:
            _RejectError: On any syntax or evaluation failure.
        """
        quantity = self._sum().number
        token = self._peek()
        if token is None:
            return quantity, None
        if token.kind is not _Kind.UNIT or token.unit is None:
            raise _RejectError(
                RejectionReason.SYNTAX_ERROR, "Unexpected token after the expression."
            )
        source = token.unit
        self._position += 1
        keyword = self._peek()
        if keyword is None or keyword.kind is not _Kind.TO:
            raise _RejectError(
                RejectionReason.UNIT_WITHOUT_TARGET,
                f"A quantity in {source.symbol} needs 'to <unit>' after it.",
            )
        self._position += 1
        target_token = self._peek()
        if target_token is None or target_token.unit is None:
            raise _RejectError(
                RejectionReason.SYNTAX_ERROR, "Expected a target unit after 'to'."
            )
        target = target_token.unit
        self._position += 1
        if self._peek() is not None:
            raise _RejectError(
                RejectionReason.SYNTAX_ERROR, "Unexpected text after the target unit."
            )
        if source.family is not target.family:
            raise _RejectError(
                RejectionReason.CROSS_FAMILY,
                f"Cannot convert {source.family.value} ({source.symbol}) to "
                f"{target.family.value} ({target.symbol}).",
            )
        converted = target.from_base(source.to_base(quantity))
        return _finite(converted), target

    def _sum(self) -> _Value:
        left = self._term()
        while (
            operator := self._peek_operator(Operator.ADD, Operator.SUBTRACT)
        ) is not None:
            self._position += 1
            right = self._term()
            sign = 1.0 if operator is Operator.ADD else -1.0
            if right.is_percent:
                # Calculator semantics: a + b% is a * (1 + b/100).
                result = left.number * (1.0 + sign * right.number)
            else:
                result = left.number + sign * right.number
            left = _Value(_finite(result))
        return left

    def _term(self) -> _Value:
        left = self._unary()
        while (
            operator := self._peek_operator(Operator.MULTIPLY, Operator.DIVIDE)
        ) is not None:
            self._position += 1
            right = self._unary()
            if operator is Operator.MULTIPLY:
                result = left.number * right.number
            else:
                if right.number == 0:
                    raise _RejectError(
                        RejectionReason.DIVISION_BY_ZERO, "Division by zero."
                    )
                result = left.number / right.number
            left = _Value(_finite(result))
        return left

    def _unary(self) -> _Value:
        operator = self._peek_operator(Operator.ADD, Operator.SUBTRACT)
        if operator is None:
            return self._postfix()
        self._position += 1
        self._enter()
        inner = self._unary()
        self._leave()
        if operator is Operator.SUBTRACT:
            return _Value(-inner.number, inner.is_percent)
        return inner

    def _postfix(self) -> _Value:
        value = self._primary()
        if self._peek_operator(Operator.PERCENT) is not None:
            self._position += 1
            return _Value(value.number / 100.0, is_percent=True)
        return value

    def _primary(self) -> _Value:
        token = self._peek()
        if token is None:
            raise _RejectError(
                RejectionReason.SYNTAX_ERROR, "The expression ends too early."
            )
        if token.kind is _Kind.NUMBER:
            self._position += 1
            return _Value(token.number)
        if token.kind is _Kind.OPERATOR and token.operator is Operator.OPEN_PAREN:
            self._position += 1
            self._enter()
            inner = self._sum()
            self._leave()
            if self._peek_operator(Operator.CLOSE_PAREN) is None:
                raise _RejectError(
                    RejectionReason.SYNTAX_ERROR, "Missing closing parenthesis."
                )
            self._position += 1
            # Parentheses end a percentage: (10%) is the plain number 0.1.
            return _Value(inner.number)
        raise _RejectError(
            RejectionReason.SYNTAX_ERROR, "Expected a number or '(' here."
        )


def _display(value: float, unit: Unit | None) -> str:
    """Format a result for display, to ten significant digits.

    Args:
        value: The computed value.
        unit: The target unit, if any.

    Returns:
        E.g. `20 m/s`, `516`, `-40 °F`.
    """
    shown = format(value, f".{_DISPLAY_DIGITS}g")
    if shown in {"-0", "0"}:
        shown = "0"
    return f"{shown} {unit.symbol}" if unit else shown


def _run(expression: str) -> EvaluationResult:
    """Tokenize, parse and evaluate, catching every rejection.

    Args:
        expression: The raw expression.

    Returns:
        The accepted value or the rejection.
    """
    try:
        value, unit = _Parser(_tokenize(expression)).parse()
    except _RejectError as rejection:
        return Rejected(expression, rejection.reason, rejection.detail)
    except ArithmeticError:
        return Rejected(
            expression, RejectionReason.NON_FINITE, "The result is not finite."
        )
    if value == 0:
        value = 0.0  # normalise -0.0
    return Accepted(
        expression=expression,
        value=value,
        unit=unit.symbol if unit else None,
        display=_display(value, unit),
    )


def evaluate(expression: str) -> EvaluationResult:
    """Compute an expression in the evaluator's closed grammar.

    Pure, and never raises on bad input.

    Args:
        expression: Untrusted text, typically written by the router model.

    Returns:
        `Accepted` with the value and normalised unit, or `Rejected` with a
        machine-readable reason.
    """
    return _run(expression)


def validate(expression: str) -> Rejected | None:
    """Decide whether the evaluator accepts an expression.

    The gate for releasing the deterministic route's second reserved unit.
    Shares the tokenizer, table and parser with `evaluate`, so an expression
    validates if and only if it evaluates -- the two cannot drift.

    Args:
        expression: Untrusted text, typically written by the router model.

    Returns:
        None when the evaluator accepts it, else the rejection.
    """
    result = _run(expression)
    return result if isinstance(result, Rejected) else None
