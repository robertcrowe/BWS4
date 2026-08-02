// Built with Spec4 AI - https://spec4.ai
/**
 * The negotiation run UI, driven by a hand-fed SSE stream.
 *
 * The headline test here is `one seller's bid leaves the other column in
 * progress`. It is the only one that can tell the two implementations apart:
 * render both columns from a single state object updated on every event and
 * they will move together, the visible fan-out disappears, and *every other
 * assertion still passes* — both bids arrive, both are correct, the award is
 * right. The demo would have quietly stopped teaching the thing it exists for.
 *
 * The pure fold is tested directly rather than through the DOM wherever the
 * property is about state, which is why `runState.ts` is a module beside the
 * components and not a hook.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { startNegotiation } from '../src/api/collab'
import type { RunEvent } from '../src/api/collab'
import { CollabApp } from '../src/apps/collab/CollabApp'
import {
  applyRunEvent,
  bothBidding,
  initialRunState,
  stageStatuses,
} from '../src/apps/collab/runState'

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
  request: { text: 'REQUEST FOR QUOTATION', goods: 'tyres', baseline_requirement: '320' },
  model_calls: 0,
  declared_budget: { total: 8, negotiation: 6, explanation: 2 },
  sellers: ['meridian', 'northwind'],
}

function bid(sellerId: string, stage: string, price: number): RunEvent {
  return {
    kind: 'bid',
    stage,
    seller_id: sellerId,
    unit_price: price,
    quantity: 320,
    delivery_days: 5,
    warranty_months: 30,
    notes: `${sellerId} notes`,
    concessions_made: [],
  }
}

describe('the run state fold', () => {
  it('puts both sellers in progress the moment the RFQ lands', () => {
    const state = applyRunEvent(initialRunState(), RFQ)

    expect(bothBidding(state)).toBe(true)
    expect(state.sellerOrder).toEqual(['meridian', 'northwind'])
  })

  it('leaves the other column untouched by identity when one bid arrives', () => {
    // Identity, not just value: a fold that rebuilt every column on every event
    // would pass a value comparison while re-rendering both together.
    const before = applyRunEvent(initialRunState(), RFQ)
    const after = applyRunEvent(before, bid('meridian', 'opening_bids', 109))

    expect(after.columns.meridian.phase).toBe('opening_in')
    expect(after.columns.northwind.phase).toBe('bidding')
    expect(after.columns.northwind).toBe(before.columns.northwind)
  })

  it('leaves the surviving column intact when the other fails', () => {
    let state = applyRunEvent(initialRunState(), RFQ)
    state = applyRunEvent(state, bid('northwind', 'opening_bids', 84))
    state = applyRunEvent(state, {
      kind: 'degraded',
      stage: 'final_bids',
      seller_id: 'meridian',
      status: 'failed',
    })

    expect(state.columns.meridian.phase).toBe('failed')
    expect(state.columns.meridian.error).toBeTruthy()
    expect(state.columns.northwind.opening?.unitPrice).toBe(84)
  })

  it('separates a cap refusal from a halted run', () => {
    const capped = applyRunEvent(initialRunState(), {
      kind: 'error',
      stage: 'refused',
      code: 'usage_limit_reached',
      outcome: 'usage_limit_reached',
      message: 'no room this hour',
      remaining: 2,
      cap: 25,
      resets_at: '2026-08-01T18:00:00+00:00',
    })
    const halted = applyRunEvent(initialRunState(), {
      kind: 'error',
      stage: 'counter_offers',
      code: 'counter_offers_failed',
      message: 'the buyer broke',
    })

    expect(capped.phase).toBe('cap_refused')
    expect(capped.error?.allowance?.remaining).toBe(2)
    expect(halted.phase).toBe('halted')
    expect(halted.error?.allowance).toBeNull()
  })

  it('derives stage status from arrived events rather than a timer', () => {
    const start = stageStatuses(initialRunState())
    expect(start.every((status) => status === 'pending')).toBe(true)

    const afterRfq = stageStatuses(applyRunEvent(initialRunState(), RFQ))
    expect(afterRfq[0]).toBe('done')
    expect(afterRfq[1]).toBe('active')
  })
})

function renderApp() {
  // `IdentityCards` is a TanStack query, so the app needs a provider even
  // though nothing in these tests exercises the cards themselves.
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <CollabApp />
    </QueryClientProvider>,
  )
}

/** Start a run and hand back the sink the component registered. */
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
    'fleet_tyres_replacement',
  )
  await user.click(screen.getByRole('radio', { name: /lowest price/i }))
  await user.click(screen.getByRole('button', { name: /start negotiation/i }))

  await waitFor(() => expect(sink).toBeDefined())
  return sink as (event: RunEvent) => void
}

