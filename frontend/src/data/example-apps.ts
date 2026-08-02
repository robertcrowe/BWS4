// Built with Spec4 AI - https://spec4.ai
export type ExampleAppStatus = 'live' | 'coming-soon'

export interface ExampleApp {
  id: string
  name: string
  description: string
  patternTag: string
  /** A few sentences on what the *pattern* is and why it's used, independent
   * of this particular demo. Rendered in each example app's screen intro, so a
   * visitor evaluating Spec4 can tell what they're looking at before running
   * anything. `description` sells the demo; this explains the technique. */
  patternSummary: string
  status: ExampleAppStatus
  route: string
}

/**
 * The single source of truth for the example-app directory shown on the
 * landing screen. Each entry's `status` gates whether the directory card
 * links to its `route` — mark an app 'coming-soon' until its screen and
 * backend support actually exist, so the directory never links to a
 * broken route.
 *
 * **Array order is display order**, and it is deliberate. The first four run
 * from the least machinery to the most — embeddings (compare positions,
 * generate nothing), single call (one prompt, one response), RAG (retrieve
 * first, then answer from what you retrieved), tool use (let the model decide
 * what to call) — so a visitor reading top to bottom meets each pattern after
 * the cheaper one it builds on. Everything after those four is appended in the
 * order it shipped rather than slotted into the progression: chained calls
 * would otherwise sit directly after single call, and each later app would
 * shuffle the ones before it. **Newest last** is the rule — append, never
 * insert. Reordering here reorders the landing cards *and* the header menu,
 * since `NavMenu` maps the same array.
 */
