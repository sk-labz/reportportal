# ReportPortal Dashboard Kit

Provisions a consistent set of dashboards into ReportPortal projects via the
REST API, so every team and stakeholder sees the same layout:

**Standard dashboards** (every project):

1. **Pass/Fail Trends & Launch Health** — overall stats, passing rate, trend
   over the last 30 launches, and a recent-launches table.
2. **Failure & Defect Breakdown** — top failing tests, defect-type
   classification, flaky tests.
3. **Team / Project Comparison** — recent launches with their `team:`/
   `layer:`/`service:` attributes, and a `componentHealthCheck` widget
   grouped by `service`.

**Extended dashboards** (every project, unless `extended_dashboards: false`):

4. **Test Layer Breakdown** — `componentHealthCheck` grouped by the `layer`
   attribute (api/ui/integration/unit), plus a recent-launches view.
5. **Release / Sprint Report** — passing rate, defect summary, cumulative
   trend, and a side-by-side comparison across the most recent
   release-tagged launches (`version:`/`build:` attribute, see
   `build_attribute_key`).
6. **Duration & Flakiness Trends** — execution duration trend, test-case
   growth trend, and a wider-window flaky-test view.

An optional 7th dashboard, **Org Quality Overview**, is provisioned into
"umbrella" projects (see below) for a cross-team rollup.

## Why per-project, not one global dashboard?

ReportPortal's open-source dashboards/widgets/filters are scoped to a single
project — there's no built-in cross-project widget. This kit takes a hybrid
approach:

- **Every team project** (`mode: team`) gets the same 3 dashboards. Stakeholders
  switch projects in the RP UI and see the same layout — "centralized" in the
  sense of *consistent*, even if not literally one page.
- **Optional umbrella project(s)** (`mode: umbrella`, e.g. `payments_overview`)
  provide a true single-page, cross-team view via `componentHealthCheck`,
  *if* teams additionally report (or duplicate-report) launches into that
  project tagged with the `team:`/`layer:`/`service:` attributes described in
  [`ci-examples/ATTRIBUTES.md`](ci-examples/ATTRIBUTES.md).

See `dashboard-kit/docs/SETUP_RUNBOOK.md` for the end-to-end deployment +
provisioning sequence.

## Prerequisites

- A running ReportPortal instance (see `../docker-compose.yml` /
  `../docker-compose.prod.yml`) and the projects you want to provision already
  created (Admin → Projects → Add Project).
- An RP user with Project Admin (or org Admin) rights on those projects.
- An **API token**: log in to RP, open your user profile menu → **API Keys**
  (or Access Tokens) → generate a token. Treat it as a secret — it's used as
  a Bearer token.

## Setup

```bash
cd dashboard-kit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config/teams.example.yml config/teams.yml
# edit config/teams.yml with your real project keys (config/teams.yml is
# git-ignored so internal team/project structure doesn't have to be public)

export RP_API_URL=https://reportportal.example.com/api
export RP_API_TOKEN=<your-api-token>
```

## Usage

```bash
# 1. Preview what would be created/updated (still does read-only GETs against
#    --api-url to check what already exists; performs no POST/PUT/DELETE).
python3 provision_dashboards.py --dry-run

# 2. Provision for real
python3 provision_dashboards.py

# Single project, ad-hoc (bypasses config/teams.yml)
python3 provision_dashboards.py --project payments_checkout --mode team

# Single umbrella project with per-team drill-down filters
python3 provision_dashboards.py --project payments_overview --mode umbrella \
  --group-by-attribute team --teams checkout,fraud

# Skip the Phase 2 extended dashboards for a project
python3 provision_dashboards.py --project platform_search --no-extended-dashboards

# This team tags releases with `build:<n>` instead of `version:`
python3 provision_dashboards.py --project payments_fraud --build-attribute-key build

# Create the project if it doesn't exist yet (VERIFY: see RPClient.create_project)
python3 provision_dashboards.py --project new_team --create-project \
  --project-description "New team test results"

# Read-only audit: list existing filters/widgets/dashboards per project
python3 provision_dashboards.py --list-existing
```

After running, open each project's **Dashboards** tab in the RP UI — you
should see the dashboards listed above. Widgets show "no data" until launches
with the right attributes start arriving (see the CI examples).

## Idempotency

The script is safe to re-run:

- **Filters/widgets**: looked up by `name` first. If found, they're reused
  as-is unless `--force` is passed (which `PUT`s the template over the
  existing item — review the diff before doing this on a shared instance).
- **Dashboards**: looked up by `name`. If found, only widgets *not already
  attached* are added (existing widget positions/sizes are left alone).

