# Built with Spec4 AI - https://spec4.ai
"""The deterministic evaluator: correct arithmetic, honest rejection, no eval.

Model-produced text reaches this evaluator, so the tests come in three groups:
fixed numeric expectations for every operator, percent rule and unit family
(temperature offsets included); rejection of everything that is not in the
closed grammar, without raising; and a source scan that forbids the dynamic
evaluation shortcuts outright.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.app.router import evaluator
from backend.app.router.constants import MAX_EXPRESSION_CHARS, MAX_NESTING_DEPTH
from backend.app.router.evaluator import (
    Accepted,
    Rejected,
    RejectionReason,
    evaluate,
    validate,
)
from backend.app.router.unit_table import (
    FAMILIES,
    OPERATOR_SYMBOLS,
    OPERATOR_WORDS,
    UNITS,
    render_supported_operations_line,
    units_in,
)


def _value(expression: str) -> float:
    result = evaluate(expression)
    assert isinstance(result, Accepted), result
    return result.value


def _reason(expression: str) -> RejectionReason:
    result = evaluate(expression)
    assert isinstance(result, Rejected), result
    return result.reason


class TestArithmetic:
    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("1 + 2", 3),
            ("10 - 4", 6),
            ("6 * 7", 42),
            ("6 x 7", 42),
            ("6 × 7", 42),
            ("6x7", 42),
            ("20 / 8", 2.5),
            ("20 ÷ 8", 2.5),
            ("10 − 4", 6),
            ("2,450 + 50", 2500),
            ("1,000,000 / 1,000", 1000),
            (".5 + .25", 0.75),
        ],
    )
    def test_each_operator(self, expression: str, expected: float) -> None:
        assert _value(expression) == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("2 + 3 * 4", 14),
            ("(2 + 3) * 4", 20),
            ("10 - 4 - 3", 3),
            ("24 / 4 / 2", 3),
            ("2 * 3 + 4 * 5", 26),
            ("((1 + 2) * (3 + 4))", 21),
            ("100 / (2 + 3) * 2", 40),
        ],
    )
    def test_precedence_and_associativity(
        self, expression: str, expected: float
    ) -> None:
        assert _value(expression) == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [("-5 + 2", -3), ("--5", 5), ("-(2 + 3)", -5), ("3 * -2", -6), ("+4", 4)],
    )
    def test_unary_signs(self, expression: str, expected: float) -> None:
        assert _value(expression) == pytest.approx(expected)


class TestPercentages:
    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("15%", 0.15),
            ("18% of 2450", 441),
            ("18% of 2,450 + 75", 516),
            ("50 * 10%", 5),
            ("200 + 10%", 220),
            ("80 - 25%", 60),
            ("200 + (10%)", 200.1),
            ("200 * 5% + 1", 11),
            ("(50 + 50)%", 1),
        ],
    )
    def test_percent_semantics(self, expression: str, expected: float) -> None:
        assert _value(expression) == pytest.approx(expected)

    def test_double_percent_is_rejected(self) -> None:
        assert _reason("5%%") is RejectionReason.SYNTAX_ERROR


class TestConversions:
    def test_72_kmh_to_ms_is_20(self) -> None:
        result = evaluate("72 km/h to m/s")
        assert isinstance(result, Accepted)
        assert result.value == pytest.approx(20)
        assert result.unit == "m/s"
        assert result.display == "20 m/s"

    @pytest.mark.parametrize(
        ("expression", "expected", "unit"),
        [
            ("1 km to m", 1000, "m"),
            ("1 mi to km", 1.609344, "km"),
            ("12 in to ft", 1, "ft"),
            ("3 feet to yards", 1, "yd"),
            ("250 cm to m", 2.5, "m"),
            ("5 kilometres to metres", 5000, "m"),
            ("60 mph to km/h", 96.56064, "km/h"),
            ("10 m/s to km/h", 36, "km/h"),
            ("1 knot to km/h", 1.852, "km/h"),
            ("72 kilometres per hour to metres per second", 20, "m/s"),
            ("(30 + 42) km/h to m/s", 20, "m/s"),
        ],
    )
    def test_length_and_speed(
        self, expression: str, expected: float, unit: str
    ) -> None:
        result = evaluate(expression)
        assert isinstance(result, Accepted), result
        assert result.value == pytest.approx(expected)
        assert result.unit == unit

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("0 C to F", 32),
            ("100 °C to °F", 212),
            ("-40 celsius to fahrenheit", -40),
            ("32 F to C", 0),
            ("98.6 degf to degc", 37),
            ("0 K to C", -273.15),
            ("25 C to K", 298.15),
            ("212 F to K", 373.15),
            ("0 degrees celsius to kelvin", 273.15),
        ],
    )
    def test_temperature_is_affine(self, expression: str, expected: float) -> None:
        assert _value(expression) == pytest.approx(expected)

    def test_temperature_is_not_a_pure_ratio(self) -> None:
        # A ratio-only implementation maps 0 to 0 in every unit.
        assert _value("0 C to K") == pytest.approx(273.15)
        assert _value("0 C to F") == pytest.approx(32)

    @pytest.mark.parametrize(
        "expression",
        ["10 km to C", "5 m/s to m", "30 C to mph", "1 K to ft"],
    )
    def test_cross_family_is_rejected(self, expression: str) -> None:
        assert _reason(expression) is RejectionReason.CROSS_FAMILY

    @pytest.mark.parametrize("expression", ["72 km/h", "5 km + 3"])
    def test_unit_without_target_is_rejected(self, expression: str) -> None:
        assert _reason(expression) is RejectionReason.UNIT_WITHOUT_TARGET

    @pytest.mark.parametrize(
        "expression", ["5 km to", "5 km to m to ft", "5 to m", "km to m"]
    )
    def test_malformed_conversions_are_rejected(self, expression: str) -> None:
        assert isinstance(evaluate(expression), Rejected)

    @pytest.mark.parametrize(
        "expression", ["5 furlongs to m", "3 parsecs to km", "10 lightyears to m"]
    )
    def test_unknown_units_are_rejected(self, expression: str) -> None:
        assert _reason(expression) is RejectionReason.UNKNOWN_WORD


class TestRejection:
    @pytest.mark.parametrize(
        "expression",
        [
            '__import__("os")',
            "__import__('os').system('ls')",
            "().__class__.__bases__",
            "os.system",
            "import os",
            "exec",
            "eval",
            "abs(-3)",
            "pow(2, 8)",
            "a + 1",
            "1; 2",
            "'1 + 2'",
            '"1 + 2"',
            "1 + 2 # comment",
            "[1, 2]",
            "{1}",
            "1 ** 2",
            "1 \\ 2",
            "x",
            "lambda: 1",
            "1_000",
            "1e3",
            "1 & 2",
            "convert 72 km/h to m/s",
        ],
    )
    def test_code_and_identifiers_are_rejected(self, expression: str) -> None:
        result = evaluate(expression)
        assert isinstance(result, Rejected), expression
        assert result.reason in {
            RejectionReason.DISALLOWED_CHARACTER,
            RejectionReason.UNKNOWN_WORD,
            RejectionReason.SYNTAX_ERROR,
            RejectionReason.INVALID_NUMBER,
        }

    @pytest.mark.parametrize(
        "expression",
        [
            "１ + 2",  # fullwidth digit one
            "١ + 2",  # arabic-indic digit one
            "1 ＋ 2",  # fullwidth plus
            "5 км to m",  # cyrillic letters that look like 'km'
            "1 + 2",  # no-break space
            "1 + 2​",  # zero-width space
            "․",  # one dot leader
        ],
    )
    def test_unicode_lookalikes_are_rejected(self, expression: str) -> None:
        assert _reason(expression) is RejectionReason.DISALLOWED_CHARACTER

    @pytest.mark.parametrize("expression", ["", "   "])
    def test_empty_is_rejected(self, expression: str) -> None:
        assert _reason(expression) is RejectionReason.EMPTY

    def test_division_by_zero_is_rejected(self) -> None:
        assert _reason("1/0") is RejectionReason.DIVISION_BY_ZERO
        assert _reason("5 / (2 - 2)") is RejectionReason.DIVISION_BY_ZERO

    def test_largest_value_within_the_cap_stays_finite(self) -> None:
        """No exponent operator and a 200-char cap keep results under ~1e200,
        so float overflow cannot be reached; the non-finite guard is defence
        in depth rather than a reachable path."""
        huge = "9" * 98
        result = evaluate(f"{huge} * {huge}")
        assert isinstance(result, Accepted)
        assert result.value == pytest.approx(1e196)

    def test_length_cap(self) -> None:
        at_cap = "1" + " + 1" * ((MAX_EXPRESSION_CHARS - 1) // 4)
        assert len(at_cap) <= MAX_EXPRESSION_CHARS
        assert isinstance(evaluate(at_cap), Accepted)
        assert _reason("1" * (MAX_EXPRESSION_CHARS + 1)) is RejectionReason.TOO_LONG

    def test_nesting_cap(self) -> None:
        ok = "(" * MAX_NESTING_DEPTH + "1" + ")" * MAX_NESTING_DEPTH
        too_deep = "(" * (MAX_NESTING_DEPTH + 1) + "1" + ")" * (MAX_NESTING_DEPTH + 1)
        assert _value(ok) == 1
        assert _reason(too_deep) is RejectionReason.TOO_DEEP
        assert _reason("-" * (MAX_NESTING_DEPTH + 1) + "1") is RejectionReason.TOO_DEEP

    @pytest.mark.parametrize(
        "expression",
        ["1 +", "* 2", "(1 + 2", "1 + 2)", "1 2", "()", "1..2", "1,23", ",5", "1."],
    )
    def test_syntax_errors_are_rejected(self, expression: str) -> None:
        assert isinstance(evaluate(expression), Rejected), expression

    def test_never_raises_on_hostile_input(self) -> None:
        for expression in ["\x00", "\ud800", "(" * 500, "-" * 500, "%" * 50]:
            assert isinstance(evaluate(expression), Rejected)


class TestValidate:
    def test_accepts_exactly_what_evaluate_accepts(self) -> None:
        for expression in ["72 km/h to m/s", "1 + 2", "1/0", "abs(1)", "5 km to C"]:
            accepted = isinstance(evaluate(expression), Accepted)
            assert (validate(expression) is None) is accepted

    def test_returns_the_rejection_reason(self) -> None:
        rejection = validate("1/0")
        assert rejection is not None
        assert rejection.reason is RejectionReason.DIVISION_BY_ZERO


class TestSingleSource:
    def test_every_unit_spelling_is_accepted(self) -> None:
        for unit in UNITS:
            target = units_in(unit.family)[0].symbol
            for alias in (unit.symbol, *unit.aliases):
                assert validate(f"1 {alias} to {target}") is None, alias

    def test_every_operator_spelling_is_accepted(self) -> None:
        templates = {
            "+": "2 {} 3",
            "-": "2 {} 3",
            "*": "2 {} 3",
            "/": "2 {} 3",
            "%": "2{}",
            "(": "{}2)",
            ")": "(2{}",
        }
        for spelling, operator in OPERATOR_SYMBOLS.items():
            assert validate(templates[operator.value].format(spelling)) is None
        for word in OPERATOR_WORDS:
            assert validate(f"2 {word} 3") is None

    def test_line_names_exactly_the_tables_families_and_units(self) -> None:
        line = render_supported_operations_line()
        assert "\n" not in line
        named = set(
            re.findall(r"\b(length|speed|temperature|mass|time|volume)\b", line)
        )
        assert named == {family.value for family in FAMILIES}
        for unit in UNITS:
            assert unit.symbol in line

    def test_line_example_is_itself_accepted(self) -> None:
        example = re.search(r"e\.g\. '([^']+)'", render_supported_operations_line())
        assert example is not None
        assert validate(example.group(1)) is None


class TestNoDynamicEvaluation:
    def test_source_has_no_eval_exec_or_ast(self) -> None:
        for module in (evaluator,):
            source = Path(module.__file__ or "").read_text(encoding="utf-8")
            assert "eval(" not in source
            assert "exec(" not in source
            assert "literal_eval" not in source
            assert "compile(" not in source
            assert "__import__" not in source
            assert not re.search(r"^\s*(import ast|from ast\b)", source, re.MULTILINE)
            assert not re.search(r"^\s*import .*\bast\b", source, re.MULTILINE)
