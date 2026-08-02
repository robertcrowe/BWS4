# Built with Spec4 AI - https://spec4.ai
"""The message bus, and the one property the collaboration example rests on.

`context_for` filtering on recipient equality is not a convenience -- it is the
mechanism behind the claim that one seller cannot see its rival's bid. So the
tests here are written to fail if that filter is ever widened, including in the
ways it would plausibly be widened by someone trying to be helpful: a broadcast
address, a wildcard recipient, an "observer" that sees everything.

A test asserting only that an agent *receives its own* messages would pass
against every one of those weakenings. Each test below therefore asserts what
is **absent** from a context as well as what is present.
"""

from __future__ import annotations

from backend.app.collab.protocol import Artifact, DataPart, Message, Role, TextPart
from backend.app.services.message_bus import PeerMessageBus, PeerMessageEnvelope


def _message(text: str) -> Message:
    """Build a minimal A2A message carrying one text part."""
    return Message(
        message_id=f"msg-{text}",
        role=Role.USER,
        parts=[TextPart(text=text)],
    )


def _envelope(sender: str, recipient: str, text: str) -> PeerMessageEnvelope:
    """Build an undelivered envelope; the bus assigns its sequence."""
    return PeerMessageEnvelope(
        sender=sender,
        recipient=recipient,
        stage="opening_bids",
        work_item=_message(text),
    )


def _mixed_bus() -> PeerMessageBus:
    """A bus carrying traffic in both directions between three agents."""
    bus = PeerMessageBus()
    bus.deliver(_envelope("buyer", "northwind", "rfq-to-northwind"))
    bus.deliver(_envelope("buyer", "meridian", "rfq-to-meridian"))
    bus.deliver(_envelope("northwind", "buyer", "northwind-opening-bid"))
    bus.deliver(_envelope("meridian", "buyer", "meridian-opening-bid"))
    bus.deliver(_envelope("buyer", "northwind", "counter-to-northwind"))
    return bus


class TestContextIsBoundedByRecipient:
    def test_returns_only_envelopes_addressed_to_the_requested_agent(self) -> None:
        bus = _mixed_bus()

        context = bus.context_for("northwind")

        assert [envelope.recipient for envelope in context] == [
            "northwind",
            "northwind",
        ]
        assert len(context) == 2

    def test_a_seller_never_receives_the_rival_s_traffic(self) -> None:
        """The headline claim, asserted as an absence.

        Five envelopes exist and Meridian sent one of them. Northwind's context
        must contain none of it -- not the message, not the sender's name, not
        the text. This is what a broadcast address or an observer flag would
        break.
        """
        bus = _mixed_bus()

        context = bus.context_for("northwind")

        senders = {envelope.sender for envelope in context}
        assert "meridian" not in senders
        assert all(envelope.recipient == "northwind" for envelope in context)

        rendered = repr(context)
        assert "meridian" not in rendered
        assert "meridian-opening-bid" not in rendered

    def test_the_two_sellers_contexts_are_disjoint(self) -> None:
        """Neither seller's context shares a single envelope with the other's."""
        bus = _mixed_bus()

        northwind = {envelope.sequence for envelope in bus.context_for("northwind")}
        meridian = {envelope.sequence for envelope in bus.context_for("meridian")}

        assert northwind & meridian == set()
        assert northwind and meridian

    def test_returns_an_empty_list_for_an_agent_with_nothing_addressed_to_it(
        self,
    ) -> None:
        bus = _mixed_bus()

        assert bus.context_for("nobody") == []

    def test_returns_an_empty_list_on_an_empty_bus(self) -> None:
        assert PeerMessageBus().context_for("buyer") == []

    def test_matches_the_recipient_exactly_rather_than_by_prefix(self) -> None:
        """Equality, not `startswith` or `in` -- a looser match would leak."""
        bus = PeerMessageBus()
        bus.deliver(_envelope("buyer", "northwind-eu", "for-the-subsidiary"))

        assert bus.context_for("northwind") == []
        assert len(bus.context_for("northwind-eu")) == 1

    def test_the_sender_does_not_see_its_own_outgoing_message(self) -> None:
        """Context is what was addressed *to* you, not what you said.

        Otherwise an agent's turn context would grow its own prior output, and
        `context_for` would be a transcript rather than an inbox.
        """
        bus = PeerMessageBus()
        bus.deliver(_envelope("buyer", "northwind", "rfq"))

        assert bus.context_for("buyer") == []


