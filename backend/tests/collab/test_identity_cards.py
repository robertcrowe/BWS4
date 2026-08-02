# Built with Spec4 AI - https://spec4.ai
"""The identity-cards endpoint, and the camelCase it is supposed to speak.

The alias assertions here are the point of the file. A2A's wire keys are
camelCase, and an alias generator that silently stopped applying would still
return a body that looked entirely reasonable -- `protocol_version` is not a
*wrong* key, it is just not A2A's. So the keys are asserted by name rather than
inferred from the response validating, which it would do either way.

`TestClient(app)` is used without its context manager, following
`test_roster_api.py`: entering it runs the lifespan, which loads
sentence-transformers and fits the embeddings projection -- real work, on every
construction, for a route that touches neither a model nor a database. Twelve
of those took this file from under a second to thirty-five.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend.app.collab.protocol import AgentCard, ToolAccess
from backend.app.collab.scenarios import IDENTITY_CARDS, SELLER_IDS
from backend.app.main import app

client = TestClient(app)


def _cards() -> list[dict[str, Any]]:
    """Fetch the endpoint's payload once, for the assertions below."""
    response = client.get("/api/collab/identity-cards")
    assert response.status_code == 200, response.text
    agents: list[dict[str, Any]] = response.json()["agents"]
    return agents


class TestTheEndpointServesThreePeers:
    def test_returns_one_buyer_and_two_sellers(self) -> None:
        agents = _cards()

        assert len(agents) == 3
        assert [agent["role"] for agent in agents] == ["buyer", "seller", "seller"]

    def test_every_agent_id_is_distinct(self) -> None:
        """Ids are bus addresses, and `context_for` matches on them exactly --
        two agents sharing one would share an inbox."""
        agents = _cards()

        ids = [agent["id"] for agent in agents]
        assert len(set(ids)) == 3

    def test_the_two_sellers_are_named_differently(self) -> None:
        agents = _cards()

        seller_names = [
            agent["card"]["name"] for agent in agents if agent["role"] == "seller"
        ]
        assert len(set(seller_names)) == 2

    def test_the_published_ids_match_the_module_constants(self) -> None:
        agents = _cards()

        assert [agent["id"] for agent in agents] == [a.id for a in IDENTITY_CARDS]
        assert set(SELLER_IDS) == {
            agent["id"] for agent in agents if agent["role"] == "seller"
        }


class TestEveryCardDeclaresNoToolAccess:
    def test_tool_access_is_none_on_all_three(self) -> None:
        agents = _cards()

        assert [agent["card"]["toolAccess"] for agent in agents] == ["none"] * 3

    def test_the_enum_permits_nothing_else_today(self) -> None:
        """A closed vocabulary is what makes "knowledge-only" a typed claim
        rather than a string that could quietly grow an exception."""
        assert [member.value for member in ToolAccess] == ["none"]


class TestTheWireKeysAreA2AsOwnCamelCase:
    def test_the_card_uses_camel_case_for_every_multi_word_key(self) -> None:
        card = _cards()[0]["card"]

        for key in ("protocolVersion", "toolAccess", "defaultInputModes"):
            assert key in card, f"{key} missing -- alias generator not applied"

        for key in ("protocol_version", "tool_access", "default_input_modes"):
            assert key not in card, f"{key} present -- snake_case leaked to the wire"

    def test_nested_models_are_aliased_too(self) -> None:
        """The failure this guards against is mixed-case JSON: an alias set on
        the outer model but missing from a nested one."""
        card = _cards()[0]["card"]

        assert "pushNotifications" in card["capabilities"]
        assert "stateTransitionHistory" in card["capabilities"]
        assert "push_notifications" not in card["capabilities"]

    def test_the_message_shapes_alias_the_keys_a2a_names(self) -> None:
        """`messageId`, `taskId`, `artifactId`, `contextId`, `mediaType` -- the
        keys the A2A specification writes, checked on the models rather than
        through this endpoint, which serves none of them."""
        from backend.app.collab.protocol import Artifact, Message, Role, TextPart

        message = Message(
            message_id="m1",
            role=Role.USER,
            parts=[TextPart(text="hello", media_type="text/plain")],
            task_id="t1",
            context_id="c1",
        ).model_dump(by_alias=True)

        assert {"messageId", "taskId", "contextId"} <= set(message)
        assert "mediaType" in message["parts"][0]

        artifact = Artifact(artifact_id="a1", parts=[TextPart(text="x")]).model_dump(
            by_alias=True
        )
        assert "artifactId" in artifact

    def test_models_still_construct_from_python_names(self) -> None:
        """`populate_by_name=True`, asserted directly.

        Without it every call site would have to build these from their
        aliases, and `scenarios.py` would not import.
        """
        card = AgentCard.model_validate(
            {
                "name": "n",
                "description": "d",
                "version": "1",
                "protocol_version": "0.3.0",
                "provider": {"organization": "o"},
                "capabilities": {},
                "skills": [],
                "tool_access": "none",
            }
        )

        assert card.protocol_version == "0.3.0"
        assert card.tool_access is ToolAccess.NONE


class TestACardIsThePublicFaceOnly:
    def test_the_card_model_has_no_field_a_sealed_position_could_ride_in(self) -> None:
        """Naming a constraint's *existence* is the card's job; carrying its
        *value* is what must never happen.

        So this pins the field set rather than scanning the prose -- a card
        saying "bids against a private cost floor it never discloses" is
        correct and desirable, while a card that grew a `cost_floor: int` in a
        later phase is the leak. Asserting on the text would have flagged the
        first and missed the second.
        """
        assert set(AgentCard.model_fields) == {
            "name",
            "description",
            "version",
            "protocol_version",
            "url",
            "provider",
            "capabilities",
            "skills",
            "tool_access",
            "default_input_modes",
            "default_output_modes",
        }

    def test_no_published_value_is_numeric_beyond_the_version_strings(self) -> None:
        """A sealed position is a number -- a floor, a ceiling, a capacity. The
        only numbers a card publishes are its two version strings."""
        card = _cards()[1]["card"]

        assert card["version"] == "1.0.0"
        assert card["protocolVersion"] == "0.3.0"
        assert not any(isinstance(value, int | float) for value in card.values()), (
            "a numeric field appeared on a published card"
        )

    def test_the_endpoint_needs_no_database_and_no_model(self) -> None:
        """Static configuration: it must answer on a deployment with no
        provider keys, which is what makes it safe to render on page load."""
        first = client.get("/api/collab/identity-cards").json()
        second = client.get("/api/collab/identity-cards").json()

        assert first == second


class TestMountingTheRouterDidNotDisplaceTheExistingOnes:
    def test_the_other_example_apps_still_answer(self) -> None:
        assert client.get("/api/orchestrated/roster").status_code == 200
        assert client.get("/api/collab/identity-cards").status_code == 200
