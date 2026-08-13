# Deployment Plan

## Coding Agent Guidance

**Agent:** Claude Code (Anthropic, terminal-based)

### Starting the agent

Launch Claude Code from inside the BWS4 repository root. Every path below is relative to that directory, and Claude Code scopes both file access and `CLAUDE.md` discovery to the directory it was started in:

```shell
cd /path/to/bws4
claude
```

If you start it elsewhere and `cd` afterwards, `@` references will silently miss.

### Where the Spec4 files live

Spec4 has already written all planning artifacts into `.spec4/` in the project directory. This round is **v8**:

| Path | Contents |
|---|---|
| `.spec4/v8/vision.json` | Project vision statement |
| `.spec4/v8/stack.json` | Ratified technology stack |
| `.spec4/v8/code_review.json` | Brownfield review of the current Render deployment |
| `.spec4/v8/phases/phase1.md` … `phase6.md` | Six phase files — JSON frontmatter plus prose body |
| `.spec4/v8/design/mock.html` | UI design mock, if Designer produced one in an earlier round |

Confirm `.spec4/` and `deploy/` are not gitignored, or Claude will not be able to read them.

### Referencing phase files

Use the `@` prefix, which triggers path autocompletion and pulls the file directly into context:

```
Read @.spec4/v8/phases/phase1.md and implement it. Consult
@.spec4/v8/stack.json for the ratified stack and
@.spec4/v8/code_review.json for what the current Render deployment already does.
```

### Recommended workflow

Work **one phase per session**, in order, and `/clear` between phases. Six phases in one context window will degrade badly — this migration produces long shell transcripts and those consume context quickly.

For each phase:

1. Enter **plan mode** (`Shift+Tab` twice). Have Claude read the phase file and propose its approach before touching anything.
2. Review and correct the plan. Do not accept the first version uncritically.
3. Exit plan mode and let it execute.
4. Run the phase's verification steps and **paste the real output back into the session**, so Claude reasons about actual state rather than assumed state.

Verification in this revision is largely observational: `systemctl status bws4-api`, `curl -I https://bwtemp.spec4.ai`, `journalctl -u bws4-api -n 50`, and confirming SSE events arrive progressively rather than in one lump. Phase 5 is an acceptance pass, not a coding phase — Claude's job there is to help script and interpret checks, not write features.

Useful commands: `/clear` (fresh context between phases), `/compact` (proactively, with instructions like `/compact - preserve the deploy paths and unit file decisions`), `/context` (check how close you are to the limit), `Esc Esc` (rewind if a phase goes wrong).

### The wrinkle specific to this revision

Claude Code runs on your **local machine**, but Phases 1–3 and 6 are almost entirely work on the netcup host. The recommended split:

- **Author locally, execute over SSH yourself.** Claude writes the committed artifacts — `deploy/Caddyfile`, `deploy/bws4-api.service`, `deploy/deploy.sh`, the provisioning runbook — and hands you exact commands. You stay the one holding root. This keeps blast radius small and matches what the phases actually ask you to commit.
- Alternatively, run a second Claude Code session **on the VPS** if you want it driving the host directly. Faster, but that is an agent with `sudo` on your production box. If you do this, add `PreToolUse` deny rules for destructive commands.

### Guardrails to set up before starting

Add a `CLAUDE.md` at the repo root stating:

- `/etc/bws4/bws4.env` is created **outside** the repository tree and must never be written into the repo.
- Committed files reference environment variable **names only, never values**.
- The API runs with `--workers 1`. This is a hard invariant, not a default — the loaded embedding model, fitted PCA projection, in-process message bus, and ReAct duplicate-guard cache are all per-process state.

`CLAUDE.md` instructions are followed roughly 70% of the time; hooks enforce at 100%. Add a `PreToolUse` deny rule for writes matching `*.env` inside the repo. Every one of your six phases repeats the secrets constraint, which tells you it is the failure mode Phaser was most concerned about.

### Caveat worth stating explicitly

`deploy/deploy.sh` **must export `VITE_SENTRY_DSN` into the `npm run build` step**. The systemd `EnvironmentFile` does not apply to the build — Vite inlines that variable at build time. This is an easy thing for an agent to assume is handled when it is not.

---

## Target

### `web_client`

- **Type:** on-premise (self-hosted VPS)
- **Provider:** netcup — VPS 500 G12 (2 vCore, 4 GB DDR5 ECC, 128 GB NVMe, always-on)
- **Service:** Caddy 2 serving static files from `/srv/bws4/frontend/dist`
- **Region:** netcup European datacenter (Nuremberg / Vienna / Amsterdam). Choose the one nearest your primary audience — this bears directly on `nfr_pages_appear_within_about_a_second`.
- **Transport:** HTTPS only. Automatic Let's Encrypt issuance and renewal by Caddy, automatic HTTP→HTTPS redirect.
- **CORS:** not applicable — serves the browser origin itself rather than consuming one.

