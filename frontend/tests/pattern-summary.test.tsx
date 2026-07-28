// Built with Spec4 AI - https://spec4.ai
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { PatternSummary } from '../src/components/PatternSummary'
import { exampleApps } from '../src/data/example-apps'

describe('PatternSummary', () => {
  it('renders the summary text held in the example-app directory', () => {
    const app = exampleApps[0]

    render(<PatternSummary appId={app.id} />)

    expect(screen.getByText(app.patternSummary)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(app.patternTag))).toBeInTheDocument()
  })

  it('renders nothing for an id with no directory entry', () => {
    const { container } = render(<PatternSummary appId="not_a_real_app" />)

    expect(container).toBeEmptyDOMElement()
  })

  it('has a summary for every example app, so no screen renders a blank intro', () => {
    for (const app of exampleApps) {
      expect(app.patternSummary.trim().length).toBeGreaterThan(0)
    }
  })
})
