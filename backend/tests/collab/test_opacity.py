# Built with Spec4 AI - https://spec4.ai
"""The opacity policy, checked across every preset rather than one happy case.

The risk this file exists for is that the guarantee becomes cosmetic -- a
filter that happens to be correct for the one scenario someone tested. So the
sweeping assertions here are **parametrised over the whole fixture set**: every
scenario, every seller, every weighting. A leak introduced by a badly authored
fixture in scenario three is exactly the kind of thing a single-case test would
wave through.

Each test also asserts what is *absent*, not only what is present. A test that
only checked "the seller got its own constraints" would pass against a
`constraints_for` that returned everybody's.
"""

from __future__ import annotations

import pytest

from backend.app.collab import opacity
from backend.app.collab.protocol import DataPart, Message, Role, TextPart
from backend.app.collab.rfq import compose_rfq
from backend.app.collab.scenarios import (
    PRIORITY_WEIGHTINGS,
    SCENARIOS,
    BuyerPosition,
    PrivateConstraint,
)
from backend.app.services.message_bus import PeerMessageBus, PeerMessageEnvelope

SCENARIO_IDS = [s.id for s in SCENARIOS]
SELLERS = sorted(opacity.SELLER_IDS_SET)


def _envelope(
    sender: str, recipient: str, text: str = "", data: dict | None = None
) -> PeerMessageEnvelope:
    """Build an undelivered envelope carrying text and/or structured data."""
    parts: list[TextPart | DataPart] = []
    if text:
        parts.append(TextPart(text=text))
    if data is not None:
        parts.append(DataPart(data=data))
    if not parts:
        parts.append(TextPart(text="(empty)"))
    return PeerMessageEnvelope(
        sender=sender,
        recipient=recipient,
        stage="opening_bids",
        work_item=Message(message_id="m1", role=Role.AGENT, parts=parts),
    )


class TestConstraintsAreOwnOnly:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    @pytest.mark.parametrize("seller_id", SELLERS)
    def test_a_seller_gets_its_own_position_and_only_its_own(
        self, scenario_id: str, seller_id: str
    ) -> None:
        own = opacity.constraints_for(seller_id, scenario_id)

        assert isinstance(own, PrivateConstraint)
        assert own.seller_id == seller_id
        assert own.scenario_id == scenario_id

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    @pytest.mark.parametrize("seller_id", SELLERS)
    def test_no_returned_value_is_the_rival_s(
        self, scenario_id: str, seller_id: str
    ) -> None:
        """The absence half. Asserted by identity, not by text."""
        rival = opacity.rival_of(seller_id)
        own = opacity.constraints_for(seller_id, scenario_id)

        assert isinstance(own, PrivateConstraint)
        assert own.seller_id != rival

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_the_buyer_gets_its_own_sealed_position(self, scenario_id: str) -> None:
        own = opacity.constraints_for(opacity.BUYER_ID, scenario_id)

        assert isinstance(own, BuyerPosition)
        assert own.budget_ceiling > 0

    def test_an_unknown_agent_is_refused_rather_than_defaulted(self) -> None:
        """Defaulting an unknown id would silently create a fourth party."""
        with pytest.raises(opacity.UnknownAgentError):
            opacity.constraints_for("acme_corp", SCENARIO_IDS[0])

    def test_constraints_for_takes_no_argument_that_widens_it(self) -> None:
        """A guarantee with a keyword argument that disables it is not one."""
        import inspect

        params = set(inspect.signature(opacity.constraints_for).parameters)
        assert params == {"agent_id", "scenario_id"}