Build: `npm ci && npm run build` executed **on the VPS** by `deploy/deploy.sh`, producing a hashed bundle with route-based lazy-loaded chunks per example app. Served with SPA history fallback.

### `api`

- **Type:** on-premise (self-hosted VPS) — same host as `web_client`
- **Provider:** netcup — same VPS 500 G12
- **Service:** Uvicorn under `uv`, supervised by systemd (`bws4-api.service`), reverse-proxied by Caddy
- **Region:** same host
- **Transport:** HTTPS only, terminated by Caddy at the edge. **Uvicorn binds `127.0.0.1:8000` only and is never directly reachable from the network.**
- **CORS:** allow only the single non-wildcard configured origin, `CORS_ORIGIN`. Retained unchanged as part of the environment contract. Because the SPA now serves from the same canonical origin, cross-origin requests no longer occur in production — the policy is exercised chiefly in local development.

Runtime: Python 3.12, `--workers 1`, async concurrency only. FastAPI lifespan warm-up loads the embedding model and fits the 2D PCA projection once at boot and stays warm for the process lifetime. Warm-up is best-effort — a failed projection fit still boots.

---

## Containerization

- **Enabled:** No

The existing `render.yaml` PaaS config is retired and deleted in Phase 6. This revision runs bare-metal: `uv sync` from `pyproject.toml`/`uv.lock`, supervised by systemd. No Dockerfile, no registry.

Rationale: a container adds a layer without buying anything here. There is one process on one host, `uv` already pins the Python version and locks dependencies reproducibly, and systemd provides the supervision a container runtime would otherwise supply. Given 4 GB of RAM with torch and `sentence-transformers` resident, avoiding a container runtime's overhead is a small but real gain.

---

## CI/CD

- **Enabled:** No

Explicitly out of scope for this revision, per `release_delivery`. No CI exists in the tree today and adding one is not part of this migration. Quality gates — `ruff`, `mypy`, `pytest`, `vitest` — remain developer-run before push.

Release delivery is instead a single committed shell script, `deploy/deploy.sh`, run on the VPS. One readable, version-controlled procedure documenting the entire release in one file.

---

## Environment

**Required variables** — carried over verbatim from the retired Render dashboard. This revision adds none, removes none, renames none:

- `DATABASE_URL` — Neon Postgres connection string, pgvector-enabled. Unchanged; still the same external database Render currently uses.
- `OPENROUTER_API_KEY` — OpenRouter credential for the shared model chain
- `GROQ_API_KEY` — Groq credential for the LiteLLM and PydanticAI lanes
- `EXA_API_KEY` — Exa web-search credential (tool-use app and ReAct loop)
- `OPENAI_API_KEY` — carried in the contract across all phases
- `CORS_ORIGIN` — `https://bwtemp.spec4.ai` during Phases 1–5; repointed to `https://bw.spec4.ai` at Phase 6 cutover. **The name is unchanged from the retired platform's contract; only the value moves.**

**Optional:**

- `SENTRY_DSN` — backend error tracking. `configure_sentry` no-ops cleanly when unset.
- `VITE_SENTRY_DSN` — frontend error tracking. **Build-time only**, consumed by `npm run build`; the systemd `EnvironmentFile` does not reach the build.

**Secrets management:** single root-owned, `chmod 0600` file at `/etc/bws4/bws4.env`, created **outside the repository tree**, loaded via systemd `EnvironmentFile=`. Never committed. Committed files — `deploy/bws4-api.service`, `deploy/deploy.sh`, `deploy/Caddyfile` — reference variable **names only, never values**.

> **Shared-allowance warning.** During Phases 1–5 both Render and the VPS are live against the same Neon database, so the acceptance pass spends real free-tier model and Exa allowance against the **same shared hourly and daily caps** Render's traffic consumes. Plan the acceptance run for a quiet window and expect to hit caps sooner than usual.

---

## Monitoring

- **Error tracking:** Sentry — set both `SENTRY_DSN` (runtime) and `VITE_SENTRY_DSN` (build-time). Already wired into the codebase; no-ops cleanly when unset. Free tier: 5k errors/month, 1 user.
- **Metrics:** systemd journal via `journalctl`, capped at `SystemMaxUse=500M`. structlog's JSON output is captured through stdout/stderr. No external metrics platform — proportionate for a single-host teaching gallery.
- **Availability:** Better Stack free tier — 3-minute checks, 10 monitors, hosted status page. Configure **two** monitors:
  1. `https://bw.spec4.ai/` — does Caddy serve the SPA shell?
  2. `https://bw.spec4.ai/api/<health endpoint>` — does Uvicorn answer through the proxy?

  Two separate monitors matter because the surfaces fail differently: Caddy can serve static files perfectly while Uvicorn is dead, and a monitor on the root URL alone would show green through a total API outage. Add a third monitor on `bwtemp.spec4.ai` during the migration window, and remove it after cutover.

  Use the status page to communicate deliberate deploy restarts.
