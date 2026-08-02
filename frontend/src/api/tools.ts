// Built with Spec4 AI - https://spec4.ai
export interface SearchResult {
  title: string
  summary: string
  source: string
  rank: number
  /**
   * When the page was published, as Exa reports it, or null when it could not
   * determine one.
   *
   * Shown on the card because **relevance is not recency**: Exa ranks purely
   * on relevance, so a 2023 article can out-rank a current one for a
   * time-sensitive question. Without a date on screen, a stale *page* is
   * indistinguishable from the demo answering out of stale training data —
   * which is exactly how it was read.
   */
  published_date: string | null
}

/**
 * One observable step from the backend agent loop. These reflect what the
 * model actually did — which tool it chose, what query it wrote, what came
 * back — rather than a cosmetic animation.
 */
export interface AgentStep {
  kind: 'decision' | 'tool_call' | 'tool_result' | 'answer'
  label: string
  detail: string
}

export interface SearchResponse {
  answer: string
  results: SearchResult[]
  steps: AgentStep[]
  queries: string[]
  model: string
  iterations: number
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/**
 * Run the tool-use agent loop over a visitor's question.
 *
 * The question is not sent to the search API as-is: the backend hands the
 * model a `web_search` tool schema, and the model decides whether to search
 * and writes its own query.
 *
 * @param searchQuery - The visitor's question.
 * @returns The agent's answer, its step trace, and the results it saw.
 * @throws Error if the backend responds with a non-2xx status (e.g. a usage
 * cap has been reached or the free-model chain is exhausted, per the
 * tool_use_integration failure mode).
 */
export async function searchTool(searchQuery: string): Promise<SearchResponse> {
  const response = await fetch(`${API_BASE_URL}/api/tools/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ search_query: searchQuery }),
  })

  const body = (await response.json()) as SearchResponse | { status: string; detail: string }

  if (!response.ok) {
    throw new Error(
      'detail' in body ? body.detail : `Searching failed with status ${response.status}`,
    )
  }

  return body as SearchResponse
}
