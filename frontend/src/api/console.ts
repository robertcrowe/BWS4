// Built with Spec4 AI - https://spec4.ai
export type ConsoleCapability = 'generation' | 'representation' | 'storage'

export interface UsageLimitOut {
  capability: ConsoleCapability
  /** Units consumed during the current UTC day, not since the beginning of time. */
  used: number
  cap: number
  /** The UTC date `used` is counting for; caps reset at 00:00 UTC. */
  window_start: string | null
}

export interface ServiceLogEntryOut {
  app_name: string
  capability: ConsoleCapability
  summary: string
  timestamp: string
}

export interface ConsoleStatus {
  usage_limits: UsageLimitOut[]
  log_entries: ServiceLogEntryOut[]
}

export interface ConsoleTestRequestInput {
  request_type: ConsoleCapability
  request_payload: string
}

export interface ConsoleTestRequestResult {
  status: 'ok'
  result: Record<string, unknown>
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/**
 * Fetch the framework_services_console's live usage limits and cross-app request log.
 *
 * @returns The current usage limits and most recent log entries.
 * @throws Error if the backend responds with a non-2xx status.
 */
export async function fetchConsoleStatus(): Promise<ConsoleStatus> {
  const response = await fetch(`${API_BASE_URL}/api/console/status`)

  if (!response.ok) {
    throw new Error(`Fetching the console status failed with status ${response.status}`)
  }

  return (await response.json()) as ConsoleStatus
}

/**
 * Send a manual test request through the shared generation, representation,
 * or storage capability, via the console's request tester.
 *
 * @param input - The capability to invoke and the payload to send it.
 * @returns The capability's result.
 * @throws Error if the backend responds with a non-2xx status (e.g. the
 * capability's usage cap has been reached).
 */
export async function sendConsoleTestRequest(
  input: ConsoleTestRequestInput,
): Promise<ConsoleTestRequestResult> {
  const response = await fetch(`${API_BASE_URL}/api/console/test-request`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })

  const body = (await response.json()) as ConsoleTestRequestResult | { status: string; detail: string }

  if (!response.ok) {
    throw new Error(
      'detail' in body ? body.detail : `The console test request failed with status ${response.status}`,
    )
  }

  return body as ConsoleTestRequestResult
}
