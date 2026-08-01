// Built with Spec4 AI - https://spec4.ai
/**
 * The dispatch stream's client half: the fold, and the request itself.
 *
 * Two things worth pinning here, and neither is about rendering.
 *
 * The fold must keep the columns **independent**. A specialist settling has to
 * leave its partner exactly as it was — otherwise "both columns in progress
 * together" is a claim the state cannot actually support, however the columns
 * happen to look on the day.
 *
 * The request must be a POST that overrides `openWhenHidden`. The default
 * reopens a dropped connection when a backgrounded tab returns, which against
 * this endpoint means posting the same `decision_id` twice — and the server
 * redeems that id on first use, so the second attempt is refused and the
 * visitor loses the run.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import {
  applyDispatchEvent,
  bothRunning,
  initialDispatchState,
  merging,
} from '../src/apps/orchestrated/runState'
import type { DispatchEvent } from '../src/api/orchestrated'

const BRIEFS = [
  { specialist_id: 'technical', instruction: 'Cover the mechanism.' },
  { specialist_id: 'financial', instruction: 'Cover the cost.' },
]

const running = (id: string): DispatchEvent => ({
  name: 'specialist_status',
  data: { specialist_id: id, status: 'running' },
})

const answered = (id: string): DispatchEvent => ({
  name: 'specialist_answer',
  data: {
    specialist_id: id,
    status: 'ok',
    answer: `${id} answer`,
    key_points: [`${id} point`],
    error: null,
  },
})

describe('folding the dispatch stream', () => {
  it('heads every column with its brief before anything runs', () => {
    const state = initialDispatchState(BRIEFS)

    expect(state.columns.map((c) => c.instruction)).toEqual([
      'Cover the mechanism.',
      'Cover the cost.',
    ])
    expect(state.columns.every((c) => c.phase === 'waiting')).toBe(true)
  })

  it('shows both columns running at once', () => {
    let state = initialDispatchState(BRIEFS)
    state = applyDispatchEvent(state, running('technical'))
    expect(bothRunning(state)).toBe(false)

    state = applyDispatchEvent(state, running('financial'))
    expect(bothRunning(state)).toBe(true)
  })

  it('leaves the partner column untouched when one settles', () => {
    let state = initialDispatchState(BRIEFS)
    state = applyDispatchEvent(state, running('technical'))
    state = applyDispatchEvent(state, running('financial'))
    const slowColumn = state.columns[1]

    state = applyDispatchEvent(state, answered('technical'))

    expect(state.columns[0].phase).toBe('ok')
    expect(state.columns[0].answer).toBe('technical answer')
    // Identity, not equality: the untouched column is not even rebuilt.
    expect(state.columns[1]).toBe(slowColumn)
    expect(state.columns[1].phase).toBe('running')
  })

  it('keeps a surviving answer when its partner fails', () => {
    let state = initialDispatchState(BRIEFS)
    state = applyDispatchEvent(state, answered('financial'))
    state = applyDispatchEvent(state, {
      name: 'specialist_answer',
      data: {
        specialist_id: 'technical',
        status: 'failed',
        answer: '',
        key_points: [],
        error: 'This specialist could not be reached.',
      },
    })

    expect(state.columns[0].phase).toBe('failed')
    expect(state.columns[1].answer).toBe('financial answer')
  })

  it('distinguishes a timeout from a failure', () => {
    let state = initialDispatchState(BRIEFS)
    state = applyDispatchEvent(state, {
      name: 'specialist_answer',
      data: {
        specialist_id: 'technical',
        status: 'timeout',
        answer: '',
        key_points: [],
        error: 'Still working when the run stopped waiting.',
      },
    })

    expect(state.columns[0].phase).toBe('timeout')
    expect(state.columns[0].phase).not.toBe('failed')
  })

  it('carries the run refund from a both-failed stream', () => {
    let state = initialDispatchState(BRIEFS)
    state = applyDispatchEvent(state, {
      name: 'error',
      data: {
        outcome: 'specialists_failed',
        message: 'Neither specialist could be reached.',
        decision_id: 'run-1',
        retryable: true,
        refund_run: true,
      },
    })

    expect(state.error?.refundRun).toBe(true)
    expect(state.error?.retryable).toBe(true)
  })

  it('treats a missing refund flag as no refund', () => {
    let state = initialDispatchState(BRIEFS)
    state = applyDispatchEvent(state, {
      name: 'error',
      data: {
        outcome: 'dispatch_expired',
        message: 'No longer valid.',
        decision_id: 'run-1',
        retryable: false,
      },
    })

    expect(state.error?.refundRun).toBe(false)
  })

  it('reports merging only between the fan-out and the merged answer', () => {
    let state = initialDispatchState(BRIEFS)
    expect(merging(state)).toBe(false)

    state = applyDispatchEvent(state, answered('technical'))
    state = applyDispatchEvent(state, answered('financial'))
    expect(merging(state)).toBe(false)

    state = applyDispatchEvent(state, {
      name: 'fan_out_complete',
      data: { decision_id: 'run-1', survivors: ['technical', 'financial'], model_call_count: 3 },
    })
    // The columns are done and the final event has not arrived. Derived, not timed.
    expect(merging(state)).toBe(true)

    state = applyDispatchEvent(state, {
      name: 'merged_answer',
      data: {
        decision_id: 'run-1',
        text: 'One integrated answer.',
        sources_used: ['technical', 'financial'],
        disagreement_note: {
          summary: 'One priced it, the other explained it.',
          agreements: ['Contention is the problem'],
          complements: ['Technical supplied mechanism, Financial supplied cost'],
          contradictions: [],
          comparable: true,
        },
        model_call_count: 3,
      },
    })

    expect(merging(state)).toBe(false)
    expect(state.merged?.text).toBe('One integrated answer.')
    expect(state.merged?.disagreement_note.comparable).toBe(true)
  })

  it('keeps the columns intact when the merged answer arrives', () => {
    let state = initialDispatchState(BRIEFS)
    state = applyDispatchEvent(state, answered('technical'))
    const settledColumn = state.columns[0]

    state = applyDispatchEvent(state, {
      name: 'merged_answer',
      data: {
        decision_id: 'run-1',
        text: 'merged',
        sources_used: ['technical'],
        disagreement_note: {
          summary: 'Only one specialist returned an answer.',
          agreements: [],
          complements: [],
          contradictions: [],
          comparable: false,
        },
        model_call_count: 3,
      },
    })

    // The specialist answers stay on screen beside the merge.
    expect(state.columns[0]).toBe(settledColumn)
    expect(state.merged?.disagreement_note.comparable).toBe(false)
  })

  it('stops reporting merging once the stream errors', () => {
    let state = initialDispatchState(BRIEFS)
    state = applyDispatchEvent(state, {
      name: 'fan_out_complete',
      data: { decision_id: 'run-1', survivors: ['technical'], model_call_count: 3 },
    })
    state = applyDispatchEvent(state, {
      name: 'error',
      data: {
        outcome: 'synthesis_failed',
        message: 'They could not be merged.',
        decision_id: 'run-1',
        retryable: true,
      },
    })

    expect(merging(state)).toBe(false)
  })

  it('ignores an event naming a column that does not exist', () => {
    const state = initialDispatchState(BRIEFS)

    expect(applyDispatchEvent(state, running('historical')).columns).toEqual(
      state.columns,
    )
  })
})

describe('the dispatch request', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts the decision and never reopens on a hidden tab', async () => {
    const calls: Array<Record<string, unknown>> = []
    vi.doMock('@microsoft/fetch-event-source', () => ({
      fetchEventSource: async (url: string, options: Record<string, unknown>) => {
        calls.push({ url, ...options })
      },
    }))

    const { dispatchSpecialists } = await import('../src/api/orchestrated')
    await dispatchSpecialists({
      decisionId: 'run-1',
      decision: {
        decision_id: 'run-1',
        chosen_specialists: ['technical', 'financial'],
        rationale: 'why',
        briefs: BRIEFS,
        fit_quality: 'strong',
        model_call_count: 3,
      },
      question: 'Should we split the database?',
      onEvent: () => {},
    })

    expect(calls).toHaveLength(1)
    expect(calls[0].method).toBe('POST')
    // Reopening would re-post a decision id the server has already redeemed.
    expect(calls[0].openWhenHidden).toBe(true)
    expect(JSON.parse(String(calls[0].body))).toMatchObject({
      decision_id: 'run-1',
      question: 'Should we split the database?',
    })
  })

  it('rethrows from onerror so a failed dispatch is terminal', async () => {
    let capturedOnError: ((cause: unknown) => void) | undefined
    vi.doMock('@microsoft/fetch-event-source', () => ({
      fetchEventSource: async (_url: string, options: Record<string, unknown>) => {
        capturedOnError = options.onerror as (cause: unknown) => void
      },
    }))

    const { dispatchSpecialists } = await import('../src/api/orchestrated')
    await dispatchSpecialists({
      decisionId: 'run-1',
      decision: {
        decision_id: 'run-1',
        chosen_specialists: ['technical', 'financial'],
        rationale: 'why',
        briefs: BRIEFS,
        fit_quality: 'strong',
        model_call_count: 3,
      },
      question: 'q',
      onEvent: () => {},
    })

    // Returning would retry forever against an endpoint that spends allowance.
    expect(() => capturedOnError?.(new Error('boom'))).toThrow()
  })
})
