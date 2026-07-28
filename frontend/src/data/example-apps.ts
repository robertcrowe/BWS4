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
 */
export const exampleApps: ExampleApp[] = [
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
]
