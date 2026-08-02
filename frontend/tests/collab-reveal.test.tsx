// Built with Spec4 AI - https://spec4.ai
/**
 * The two post-award panels, and the cache that survives navigation.
 *
 * The property worth stating: **neither panel ever shows an empty state**.
 * They arrive after six stages of waiting, so a spinner or a blank card at
 * that moment is the worst thing the screen could do. The reveal renders its
 * table from the run's own record before any narration arrives, and a
 * template-generated narration renders with a badge rather than being passed
 * off as written prose.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { startNegotiation } from '../src/api/collab'
import type { RunEvent } from '../src/api/collab'
import { CollabApp } from '../src/apps/collab/CollabApp'
import { STORAGE_KEY, loadRun, rehydrate, saveRun } from '../src/apps/collab/runCache'
import { applyRunEvent, initialRunState } from '../src/apps/collab/runState'

vi.mock('../src/api/collab', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/api/collab')>()
  return {
    ...actual,
    fetchIdentityCards: vi.fn().mockResolvedValue({ agents: [] }),
    startNegotiation: vi.fn(),
  }
})

const mockedStart = vi.mocked(startNegotiation)

const RFQ: RunEvent = {
  kind: 'quotation_request',
  stage: 'rfq',
  request: { text: 'RFQ', goods: 'laptops', baseline_requirement: '240' },
  model_calls: 0,
  declared_budget: { total: 8, negotiation: 6, explanation: 2 },
  sellers: ['meridian', 'northwind'],
}

function bid(seller: string, stage: string, price: number): RunEvent {
  return {
    kind: 'bid',
    stage,
    seller_id: seller,
    unit_price: price,
    quantity: 180,
    delivery_days: 14,
    warranty_months: 12,
    notes: `${seller} notes`,
    concessions_made: [],
  }
}

const AWARD: RunEvent = {
  kind: 'award',
  stage: 'award',
  award: {
    winner_id: 'northwind',
    per_priority_scoring: [],
    rationale: 'Cheapest overall.',
    priority_references: ['price'],
    runner_up_note: 'Meridian had the longer warranty.',
  },
  reconciled: true,
  reconciliation_note: '',
  model_calls_used: 6,
  negotiation_stage_calls: 6,
}

function revealEvent(fallback: boolean): RunEvent {
  return {
    kind: 'reveal',
    stage: 'reveal',
    fallback_generated: fallback,
    violations: fallback ? ['stance_mismatch'] : [],
    parties: [
      {
        party_id: 'northwind',
        headline: 'Held its floor on price.',
        axes: [
          {
            axis: 'price',
            stance: 'conceded',
            opening_value: 380,
            final_value: 356,
            binding_constraint: 'cost_floor',
            explanation: 'It went as far as its cost floor allowed.',
          },
        ],
      },
    ],
  }
}

const SENSITIVITY: RunEvent = {
  kind: 'sensitivity',
  stage: 'sensitivity',
  likely_winner: 'meridian',
  decisive_dimensions: ['warranty'],
  narration: 'Weighting warranty above price would likely change the result.',
  confidence: 'medium',
  caveat: 'This is a projection from the recorded bids, not a re-run.',
  fallback_generated: false,
  violations: [],
  computed: {
    original_weights: { price: 25, delivery: 25, quantity: 25, warranty: 25 },
    alternative_weights: { price: 25, delivery: 25, quantity: 25, warranty: 25 },
    alternative_label: 'Warranty over price',
    original_winner: 'northwind',
    alternative_winner: 'meridian',
    outcome: 'flipped',
    decisive_axes: ['warranty'],
  },
}

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <CollabApp />
    </QueryClientProvider>,
  )
}

async function startRun(): Promise<(event: RunEvent) => void> {
  let sink: ((event: RunEvent) => void) | undefined
  mockedStart.mockImplementation(async (options) => {
    sink = options.onEvent
    await new Promise(() => {})
  })

  const user = userEvent.setup()
  renderApp()
  await user.selectOptions(
    screen.getByLabelText(/procurement scenario/i),
    'refurbished_laptops_school',
  )
  await user.click(screen.getByRole('radio', { name: /balanced/i }))
  await user.click(screen.getByTestId('start-run'))
  await waitFor(() => expect(sink).toBeDefined())
  return sink as (event: RunEvent) => void
}

describe('the reveal panel', () => {
  beforeEach(() => {
    mockedStart.mockReset()
    window.localStorage.clear()
  })

  it('stays sealed until the award arrives', async () => {
    const send = await startRun()
    send(RFQ)
    send(bid('northwind', 'final_bids', 356))

    expect(await screen.findByTestId('reveal-sealed')).toHaveTextContent(/sealed/i)
    expect(screen.queryByTestId('reveal-table')).toBeNull()
  })

  it('renders the unsealed table before any narration arrives', async () => {
    // The property that keeps this panel from ever being blank: the table is
    // built from the run's own record, not from the explanation call.
    const send = await startRun()
    send(RFQ)
    send(bid('northwind', 'opening_bids', 380))
    send(bid('northwind', 'final_bids', 356))
    send(AWARD)

    const table = await screen.findByTestId('reveal-table')
    expect(table).toHaveTextContent('380')
    expect(table).toHaveTextContent('356')
    // No narration yet, and still no empty state.
    expect(screen.queryByTestId('reveal-narration')).toBeNull()
    expect(screen.getByTestId('reveal-panel')).toHaveTextContent(/Unsealing/i)
  })

  it('fills in the per-axis explanations when the event lands', async () => {
    const user = userEvent.setup()
    const send = await startRun()
    send(RFQ)
    send(bid('northwind', 'final_bids', 356))
    send(AWARD)
    send(revealEvent(false))

    await screen.findByTestId('reveal-narration')
    // Collapsed by default: the reveal should clarify a dense run, not add to it.
    expect(screen.queryByText(/went as far as its cost floor/i)).toBeNull()

    await user.click(screen.getByRole('button', { name: /northwind/i }))
    expect(
      await screen.findByText(/went as far as its cost floor/i),
    ).toBeInTheDocument()
  })

  it('badges a template-generated narration rather than passing it off', async () => {
    const send = await startRun()
    send(RFQ)
    send(bid('northwind', 'final_bids', 356))
    send(AWARD)
    send(revealEvent(true))

    expect(await screen.findByTestId('reveal-fallback-badge')).toHaveTextContent(
      /generated from the record/i,
    )
  })

  it('shows no badge when the narration was written', async () => {
    const send = await startRun()
    send(RFQ)
    send(bid('northwind', 'final_bids', 356))
    send(AWARD)
    send(revealEvent(false))

    await screen.findByTestId('reveal-narration')
    expect(screen.queryByTestId('reveal-fallback-badge')).toBeNull()
  })
})

describe('the sensitivity panel', () => {
  beforeEach(() => {
    mockedStart.mockReset()
    window.localStorage.clear()
  })

  it('reads as a projection and carries its caveat and confidence', async () => {
    const send = await startRun()
    send(RFQ)
    send(bid('northwind', 'final_bids', 356))
    send(AWARD)
    send(SENSITIVITY)

    const panel = await screen.findByTestId('sensitivity-panel')
    // The heading itself must not read as a settled fact.
    expect(panel).toHaveTextContent(/a projection/i)
    expect(screen.getByTestId('sensitivity-caveat')).toHaveTextContent(/not a re-run/i)
    expect(screen.getByTestId('sensitivity-confidence')).toHaveTextContent('medium')
    expect(screen.getByTestId('decisive-dimensions')).toHaveTextContent('warranty')
  })

  it('shows both weightings side by side with the computed outcome', async () => {
    const send = await startRun()
    send(RFQ)
    send(bid('northwind', 'final_bids', 356))
    send(AWARD)
    send(SENSITIVITY)

    const panel = await screen.findByTestId('sensitivity-panel')
    // The arithmetic beside the prose about it.
    expect(panel).toHaveTextContent(/As run/i)
    expect(panel).toHaveTextContent(/Warranty over price/i)
  })

  it('is absent rather than empty before the projection arrives', async () => {
    const send = await startRun()
    send(RFQ)
    send(bid('northwind', 'final_bids', 356))
    send(AWARD)

    // The reveal is up; the projection has not arrived. It renders nothing at
    // all rather than an empty card waiting to be filled.
    await waitFor(() => expect(screen.getByTestId('reveal-panel')).toBeInTheDocument())
    expect(screen.queryByTestId('sensitivity-panel')).toBeNull()
  })
})

describe('the run cache', () => {
  beforeEach(() => {
    mockedStart.mockReset()
    window.localStorage.clear()
  })

  it('round-trips a completed run through localStorage', () => {
    let state = initialRunState()
    for (const event of [
      RFQ,
      bid('northwind', 'opening_bids', 380),
      bid('northwind', 'final_bids', 356),
      AWARD,
      revealEvent(false),
      SENSITIVITY,
      {
        kind: 'message_log',
        stage: 'message_log',
        seller_to_seller_count: 0,
        messages: [
          {
            sequence: 1,
            timestamp: '2026-08-01T16:20:03+00:00',
            sender: 'buyer',
            recipient: 'northwind',
            stage: 'rfq',
            work_item: {},
          },
        ],
      } as RunEvent,
    ]) {
      state = applyRunEvent(state, event)
    }

    saveRun(state, 'refurbished_laptops_school', 'balanced')
    const cached = loadRun()

    expect(cached).not.toBeNull()
    const restored = rehydrate(cached!, initialRunState())
    expect(restored.award?.winner_id).toBe('northwind')
    expect(restored.reveal?.parties).toHaveLength(1)
    expect(restored.sensitivity?.likely_winner).toBe('meridian')
    expect(restored.messages).toHaveLength(1)
    expect(restored.phase).toBe('complete')
  })

  it('rehydrates the whole run on mount with no network call', async () => {
    let state = initialRunState()
    for (const event of [RFQ, bid('northwind', 'final_bids', 356), AWARD, SENSITIVITY]) {
      state = applyRunEvent(state, event)
    }
    saveRun(state, 'refurbished_laptops_school', 'balanced')

    renderApp()

    // The record, the award and the projection are all back without a request.
    expect(await screen.findByTestId('award')).toHaveTextContent('northwind')
    expect(screen.getByTestId('sensitivity-panel')).toBeInTheDocument()
    expect(mockedStart).not.toHaveBeenCalled()
  })

  it('ignores an entry written by an older shape rather than half-reading it', () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ version: 0, scenarioId: 'x', weightingId: 'y', state: {} }),
    )

    expect(loadRun()).toBeNull()
  })

  it('survives unreadable storage without breaking the page', () => {
    window.localStorage.setItem(STORAGE_KEY, 'not json')

    expect(loadRun()).toBeNull()
  })

  it('keeps no per-app run counter', () => {
    // This app's limit is the framework-standard hourly gate the server
    // enforces. A client-side counter would invent a limit the backend does
    // not apply — and one a private window would clear anyway.
    let state = initialRunState()
    state = applyRunEvent(state, RFQ)
    saveRun(state, 'refurbished_laptops_school', 'balanced')

    const raw = window.localStorage.getItem(STORAGE_KEY) ?? ''
    expect(raw).not.toMatch(/runsUsed|runs_used|remaining|allowance/i)
  })
})
