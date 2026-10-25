// Built with Spec4 AI - https://spec4.ai
/** Shared Router fixtures: the presets payload, camel-cased and as wire JSON. */
import type {
  AnswerEvent,
  DecisionEvent,
  RouterPresetsResponse,
  RouterRoute,
  RouterRunEvent,
  RunEndEvent,
} from '../src/api/router'

/**
 * Route descriptions with deliberately awkward whitespace — a double space and
 * a trailing space — so a test that the panel renders them byte for byte can
 * tell verbatim rendering from whitespace collapsing.
 */
export const ROUTES: RouterRoute[] = [
  {
    id: 'deterministic_evaluator',
    label: 'Deterministic evaluator',
    description: "No-model evaluator for arithmetic  (+, -, *, /) e.g. '72 km/h to m/s'.",
    costRank: 0,
  },
  {
    id: 'single_call',
    label: 'Single call',
    description: 'One call answering from the request alone. ',
    costRank: 1,
  },
  {
    id: 'retrieval',
    label: 'RAG over the space dataset',
    description: 'Retrieval over indexed documents. Subjects: Apollo 11, Curiosity, SpaceX.',
    costRank: 2,
  },
  {
    id: 'search_generation',
    label: 'Search + generate',
    description: 'Shared Exa web search followed by one generation call.',
    costRank: 3,
  },
]

export const ROUTER_PRESETS: RouterPresetsResponse = {
  setVersion: 'v1',
  decisionMargin: 0.15,
  costOrder: ['deterministic_evaluator', 'single_call', 'retrieval', 'search_generation'],
  presets: [
    {
      id: 'p1',
      request: 'Convert 72 km/h to metres per second.',
      expectedRoute: 'deterministic_evaluator',
      reason: 'A pure calculation.',
      pair: 'conversion',
      pairRole: 'control',
    },
    {
      id: 'p2',
      request: 'Rewrite "hey, can u send me the report asap" so it sounds professional.',
      expectedRoute: 'single_call',
      reason: 'Needs language generation but no outside facts.',
      pair: null,
      pairRole: null,
    },
    {
      id: 'p3',
      request: 'How long did Apollo 11 spend on the lunar surface, and who stayed in orbit?',
      expectedRoute: 'retrieval',
      reason: 'In the dataset.',
      pair: 'space',
      pairRole: 'control',
    },
    {
      id: 'p4',
      request: 'Who won the most recent Formula 1 race?',
      expectedRoute: 'search_generation',
      reason: 'Time-variable.',
      pair: null,
      pairRole: null,
    },
    {
      id: 'p5',
      request: 'When is the next crewed launch to the International Space Station?',
      expectedRoute: 'search_generation',
      reason: 'Near-miss.',
      pair: 'space',
      pairRole: 'near_miss',
    },
    {
      id: 'p6',
      request: 'Explain why 1 mile is about 1.609 kilometres.',
      expectedRoute: 'single_call',
      reason: 'Near-miss.',
      pair: 'conversion',
      pairRole: 'near_miss',
    },
  ],
  routeDescriptions: ROUTES,
  routeDescriptionsBlock: ROUTES.map((route) => `${route.id}: ${route.description}`).join('\n'),
  // Not a real digest: the client displays the server's hash, never recomputes it.
  routeDescriptionsSha256: 'a'.repeat(64),
}

/** The same catalogue as the backend sends it, snake_cased on the wire. */
export function presetsWireBody(body: RouterPresetsResponse) {
  return {
    set_version: body.setVersion,
    decision_margin: body.decisionMargin,
    cost_order: body.costOrder,
    presets: body.presets.map((preset) => ({
      id: preset.id,
      request: preset.request,
      expected_route: preset.expectedRoute,
      reason: preset.reason,
      pair: preset.pair,
      pair_role: preset.pairRole,
    })),
    route_descriptions: body.routeDescriptions.map((route) => ({
      id: route.id,
      label: route.label,
      description: route.description,
      cost_rank: route.costRank,
    })),
    route_descriptions_block: body.routeDescriptionsBlock,
    route_descriptions_sha256: body.routeDescriptionsSha256,
  }
}

