# Built with Spec4 AI - https://spec4.ai
"""What the collab slice needs from a deployment, and what it must not.

The claim being pinned is that this slice **adds nothing to the deploy**: no
build step, no system binary, no model download, no environment variable. That
matters more than it sounds: the whole gallery is one always-on process whose
boot already pays for the embedding model and the PCA projection, and a slice
that quietly added a download or a variable would move its cost onto every
release restart and onto whoever maintains /etc/bws4/bws4.env by hand.

Originally asserted against render.yaml; since the Phase 6 cutover (2026-08-19)
the deployment's sources of truth are the systemd unit template
`deploy/bws4-api.service`, the release script `deploy/deploy.sh`, and the
documented environment contract (`deploy/README.md` for the VPS,
`.env.example` for local development). Asserted against those files themselves
rather than remembered, for the same reason as before: a drift between them
and this belief is exactly what nobody would notice until a deploy failed.
"""

from __future__ import annotations

import ast
from pathlib import Path

from backend.app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
UNIT = (REPO_ROOT / "deploy" / "bws4-api.service").read_text()
DEPLOY_SH = (REPO_ROOT / "deploy" / "deploy.sh").read_text()
DEPLOY_README = (REPO_ROOT / "deploy" / "README.md").read_text()
ENV_EXAMPLE = (REPO_ROOT / ".env.example").read_text()
COLLAB = REPO_ROOT / "backend" / "app" / "collab"

EXEC_START = next(
    line for line in UNIT.splitlines() if line.startswith("ExecStart=")
)


def _env_example_entries() -> dict[str, str]:
    """The local-dev contract, parsed from .env.example itself."""
    entries: dict[str, str] = {}
    for line in ENV_EXAMPLE.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        entries[key.strip()] = value.strip()
    return entries


class TestTheSliceAddsNothingToTheDeploy:
    def test_the_release_script_is_unchanged_by_this_slice(self) -> None:
        """One locked dependency sync, one frontend build, no model download.

        The release script must not download model weights at all: the
        embedding model lives in the service user's HuggingFace cache and is
        loaded by the lifespan warm-up, so a download appearing here would be
        a second copy of a cost the boot already pays. Nothing collab-shaped
        anywhere in the procedure.
        """
        assert "sync --locked" in DEPLOY_SH
        assert "npm run build" in DEPLOY_SH
        assert "collab" not in DEPLOY_SH
        assert "SentenceTransformer" not in DEPLOY_SH
        assert "huggingface" not in DEPLOY_SH.lower()

    def test_the_unit_starts_the_same_single_process(self) -> None:
        """One uvicorn worker on loopback — the architecture's one hard rule.

        The in-process peer message bus this slice depends on is per-process
        state; the unit growing a second worker would not crash, it would
        silently break peer opacity. So the start command is pinned verbatim.
        """
        assert "uvicorn backend.app.main:app" in EXEC_START
        assert "--workers 1" in EXEC_START
        assert "--host 127.0.0.1" in EXEC_START
        assert "collab" not in EXEC_START

    def test_the_env_contracts_declare_exactly_the_settings_the_app_reads(
        self,
    ) -> None:
        """The documented contracts and the code must agree, in both directions.

        A variable the app reads but no contract documents fails on a fresh
        provisioning rather than in a test, which is the worst place to find
        out; a variable documented but read nowhere is a stale instruction to
        whoever fills in /etc/bws4/bws4.env by hand. Asserted both ways
        against .env.example (the machine-parseable contract), and the
        runtime names are additionally required to appear in the VPS runbook.

        The lists are spelled out rather than derived from Settings so that
        adding a key stays a deliberate act — and none of them may ever grow
        a collab-shaped entry.
        """
        declared = set(_env_example_entries())
        expected = {
            "DATABASE_URL",
            "CORS_ORIGIN",
            "PORT",
            "EMBEDDING_MODEL_NAME",
            "OPENROUTER_API_KEY",
            "GROQ_API_KEY",
            "EXA_API_KEY",
            "OPENAI_API_KEY",
            "SENTRY_DSN",
            "SENTRY_ENVIRONMENT",
            "VITE_API_BASE_URL",
            "VITE_SENTRY_DSN",
        }
        assert declared <= expected, f"unexpected new env vars: {declared - expected}"
        assert expected <= declared, f"undeclared env vars: {expected - declared}"

        runtime_contract = {
            "DATABASE_URL",
            "OPENROUTER_API_KEY",
            "GROQ_API_KEY",
            "EXA_API_KEY",
            "OPENAI_API_KEY",
            "CORS_ORIGIN",
            "SENTRY_DSN",
        }
        for name in runtime_contract:
            assert f"`{name}`" in DEPLOY_README, f"{name} missing from the runbook"

        assert not {name for name in declared if "collab" in name.lower()}

    def test_every_secret_stays_outside_the_repository(self) -> None:
        """Credentials reach the process only via the root-owned env file.

        Three structural facts carry that: the unit sources its environment
        from /etc/bws4/bws4.env (outside the tree, readable only by root),
        the committed .env.example carries names with EMPTY values for every
        credential-bearing key, and .env itself is ignored so a local dev
        file cannot be committed by accident. A key with a literal value in
        any committed file would be a real disclosure, not a lint finding.
        """
        assert "EnvironmentFile=/etc/bws4/bws4.env" in UNIT

        secrets = {
            "DATABASE_URL",
            "OPENROUTER_API_KEY",
            "GROQ_API_KEY",
            "EXA_API_KEY",
            "OPENAI_API_KEY",
            "SENTRY_DSN",
        }
        entries = _env_example_entries()
        for key in secrets:
            assert entries[key] == "", f"{key} has a literal value in .env.example"

        gitignore = (REPO_ROOT / ".gitignore").read_text().splitlines()
        assert ".env" in gitignore

    def test_cors_stays_pinned_to_the_one_origin(self) -> None:
        """A single-element allow list built from one setting, never widened —
        the constraint every phase of this project has kept. Asserted against
        the source rather than a deploy config, because since the cutover the
        pin lives in exactly one place."""
        main_py = (REPO_ROOT / "backend" / "app" / "main.py").read_text()
        assert "allow_origins=[settings.cors_origin]" in main_py
        # Methods and headers legitimately use "*"; the ORIGIN list never may.
        assert 'allow_origins=["*"]' not in main_py
        assert "allow_origins=['*']" not in main_py


