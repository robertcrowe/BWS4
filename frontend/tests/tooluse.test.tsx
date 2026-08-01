// Built with Spec4 AI - https://spec4.ai
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { searchTool } from '../src/api/tools'
import { ToolUseApp } from '../src/apps/tooluse/ToolUseApp'

vi.mock('../src/api/tools', () => ({
  searchTool: vi.fn(),
}))

const mockedSearchTool = vi.mocked(searchTool)

function renderToolUseApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToolUseApp />
    </QueryClientProvider>,
  )
}

async function submitQuery(query: string) {
  const user = userEvent.setup()
  const input = screen.getByPlaceholderText(/what's the latest spec4 release/i)
  await user.type(input, query)
  await user.click(screen.getByRole('button', { name: 'Run agent' }))
}

describe('ToolUseApp', () => {
  beforeEach(() => {
    mockedSearchTool.mockReset()
  })

  it('renders the agent answer, its trace, and the sources it saw', async () => {
    mockedSearchTool.mockResolvedValue({
      answer: 'The latest Spec4 release is v0.9, which adds agent composition.',
      model: 'openrouter/nvidia/some-model:free',
      iterations: 2,
      queries: ['Spec4 latest release changelog'],
      steps: [
        {
          kind: 'tool_call',
          label: 'Called web_search (#1)',
          detail: 'Spec4 latest release changelog',
        },
        { kind: 'tool_result', label: 'Received 2 result(s)', detail: 'Spec4 v0.9' },
        { kind: 'answer', label: 'Answered', detail: 'Model answered from the results.' },
      ],
      results: [
        {
          title: 'Spec4 v0.9 — Agent Composition Update',
          summary: 'Adds first-class support for composing multiple example-app agents.',
          source: 'spec4.dev/changelog',
          rank: 1,
        },
        {
          title: 'Spec4 Release Notes Archive',
          summary: 'Full history of Spec4 releases.',
          source: 'github.com/spec4/spec4',
          rank: 2,
        },
      ],
    })

    renderToolUseApp()
    await submitQuery('What is the latest Spec4 release?')

    expect(
      await screen.findByText(/The latest Spec4 release is v0\.9/),
    ).toBeInTheDocument()

    // The trace shows the model's own decisions, not a fixed animation.
    expect(screen.getByText('Called web_search (#1)')).toBeInTheDocument()
    expect(screen.getByText('Received 2 result(s)')).toBeInTheDocument()
    expect(screen.getByText(/query written by the model/i)).toBeInTheDocument()
    // The model's query shows up twice by design: once in the trace step and
    // once on the routing line above the answer.
    expect(screen.getAllByText(/Spec4 latest release changelog/)).toHaveLength(2)

    expect(screen.getByText('[1] Spec4 v0.9 — Agent Composition Update')).toBeInTheDocument()
    expect(screen.getByText('[2] Spec4 Release Notes Archive')).toBeInTheDocument()
    expect(screen.getByText(/Source: spec4\.dev\/changelog/)).toBeInTheDocument()
  })

  it('renders a markdown answer as formatted elements even though the prompt forbade it', async () => {
    // `agent_v1.md` says "no markdown formatting". Models disregard it, and
    // when they comply the renderer is a no-op — so this is about being robust
    // to the model, not about changing what we ask for.
    mockedSearchTool.mockResolvedValue({
      answer: 'The latest release is **v0.9**.',
      model: 'openrouter/nvidia/some-model:free',
      iterations: 1,
      queries: [],
      steps: [],
      results: [],
    })

    renderToolUseApp()
    await submitQuery('What is the latest Spec4 release?')

    expect((await screen.findByText('v0.9')).tagName).toBe('STRONG')
  })

  it('makes it visible when the model chose not to call the search tool', async () => {
    mockedSearchTool.mockResolvedValue({
      answer: '17 times 24 is 408.',
      model: 'openrouter/nvidia/some-model:free',
      iterations: 1,
      queries: [],
      steps: [
        { kind: 'answer', label: 'Answered', detail: 'Model answered from its own knowledge.' },
      ],
      results: [],
    })

    renderToolUseApp()
    await submitQuery('What is 17 times 24?')

    expect(await screen.findByText('17 times 24 is 408.')).toBeInTheDocument()
    expect(screen.getByText(/answered without calling the search tool/i)).toBeInTheDocument()
    expect(screen.queryByText(/query written by the model/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Sources the agent saw/i)).not.toBeInTheDocument()
  })

  it('renders the clear unavailable message when the agent reports a mocked failure', async () => {
    mockedSearchTool.mockRejectedValue(
      new Error(
        'The search tool is temporarily unavailable — it has reached its free-tier usage limit for now. Please try again later.',
      ),
    )

    renderToolUseApp()
    await submitQuery('What is the latest Spec4 release?')

    expect(await screen.findByText(/temporarily unavailable/i)).toBeInTheDocument()
    expect(screen.getByText(/agent unavailable/i)).toBeInTheDocument()
  })
})
