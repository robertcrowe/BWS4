// Built with Spec4 AI - https://spec4.ai
import type { CostStrip } from '../../api/router'

function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(2)} s`
}

/**
 * `Router Cost Strip`: the route taken against a "no router" baseline.
 *
 * The route taken always shows its own measured time. The baseline's time is
 * labelled *typical*, comes with its sample size, and is never in the "this
 * run" column; until five search-route runs exist it is omitted and the note
 * says why. The router's own call is a separate row — shown as an explicit
 * zero on a re-run rather than left out.
 */
export function CostStripView({ strip, rerun = false }: { strip: CostStrip; rerun?: boolean }) {
  const { route_taken: taken, baseline, overhead } = strip
  const typical =
    baseline.typical_ms !== null
      ? `typical ${seconds(baseline.typical_ms)} (median of ${baseline.sample_size} real search-route runs)`
      : null

  return (
    <section
      aria-label="Cost strip"
      data-testid="cost-strip"
      className="rounded-lg border border-gray-200 p-3 dark:border-gray-800"
    >
      <h4 className="mb-2 font-mono text-xs uppercase tracking-wide text-gray-500">Cost strip</h4>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-left text-xs">
          <thead className="text-gray-500">
            <tr>
              <th className="py-1 pr-2 font-semibold">Resource</th>
              <th className="py-1 pr-2 font-semibold">
                {rerun ? 'This re-run' : 'This run'} · {strip.route_label}
              </th>
              <th className="py-1 font-semibold">“No router” baseline (search + generate)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-800">
            <tr>
              <td className="py-1 pr-2">Model calls (routed path)</td>
              <td className="py-1 pr-2">{taken.model_calls}</td>
              <td className="py-1">{baseline.model_calls}</td>
            </tr>
            <tr>
              <td className="py-1 pr-2">Searches</td>
              <td className="py-1 pr-2">{taken.searches}</td>
              <td className="py-1">{baseline.searches}</td>
            </tr>
            <tr>
              <td className="py-1 pr-2">Retrievals</td>
              <td className="py-1 pr-2">{taken.retrievals}</td>
              <td className="py-1">{baseline.retrievals}</td>
            </tr>
            <tr>
              <td className="py-1 pr-2">Routed path time</td>
              <td className="py-1 pr-2" data-testid="measured-time">
                {seconds(taken.measured_ms)} (measured)
              </td>
              <td className="py-1" data-testid="baseline-time">
                {typical ?? (
                  <span className="text-gray-500">
                    counts only (n = {baseline.sample_size})
                  </span>
                )}
              </td>
            </tr>
            <tr>
              <td className="py-1 pr-2 font-semibold">Router overhead (separate)</td>
              <td className="py-1 pr-2" data-testid="overhead">
                {overhead.model_calls} model call{overhead.model_calls === 1 ? '' : 's'} ·{' '}
                {seconds(overhead.measured_ms)}
              </td>
              <td className="py-1">—</td>
            </tr>
          </tbody>
        </table>
      </div>
      {strip.notes.length > 0 && (
        <ul className="mt-2 grid gap-1 text-xs text-gray-600 dark:text-gray-400">
          {strip.notes.map((note) => (
            <li key={note} data-testid="cost-note">
              {note}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-xs text-gray-500">
        Baseline time is a typical value from past runs, never this run’s time.
      </p>
    </section>
  )
}
