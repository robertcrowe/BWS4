---
{
  "phase_number": 6,
  "total_phases": 8,
  "phase_title": "Retired-Host (Render) Sweep and Startup Docstring",
  "phase_summary": "Rewrite the stale main.py lifespan docstring to describe the always-on VPS, where the embedding model and 2D projection load once at boot and stay warm. Sweep all code, docs, config and deploy files so Render is cited only where recording its retirement.",
  "features": [
    {
      "id": "codebase_quality_and_config_cleanup",
      "role": "extended",
      "scope_note": "Stale Render references (item 4)."
    }
  ],
  "capabilities": [],
  "tech_stack_spec": {
    "dependencies": [
      "Ruff",
      "mypy"
    ],
    "configurations": "No environment changes. The environment contract carries over with no variable added, removed or renamed."
  },
  "instructions": [
    "Rewrite the docstring of the lifespan function in backend/app/main.py. It must describe the always-on netcup VPS: the embedding model load and the 2D projection fit happen once at boot and stay warm for the process lifetime. It must state that the embeddings warm-up and the Router route-description warm-up are best-effort (failure logged, API still starts) and that missing GROQ_API_KEY or OPENAI_API_KEY is fatal. Remove the free-tier spin-down text. Follow the Google-style docstring and heavy 'why' comment convention.",
    "Run a case-insensitive search for 'render' across the whole repo (`git grep -n -i render`), excluding node_modules, dist, lockfile hashes and React's own `render` API usage (for example `render(` in Testing Library and ReactDOM render calls). Classify each hit as: stale host reference (update or delete), legitimate React/rendering term (leave), or a statement recording the retirement (keep).",
    "Check specifically: README.md, CLAUDE.md, .env.example, deploy/ (Caddyfile, systemd unit, deploy.sh, provisioning README), .claude/settings.json, pyproject.toml, frontend/index.html, frontend/public/, frontend/src/seo/siteMeta.ts, backend comments and test comments or fixtures, CORS_ORIGIN examples such as onrender.com URLs, and any render.yaml remnant (it must be absent).",
    "Update stale mentions to describe the VPS (netcup VPS 500 G12, Caddy, systemd) or remove them. Keep at most one clear statement per document that Render was retired, where it is useful history. Do not add any new variable names.",
    "If any hit is a URL used at runtime (for example a canonical URL, sitemap entry or CORS default pointing at a Render hostname), do not guess the replacement. Replace it with the configured canonical origin only if one is already defined elsewhere in the repo; otherwise flag it in the review note for the owner.",
    "Append a 'Render sweep' section to docs/v10-cleanup-review-note.md listing each file changed and each retirement-recording mention kept.",
    "Run `uv run ruff check . && uv run ruff format --check . && uv run mypy` and `uv run pytest` to confirm the docstring and comment edits changed nothing else."
  ],
  "risk_assessment": {
    "potential_bottlenecks": "A text sweep can miss variants (onrender, render.com, RENDER_ env names) or wrongly alter React's legitimate render terminology. A runtime URL could be altered incorrectly.",
    "mitigation_strategy": "Search several spellings (render, onrender, render.com, RENDER_), review each hit manually, and flag runtime URLs for the owner instead of guessing."
  },
  "verification": "`git grep -n -i \"onrender\\|render\\.com\\|render\\.yaml\\|render free\\|render's\"` returns only lines that record the retirement. The remaining `render` hits are demonstrably React or test-library rendering terms. The main.py lifespan docstring mentions the always-on VPS and warm-at-boot behaviour. `uv run ruff check .`, `uv run mypy` and `uv run pytest` all pass. Cites nfr_the_first_visit_loads_without_a_cold_start_delay_because_the_embedding_capability_is_ready_at_startup for the documented warm-at-boot behaviour.",
  "references": [
    {
      "standard": "netcup VPS (G12 line)",
      "url": "https://www.netcup.com/en/server/vps"
    },
    {
      "standard": "Caddy",
      "url": "https://caddyserver.com/docs/"
    },
    {
      "standard": "systemd service units",
      "url": "https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html"
    }
  ]
}
---

# Phase 6 of 8: Retired-Host (Render) Sweep and Startup Docstring

Rewrite the stale main.py lifespan docstring to describe the always-on VPS, where the embedding model and 2D projection load once at boot and stay warm. Sweep all code, docs, config and deploy files so Render is cited only where recording its retirement.

## Feature Specifications

These specifications are authoritative for this phase. Implement to them; the instructions below tell you how and in what order.

### Codebase_Quality_And_Config_Cleanup — product feature — extended in this phase

*Scope for this phase: Stale Render references (item 4).*

A behaviour-preserving cleanup that brings the whole codebase under full lint and type checking, makes the required credentials truly required, removes stale references to the retired host, and documents previously unrecorded edits.

**Invocation**

- Trigger: Maintainers run this one-time cleanup before the next release; the checks then run in the normal quality gate.

**Inputs**

- `Existing codebase` (set of source files, required) — All source, tests, docs and configuration, including older modules currently excluded from checks.
- `Unrecorded edits` (list of items, required) — Site metadata, the shared generation service, project documentation, assistant settings, project configuration and ReAct frontend test changes awaiting review.

**Outputs**

- Primary: A fully checked, consistently formatted codebase with no exclusions, updated documentation, and a written list of reviewed edits and any items flagged for the owner's decision.
- Format: Updated files plus a review note
- Schema notes: No visible behaviour change except that startup now fails when either required credential is missing. Chained Calls 'critique_failed' behaviour and the Router route-id contract are unchanged. Anything that looks unintended is flagged, not silently reverted.