- **Model observability:** existing `usage_limits` / `service_log_entries` tables in Neon, plus structlog JSON in the journal. **No new tooling.** This revision introduces no new AI features — it relocates existing ones — so eval cadence and feedback-loop infrastructure would be over-engineering for a migration round.
- **Eval cadence:** none. Phase 5's behaviour-preservation acceptance pass is the migration's equivalent, comparing behaviour across both hosts against the same database.
- **Feedback loop:** none this round.
- **Safety/guardrails:** unchanged — the existing content moderation gate in the orchestrated-subagents app and the shared usage-limit gate carry over untouched.

**Why external monitoring is not optional here.** `systemd Restart=always` restarts a crashed process, and Caddy renews certificates in-process. Neither can tell you the *host* is down, the disk filled, or Caddy is misconfigured. On a single self-hosted VPS with no external observer, those failures are invisible until a visitor mentions them. Render was silently providing this; you now own it.

---

## Deployment Steps

### 1. Provision the VPS and establish SSH access

Order the netcup VPS 500 G12 with a **Debian 13 (trixie)** image in your chosen European datacenter. Note the public IPv4 (and IPv6, if assigned) from the netcup control panel.

From your local machine:

```shell
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@<VPS_IP>
ssh root@<VPS_IP>
```

Verify the image and resources:

```shell
cat /etc/os-release
free -h
df -h /
nproc
```

### 2. Harden SSH to key-only

Confirm your key works **before** disabling password authentication, or you will lock yourself out.

```shell
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sshd -t
systemctl restart ssh
```

Open a second terminal and confirm you can still log in before closing the first.

### 3. Base packages, firewall, and unattended upgrades

```shell
apt update && apt upgrade -y
apt install -y git curl ca-certificates ufw unattended-upgrades apt-listchanges

ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose
```

Port 8000 is deliberately **not** opened — Uvicorn binds to localhost only.

Enable automatic security updates:

```shell
dpkg-reconfigure -plow unattended-upgrades
systemctl status unattended-upgrades --no-pager
```

### 4. Create the 2 GB swapfile

This is not optional housekeeping. `deploy.sh` runs `npm ci && npm run build` on the VPS while the old process still holds torch, `sentence-transformers`, and the fitted PCA model resident. On 2 vCore / 4 GB that is a realistic OOM window, and an OOM mid-deploy leaves you with a half-built `dist/`.

```shell
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

sysctl -w vm.swappiness=10
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf

free -h
```

### 5. Cap journald retention

You are moving from Render's managed, rotated log stream to a box where nothing truncates logs unless you say so. Four SSE-streaming example apps emit a lot of structured events over months of always-on operation.

```shell
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/99-bws4.conf <<'EOF'
[Journal]
SystemMaxUse=500M
SystemMaxFileSize=50M
MaxRetentionSec=1month
EOF

systemctl restart systemd-journald
journalctl --disk-usage
```

### 6. Install uv, Node 20, and Caddy

`uv` downloads and pins its own Python 3.12, so Debian 13's system Python 3.13 is irrelevant.

```shell
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> /root/.bashrc
uv --version
```

Node 20 from NodeSource:

```shell
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
node --version && npm --version
```

Caddy **from Debian's own repository**:

```shell
apt install -y caddy
caddy version
```

> **Why not the Cloudsmith repo.** Debian 13 verifies APT signatures with `sqv`, which is stricter than the old `gpgv`, and Caddy's official Cloudsmith repository currently fails verification on trixie (`caddyserver/dist` issue #131: *"Signing key … is not bound: No binding signature"*). Debian ships `caddy` in main, so this route avoids the third-party keyring entirely. If you later need a newer Caddy than trixie packages, revisit the Cloudsmith instructions and check whether the signing issue has been resolved.

### 7. Create the secrets file — outside the repository tree

```shell
mkdir -p /etc/bws4
touch /etc/bws4/bws4.env
chown root:root /etc/bws4/bws4.env
chmod 0600 /etc/bws4/bws4.env
```

Populate it with your real values, copied from the Render dashboard:

```shell
nano /etc/bws4/bws4.env
```

Structure — **names shown, values yours**:

```
DATABASE_URL=
OPENROUTER_API_KEY=
GROQ_API_KEY=
EXA_API_KEY=
OPENAI_API_KEY=
CORS_ORIGIN=https://bwtemp.spec4.ai
SENTRY_DSN=
```

