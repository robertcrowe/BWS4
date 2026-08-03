# Built with Spec4 AI - https://spec4.ai
"""What the collab slice needs from a deployment, and what it must not.

The claim being pinned is that this slice **adds nothing to the deploy**: no
build step, no system binary, no model download, no environment variable. That
matters more than it sounds. The free Web Service has a fixed build and a
15-minute idle spin-down, so a slice that quietly added a download would move
the cost onto every cold start — and cold start is a routine path here, not an
edge case.

Asserted against `render.yaml` itself rather than remembered, because the file
is the deployment's source of truth and a drift between it and this belief is
exactly what nobody would notice until a deploy failed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

from backend.app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
RENDER = yaml.safe_load((REPO_ROOT / "render.yaml").read_text())
API_SERVICE = next(
    service for service in RENDER["services"] if service["name"] == "bws4-api"
)
COLLAB = REPO_ROOT / "backend" / "app" / "collab"


class TestTheSliceAddsNothingToTheBuild:
    def test_the_build_command_is_unchanged_by_this_slice(self) -> None:
        """One `uv sync` and the embeddings model pre-download that predates
        this revision. Nothing collab-shaped in it."""
        build = API_SERVICE["buildCommand"]

        assert "uv sync --frozen" in build
        assert "collab" not in build
        # The only download is the embeddings model, which v0 introduced.
        assert build.count("python -c") == 1
        assert "SentenceTransformer" in build

    def test_the_start_command_is_the_same_single_process(self) -> None:
        assert API_SERVICE["startCommand"].startswith(
            "uv run uvicorn backend.app.main:app"
        )
        assert "collab" not in API_SERVICE["startCommand"]

    def test_render_yaml_declares_exactly_the_settings_the_app_reads(self) -> None:
        """The deploy config and the code must agree, in both directions.

        Written for v6, which introduced no environment variable, and named for
        that at the time. What it *enforces* is the more durable property, so it
        is named for that now: a variable the app reads but `render.yaml` never
        declares fails on a deploy rather than in CI, which is the worst place
        to find out, and a variable declared here but read nowhere is a stale
        instruction to whoever configures the service by hand.

        Asserted **both ways**, because the subset check alone was too weak and
        let a real gap through: `MODERATION_HASH_SALT` had never been declared
        in `render.yaml` at all, and a test that only forbids *extra* keys
        passes happily on a missing one.

        Adding a key here is therefore a deliberate act, and the list is spelled
        out rather than derived from `Settings` so it stays one.
        """
        declared = {var["key"] for var in API_SERVICE["envVars"]}
        expected = {
            "PYTHON_VERSION",
            "HF_HOME",
            "HF_TOKEN",
            "DATABASE_URL",
            "CORS_ORIGIN",
            "OPENROUTER_API_KEY",
            "GROQ_API_KEY",
            "EXA_API_KEY",
            "OPENAI_API_KEY",
            "MODERATION_HASH_SALT",
            "SENTRY_DSN",
            "SENTRY_ENVIRONMENT",
        }

        assert declared <= expected, f"unexpected new env vars: {declared - expected}"
        assert expected <= declared, f"undeclared env vars: {expected - declared}"

    def test_every_secret_stays_dashboard_entered(self) -> None:
        """`sync: false` keeps credentials out of the repo. A key committed
        here would be a real disclosure, not a lint finding.

        Scoped to the variables that actually carry a credential.
        `SENTRY_ENVIRONMENT` is a plain label with a literal value and
        `PYTHON_VERSION`/`HF_HOME` are build configuration -- requiring
        dashboard entry for those would be cargo-culting the rule rather than
        applying it.
        """
        secrets = {
            "DATABASE_URL",
            "OPENROUTER_API_KEY",
            "GROQ_API_KEY",
            "EXA_API_KEY",
            "OPENAI_API_KEY",
            "MODERATION_HASH_SALT",
            "SENTRY_DSN",
            "HF_TOKEN",
        }
        for var in API_SERVICE["envVars"]:
            if var["key"] not in secrets:
                continue
            assert var.get("sync") is False, f"{var['key']} is not dashboard-entered"
            assert "value" not in var, f"{var['key']} has a literal value in the repo"

    def test_cors_stays_pinned_to_the_one_origin(self) -> None:
        """Cross-wired from the web service, never widened -- the constraint
        every phase of this project has kept."""
        cors = next(v for v in API_SERVICE["envVars"] if v["key"] == "CORS_ORIGIN")

        assert "fromService" in cors
        assert cors["fromService"]["name"] == "bws4-web"


class TestTheSliceAddsNoRuntimeWeight:
    def test_it_imports_no_new_third_party_package(self) -> None:
        """Every import in the slice is either stdlib, a package the project
        already had, or another module of this project. A new dependency would
        need a lockfile change and would land on the cold-start path."""
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
        """The embeddings app pays a model download; this slice must not add a
        second one. Its agents are remote, and its arithmetic is arithmetic."""
        for path in COLLAB.rglob("*.py"):
            text = path.read_text()
            for forbidden in ("sentence_transformers", "SentenceTransformer", "torch"):
                assert forbidden not in text, f"{path.name} would load local weights"

    def test_nothing_in_the_slice_runs_at_import_time(self) -> None:
        """A slice that reached a provider or a database at import would move
        the cost onto process start, which on a free tier is every cold start.

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
        """The first thing a visitor sees after a spin-down. It has to render
        before any model work begins, or the screen reads as hung for the ten
        seconds Render takes to wake."""
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
        content, so a sleeping backend does not delay them. Asserted here as a
        backend property: there is no endpoint they depend on."""
        from backend.app.api import collab as collab_api

        routes = {
            route.path  # type: ignore[attr-defined]
            for route in collab_api.router.routes
        }
        assert routes == {"/api/collab/identity-cards", "/api/collab/run"}

    def test_the_run_endpoint_sets_a_keep_alive_ping(self) -> None:
        """Render's proxy closes an idle connection, and a bidding stage
        against a free model can run for tens of seconds with nothing to say.
        Without the ping the stream dies mid-run behind the proxy."""
        from backend.app.api import collab as collab_api

        assert collab_api.PING_SECONDS > 0
        assert collab_api.PING_SECONDS < 30


class TestSettingsRequireNothingNew:
    def test_v6_introduced_no_new_setting(self) -> None:
        fields = set(Settings.model_fields)
        assert not {
            name for name in fields if "collab" in name or "negotiation" in name
        }
