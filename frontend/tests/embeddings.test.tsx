// Built with Spec4 AI - https://spec4.ai
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { lazy, Suspense } from 'react'
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { PlacementResult, PresetPoint } from '../src/api/embeddings'
import { fetchPresets, placeCustomText } from '../src/api/embeddings'
import { EmbeddingsApp } from '../src/apps/embeddings/EmbeddingsApp'
import {
  buildCategoryTraces,
  buildCustomTrace,
  CATEGORY_COLORS,
  CUSTOM_TRACE_NAME,
} from '../src/apps/embeddings/plotTraces'
import { NavMenu } from '../src/components/NavMenu'
import { exampleApps } from '../src/data/example-apps'
import { LandingScreen } from '../src/screens/landing/LandingScreen'

vi.mock('../src/api/embeddings', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/api/embeddings')>()),
  fetchPresets: vi.fn(),
  placeCustomText: vi.fn(),
}))

// plotly draws to a real canvas and does not run under jsdom. Mocking at the
// SemanticPlot boundary keeps the assertions on what this app controls -- the
// traces handed to the chart -- rather than on plotly's own rendering.
const { plotSpy } = vi.hoisted(() => ({ plotSpy: vi.fn() }))

vi.mock('../src/apps/embeddings/SemanticPlot', () => ({
  SemanticPlot: (props: { presets: PresetPoint[]; customPlacement?: PlacementResult | null }) => {
    plotSpy(props)
    return <div data-testid="semantic-plot" />
  },
}))

const mockedFetchPresets = vi.mocked(fetchPresets)
const mockedPlaceCustomText = vi.mocked(placeCustomText)

const PRESETS: PresetPoint[] = [
  { label: 'dog', category: 'Animals', x: 0.1, y: -0.3 },
  { label: 'cat', category: 'Animals', x: 0.14, y: -0.28 },
  { label: 'joy', category: 'Emotions', x: 0.39, y: 0.05 },
  { label: 'database', category: 'Technology', x: -0.35, y: -0.1 },
  { label: 'pizza', category: 'Food', x: -0.12, y: 0.36 },
]

const PLACEMENT: PlacementResult = {
  point: { x: 0.12, y: -0.27 },
  text: 'kitten',
  nearest_neighbors: [
    { text: 'cat', distance: 0.2118 },
    { text: 'dog', distance: 0.4795 },
  ],
  embedding_model_version: 'sentence-transformers/all-MiniLM-L6-v2',
}

function renderEmbeddingsApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <EmbeddingsApp />
    </QueryClientProvider>,
  )
}

describe('buildCategoryTraces', () => {
  it('emits one trace per category, holding every preset exactly once', () => {
    const traces = buildCategoryTraces(PRESETS)

    expect(traces.map((trace) => trace.name)).toEqual([
      'Animals',
      'Emotions',
      'Technology',
      'Food',
    ])

    const plotted = traces.flatMap((trace) => trace.text)
    expect(plotted).toHaveLength(PRESETS.length)
    expect(new Set(plotted)).toEqual(new Set(PRESETS.map((preset) => preset.label)))
  })

  it('keeps each point’s coordinates aligned with its label', () => {
    const animals = buildCategoryTraces(PRESETS).find((trace) => trace.name === 'Animals')!

    expect(animals.x).toEqual([0.1, 0.14])
    expect(animals.y).toEqual([-0.3, -0.28])
    expect(animals.text).toEqual(['dog', 'cat'])
  })

  it('colours each category from the shared palette', () => {
    for (const trace of buildCategoryTraces(PRESETS)) {
      expect(trace.marker.color).toBe(CATEGORY_COLORS[trace.name])
    }
  })

  it('puts the source text on hover so a visitor can read any point', () => {
    const [animals] = buildCategoryTraces(PRESETS)

    expect(animals.hovertemplate).toContain('%{text}')
    expect(animals.hovertemplate).toContain('Animals')
  })

  it('falls back to a neutral colour for a category the palette does not name', () => {
    const [trace] = buildCategoryTraces([
      { label: 'quasar', category: 'Astronomy', x: 0, y: 0 },
    ])

    expect(trace.marker.color).toBeTruthy()
    expect(trace.name).toBe('Astronomy')
  })
})