Verify permissions:

```shell
ls -l /etc/bws4/bws4.env   # expect -rw------- 1 root root
```

### 8. Clone the repository to `/srv/bws4`

```shell
mkdir -p /srv
git clone <YOUR_REPO_URL> /srv/bws4
cd /srv/bws4
git log --oneline -1
```

For a private repo, use a deploy key:

```shell
ssh-keygen -t ed25519 -f /root/.ssh/bws4_deploy -N ""
cat /root/.ssh/bws4_deploy.pub   # add as a read-only deploy key in your Git host
```

### 9. First manual build — verify before automating

Do this by hand once, so you learn where it breaks without a script hiding the error.

```shell
cd /srv/bws4
uv sync

cd /srv/bws4/frontend
npm ci
npm run build
ls -la dist/    # expect index.html plus hashed assets

cd /srv/bws4/backend
uv run alembic upgrade head
```

Migrations run against the external Neon `DATABASE_URL`. Since Render already has this schema applied, `upgrade head` should be a no-op — confirm it reports nothing to do rather than attempting changes.

Smoke-test the app in the foreground:

```shell
cd /srv/bws4/backend
set -a && . /etc/bws4/bws4.env && set +a
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Watch for the lifespan warm-up loading the embedding model and fitting the PCA projection. From a second SSH session:

```shell
curl -sS http://127.0.0.1:8000/api/health || curl -sS http://127.0.0.1:8000/docs -o /dev/null -w '%{http_code}\n'
```

`Ctrl-C` when satisfied.

### 10. Point DNS at the VPS for the staging origin

Create an `A` record for `bwtemp.spec4.ai` → VPS public IPv4 (and `AAAA` → IPv6 if assigned). **This must resolve before Caddy starts**, because Let's Encrypt validates over the public hostname.

Verify propagation from your local machine:

```shell
dig +short bwtemp.spec4.ai
dig +short AAAA bwtemp.spec4.ai
```

Do not proceed until this returns the VPS IP. Repeated failed ACME attempts can hit Let's Encrypt rate limits.

### 11. Install the systemd unit

```shell
cp /srv/bws4/deploy/bws4-api.service /etc/systemd/system/bws4-api.service
systemctl daemon-reload
systemctl enable --now bws4-api
systemctl status bws4-api --no-pager
journalctl -u bws4-api -n 50 --no-pager
```

Verify restart survival and that warm-up completes at boot:

```shell
systemctl restart bws4-api
sleep 20
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/docs
```

Verify it survives a reboot:

```shell
reboot
# reconnect after ~30s
systemctl is-enabled bws4-api
systemctl is-active bws4-api
```

Confirm exactly one worker:

```shell
systemctl show bws4-api -p ExecStart | grep -o 'workers 1'
ps -ef | grep uvicorn | grep -v grep
```

### 12. Install the Caddyfile and bring up HTTPS

```shell
cp /srv/bws4/deploy/Caddyfile /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl reload caddy
systemctl status caddy --no-pager
journalctl -u caddy -n 50 --no-pager
```

Watch the journal for successful certificate issuance. Then verify from your local machine:

```shell
curl -I https://bwtemp.spec4.ai
curl -I http://bwtemp.spec4.ai            # expect 308 redirect to HTTPS
curl -sS https://bwtemp.spec4.ai/api/health
curl -I https://bwtemp.spec4.ai/some/spa/route   # expect 200 via history fallback
echo | openssl s_client -connect bwtemp.spec4.ai:443 -servername bwtemp.spec4.ai 2>/dev/null | openssl x509 -noout -dates
```

Confirm port 8000 is not reachable from outside:

```shell
curl --max-time 5 http://<VPS_IP>:8000/    # must fail/time out
```

**Verify SSE streams progressively** — this is the check most likely to reveal an edge misconfiguration, and it will not show up in a status code:

```shell
curl -N -sS -X POST https://bwtemp.spec4.ai/api/react/run \
  -H 'Content-Type: application/json' \
  -d '{"question":"<a short test question>"}'
```

Events must arrive one at a time as they are produced, not all at once at the end.

### 13. Make the deploy script executable and run a full cycle

```shell
chmod +x /srv/bws4/deploy/deploy.sh
/srv/bws4/deploy/deploy.sh
```

Confirm the sequence completes: git pull → uv sync → npm build → alembic → restart, with the site healthy afterwards.

### 14. Configure Sentry and Better Stack

Add `SENTRY_DSN` to `/etc/bws4/bws4.env`, then:

```shell
systemctl restart bws4-api
```

For the frontend, export `VITE_SENTRY_DSN` in the environment where `deploy.sh` runs, or add it to the script's build step, then redeploy so Vite inlines it.

In Better Stack, create monitors at 3-minute intervals:

| Monitor | URL |
|---|---|
| SPA shell | `https://bwtemp.spec4.ai/` → later `https://bw.spec4.ai/` |
| API health | `https://bwtemp.spec4.ai/api/health` → later `https://bw.spec4.ai/api/health` |