class TestSequencing:
    def test_the_bus_assigns_sequence_numbers(self) -> None:
        bus = _mixed_bus()

        assert [envelope.sequence for envelope in bus.log()] == [1, 2, 3, 4, 5]

    def test_sequence_numbers_are_unique(self) -> None:
        bus = _mixed_bus()

        sequences = [envelope.sequence for envelope in bus.log()]
        assert len(set(sequences)) == len(sequences)

    def test_a_caller_supplied_sequence_is_replaced_not_trusted(self) -> None:
        """The log is the visitor's evidence for the opacity claim, so its
        ordering must be the bus's record rather than a caller's assertion."""
        bus = PeerMessageBus()
        bus.deliver(_envelope("buyer", "northwind", "first"))

        forged = PeerMessageEnvelope(
            sequence=999,
            sender="buyer",
            recipient="meridian",
            stage="opening_bids",
            work_item=_message("second"),
        )
        delivered = bus.deliver(forged)

        assert delivered.sequence == 2
        assert [envelope.sequence for envelope in bus.log()] == [1, 2]

    def test_deliver_returns_the_stamped_envelope_without_mutating_the_original(
        self,
    ) -> None:
        bus = PeerMessageBus()
        original = _envelope("buyer", "northwind", "rfq")

        delivered = bus.deliver(original)

        assert delivered.sequence == 1
        assert original.sequence == 0


class TestLogProjection:
    def test_returns_every_envelope_in_ascending_sequence_order(self) -> None:
        bus = _mixed_bus()

        log = bus.log()

        assert len(log) == 5
        assert [envelope.sequence for envelope in log] == sorted(
            envelope.sequence for envelope in log
        )

    def test_shows_traffic_addressed_to_every_agent(self) -> None:
        """Unlike `context_for`, the log is deliberately unfiltered: the visitor
        is outside the agent trust boundary and is the party checking it."""
        bus = _mixed_bus()

        recipients = {envelope.recipient for envelope in bus.log()}
        assert recipients == {"buyer", "northwind", "meridian"}

    def test_carries_no_seller_to_seller_traffic_for_this_delivery_pattern(
        self,
    ) -> None:
        """The predicate the app's headline claim is checked with."""
        bus = _mixed_bus()
        sellers = {"northwind", "meridian"}

        seller_to_seller = [
            envelope
            for envelope in bus.log()
            if envelope.sender in sellers and envelope.recipient in sellers
        ]
        assert seller_to_seller == []

    def test_is_empty_on_a_fresh_bus(self) -> None:
        assert PeerMessageBus().log() == []


class TestTheBusCarriesArtifactsAsWellAsMessages:
    def test_an_artifact_work_item_survives_delivery_and_filtering(self) -> None:
        bus = PeerMessageBus()
        artifact = Artifact(
            artifact_id="bid-1",
            name="Opening bid",
            parts=[DataPart(data={"unit_price": 412, "lead_time_days": 21})],
        )
        bus.deliver(
            PeerMessageEnvelope(
                sender="northwind",
                recipient="buyer",
                stage="opening_bids",
                work_item=artifact,
            )
        )

        context = bus.context_for("buyer")

        assert len(context) == 1
        work_item = context[0].work_item
        assert isinstance(work_item, Artifact)
        assert work_item.artifact_id == "bid-1"


class TestTheSubstrateHasNoWayToWiden:
    def test_the_bus_exposes_no_broadcast_or_observer_surface(self) -> None:
        """A structural assertion, not a stylistic one.

        The guarantee is that an agent's context *cannot* contain another
        agent's mail. That holds only while there is no second read path, so
        this fails the moment someone adds `subscribe`, `all_for`, or a
        `see_everything` flag -- which is exactly when it should.
        """
        public = {name for name in dir(PeerMessageBus) if not name.startswith("_")}

        assert public == {"deliver", "context_for", "log"}

    def test_two_buses_do_not_share_state(self) -> None:
        """The provider hands out a fresh bus per request, so two concurrent
        runs cannot see each other's traffic."""
        first = PeerMessageBus()
        second = PeerMessageBus()
        first.deliver(_envelope("buyer", "northwind", "rfq"))

        assert second.log() == []
        assert second.context_for("northwind") == []
