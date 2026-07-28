// Built with Spec4 AI - https://spec4.ai
export type ExampleAppStatus = 'live' | 'coming-soon'
export type ExampleAppAudience = 'visitor' | 'maintainer'

export interface ExampleApp {
  id: string
  name: string
  description: string
  patternTag: string
  status: ExampleAppStatus
  route: string
  /** Defaults to 'visitor' when omitted -- only 'maintainer' surfaces (e.g.
   * the framework services console) are rendered outside the visitor-facing
   * example-app directory. */
  audience?: ExampleAppAudience
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
    status: 'live',
    route: '/rag',
  },
  {
    id: 'tool_use_integration',
    name: 'Tool-Use Example App',
    description:
      'Give a model a tool schema and watch it decide whether to search, write its own query, and answer from what comes back.',
    patternTag: 'Tool Use / Function Calling',
    status: 'live',
    route: '/tool-use',
  },
  {
    id: 'shared_framework_services',
    name: 'Framework Services Console',
    description:
      'Inspect the shared generation, representation, and storage services every app is built on.',
    patternTag: 'Shared Framework Services',
    status: 'live',
    route: '/console',
    audience: 'maintainer',
  },
]