describe('EmbeddingsApp', () => {
  beforeEach(() => {
    mockedFetchPresets.mockReset()
    plotSpy.mockReset()
  })

  it('renders one plotted marker per preset returned by the backend', async () => {
    mockedFetchPresets.mockResolvedValue(PRESETS)

    renderEmbeddingsApp()

    expect(await screen.findByTestId('semantic-plot')).toBeInTheDocument()

    const { presets } = plotSpy.mock.calls.at(-1)![0]
    expect(presets).toHaveLength(PRESETS.length)

    // The chart receives exactly the points the backend sent, so the marker
    // count on screen is the preset count.
    const markerCount = buildCategoryTraces(presets).reduce(
      (total, trace) => total + trace.x.length,
      0,
    )
    expect(markerCount).toBe(PRESETS.length)
  })

  it('shows the educational explanation of the embedding pattern', async () => {
    mockedFetchPresets.mockResolvedValue(PRESETS)

    renderEmbeddingsApp()

    // The explanation does not wait on the backend — it is static copy, and a
    // visitor who arrives while the plot loads should still learn what an
    // embedding is.
    expect(await screen.findByText('What is an embedding?')).toBeInTheDocument()
    expect(screen.getByText(/texts with similar meaning get similar numbers/i)).toBeInTheDocument()

    // The caveat about the projection ships with the plot it qualifies.
    await screen.findByTestId('semantic-plot')
    expect(screen.getByText(/keeps under a fifth of the original detail/i)).toBeInTheDocument()
  })

  it('summarises how many texts and categories are plotted', async () => {
    mockedFetchPresets.mockResolvedValue(PRESETS)

    renderEmbeddingsApp()

    expect(await screen.findByText('5 texts · 4 categories')).toBeInTheDocument()
  })

  it('renders a legend entry for every category colour', async () => {
    mockedFetchPresets.mockResolvedValue(PRESETS)

    renderEmbeddingsApp()

    await screen.findByTestId('semantic-plot')
    for (const category of Object.keys(CATEGORY_COLORS)) {
      expect(screen.getByText(category)).toBeInTheDocument()
    }
  })

  it('reports a clear failure instead of an empty plot when presets cannot load', async () => {
    mockedFetchPresets.mockRejectedValue(new Error('backend down'))

    renderEmbeddingsApp()

    expect(await screen.findByText(/could not load the preset examples/i)).toBeInTheDocument()
    expect(screen.queryByTestId('semantic-plot')).not.toBeInTheDocument()
  })

  it('surfaces the specific reason the request failed, not just that it did', async () => {
    // A blocked origin and a stopped backend are indistinguishable to `fetch`,
    // so the screen has to name both possibilities or the failure is
    // undiagnosable from the browser — which is exactly how a CORS origin
    // mismatch went unexplained once already.
    mockedFetchPresets.mockRejectedValue(
      new Error(
        "Could not reach the backend at http://localhost:8000. Either it isn't running, or " +
          "this page's origin (http://127.0.0.1:5173) doesn't match the backend's CORS_ORIGIN setting.",
      ),
    )

    renderEmbeddingsApp()

    expect(await screen.findByText(/doesn't match the backend's CORS_ORIGIN/i)).toBeInTheDocument()
    expect(screen.getByText(/http:\/\/127\.0\.0\.1:5173/)).toBeInTheDocument()
  })
})

