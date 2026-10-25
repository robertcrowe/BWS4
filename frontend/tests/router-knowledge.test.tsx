// Built with Spec4 AI - https://spec4.ai
/**
 * The Router knowledge panel renders the route-descriptions block exactly as
 * the API sent it — whitespace included — with the margin and cost order.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { KnowledgePanel } from '../src/apps/router/KnowledgePanel'
import { ROUTER_PRESETS } from './routerFixtures'

function renderPanel() {
  render(
    <KnowledgePanel
      block={ROUTER_PRESETS.routeDescriptionsBlock}
      sha256={ROUTER_PRESETS.routeDescriptionsSha256}
      routes={ROUTER_PRESETS.routeDescriptions}
      decisionMargin={ROUTER_PRESETS.decisionMargin}
      costOrder={ROUTER_PRESETS.costOrder}
    />,
  )
}

describe('the Router knowledge panel', () => {
  it('renders the block byte for byte, whitespace included', () => {
    renderPanel()

    const pre = screen.getByTestId('route-descriptions-block')
    expect(pre.tagName).toBe('PRE')
    expect(pre.textContent).toBe(ROUTER_PRESETS.routeDescriptionsBlock)
    expect(pre.textContent).toContain('arithmetic  (+')
    expect(pre.textContent).toContain('alone. \n')
  })

  it('prints the decision margin beside the descriptions', () => {
    renderPanel()

    expect(screen.getByTestId('decision-margin')).toHaveTextContent('0.15')
  })

  it('prints the cost order cheapest first, using the route labels', () => {
    renderPanel()

    expect(screen.getByTestId('cost-order')).toHaveTextContent(
      'Deterministic evaluator < Single call < RAG over the space dataset < Search + generate',
    )
  })

  it('shows the server hash so the block can be checked', () => {
    renderPanel()

    expect(screen.getByTestId('route-descriptions-sha256')).toHaveTextContent(
      ROUTER_PRESETS.routeDescriptionsSha256,
    )
  })
})
