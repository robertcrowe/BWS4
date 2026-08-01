# Built with Spec4 AI - https://spec4.ai
"""Input sanitisation and untrusted-data framing for the planning agent.

Two different jobs, both required by the capability's Privacy & safety section,
and it is worth being clear that only one of them is a security control:

1. `sanitize_field` cleans what the *visitor* typed -- length caps and control
   characters. This is hygiene. The visitor is not the adversary here; the point
   is that invisible characters and unbounded input do not reach a prompt.
2. `untrusted_block` frames what the *web* returned. This is the security
   control, because Exa results are open-web text arriving inside a prompt, and
   the capability names prompt injection through them as a failure mode.

**Neither makes injection impossible, and the code should not pretend
otherwise.** Delimiting plus a system-prompt instruction to treat the block as
data raises the bar; it is not a proof. What actually bounds the damage is the
tool surface: the executor can search the web and do nothing else, so the worst
outcome of a successful injection is a bad itinerary, not an action taken in
someone's name. That is the real boundary, and it lives in the design rather
than in this file.
"""

from __future__ import annotations

import unicodedata

#: Caps on what a visitor may submit. A city is a name; interests are a phrase.
#: Anything longer is a pasted document heading for a shared token budget.
MAX_CITY_CHARS = 80
MAX_INTERESTS_CHARS = 300

#: Cap on one search result's text before it goes into a prompt. Exa summaries
#: are short, so this bounds a pathological response rather than trimming normal
#: ones.
MAX_SNIPPET_CHARS = 800

_BLOCK_OPEN = "<<<UNTRUSTED_WEB_CONTENT"
_BLOCK_CLOSE = "<<<END_UNTRUSTED_WEB_CONTENT>>>"
_REMOVED = "[delimiter removed]"


def _neutralise_delimiters(text: str) -> str:
    """Strip the untrusted-block markers from text that must not carry them.

    Applied to both sides of the boundary: to search results, where a forged
    closing marker would end the untrusted region early and let everything after
    it read as prompt, and to the visitor's own fields, where a forged marker
    could not escalate anything but could still make real content appear to sit
    inside an untrusted block. Neither is text a legitimate input needs.

    Args:
        text: Content about to be placed in a prompt.

    Returns:
        The text with either marker replaced by a visible placeholder, so the
        substitution is legible to a reader rather than a silent deletion.
    """
    for marker in (_BLOCK_OPEN, _BLOCK_CLOSE):
        text = text.replace(marker, _REMOVED)
    return text


class InvalidInputError(ValueError):
    """Raised when a submitted field is blank or over-long after cleaning."""


def _strip_control_characters(text: str) -> str:
    """Remove characters that carry no meaning but do change how text reads.

    Targets Unicode categories `Cc` (control) and `Cf` (format). `Cf` is the
    interesting one: it covers the bidirectional overrides and zero-width
    joiners that let a string display as something other than what it contains
    -- a way to hide text from a human reviewing the field while the model still
    reads it.

    **Whitespace controls become a space; everything else is deleted.** The
    distinction is load-bearing rather than fussy: deleting a newline welds the
    words on either side of it into one ("food\\nand art" -> "foodand art"),
    which corrupts input a visitor typed innocently, while turning a zero-width
    joiner into a space would split a word that was always one word. Newlines
    and tabs are still not *preserved* -- nothing here is a multi-line field,
    and layout that mimics the prompt's own structure is exactly what should not
    survive.

    Args:
        text: Raw input.

    Returns:
        The text with control and format characters removed or spaced.
    """
    cleaned: list[str] = []

    for char in text:
        if char.isspace():
            cleaned.append(" ")
        elif unicodedata.category(char) not in {"Cc", "Cf"}:
            cleaned.append(char)

    return "".join(cleaned)


def sanitize_field(raw: str, *, field: str, max_chars: int) -> str:
    """Clean and bound one visitor-supplied field before it reaches a prompt.

    Google-style docstring per project convention.

    Args:
        raw: The submitted value.
        field: The field's name, used in the error message.
        max_chars: The longest accepted value after cleaning.

    Returns:
        The cleaned value: control characters removed, untrusted-block markers
        neutralised, runs of whitespace collapsed to single spaces, surrounding
        whitespace stripped.

    Raises:
        InvalidInputError: If the value is empty after cleaning, or longer than
            `max_chars`. Over-long input is rejected rather than truncated --
            silently planning a trip for the first 80 characters of a city name
            would be a stranger outcome than saying no.
    """
    cleaned = " ".join(_neutralise_delimiters(_strip_control_characters(raw)).split())

    if not cleaned:
        raise InvalidInputError(f"Enter a {field} before generating a plan.")
    if len(cleaned) > max_chars:
        raise InvalidInputError(
            f"That {field} is {len(cleaned)} characters — the limit is {max_chars}."
        )
    return cleaned


def sanitize_city(raw: str) -> str:
    """Clean a submitted city name.

    Args:
        raw: The submitted city.

    Returns:
        The cleaned city name.

    Raises:
        InvalidInputError: If it is blank or over-long.
    """
    return sanitize_field(raw, field="city", max_chars=MAX_CITY_CHARS)


def sanitize_interests(raw: str) -> str:
    """Clean a submitted interests phrase.

    Args:
        raw: The submitted interests.

    Returns:
        The cleaned interests text.

    Raises:
        InvalidInputError: If it is blank or over-long.
    """
    return sanitize_field(raw, field="description of your interests", max_chars=MAX_INTERESTS_CHARS)


def untrusted_block(label: str, content: str) -> str:
    """Wrap open-web text in a delimited block the prompts tell the model to distrust.

    The delimiters are stripped from `content` before wrapping. Without that the
    block is trivially escapable: a search result containing the closing marker
    would end the untrusted region early and everything after it would read as
    prompt. That single line is what makes the framing worth anything.

    Args:
        label: What this block is, e.g. "step 1 search results". Appears in the
            opening delimiter so the model can tell blocks apart.
        content: The untrusted text.

    Returns:
        The content wrapped in opening and closing delimiters.
    """
    return f"{_BLOCK_OPEN} {label}>>>\n{_neutralise_delimiters(content)}\n{_BLOCK_CLOSE}"
