// Built with Spec4 AI - https://spec4.ai
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SingleCallPresets, SingleCallResult } from '../src/api/singleCall'
import {
  fetchSingleCallPresets,
  runSingleCall,
  SingleCallRequestError,
} from '../src/api/singleCall'
import { SingleCallApp } from '../src/apps/single-call/SingleCallApp'
import { formatRequest, schemaTitleOf } from '../src/apps/single-call/format'
import { NavMenu } from '../src/components/NavMenu'
import { exampleApps } from '../src/data/example-apps'
import { LandingScreen } from '../src/screens/landing/LandingScreen'

vi.mock('../src/api/singleCall', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/api/singleCall')>()),
  runSingleCall: vi.fn(),
  fetchSingleCallPresets: vi.fn(),
}))

const mockedRunSingleCall = vi.mocked(runSingleCall)
const mockedFetchPresets = vi.mocked(fetchSingleCallPresets)

const CLASSIFY_SCHEMA = {
  title: 'ClassificationResult',
  type: 'object',
  properties: {
    category: { type: 'string', enum: ['bug', 'feature_request'] },
    urgency: { type: 'string', enum: ['low', 'high'] },
    reasoning: { type: 'string' },
  },
  required: ['category', 'urgency', 'reasoning'],
  additionalProperties: false,
}

const PRESETS: SingleCallPresets = {
  presets: [
    {
      id: 'classify',
      label: 'Classify a support ticket',
      intent: 'Classify',
      prompt_text:
        'Classify the following support ticket by type and urgency: "The export button does nothing."',
      response_schema: CLASSIFY_SCHEMA,
    },
    {
      id: 'summarize',
      label: 'Summarize a passage',
      intent: 'Summarize',
      prompt_text: 'Summarize the following passage in two sentences: "Webb sees infrared."',
      response_schema: { title: 'SummaryResult', type: 'object' },
    },
  ],
  preset_set_version: 'v1',
  default_response_schema: { title: 'DemoResult', type: 'object' },
}

const RESULT: SingleCallResult = {
  mode: 'plain',
  plain_text: 'A hash table maps keys to slots using a hash function.',
  structured_object: null,
  schema_conforming: null,
  model: 'groq/llama-3.3-70b-versatile',
  prompt_text: 'What is a hash table?',
  raw_output: null,
  validation_error: null,
  structured_request: null,
}

const STRUCTURED_REQUEST = {
  system_prompt: 'You return data, not prose. Respond with a single JSON object...',
  prompt_text: PRESETS.presets[0].prompt_text,
  response_schema: CLASSIFY_SCHEMA,
  schema_name: 'ClassificationResult',
}

const CONFORMING: SingleCallResult = {
  mode: 'structured',
  plain_text: null,
  structured_object: {
    category: 'bug',
    urgency: 'high',
    reasoning: 'The export button is unresponsive.',
  },
  schema_conforming: true,
  model: 'groq/openai/gpt-oss-120b',
  prompt_text: PRESETS.presets[0].prompt_text,
  raw_output: null,
  validation_error: null,
  structured_request: STRUCTURED_REQUEST,
}

const MISMATCH: SingleCallResult = {
  mode: 'structured',
  plain_text: null,
  structured_object: null,
  schema_conforming: false,
  model: 'openrouter/poolside/laguna-s-2.1:free',
  prompt_text: PRESETS.presets[0].prompt_text,
  raw_output: '{"classification": "bug", "priority": "high"}',
  validation_error:
    'The response did not match ClassificationResult -- category: Field required; urgency: Field required.',
  structured_request: STRUCTURED_REQUEST,
}

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SingleCallApp />
    </QueryClientProvider>,
  )
}

/** Render, then wait for the preset chips to arrive so the form is settled. */
async function renderAppWithPresets() {
  const rendered = renderApp()
  await screen.findByRole('button', { name: /Classify a support ticket/i })
  return rendered
}

/** Switch the mode toggle to Structured. */
async function chooseStructured(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('radio', { name: /Structured/i }))
}

