// Built with Spec4 AI - https://spec4.ai
/**
 * The educational surface: what the page teaches when nobody presses Start.
 *
 * **Each required disclosure gets its own assertion**, because the phase's
 * second named risk is copy that describes the pattern accurately while
 * quietly dropping one of the specific things it has to say. The presets 4–5
 * caveat and the "ReAct agents in general run any number of cycles" framing are
 * the two easiest to lose, and losing either makes the demo misleading about
 * where the pattern ends and this deployment's budget begins.
 *
 * **The quota assertions are made against the form, not the overview.** A test
 * that only checked the page as a whole would pass with the cost buried three
 * screens above the button that spends it, which is exactly what instruction 8
 * forbids. So the run control's own quota block is rendered in isolation.
 *
 * The planning cross-reference is asserted as a *router link resolving to the
 * catalogue's route*, not as the string `/react`: a hard-coded URL is the thing
 * instruction 11 rules out, and asserting the literal would let one back in.
 */
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { QuestionForm } from '../src/apps/react/QuestionForm'
import { TraceStream } from '../src/apps/react/TraceStream'
import { applyRunEvent, initialRunState } from '../src/apps/react/runState'
import { PatternOverview } from '../src/apps/react/PatternOverview'
import { ReactCrossReference } from '../src/apps/planning/ReactCrossReference'
import { exampleApps } from '../src/data/example-apps'

function renderOverview() {
  return render(
    <MemoryRouter>
      <PatternOverview />
    </MemoryRouter>,
  )
}

