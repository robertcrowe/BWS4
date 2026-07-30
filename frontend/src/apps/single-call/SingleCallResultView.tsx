// Built with Spec4 AI - https://spec4.ai
import type { SingleCallResult } from '../../api/singleCall'
import { formatRequest } from './format'

interface SingleCallResultViewProps {
  result: SingleCallResult
}

/**
 * Renders one completed call, in the shape its mode calls for.
 *
 * Three of the surface's states live here — `simple-result`,
 * `structured-result-conforming`, and `structured-result-mismatch` — and the
 * branch between the last two is `schema_conforming`, never the presence of an
 * object. That distinction is the point of the whole app: a non-conforming
 * response must not be dressed up as a successful one.
 *
 * Layout tracks .spec4/v2/design/mock.html's `.answer-card` /
 * `.structured-grid`: a meta row of tags, an amber warning banner when the
 * schema was missed, then two `<pre>` blocks side by side on wide screens and
 * stacked below 768px.
 */
export function SingleCallResultView({ result }: SingleCallResultViewProps) {
  if (result.mode === 'plain') {
    return <PlainResult result={result} />
  }
  return <StructuredResult result={result} />
}

/** Shared card chrome, tinted by outcome the way the mock's `.answer-card` variants are. */
function ResultCard({
  tone,
  children,
}: {
  tone: 'neutral' | 'warn'
  children: React.ReactNode
}) {
  const border =
    tone === 'warn'
      ? 'border-amber-300 dark:border-amber-700/70'
      : 'border-gray-200 dark:border-gray-800'
  return (
    <section
      data-testid="single-call-result"
      className={`rounded-2xl border ${border} bg-white dark:bg-gray-900 p-5`}
    >
      {children}
    </section>
  )
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 px-2.5 py-1 font-mono text-[11px] text-gray-600 dark:text-gray-400">
      {children}
    </span>
  )
}

/** `simple-result`: the plain-text answer and nothing else, per instruction 8. */
function PlainResult({ result }: { result: SingleCallResult }) {
  return (
    <ResultCard tone="neutral">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tag>
          <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
          Mode: Simple (plain text)
        </Tag>
        {/* The model that actually served this call, read off the response —
            the request walks a fallback chain, so the chain's head is a guess. */}
        <Tag>{result.model}</Tag>
      </div>
      <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-gray-700 dark:text-gray-300">
        {result.plain_text}
      </p>
      <p className="mt-4 border-t border-gray-200 dark:border-gray-800 pt-3 text-xs text-gray-500">
        One request, one response. The text above is the model's, unedited — nothing was retrieved,
        and nothing was stitched together on the way back.
      </p>
    </ResultCard>
  )
}

/**
 * `structured-result-conforming` and `structured-result-mismatch`.
 *
 * On a mismatch the response pane shows the **raw output** rather than a parsed
 * object, because there is no parsed object to show — that is exactly what
 * failed. Showing the raw text is the capability's specified
 * on_validation_failure behaviour, and it is also the more educational half:
 * seeing what "didn't conform" actually looked like teaches more than an error
 * message about it.
 */
function StructuredResult({ result }: { result: SingleCallResult }) {
  const conforming = result.schema_conforming === true
  const request = result.structured_request

  return (
    <ResultCard tone={conforming ? 'neutral' : 'warn'}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tag>
          <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
          Mode: Structured (schema-conforming)
        </Tag>
        <Tag>{result.model}</Tag>
        {conforming ? (
          <span className="rounded-full border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 px-2.5 py-1 font-mono text-[11px] text-emerald-700 dark:text-emerald-300">
            Response conforms to schema
          </span>
        ) : (
          <span className="rounded-full border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/40 px-2.5 py-1 font-mono text-[11px] text-amber-700 dark:text-amber-300">
            Schema mismatch detected
          </span>
        )}
      </div>

      {!conforming && (
        <div
          role="alert"
          className="mb-4 rounded-lg border border-amber-300 dark:border-amber-700/70 bg-amber-50 dark:bg-amber-950/30 p-3"
        >
          <p className="text-xs font-medium text-amber-800 dark:text-amber-300">
            The response did not match the requested schema.
          </p>
          <p className="mt-1 text-xs leading-relaxed text-amber-800/90 dark:text-amber-300/90">
            {result.validation_error}
          </p>
          <p className="mt-2 text-xs leading-relaxed text-amber-800/80 dark:text-amber-300/80">
            It is shown below as it arrived, not retried and not repaired. The call was validated
            server-side after the model answered, so a mismatch is reported rather than hidden —
            and nothing was re-requested, which would have spent a second unit of quota.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
        <StructuredPane title="Request submitted">
          {request ? formatRequest(request) : '(not recorded)'}
        </StructuredPane>
        <StructuredPane title={conforming ? 'Response returned' : 'Raw output returned'}>
          {conforming
            ? JSON.stringify(result.structured_object, null, 2)
            : (result.raw_output ?? '(empty response)')}
        </StructuredPane>
      </div>

      {request && (
        <details className="mt-3 text-xs text-gray-500">
          {/* Part of the request, but long — it restates the whole schema. Kept
              out of the pane above so the schema there stays readable, and kept
              on the page because "the request submitted" should mean all of it. */}
          <summary className="cursor-pointer hover:text-gray-700 dark:hover:text-gray-300">
            System instruction sent with it
          </summary>
          <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 p-3 font-mono text-[11px] leading-relaxed text-gray-600 dark:text-gray-400">
            {request.system_prompt}
          </pre>
        </details>
      )}

      <p className="mt-3 border-t border-gray-200 dark:border-gray-800 pt-3 text-xs text-gray-500">
        Still one model call. The schema rides along on the request as a{' '}
        <span className="font-mono">response_format</span> directive, and the response is validated
        against it after the fact — because not every free model honours the directive.
      </p>
    </ResultCard>
  )
}

function StructuredPane({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <h6 className="mb-2 font-mono text-[11px] uppercase tracking-wide text-gray-500">{title}</h6>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 p-3.5 font-mono text-[11.5px] leading-relaxed text-gray-700 dark:text-gray-300">
        {children}
      </pre>
    </div>
  )
}

