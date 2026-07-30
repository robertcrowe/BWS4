// Built with Spec4 AI - https://spec4.ai
import type { ChainStep } from '../../api/chainedCalls'
import type { RunPhase, StepStatus } from './chainState'
import { stepStatuses } from './chainState'

interface ChainStepsProps {
  steps: ChainStep[]
  phase: RunPhase
}

/**
 * Both calls, described before either one runs, and tracked while they do.
 *
 * This is the feature's "the user is told upfront what each of the two calls is
 * meant to do" criterion, and its mitigation for "the user misunderstands what
 * each call's role is meant to be". Both are satisfied at `idle`, before any
 * submission — the descriptions are not a running commentary that appears once
 * work starts.
 *
 * Layout tracks the mock's `.steps` / `.step` rows, with the role description
 * carried alongside each row rather than only its label.
 */
export function ChainSteps({ steps, phase }: ChainStepsProps) {
  const statuses = stepStatuses(phase)

  return (
    <ol data-testid="chain-steps" className="space-y-2.5">
      {steps.map((step, index) => (
        <StepRow
          key={step.role}
          step={step}
          total={steps.length}
          status={statuses[index] ?? 'pending'}
        />
      ))}
    </ol>
  )
}

function StepRow({
  step,
  total,
  status,
}: {
  step: ChainStep
  total: number
  status: StepStatus
}) {
  const tone =
    status === 'failed'
      ? 'border-red-300 dark:border-red-900/70 bg-red-50/60 dark:bg-red-950/20'
      : status === 'done'
        ? 'border-emerald-300 dark:border-emerald-800/70 bg-emerald-50/50 dark:bg-emerald-950/20'
        : status === 'running'
          ? 'border-violet-300 dark:border-violet-800/70 bg-violet-50/50 dark:bg-violet-950/20'
          : 'border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950'

  return (
    <li className={`rounded-xl border ${tone} p-3.5`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-2.5 py-0.5 font-mono text-[11px] text-gray-600 dark:text-gray-400">
          Call {step.position} of {total}
        </span>
        <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{step.label}</span>
        <span className="font-mono text-[11px] text-gray-400">{step.role}</span>
        <StatusBadge status={status} />
      </div>
      <p className="mt-1.5 text-[13px] leading-relaxed text-gray-600 dark:text-gray-400">
        {step.description}
      </p>
    </li>
  )
}

function StatusBadge({ status }: { status: StepStatus }) {
  if (status === 'pending') {
    return null
  }

  if (status === 'running') {
    return (
      <span className="ml-auto flex items-center gap-1.5 font-mono text-[11px] text-violet-600 dark:text-violet-400">
        <span className="h-3 w-3 animate-spin rounded-full border-2 border-violet-200 dark:border-violet-900 border-t-violet-500" />
        running
      </span>
    )
  }

  if (status === 'failed') {
    return (
      <span className="ml-auto font-mono text-[11px] text-red-600 dark:text-red-400">failed</span>
    )
  }

  return (
    <span className="ml-auto font-mono text-[11px] text-emerald-600 dark:text-emerald-400">
      done
    </span>
  )
}
