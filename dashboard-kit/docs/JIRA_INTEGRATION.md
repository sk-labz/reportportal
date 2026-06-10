# Jira Integration (`plugin-bts-jira`)

This is the Phase 2 implementation of the Jira item from `PHASE2_ROADMAP.md`.
Like SSO, most of this is configured through the Admin UI rather than
compose/env files; this doc sequences that configuration and an optional
automation script (`configure_bts_jira.py`) for teams that want to manage
their Jira mapping as config instead of clicking through the UI per project.

## 1. Install the plugin (one-time, ADMINISTRATOR only)

1. **Administrate → Plugins**.
2. The Jira Server / Jira Cloud plugin (`plugin-bts-jira`) ships with
   ReportPortal's plugin set and is loaded automatically by the `jobs`
   service's plugin-loading cron
   (`COM_TA_REPORTPORTAL_JOB_LOAD_PLUGINS_CRON`, already set in
   `docker-compose.yml`). If it doesn't appear, check `jobs` service logs
   for plugin-load errors.
3. Confirm the "JIRA Server" and/or "JIRA Cloud" panels are visible and
   enabled.

## 2. Global vs. per-project configuration

Two scopes are available; **per-project is recommended** for this kit's
multi-team model (matches the per-team-project structure from Phase 1 — see
`dashboard-kit/README.md` → "Why per-project, not one global dashboard?"):

| Scope | Pros | Cons |
|-------|------|------|
| Global (Administrate → Plugins → JIRA) | Configure once, applies to all projects without their own config | All teams share one Jira project/credentials — doesn't fit "each team owns their Jira project" |
| Per-project (Project Settings → Integrations) | Each team configures their own Jira project + credentials; teams can't see each other's BTS config | Must be repeated per project (mitigated by `configure_bts_jira.py` below) |

If most teams share one Jira instance/project, configure global once as a
fallback, then add per-project overrides only for teams with their own Jira
project (unlink from global first: Project Settings → Integrations → Jira →
"Unlink from global").

## 3. Required fields per integration

**Jira Server / Data Center:**
- Integration Name (unique)
- Link to BTS (Jira base URL)
- Project key in BTS (e.g. `CHK` for the Checkout team's Jira project)
- Authorization Type: Basic
- BTS Username + BTS Password/API Token (service account recommended)

**Jira Cloud:**
- Integration Name (unique)
- Link to BTS (`https://<your-domain>.atlassian.net`)
- Project key in BTS
- Email (service account)
- API Token (https://id.atlassian.com/manage-profile/security/api-tokens)

## 4. Mapping table (fill in for your org)

One row per project in `dashboard-kit/config/teams.yml`:

| RP project           | Jira URL                          | Jira project key | Auth        |
|------------------------|-------------------------------------|---------------------|--------------|
| `payments_checkout`    | `https://example.atlassian.net`     | `CHK`               | Cloud (email + API token) |
| `payments_fraud`       | `https://example.atlassian.net`     | `FRD`               | Cloud (email + API token) |
| `platform_search`      | `https://jira.example.com`          | `SRCH`              | Server (basic) |

## 5. Defect-type → Jira issue-type mapping

`dashboard-kit/config/widgets/failure_defect_breakdown.json`'s "Defect Type
Breakdown" widget already segments failures by RP's defect types
(`product_bug`, `automation_bug`, `system_issue`, `no_defect`,
`to_investigate` — configurable per project under Project Settings → Defect
Types). When posting a failed test item to Jira, RP lets you pick the Jira
issue type per post; for consistency, agree on a mapping up front:

| RP defect type    | Jira issue type   |
|--------------------|--------------------|
| `product_bug`      | Bug                |
| `automation_bug`   | Task (or "Test Defect" if your Jira has one) |
| `system_issue`     | Bug (label: `infra`) |
| `to_investigate`   | (don't auto-post — triage first) |
| `no_defect`        | (never post)       |

Document this mapping per Jira project if issue-type names differ (e.g. some
Jira projects use "Defect" instead of "Bug").

## 6. Optional: automate per-project configuration

For teams that prefer config-as-code over the UI flow in steps 2–4:

```bash
cd dashboard-kit
cp config/jira.example.yml config/jira.yml   # git-ignored, like teams.yml
# edit config/jira.yml with the mapping table values from section 4

export RP_API_URL=https://<RP_DOMAIN>/api
export RP_API_TOKEN=<token>

python3 configure_bts_jira.py --dry-run
python3 configure_bts_jira.py
```

> ⚠️ **VERIFY before a non-dry-run execution**: `configure_bts_jira.py` POSTs
> to `/v1/{project}/integration/jira` (or `/v1/{project}/integration` with a
> Jira-specific body — exact path and payload schema flagged in the script).
> This endpoint/schema is **not confirmed** against a live RP 5.15 instance.
> Use `--dry-run` first and compare the printed request against your
> instance's Swagger UI (`Integration` controller) before running for real.
> If the schema doesn't match, the UI flow in steps 2–4 always works as a
> fallback.

## 7. After configuring

- Re-open the **Failure & Defect Breakdown** dashboard
  (`dashboard-kit/config/dashboards/dashboard_failure_defect_breakdown.json`)
  and confirm failed items now show a "Post to Jira" / "Link issue" action in
  the RP UI.
- Test end-to-end on one non-critical failed item per project before relying
  on it broadly.
