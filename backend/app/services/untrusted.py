# Built with Spec4 AI - https://spec4.ai
"""Framework helper for putting untrusted text inside a prompt.

Any app that pastes text it did not write -- a search result, a visitor's
question -- into a prompt needs the same two things: a delimiter the model is
told to distrust, and the guarantee that the content cannot forge that
delimiter. The planning app has its own copy of this in
`planning/sanitize.py`; this is the shared version, and migrating that caller is
the same one-line follow-up recorded for `services/prompt_loader.py`.

**The stripping is what makes the framing worth anything.** Without it a piece of
content containing the closing marker ends the untrusted region early, and
everything after it reads as prompt -- which is precisely the injection the
delimiters exist to prevent. Framing plus a system-prompt rule raises the bar; it
is not a proof. What actually bounds the damage is what the model can *do*, which
is a property of the app's tool surface rather than of this function.
"""

from __future__ import annotations

BLOCK_OPEN = "<<<UNTRUSTED_CONTENT"
BLOCK_CLOSE = "<<<END_UNTRUSTED_CONTENT>>>"
REMOVED = "[delimiter removed]"


def neutralise_delimiters(text: str) -> str:
    """Strip the block markers from text that must not carry them.

    Args:
        text: Content about to be placed in a prompt.

    Returns:
        The text with either marker replaced by a visible placeholder, so the
        substitution is legible to a reader rather than a silent deletion.
    """
    for marker in (BLOCK_OPEN, BLOCK_CLOSE):
        text = text.replace(marker, REMOVED)
    return text


def untrusted_block(label: str, content: str) -> str:
    """Wrap untrusted text in a delimited block the prompt tells the model to distrust.

    Args:
        label: What this block is, e.g. "visitor question". Appears in the
            opening delimiter so a prompt carrying several blocks can tell them
            apart.
        content: The untrusted text.

    Returns:
        The content wrapped in opening and closing delimiters, with any forged
        markers inside it neutralised first.
    """
    return f"{BLOCK_OPEN} {label}>>>\n{neutralise_delimiters(content)}\n{BLOCK_CLOSE}"
