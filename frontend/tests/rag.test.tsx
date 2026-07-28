// Built with Spec4 AI - https://spec4.ai
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { askRag, fetchDataset } from '../src/api/rag'
import { RagApp } from '../src/apps/rag/RagApp'

vi.mock('../src/api/rag', () => ({
  askRag: vi.fn(),
  fetchDataset: vi.fn(),
}))

const mockedAskRag = vi.mocked(askRag)
const mockedFetchDataset = vi.mocked(fetchDataset)

function renderRagApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <RagApp />
    </QueryClientProvider>,
  )
}

async function submitQuestion(question: string) {
  const user = userEvent.setup()
  const input = screen.getByPlaceholderText(/when did voyager 1 launch/i)
  await user.type(input, question)
  await user.click(screen.getByRole('button', { name: 'Ask' }))
}

describe('RagApp', () => {
  beforeEach(() => {
    mockedAskRag.mockReset()
    mockedFetchDataset.mockReset()
    mockedFetchDataset.mockResolvedValue([
      { title: 'Voyager 1', text: 'Voyager 1 launched on September 5, 1977.' },
    ])
  })

  it('renders the answer and a retrieved passage with a similarity score for a grounded response', async () => {
    mockedAskRag.mockResolvedValue({
      answer: 'Voyager 1 launched in 1977 [1].',
      retrieved_passages: [
        {
          passage_id: 'voyager-1-1',
          source_title: 'Voyager 1',
          text_excerpt: 'Voyager 1 launched on September 5, 1977.',
          similarity_score: 0.82,
        },
      ],
      status: 'grounded',
    })

    renderRagApp()
    await submitQuestion('When did Voyager 1 launch?')

    expect(await screen.findByText('Voyager 1 launched in 1977 [1].')).toBeInTheDocument()
    expect(screen.getByText(/match score: 0\.82/)).toBeInTheDocument()
    expect(screen.getByText(/Grounded in 1 retrieved passage/)).toBeInTheDocument()
  })

  it('renders the graceful no-strong-match message instead of a fabricated answer', async () => {
    mockedAskRag.mockResolvedValue({
      answer: 'No strong match found in this dataset for that question.',
      retrieved_passages: [],
      status: 'low_relevance',
    })

    renderRagApp()
    await submitQuestion("What's the best pizza topping?")

    expect(await screen.findByText(/no strong match found in this dataset/i)).toBeInTheDocument()
    expect(screen.getByText(/low confidence/i)).toBeInTheDocument()
  })
})