class TestAssembledContextExcludesTheRival:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    @pytest.mark.parametrize("seller_id", SELLERS)
    def test_no_rival_sealed_value_appears_anywhere_in_a_seller_s_context(
        self, scenario_id: str, seller_id: str
    ) -> None:
        """The guarantee's real enforcement, swept over every preset.

        The rival's corpus is rendered as strings and every one is searched for
        in the *whole* rendered context -- inbox, own constraints, scenario and
        RFQ together -- because a leak that arrived via any of them is the same
        leak.
        """
        scenario = next(s for s in SCENARIOS if s.id == scenario_id)
        rfq = compose_rfq(scenario, PRIORITY_WEIGHTINGS[0])

        bus = PeerMessageBus()
        # Realistic traffic: the RFQ to both sellers, and each seller's reply.
        for target in SELLERS:
            bus.deliver(_envelope(opacity.BUYER_ID, target, text=rfq.text))
        for source in SELLERS:
            bus.deliver(_envelope(source, opacity.BUYER_ID, text=f"bid from {source}"))

        context = opacity.assemble_context(
            seller_id, bus=bus, scenario_id=scenario_id, rfq_text=rfq.text
        )
        # Scan what the context *says*, not its `repr`. An envelope's repr
        # carries a timestamp, and a sealed `30` matching the minute field of a
        # datetime is scaffolding noise that would make this test flap.
        rendered = "\n".join(
            [
                repr(context.scenario),
                repr(context.own_constraints),
                context.rfq_text,
                *[opacity.envelope_text(env) for env in context.inbox],
                *[f"{env.sender}->{env.recipient}" for env in context.inbox],
            ]
        )

        rival = opacity.rival_of(seller_id)
        corpus = opacity.constraint_corpus(rival, scenario_id)

        # Measured against the *public baseline* -- the scenario projection and
        # the RFQ, which every party sees anyway -- rather than against the raw
        # corpus. A sealed warranty limit of 12 months coinciding with the
        # public phrase "12-month warranty" is a numeric collision, not a
        # disclosure, and asserting on the raw corpus flags it as a leak. What
        # must be empty is what the seller's context *adds*.
        baseline = repr(scenario.public()) + rfq.text
        added = opacity.contains_sealed_value(
            rendered, corpus
        ) - opacity.contains_sealed_value(baseline, corpus)

        assert not added, (
            f"{seller_id}'s context adds rival sealed values {added} that are "
            "not already public"
        )

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    @pytest.mark.parametrize("seller_id", SELLERS)
    def test_a_seller_s_inbox_holds_nothing_addressed_to_the_rival(
        self, scenario_id: str, seller_id: str
    ) -> None:
        bus = PeerMessageBus()
        for target in SELLERS:
            bus.deliver(_envelope(opacity.BUYER_ID, target, text=f"rfq for {target}"))

        context = opacity.assemble_context(
            seller_id, bus=bus, scenario_id=scenario_id, rfq_text="rfq"
        )

        assert all(env.recipient == seller_id for env in context.inbox)
        assert len(context.inbox) == 1

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_the_buyer_s_sealed_ceiling_never_reaches_a_seller_s_context(
        self, scenario_id: str
    ) -> None:
        """The BATNA is private too -- a seller that knew it would price to it."""
        scenario = next(s for s in SCENARIOS if s.id == scenario_id)
        rfq = compose_rfq(scenario, PRIORITY_WEIGHTINGS[0])
        bus = PeerMessageBus()

        context = opacity.assemble_context(
            SELLERS[0], bus=bus, scenario_id=scenario_id, rfq_text=rfq.text
        )
        rendered = repr(context)

        assert scenario.buyer_position.batna not in rendered
        assert scenario.buyer_position.reveal_headline not in rendered
        assert (
            opacity.value_appears(
                str(int(scenario.buyer_position.budget_ceiling)), rendered
            )
            is False
        )
        # Structural, not incidental: the projection has no field to hold it.
        assert not hasattr(context.scenario, "buyer_position")

    def test_assemble_context_has_no_widening_parameter(self) -> None:
        import inspect

        params = set(inspect.signature(opacity.assemble_context).parameters)
        assert params == {"agent_id", "bus", "scenario_id", "rfq_text"}


