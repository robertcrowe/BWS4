# Built with Spec4 AI - https://spec4.ai
"""A2A-shaped peer message types: the data model, without the transport.

These models implement the **canonical data model and interaction pattern** of
the Agent2Agent (A2A) protocol -- its Layer 1 objects and the Layer 2 shape of
an exchange between two peers -- and deliberately stop there. There is no
Layer 3 transport binding in this file and there must not be one: no HTTP
client, no JSON-RPC envelope, no gRPC service, no `httpx` import. Two agents in
this repo hand each other Python objects through an in-process bus.

## What a real cross-owner deployment would add

Everything that makes A2A a *protocol* rather than a schema, and it is all
absent here:

- **A Layer 3 transport binding** -- JSON-RPC 2.0 over HTTPS, gRPC, or the REST
  binding -- so the two peers can be separate processes on separate networks.
- **Agent discovery** over `/.well-known/agent-card.json`, so a party can find
  and inspect a peer it was not compiled alongside.
- **Real authentication between owners**: per-party credentials, signed
  messages, and an authorisation decision at each endpoint about who may open a
  task at all.

The showcase's `/collab` screen says this in the visitor's own words rather
than leaving it in a docstring, because a demo that quietly implied it had
spoken A2A over a network would be claiming something nothing had done.

## What is deliberately not modelled

The A2A data model is large. This file carries the objects the collaboration
slice actually exchanges and **nothing else**, because it is read by people
learning the pattern. Omitted on purpose: task lifecycle operations
(`tasks/get`, `tasks/cancel`, resubscription), push-notification
configuration, security schemes, `FilePart` and the file payload types,
extensions, and every request/response envelope. If a model is not in this
file, its absence is a decision, not an oversight.

## Naming

A2A writes its wire keys in camelCase (`messageId`, `taskId`, `artifactId`,
`contextId`, `mediaType`); Python writes attributes in snake_case. `_A2AModel`
holds the alias configuration so there is exactly one place that can be wrong,
and every model here inherits it. `populate_by_name=True` is what keeps
ordinary keyword construction working -- without it these models could only be
built from their aliases, which would make every call site read like JSON.

One naming divergence worth stating: A2A spells the media descriptor
`mimeType` and carries it on file payloads, which this slice does not model.
`mediaType` rides on the parts instead, which is where a reader of this file
would look for it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _A2AModel(BaseModel):
    """Base for every protocol model: camelCase on the wire, snake_case in Python.

    The alias configuration lives here and only here. A model that forgot to
    inherit this would serialise `message_id` while its siblings serialised
    `messageId`, and mixed-case JSON is the failure this centralisation exists
    to prevent.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Role(StrEnum):
    """Who authored a message.

    A2A's two roles. In this slice `USER` is whichever peer opened the exchange
    and `AGENT` is the one responding -- the buyer is a "user" of a seller
    agent for the length of a request, which is exactly the peer symmetry the
    example is demonstrating.
    """

    USER = "user"
    AGENT = "agent"


class TaskState(StrEnum):
    """Where a task has got to.

    A2A's canonical lifecycle states. The collaboration slice only ever drives
    a task to `COMPLETED` or `FAILED`, but the full set is carried because a
    partial enum would misrepresent the protocol to someone reading this to
    learn it.
    """

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    REJECTED = "rejected"
    AUTH_REQUIRED = "auth-required"
    UNKNOWN = "unknown"


class ToolAccess(StrEnum):
    """What tools an agent may reach.

    **Not an A2A field.** A2A describes an agent's capabilities but has no
    notion of "this agent has no tools"; that is a claim this showcase makes
    about its own agents, so it is published explicitly rather than left to be
    inferred from an empty skills list.

    One member today, and that is the point: every agent in this slice is
    knowledge-only. A closed vocabulary makes "no tool access" a typed
    assertion the identity-card endpoint can be tested against, rather than a
    free-text string that could quietly become "none (except search)".
    """

    NONE = "none"


class TextPart(_A2AModel):
    """A run of plain text inside a message or artifact.

    Attributes:
        kind: The discriminator. Always `"text"`.
        text: The text itself.
        media_type: Serialised as `mediaType`. Optional; `text/plain` when a
            caller wants to be explicit.
    """

    kind: Literal["text"] = "text"
    text: str
    media_type: str | None = None


class DataPart(_A2AModel):
    """A structured JSON payload inside a message or artifact.

    This is how a bid, a counter-offer or an award travels: as data a receiving
    agent can read field by field, rather than prose it would have to parse.

    Attributes:
        kind: The discriminator. Always `"data"`.
        data: The structured payload.
        media_type: Serialised as `mediaType`. Optional; `application/json`
            when a caller wants to be explicit.
    """

    kind: Literal["data"] = "data"
    data: dict[str, Any]
    media_type: str | None = None