**Success criteria**

- No lint or type-check exclusions remain and all findings are fixed.
- Example app behaviour, routes, response shapes, usage caps and visitor messages are unchanged.
- Startup fails clearly when either required credential is missing, with no placeholders or opt-out; tests require real credentials and the live smoke run stays opt-in.
- No mention of the retired host remains in code, docs, configuration or release files, and the startup description matches the always-on instance.
- Each unrecorded edit is documented as kept or flagged for the owner.
- A one-time check confirms the Router code and tests are covered by the checks.
- A failure while preparing route descriptions is logged, startup still succeeds, and the Router shows its unavailable state with a retry action until preparation succeeds.

**Failure modes**

- Fixing findings accidentally changes behaviour (likelihood: medium) — mitigation: Run the full test suite and compare visible behaviour before and after.
- Stricter credential rule breaks test runs without credentials (likelihood: high) — mitigation: Document that real credentials are needed for every test run and communicate the change to maintainers.
- An unintended edit is kept without review (likelihood: medium) — mitigation: Inspect each unrecorded edit and flag doubtful ones for the owner.
- A stale reference to the retired host is missed (likelihood: medium) — mitigation: Sweep all code, docs, configuration and release files for it.

- depends on: shared_framework_services, router_example_app, self_hosted_deployment (build these no later than `codebase_quality_and_config_cleanup`)
- entities: Source File, Check Finding, Credential, Review Note

## Tech Stack

**Dependencies:**

- Ruff
- mypy

**Configurations:** No environment changes. The environment contract carries over with no variable added, removed or renamed.

**Project-wide stack** (applies to every phase):

- FastAPI
- uvicorn
- SQLAlchemy
- asyncpg
- Alembic
- Pydantic
- tenacity
- pydantic-settings
- structlog
- sentry-sdk
- pytest
- Ruff
- mypy
- React
- react-dom
- Vite
- @vitejs/plugin-react
- React Router
- TanStack Query
- Tailwind CSS
- postcss
- autoprefixer
- typescript
- oxlint
- Vitest
- jsdom
- React Testing Library
- @testing-library/jest-dom
- @testing-library/user-event
- @types/node
- @types/react
- @types/react-dom
- @sentry/react

## Instructions

1. Rewrite the docstring of the lifespan function in backend/app/main.py. It must describe the always-on netcup VPS: the embedding model load and the 2D projection fit happen once at boot and stay warm for the process lifetime. It must state that the embeddings warm-up and the Router route-description warm-up are best-effort (failure logged, API still starts) and that missing GROQ_API_KEY or OPENAI_API_KEY is fatal. Remove the free-tier spin-down text. Follow the Google-style docstring and heavy 'why' comment convention.
2. Run a case-insensitive search for 'render' across the whole repo (`git grep -n -i render`), excluding node_modules, dist, lockfile hashes and React's own `render` API usage (for example `render(` in Testing Library and ReactDOM render calls). Classify each hit as: stale host reference (update or delete), legitimate React/rendering term (leave), or a statement recording the retirement (keep).
3. Check specifically: README.md, CLAUDE.md, .env.example, deploy/ (Caddyfile, systemd unit, deploy.sh, provisioning README), .claude/settings.json, pyproject.toml, frontend/index.html, frontend/public/, frontend/src/seo/siteMeta.ts, backend comments and test comments or fixtures, CORS_ORIGIN examples such as onrender.com URLs, and any render.yaml remnant (it must be absent).
4. Update stale mentions to describe the VPS (netcup VPS 500 G12, Caddy, systemd) or remove them. Keep at most one clear statement per document that Render was retired, where it is useful history. Do not add any new variable names.
5. If any hit is a URL used at runtime (for example a canonical URL, sitemap entry or CORS default pointing at a Render hostname), do not guess the replacement. Replace it with the configured canonical origin only if one is already defined elsewhere in the repo; otherwise flag it in the review note for the owner.
6. Append a 'Render sweep' section to docs/v10-cleanup-review-note.md listing each file changed and each retirement-recording mention kept.
7. Run `uv run ruff check . && uv run ruff format --check . && uv run mypy` and `uv run pytest` to confirm the docstring and comment edits changed nothing else.

## Risk Assessment

**Potential bottlenecks:**

A text sweep can miss variants (onrender, render.com, RENDER_ env names) or wrongly alter React's legitimate render terminology. A runtime URL could be altered incorrectly.

**Mitigation strategy:**

Search several spellings (render, onrender, render.com, RENDER_), review each hit manually, and flag runtime URLs for the owner instead of guessing.

## Verification

`git grep -n -i "onrender\|render\.com\|render\.yaml\|render free\|render's"` returns only lines that record the retirement. The remaining `render` hits are demonstrably React or test-library rendering terms. The main.py lifespan docstring mentions the always-on VPS and warm-at-boot behaviour. `uv run ruff check .`, `uv run mypy` and `uv run pytest` all pass. Cites nfr_the_first_visit_loads_without_a_cold_start_delay_because_the_embedding_capability_is_ready_at_startup for the documented warm-at-boot behaviour.

## References

- [netcup VPS (G12 line)](https://www.netcup.com/en/server/vps)
- [Caddy](https://caddyserver.com/docs/)
- [systemd service units](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