class TestTheSliceAddsNoRuntimeWeight:
    def test_it_imports_no_new_third_party_package(self) -> None:
        """Every import in the slice is either stdlib, a package the project
        already had, or another module of this project. A new dependency would
        need a lockfile change and would land on the warm-up path."""
        allowed_third_party = {
            "pydantic",
            "pydantic_ai",
            "structlog",
            "sqlalchemy",
            "fastapi",
            "sse_starlette",
        }
        stdlib_ok = {
            "__future__",
            "asyncio",
            "dataclasses",
            "datetime",
            "enum",
            "collections",
            "pathlib",
            "re",
            "time",
            "typing",
            "uuid",
        }

        for path in COLLAB.rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    root = name.split(".")[0]
                    assert (
                        root == "backend"
                        or root in allowed_third_party
                        or root in stdlib_ok
                    ), f"{path.name} imports {name}, which is new to the deploy"

    def test_it_downloads_no_model_and_loads_no_local_weights(self) -> None:
        """The embeddings warm-up pays a model load at boot; this slice must
        not add a second one. Its agents are remote, and its arithmetic is
        arithmetic."""
        for path in COLLAB.rglob("*.py"):
            text = path.read_text()
            for forbidden in ("sentence_transformers", "SentenceTransformer", "torch"):
                assert forbidden not in text, f"{path.name} would load local weights"

    def test_nothing_in_the_slice_runs_at_import_time(self) -> None:
        """A slice that reached a provider or a database at import would move
        the cost onto process start — the release-restart window every deploy
        already pays once, and the reboot path the always-on guarantee rests on.

        Importing the package's modules here would fail outright if any of them
        did -- there is no provider and no database in this test process.
        """
        import importlib

        for path in sorted(COLLAB.glob("*.py")):
            if path.name == "__init__.py":
                continue
            importlib.import_module(f"backend.app.collab.{path.stem}")


class TestTheColdStartPath:
    def test_the_identity_cards_answer_without_a_model_or_a_database(self) -> None:
        """The first thing the collab screen fetches. It must not depend on
        the lifespan warm-up or the database, or the screen reads as hung for
        the ~30 s a release restart spends rebuilding warm state. (On the
        retired platform this guarded every cold start; the property is the
        same, the window is now just the one the operator chooses.)"""
        from fastapi.testclient import TestClient

        from backend.app.main import app

        # No context manager: entering it runs the lifespan, which loads
        # sentence-transformers. This route must answer without any of that.
        client = TestClient(app)
        response = client.get("/api/collab/identity-cards")

        assert response.status_code == 200
        assert len(response.json()["agents"]) == 3

    def test_the_overview_needs_no_backend_at_all(self) -> None:
        """The pattern explanation and the candid note are static frontend
        content, so a restarting backend does not delay them. Asserted here as
        a backend property: there is no endpoint they depend on."""
        from backend.app.api import collab as collab_api

        routes = {
            route.path  # type: ignore[attr-defined]
            for route in collab_api.router.routes
        }
        assert routes == {"/api/collab/identity-cards", "/api/collab/run"}

    def test_the_run_endpoint_sets_a_keep_alive_ping(self) -> None:
        """Idle proxy hops close silent connections — Caddy at the edge now,
        and whatever intermediaries a visitor sits behind regardless of host —
        and a bidding stage against a free model can run for tens of seconds
        with nothing to say. Without the ping the stream dies mid-run behind
        the proxy (Phase 5 observed the pings holding a stream through a
        ~100 s idle stretch)."""
        from backend.app.api import collab as collab_api

        assert collab_api.PING_SECONDS > 0
        assert collab_api.PING_SECONDS < 30


class TestSettingsRequireNothingNew:
    def test_v6_introduced_no_new_setting(self) -> None:
        fields = set(Settings.model_fields)
        assert not {
            name for name in fields if "collab" in name or "negotiation" in name
        }