Set up a status page and configure alert delivery. Test by stopping the service briefly:

```shell
systemctl stop bws4-api
# confirm the API monitor alerts while the SPA monitor stays green
systemctl start bws4-api
```

### 15. Phase 5 — behaviour-preservation acceptance pass

Work through every example app on `https://bwtemp.spec4.ai`: RAG, tool-use, embeddings, single-call, chained-calls, planning-agent, ReAct loop, orchestrated-subagents, multi-agent collaboration.

Confirm for each: correct results, progressive SSE delivery where applicable, and candid failure surfacing when allowance is exhausted.

Remember this spends real allowance from the **same** caps Render's traffic consumes. Run it in a quiet window.

```shell
journalctl -u bws4-api -f    # watch structlog output during the pass
```

Also confirm the first interaction after a fresh restart has **no warm-up wait** — this is the goal Render's cold starts broke and the main functional reason for the migration.

### 16. Phase 6 — lower TTL, cut over, retire Render

Ahead of the change, lower the TTL on `bw.spec4.ai` (e.g. to 300s) and wait for the old TTL to expire so the propagation window is short.

Edit the Caddyfile so its single site block is `bw.spec4.ai` and the `bwtemp.spec4.ai` block is removed:

```shell
nano /srv/bws4/deploy/Caddyfile
cp /srv/bws4/deploy/Caddyfile /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

Update `CORS_ORIGIN`:

```shell
sed -i 's|^CORS_ORIGIN=.*|CORS_ORIGIN=https://bw.spec4.ai|' /etc/bws4/bws4.env
grep CORS_ORIGIN /etc/bws4/bws4.env
```

Repoint the `A` record (and `AAAA`) for `bw.spec4.ai` from Render to the VPS IP. Then:

```shell
systemctl reload caddy
systemctl restart bws4-api
```

Verify:

```shell
dig +short bw.spec4.ai
curl -I https://bw.spec4.ai
curl -sS https://bw.spec4.ai/api/health
echo | openssl s_client -connect bw.spec4.ai:443 -servername bw.spec4.ai 2>/dev/null | openssl x509 -noout -dates
```

Update the Better Stack monitors to the canonical hostname. Once traffic is confirmed healthy:

```shell
cd /srv/bws4
git rm render.yaml
git commit -m "Retire Render: remove render.yaml after VPS cutover"
git push
```

Suspend or delete the Render service, and remove the `bwtemp.spec4.ai` DNS record and its Better Stack monitor. Restore a normal TTL on `bw.spec4.ai`.

---

## Configuration Files

### `deploy/bws4-api.service`

The systemd unit. `Restart=always` and `WantedBy=multi-user.target` keep the always-on instance running across crashes and reboots, so the boot-time model load and PCA fit stay warm for the process lifetime. **`--workers 1` is a hard invariant** — the loaded model, fitted projection, in-process peer message bus, and ReAct duplicate-guard cache are all per-process state. References variable names only.

```ini
[Unit]
Description=BWS4 API (FastAPI/Uvicorn)
Documentation=https://bw.spec4.ai
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=root
WorkingDirectory=/srv/bws4/backend

# Root-owned 0600 file OUTSIDE the repository tree.
# Supplies: DATABASE_URL, OPENROUTER_API_KEY, GROQ_API_KEY, EXA_API_KEY,
#           OPENAI_API_KEY, CORS_ORIGIN, and optional SENTRY_DSN.
EnvironmentFile=/etc/bws4/bws4.env

Environment=PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=PYTHONUNBUFFERED=1

# Single worker is mandatory, not incidental: the embedding model, fitted PCA
# projection, in-process message bus and ReAct duplicate-guard cache are all
# per-process state.
ExecStart=/root/.local/bin/uv run uvicorn app.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 \
    --no-access-log

Restart=always
RestartSec=3

# Generous startup window: the lifespan warm-up loads all-MiniLM-L6-v2 and
# fits the 2D PCA projection before the app reports ready.
TimeoutStartSec=300
TimeoutStopSec=30

StandardOutput=journal
StandardError=journal
SyslogIdentifier=bws4-api

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/srv/bws4

