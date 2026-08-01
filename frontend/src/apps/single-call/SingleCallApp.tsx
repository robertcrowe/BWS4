// Built with Spec4 AI - https://spec4.ai
import { useState } from 'react'

import type { PresetPrompt, SingleCallMode } from '../../api/singleCall'
import { MAX_PROMPT_CHARS, SingleCallRequestError } from '../../api/singleCall'
import { useSingleCall, useSingleCallPresets } from '../../api/useSingleCall'
import { ModeToggle } from './ModeToggle'
import { schemaTitleOf } from './format'
import { PresetSelector } from './PresetSelector'
import { SingleCallResultView } from './SingleCallResultView'

/**
 * The single-call example app: prompt/preset input, mode toggle, and the result
 * in whichever shape the chosen mode produces.
 *
 * Layout follows .spec4/v2/design/mock.html's `#screen-singlecall`: a
 * single-column stack of input card then result panel — unlike the RAG and
 * embeddings screens, this one has no second column, because in Structured
 * mode the result itself is already two columns wide.
 *
 * The pattern explanation is *not* here. It belongs to the screen, which
 * renders it through the shared `PatternSummary` above this component — one
 * explanation, sourced from `example-apps.ts` so the landing directory and the
 * screen cannot describe the same pattern differently. An in-app explainer card
 * existed briefly and was removed as a duplicate of it.
 */
export function SingleCallApp() {
  const presets = useSingleCallPresets()
  const call = useSingleCall()

  const [prompt, setPrompt] = useState('')
  // Which preset the current prompt text came from, or null when the visitor
  // typed it. Any edit clears this, so the request always names the source the
  // textarea is actually showing.
  const [presetId, setPresetId] = useState<string | null>(null)
  const [mode, setMode] = useState<SingleCallMode>('plain')
  const [validationError, setValidationError] = useState<string | null>(null)

  const defaultSchemaName = schemaTitleOf(presets.data?.default_response_schema) ?? 'default'

  function selectPreset(preset: PresetPrompt) {
    // The full text goes into the box: the visitor must be able to read exactly
    // what will be sent before spending a call on it.
    setPrompt(preset.prompt_text)
    setPresetId(preset.id)
    setValidationError(null)
  }

  function submit() {
    const trimmed = prompt.trim()

    // Blocked client-side before any request, per the capability's mitigation
    // for an empty submission. The server enforces it too; this only spares
    // the visitor a round trip.
    if (!trimmed && !presetId) {
      setValidationError('Please enter a prompt or choose a preset above before submitting.')
      return
    }
    if (trimmed.length > MAX_PROMPT_CHARS) {
      setValidationError(
        `That prompt is ${trimmed.length} characters — the limit is ${MAX_PROMPT_CHARS}.`,
      )
      return
    }

    setValidationError(null)
    call.mutate({ promptText: trimmed, presetPromptId: presetId, mode })
  }

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
        <h4 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">
          Choose or write a prompt
        </h4>

        {presets.isPending && (
          <p className="mb-3 text-xs text-gray-500">Loading the preset prompts…</p>
        )}
        {presets.isError && (
          // Non-blocking: presets are a convenience, and free text works
          // without them. Hiding the whole form because a chip list failed
          // would be a worse outcome than losing the chips.
          <div className="mb-3 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 p-3">
            <p className="text-xs text-gray-600 dark:text-gray-400">
              The preset prompts could not be loaded, so only free text is available.
            </p>
            <button
              type="button"
              onClick={() => void presets.refetch()}
              disabled={presets.isFetching}
              className="mt-2 rounded-md border border-gray-200 dark:border-gray-800 px-2.5 py-1 text-xs text-gray-700 dark:text-gray-300 hover:border-violet-500 disabled:opacity-50"
            >
              {presets.isFetching ? 'Retrying…' : 'Retry'}
            </button>
          </div>
        )}
        {presets.data && presets.data.presets.length > 0 && (
          <div className="mb-4">
            <PresetSelector
              presets={presets.data.presets}
              selectedId={presetId}
              onSelect={selectPreset}
              mode={mode}
              defaultSchemaName={defaultSchemaName}
              disabled={call.isPending}
            />
          </div>
        )}

        <form
          onSubmit={(event) => {
            event.preventDefault()
            // Guarded as well as disabled: a button is not the only way to
            // submit a form, and a second in-flight request would spend a
            // second unit of a shared hourly quota.
            if (!call.isPending) {
              submit()
            }
          }}
        >
          <label
            htmlFor="single-call-prompt"
            className="mb-1.5 block font-mono text-[11px] uppercase tracking-wide text-gray-500"
          >
            Prompt
          </label>
          <textarea
            id="single-call-prompt"
            rows={5}
            value={prompt}
            onChange={(event) => {
              setPrompt(event.target.value)
              // Editing makes this the visitor's own prompt, not the preset's.
              // Without this the server would send the preset's canonical text
              // while the box showed something else.
              setPresetId(null)
              if (validationError) {
                setValidationError(null)
              }
            }}
            placeholder="Write your own prompt, or pick a preset above (each labeled with its task)..."
            aria-invalid={validationError ? true : undefined}
            aria-describedby={validationError ? 'single-call-prompt-error' : undefined}
            className="w-full resize-y rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:border-violet-500 focus:outline-none"
          />

          <div className="mt-4">
            <ModeToggle mode={mode} onChange={setMode} disabled={call.isPending} />
          </div>

          <div className="mt-4 flex items-center justify-between gap-3">
            <span className="font-mono text-[11px] text-gray-400">
              {mode === 'structured'
                ? `Response must match ${activeSchemaName(presets.data?.presets, presetId, defaultSchemaName)}`
                : 'No schema — readable prose'}
            </span>
            <button
              type="submit"
              disabled={call.isPending}
              className="shrink-0 rounded-lg bg-violet-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
            >
              {call.isPending ? 'Running…' : 'Run single call'}
            </button>
          </div>
        </form>

        {validationError && (
          <p
            id="single-call-prompt-error"
            role="alert"
            className="mt-2 text-xs text-red-600 dark:text-red-400"
          >
            {validationError}
          </p>
        )}
      </section>

      {call.isPending && (
        // Deliberately indeterminate. There is exactly one round trip and no
        // observable intermediate step, so any staged animation here would be
        // invented — the same theater the tool-use screen's fake progress bar
        // was removed for.
        <p className="flex items-center gap-2.5 font-mono text-xs text-gray-500">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-300 dark:border-gray-700 border-t-violet-500" />
          Sending a single request to the shared generation service…
        </p>
      )}

      {call.isError && !validationError && <CallError error={call.error} onRetry={submit} />}

      {call.data && !call.isError && <SingleCallResultView result={call.data} />}
    </div>
  )
}

