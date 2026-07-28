// Built with Spec4 AI - https://spec4.ai
export interface HealthResponse {
  status: string
  db: string
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/**
 * Fetch the backend's liveness/DB-connectivity status.
 *
 * @returns The parsed health response.
 * @throws Error if the backend responds with a non-2xx status.
 */
export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`)

  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`)
  }

  return (await response.json()) as HealthResponse
}
