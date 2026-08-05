// Built with Spec4 AI - https://spec4.ai
/**
 * The hop-annotation panel: badges on the right cycles, and silence otherwise.
 *
 * **The assertion that matters most is the negative one.** Annotation is
 * decorative — the model chain being down must cost a badge, never the exhibit —
 * so a run that produces no annotations must render the trace exactly as it did
 * before this panel existed: no error, no apology, no empty state. A panel that
 * rendered "annotations unavailable" would be an apology for something the
 * visitor did not ask for and cannot act on.
 *
 * The rest is that badges attach to the cycle they name, that the three source
 * variants are distinguishable by wording rather than colour alone, and that
 * the panel says plainly what these labels are: an automated reading, not a
 * provenance guarantee.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AnnotationResult, HopAnnotation } from '../src/api/react'
import { AnnotationPanel } from '../src/apps/react/AnnotationPanel'
import { applyRunEvent, initialRunState } from '../src/apps/react/runState'

function hop(overrides: Partial<HopAnnotation> = {}): HopAnnotation {
  return {
    cycle_index: 1,
    fact: 'the newest UN member',
    source: 'observation',
    supporting_cycle: 1,
    note: 'Snippet 1 of cycle 1 names it.',
    ...overrides,
  }
}

function result(overrides: Partial<AnnotationResult> = {}): AnnotationResult {
  return {
    hops: [hop()],
    all_hops_observed: true,
    observed_count: 1,
    recalled_count: 0,
    dropped: [],
    downgraded: [],
    ...overrides,
  }
}

describe('a run with no annotations', () => {
  it('renders nothing at all when annotations are absent', () => {
    // The point of the whole feature being decorative.
    const { container } = render(
      <AnnotationPanel annotations={null} exhausted={false} />,
    )

    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByTestId('react-annotation-panel')).toBeNull()
  })

  it('renders nothing when every annotation was dropped', () => {
    const { container } = render(
      <AnnotationPanel
        annotations={result({ hops: [], observed_count: 0, all_hops_observed: false })}
        exhausted={false}
      />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('shows no error state for a missing annotation', () => {
    render(<AnnotationPanel annotations={null} exhausted={false} />)

    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByText(/unavailable|failed|could not/i)).toBeNull()
  })

  it('leaves the run state annotation-free until the event arrives', () => {
    const state = initialRunState()

    expect(state.annotations).toBeNull()
  })
})

describe('badges attach to the cycle they name', () => {
  it('renders one row per hop, keyed to its cycle', () => {
    render(
      <AnnotationPanel
        annotations={result({
          hops: [
            hop({ cycle_index: 1, supporting_cycle: 1 }),
            hop({ cycle_index: 2, supporting_cycle: 2, fact: 'its highest mountain' }),
          ],
          observed_count: 2,
        })}
        exhausted={false}
      />,
    )

    expect(screen.getByTestId('react-hop-1')).toHaveTextContent('Cycle 1')
    expect(screen.getByTestId('react-hop-2')).toHaveTextContent('its highest mountain')
  })

  it('links a hop to the cycle whose observation supplied it', () => {
    render(
      <AnnotationPanel
        annotations={result({ hops: [hop({ cycle_index: 2, supporting_cycle: 1 })] })}
        exhausted={false}
      />,
    )

    const link = screen.getByTestId('react-hop-link-2')
    expect(link).toHaveAttribute('href', '#react-cycle-1')
    expect(link).toHaveTextContent('cycle 1 observation')
  })

  it('says plainly when no observation supplies a hop', () => {
    render(
      <AnnotationPanel
        annotations={result({
          hops: [hop({ source: 'model_knowledge', supporting_cycle: null })],
          observed_count: 0,
          recalled_count: 1,
          all_hops_observed: false,
        })}
        exhausted={false}
      />,
    )

    expect(screen.getByTestId('react-hop-1')).toHaveTextContent(
      /no observation in this trace supplies it/i,
    )
    expect(screen.queryByTestId('react-hop-link-1')).toBeNull()
  })
})

describe('the three source variants', () => {
  const variants: Array<[HopAnnotation['source'], RegExp]> = [
    ['observation', /observed/i],
    ['model_knowledge', /from memory/i],
    ['mixed', /observed \+ recalled/i],
  ]

  it.each(variants)('renders %s distinctly', (source, label) => {
    render(
      <AnnotationPanel
        annotations={result({
          hops: [
            hop({
              source,
              supporting_cycle: source === 'model_knowledge' ? null : 1,
            }),
          ],
        })}
        exhausted={false}
      />,
    )

    const row = screen.getByTestId('react-hop-1')
    // Distinguished by wording, not colour alone.
    expect(within(row).getByText(label)).toBeInTheDocument()
    expect(row).toHaveAttribute('data-source', source)
  })

  it('gives the three variants three different labels', () => {
    const labels = new Set<string>()
    for (const [source] of variants) {
      const { unmount } = render(
        <AnnotationPanel
          annotations={result({
            hops: [hop({ source, supporting_cycle: source === 'model_knowledge' ? null : 1 })],
          })}
          exhausted={false}
        />,
      )
      labels.add(screen.getByTestId('react-hop-1').textContent ?? '')
      unmount()
    }

    expect(labels.size).toBe(3)
  })
})

describe('what the panel claims', () => {
  it('states the derived all-hops-observed flag when it holds', () => {
    render(<AnnotationPanel annotations={result()} exhausted={false} />)

    const flag = screen.getByTestId('react-all-hops-observed')
    expect(flag).toHaveTextContent(/every hop in this run came from an observation/i)
    // It may say this only because the server derived it from its own
    // cross-checks rather than taking the model's word.
    expect(flag).toHaveTextContent(/checked against the trace/i)
  })

  it('omits the flag when a hop came from memory', () => {
    render(
      <AnnotationPanel
        annotations={result({
          hops: [hop(), hop({ cycle_index: 2, source: 'model_knowledge', supporting_cycle: null })],
          observed_count: 1,
          recalled_count: 1,
          all_hops_observed: false,
        })}
        exhausted={false}
      />,
    )

    expect(screen.queryByTestId('react-all-hops-observed')).toBeNull()
  })

  it('says these labels are a reading, not a guarantee', () => {
    render(<AnnotationPanel annotations={result()} exhausted={false} />)

    expect(
      screen.getByText(/not a verified provenance guarantee/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/nothing here verifies that the snippet supports the fact/i),
    ).toBeInTheDocument()
  })

  it('never presents a budget-exhausted run as answered', () => {
    render(
      <AnnotationPanel
        annotations={result({ all_hops_observed: false })}
        exhausted
      />,
    )

    expect(
      screen.getByRole('region', { name: /hop source annotation/i }),
    ).toHaveTextContent(/run ended without an answer/i)
    expect(screen.getByText(/they are not an answer/i)).toBeInTheDocument()
  })

  it('counts observed and recalled hops separately', () => {
    render(
      <AnnotationPanel
        annotations={result({
          hops: [hop(), hop({ cycle_index: 2, source: 'model_knowledge', supporting_cycle: null })],
          observed_count: 1,
          recalled_count: 1,
          all_hops_observed: false,
        })}
        exhausted={false}
      />,
    )

    expect(screen.getByTestId('react-annotation-observed-count')).toHaveTextContent(
      '1 hop grounded',
    )
    expect(screen.getByTestId('react-annotation-recalled-count')).toHaveTextContent(
      '1 hop recalled',
    )
  })
})

describe('the annotation event folds into the run state', () => {
  it('arrives after the terminal card and does not disturb it', () => {
    let state = initialRunState()
    state = applyRunEvent(state, {
      kind: 'final_answer',
      run_id: 'r',
      answer: 'An answer.',
      observation_cycles: [1],
      audit: { all_cited_present: true, cited: [1], unverified: [] },
      searches_used: 1,
      cycle_budget: 8,
      stub: false,
    })
    const terminalBefore = state.terminal

    state = applyRunEvent(state, { kind: 'hop_annotations', ...result() })

    expect(state.annotations?.hops).toHaveLength(1)
    // The card the visitor is already reading is untouched.
    expect(state.terminal).toBe(terminalBefore)
    expect(state.phase).toBe('complete')
  })

  it('is not treated as a terminal event', () => {
    // Annotation is neither an ending nor a reason a run ends.
    let state = initialRunState()
    state = applyRunEvent(state, { kind: 'hop_annotations', ...result() })

    expect(state.terminal).toBeNull()
    expect(state.phase).toBe('idle')
  })
})