[Install]
WantedBy=multi-user.target
```

### `deploy/Caddyfile` — Phases 3–5 (staging origin)

Single site block on the temporary validation hostname. `handle /api/*` is ordered before the SPA fallback so API requests never fall through to `index.html`. `flush_interval -1` disables response buffering explicitly — Caddy does not buffer by default and detects `text/event-stream`, but stating it documents the intent and protects the four SSE example apps from a future default change.

```
bwtemp.spec4.ai {
	encode zstd gzip

	# API: reverse-proxy to Uvicorn on localhost.
	# flush_interval -1 keeps server-sent events streaming progressively
	# through the edge for the planning-agent, ReAct loop,
	# orchestrated-subagents and multi-agent collaboration apps.
	handle /api/* {
		reverse_proxy 127.0.0.1:8000 {
			flush_interval -1
			transport http {
				response_header_timeout 5m
				dial_timeout 5s
			}
		}
	}

	# SPA: serve the Vite bundle with history fallback so client-side
	# routes deep-link and survive a refresh.
	handle {
		root * /srv/bws4/frontend/dist
		try_files {path} /index.html
		file_server

		# Hashed assets are immutable; the shell must never be cached.
		@hashed path_regexp \.[0-9a-f]{8,}\.(js|css|woff2?|png|jpe?g|svg|webp)$
		header @hashed Cache-Control "public, max-age=31536000, immutable"

		@shell path /index.html /
		header @shell Cache-Control "no-cache, must-revalidate"
	}

	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "strict-origin-when-cross-origin"
		-Server
	}

	log {
		output file /var/log/caddy/bws4.log {
			roll_size 20MiB
			roll_keep 5
		}
		format json
	}
}
```

### `deploy/Caddyfile` — Phase 6 (canonical origin)

Replaces the above at cutover. Identical apart from the hostname; the `bwtemp` block is removed entirely.

```
bw.spec4.ai {
	encode zstd gzip

	handle /api/* {
		reverse_proxy 127.0.0.1:8000 {
			flush_interval -1
			transport http {
				response_header_timeout 5m
				dial_timeout 5s
			}
		}
	}

	handle {
		root * /srv/bws4/frontend/dist
		try_files {path} /index.html
		file_server

		@hashed path_regexp \.[0-9a-f]{8,}\.(js|css|woff2?|png|jpe?g|svg|webp)$
		header @hashed Cache-Control "public, max-age=31536000, immutable"

		@shell path /index.html /
		header @shell Cache-Control "no-cache, must-revalidate"
	}

	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "strict-origin-when-cross-origin"
		-Server
	}

	log {
		output file /var/log/caddy/bws4.log {
			roll_size 20MiB
			roll_keep 5
		}
		format json
	}
}
```

### `deploy/deploy.sh`

The whole release in one readable, version-controlled file. It sources **no secrets of its own** — runtime variables reach the app solely through the systemd `EnvironmentFile`. `VITE_SENTRY_DSN` is the exception and must be exported into the build environment explicitly, because Vite consumes it at build time. References variable names only.

```bash
#!/usr/bin/env bash
#
# BWS4 release script — run ON the VPS as root.
#
#   git pull -> uv sync -> npm ci && npm run build -> alembic upgrade head
#   -> systemctl restart bws4-api
#
# Runtime secrets are NOT handled here: they reach the application through
# systemd's EnvironmentFile at /etc/bws4/bws4.env.
#
# BUILD-time variables required by Vite must be exported into the environment
# of the `npm run build` step, because the systemd EnvironmentFile does not
# apply to the build. VITE_SENTRY_DSN is the only such variable.
#
# A release is a brief restart. The embedding model load and PCA projection
# fit are re-paid at boot, and in-flight SSE streams are cut.

set -euo pipefail

REPO_DIR="/srv/bws4"
FRONTEND_DIR="${REPO_DIR}/frontend"
BACKEND_DIR="${REPO_DIR}/backend"
DIST_DIR="${FRONTEND_DIR}/dist"
SERVICE="bws4-api"
ENV_FILE="/etc/bws4/bws4.env"
UV="/root/.local/bin/uv"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31mFAILED:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "must run as root"
[[ -f "$ENV_FILE" ]] || fail "missing ${ENV_FILE}"
command -v "$UV" >/dev/null || fail "uv not found at ${UV}"
command -v npm >/dev/null || fail "npm not found"

log "Pulling latest revision"
cd "$REPO_DIR"
git pull --ff-only
git log --oneline -1

log "Syncing Python dependencies"
cd "$REPO_DIR"
"$UV" sync --frozen

# Vite inlines VITE_* at build time. Export it here if set in the invoking
# environment; the build succeeds without it and simply omits frontend Sentry.
log "Building frontend bundle"
cd "$FRONTEND_DIR"
if [[ -n "${VITE_SENTRY_DSN:-}" ]]; then
  echo "    VITE_SENTRY_DSN is set; frontend Sentry will be enabled"
  export VITE_SENTRY_DSN
else
  echo "    VITE_SENTRY_DSN unset; frontend Sentry will be disabled"
fi
npm ci
npm run build
[[ -f "${DIST_DIR}/index.html" ]] || fail "build produced no ${DIST_DIR}/index.html"

log "Applying database migrations (external Neon)"
cd "$BACKEND_DIR"
set -a; . "$ENV_FILE"; set +a
"$UV" run alembic -c alembic.ini upgrade head
unset DATABASE_URL OPENROUTER_API_KEY GROQ_API_KEY EXA_API_KEY \
      OPENAI_API_KEY CORS_ORIGIN SENTRY_DSN

log "Restarting ${SERVICE}"
systemctl restart "$SERVICE"

log "Waiting for warm-up (model load + PCA fit)"
for i in $(seq 1 60); do
  if curl -fsS -o /dev/null --max-time 3 http://127.0.0.1:8000/docs; then
    log "Service healthy after ${i}s"
    systemctl status "$SERVICE" --no-pager | head -n 12
    log "Deploy complete"
    exit 0
  fi
  sleep 1
done

journalctl -u "$SERVICE" -n 60 --no-pager
fail "service did not become healthy within 60s"
```

### `CLAUDE.md` (repo root)

Persistent context so every Claude Code session starts with the invariants that matter.

```markdown
# BWS4 — Agent Context

## Hard invariants

- **Secrets never enter the repository.** Runtime configuration lives in
  `/etc/bws4/bws4.env` on the VPS — root-owned, chmod 0600, outside the
  repository tree. Never create a `.env` file inside this repo. Committed
  files reference environment variable NAMES only, never values.
- **The API runs with `--workers 1`.** This is a requirement, not a default.
  The loaded embedding model, the fitted PCA projection, the in-process peer
  message bus and the ReAct duplicate-guard cache are all per-process state.
  Never add workers, never suggest Gunicorn with multiple workers.
- **Postgres is external.** Neon + pgvector, unchanged by the VPS migration.
  Never propose installing Postgres on the host.

## Deployment shape

- Host: netcup VPS 500 G12, Debian 13 (trixie), 2 vCore / 4 GB / 128 GB NVMe
- Repo on host: `/srv/bws4`; frontend build output: `/srv/bws4/frontend/dist`
- Caddy serves `dist/` with SPA history fallback, reverse-proxies `/api/*`
  to `127.0.0.1:8000` with `flush_interval -1`
- systemd unit: `bws4-api`; release script: `deploy/deploy.sh`
- Canonical origin: `https://bw.spec4.ai` (staging: `https://bwtemp.spec4.ai`)

## Environment contract (names only)

Required: `DATABASE_URL`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`,
`EXA_API_KEY`, `OPENAI_API_KEY`, `CORS_ORIGIN`
Optional: `SENTRY_DSN` (runtime), `VITE_SENTRY_DSN` (build-time only —
the systemd EnvironmentFile does NOT reach `npm run build`)

## Quality gates (developer-run, no CI)

`ruff`, `mypy`, `pytest`, `vitest` — run before push.
```

---

## Notes

### Cost

| Item | Cost |
|---|---|
| netcup VPS 500 G12 (12-month) | ~€5.91/mo (~$6.81) |
| Neon Postgres + pgvector | Free tier |
| Caddy, systemd, Debian | Free |
| Sentry | Free (5k errors/mo, 1 user) |
| Better Stack | Free (10 monitors, 3-min checks) |
| **Total** | **~€6/mo** |

Note netcup's traffic policy: if average network traffic over 24h exceeds 2 TB, throughput is temporarily throttled to 200 Mbit/s. Irrelevant at this scale.

### Non-functional goals — what this deployment delivers

**Settled by this deployment:**

- **`nfr_immediately_responsive…no warm-up wait at any time of day`** — this is the migration's central win. The always-on VPS with `Restart=always` means the FastAPI lifespan loads the embedding model and fits the PCA projection **once at boot**, and it stays resident for the process lifetime. Render's free tier cold-started and made every first visitor pay that cost. 4 GB of guaranteed ECC RAM also removes the memory pressure that made warm-up unreliable. Delivered by steps 11 and 4.
- **`nfr_pages_appear_within_about_a_second, and model-driven results appear progressively`** — European datacenter selection (step 1) for latency to the primary audience; `encode zstd gzip` and immutable cache headers on hashed assets for the static bundle; `flush_interval -1` on the API proxy so SSE events reach the browser as produced rather than buffered at the edge. Verified explicitly in step 12 — a status-code check alone would not catch buffering.
- **`nfr_continuously_reachable at one canonical public address over a connection visitors' browsers trust`** — Caddy terminates TLS with automatic Let's Encrypt issuance and **in-process renewal**, which makes an expired certificate structurally hard rather than merely scheduled; HSTS and automatic HTTP→HTTPS redirect; `systemd Restart=always` plus `WantedBy=multi-user.target` for crash and reboot survival. Critically, the stack's claims here cover only process and certificate lifecycle — they cannot detect host-level failure, which is why **external Better Stack monitoring is part of satisfying this goal, not an optional extra.**
- **`nfr_comfortable_for_tens_of_visitors_exploring_at_the_same_time`** — single Uvicorn process with async concurrency on 2 vCore / 4 GB. Adequate for tens of concurrent visitors given the workload is I/O-bound on model and search APIs. The swapfile guards the build-time memory spike rather than steady-state load.

**Addressed but not fully satisfied — stated plainly:**

- **`nfr_content_and_example_apps_can_be_updated_while_the_gallery_keeps_running, without interrupting visitors`** — **no stack component claims this goal, and this deployment does not satisfy it either.** `release_delivery` states a release is a brief restart during which warm state is rebuilt at boot. With a single Uvicorn worker holding the embedding model, fitted PCA, message bus, and duplicate-guard cache as per-process state, blue-green or rolling deploys are unavailable without a second process — and a second process would violate the single-worker invariant the stack requires. **Consequence: each deploy causes an interruption of roughly the model-load time, and in-flight SSE streams are cut.** Mitigation is operational, not architectural: deploy during quiet periods, keep releases deliberate and infrequent, and use the Better Stack status page to communicate the window. If this goal later becomes a hard requirement it needs a stack change — an out-of-process model server, or externalised message bus and projection cache — not a deployment change.

**The coding agent's to satisfy, not this deployment's:**

- `nfr_total_model_and_search_usage_stays_within_a_free_usage_allowance` — enforced by the `allowance_holds`, `react_run_allowance`, and `issued_query_embeddings` code paths and the shared quota gate. No hosting choice caps API spend. Deployment's only contribution is the shared-allowance warning below.
- `nfr_every_failure…is_surfaced_candidly_and_actionably, never as a hang` — application error handling in `agent_loop_runtime` and the per-app allowance gates. Sentry will *report* failures to you; it cannot make them candid to a visitor.
- `nfr_each_example_app_teaches_its_pattern_well_enough…without_reading_any_source` — `educational_overviews` content.
- `nfr_every_example_app_shares_one_consistent_layout_and_navigation` and `nfr_usable_in_current_browsers…legible_on_smaller_screens` — Tailwind CSS and component structure.
- `nfr_a_new_example_app_can_be_added…without_altering_any_existing_app` — React Router plus the `example_app_directory` pattern. Vite's per-app code-splitting keeps this cheap at the bundle level, but the extensibility itself is code.

### Migration-specific cautions

- **Shared allowance during Phases 1–5.** Both hosts run against the same Neon database, so the acceptance pass consumes the *same* hourly and daily caps Render's live traffic does. Run it in a quiet window and expect to hit caps sooner than normal.
- **DNS before Caddy.** `bwtemp.spec4.ai` must resolve before Caddy first starts (step 10). Let's Encrypt validates over the public hostname, and repeated failed ACME attempts risk rate limits.
- **Migrations are expected to be a no-op.** Render already applied this schema to the same Neon database. If `alembic upgrade head` attempts changes in step 9, stop and investigate — that indicates a revision mismatch, not a normal first deploy.
- **Verify SSE streaming explicitly.** A buffering misconfiguration returns HTTP 200 and looks healthy. Use `curl -N` (step 12) and confirm events arrive incrementally.
- **Caddy from Debian, not Cloudsmith.** The upstream repo currently fails `sqv` signature verification on trixie. Revisit if you need a newer Caddy.
- **Test the firewall claim.** Actually confirm `http://<VPS_IP>:8000/` is unreachable from outside rather than assuming ufw is correct.

### Roadmap — recorded, not provisioned

- `remark-gfm` (optional library)
- `Playwright` (deferred library) — end-to-end tests. If adopted, Playwright would be the natural forcing function for introducing CI, which is out of scope this round.
- **CI/CD** — no CI exists in the tree; adding one is explicitly out of this revision's scope. When you do, GitHub Actions running the existing gates and then SSH-ing `deploy.sh` is the smallest sensible step.
- **`fail2ban`** — considered and skipped; key-only SSH makes brute-forcing pointless.
- **netcup Copy-On-Write snapshots** — worth enabling once the migration has settled. Lower priority than it sounds: Neon holds all durable data, and the VPS is fully reconstructible from the repo plus `/etc/bws4/bws4.env`.
- **Backups.** Durability rests entirely on Neon, which is correct — the VPS holds no source-of-truth data. The one irreplaceable thing on the host is `/etc/bws4/bws4.env`; keep those credentials in your password manager independently, since a lost VPS means re-entering them by hand.