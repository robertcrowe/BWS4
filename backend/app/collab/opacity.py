# Built with Spec4 AI - https://spec4.ai
"""The collaboration slice's opacity policy: the only sanctioned way in.

`services/message_bus.py` is a generic substrate -- it knows senders,
recipients and sequence, and nothing about buyers or sellers. This module is
where that substrate meets *this* example's rules: who may read whose sealed
constraints, what an agent's turn context is allowed to contain, and which
deliveries are forbidden outright.

The policy lives here, in the slice, so the bus stays reusable by a future
peer-agent example that has no notion of a seller at all.

## Three enforcement layers, deliberately different in kind

1. **`constraints_for(agent_id, ...)` has no code path to another party's
   position.** It is not a filter over all constraints; it is a lookup keyed by
   the caller's own identity. There is no argument that widens it.
2. **`deliver()` refuses seller-to-seller envelopes by raising**, before the
   bus is touched. Not a warning, not a drop -- an invariant violation. If it
   ever happens, something upstream is wrong in a way that a silently swallowed
   message would hide.
3. **`lint_outbound()` scans a message against the *rival's* sealed corpus**
   before it goes anywhere. Layers 1 and 2 mean rival material should never be
   in an outbound message; this is the check that says so out loud, because
   "should never" and "does not" are different claims and only one of them is
   verifiable.

Layer 3 is the interesting one. It exists precisely because layers 1 and 2 are
supposed to make it unnecessary -- a hit means a real defect, so it is a hard
stop rather than a redaction. Quietly stripping the offending text would let
the bug survive and ship.

## What is deliberately absent

No parameter, flag, override or "admin" path anywhere in this module widens
what an agent can see. `assemble_context` takes the agent's own id and the run
it belongs to, and that is all. The guarantee this example teaches is that a
seller cannot reach the rival's bid *even if it asks*, and a guarantee with a
keyword argument that disables it is not a guarantee.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import structlog

from backend.app.collab.scenarios import (
    BUYER,
    IDENTITY_CARDS,
    SCENARIOS_BY_ID,
    SEALED_CONSTRAINTS_BY_KEY,
    BuyerPosition,
    PrivateConstraint,
    PublicScenario,
    Scenario,
)
from backend.app.services.message_bus import PeerMessageBus, PeerMessageEnvelope

logger = structlog.get_logger()

COLLAB_APP_NAME: Final[str] = "Multi-Agent Collaboration App"


class AgentRole(StrEnum):
    """What kind of party an agent is.

    The distinction the whole policy turns on: two sellers are rivals and must
    not see each other, while the buyer is a counterparty to both and legitimately
    sees the bids they address to it.
    """

    BUYER = "buyer"
    SELLER = "seller"


#: Role by agent id, derived from the cast rather than restated, so a new agent
#: cannot be added to one and forgotten in the other.
_ROLES: Final[dict[str, AgentRole]] = {
    agent.id: AgentRole(agent.role) for agent in IDENTITY_CARDS
}

#: The two rival sellers.
SELLER_IDS_SET: Final[frozenset[str]] = frozenset(
    agent_id for agent_id, role in _ROLES.items() if role is AgentRole.SELLER
)

BUYER_ID: Final[str] = BUYER.id


class UnknownAgentError(Exception):
    """Raised when an agent id is not one of the three participants."""


class SellerToSellerError(Exception):
    """Raised when a delivery would put one seller in touch with the other.

    An invariant violation rather than a recoverable condition: the run is
    structured so this cannot arise, so if it does, the structure is broken.
    """


class ConstraintLeakError(Exception):
    """Raised when an outbound message carries a rival's sealed material.

    A hard safety stop. The offending artifact is never emitted -- see
    `lint_outbound`.
    """


def role_of(agent_id: str) -> AgentRole:
    """Return an agent's role.

    Args:
        agent_id: The agent to look up.

    Returns:
        Its role.

    Raises:
        UnknownAgentError: If the id is not one of the three participants.
            Refused rather than defaulted: defaulting an unknown id to `SELLER`
            would silently create a fourth party, and to `BUYER` would hand it
            both sellers' mail.
    """
    try:
        return _ROLES[agent_id]
    except KeyError:
        raise UnknownAgentError(f"Unknown agent id {agent_id!r}") from None


def rival_of(seller_id: str) -> str:
    """Return the other seller's id.

    Used only to build the corpus a message is linted *against*. Nothing in
    this module hands a seller anything belonging to its rival.

    Args:
        seller_id: One of the two sellers.

    Returns:
        The other seller's id.

    Raises:
        UnknownAgentError: If the id is not a seller.
    """
    if role_of(seller_id) is not AgentRole.SELLER:
        raise UnknownAgentError(f"{agent_label(seller_id)} is not a seller")
    others = SELLER_IDS_SET - {seller_id}
    return next(iter(others))


def agent_label(agent_id: str) -> str:
    """Return a safe label for logs and error messages.

    Args:
        agent_id: The agent to label.

    Returns:
        The agent id itself. A function rather than an f-string at each call
        site so that if labels ever need to carry more, they cannot
        accidentally start carrying sealed material.
    """
    return agent_id


def constraints_for(
    agent_id: str, scenario_id: str
) -> PrivateConstraint | BuyerPosition:
    """Return **this agent's own** sealed position, and nothing else.

    Note the shape: this is a keyed lookup on the caller's identity, not a
    filter over a collection of everyone's constraints. There is no code path
    here that returns another party's position, and no argument that could ask
    for one. That is what makes the opacity structural rather than a rule
    someone has to remember to apply.

    Args:
        agent_id: The agent asking for its own position.
        scenario_id: The scenario being negotiated.

    Returns:
        The seller's `PrivateConstraint`, or the buyer's `BuyerPosition`.

    Raises:
        UnknownAgentError: If the agent is not a participant.
        KeyError: If the scenario has no sealed position for that agent, which
            means the fixtures are incomplete rather than that the agent has
            no constraints -- an empty position would let a seller bid without
            a floor.
    """
    role = role_of(agent_id)
    if role is AgentRole.BUYER:
        return _scenario(scenario_id).buyer_position
    return SEALED_CONSTRAINTS_BY_KEY[(scenario_id, agent_id)]


def _scenario(scenario_id: str) -> Scenario:
    """Look up a scenario, raising `KeyError` when it does not exist."""
    return SCENARIOS_BY_ID[scenario_id]


def constraint_corpus(seller_id: str, scenario_id: str) -> frozenset[str]:
    """Render one seller's sealed values as the strings a leak would look like.

    The corpus the leak lint matches against. Values are rendered several ways
    because a model writes numbers the way prose does -- `356`, `356.0`,
    `£356`, `356.00` are the same disclosure.

    Deliberately **exact** string matching rather than fuzzy or semantic: the
    question this answers is "did a specific private number appear", and a
    fuzzy matcher would both miss reformattings it had not anticipated and
    raise false positives on ordinary numbers, which on a hard-stop check means
    aborting healthy runs.

    Args:
        seller_id: Whose sealed values to render.
        scenario_id: The scenario being negotiated.

    Returns:
        The string renderings of that seller's sealed numeric values. Prose
        fields (`reveal_headline`, `explanation_seed`) are **not** included:
        they are released to the visitor after the award and matching on them
        would abort every run that reached the reveal.

    Raises:
        UnknownAgentError: If the id is not a seller.
        KeyError: If the scenario has no sealed position for that seller.
    """
    if role_of(seller_id) is not AgentRole.SELLER:
        raise UnknownAgentError(f"{agent_label(seller_id)} is not a seller")

    sealed = SEALED_CONSTRAINTS_BY_KEY[(scenario_id, seller_id)]
    numbers: tuple[float, ...] = (
        sealed.cost_floor,
        float(sealed.capacity_ceiling),
        float(sealed.delivery_capability_days),
        float(sealed.warranty_liability_limit_months),
    )

    renderings: set[str] = set()
    for number in numbers:
        renderings.update(_render_number(number))
    return frozenset(renderings)


def _render_number(number: float) -> frozenset[str]:
    """Return the ways a model might write one number.

    Args:
        number: The value to render.

    Returns:
        Its plausible string forms. Integral values are rendered without a
        decimal part as well as with one, because `356` and `356.0` are the
        same disclosure written two ways.
    """
    forms = {f"{number:.2f}", f"{number:g}"}
    if number.is_integer():
        forms.add(str(int(number)))
        forms.add(f"{int(number):,}")
    return frozenset(forms)


@dataclass(frozen=True)
class TurnContext:
    """Everything one agent is given for one turn. Nothing else exists for it.

    This object *is* the opacity guarantee: a prompt built from it cannot
    contain the rival's material because the rival's material was never put
    in it. There is no lazy field, no reference back to the bus, and no
    accessor that reaches further.

    Attributes:
        agent_id: Whose turn this is.
        role: Its role.
        scenario: The **public** projection of the scenario. A
            `PublicScenario` has no field for the buyer's ceiling or BATNA, so
            it cannot carry them however it is passed on. Holding a full
            `Scenario` here was a real leak, caught by the exhaustive
            context test.
        own_constraints: This agent's own sealed position, and only its own.
        inbox: The envelopes addressed to this agent, oldest first.
        rfq_text: The public request for quotation, identical for both sellers.
    """

    agent_id: str
    role: AgentRole
    scenario: PublicScenario
    own_constraints: PrivateConstraint | BuyerPosition
    inbox: tuple[PeerMessageEnvelope, ...]
    rfq_text: str


def assemble_context(
    agent_id: str,
    *,
    bus: PeerMessageBus,
    scenario_id: str,
    rfq_text: str,
) -> TurnContext:
    """Build one agent's turn context from only what it is entitled to.

    Three sources, all of them keyed to `agent_id`: the messages the bus says
    were addressed to it, its own sealed position, and the public RFQ that both
    sellers received identically.

    **There is deliberately no fourth argument.** No flag, no override, no
    "include_rival" for debugging. The rival's envelopes and constraints are
    never handed to this function, so a prompt built from its return value
    cannot contain them -- which holds even when a seller reasons its way
    toward asking about the rival, because asking is not a channel.

    Args:
        agent_id: Whose turn is being prepared.
        bus: The run's message bus.
        scenario_id: The scenario being negotiated.
        rfq_text: The public request for quotation.

    Returns:
        The agent's turn context.

    Raises:
        UnknownAgentError: If the agent is not a participant.
        KeyError: If the scenario or the agent's sealed position is missing.
    """
    role = role_of(agent_id)
    return TurnContext(
        agent_id=agent_id,
        role=role,
        scenario=_scenario(scenario_id).public(),
        own_constraints=constraints_for(agent_id, scenario_id),
        inbox=tuple(bus.context_for(agent_id)),
        rfq_text=rfq_text,
    )


def envelope_text(envelope: PeerMessageEnvelope) -> str:
    """Flatten every text and data part of an envelope into one string.

    What the leak lint scans. Both part kinds are included: a sealed number is
    as disclosed sitting in a `DataPart`'s JSON as it is written into prose.

    Args:
        envelope: The envelope to flatten.

    Returns:
        Its content as a single string.
    """
    fragments: list[str] = []
    for part in envelope.work_item.parts:
        if part.kind == "text":
            fragments.append(part.text)
        else:
            fragments.append(_stringify(part.data))
    return "\n".join(fragments)


def _stringify(data: object) -> str:
    """Render nested JSON-ish data as a flat string for scanning."""
    if isinstance(data, dict):
        return " ".join(
            f"{key} {_stringify(value)}" for key, value in sorted(data.items())
        )
    if isinstance(data, (list, tuple)):
        return " ".join(_stringify(item) for item in data)
    if isinstance(data, float) and data.is_integer():
        # `json` round-trips 356 as 356.0; scan it the way it was written.
        return f"{data:g}"
    return str(data)


def value_appears(value: str, text: str) -> bool:
    """Whether a rendered sealed value appears in text as a *number*.

    Plain substring matching is wrong here, and the exhaustive lint tests
    caught it: a sealed delivery lead time of `7` matches inside `27`, so a
    seller quoting its own price of 27 tripped a hard safety stop and would
    have aborted a healthy run. Short sealed values -- days, months -- collide
    with almost every other number in a bid.

    So a match must not be adjacent to another digit. The lookaheads also let
    `19.5` match at the end of a sentence (`"below 19.5."`) while refusing to
    match inside `119.5` or `19.55`.

    Args:
        value: One rendered form of a sealed value.
        text: The text to search.

    Returns:
        True when the value appears as a standalone number.
    """
    pattern = rf"(?<![\d.]){re.escape(value)}(?!\d)(?!\.\d)"
    return re.search(pattern, text) is not None


def contains_sealed_value(text: str, corpus: frozenset[str]) -> frozenset[str]:
    """Return which of a corpus's values appear in text.

    The single definition of "this sealed value appears", shared by the lint
    and by the tests that sweep every preset. One definition rather than two,
    so a test cannot pass against a rule the lint does not apply.

    Args:
        text: The text to search.
        corpus: Rendered sealed values to look for.

    Returns:
        The values found, empty when none are.
    """
    return frozenset(value for value in corpus if value_appears(value, text))


def lint_outbound(
    envelope: PeerMessageEnvelope, *, scenario_id: str, public_text: str = ""
) -> frozenset[str]:
    """Return any rival sealed values found in an outbound envelope.

    Pure: it decides nothing and aborts nothing. `deliver` is what turns a
    non-empty result into a hard stop, so this stays testable without a bus,
    a run, or a logger.

    The corpus is the *rival's*, not the sender's. A seller quoting its own
    cost floor is disclosing its own position -- unwise, but its business. A
    seller or the buyer quoting the *other* seller's floor is the leak this
    example exists to prevent.

    **Values that are already public are subtracted from the corpus, and
    without that this check is unusable.** The laptops RFQ says "14-inch" and
    "a 12-month hardware warranty"; one seller's sealed delivery capability is
    14 days and its warranty limit is 12 months. Matching the raw corpus
    therefore flagged the *public request itself* and aborted every run at
    stage 1 -- found by wiring the sequencer up, not by review. A number the
    buyer published cannot become a disclosure because someone repeated it.

    Args:
        envelope: The envelope about to be delivered.
        scenario_id: The scenario being negotiated.
        public_text: Text every party has already seen -- in practice the RFQ.
            Any sealed value appearing in it is excluded from the check.

    Returns:
        The rival values found, empty when the envelope is clean.
    """
    text = envelope_text(envelope)
    corpus: set[str] = set()

    if role_of(envelope.sender) is AgentRole.SELLER:
        # A seller may not carry the other seller's numbers.
        corpus |= constraint_corpus(rival_of(envelope.sender), scenario_id)
    if role_of(envelope.recipient) is AgentRole.SELLER:
        # And nothing addressed to a seller may carry the other's -- this is
        # the buyer-quotes-seller-A-to-seller-B path the capability names.
        corpus |= constraint_corpus(rival_of(envelope.recipient), scenario_id)

    if public_text:
        corpus -= contains_sealed_value(public_text, frozenset(corpus))

    return frozenset(value for value in corpus if value_appears(value, text))


def deliver(
    bus: PeerMessageBus,
    envelope: PeerMessageEnvelope,
    *,
    scenario_id: str,
    run_id: str,
    public_text: str = "",
) -> PeerMessageEnvelope:
    """Deliver an envelope, enforcing this slice's two hard invariants first.

    The checks run **before** the bus is touched, so a refused envelope is
    never appended and never appears in the message log. Placing them here
    rather than at each call site is what makes them unbypassable: an agent
    cannot reach the bus without coming through this function.

    Args:
        bus: The run's message bus.
        envelope: The envelope to deliver.
        scenario_id: The scenario being negotiated.
        run_id: The run, for the log line a leak fires.
        public_text: Text every party has already seen, excluded from the leak
            check. In practice the RFQ -- see `lint_outbound`.

    Returns:
        The delivered envelope, carrying its bus-assigned sequence number.

    Raises:
        SellerToSellerError: If both parties are sellers. The rival channel
            does not exist and must not be creatable.
        ConstraintLeakError: If the envelope carries the rival's sealed
            values. A hard safety stop -- the artifact is not delivered and
            the caller is expected to abort the run rather than continue.
        UnknownAgentError: If either party is not a participant.
    """
    sender_role = role_of(envelope.sender)
    recipient_role = role_of(envelope.recipient)

    if sender_role is AgentRole.SELLER and recipient_role is AgentRole.SELLER:
        logger.error(
            "collab_seller_to_seller_blocked",
            run_id=run_id,
            sender=agent_label(envelope.sender),
            recipient=agent_label(envelope.recipient),
            stage=envelope.stage,
        )
        raise SellerToSellerError(
            f"Refusing to deliver {envelope.sender!r} -> {envelope.recipient!r}: "
            "there is no seller-to-seller channel in this run."
        )

    hits = lint_outbound(envelope, scenario_id=scenario_id, public_text=public_text)
    if hits:
        # The values themselves are NOT logged -- logging a leak's contents
        # would relocate the leak into the operator's log rather than stop it.
        logger.error(
            "collab_constraint_leak_blocked",
            run_id=run_id,
            sender=agent_label(envelope.sender),
            recipient=agent_label(envelope.recipient),
            stage=envelope.stage,
            leaked_value_count=len(hits),
        )
        raise ConstraintLeakError(
            f"Outbound {envelope.stage} message from {envelope.sender!r} carries "
            f"{len(hits)} of the rival's sealed values; aborting the run."
        )

    return bus.deliver(envelope)


def seller_to_seller_count(bus: PeerMessageBus) -> int:
    """Count seller-to-seller messages in a run's log.

    The app's headline claim, as a number. Expected to be zero for every run
    -- `deliver` makes any other value impossible -- which is exactly why it
    is worth measuring rather than asserting: a count computed from the log is
    evidence, and a sentence in the UI is not.

    Args:
        bus: The run's message bus.

    Returns:
        How many delivered envelopes had a seller at both ends.
    """
    return sum(
        1
        for envelope in bus.log()
        if envelope.sender in SELLER_IDS_SET and envelope.recipient in SELLER_IDS_SET
    )