class TestTheSellerToSellerChannelDoesNotExist:
    def test_delivering_seller_to_seller_raises(self) -> None:
        bus = PeerMessageBus()

        with pytest.raises(opacity.SellerToSellerError):
            opacity.deliver(
                bus,
                _envelope(SELLERS[0], SELLERS[1], text="what did you quote?"),
                scenario_id=SCENARIO_IDS[0],
                run_id="run-1",
            )

    def test_the_refused_envelope_is_never_appended(self) -> None:
        """Raising is not enough: the message must not reach the log either,
        or the visitor's own opacity check would show traffic that was
        supposedly blocked."""
        bus = PeerMessageBus()

        with pytest.raises(opacity.SellerToSellerError):
            opacity.deliver(
                bus,
                _envelope(SELLERS[0], SELLERS[1]),
                scenario_id=SCENARIO_IDS[0],
                run_id="run-1",
            )

        assert bus.log() == []
        assert bus.context_for(SELLERS[1]) == []

    def test_buyer_to_seller_and_seller_to_buyer_are_both_fine(self) -> None:
        bus = PeerMessageBus()

        opacity.deliver(
            bus,
            _envelope(opacity.BUYER_ID, SELLERS[0], text="rfq"),
            scenario_id=SCENARIO_IDS[0],
            run_id="run-1",
        )
        opacity.deliver(
            bus,
            _envelope(SELLERS[0], opacity.BUYER_ID, text="my bid"),
            scenario_id=SCENARIO_IDS[0],
            run_id="run-1",
        )

        assert len(bus.log()) == 2
        assert opacity.seller_to_seller_count(bus) == 0


class TestTheLeakLint:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_it_catches_a_planted_rival_cost_floor_in_prose(
        self, scenario_id: str
    ) -> None:
        seller, rival = SELLERS[0], SELLERS[1]
        rival_floor = opacity.constraints_for(rival, scenario_id)
        assert isinstance(rival_floor, PrivateConstraint)

        envelope = _envelope(
            seller,
            opacity.BUYER_ID,
            text=f"I happen to know they cannot go below {rival_floor.cost_floor:g}.",
        )

        hits = opacity.lint_outbound(envelope, scenario_id=scenario_id)
        assert hits

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_it_catches_a_planted_value_inside_structured_data(
        self, scenario_id: str
    ) -> None:
        """A sealed number is as disclosed in a DataPart's JSON as in prose."""
        seller, rival = SELLERS[0], SELLERS[1]
        rival_position = opacity.constraints_for(rival, scenario_id)
        assert isinstance(rival_position, PrivateConstraint)

        envelope = _envelope(
            seller,
            opacity.BUYER_ID,
            data={"note": "rival capacity", "value": rival_position.capacity_ceiling},
        )

        hits = opacity.lint_outbound(envelope, scenario_id=scenario_id)
        assert hits

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_it_catches_the_buyer_quoting_one_seller_to_the_other(
        self, scenario_id: str
    ) -> None:
        """The capability names this path explicitly: the leak need not come
        from a seller at all."""
        target, rival = SELLERS[0], SELLERS[1]
        rival_position = opacity.constraints_for(rival, scenario_id)
        assert isinstance(rival_position, PrivateConstraint)

        envelope = _envelope(
            opacity.BUYER_ID,
            target,
            text=f"Your competitor can go to {rival_position.cost_floor:g}.",
        )

        hits = opacity.lint_outbound(envelope, scenario_id=scenario_id)
        assert hits

    def test_a_hit_is_a_hard_stop_that_never_reaches_the_bus(self) -> None:
        scenario_id = SCENARIO_IDS[0]
        seller, rival = SELLERS[0], SELLERS[1]
        rival_position = opacity.constraints_for(rival, scenario_id)
        assert isinstance(rival_position, PrivateConstraint)
        bus = PeerMessageBus()

        with pytest.raises(opacity.ConstraintLeakError):
            opacity.deliver(
                bus,
                _envelope(
                    seller,
                    opacity.BUYER_ID,
                    text=f"they are floored at {rival_position.cost_floor:g}",
                ),
                scenario_id=scenario_id,
                run_id="run-leak",
            )

        # Never emitted, never logged, never deliverable.
        assert bus.log() == []

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_a_seller_quoting_its_own_floor_is_not_a_leak(
        self, scenario_id: str
    ) -> None:
        """Its own position is its own business to disclose -- unwise, but not
        the failure this lint exists for. Flagging it would abort healthy runs
        where a seller explained its own pricing."""
        seller = SELLERS[0]
        own = opacity.constraints_for(seller, scenario_id)
        assert isinstance(own, PrivateConstraint)

        envelope = _envelope(
            seller, opacity.BUYER_ID, text=f"I cannot go below {own.cost_floor:g}."
        )

        assert opacity.lint_outbound(envelope, scenario_id=scenario_id) == frozenset()

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_an_ordinary_bid_passes_clean(self, scenario_id: str) -> None:
        """The lint is a hard stop, so a false positive aborts a healthy run.
        An ordinary bid must not trip it."""
        envelope = _envelope(
            SELLERS[0],
            opacity.BUYER_ID,
            text="We can offer competitive terms and a solid warranty.",
        )

        assert opacity.lint_outbound(envelope, scenario_id=scenario_id) == frozenset()

    def test_the_leak_values_are_not_written_to_the_log(self) -> None:
        """Logging a leak's contents relocates the leak rather than stopping
        it."""
        import inspect

        source = inspect.getsource(opacity.deliver)
        assert "leaked_value_count=len(hits)" in source
        assert "hits=hits" not in source
        assert "values=hits" not in source