describe('the negotiation screen', () => {
  beforeEach(() => {
    mockedStart.mockReset()
  })

  it('states the run cost before anything is started', () => {
    renderApp()

    const cost = screen.getByTestId('declared-cost')
    expect(cost).toHaveTextContent('8 model calls')
    expect(cost).toHaveTextContent('6 negotiation')
    expect(cost).toHaveTextContent('2 post-award explanation')
  })

  it('offers no free-text input anywhere on the screen', () => {
    // The property that makes this the one injection-proof example: there is
    // nothing to type, so nothing a visitor types can reach a prompt.
    const { container } = renderApp()

    expect(container.querySelector('textarea')).toBeNull()
    expect(container.querySelector('input[type="text"]')).toBeNull()
  })

  it('shows both seller columns in progress before either bid arrives', async () => {
    const send = await startRun()

    send(RFQ)

    await waitFor(() => {
      expect(screen.getByTestId('seller-column-meridian')).toHaveAttribute(
        'data-phase',
        'bidding',
      )
    })
    expect(screen.getByTestId('seller-column-northwind')).toHaveAttribute(
      'data-phase',
      'bidding',
    )
  })

  it('updates only the column whose bid arrived', async () => {
    const send = await startRun()
    send(RFQ)
    await screen.findByTestId('seller-column-meridian')

    send(bid('meridian', 'opening_bids', 109))

    await waitFor(() => {
      expect(screen.getByTestId('seller-column-meridian')).toHaveAttribute(
        'data-phase',
        'opening_in',
      )
    })
    // The sibling is still working. This is the assertion the screen exists for.
    expect(screen.getByTestId('seller-column-northwind')).toHaveAttribute(
      'data-phase',
      'bidding',
    )
    expect(screen.getByTestId('seller-status-northwind')).toHaveTextContent('bidding')
  })

  it('keeps the surviving bid on screen when the other seller errors', async () => {
    const send = await startRun()
    send(RFQ)
    send(bid('northwind', 'opening_bids', 84))
    send({
      kind: 'degraded',
      stage: 'final_bids',
      seller_id: 'meridian',
      status: 'failed',
    })

    await waitFor(() => {
      expect(screen.getByTestId('seller-column-meridian')).toHaveAttribute(
        'data-phase',
        'failed',
      )
    })
    const survivor = screen.getByTestId('seller-column-northwind')
    expect(survivor).toHaveTextContent('84')
    expect(survivor).toHaveTextContent('northwind notes')
  })

  it('flags an award that did not reconcile rather than presenting it as sound', async () => {
    const send = await startRun()
    send(RFQ)
    send({
      kind: 'award',
      stage: 'award',
      award: {
        winner_id: 'meridian',
        per_priority_scoring: [],
        rationale: 'Meridian offered the best terms.',
        priority_references: ['price'],
        runner_up_note: 'Northwind was cheaper.',
      },
      reconciled: false,
      reconciliation_note: 'Your own scores favour northwind.',
      model_calls_used: 7,
      negotiation_stage_calls: 6,
    })

    const banner = await screen.findByTestId('reconciliation-banner')
    expect(banner).toHaveTextContent(/did not reconcile/i)
    expect(banner).toHaveTextContent('Your own scores favour northwind.')
    // The model's declared winner is still what is shown.
    expect(screen.getByTestId('award')).toHaveTextContent('Awarded to meridian')
  })
})

