# Built with Spec4 AI - https://spec4.ai
"""Framework web-search capability: an async Exa Search API client, per Exa's
documented REST search endpoint.

This lives in services/ rather than inside the tool-use example because search
is a *framework* capability, not that app's private helper: a second example
app that needs the web should call this module, not import from a sibling
example. Its usage cap is CAPABILITY_SEARCH in services/shared.py.

The module name states the capability and the symbols state the provider --
there is exactly one implementation, and wrapping it in a provider-neutral
facade would only hide which service the demo actually calls.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from backend.app.core.config import get_settings

EXA_SEARCH_URL = "https://api.exa.ai/search"
REQUEST_TIMEOUT_SECONDS = 15
NUM_RESULTS = 5

_RATE_LIMIT_STATUS_CODES = {402, 429}


@dataclass(frozen=True)
class ExaResult:
    """One result item from the Exa Search API, as needed by tool_use_integration."""

    title: str
    summary: str
    source: str
    #: ISO-8601 date Exa reports for the page, or None when it could not
    #: determine one (common for package indexes and docs pages).
    #:
    #: **Carried because relevance is not recency.** Exa ranks purely on
    #: relevance, so a 2023 article can out-rank a current one for a
    #: time-sensitive question -- observed live: "Who is the CEO of Twitter?"
    #: returned two 2023 pieces at the top. Dropping this field left the model
    #: unable to weigh how current a source was and left the visitor unable to
    #: see it, which reads as the demo answering from stale training data when
    #: it is in fact reporting a stale *page*.
    published_date: str | None = None


class ExaClientError(Exception):
    """Raised when the Exa Search API call fails for a non-rate-limit reason."""


class ExaRateLimitError(Exception):
    """Raised when Exa rejects the request for hitting its rate/usage limit."""


async def search(query: str) -> list[ExaResult]:
    """Call Exa's Search API and return ranked results.

    Google-style docstring per project convention.

    Args:
        query: The search query text.

    Returns:
        Up to NUM_RESULTS results, in the order Exa ranked them.

    Raises:
        ExaRateLimitError: If Exa responds with a rate-limit/usage-limit
            status (402 or 429).
        ExaClientError: If the request fails for any other reason, or Exa
            returns a response that can't be parsed into results.
    """
    settings = get_settings()

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(
                EXA_SEARCH_URL,
                headers={
                    "x-api-key": settings.exa_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "numResults": NUM_RESULTS,
                    "contents": {"summary": True},
                },
                # No `startPublishedDate` filter, deliberately. It would make
                # recent results dominate -- and it would also break every
                # legitimately historical question ("who founded Twitter?").
                # The honest fix is to *surface* the date and let the model and
                # the visitor weigh it, not to hide old pages from both.
            )
        except httpx.HTTPError as exc:
            raise ExaClientError(str(exc)) from exc

    if response.status_code in _RATE_LIMIT_STATUS_CODES:
        raise ExaRateLimitError(
            f"Exa Search API rejected the request with status {response.status_code}"
        )
    if response.is_error:
        raise ExaClientError(
            f"Exa Search API request failed with status {response.status_code}: {response.text}"
        )

    try:
        payload = response.json()
        raw_results = payload["results"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ExaClientError("Exa Search API returned an unparseable response") from exc

    return [
        ExaResult(
            title=item.get("title") or "Untitled result",
            summary=item.get("summary") or "",
            source=item.get("url", ""),
            published_date=item.get("publishedDate"),
        )
        for item in raw_results
    ]