/**
 * Name the schema this submission would be held to.
 *
 * @param presets - The loaded preset set, if any.
 * @param presetId - The selected preset id, or null for free text.
 * @param defaultSchemaName - The schema free text is held to.
 * @returns The schema's display name.
 */
function activeSchemaName(
  presets: PresetPrompt[] | undefined,
  presetId: string | null,
  defaultSchemaName: string,
): string {
  const selected = presets?.find((preset) => preset.id === presetId)
  return schemaTitleOf(selected?.response_schema) ?? defaultSchemaName
}

/**
 * The `service-unavailable` state, naming which failure it was.
 *
 * A spent hourly cap and an unreachable provider both arrive as a 503 but are
 * different problems: one resets at the top of the hour and the other needs someone to
 * look at it. The backend's `code` separates them, so the retry offer is
 * withheld when retrying cannot possibly help.
 */
function CallError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const code = error instanceof SingleCallRequestError ? error.code : 'request_failed'
  const message =
    error instanceof Error ? error.message : 'The single call failed for an unknown reason.'
  const retryable = code !== 'usage_limit_reached'

  return (
    <div
      role="alert"
      className="rounded-2xl border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/30 p-4"
    >
      <p className="text-sm font-medium text-red-700 dark:text-red-300">
        {code === 'usage_limit_reached'
          ? 'The shared generation quota for this hour is spent.'
          : 'The single call did not complete.'}
      </p>
      <p className="mt-1 text-xs text-red-700/90 dark:text-red-300/90">{message}</p>
      {retryable && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-md border border-red-300 dark:border-red-800 px-2.5 py-1 text-xs text-red-700 dark:text-red-300 hover:bg-red-100 dark:hover:bg-red-900/40"
        >
          Try again
        </button>
      )}
    </div>
  )
}