// Deliberately NOT mocking ../src/data/example-apps here, unlike
// landing.test.tsx: the point of these two tests is that the real directory
// entry exists and is discoverable, which a stubbed directory could not show.
describe('the Single Call entry in the shared app directory', () => {
  it('is registered as a live entry pointing at the single-call route', () => {
    const entry = exampleApps.find((app) => app.id === 'single_call_example_app')

    expect(entry).toBeDefined()
    expect(entry?.status).toBe('live')
    expect(entry?.route).toBe('/single-call')
    // PatternSummary looks the copy up by this id; without it the screen
    // renders no pattern explanation at all. Since the in-app explainer card
    // was removed as a duplicate, this string is now the *only* place the
    // pattern is explained — including the structured-mode paragraph that
    // moved here from it.
    expect(entry?.patternSummary).toBeTruthy()
    expect(entry?.patternSummary).toMatch(/JSON Schema/i)
  })

  it('is listed on the landing page as a link to its screen', () => {
    render(
      <MemoryRouter>
        <LandingScreen />
      </MemoryRouter>,
    )

    const card = screen.getByText('Single-Call Example App').closest('a')
    expect(card).toHaveAttribute('href', '/single-call')
  })

  it('appears in the header menu without any menu-specific wiring', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <NavMenu />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: /open navigation menu/i }))

    // NavMenu maps the directory itself, so adding the entry is the whole
    // wiring. This test exists to catch the reverse: a future change that
    // stops the menu reading the shared directory.
    expect(screen.getByRole('menuitem', { name: 'Single-Call Example App' })).toHaveAttribute(
      'href',
      '/single-call',
    )
  })
})

