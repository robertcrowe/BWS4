// Built with Spec4 AI - https://spec4.ai
import { Markdown } from '../../components/Markdown'
import type { ColumnBid, ColumnState, RunState } from './runState'

/**
 * The two seller tracks, side by side and advancing independently.
 *
 * Each column reads **only its own slice** of `RunState.columns`, so a bid
 * event for one seller cannot re-render the other into a different state. That
 * is the visible fan-out this screen teaches, and it is easy to lose: render
 * both from one combined object and they complete together, even though the
 * backend genuinely ran them at the same time.
 *
 * Deliberately matched to the orchestrated app's specialist columns — same
 * two-up grid, same per-column status pill, same "the failed column stays on
 * screen" treatment — so a visitor who learned that screen needs no relearning.
 *
 * A failing seller keeps its column with its own error state rather than
 * disappearing: which contribution is *missing* is part of what the run
 * produced, and a vanished column would quietly turn a two-supplier
 * negotiation into a one-supplier one.
 */

const STATUS_COPY: Record<string, string> = {
  waiting: 'waiting',
  bidding: 'bidding…',
  opening_in: 'opening bid in',
  final_in: 'best & final in',
  failed: 'unavailable',
}

/** Props for {@link SellerColumns}. */
export interface SellerColumnsProps {
  state: RunState
}

function BidBlock({ bid, label }: { bid: ColumnBid; label: string }) {
  return (
    <div className="mt-3">
      <p className="font-mono text-[10px] uppercase tracking-wide text-gray-500">
        {label}
        {bid.reissued && (
          <span className="ml-2 rounded-full border border-amber-500/50 px-1.5 py-0.5 text-amber-600 dark:text-amber-400">
            re-issued
          </span>
        )}
      </p>
      <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <dt className="text-gray-500">Unit price</dt>
        <dd className="text-right font-mono text-gray-800 dark:text-gray-200">
          {bid.unitPrice}
        </dd>
        <dt className="text-gray-500">Quantity</dt>
        <dd className="text-right font-mono text-gray-800 dark:text-gray-200">
          {bid.quantity}
        </dd>
        <dt className="text-gray-500">Delivery</dt>
        <dd className="text-right font-mono text-gray-800 dark:text-gray-200">
          {bid.deliveryDays} days
        </dd>
        <dt className="text-gray-500">Warranty</dt>
        <dd className="text-right font-mono text-gray-800 dark:text-gray-200">
          {bid.warrantyMonths} months
        </dd>
      </dl>
      {bid.notes && <Markdown className="mt-2">{bid.notes}</Markdown>}
      {bid.concessions.length > 0 && (
        <p className="mt-1.5 text-[11px] text-emerald-700 dark:text-emerald-400">
          Conceded: {bid.concessions.join(', ')}
        </p>
      )}
    </div>
  )
}

function SellerColumn({ column }: { column: ColumnState }) {
  const working = column.phase === 'bidding'

  return (
    <div
      data-testid={`seller-column-${column.sellerId}`}
      data-phase={column.phase}
      className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-800 dark:bg-gray-950"
    >
      <div className="flex items-center gap-2">
        <strong className="text-[13px] font-semibold text-gray-900 capitalize dark:text-gray-100">
          {column.sellerId}
        </strong>
        <span
          data-testid={`seller-status-${column.sellerId}`}
          className={`ml-auto inline-flex items-center gap-1.5 font-mono text-[10px] ${
            column.phase === 'failed'
              ? 'text-red-600 dark:text-red-400'
              : working
                ? 'text-violet-600 dark:text-violet-400'
                : 'text-emerald-600 dark:text-emerald-400'
          }`}
        >
          {working && (
            <span
              aria-hidden="true"
              className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-500"
            />
          )}
          {STATUS_COPY[column.phase]}
        </span>
      </div>

      {column.error && (
        <p className="mt-3 text-xs leading-relaxed text-red-600 dark:text-red-400">
          {column.error}
        </p>
      )}

      {column.opening && <BidBlock bid={column.opening} label="Opening bid" />}

      {column.counter && (
        <div className="mt-3 rounded-lg border border-violet-500/30 bg-violet-500/5 p-2.5">
          <p className="font-mono text-[10px] uppercase tracking-wide text-violet-600 dark:text-violet-400">
            Buyer pressed on {column.counter.targeted_term}
          </p>
          <p className="mt-1 text-xs text-gray-700 dark:text-gray-300">
            {column.counter.ask}
          </p>
        </div>
      )}

      {column.final && <BidBlock bid={column.final} label="Best and final" />}

      {working && !column.opening && (
        <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
          Pricing against its own sealed constraints. It cannot see the other
          supplier&rsquo;s quote.
        </p>
      )}
    </div>
  )
}

/**
 * Render both seller tracks side by side.
 *
 * @param props - The current run state.
 * @returns The parallel columns, or null before a run starts.
 */
export function SellerColumns({ state }: SellerColumnsProps) {
  if (state.sellerOrder.length === 0) {
    return null
  }

  return (
    <section
      data-testid="seller-columns"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        The two suppliers, bidding at the same time
      </h3>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        Each column advances on its own as that supplier&rsquo;s call completes.
        Neither is given anything belonging to the other.
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {state.sellerOrder.map((sellerId) => {
          const column = state.columns[sellerId]
          return column ? <SellerColumn key={sellerId} column={column} /> : null
        })}
      </div>
    </section>
  )
}