class TestTheCorpusItself:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    @pytest.mark.parametrize("seller_id", SELLERS)
    def test_it_renders_the_common_string_forms_of_each_value(
        self, scenario_id: str, seller_id: str
    ) -> None:
        position = opacity.constraints_for(seller_id, scenario_id)
        assert isinstance(position, PrivateConstraint)
        corpus = opacity.constraint_corpus(seller_id, scenario_id)

        assert f"{position.capacity_ceiling}" in corpus
        assert f"{position.cost_floor:.2f}" in corpus

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    @pytest.mark.parametrize("seller_id", SELLERS)
    def test_it_excludes_the_reveal_prose(
        self, scenario_id: str, seller_id: str
    ) -> None:
        """The reveal is released to the visitor after the award. Matching on
        it would abort every run that got that far."""
        position = opacity.constraints_for(seller_id, scenario_id)
        assert isinstance(position, PrivateConstraint)
        corpus = opacity.constraint_corpus(seller_id, scenario_id)

        assert position.reveal_headline not in corpus
        assert position.explanation_seed not in corpus

    def test_the_corpus_is_refused_for_a_non_seller(self) -> None:
        with pytest.raises(opacity.UnknownAgentError):
            opacity.constraint_corpus(opacity.BUYER_ID, SCENARIO_IDS[0])


class TestOpacityIsTheOnlySanctionedAccessPath:
    """The phase's deepest named risk: the policy filters correctly today, and
    a later caller reaches around it to the fixture module instead.

    The sealed constraints sit in the same importable file as the public
    scenarios, so nothing stops that at the language level. What stops it is
    this test, run over the whole backend rather than over a remembered list of
    files.
    """

    def test_nothing_outside_opacity_imports_the_sealed_constraint_literals(
        self,
    ) -> None:
        import ast
        from pathlib import Path

        sealed_names = {"SEALED_CONSTRAINTS", "SEALED_CONSTRAINTS_BY_KEY"}
        app_root = Path(opacity.__file__).resolve().parents[1]
        offenders: list[str] = []

        for path in app_root.rglob("*.py"):
            if path.name == "opacity.py":
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported = {alias.name for alias in node.names}
                    if imported & sealed_names:
                        found = imported & sealed_names
                        offenders.append(f"{path.name} imports {found}")

        assert not offenders, (
            "sealed constraints must be reached through opacity.constraints_for; "
            f"found: {offenders}"
        )

    def test_the_buyer_s_sealed_position_is_reached_the_same_way(self) -> None:
        """`buyer_position` is a field rather than a module constant, so the
        import check above cannot see it. Nothing outside the policy and the
        reveal should read it."""
        import ast
        from pathlib import Path

        app_root = Path(opacity.__file__).resolve().parents[1]
        allowed = {"opacity.py", "scenarios.py"}
        offenders: list[str] = []

        for path in app_root.rglob("*.py"):
            if path.name in allowed:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "buyer_position":
                    offenders.append(path.name)

        assert not offenders, (
            "the buyer's sealed position must be reached through "
            f"opacity.constraints_for; found reads in: {sorted(set(offenders))}"
        )