describe('SingleCallApp', () => {
  // Several assertions here are about *how many* requests were sent, which
  // only means anything if the counter starts at zero each time.
  beforeEach(() => {
    mockedRunSingleCall.mockReset()
    mockedFetchPresets.mockReset()
    mockedFetchPresets.mockResolvedValue(PRESETS)
  })

  it('renders the prompt input, mode toggle, and submit control', () => {
    renderApp()

    expect(screen.getByLabelText('Prompt')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Simple/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Structured/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /run single call/i })).toBeInTheDocument()
  })

  it('does not explain the pattern itself — the screen does that once, above', () => {
    renderApp()

    // There was briefly a second explainer card inside the app, duplicating the
    // shared PatternSummary the screen already renders. One explanation, one
    // source: example-apps.ts.
    expect(screen.queryByText(/What is the single-call pattern\?/i)).not.toBeInTheDocument()
  })

  it('starts in Simple mode', () => {
    renderApp()

    expect(screen.getByRole('radio', { name: /Simple/i })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: /Structured/i })).toHaveAttribute(
      'aria-checked',
      'false',
    )
  })

  it('sends the prompt in plain mode and renders the response text', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue(RESULT)
    renderApp()

    await user.type(screen.getByLabelText('Prompt'), 'What is a hash table?')
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    expect(await screen.findByText(RESULT.plain_text!)).toBeInTheDocument()
    // Indexed rather than toHaveBeenCalledWith: TanStack Query appends its own
    // context object as a second argument to every mutationFn call.
    expect(mockedRunSingleCall.mock.calls[0][0]).toEqual({
      promptText: 'What is a hash table?',
      presetPromptId: null,
      mode: 'plain',
    })
  })

  it('renders a markdown response in plain mode as formatted elements', async () => {
    // The summarize preset asks the model to "list its key points", so a
    // markdown list is the shape of a *correct* answer here.
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue({
      ...RESULT,
      plain_text: 'A **hash table** maps keys to slots.\n\n- O(1) average lookup\n- Collisions need handling',
    })
    renderApp()

    await user.type(screen.getByLabelText('Prompt'), 'What is a hash table?')
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    expect((await screen.findByText('hash table')).tagName).toBe('STRONG')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('leaves structured mode’s raw output as raw text, not markdown', async () => {
    // `raw_output` is JSON the visitor is meant to read as JSON. Parsing it as
    // markdown would mangle the very thing the schema-mismatch view exists to
    // show.
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue(MISMATCH)
    renderApp()

    await user.click(screen.getByRole('radio', { name: /Structured/i }))
    await user.type(screen.getByLabelText('Prompt'), 'classify this')
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    const raw = await screen.findByText(new RegExp(MISMATCH.raw_output!.slice(1, 25)))
    expect(raw.closest('pre')).not.toBeNull()
  })

  it('names the model that actually served the response', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue({ ...RESULT, model: 'openrouter/somebody-else:free' })
    renderApp()

    await user.type(screen.getByLabelText('Prompt'), 'hi')
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    // The request walks a fallback chain, so the chain's head is a guess and
    // the response's own model field is the fact.
    expect(await screen.findByText('openrouter/somebody-else:free')).toBeInTheDocument()
  })

  it('blocks an empty submission without calling the backend', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue(RESULT)
    renderApp()

    await user.click(screen.getByRole('button', { name: /run single call/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/enter a prompt/i)
    expect(mockedRunSingleCall).not.toHaveBeenCalled()
  })

  it('blocks a whitespace-only submission too', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue(RESULT)
    renderApp()

    await user.type(screen.getByLabelText('Prompt'), '    ')
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/enter a prompt/i)
    expect(mockedRunSingleCall).not.toHaveBeenCalled()
  })

  it('sends exactly one request per submission', async () => {
    const user = userEvent.setup()
    let release: (value: SingleCallResult) => void = () => {}
    mockedRunSingleCall.mockImplementation(
      () => new Promise<SingleCallResult>((resolve) => (release = resolve)),
    )
    renderApp()

    await user.type(screen.getByLabelText('Prompt'), 'What is a hash table?')
    const submit = screen.getByRole('button', { name: /run single call/i })
    await user.click(submit)

    // The submit control is disabled while in flight, so a second click
    // cannot spend a second unit of a shared daily quota.
    expect(submit).toBeDisabled()
    await user.click(submit)
    expect(mockedRunSingleCall).toHaveBeenCalledTimes(1)

    release(RESULT)
    expect(await screen.findByText(RESULT.plain_text!)).toBeInTheDocument()
  })

  it('offers a manual retry when the provider chain fails', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockRejectedValue(
      new SingleCallRequestError('every model failed', 'generation_unavailable', 503),
    )
    renderApp()

    await user.type(screen.getByLabelText('Prompt'), 'hi')
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    expect(await screen.findByText(/did not complete/i)).toBeInTheDocument()
    const retry = screen.getByRole('button', { name: /try again/i })

    mockedRunSingleCall.mockResolvedValue(RESULT)
    await user.click(retry)

    expect(await screen.findByText(RESULT.plain_text!)).toBeInTheDocument()
  })

  it('does not offer a retry when the hourly quota is spent', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockRejectedValue(
      new SingleCallRequestError(
        "The 'generation' capability has reached its free-tier usage limit for today.",
        'usage_limit_reached',
        503,
      ),
    )
    renderApp()

    await user.type(screen.getByLabelText('Prompt'), 'hi')
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    // Retrying a spent daily cap cannot succeed until 00:00 UTC, so offering
    // the button would invite the visitor to keep failing.
    expect(await screen.findByText(/quota for this hour is spent/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })

  it('never retries automatically', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockRejectedValue(
      new SingleCallRequestError('every model failed', 'generation_unavailable', 503),
    )
    renderApp()

    await user.type(screen.getByLabelText('Prompt'), 'hi')
    await user.click(screen.getByRole('button', { name: /run single call/i }))
    await screen.findByText(/did not complete/i)

    // An automatic retry would spend a second quota unit nobody asked for,
    // and would contradict a demo whose subject is that one call was made.
    await waitFor(() => expect(mockedRunSingleCall).toHaveBeenCalledTimes(1))
  })
})