function renderForm(overrides: Record<string, unknown> = {}) {
  const props = {
    presets: [],
    selectedId: null,
    typed: '',
    onSelect: () => {},
    onType: () => {},
    onStart: () => {},
    onStop: () => {},
    pending: false,
    exhausted: false,
    remaining: 2,
    cap: 2,
    cycleBudget: 8,
    limitMessage: null,
    suitability: null,
    checking: false,
    checked: false,
    onQuestionBlur: () => {},
    refusal: null,
    ...overrides,
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return render(<QuestionForm {...(props as any)} />)
}

describe('the overview explains the loop itself', () => {
  it('names all three phases of the cycle', () => {
    renderOverview()
    const overview = screen.getByTestId('react-overview')

    expect(overview).toHaveTextContent(/thought/i)
    expect(overview).toHaveTextContent(/action/i)
    expect(overview).toHaveTextContent(/observation/i)
  })

  it('says the next step is chosen only after reading the previous result', () => {
    renderOverview()

    // The whole pattern in one sentence — a visitor who reads nothing else
    // should still come away with this.
    expect(screen.getByTestId('react-overview')).toHaveTextContent(
      /only then (thinks again|decides)/i,
    )
    expect(screen.getByTestId('react-overview')).toHaveTextContent(
      /second query is written only after the first result has been read/i,
    )
  })

  it('carries a heading so the region is reachable by name', () => {
    renderOverview()

    expect(
      screen.getByRole('heading', { name: /reason.act.observe loop/i }),
    ).toBeInTheDocument()
  })
})

describe('the two contrasts', () => {
  it('distinguishes ReAct from the single search decision in Tool Use', () => {
    renderOverview()
    const overview = screen.getByTestId('react-overview')

    expect(overview).toHaveTextContent(/single decision about whether to search/i)
    expect(overview).toHaveTextContent(/afresh on every cycle/i)
  })

  it('distinguishes ReAct from the plan-first Planning Agent', () => {
    renderOverview()
    const overview = screen.getByTestId('react-overview')

    expect(overview).toHaveTextContent(/fixed and shown to you for approval/i)
    expect(overview).toHaveTextContent(/no plan is shown up front/i)
    expect(overview).toHaveTextContent(/approve nothing mid-run/i)
  })

  it('links each contrast to the example it names', () => {
    renderOverview()

    const planningRoute = exampleApps.find(
      (app) => app.id === 'planning_agent_example_app',
    )?.route
    const toolUseRoute = exampleApps.find((app) => app.id === 'tool_use_integration')?.route

    expect(screen.getByTestId('react-planning-crossref')).toHaveAttribute(
      'href',
      planningRoute,
    )
    expect(screen.getByRole('link', { name: /tool-use example/i })).toHaveAttribute(
      'href',
      toolUseRoute,
    )
  })
})

describe('the presets 4-5 caveat', () => {
  it('says the model may state an early hop from its own knowledge', () => {
    renderOverview()

    expect(screen.getByTestId('react-overview')).toHaveTextContent(
      /state an early hop straight from its own knowledge/i,
    )
  })

  it('calls that correct ReAct behaviour rather than a bug', () => {
    renderOverview()
    const overview = screen.getByTestId('react-overview')

    expect(overview).toHaveTextContent(/correct.{0,20}rather than a bug/i)
    // The reason it is correct, which is the teaching content itself.
    expect(overview).toHaveTextContent(/wasting its budget/i)
    expect(overview).toHaveTextContent(/choosing where observation is required/i)
  })

  it('states the presets 1-3 guarantee', () => {
    renderOverview()

    expect(screen.getByTestId('react-overview')).toHaveTextContent(
      /presets 1 to 3 are curated so that at least one demonstration has every hop visibly coming from an observation/i,
    )
  })
})

describe('the two endings are explained before a run starts', () => {
  it('names both endings and presents exhaustion as designed', () => {
    renderOverview()
    const overview = screen.getByTestId('react-overview')

    expect(overview).toHaveTextContent(/final answer/i)
    expect(overview).toHaveTextContent(/budget-exhausted/i)
    // Not a malfunction — the point of saying it up front.
    expect(overview).toHaveTextContent(/designed outcome, not a malfunction/i)
  })

  it('warns that free-form questions are the likeliest to end that way', () => {
    renderOverview()

    expect(screen.getByTestId('react-overview')).toHaveTextContent(
      /free-form questions are the likeliest/i,
    )
  })
})

describe('the quota rationale sits next to the run control', () => {
  it('is rendered by the form, not only by the overview', () => {
    renderForm()

    // The form renders with no overview above it at all, so this can only be
    // passing because the disclosure is beside the button that spends it.
    expect(screen.queryByTestId('react-overview')).toBeNull()
    expect(screen.getByTestId('react-quota-note')).toBeInTheDocument()
  })

  it('discloses the worst-case call budget and the refund', () => {
    renderForm()
    const note = screen.getByTestId('react-quota-note')

    expect(note).toHaveTextContent(/8 search-cycle calls/i)
    expect(note).toHaveTextContent(/1 final-answer call/i)
    expect(note).toHaveTextContent(/1 post-run\s+annotation call/i)
    expect(note).toHaveTextContent(/10 in all/i)
    expect(note).toHaveTextContent(/refunds whatever it does not spend/i)
  })

  it('discloses the extra suitability call, and that presets never spend one', () => {
    renderForm()
    const note = screen.getByTestId('react-quota-note')

    expect(note).toHaveTextContent(/one suitability check/i)
    expect(note).toHaveTextContent(/curated questions never spend one/i)
  })

  it('states the two-run limit and why it is the gallery tightest', () => {
    renderForm()
    const note = screen.getByTestId('react-quota-note')

    expect(note).toHaveTextContent(/you get 2 runs/i)
    expect(note).toHaveTextContent(/tightest per-app limit/i)
    expect(note).toHaveTextContent(/search on every cycle/i)
  })

  it('says the limits are this demo choice and not a property of the pattern', () => {
    // The disclosure most easily dropped, and the one that stops a visitor
    // concluding ReAct itself is capped at eight cycles.
    renderForm()
    const note = screen.getByTestId('react-quota-note')

    expect(note).toHaveTextContent(/ReAct agents in general run any number of cycles/i)
    expect(note).toHaveTextContent(/not a property of the pattern/i)
  })

  it('never describes a visitor-settable budget', () => {
    renderForm()

    // The attached spec's 3..6 clamp is superseded; the budget is server-fixed.
    expect(screen.queryByText(/3.{0,3}6 cycles/i)).toBeNull()
    expect(screen.queryByRole('slider')).toBeNull()
  })
})

describe('the run control region is named for assistive technology', () => {
  it('gives the runs-remaining indicator an accessible name', () => {
    renderForm({ remaining: 1 })

    expect(screen.getByTestId('react-runs-remaining')).toHaveAttribute(
      'aria-label',
      'Runs remaining: 1 of 2',
    )
  })

  it('groups the preset chips under a name', () => {
    renderForm()

    expect(
      screen.getByRole('group', { name: /curated multi-hop questions/i }),
    ).toBeInTheDocument()
  })
})

describe('the assistive-technology pass', () => {
  function stream(cycleCount: number) {
    let state = applyRunEvent(initialRunState(), {
      kind: 'run_started',
      run_id: 'r',
      question: 'a multi-hop question',
      cycle_budget: 8,
      stub: false,
    })
    for (let cycle = 1; cycle <= cycleCount; cycle += 1) {
      state = applyRunEvent(state, {
        kind: 'cycle_thought',
        cycle,
        thought: `Thinking about hop ${cycle}.`,
        stub: false,
      })
      state = applyRunEvent(state, {
        kind: 'cycle_action',
        cycle,
        action_kind: 'search',
        query: `query ${cycle}`,
        rationale: '',
        stub: false,
      })
      state = applyRunEvent(state, {
        kind: 'cycle_observation',
        index: cycle,
        query: `query ${cycle}`,
        results: [
          {
            idx: 1,
            title: 'A result',
            snippet: 'A snippet.',
            url: 'https://example.org/a',
            published_date: '2026-01-01',
            truncated: false,
          },
        ],
        is_empty: false,
        status: 'ok',
        detail: null,
        truncated: false,
        stub: false,
      })
    }
    return state
  }

  it('announces one sentence per cycle rather than every partial update', () => {
    // The phase's fourth named risk: an `aria-live` on the trace itself would
    // re-read the whole thing on every one of the three mutations a cycle makes
    // — and again for each of the five snippets an observation adds.
    render(<TraceStream state={stream(2)} pending />)

    const announcer = screen.getByTestId('react-trace-announcer')
    expect(announcer).toHaveAttribute('role', 'status')
    expect(announcer.textContent).toBe('Cycle 2: observation returned with 1 results.')

    // The trace itself is a log, which assistive technology reads on request
    // rather than interrupting with.
    const trace = screen.getByRole('log', { name: /reason, act and observe cycles/i })
    expect(trace).not.toHaveAttribute('aria-live')
  })

  it('announces the ending once the run is over', () => {
    let state = stream(1)
    state = applyRunEvent(state, {
      kind: 'budget_exhausted',
      run_id: 'r',
      reason: 'cycle_budget_reached',
      unresolved: 'the second hop',
      searches_used: 8,
      cycle_budget: 8,
      stub: false,
    })

    render(<TraceStream state={state} pending={false} />)

    expect(screen.getByTestId('react-trace-announcer')).toHaveTextContent(
      /run ended without an answer/i,
    )
  })

  it('gives the cycle counter an accessible name without announcing every tick', () => {
    render(<TraceStream state={stream(3)} pending />)

    const counter = screen.getByTestId('react-cycle-counter')
    expect(counter).toHaveAttribute(
      'aria-label',
      expect.stringMatching(/search budget: search \d+ of \d+/i),
    )
    // One announcer for the run; the counter is not a second one competing
    // with it.
    expect(counter).not.toHaveAttribute('role', 'status')
    expect(counter).not.toHaveAttribute('aria-live')
  })

  it('keeps the heading levels in order down the screen', () => {
    // h1 screen title, h2 pattern panels, h3 the working surfaces. A skipped
    // level makes the page unnavigable by heading.
    const { container } = render(
      <MemoryRouter>
        <PatternOverview />
      </MemoryRouter>,
    )
    expect(container.querySelector('h2')).not.toBeNull()
    expect(container.querySelector('h1')).toBeNull()

    const trace = render(<TraceStream state={stream(1)} pending={false} />)
    expect(trace.container.querySelector('h3')).not.toBeNull()
    expect(trace.container.querySelector('h1, h2')).toBeNull()
  })
})

describe('the planning agent cross-reference', () => {
  function renderCrossReference() {
    return render(
      <MemoryRouter>
        <ReactCrossReference />
      </MemoryRouter>,
    )
  }

  it('links to the ReAct Loop route as the catalogue declares it', () => {
    renderCrossReference()

    const route = exampleApps.find((app) => app.id === 'react_loop_example_app')?.route
    expect(route).toBeTruthy()
    expect(screen.getByTestId('planning-react-link')).toHaveAttribute('href', route)
  })

  it('reads the route from the catalogue rather than a hard-coded string', () => {
    // Mutating the catalogue entry must move the link. A literal URL in the
    // component would survive this, which is what instruction 11 rules out.
    const entry = exampleApps.find((app) => app.id === 'react_loop_example_app')
    const original = entry?.route
    if (entry === undefined || original === undefined) {
      throw new Error('the ReAct entry is missing from the catalogue')
    }

    try {
      Object.assign(entry, { route: '/moved-somewhere-else' })
      renderCrossReference()
      expect(screen.getByTestId('planning-react-link')).toHaveAttribute(
        'href',
        '/moved-somewhere-else',
      )
    } finally {
      Object.assign(entry, { route: original })
    }
  })

  it('states the distinction in both directions', () => {
    renderCrossReference()
    const panel = screen.getByTestId('planning-react-crossref')

    expect(panel).toHaveTextContent(/plan-first/i)
    expect(panel).toHaveTextContent(
      /whole plan is fixed and shown to you\s+for approval before any step runs/i,
    )
    expect(panel).toHaveTextContent(/interleaved reason.act.observe/i)
    expect(panel).toHaveTextContent(/only then decides its next step/i)
    expect(panel).toHaveTextContent(/no approval asked/i)
  })

  it('is a router link rather than a page-reloading anchor', () => {
    renderCrossReference()
    const link = within(screen.getByTestId('planning-react-crossref')).getByRole('link')

    expect(link.tagName).toBe('A')
    expect(link).not.toHaveAttribute('target')
  })
})
