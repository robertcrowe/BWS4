// Built with Spec4 AI - https://spec4.ai
import type { AgreementCell, RouterHistory, RouterPreset } from '../../api/router'

/** Props for {@link AgreementPanel}. */
export interface AgreementPanelProps {
  history: RouterHistory | undefined
  presets: RouterPreset[]
  error: string | null
}

function rateText(cell: AgreementCell): string | null {
  return cell.rate === null ? null : `${Math.round(cell.rate * 100)}%`
}

function RateCell({ cell }: { cell: AgreementCell }) {
  const rate = rateText(cell)
  return rate ? (
    <span className="font-semibold">{rate}</span>
  ) : (
    <span className="text-gray-500">counts only (n = {cell.total})</span>
  )
}

/**
 * `Router Agreement Panel`: shared history of how often the router agreed.
 *
 * The overall rate sits above the six presets because it is the one calibrated
 * number on the page — the scores on each card are uncalibrated self-report.
 * Every cell, the overall one included, shows counts only until it has five
 * observations: a rate over two runs would look more meaningful than it is.
 */
export function AgreementPanel({ history, presets, error }: AgreementPanelProps) {
  return (
    <section
      aria-label="Agreement history"
      className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
    >
      <h2 className="mb-2 font-mono text-xs uppercase tracking-wide text-gray-500">
        Agreement history
      </h2>
      {error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      )}
      {!error && !history && <p className="text-sm text-gray-500">Loading history…</p>}
      {history && (
        <>
          <p data-testid="overall-rate" className="mb-3 text-sm">
            <span className="font-semibold">Overall agreement with expected routes: </span>
            <RateCell cell={history.overall} /> · {history.overall.agreed} agreed of{' '}
            {history.overall.total}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] text-left text-xs">
              <thead className="text-gray-500">
                <tr>
                  <th className="py-1 pr-2 font-semibold">Preset</th>
                  <th className="py-1 pr-2 font-semibold">Agreed</th>
                  <th className="py-1 pr-2 font-semibold">Disagreed</th>
                  <th className="py-1 pr-2 font-semibold">Declined</th>
                  <th className="py-1 font-semibold">Rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-800">
                {presets.map((preset, index) => {
                  const cell = history.presets.find((item) => item.presetId === preset.id) ?? {
                    presetId: preset.id,
                    agreed: 0,
                    disagreed: 0,
                    declined: 0,
                    total: 0,
                    rate: null,
                  }
                  return (
                    <tr key={preset.id} data-testid={`agreement-${preset.id}`}>
                      <td className="max-w-[220px] truncate py-1 pr-2" title={preset.request}>
                        {index + 1}. {preset.request}
                      </td>
                      <td className="py-1 pr-2">{cell.agreed}</td>
                      <td className="py-1 pr-2">{cell.disagreed}</td>
                      <td className="py-1 pr-2">{cell.declined}</td>
                      <td className="py-1">
                        <RateCell cell={cell} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-gray-500">
            Rate = agreed ÷ (agreed + disagreed + declined), shown once a cell has{' '}
            {history.minObservations} observations. Shared across all visitors. A low-confidence
            tie-break counts as declined even when it lands on the expected route — it earns no
            credit. Free-text runs and comparison re-runs never count.
          </p>
        </>
      )}
    </section>
  )
}
