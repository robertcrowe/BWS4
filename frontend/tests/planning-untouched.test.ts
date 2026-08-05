// Built with Spec4 AI - https://spec4.ai
/**
 * The planning agent is copy-plus-one-link in this revision, and this proves it.
 *
 * **The phase's first named risk is scope creep into a working app.** The
 * revision lists Planning Agent as a changed feature, which reads as licence to
 * tidy its overview component, its route or its budget while passing through.
 * Instruction 12 forbids exactly that, and a claim of "we didn't touch it" is
 * the sort of claim this project has a standing rule against making unverified.
 *
 * So the assertions are made against **git**, not against the code's own
 * opinion of itself: the planning package must have a literally empty diff, its
 * screen's diff must be additions only, and its test files must be byte
 * identical to what is committed. A component test asserting "planning still
 * renders" would pass through a rewrite; this cannot.
 *
 * The companion half of instruction 18 — that the existing planning suite still
 * passes — is satisfied by those suites running unmodified in this same run.
 * Unmodified is the part that needed proving; passing was already measured.
 */
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const REPO_ROOT = resolve(__dirname, '../..')

function git(...args: string[]): string {
  return execFileSync('git', args, { cwd: REPO_ROOT, encoding: 'utf8' })
}

/** Paths whose committed content this phase must not have altered at all. */
const UNTOUCHED = [
  // Instruction 12 names this one explicitly.
  'backend/app/planning',
  'backend/app/api/planning.py',
  // The behavioural half of the frontend app. The cross-reference is a new
  // file, so it appears as untracked rather than as a diff to any of these.
  'frontend/src/apps/planning/PlanningApp.tsx',
  'frontend/src/apps/planning/PlanOverview.tsx',
  'frontend/src/apps/planning/PlanGoalForm.tsx',
  'frontend/src/apps/planning/PlanReviewPanel.tsx',
  'frontend/src/apps/planning/planState.ts',
  'frontend/src/apps/planning/runAllowance.ts',
  'frontend/src/api/planning.ts',
  'frontend/src/api/usePlanningRun.ts',
  // The frontend suites instruction 18 requires still pass *unmodified*.
  'frontend/tests/planning.test.tsx',
  'frontend/tests/planning-ui.test.tsx',
]

describe('the planning agent is unchanged apart from its cross-reference', () => {
  it.each(UNTOUCHED)('has no working-tree diff at all: %s', (path) => {
    expect(git('diff', 'HEAD', '--', path)).toBe('')
  })

  it('added the cross-reference as a new file rather than editing an existing one', () => {
    const tracked = git('ls-files', '--', 'frontend/src/apps/planning')
      .split('\n')
      .filter((line) => line !== '')

    // Every pre-existing file in the folder is still tracked and undiffed; the
    // one new file is untracked, so it cannot be a rewrite of any of them.
    expect(tracked).not.toContain('frontend/src/apps/planning/ReactCrossReference.tsx')
    expect(git('diff', 'HEAD', '--', 'frontend/src/apps/planning')).toBe('')
  })

  it('changed the planning screen by addition only', () => {
    const diff = git('diff', 'HEAD', '--unified=0', '--', 'frontend/src/screens/planning')
    const removed = diff
      .split('\n')
      .filter((line) => line.startsWith('-') && !line.startsWith('---'))

    // One removal is permitted and is copy: the limits tag said "3 runs per
    // day" from before v5 moved the usage window to the UTC hour, so the page
    // was stating a limit the server has not enforced for two revisions.
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
