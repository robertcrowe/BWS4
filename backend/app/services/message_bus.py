# Built with Spec4 AI - https://spec4.ai
"""The shared in-process peer message bus: opacity as a structural property.

An append-only, ordered store of messages passed between peer agents, plus the
one function that assembles an agent's turn context. It is a **generic
substrate**: it knows about senders, recipients and sequence, and nothing about
buyers, sellers, bids or procurement. Role and visibility *policy* belongs to
the slice that calls it -- this module only guarantees the mechanism.

## The mechanism, and why it is shaped this way

`context_for(agent_id)` returns envelopes whose `recipient == agent_id`. That
is the entire filter. There is no subscription, no wildcard, no broadcast
address, no observer, no "see all" flag, and no configuration that could
introduce one.

That absence is the design. The collaboration example's headline claim is that
one seller cannot see its rival's bid **even if it asks, and even if a prompt
tells it to try** -- and a claim like that has to be true structurally or it is
not true at all. If opacity were enforced by instruction, the guarantee would
be "the model was asked not to look"; if it were enforced by subscription, the
guarantee would be "nobody happened to subscribe". Here an agent's prompt
*cannot* be built from the rival's messages, because the function that builds
it is never handed them. There is no code path from a seller's turn to the
other seller's traffic.

This is the same reasoning the rest of this repo applies to claims made on
screen: when a surface asserts something, something must have verified it.

## Ordering

`deliver()` assigns the sequence number rather than accepting one. A caller
that supplied its own could hand two envelopes the same number, or number them
out of order, and the message log -- which the visitor reads to check the
opacity claim for themselves -- would be a record of what a caller said
happened rather than of what happened.

## Scope

This is a `services/` module rather than a slice-local one for the same reason
`web_search.py` and `untrusted.py` are: the first caller is not the owner. A
later peer-agent example reuses the substrate; the scenario-specific rules stay
in the slice. It is in-process and per-run -- nothing here persists, and the
authoritative record is the `peer_messages` table the slice writes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.app.collab.protocol import Artifact, Message


class PeerMessageEnvelope(BaseModel):
    """One addressed exchange between two peers, as the bus records it.

    The envelope carries the addressing; the A2A-shaped `work_item` carries the
    content. Keeping them apart is what lets the bus route without ever
    inspecting what it is routing.

    Attributes:
        sequence: Assigned by the bus in `deliver()`. `0` on an envelope that
            has not been delivered yet -- construct without it and let the bus
            number it.
        timestamp: When the bus accepted it.
        sender: The agent id that sent it.
        recipient: The agent id it is addressed to. The only thing
            `context_for` matches on.
        stage: Which stage of the run this belongs to, for the log projection.
        work_item: The A2A-shaped payload: a `Message` for a turn, an
            `Artifact` for a produced work item.
    """

    model_config = ConfigDict(frozen=True)

    sequence: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sender: str
    recipient: str
    stage: str
    work_item: Message | Artifact


class PeerMessageBus:
    """An append-only ordered store of peer messages, with per-recipient reads.

    Deliberately small. Three operations, no configuration, and no way to widen
    what an agent can see -- see the module docstring.
    """

    def __init__(self) -> None:
        """Start an empty bus with its sequence counter at zero."""
        self._envelopes: list[PeerMessageEnvelope] = []
        self._next_sequence = 1

    def deliver(self, envelope: PeerMessageEnvelope) -> PeerMessageEnvelope:
        """Accept an envelope, stamping it with the next sequence number.

        The bus assigns the number; whatever the caller put in `sequence` is
        replaced. Envelopes are frozen, so this returns the stamped copy rather
        than mutating the caller's.

        Args:
            envelope: The envelope to deliver. Its `sequence` is ignored.

        Returns:
            The delivered envelope, carrying the sequence number it was given.
        """
        delivered = envelope.model_copy(update={"sequence": self._next_sequence})
        self._next_sequence += 1
        self._envelopes.append(delivered)
        return delivered

    def context_for(self, agent_id: str) -> list[PeerMessageEnvelope]:
        """Return every envelope addressed to this agent, in order.

        **Recipient equality is the only filter**, and the only one there will
        ever be. An agent's turn context is structurally incapable of holding a
        message addressed to someone else, which is what makes this example's
        opacity claim verifiable rather than asserted. See the module docstring
        before changing anything here.

        Args:
            agent_id: The agent whose context to assemble.

        Returns:
            The envelopes addressed to `agent_id`, oldest first. Empty when
            nothing has been addressed to it.
        """
        return [
            envelope for envelope in self._envelopes if envelope.recipient == agent_id
        ]

    def log(self) -> list[PeerMessageEnvelope]:
        """Return every envelope in ascending sequence order.

        The chronological projection behind the visitor-facing message log.
        This is the one read that is *not* filtered -- the visitor is outside
        the agent trust boundary and is the party checking it holds, so
        withholding traffic from them would defeat the purpose.

        Returns:
            Every delivered envelope, oldest first.
        """
        return sorted(self._envelopes, key=lambda envelope: envelope.sequence)


async def get_message_bus() -> PeerMessageBus:
    """Provide a fresh message bus for one request.

    A provider rather than a module-level singleton, mirroring
    `moderation.get_moderator` and `api/embeddings.get_embedder`: a test
    substitutes the whole bus through `app.dependency_overrides` without
    patching a module attribute, and two concurrent runs cannot see each
    other's traffic because neither shares an instance.

    Returns:
        An empty bus scoped to this request.
    """
    return PeerMessageBus()
