// Built with Spec4 AI - https://spec4.ai
/**
 * The cost strip and the agreement panel, in their counts-only and full states.
 *
 * The rule both enforce is the same: a number that rests on fewer than five
 * observations is not shown as a rate or a typical time.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { CostStrip, RouterHistory } from '../src/api/router'
import { AgreementPanel } from '../src/apps/router/AgreementPanel'
import { CostStripView } from '../src/apps/router/CostStripView'
import { ROUTED_END, ROUTER_PRESETS } from './routerFixtures'

const SPARSE: CostStrip = ROUTED_END.cost_strip
const FULL: CostStrip = {
  ...SPARSE,
  baseline: { ...SPARSE.baseline, typical_ms: 4800, sample_size: 12 },
  notes: [SPARSE.notes[0]],
}

describe('the cost strip', () => {
  it('shows counts only for the baseline below five observations', () => {
    render(<CostStripView strip={SPARSE} />)

    expect(screen.getByTestId('baseline-time')).toHaveTextContent('counts only (n = 2)')
    expect(screen.getByText(/appears once at least 5 real search-route runs/)).toBeInTheDocument()
  })

  it('labels the baseline time typical, with its sample size, never as this run', () => {
    render(<CostStripView strip={FULL} />)

    expect(screen.getByTestId('baseline-time')).toHaveTextContent(
      'typical 4.80 s (median of 12 real search-route runs)',
    )
    expect(screen.getByTestId('measured-time')).toHaveTextContent('4.30 s (measured)')
    expect(screen.getByTestId('measured-time')).not.toHaveTextContent('4.80')
  })

  it('shows the router overhead as its own row', () => {
    render(<CostStripView strip={FULL} />)

    expect(screen.getByTestId('overhead')).toHaveTextContent('1 model call · 0.81 s')
  })

  it('says plainly when routing saved nothing', () => {
    render(<CostStripView strip={FULL} />)

    expect(screen.getByText(/routing added one call and saved nothing/i)).toBeInTheDocument()
  })

  it('shows a zero overhead explicitly on a re-run', () => {
    render(
      <CostStripView
        strip={{ ...FULL, overhead: { model_calls: 0, measured_ms: 0 }, saved_nothing: false, notes: [] }}
        rerun
      />,
    )

    expect(screen.getByTestId('overhead')).toHaveTextContent('0 model calls · 0.00 s')
    expect(screen.getByRole('columnheader', { name: /This re-run/ })).toBeInTheDocument()
  })
})

const HISTORY: RouterHistory = {
  presets: [
    { presetId: 'p1', agreed: 4, disagreed: 1, declined: 1, total: 6, rate: 4 / 6 },
    { presetId: 'p2', agreed: 2, disagreed: 0, declined: 1, total: 3, rate: null },
  ],
  overall: { presetId: null, agreed: 6, disagreed: 1, declined: 2, total: 9, rate: 6 / 9 },
  baseline: { typicalMs: 4800, sampleSize: 7, window: 50 },
  minObservations: 5,
}

describe('the agreement panel', () => {
  it('shows the overall rate above the presets', () => {
    render(<AgreementPanel history={HISTORY} presets={ROUTER_PRESETS.presets} error={null} />)

    expect(screen.getByTestId('overall-rate')).toHaveTextContent('67%')
    expect(screen.getByTestId('overall-rate')).toHaveTextContent('6 agreed of 9')
  })

  it('shows a rate only for a cell with five or more observations', () => {
    render(<AgreementPanel history={HISTORY} presets={ROUTER_PRESETS.presets} error={null} />)

    const p1 = within(screen.getByTestId('agreement-p1'))
    expect(p1.getByText('67%')).toBeInTheDocument()
    const p2 = screen.getByTestId('agreement-p2')
    expect(p2).toHaveTextContent('counts only (n = 3)')
    expect(p2).not.toHaveTextContent('%')
  })

  it('lists every preset, with zero counts for one that has no rows', () => {
    render(<AgreementPanel history={HISTORY} presets={ROUTER_PRESETS.presets} error={null} />)

    expect(screen.getAllByTestId(/^agreement-p/)).toHaveLength(6)
    expect(screen.getByTestId('agreement-p6')).toHaveTextContent('counts only (n = 0)')
  })

  it('shows counts only overall when the whole history is thin', () => {
    const thin: RouterHistory = {
      ...HISTORY,
      overall: { presetId: null, agreed: 2, disagreed: 1, declined: 0, total: 3, rate: null },
    }
    render(<AgreementPanel history={thin} presets={ROUTER_PRESETS.presets} error={null} />)

    expect(screen.getByTestId('overall-rate')).toHaveTextContent('counts only (n = 3)')
  })

  it('carries the tie-break footnote', () => {
    render(<AgreementPanel history={HISTORY} presets={ROUTER_PRESETS.presets} error={null} />)

    expect(screen.getByText(/tie-break counts as declined/)).toBeInTheDocument()
  })

  it('reports an unreadable history candidly', () => {
    render(
      <AgreementPanel
        history={undefined}
        presets={ROUTER_PRESETS.presets}
        error="The history could not be read."
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('could not be read')
  })
})
