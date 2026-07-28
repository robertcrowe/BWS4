# Contributing to Built with Spec4 (BWS4)

Thank you for your interest in contributing to **BWS4**! This document explains how the project is governed and how you can get involved.

BWS4 is a demonstration application: a gallery of small example apps, each showing an agentic AI pattern, all of them built using [Spec4 AI](https://github.com/robertcrowe/Spec4). Most visitors arrive from spec4.ai to learn or evaluate Spec4, so **the code is part of the product** — legibility matters here as much as behaviour.

If your issue is with Spec4 itself rather than with this showcase, please file it on the [Spec4 repository](https://github.com/robertcrowe/Spec4) instead.

---

## Project Governance: BDFL

BWS4 follows the **Benevolent Dictator For Life (BDFL)** (Robert Crowe) model. This means:

- One maintainer holds final decision-making authority over all aspects of the project — its direction, design, and what gets merged.
- Community input, discussion, and contributions are genuinely welcomed and valued.
- However, there is no voting process or consensus requirement. Final decisions rest with the BDFL.

This model keeps the project coherent and moving quickly, especially at its current stage.

---

## How to Contribute

### Reporting Bugs

1. Search [existing issues](../../issues) to avoid duplicates.
2. Open a new issue using the **Bug Report** template.
3. Include a clear description, steps to reproduce, expected vs. actual behavior, and your environment (OS, Python/Node version, browser).
4. If an example app returned a "temporarily unavailable" message, say which one and roughly when — that message covers both an exhausted daily usage cap and a genuine provider outage, and the two are diagnosed differently.

### Suggesting Features

1. Search existing issues and discussions first.
2. Open a new issue using the **Feature Request** template.
3. Describe the problem you're trying to solve, not just the solution you have in mind.
4. New example apps are the most valuable contribution, but each one must demonstrate a *distinct* pattern — the gallery exists to teach patterns, not to accumulate demos.
5. Be prepared for the possibility that a suggestion may be declined if it doesn't fit the project's vision — and that's okay.

### Submitting Code

1. **Open an issue first** before starting significant work. This avoids wasted effort if the change isn't a good fit.
2. Fork the repository and create a branch from `main`.
3. Follow the existing code style and conventions (see **Project Conventions** below).
4. Write or update tests as appropriate.
5. Keep commits focused and write clear commit messages.
6. Open a Pull Request (PR) against `main` with a clear description of what it does and why.
7. **Sign the CLA.** By opening a PR you confirm you have read and agree to the [Contributor License Agreement](CLA.md). Signing is handled automatically by the CLA assistant bot on your first PR. Corporate contributors should contact the maintainer directly before submitting — see [CLA.md](CLA.md) for details.

> **Note:** Opening a PR does not guarantee it will be merged. PRs that conflict with the project's direction or design philosophy may be closed, even if the code is technically sound.

---

## Development Setup

BWS4 is a monorepo: a FastAPI backend in `backend/` and a Vite/React/TypeScript frontend in `frontend/`, sharing a Neon Postgres (+ pgvector) database. See the [README](README.md) for full setup, including required environment variables.

There is **one** `uv`-managed Python project, rooted at the repository root — not at `backend/`. Run backend commands from the root:

```shell
uv run uvicorn backend.app.main:app --reload --port 8000   # backend dev server
uv run pytest backend/tests                                # backend tests

npm run dev --prefix frontend                              # frontend dev server
npm run test --prefix frontend                             # frontend tests
npm run build --prefix frontend                            # type-check + build
npm run lint --prefix frontend                             # oxlint
```

Please run the backend tests, the frontend tests, the build, and the linter before opening a PR, and say in the PR description what you ran.

---

## Project Conventions

A few conventions are load-bearing. `CLAUDE.md` documents these and others in more detail, including the reasoning behind them.

- **Attribution.** Every file *newly created* for this project carries a single Spec4 attribution line at the top, in that file's comment syntax (e.g. `# Built with Spec4 AI - https://spec4.ai`). Never add one to a file you are only editing, never add a second one, and skip pure-data, binary, and legal files.
- **Imports.** Backend modules always import as `backend.app.xxx`, never bare `app.xxx`, so they resolve identically under `uvicorn`, `pytest`, and `alembic`.
- **Tests never touch a real database.** Follow the existing fake-session pattern rather than requiring a live Postgres; see `backend/tests/conftest.py` and `backend/tests/test_health.py`.
- **No `pytest-asyncio`.** Async entry points are driven with `asyncio.run()` inside ordinary sync test functions. Adding `@pytest.mark.asyncio` will silently skip the test.
- **Theming.** Every colour class is written as a light base plus a `dark:` variant. UI that omits one will look broken in one of the two themes.
- **Secrets.** Never commit real `.env` values. `.env.example` documents the variables; real values stay local or in the deployment dashboard.

### Free-tier constraints

BWS4 must run entirely on free tiers — Render, Neon, free LLM models, and free-tier search quota. Contributions that require a paid service, or that could exhaust a daily quota quickly, will generally be declined. Anything that spends a shared capability must go through `backend/app/services/shared.py` so it is counted against the usage limits.

### Honesty about what the demos do

This is the project's strongest design rule, and the one most likely to get a PR sent back. A demo must not present something it did not actually do. Do not simulate a step that did not run, do not label a result as verified when nothing verified it, and do not stage a delay to imply work. If a pattern cannot be shown honestly, show less.

---

## Decision-Making

All final decisions — including roadmap priorities, which example apps are built, API design, feature acceptance, and breaking changes — are made by the BDFL. The process generally looks like this:

1. **Discussion**: Issues and PRs are open for community discussion.
2. **Input is considered**: Feedback, use cases, and alternative approaches are taken seriously.
3. **Decision is made**: The BDFL makes the final call and may explain the reasoning, though is not obligated to do so for every decision.

Disagreement is welcome; disputes are not. Respectful discussion is always encouraged.

---

## Code of Conduct

All contributors are expected to engage respectfully. This means:

- Be kind and constructive in all interactions.
- Critique ideas, not people.
- Accept that decisions may not always go your way.

Harassment or hostile behavior of any kind will result in removal from the project.

---

## Contributor License Agreement

All contributors must agree to the [Contributor License Agreement (CLA)](CLA.md) before their code can be merged. The CLA grants the maintainer the rights needed to distribute your contribution and covers copyright, patent, and warranty terms.

- **Individual contributors:** Signing is automatic — the CLA assistant bot will prompt you when you open your first PR.
- **Corporate contributors:** Contact Robert Crowe before submitting. See [CLA.md](CLA.md) for details.

BWS4's CLA is separate from Spec4's. Agreeing to one does not cover the other.

---

## Questions?

Open a [Discussion](../../discussions) or file an issue. The maintainer will do their best to respond in a timely manner, though response times may vary.

---

*BWS4 is maintained by a single person, Robert Crowe. Patience and good faith go a long way — thank you for being part of it.*