describe('embeddings navigation', () => {
  const embeddings = exampleApps.find((app) => app.id === 'embeddings_example_app')

  it('is registered in the shared example app directory as a live route', () => {
    expect(embeddings).toBeDefined()
    expect(embeddings?.route).toBe('/embeddings')
    expect(embeddings?.status).toBe('live')
  })

  it('appears in the landing directory and links to its route', () => {
    const router = createMemoryRouter([{ path: '/', element: <LandingScreen /> }])
    render(<RouterProvider router={router} />)

    expect(screen.getByText('Embeddings Example App').closest('a')).toHaveAttribute(
      'href',
      '/embeddings',
    )
  })

  it('appears in the hamburger nav menu and links to its route', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <NavMenu />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: /navigation menu/i }))

    expect(screen.getByRole('menuitem', { name: /Embeddings Example App/ })).toHaveAttribute(
      'href',
      '/embeddings',
    )
  })

  it('opens the lazy-loaded screen from the landing card without throwing', async () => {
    mockedFetchPresets.mockResolvedValue(PRESETS)
    const user = userEvent.setup()

    const EmbeddingsScreen = lazy(() =>
      import('../src/screens/embeddings/EmbeddingsScreen').then((module) => ({
        default: module.EmbeddingsScreen,
      })),
    )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const router = createMemoryRouter([
      { path: '/', element: <LandingScreen /> },
      {
        path: '/embeddings',
        element: (
          <Suspense fallback={<p>Loading...</p>}>
            <EmbeddingsScreen />
          </Suspense>
        ),
      },
    ])

    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )

    await user.click(screen.getByText('Embeddings Example App'))

    expect(
      await screen.findByRole('heading', { name: 'Embeddings Example App' }),
    ).toBeInTheDocument()
    expect(await screen.findByTestId('semantic-plot')).toBeInTheDocument()
  })
})

describe('EmbeddingsApp recovery', () => {
  beforeEach(() => {
    mockedFetchPresets.mockReset()
    plotSpy.mockReset()
  })

  it('recovers when the backend comes up after the page loaded', async () => {
    // `staleTime: Infinity` stops a failed query refetching on its own, so
    // without an explicit retry a backend started late leaves a dead screen.
    mockedFetchPresets.mockRejectedValueOnce(new Error('backend down'))
    mockedFetchPresets.mockResolvedValue(PRESETS)

    const user = userEvent.setup()
    renderEmbeddingsApp()

    await screen.findByText(/could not load the preset examples/i)
    await user.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByTestId('semantic-plot')).toBeInTheDocument()
    expect(screen.queryByText(/could not load the preset examples/i)).not.toBeInTheDocument()
  })
})

