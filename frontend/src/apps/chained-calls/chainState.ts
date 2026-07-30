// Built with Spec4 AI - https://spec4.ai
/**
 * How the two-step indicator reads in each state of a run.
 *
 * Pure logic, kept beside the components rather than inside one, so it is
 * testable without rendering and stays off React's fast-refresh path — the same
 * arrangement as `apps/single-call/format.ts` and `apps/embeddings/plotTraces.ts`.
 */

/** Where a run currently is. */
export type RunPhase =
  | 'idle'
  /** Both calls are in flight inside one round trip. */
  | 'chain-running'
  /** Only call 2 is in flight, against a story that already exists. */
  | 'retry-running'
  | 'complete'
  | 'critique-failed'
  /** Nothing ran: the budget couldn't cover the chain, or call 1 failed outright. */
  | 'blocked'

export type StepStatus = 'pending' | 'running' | 'done' | 'failed'

/**
 * Derive each call's indicator status from the run's phase.
 *
 * **`chain-running` marks both calls running, and that is deliberate.** The
 * whole chain is one HTTP round trip, so the browser learns that call 1
 * finished at the same instant it learns call 2 did. The design mock animates
 * `step1-done → step2-running` between them, but the mock drives a fake backend
 * with `setTimeout`; reproducing that here would be an invented sequence
 * presented as observed fact — the same theater the tool-use screen's fabricated
 * progress bar was removed for. Showing the real state costs a little polish and
 * keeps the screen honest. Streaming the steps live would need SSE and a
 * protocol change.
 *
 * The retry path *is* granular, and gets the finer treatment for free: only one
 * call is in flight there, so `retry-running` genuinely knows call 1 is done.
 *
 * @param phase - The run's current phase.
 * @returns The status of call 1 and call 2, in order.
 */
export function stepStatuses(phase: RunPhase): [StepStatus, StepStatus] {
  switch (phase) {
    case 'chain-running':
      return ['running', 'running']
    case 'retry-running':
      return ['done', 'running']
    case 'complete':
      return ['done', 'done']
    case 'critique-failed':
      return ['done', 'failed']
    case 'idle':
    case 'blocked':
      return ['pending', 'pending']
  }
}

/** Story ideas offered as one-click chips, taken from the design mock. */
export const PRESET_STORY_PROMPTS = [
  'a lonely lighthouse keeper who finds a message in a bottle',
  'two rival street food vendors forced to share a food truck for one night',
  'a small robot learning to paint by watching sunsets',
]