#: A discriminated union on `kind`, so a mixed `parts` list round-trips through
#: JSON without a validator having to guess which member it is looking at.
#: A2A also defines a file part; this slice exchanges no files and so does not
#: model one.
Part = Annotated[TextPart | DataPart, Field(discriminator="kind")]


class Message(_A2AModel):
    """One turn addressed from one peer to another.

    Attributes:
        message_id: Serialised as `messageId`. Unique per message.
        role: Who authored it.
        parts: Its content, as one or more parts.
        task_id: Serialised as `taskId`. The task this turn belongs to, when
            it belongs to one.
        context_id: Serialised as `contextId`. Groups related tasks into one
            conversation -- here, one negotiation run.
    """

    message_id: str
    role: Role
    parts: list[Part]
    task_id: str | None = None
    context_id: str | None = None


class Artifact(_A2AModel):
    """A work item a peer produced and attached to its reply.

    In this slice an artifact is a bid, a counter-offer or an award: the output
    of a turn, kept distinct from the message that carried it so the negotiation
    record can show what was *produced* separately from what was *said*.

    Attributes:
        artifact_id: Serialised as `artifactId`. Unique per artifact.
        name: Short human-readable label.
        description: What this artifact is, for a reader of the message log.
        parts: Its content, as one or more parts.
    """

    artifact_id: str
    name: str | None = None
    description: str | None = None
    parts: list[Part]


class TaskStatus(_A2AModel):
    """A task's current state, and optionally the message that set it.

    Attributes:
        state: Where the task has got to.
        message: The turn that moved it here, when there was one.
        timestamp: When this state was recorded.
    """

    state: TaskState
    message: Message | None = None
    timestamp: datetime | None = None


class Task(_A2AModel):
    """A unit of work one peer asked another to do.

    Attributes:
        id: Unique per task.
        context_id: Serialised as `contextId`. Groups the tasks of one run.
        status: Current state.
        history: The turns exchanged, oldest first.
        artifacts: What the task produced.
    """

    id: str
    context_id: str | None = None
    status: TaskStatus
    history: list[Message] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)


class AgentProvider(_A2AModel):
    """The organisation standing behind an agent.

    Attributes:
        organization: The provider's name.
        url: Where to find them.
    """

    organization: str
    url: str | None = None


class AgentSkill(_A2AModel):
    """One capability an agent advertises it can perform.

    Attributes:
        id: Stable identifier.
        name: Short human-readable label.
        description: What the skill does.
        tags: Free-form labels for discovery.
        examples: Example prompts or inputs this skill handles.
    """

    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class AgentCapabilities(_A2AModel):
    """Transport-level features an agent supports.

    Every flag is `False` for every agent in this slice, and that is accurate
    rather than lazy: there is no transport here to stream over or push
    notifications across.

    Attributes:
        streaming: Whether the agent supports streamed responses.
        push_notifications: Serialised as `pushNotifications`.
        state_transition_history: Serialised as `stateTransitionHistory`.
    """

    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = False


class AgentCard(_A2AModel):
    """What a peer publishes about itself, for inspection before an exchange.

    In a real A2A deployment this is what a party would serve at
    `/.well-known/agent-card.json` and what a peer would fetch to decide
    whether and how to talk to it. Here it is served from
    `GET /api/collab/identity-cards` so a visitor can read the same thing.

    Note what is *not* on a card: an agent's private constraints. A card is the
    public face; the sealed negotiating position stays sealed until the run
    ends.

    Attributes:
        name: The agent's name.
        description: What it does.
        version: The card's version.
        protocol_version: Serialised as `protocolVersion`. The A2A data-model
            version these shapes follow.
        url: Where the agent would be reached. `None` here, because it is not
            reachable over a network -- see this module's docstring.
        provider: The organisation behind it.
        capabilities: Transport features it supports.
        skills: What it advertises it can do.
        tool_access: Serialised as `toolAccess`. This showcase's own field --
            see `ToolAccess`.
        default_input_modes: Serialised as `defaultInputModes`.
        default_output_modes: Serialised as `defaultOutputModes`.
    """

    name: str
    description: str
    version: str
    protocol_version: str
    url: str | None = None
    provider: AgentProvider
    capabilities: AgentCapabilities
    skills: list[AgentSkill]
    tool_access: ToolAccess
    default_input_modes: list[str] = Field(default_factory=list)
    default_output_modes: list[str] = Field(default_factory=list)