describe('custom text submission', () => {
  beforeEach(() => {
    mockedFetchPresets.mockReset()
    mockedPlaceCustomText.mockReset()
    plotSpy.mockReset()
    mockedFetchPresets.mockResolvedValue(PRESETS)
  })

  async function renderReady() {
    renderEmbeddingsApp()
    await screen.findByTestId('semantic-plot')
    return userEvent.setup()
  }

  function submitButton() {
    return screen.getByRole('button', { name: /add to plot/i })
  }

  it('rejects whitespace-only input inline without touching the network', async () => {
    const user = await renderReady()

    await user.type(screen.getByLabelText(/text to place/i), '   ')
    await user.click(submitButton())

    expect(await screen.findByRole('alert')).toHaveTextContent(/enter some text/i)
    expect(mockedPlaceCustomText).not.toHaveBeenCalled()
  })

  it('rejects an empty submission without touching the network', async () => {
    const user = await renderReady()

    await user.click(submitButton())

    expect(await screen.findByRole('alert')).toHaveTextContent(/enter some text/i)
    expect(mockedPlaceCustomText).not.toHaveBeenCalled()
  })

  it('rejects over-long input client-side, before a pointless round trip', async () => {
    const user = await renderReady()

    // fireEvent-style direct set: typing 501 characters one keystroke at a
    // time is needlessly slow and tests nothing extra.
    const input = screen.getByLabelText(/text to place/i) as HTMLInputElement
    await user.click(input)
    fireEvent.change(input, { target: { value: 'a'.repeat(501) } })
    await user.click(submitButton())

    expect(await screen.findByRole('alert')).toHaveTextContent(/limit is 500/i)
    expect(mockedPlaceCustomText).not.toHaveBeenCalled()
  })

  it('adds a visually distinct point without moving any preset marker', async () => {
    mockedPlaceCustomText.mockResolvedValue(PLACEMENT)
    const user = await renderReady()

    const before = plotSpy.mock.calls.at(-1)![0]
    const presetTracesBefore = buildCategoryTraces(before.presets)

    await user.type(screen.getByLabelText(/text to place/i), 'kitten')
    await user.click(submitButton())

    await screen.findByText(/nearest presets/i)

    const after = plotSpy.mock.calls.at(-1)![0]
    expect(after.customPlacement).toEqual(PLACEMENT)

    // The mitigation this phase names: preset positions must be untouched.
    expect(buildCategoryTraces(after.presets)).toEqual(presetTracesBefore)
    expect(mockedFetchPresets).toHaveBeenCalledTimes(1)

    // Distinct on symbol, size, and colour — none shared with a preset trace.
    const custom = buildCustomTrace(PLACEMENT, '#ffffff')
    const presetMarkers = presetTracesBefore.map((trace) => trace.marker)
    expect(custom.marker.symbol).toBe('diamond')
    expect(custom.name).toBe(CUSTOM_TRACE_NAME)
    expect(presetMarkers.map((marker) => marker.color)).not.toContain(custom.marker.color)
    expect(presetMarkers.every((marker) => marker.size < custom.marker.size)).toBe(true)
  })

  it('keeps preset positions identical across repeated submissions', async () => {
    mockedPlaceCustomText.mockResolvedValue(PLACEMENT)
    const user = await renderReady()

    const baseline = buildCategoryTraces(plotSpy.mock.calls.at(-1)![0].presets)

    for (const word of ['kitten', 'espresso', 'quicksort']) {
      mockedPlaceCustomText.mockResolvedValue({ ...PLACEMENT, text: word })
      const input = screen.getByLabelText(/text to place/i)
      await user.clear(input)
      await user.type(input, word)
      await user.click(submitButton())
      await screen.findByText(new RegExp(`Nearest presets to .${word}`, 'i'))

      expect(buildCategoryTraces(plotSpy.mock.calls.at(-1)![0].presets)).toEqual(baseline)
    }

    // Never refetched: preset coordinates come from one server-side fit.
    expect(mockedFetchPresets).toHaveBeenCalledTimes(1)
  })

  it('lists the nearest presets with their distances', async () => {
    mockedPlaceCustomText.mockResolvedValue(PLACEMENT)
    const user = await renderReady()

    await user.type(screen.getByLabelText(/text to place/i), 'kitten')
    await user.click(submitButton())

    expect(await screen.findByText(/nearest presets to/i)).toBeInTheDocument()
    expect(screen.getByText('cat')).toBeInTheDocument()
    expect(screen.getByText('0.212')).toBeInTheDocument()
  })

  it('shows a non-blocking inline error with a retry that succeeds', async () => {
    mockedPlaceCustomText.mockRejectedValueOnce(new Error('The embedding model is unavailable.'))
    const user = await renderReady()

    await user.type(screen.getByLabelText(/text to place/i), 'kitten')
    await user.click(submitButton())

    expect(await screen.findByText(/embedding model is unavailable/i)).toBeInTheDocument()
    // Non-blocking: the preset plot is still on screen.
    expect(screen.getByTestId('semantic-plot')).toBeInTheDocument()

    mockedPlaceCustomText.mockResolvedValue(PLACEMENT)
    await user.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByText(/nearest presets to/i)).toBeInTheDocument()
    expect(screen.queryByText(/embedding model is unavailable/i)).not.toBeInTheDocument()
  })

  it('disables submission while a placement is in flight', async () => {
    let release: (value: PlacementResult) => void = () => {}
    mockedPlaceCustomText.mockReturnValue(
      new Promise<PlacementResult>((resolve) => {
        release = resolve
      }),
    )
    const user = await renderReady()

    await user.type(screen.getByLabelText(/text to place/i), 'kitten')
    await user.click(submitButton())

    // The race this phase flags: a second request cannot be fired while the
    // first is outstanding, so responses cannot arrive out of order.
    expect(await screen.findByRole('button', { name: /placing/i })).toBeDisabled()

    release(PLACEMENT)
    expect(await screen.findByText(/nearest presets to/i)).toBeInTheDocument()
    expect(submitButton()).toBeEnabled()
  })
})