describe('the preset selector', () => {
  beforeEach(() => {
    mockedRunSingleCall.mockReset()
    mockedFetchPresets.mockReset()
    mockedFetchPresets.mockResolvedValue(PRESETS)
  })

  it('labels every preset with its intent', async () => {
    await renderAppWithPresets()

    // The capability's mitigation for preset uncertainty: chips carry their
    // intent, not just a name.
    for (const preset of PRESETS.presets) {
      const chip = screen.getByRole('button', { name: new RegExp(preset.label, 'i') })
      expect(chip).toHaveTextContent(preset.label)
      expect(chip).toHaveTextContent(preset.intent)
    }
  })

  it('puts the full preset prompt into the box, untruncated', async () => {
    const user = userEvent.setup()
    await renderAppWithPresets()

    await user.click(screen.getByRole('button', { name: /Classify a support ticket/i }))

    // Showing the whole prompt before submission is how a visitor knows what a
    // chip will spend a call on -- a preview could not satisfy that.
    expect(screen.getByLabelText('Prompt')).toHaveValue(PRESETS.presets[0].prompt_text)
  })

  it('submits the preset id rather than the text when a chip is chosen', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue(RESULT)
    await renderAppWithPresets()

    await user.click(screen.getByRole('button', { name: /Classify a support ticket/i }))
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    await waitFor(() => expect(mockedRunSingleCall).toHaveBeenCalled())
    expect(mockedRunSingleCall.mock.calls[0][0].presetPromptId).toBe('classify')
  })

  it('treats an edited preset as the visitor own prompt', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue(RESULT)
    await renderAppWithPresets()

    await user.click(screen.getByRole('button', { name: /Classify a support ticket/i }))
    await user.type(screen.getByLabelText('Prompt'), ' Also say why.')
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    await waitFor(() => expect(mockedRunSingleCall).toHaveBeenCalled())
    const sent = mockedRunSingleCall.mock.calls[0][0]
    // Critical: the server sends a preset's *canonical* text, so keeping the id
    // after an edit would send something different from what the box shows.
    expect(sent.presetPromptId).toBeNull()
    expect(sent.promptText).toContain('Also say why.')
  })

  it('names the schema a free-text structured prompt will be held to', async () => {
    const user = userEvent.setup()
    await renderAppWithPresets()

    await chooseStructured(user)

    expect(screen.getByText(/Response must match DemoResult/i)).toBeInTheDocument()
  })

  it('names the preset own schema once a chip is chosen', async () => {
    const user = userEvent.setup()
    await renderAppWithPresets()

    await chooseStructured(user)
    await user.click(screen.getByRole('button', { name: /Classify a support ticket/i }))

    expect(screen.getByText(/Response must match ClassificationResult/i)).toBeInTheDocument()
  })

  it('still allows free text when the preset list fails to load', async () => {
    const user = userEvent.setup()
    mockedFetchPresets.mockRejectedValue(new Error('presets unreachable'))
    mockedRunSingleCall.mockResolvedValue(RESULT)
    renderApp()

    // Presets are a convenience; losing them must not take the form down.
    expect(await screen.findByText(/only free text is available/i)).toBeInTheDocument()

    await user.type(screen.getByLabelText('Prompt'), 'What is a hash table?')
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    expect(await screen.findByText(RESULT.plain_text!)).toBeInTheDocument()
  })
})

describe('structured mode', () => {
  beforeEach(() => {
    mockedRunSingleCall.mockReset()
    mockedFetchPresets.mockReset()
    mockedFetchPresets.mockResolvedValue(PRESETS)
  })

  it('sends mode=structured once the toggle is switched', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue(CONFORMING)
    await renderAppWithPresets()

    await chooseStructured(user)
    await user.click(screen.getByRole('button', { name: /Classify a support ticket/i }))
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    await waitFor(() => expect(mockedRunSingleCall).toHaveBeenCalled())
    expect(mockedRunSingleCall.mock.calls[0][0].mode).toBe('structured')
  })

  it('renders the submitted request and the returned response together', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue(CONFORMING)
    await renderAppWithPresets()

    await chooseStructured(user)
    await user.click(screen.getByRole('button', { name: /Classify a support ticket/i }))
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    expect(await screen.findByText('Request submitted')).toBeInTheDocument()
    expect(screen.getByText('Response returned')).toBeInTheDocument()

    // The request pane shows the schema that was demanded...
    const request = screen.getByText(/"response_schema"/)
    expect(request).toHaveTextContent('ClassificationResult')
    expect(request).toHaveTextContent('"mode": "structured"')

    // ...and the response pane shows the validated object.
    const response = screen.getByText(/"category": "bug"/)
    expect(response).toHaveTextContent('"urgency": "high"')

    expect(screen.getByText(/Response conforms to schema/i)).toBeInTheDocument()
  })

  it('shows the system instruction that went with the request', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue(CONFORMING)
    await renderAppWithPresets()

    await chooseStructured(user)
    await user.click(screen.getByRole('button', { name: /Classify a support ticket/i }))
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    // Kept behind a disclosure so it does not crowd out the schema, but on the
    // page, because "the request submitted" should mean all of it.
    expect(await screen.findByText(/System instruction sent with it/i)).toBeInTheDocument()
    expect(screen.getByText(/You return data, not prose/i)).toBeInTheDocument()
  })

  it('renders only the plain text in Simple mode, with no request pane', async () => {
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue(RESULT)
    await renderAppWithPresets()

    await user.type(screen.getByLabelText('Prompt'), 'What is a hash table?')
    await user.click(screen.getByRole('button', { name: /run single call/i }))

    expect(await screen.findByText(RESULT.plain_text!)).toBeInTheDocument()
    expect(screen.queryByText('Request submitted')).not.toBeInTheDocument()
    expect(screen.queryByText(/conforms to schema/i)).not.toBeInTheDocument()
  })
})

