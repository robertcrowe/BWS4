// Built with Spec4 AI - https://spec4.ai
import { type FormEvent, useState } from 'react'

import type { ConsoleCapability, ConsoleStatus } from '../../api/console'
import { useConsoleStatusQuery, useConsoleTestRequestMutation } from '../../api/useConsole'

const CAPABILITY_LABELS: Record<ConsoleCapability, string> = {
  generation: 'Text generation',
  representation: 'Text representation',
  storage: 'Data storage / retrieval',
}

const PLACEHOLDERS: Record<ConsoleCapability, string> = {
  generation: 'Summarize how BWS4 uses Spec4 to teach agentic patterns.',
  representation: 'Voyager 1 launched in 1977 and entered interstellar space in 2012.',
  storage: 'What is the James Webb Space Telescope?',
}

type ConsoleTestRequestMutation = ReturnType<typeof useConsoleTestRequestMutation>

/**
 * framework_services_console surface: a request tester that exercises the
 * shared generation, representation, and storage capabilities directly,
 * alongside a live view of usage limits and the cross-app request log.
 */
export function ConsoleApp() {
  const [requestType, setRequestType] = useState<ConsoleCapability>('generation')
  const [payload, setPayload] = useState(PLACEHOLDERS.generation)
  const [simulatedLimit, setSimulatedLimit] = useState<ConsoleCapability | null>(null)
  const statusQuery = useConsoleStatusQuery()
  const mutation = useConsoleTestRequestMutation()

  function handleTypeChange(next: ConsoleCapability) {
    setRequestType(next)
    setPayload(PLACEHOLDERS[next])
    setSimulatedLimit(null)
    mutation.reset()
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = payload.trim()
    if (!trimmed) {
      return
    }
    setSimulatedLimit(null)
    mutation.mutate({ request_type: requestType, request_payload: trimmed })
  }

  function handleSimulateLimit() {
    mutation.reset()
    setSimulatedLimit(requestType)
  }

  return (
    <div>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
          <h4 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">Request tester</h4>

          <form onSubmit={handleSubmit}>
            <label
              className="mb-1.5 block text-xs uppercase tracking-wide text-gray-500"
              htmlFor="console-request-type"
            >
              Request type
            </label>
            <select
              id="console-request-type"
              value={requestType}
              onChange={(event) => handleTypeChange(event.target.value as ConsoleCapability)}
              className="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:border-violet-500 focus:outline-none"
            >
              <option value="generation">Text generation</option>
              <option value="representation">Text representation</option>
              <option value="storage">Data storage / retrieval</option>
            </select>

            <label
              className="mb-1.5 mt-4 block text-xs uppercase tracking-wide text-gray-500"
              htmlFor="console-request-payload"
            >
              Request payload
            </label>
            <textarea
              id="console-request-payload"
              rows={3}
              value={payload}
              onChange={(event) => setPayload(event.target.value)}
              placeholder={PLACEHOLDERS[requestType]}
              className="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:border-violet-500 focus:outline-none"
            />

            <div className="mt-4 flex flex-wrap items-center gap-2.5">
              <button
                type="submit"
                disabled={mutation.isPending}
                className="rounded-lg bg-violet-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              >
                Send request
              </button>
              <button
                type="button"
                onClick={handleSimulateLimit}
                className="rounded-lg border border-gray-200 dark:border-gray-800 px-4 py-2 text-xs text-gray-600 dark:text-gray-400 hover:border-violet-500 hover:text-gray-800 dark:hover:text-gray-200"
              >
                Simulate limit reached
              </button>
            </div>
          </form>

          <ResponseBox
            requestType={requestType}
            mutation={mutation}
            isSimulatedLimit={simulatedLimit === requestType}
          />
        </div>

        <UsageLimitsPanel status={statusQuery.data} isPending={statusQuery.isPending} isError={statusQuery.isError} />
      </div>

      <div className="mt-5 rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
        <h4 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">Recent cross-app request log</h4>
        <RequestLogTable entries={statusQuery.data?.log_entries ?? []} />
      </div>
    </div>
  )
}