describe('the message log', () => {
  beforeEach(() => {
    mockedStart.mockReset()
  })

  const LOG: RunEvent = {
    kind: 'message_log',
    stage: 'message_log',
    seller_to_seller_count: 0,
    messages: [
      {
        sequence: 1,
        timestamp: '2026-08-01T16:20:03+00:00',
        sender: 'buyer',
        recipient: 'meridian',
        stage: 'rfq',
        work_item: { kind: 'text' },
      },
      {
        sequence: 2,
        timestamp: '2026-08-01T16:20:03+00:00',
        sender: 'buyer',
        recipient: 'northwind',
        stage: 'rfq',
        work_item: { kind: 'text' },
      },
      {
        sequence: 3,
        timestamp: '2026-08-01T16:20:05+00:00',
        sender: 'northwind',
        recipient: 'buyer',
        stage: 'opening_bids',
        work_item: { kind: 'data' },
      },
    ],
  }

  it('is collapsed until asked for', async () => {
    const send = await startRun()
    send(RFQ)
    send(LOG)

    await screen.findByTestId('message-log')
    expect(screen.queryByTestId('log-row-1')).toBeNull()
  })

  it('renders every envelope in sequence order with no seller-to-seller row', async () => {
    const user = userEvent.setup()
    const send = await startRun()
    send(RFQ)
    send(LOG)

    await screen.findByTestId('message-log')
    await user.click(screen.getByRole('button', { name: /show message log/i }))

    const rows = await screen.findAllByTestId(/^log-row-/)
    expect(rows).toHaveLength(3)
    expect(rows.map((row) => row.getAttribute('data-testid'))).toEqual([
      'log-row-1',
      'log-row-2',
      'log-row-3',
    ])
    // The claim the table exists to let someone check.
    for (const row of rows) {
      expect(row).toHaveAttribute('data-seller-to-seller', 'false')
    }
    expect(screen.getByTestId('opacity-check')).toHaveTextContent(
      '0 seller → seller messages',
    )
  })

  it('expands one row into its pretty-printed work item', async () => {
    const user = userEvent.setup()
    const send = await startRun()
    send(RFQ)
    send(LOG)

    await screen.findByTestId('message-log')
    await user.click(screen.getByRole('button', { name: /show message log/i }))
    const row = screen.getByTestId('log-row-3')
    await user.click(within(row).getByRole('button', { name: /show work item/i }))

    expect(await screen.findByText(/"kind": "data"/)).toBeInTheDocument()
  })
})

describe('the cap refusal', () => {
  beforeEach(() => {
    mockedStart.mockReset()
  })

  it('disables the start control and names the shared limit, not a service fault', async () => {
    const send = await startRun()
    send(RFQ)
    send(bid('northwind', 'opening_bids', 84))
    send({
      kind: 'error',
      stage: 'refused',
      code: 'usage_limit_reached',
      outcome: 'usage_limit_reached',
      message: 'The showcase-wide generation allowance is used up for this hour.',
      remaining: 0,
      cap: 25,
      resets_at: '2026-08-01T18:00:00+00:00',
    })

    const refusal = await screen.findByTestId('cap-refusal')
    expect(refusal).toHaveTextContent(/showcase-wide limit shared by every example app/i)
    expect(refusal).toHaveTextContent('0 of 25 calls left this hour')
    // By test id rather than by name: the label reads "Negotiating…" while a
    // run is in flight, so querying by text would couple this assertion to
    // whichever moment the refusal happened to arrive in.
    expect(screen.getByTestId('start-run')).toBeDisabled()

    // Results already produced stay on screen.
    expect(screen.getByTestId('seller-column-northwind')).toHaveTextContent('84')
  })
})