export const exampleApps: ExampleApp[] = [
  {
    id: 'embeddings_example_app',
    name: 'Embeddings Example App',
    description:
      'Watch 24 curated texts arrange themselves by meaning alone, then drop in your own words and see where they land.',
    patternTag: 'Embeddings / Vector Representation',
    patternSummary:
      'Text is turned into a vector whose position encodes meaning, and everything downstream is arithmetic on those vectors — nearest-neighbour search, clustering, deduplication, topic routing. No tokens are generated and there is no answer to read, only items ranked or grouped by proximity, which is what makes this the cheapest and fastest tier that still understands paraphrase. It is the retrieval half of RAG standing on its own, and its limit is the flip side of its strength: a distance tells you two things are close, never why.',
    status: 'live',
    route: '/embeddings',
  },
  {
    id: 'single_call_example_app',
    name: 'Single-Call Example App',
    description:
      'See the simplest agentic pattern — one prompt in, one model response out, with nothing in between.',
    patternTag: 'Single-Call Pattern',
    patternSummary:
      'One request carries the whole task: the prompt goes to the model and the completion comes back, with no retrieval step before it, no tool call during it, and no second call after it. That makes it the baseline every other pattern is measured against — it is the cheapest and lowest-latency way to use a model, and the right choice whenever the work is a transformation of text the caller already has, such as summarising, classifying, or extracting fields. Its limit is exactly what the other tiers exist to fix: the model can only work from the prompt and its training, so anything depending on private data or current facts is out of reach. The Structured mode below shows the one common extension that stays within a single call: the request carries a JSON Schema, so the response comes back as data your code can use rather than prose it has to parse.',
    status: 'live',
    route: '/single-call',
  },
  {
    id: 'rag_example_app',
    name: 'RAG Example App',
    description:
      'Ask questions grounded in a small public dataset using retrieval-augmented generation.',
    patternTag: 'Retrieval-Augmented Generation',
    patternSummary:
      'Rather than relying on what a model memorised during training, the question is turned into a vector and matched against pre-embedded passages from a source corpus; the closest passages are pasted into the prompt as context. The model’s job shifts from recalling facts to summarising supplied text, which is what makes an answer traceable to a specific source and updatable by changing the corpus rather than the model. It also moves the failure mode: answers are bounded by what the corpus contains, not by what the model knows.',
    status: 'live',
    route: '/rag',
  },
  {
    id: 'tool_use_integration',
    name: 'Tool-Use Example App',
    description:
      'Give a model a tool schema and watch it decide whether to search, write its own query, and answer from what comes back.',
    patternTag: 'Tool Use / Function Calling',
    patternSummary:
      'The model is handed a machine-readable schema describing a tool it may call, and then the application waits. If the model calls the tool, it writes the arguments itself; the application executes the call and feeds the result back as a new message, and the model either answers or calls again. Deciding whether to route, how to phrase the request, and when to stop are all the model’s decisions — the application only executes calls and bounds the loop. Any logic that inspects the user’s question and picks the tool in code has left this pattern.',
    status: 'live',
    route: '/tool-use',
  },
  {
    id: 'chained_calls_example_app',
    name: 'Chained-Calls Example App',
    description:
      'Watch a story idea pass through exactly two sequential model calls — a "struggling writer" then a "harsh critic" — with both steps visible.',
    patternTag: 'Chained Calls',
    patternSummary:
      'One call’s output becomes the next call’s input, so a job which is too broad for a single request is split into steps for different agents, each designed to do one narrow thing well. The steps are fixed and known in advance — that is what separates this from a tool use or planning agent, where a model chooses what happens next. What each step buys you is isolation: the second call here receives a finished story and nothing else, so it cannot be coloured by how the first call went about writing it, which is exactly what a single call asking for both a story and a critique of it cannot guarantee. The costs are the obvious ones: every link multiplies latency and spend, and an error in an early step is inherited by every step after it. This demo runs exactly two calls to conserve a shared free-tier budget; the pattern itself supports chains of any length.',
    status: 'live',
    route: '/chained-calls',
  },
  {
    id: 'planning_agent_example_app',
    name: 'Planning-Agent Example App',
    description:
      'Watch a planner call decompose a trip-day goal into a visible plan of research and synthesis steps, then execute them — only after your explicit go-ahead — into a one-day itinerary.',
    patternTag: 'Planning Agent',
    patternSummary:
      'A planning agent first calls a model to decompose a goal into a plan of discrete steps, then executes those steps one by one — here, research steps that use the shared web-search tool, ending in exactly one synthesis step that composes the final itinerary. Because the plan is produced and displayed before execution, you can inspect exactly what the agent intends to do, and nothing runs until you say so. To conserve shared usage, each run here is limited to one planner call plus up to three executor steps, and you get three runs per hour, which reset at the top of the hour. Planning agents in general can use any number of steps — these limits are a quota-conservation choice of this demo, not a limit of the pattern.',
    status: 'live',
    route: '/planning',
  },
  {
    id: 'orchestrated_subagents_example_app',
    name: 'Orchestrated-Subagents Example App',
    description:
      'Watch a coordinator pick two of four fixed specialists, brief each one differently, run them side by side, and merge their independent answers into one.',
    patternTag: 'Orchestrated Subagents',
    patternSummary:
      'Orchestrated subagents split a question between independent workers and then put their answers back together. A coordinator chooses which specialists apply, writes each one a distinct brief naming the angle it must leave to the other, and shows you that decision before anything runs. On your go-ahead both specialists run at the same time — they can, because neither needs the other’s output, which is what separates this from a chain — and the coordinator then merges their two answers into one response organised by the question rather than by who wrote what. Both source answers stay on screen so you can judge the merge. To conserve shared usage, each run here uses a fixed budget of three model calls and you get three runs per hour, which reset at the top of the hour. The pattern itself supports any number of agents — these limits are a quota-conservation choice of this demo, not a limit of the pattern.',
    status: 'live',
    route: '/orchestrated',
  },
  {
    id: 'multi_agent_collaboration_example_app',
    name: 'Multi-Agent Collaboration Example App',
    description:
      'Watch a buyer agent negotiate with two rival sellers that hold private constraints neither can see — then unseal every hidden position.',
    patternTag: 'Multi-Agent Collaboration (peer-to-peer)',
    patternSummary:
      'In collaboration the agents are peers rather than workers: no agent owns the others’ reasoning, each holds its own goals and its own private information, and they communicate only through explicit sender→recipient messages. That is the line separating this from orchestrated subagents, where one coordinator writes both briefs and sees everything that comes back — here nobody has that view, and the buyer learns what a seller will concede only by asking it. What makes the pattern worth its cost is exactly what makes it harder: because the parties genuinely hold information the others must not see, opacity has to be enforced by the plumbing rather than by asking a model nicely, so each agent is only ever handed the messages addressed to it and a rival’s bid is unreachable rather than merely off-limits. The exchanges here use the data model and interaction pattern of the A2A collaboration protocol — inspectable identity cards, peer messages with an explicit sender and recipient, work items attached to each reply — without its network transport.',
    status: 'live',
    route: '/collab',
  },
]