`--force` does **not** delete dashboards/widgets/filters that are no longer
referenced by the templates — that's intentionally left for the Phase 2
cleanup tooling described in `docs/PHASE2_ROADMAP.md`.

## ✅ Verified end-to-end against a live RP 5.15.x sandbox

The full flow below has been run against a live ReportPortal 5.15.x instance
(filters → widgets → dashboards → real seeded launch data, for both `team`
and `umbrella` modes, plus `--list-existing`, `--create-project`, idempotent
re-runs, and `--no-extended-dashboards`/`--build-attribute-key` overrides).
Along the way several payload shapes that were originally guessed turned out
to differ from what's documented; the templates and script in this kit
already reflect the corrected, confirmed shapes:

- **Filters** (`POST /v1/{project}/filter`) use top-level `conditions`/`orders`
  (not `entities`/`selectionParameters`). The "match everything" filter uses
  `{"filteringField": "name", "condition": "ne", "value": "__no_such_launch_name__"}`
  (RP rejects empty condition values).
- **Widget existence checks**: `GET /v1/{project}/widget` is `405`, and
  `/widget/names/all` returns names without IDs — so `provision_dashboards.py`
  determines widget reuse from the **dashboard's own widget list**
  (`GET /v1/{project}/dashboard/{id}` → `widgets[].widgetId`/`widgetName`),
  not a standalone widget registry.
- `mostFailedTestCases` is **not** a valid `widgetType` — use `topTestCases`.
- `topTestCases` and `casesTrend` require **exactly one** `contentFields` entry.
- `topTestCases` and `flakyTestCases` require `widgetOptions.launchNameFilter`
  (`"%"` is accepted at creation time as a wildcard, but returned **empty
  content** in this sandbox — a real launch name returned real data; teams
  may need to edit this in the UI to one of their actual launch names).
- `componentHealthCheck` requires `widgetOptions.attributeKeys` (an **array**,
  not singular `attributeKey`), plus `minPassingRate` (string percentage) and
  `excludeSkipped` (string `"true"`/`"false"`). Its content is fetched via
  `GET /v1/{project}/widget/multilevel/{id}`, not `/widget/{id}` — confirmed
  working with real per-attribute-value pass rates.
- `launchesComparisonChart` needs `widgetOptions.attributeKeys` set, or
  content-loading throws a server-side SQL error (creation still succeeds
  either way).
- **Project create/lookup** (`POST /v1/project`, `GET /v1/project/{name}` →
  200/404) work exactly as implemented in `RPClient`.

### Known remaining gaps

- `cumulative` widgets create successfully but returned **empty content** via
  both `/widget/{id}` and `/widget/multilevel/{id}` in this sandbox — the RP
  UI dashboard view may use parameters not exercised here. If "Cumulative
  Release Trend" renders empty for you too, this is a known gap.
- **`--force` on an existing `launchesComparisonChart` widget corrupted it**
  (`widgetType`/`contentParameters` became `null`) in this sandbox. Avoid
  `--force` for that widget; a fresh (non-`--force`) run creates it correctly.
  If one gets into a bad state, delete/recreate it via the RP UI.
- `statistics$defects$<type>$total` sub-type tokens
  (`product_bug`/`automation_bug`/`system_issue`/`no_defect`/`to_investigate`)
  are accepted at widget-creation time, but their data correctness depends on
  your project's Defect Types configuration (Project Settings → Defect Types)
  — confirm once real failed/triaged items exist.

If a `--dry-run` GET or a real run returns a 4xx/5xx, the script prints the
response body verbatim — use that to adjust the relevant template under
`config/`.

## Layout

```
docker-compose.sso.yml      # SAML SP entity ID overlay (see docs/SSO_SETUP.md)
.github/workflows/
  provision-dashboards.yml  # optional: auto-run this script on config/ changes

dashboard-kit/
  provision_dashboards.py   # the script described above
  configure_bts_jira.py     # optional Jira integration automation (see docs/JIRA_INTEGRATION.md)
  scripts/
    seed_demo_data.py        # dev/demo only: seed sample launches into a project for trying out the dashboards
  requirements.txt
  config/
    teams.example.yml       # copy to teams.yml and edit
    jira.example.yml        # copy to jira.yml and edit (configure_bts_jira.py)
    filters/                # reusable saved filters (POST /v1/{project}/filter)
    widgets/                # widget definitions grouped by dashboard
    dashboards/             # dashboard name + ordered widget list
  ci-examples/               # GitHub Actions snippets for reporting into RP
  docs/
    SETUP_RUNBOOK.md
    SSO_SETUP.md
    JIRA_INTEGRATION.md
    PHASE2_ROADMAP.md
```