describe('the structured validation-failure state', () => {
  beforeEach(() => {
    mockedRunSingleCall.mockReset()
    mockedFetchPresets.mockReset()
    mockedFetchPresets.mockResolvedValue(PRESETS)
  })

  async function runMismatch() {
    const user = userEvent.setup()
    mockedRunSingleCall.mockResolvedValue(MISMATCH)
    await renderAppWithPresets()

    await chooseStructured(user)
    await user.click(screen.getByRole('button', { name: /Classify a support ticket/i }))
    await user.click(screen.getByRole('button', { name: /run single call/i }))
    await screen.findByText(/Schema mismatch detected/i)
  }

  it('flags the mismatch instead of presenting it as a success', async () => {
    await runMismatch()

    expect(screen.getByText(/Schema mismatch detected/i)).toBeInTheDocument()
    expect(screen.queryByText(/Response conforms to schema/i)).not.toBeInTheDocument()
  })

  it('shows the raw output and the validation error', async () => {
    await runMismatch()

    // Surfacing the raw output is the capability's specified
    // on_validation_failure behaviour -- and the educational half: seeing what
    // "did not conform" looked like teaches more than a message about it.
    expect(screen.getByText(MISMATCH.raw_output!)).toBeInTheDocument()
    expect(screen.getByText(/category: Field required/i)).toBeInTheDocument()
    expect(screen.getByText('Raw output returned')).toBeInTheDocument()
  })

  it('still shows the request that produced it', async () => {
    await runMismatch()

    // The side-by-side comparison is most useful precisely when it failed:
    // what was asked for, beside what came back.
    expect(screen.getByText('Request submitted')).toBeInTheDocument()
    expect(screen.getByText(/"response_schema"/)).toHaveTextContent('ClassificationResult')
  })

  it('does not retry a non-conforming response', async () => {
    await runMismatch()

    // The mechanism is explicit: surface the failure rather than silently
    // trying again. A retry would also spend a second unit of quota.
    expect(mockedRunSingleCall).toHaveBeenCalledTimes(1)
  })

  it('is not treated as a request error, so no error banner appears', async () => {
    await runMismatch()

    // A 200 with schema_conforming:false is a content finding, not a transport
    // failure -- routing it through the error branch would lose the raw output.
    expect(screen.queryByText(/did not complete/i)).not.toBeInTheDocument()
  })
})

describe('the pure display helpers', () => {
  it('reads a schema name off its JSON Schema title', () => {
    expect(schemaTitleOf(CLASSIFY_SCHEMA)).toBe('ClassificationResult')
  })

  it('returns null rather than guessing when a schema carries no title', () => {
    // The name is the schema's real identity server-side, so inventing one here
    // would let the UI claim a schema the request never named.
    expect(schemaTitleOf({ type: 'object' })).toBeNull()
    expect(schemaTitleOf(undefined)).toBeNull()
  })

  it('renders the request pane as the mode, prompt, and schema that were sent', () => {
    const rendered = JSON.parse(formatRequest(STRUCTURED_REQUEST))

    expect(rendered).toEqual({
      mode: 'structured',
      prompt: STRUCTURED_REQUEST.prompt_text,
      response_schema: CLASSIFY_SCHEMA,
    })
  })

  it('leaves the system prompt out of the request pane', () => {
    // It restates the whole schema, so inlining it would push the schema itself
    // out of view. The component discloses it separately rather than hiding it.
    expect(formatRequest(STRUCTURED_REQUEST)).not.toContain('You return data')
  })
})
