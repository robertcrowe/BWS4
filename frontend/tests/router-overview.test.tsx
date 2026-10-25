// Built with Spec4 AI - https://spec4.ai
/**
 * The Router overview: each statement the specification requires, asserted
 * by text so a copy edit cannot silently drop one.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { RouterOverview } from '../src/apps/router/RouterOverview'
import { exampleApps } from '../src/data/example-apps'

function overview() {
  render(
    <MemoryRouter>
      <RouterOverview />
    </MemoryRouter>,
  )
  return screen.getByTestId('router-overview')
}

describe('the Router overview', () => {
  it('explains answering with the cheapest path that can answer well', () => {
    expect(overview()).toHaveTextContent('the cheapest path that can answer it well')
  })

  it('explains why the decision is a separate small call', () => {
    expect(overview()).toHaveTextContent('The decision is a separate, small call')
  })

  it('contrasts with Tool Use: the router emits a label, stops, and never sees the result', () => {
    const text = overview().textContent ?? ''
    expect(text).toContain('one model decides whether to call a tool inside its own turn')
    expect(text).toContain('the router emits a label and stops')
    expect(text).toContain('never sees the result of the route it chose')
  })

  it('contrasts with Planning Agent and ReAct Loop: no step follows the dispatch', () => {
    const text = overview().textContent ?? ''
    expect(text).toContain('one model keeps control across several steps')
    expect(text).toContain('no step follows the dispatch')
  })

  it('links each contrast to the example it names, from the catalogue', () => {
    overview()
    const route = (id: string) => exampleApps.find((app) => app.id === id)?.route
    expect(screen.getByRole('link', { name: 'the Tool-Use example' })).toHaveAttribute(
      'href',
      route('tool_use_integration'),
    )
    expect(screen.getByRole('link', { name: 'the Planning-Agent' })).toHaveAttribute(
      'href',
      route('planning_agent_example_app'),
    )
    expect(screen.getByRole('link', { name: 'ReAct-Loop' })).toHaveAttribute(
      'href',
      route('react_loop_example_app'),
    )
  })

  it('says the scores are uncalibrated self-report and names the calibrated number', () => {
    const text = overview().textContent ?? ''
    expect(text).toContain("uncalibrated self-report")
    expect(text).toContain('The one calibrated number on this page is the measured agreement rate with expected routes')
  })

  it('states plainly that routing is not a tier', () => {
    const text = overview().textContent ?? ''
    expect(text).toContain("Routing is not a tier in Spec4's pattern library")
    expect(text).toContain('a single call (tier 03) with the structured_outputs mechanism attached')
    expect(text).toContain('deterministic dispatch to paths whose tiers are already cited')
  })

  it('states the limits, with the shared cap separate from the app limit', () => {
    overview()
    const limits = screen.getByTestId('router-limits').textContent ?? ''
    expect(limits).toContain('at most 2 model-call units')
    expect(limits).toContain('1 on the deterministic route, 2 on the others')
    expect(limits).toContain('plus one Exa search on the search route')
    expect(limits).toContain('5 runs per visit')
    expect(limits).toContain("That is this app's own limit")
    expect(limits).toContain("the showcase's shared hourly cap")
    expect(limits).toContain('routers in general can choose among any number of paths')
  })
})
