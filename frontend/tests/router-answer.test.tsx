// Built with Spec4 AI - https://spec4.ai
/**
 * The Router's answer views: each route's answer in that route's own layout,
 * labelled with its path, and a failure shown as a failure.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AnswerEvent, DecisionEvent, RouteId } from '../src/api/router'
import { AnswerPanel } from '../src/apps/router/AnswerPanel'
import { DecisionCard } from '../src/apps/router/DecisionCard'
import { ROUTED_DECISION, ROUTER_PRESETS, TEXT_ANSWER } from './routerFixtures'

const labelFor = (id: RouteId) =>
  ROUTER_PRESETS.routeDescriptions.find((route) => route.id === id)?.label ?? id

describe('the single-call wrapper', () => {
  it("renders the Single Call example's result card, labelled with the path", () => {
    const answer: AnswerEvent = {
      ...TEXT_ANSWER,
      route: 'single_call',
      route_label: 'Single call',
      text: 'Could you send the report **when you can**?',
      model: 'stub/model',
    }
    render(<AnswerPanel answer={answer} labelFor={labelFor} />)

    expect(screen.getByTestId('answer-route')).toHaveTextContent('via Single call')
    // The unchanged Single Call component, with its own test id and chrome.
    expect(screen.getByTestId('single-call-result')).toBeInTheDocument()
    expect(screen.getByText('stub/model')).toBeInTheDocument()
    // Model text goes through the shared Markdown renderer.
    expect(screen.getByText('when you can', { selector: 'strong' })).toBeInTheDocument()
  })
})

describe('the deterministic result', () => {
  it('shows the expression, the verdict and the value, and no model', () => {
    const answer: AnswerEvent = {
      ...TEXT_ANSWER,
      route: 'deterministic_evaluator',
      route_label: 'Deterministic evaluator',
      answer_kind: 'deterministic',
      text: null,
      expression: '72 km/h to m/s',
      evaluator_verdict: 'accepted',
      value_display: '20 m/s',
      model: null,
    }
    render(<AnswerPanel answer={answer} labelFor={labelFor} />)

    expect(screen.getByTestId('answer-route')).toHaveTextContent('via Deterministic evaluator')
    expect(screen.getByTestId('deterministic-expression')).toHaveTextContent('72 km/h to m/s')
    expect(screen.getByTestId('deterministic-value')).toHaveTextContent('20 m/s')
    expect(screen.getByTestId('deterministic-result')).toHaveTextContent('accepted')
    expect(screen.getByText('No generation call was made.')).toBeInTheDocument()
  })
})

describe('the search answer', () => {
  it('shows the exact query, the answer and the sources beside it', () => {
    render(<AnswerPanel answer={TEXT_ANSWER} labelFor={labelFor} />)

    expect(screen.getByTestId('answer-route')).toHaveTextContent('via Search + generate')
    expect(screen.getByTestId('search-answer')).toHaveTextContent(
      '"When is the next crewed launch to the International Space Station?"',
    )
    const sources = screen.getByRole('list', { name: 'Search sources' })
    expect(sources).toHaveTextContent('[1] Launch schedule')
    expect(sources).toHaveTextContent('2026-10-01')
    expect(screen.getByRole('link', { name: 'https://example.test/launches' })).toHaveAttribute(
      'href',
      'https://example.test/launches',
    )
  })

  it('flags citations and links the server stripped', () => {
    const answer: AnswerEvent = {
      ...TEXT_ANSWER,
      invalid_citations: [7],
      removed_urls: ['https://evil.test'],
    }
    render(<AnswerPanel answer={answer} labelFor={labelFor} />)

    expect(screen.getByTestId('citation-warning')).toHaveTextContent('[7]')
    expect(screen.getByTestId('citation-warning')).toHaveTextContent('1 link not among the sources')
  })

  it('shows a no-results notice with no answer', () => {
    const answer: AnswerEvent = {
      ...TEXT_ANSWER,
      answer_kind: 'notice',
      text: null,
      snippets: [],
      error: 'The search ran but found no usable results for this request.',
    }
    render(<AnswerPanel answer={answer} labelFor={labelFor} />)

    expect(screen.getByTestId('answer-notice')).toHaveTextContent('no usable results')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('keeps the snippet titles and links when composing failed', () => {
    const answer: AnswerEvent = {
      ...TEXT_ANSWER,
      answer_kind: 'failure',
      text: null,
      error: 'The search ran but an answer could not be composed.',
    }
    render(<AnswerPanel answer={answer} labelFor={labelFor} />)

    expect(screen.getByRole('alert')).toHaveTextContent('could not be composed')
    expect(screen.getByRole('list', { name: 'Search sources' })).toHaveTextContent(
      'Launch schedule',
    )
  })
})

describe('the retrieval answer', () => {
  const RETRIEVAL: AnswerEvent = {
    ...TEXT_ANSWER,
    route: 'retrieval',
    route_label: 'RAG over the space dataset',
    text: 'About 21.5 hours [1].',
    query: null,
    snippets: [],
    passages: [
      {
        index: 1,
        title: 'Apollo 11',
        excerpt: 'Armstrong and Aldrin spent 21.5 hours on the surface.',
        similarity: 0.712,
        cited: true,
      },
      {
        index: 2,
        title: 'Space Shuttle',
        excerpt: 'Unrelated.',
        similarity: 0.31,
        cited: false,
      },
    ],
    grounding: 'grounded',
    searches: 0,
    retrievals: 1,
  }

  it('shows the passages with title, similarity and whether each was cited', () => {
    render(<AnswerPanel answer={RETRIEVAL} labelFor={labelFor} />)

    expect(screen.getByTestId('answer-route')).toHaveTextContent('via RAG over the space dataset')
    const passages = screen.getByRole('list', { name: 'Retrieved passages' })
    expect(passages).toHaveTextContent('[1] Apollo 11')
    expect(passages).toHaveTextContent('similarity 0.71')
    expect(passages).toHaveTextContent('cited')
    expect(passages).toHaveTextContent('retrieved, not cited')
  })

  it('reports a dataset gap as a notice and still lists the passages', () => {
    const answer: AnswerEvent = {
      ...RETRIEVAL,
      answer_kind: 'notice',
      text: null,
      grounding: null,
      error: 'The space dataset does not cover this request.',
    }
    render(<AnswerPanel answer={answer} labelFor={labelFor} />)

    expect(screen.getByTestId('answer-notice')).toHaveTextContent('does not cover')
    expect(screen.getByRole('list', { name: 'Retrieved passages' })).toBeInTheDocument()
  })
})

describe('a failed route', () => {
  it('shows the error and no answer', () => {
    const answer: AnswerEvent = {
      ...TEXT_ANSWER,
      route: 'single_call',
      answer_kind: 'failure',
      text: null,
      error: 'The single-call route could not produce an answer.',
    }
    render(<AnswerPanel answer={answer} labelFor={labelFor} />)

    expect(screen.getByRole('alert')).toHaveTextContent('could not produce an answer')
    expect(screen.queryByTestId('single-call-result')).not.toBeInTheDocument()
  })
})

describe('the evaluator fallback statement', () => {
  it('appears on the decision card', () => {
    const decision: DecisionEvent = {
      ...ROUTED_DECISION,
      chosen_route: 'deterministic_evaluator',
      dispatched_route: 'single_call',
      agreement: 'misrouted',
      evaluator_fallback_note:
        'The router chose the deterministic evaluator, but the evaluator could not compute the expression, so the request was dispatched to single call.',
    }
    render(
      <DecisionCard decision={decision} labelFor={labelFor} costOrder={ROUTER_PRESETS.costOrder} />,
    )

    expect(screen.getByTestId('evaluator-fallback')).toHaveTextContent(
      'dispatched to single call',
    )
  })
})
