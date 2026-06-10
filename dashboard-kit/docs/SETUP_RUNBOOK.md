# ReportPortal Setup Runbook — hosted instance + dashboard kit + CI

This runbook sequences everything needed to go from "nothing deployed" to
"stakeholders have dashboards and teams' CI is reporting into them," using
the files in this repo. SSO and Jira integration have their own runbooks
once the instance is up — see
[`SSO_SETUP.md`](SSO_SETUP.md) and [`JIRA_INTEGRATION.md`](JIRA_INTEGRATION.md).
[`PHASE2_ROADMAP.md`](PHASE2_ROADMAP.md) tracks what's implemented vs. what
still needs your IdP/Jira specifics, plus future dashboard-cleanup tooling.

## 1. Prerequisites

- A Linux VM (or equivalent) with Docker Engine 20.10+ and Docker Compose
  v2 installed. Sized for ~16GB RAM / 4 vCPU as a baseline (matches the
  resource limits in `../../docker-compose.prod.yml`); adjust those limits if
  your host is bigger/smaller.
- A DNS record (e.g. `reportportal.example.com`) pointing at the host's
  public IP.
- Inbound ports 80 and 443 open to that host (port 80 is needed for the
  Let's Encrypt HTTP-01 challenge as well as the HTTP→HTTPS redirect).

## 2. Deploy ReportPortal (production)

From the repo root:

```bash
# 1. Create your env file
cp .env.production.example .env
# edit .env: set strong POSTGRES_PASSWORD / RABBITMQ_DEFAULT_PASS /
# RP_INITIAL_ADMIN_PASSWORD, and set RP_DOMAIN + ACME_EMAIL.

# 2. Create the ACME storage file Traefik will write certs into
touch acme.json && chmod 600 acme.json

# 3. (Recommended first run) point at Let's Encrypt's STAGING CA to avoid
#    hitting production rate limits while you validate DNS/ports. Add this
#    line to the `gateway: command:` list in docker-compose.prod.yml:
#      - --certificatesresolvers.letsencrypt.acme.caserver=https://acme-staging-v02.api.letsencrypt.org/directory
#    Remove it once you've confirmed a staging cert is issued successfully.

# 4. Validate the merged compose config
docker compose -f docker-compose.yml -f docker-compose.prod.yml config

# 5. Bring up the core stack (add `--profile ''` too if you want OpenSearch +
#    the auto-analyzer for ML-based failure analysis)
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile core up -d
```

Verify:
- `docker compose logs -f gateway` shows ACME certificate issuance succeeding.
- `https://<RP_DOMAIN>/ui` loads over HTTPS with a valid certificate (once
  you've removed the staging CA line and re-run `up -d`, repeat the cert
  issuance check for the production cert).

### First login

- URL: `https://<RP_DOMAIN>/ui`
- User: `superadmin` / password: the `RP_INITIAL_ADMIN_PASSWORD` you set in `.env`
- Immediately change this password via the UI, then update `.env`'s
  `RP_INITIAL_ADMIN_PASSWORD` to match (for documentation/rotation purposes —
  it only takes effect on first container start).
- Generate an API token: profile menu → **API Keys** → Generate. Save it as
  `RP_API_TOKEN` for the dashboard-kit step below.

## 3. Backup setup

Add a daily cron job on the host (adjust paths/retention to your environment):

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt/reportportal   # wherever this repo is checked out
mkdir -p backups
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c \
  > "backups/postgres-$(date +%F).dump"
docker run --rm \
  -v reportportal_storage:/data:ro \
  -v "$(pwd)/backups":/backup \
  alpine tar czf "/backup/storage-$(date +%F).tgz" -C / data
find backups -mtime +14 -delete   # 14-day local retention; copy off-box too
```

Copy `backups/` off the host (S3, NFS, etc.) on the same schedule. Restoring
is the reverse: `pg_restore` into a fresh `postgres` volume, and `tar xzf`
the storage archive back into the `storage` volume.

## 4. Create per-team projects

In the RP UI: **Administrate → Projects → Add Project**, one per team, named
per the convention `<businessunit>_<team>` (e.g. `payments_checkout`,
`payments_fraud`, `platform_search`). Optionally also create one umbrella
project per business unit (e.g. `payments_overview`) — see
`../README.md` → "Why per-project, not one global dashboard?".

Alternatively, set `create: true` on a project's entry in `config/teams.yml`
(step 5) and let `provision_dashboards.py` create it for you — see the ⚠️
VERIFY note on `RPClient.create_project` in `../provision_dashboards.py`
before relying on this for a real rollout.

## 5. Provision the dashboard kit

```bash
cd dashboard-kit
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp config/teams.example.yml config/teams.yml
# edit config/teams.yml: list the projects created in step 4

export RP_API_URL=https://<RP_DOMAIN>/api
export RP_API_TOKEN=<token from step 2>

python3 provision_dashboards.py --dry-run   # review the planned calls
python3 provision_dashboards.py             # apply
```

By default every project gets the **3 standard dashboards** (Pass/Fail
Trends, Failure & Defect Breakdown, Team/Project Comparison) plus the **3
extended dashboards** (Test Layer Breakdown, Release/Sprint Report, Duration
& Flakiness Trends). Set `extended_dashboards: false` per project in
`config/teams.yml` to opt a project out of the extended set, and
`build_attribute_key` if a project tags releases with something other than
`version:` (e.g. `build:`) — see `config/teams.example.yml`.

Verify: open each project's **Dashboards** tab and confirm the dashboards
listed in `../README.md` are present (widgets will show "no data" until step
6 produces launches). Use `python3 provision_dashboards.py --list-existing`
at any time for a read-only audit of what's currently provisioned per
project.

> Before this step, read `../README.md` → "⚠️ Before your first non-dry-run
> execution: VERIFY field names" — RP REST contracts can shift between minor
> versions, and the script surfaces 4xx bodies verbatim to help you fix any
> mismatched template quickly.

### 5a. Optional: automate provisioning via GitHub Actions

`.github/workflows/provision-dashboards.yml` (repo root) runs
`provision_dashboards.py --dry-run` on PRs touching `dashboard-kit/config/**`
and the real run on push to the default branch. It's skipped (with a notice)
until you set the `RP_API_URL`/`RP_API_TOKEN` repo secrets, and needs
`config/teams.yml` to be available in CI (it's git-ignored by default — see
the comments at the top of that workflow file for options).

## 6. Onboard each team's CI (GitHub Actions)

For each team:

1. Copy the relevant template from `../ci-examples/` into that repo's
   `.github/workflows/` — covers JUnit5, TestNG, pytest, Jest, Cypress,
   Postman/Newman, Playwright, .NET NUnit, and Robot Framework (see
   `../ci-examples/ATTRIBUTES.md` for the full list).
2. Add repo secrets: `RP_ENDPOINT`, `RP_API_KEY` (a project- or
   service-account API token), `RP_PROJECT` (the project key from step 4).
3. Set `RP_LAUNCH` and the `team`/`layer`/`service` (and optionally
   `version`/`build`) attributes per `../ci-examples/ATTRIBUTES.md`.
4. Push/run the workflow, then confirm in the RP UI:
   - The launch appears under the right project with the expected attributes.
   - The dashboards from step 5 start populating (Overall Statistics, Recent
     Launches, Component Health by Service, etc.).

Repeat for each team's API, UI, integration, and unit-test pipelines —
each can be its own launch (with an appropriate `layer:` value) within the
same project, or split across multiple projects if a team owns multiple
services.

## 7. What's next

Once dashboards are live and CI is reporting consistently:

- [`SSO_SETUP.md`](SSO_SETUP.md) — configure SAML/LDAP/Active Directory.
- [`JIRA_INTEGRATION.md`](JIRA_INTEGRATION.md) — link failures to Jira issues.
- [`PHASE2_ROADMAP.md`](PHASE2_ROADMAP.md) — overall status tracker and
  future dashboard-cleanup tooling for any pre-existing instances.
