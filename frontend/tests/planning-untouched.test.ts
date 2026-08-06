// Built with Spec4 AI - https://spec4.ai
/**
 * The planning agent is copy-plus-one-link in the v7 revision, and this proves it.
 *
 * **The v7 phase set's first named risk is scope creep into a working app.** The
 * revision lists Planning Agent as a changed feature, which reads as licence to
 * tidy its overview component, its route or its budget while passing through.
 * v7 Phase 7's instruction 12 forbids exactly that, and a claim of "we didn't
 * touch it" is the sort of claim this project has a standing rule against
 * making unverified. So the assertions are made against **git**.
 *
 * ## The anchor is the commit before v7, not HEAD — and that was a real bug
 *
 * The first version of this file diffed against `HEAD`, which was correct only
 * while v7 sat uncommitted in the working tree. The moment the revision was
 * committed, `git diff HEAD` for these paths went empty and two assertions
 * failed — not because anything regressed, but because the test had pinned *the
 * state of the working tree at the time* rather than the invariant. That is
 * precisely the failure mode `routes.test.tsx` was written to escape: verifying
 * the moment instead of the property.
 *
 * Anchoring to `PRE_V7` states the durable claim — *the v7 revision changed
 * planning only for copy and one navigation link* — and it stays true whether
 * the work is committed, uncommitted, or committed and then built on.
 */
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const REPO_ROOT = resolve(__dirname, '../..')

/**
 * The last commit before the ReAct revision landed.
 *
 * `7877845 Moving to Render Starter plan` is the tip of v6. Everything v7 did
 * to the planning agent is therefore the diff from here to the working tree.
 */
const PRE_V7 = '7877845'

function git(...args: string[]): string {
  return execFileSync('git', args, { cwd: REPO_ROOT, encoding: 'utf8' })
}

/** True when the anchor commit is reachable — a shallow clone may not have it. */
function anchorAvailable(): boolean {
  try {
    git('cat-file', '-e', `${PRE_V7}^{commit}`)
    return true
  } catch {
    return false
  }
}

/**
 * Diff a path from the pre-v7 anchor to the current working tree.
 *
 * Deliberately `git diff <ref> -- <path>` rather than `<ref>..HEAD`: the
 * two-dot form compares commits only and would miss an uncommitted edit, which
 * is the state half of this repo's work is normally in.
 */
function diffSinceV7(...args: string[]): string {
  return git('diff', PRE_V7, '--', ...args)
}

/**
 * Paths v7 must not have altered at all.
 *
 * The backend package is named by instruction 12 explicitly; the frontend
 * entries are the behavioural half of the app, plus the two suites the
 * instruction requires still pass *unmodified*.
 */
const UNTOUCHED = [
  'backend/app/planning',
  'backend/app/api/planning.py',
  'frontend/src/apps/planning/PlanningApp.tsx',
  'frontend/src/apps/planning/PlanOverview.tsx',
  'frontend/src/apps/planning/PlanGoalForm.tsx',
  'frontend/src/apps/planning/PlanReviewPanel.tsx',
  'frontend/src/apps/planning/planState.ts',
  'frontend/src/apps/planning/runAllowance.ts',
  'frontend/src/api/planning.ts',
  'frontend/src/api/usePlanningRun.ts',
  'frontend/tests/planning.test.tsx',
  'frontend/tests/planning-ui.test.tsx',
]

describe('the planning agent is unchanged apart from its cross-reference', () => {
  it('can reach the commit it anchors to', () => {
    // Stated as its own assertion so a missing anchor reads as "this check did
    // not run" rather than passing vacuously through every `skipIf` below.
    expect(
      anchorAvailable(),
      `the pre-v7 anchor ${PRE_V7} is unreachable; fetch full history to run this suite`,
    ).toBe(true)
  })

  it.each(UNTOUCHED)('has no diff since before v7: %s', (path) => {
    expect(diffSinceV7(path)).toBe('')
  })

  it('added exactly one file to the planning app folder', () => {
    const added = git(
      'diff',
      PRE_V7,
      '--diff-filter=A',
      '--name-only',
      '--',
      'frontend/src/apps/planning',
    )
      .split('\n')
      .filter((line) => line !== '')

    expect(added).toEqual(['frontend/src/apps/planning/ReactCrossReference.tsx'])
  })

  it('changed the planning screen by addition only', () => {
    const diff = git(
      'diff',
      PRE_V7,
      '--unified=0',
      '--',
      'frontend/src/screens/planning',
    )
    const removed = diff
      .split('\n')
      .filter((line) => line.startsWith('-') && !line.startsWith('---'))

    // One removal is permitted and is copy: the limits tag said "3 runs per
    // day" from before v5 moved the usage window to the UTC hour, so the page
    // was stating a limit the server had not enforced for two revisions.
    expect(removed).toHaveLength(1)
    expect(removed[0]).toMatch(/runs per day/)

    const added = diff
      .split('\n')
      .filter((line) => line.startsWith('+') && !line.startsWith('+++'))
    // Import, render, comment, and the corrected tag. Nothing else.
    expect(added).toHaveLength(4)
    expect(added.join('\n')).toMatch(/ReactCrossReference/)
  })

  it('leaves the planning backend without a single reference to this revision', () => {
    // A behavioural coupling would show up here long before it showed up in a
    // diff — a shared constant, an import, a branch on the new app.
    // `git grep` exits 1 on *no match*, which is the passing case here, so the
    // status has to be read rather than left to throw.
    let hits = ''
    try {
      hits = git(
        'grep',
        '-il',
        '-e',
        'react_loop',
        '-e',
        'ReactCrossReference',
        '--',
        'backend/app/planning',
        'backend/app/api/planning.py',
      ).trim()
    } catch (cause) {
      const status = (cause as { status?: number }).status
      // Anything other than "found nothing" is a broken assertion, not a pass.
      expect(status).toBe(1)
    }

    expect(hits).toBe('')
  })
})