/** A routed decision event for preset p5, agreeing with its expected route. */
export const ROUTED_DECISION: DecisionEvent = {
  kind: 'decision',
  decision_kind: 'routed',
  chosen_route: 'search_generation',
  dispatched_route: 'search_generation',
  scores: {
    deterministic_evaluator: 0.01,
    single_call: 0.1,
    retrieval: 0.42,
    search_generation: 0.93,
  },
  rationale: 'Time-sensitive; needs live web results.',
  expression: null,
  agreement: 'agreed',
  expected_route: 'search_generation',
  expected_reason: 'Near-miss.',
  low_confidence: null,
  malformed_note: null,
  evaluator_fallback_note: null,
  classifier_ms: 812,
  model: 'groq/llama-test',
}

/** The run_end for {@link ROUTED_DECISION}. */
export const ROUTED_END: RunEndEvent = {
  kind: 'run_end',
  run_id: 'run-1',
  ending: 'routed_answer',
  dispatched_route: 'search_generation',
  units: { reserved: 2, used: 1, released: 1 },
  elapsed_ms: 1234,
  cost_strip: {
    route: 'search_generation',
    route_label: 'Search + generate',
    route_taken: { model_calls: 1, searches: 1, retrievals: 0, measured_ms: 4300 },
    baseline: { model_calls: 1, searches: 1, retrievals: 0, typical_ms: null, sample_size: 2 },
    overhead: { model_calls: 1, measured_ms: 812 },
    saved_nothing: true,
    notes: [
      'Routing added one call and saved nothing on this request: the route taken is the baseline itself.',
      'Typical baseline time appears once at least 5 real search-route runs have been observed (2 so far); until then the baseline is shown as counts only.',
    ],
  },
  rerun_eligible: false,
  is_rerun: false,
  original_run_id: null,
}

/** A text answer from the search route. */
export const TEXT_ANSWER: AnswerEvent = {
  kind: 'answer',
  route: 'search_generation',
  route_label: 'Search + generate',
  answer_kind: 'text',
  text: 'The next crewed launch is scheduled for next month [1].',
  expression: null,
  evaluator_verdict: null,
  value_display: null,
  model: 'groq/llama-test',
  elapsed_ms: 900,
  truncated: false,
  error: null,
  query: 'When is the next crewed launch to the International Space Station?',
  snippets: [
    {
      index: 1,
      title: 'Launch schedule',
      url: 'https://example.test/launches',
      excerpt: 'The next crewed flight to the ISS is planned for next month.',
      published_date: '2026-10-01',
      truncated: false,
    },
  ],
  passages: [],
  invalid_citations: [],
  removed_urls: [],
  grounding: null,
  model_calls: 1,
  searches: 1,
  retrievals: 0,
}

/** The events of one routed run, in order. */
export function routedRunEvents(
  decision: DecisionEvent = ROUTED_DECISION,
  end: RunEndEvent = ROUTED_END,
  answer: AnswerEvent = TEXT_ANSWER,
): RouterRunEvent[] {
  return [
    {
      kind: 'run_started',
      run_id: end.run_id,
      request: 'When is the next crewed launch to the International Space Station?',
      preset_id: 'p5',
      units_reserved: 2,
      is_rerun: false,
      original_run_id: null,
    },
    { kind: 'stage', stage: 'classifying', message: 'Router classifying the request (1 model call)' },
    decision,
    { kind: 'stage', stage: 'dispatching', message: 'Code dispatching' },
    answer,
    end,
  ]
}

/** A history payload as the backend sends it: p1 has a rate, p2 counts only. */
export const HISTORY_WIRE = {
  presets: [
    { preset_id: 'p1', agreed: 4, disagreed: 1, declined: 1, total: 6, rate: 4 / 6 },
    { preset_id: 'p2', agreed: 2, disagreed: 0, declined: 1, total: 3, rate: null },
  ],
  overall: { preset_id: null, agreed: 6, disagreed: 1, declined: 2, total: 9, rate: 6 / 9 },
  baseline: { typical_ms: 4800, sample_size: 7, window: 50 },
  min_observations: 5,
}

/**
 * A `fetch` stand-in that answers the presets and history endpoints by URL.
 *
 * @param history - The history body to serve.
 */
export function routerFetch(history: unknown = HISTORY_WIRE) {
  return async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/router/history')) {
      return new Response(JSON.stringify(history), { status: 200 })
    }
    return new Response(JSON.stringify(presetsWireBody(ROUTER_PRESETS)), { status: 200 })
  }
}