function ResponseBox({
  requestType,
  mutation,
  isSimulatedLimit,
}: {
  requestType: ConsoleCapability
  mutation: ConsoleTestRequestMutation
  isSimulatedLimit: boolean
}) {
  if (isSimulatedLimit) {
    return (
      <div
        role="alert"
        className="mt-4 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400"
      >
        Simulated: the &quot;{CAPABILITY_LABELS[requestType]}&quot; capability&apos;s usage limit
        has been reached. This is the same clear-failure message every example app would see once
        a shared capability is exhausted.
      </div>
    )
  }

  if (mutation.isPending) {
    return (
      <p className="mt-4 font-mono text-xs text-gray-500">
        Sending request to shared framework services…
      </p>
    )
  }

  if (mutation.isError) {
    return (
      <div
        role="alert"
        className="mt-4 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400"
      >
        {mutation.error.message}
      </div>
    )
  }

  if (mutation.isSuccess) {
    return (
      <pre className="mt-4 overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 p-3 text-xs text-gray-700 dark:text-gray-300">
        {JSON.stringify(mutation.data.result, null, 2)}
      </pre>
    )
  }

  return (
    <p className="mt-4 text-xs text-gray-500">Response will appear here once a request is sent.</p>
  )
}

function UsageLimitsPanel({
  status,
  isPending,
  isError,
}: {
  status: ConsoleStatus | undefined
  isPending: boolean
  isError: boolean
}) {
  return (
    <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
      <h4 className="mb-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
        Usage limits (free-tier)
      </h4>
      <p className="mb-3 text-xs text-gray-600 dark:text-gray-400">
        Counters are per UTC day and reset at 00:00 UTC.
      </p>

      {isPending && <p className="text-sm text-gray-500">Loading usage limits…</p>}
      {isError && <p className="text-sm text-red-600 dark:text-red-400">Could not load usage limits.</p>}
      {status && status.usage_limits.length === 0 && (
        <p className="text-sm text-gray-500">
          No shared-service capability has been invoked yet.
        </p>
      )}

      {status?.usage_limits.map((limit) => {
        const percentUsed = Math.min(100, Math.round((limit.used / limit.cap) * 100))
        const isNearCap = percentUsed >= 85
        return (
          <div key={limit.capability} className="mb-4 last:mb-0">
            <div className="mb-1.5 flex items-center justify-between text-xs">
              <span className="text-gray-700 dark:text-gray-300">{CAPABILITY_LABELS[limit.capability]}</span>
              <span className="flex items-baseline gap-2 font-mono text-gray-500">
                {limit.window_start && (
                  <span className="text-[11px] text-gray-400 dark:text-gray-600">
                    {limit.window_start}
                  </span>
                )}
                <span>
                  {limit.used} / {limit.cap}
                </span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full border border-gray-200 dark:border-gray-800 bg-gray-200 dark:bg-gray-800">
              <div
                className={`h-full rounded-full ${
                  isNearCap
                    ? 'bg-gradient-to-r from-amber-500 dark:from-amber-400 to-red-500 dark:to-red-400'
                    : 'bg-gradient-to-r from-violet-600 dark:from-violet-400 to-blue-600 dark:to-blue-400'
                }`}
                style={{ width: `${percentUsed}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function RequestLogTable({ entries }: { entries: ConsoleStatus['log_entries'] }) {
  if (entries.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        No requests yet — try the RAG example app, or send a test request above.
      </p>
    )
  }

  return (
    <table className="w-full text-left text-xs">
      <thead>
        <tr className="text-[11px] uppercase tracking-wide text-gray-500">
          <th className="border-b border-gray-200 dark:border-gray-800 px-2 py-2">Time</th>
          <th className="border-b border-gray-200 dark:border-gray-800 px-2 py-2">App</th>
          <th className="border-b border-gray-200 dark:border-gray-800 px-2 py-2">Capability</th>
          <th className="border-b border-gray-200 dark:border-gray-800 px-2 py-2">Summary</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry, index) => (
          <tr key={`${entry.timestamp}-${index}`} className="text-gray-700 dark:text-gray-300">
            <td className="border-b border-gray-200 dark:border-gray-800/60 px-2 py-2 font-mono text-gray-500">
              {new Date(entry.timestamp).toLocaleTimeString()}
            </td>
            <td className="border-b border-gray-200 dark:border-gray-800/60 px-2 py-2">
              <span className="rounded-md border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-950 px-2 py-0.5 font-mono text-[11px] text-gray-600 dark:text-gray-400">
                {entry.app_name}
              </span>
            </td>
            <td className="border-b border-gray-200 dark:border-gray-800/60 px-2 py-2">
              {CAPABILITY_LABELS[entry.capability]}
            </td>
            <td className="border-b border-gray-200 dark:border-gray-800/60 px-2 py-2">{entry.summary}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
