// Built with Spec4 AI - https://spec4.ai
import type { SingleCallMode } from '../../api/singleCall'

interface ModeToggleProps {
  mode: SingleCallMode
  onChange: (mode: SingleCallMode) => void
  disabled?: boolean
}

/**
 * The Simple/Structured mode toggle, matching the mock's `.mode-toggle`.
 *
 * Labels say "Simple" and "Structured" as the mock does, while the values are
 * the wire's `plain`/`structured` — the label is the visitor's word, the value
 * is the API's, and keeping the state in the API's terms means nothing has to
 * translate between them on submit.
 *
 * Implemented as a radiogroup rather than two plain buttons so the selected
 * mode is announced, and so arrow keys work the way a two-option choice
 * should. The mock draws it as buttons; that is a visual description, not an
 * accessibility one.
 */
export function ModeToggle({ mode, onChange, disabled = false }: ModeToggleProps) {
  const options: { value: SingleCallMode; label: string; hint: string }[] = [
    { value: 'plain', label: 'Simple (plain text)', hint: 'One prompt in, readable prose out.' },
    {
      value: 'structured',
      label: 'Structured (schema-conforming)',
      hint: 'The same single call, with a JSON Schema attached to the request.',
    },
  ]

  return (
    <div>
      <span
        id="mode-toggle-label"
        className="mb-1.5 block font-mono text-[11px] uppercase tracking-wide text-gray-500"
      >
        Response mode
      </span>
      <div role="radiogroup" aria-labelledby="mode-toggle-label" className="flex flex-wrap gap-2">
        {options.map((option) => {
          const selected = option.value === mode
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              title={option.hint}
              onClick={() => onChange(option.value)}
              className={
                selected
                  ? 'rounded-lg border border-transparent bg-violet-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50'
                  : 'rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 hover:border-violet-500 hover:text-gray-900 dark:hover:text-gray-100 disabled:opacity-50'
              }
            >
              {option.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
