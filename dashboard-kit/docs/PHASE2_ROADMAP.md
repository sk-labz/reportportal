# Phase 2 Roadmap: SSO, Jira Integration, Dashboard Cleanup

These items were explicitly deferred from Phase 1 (see
`SETUP_RUNBOOK.md`) because they require company-specific inputs (an
identity provider, a Jira instance, and/or an existing live RP deployment to
clean up) that weren't available when this kit was built. Nothing in Phase 1
blocks these — the project structure and attribute conventions
(`team:`/`layer:`/`service:`) carry forward unchanged.

## SSO (SAML / LDAP / OAuth)

ReportPortal authentication is handled by the `service-authorization` (`uat`)
service. Configuration is via environment variables on that service in
`docker-compose.yml` / `docker-compose.prod.yml`.

What's needed before this can be implemented:
- **Identity provider type and details**:
  - SAML: IdP metadata URL/XML, entity ID, ACS URL expectations.
  - LDAP/Active Directory: server URL, bind DN/credentials, user/group search
    bases and filters.
  - OAuth/OIDC (e.g. Okta, Azure AD, Google Workspace): client ID/secret,
    issuer URL, redirect URI (`https://<RP_DOMAIN>/uat/...`).
- **Role/permission mapping**: how IdP groups map to RP project roles
  (Project Admin/Member/Viewer) per project created in step 4 of the runbook.

High-level steps once those are known:
1. Add the relevant `RP_AUTH_SAML_*` / `RP_LDAP_*` / OAuth provider env vars
   to the `uat` service (a new `docker-compose.sso.yml` overlay, analogous to
   `docker-compose.prod.yml`).
2. Restart the `uat` service; verify the new login option appears on the RP
   login page.
3. Configure project-level role mapping for each project from
   `dashboard-kit/config/teams.yml`.
4. Document the rollout (who can self-register vs. who needs manual
   provisioning) and communicate to teams before disabling local-account
   login (if that's the goal).

## Jira integration (`plugin-bts-jira`)

ReportPortal's Jira plugin lets failed test items be linked to / create Jira
issues directly from a launch.

What's needed before this can be implemented:
- Jira instance URL (Cloud or Server/Data Center) and a service-account API
  token with permission to create/link issues in the relevant Jira
  project(s).
- Mapping of RP projects (from `dashboard-kit/config/teams.yml`) to Jira
  project keys — likely 1:1 per team.
- Decision on which RP "defect type" categories
  (`product_bug`/`automation_bug`/`system_issue`, configured per project and
  already referenced in `dashboard-kit/config/widgets/failure_defect_breakdown.json`)
  should auto-link or auto-create Jira issues.

High-level steps once those are known:
1. Install `plugin-bts-jira` via the RP Admin UI (Administrate → Plugins) —
   RP downloads/loads it via the `jobs` service's plugin-loading cron
   (`COM_TA_REPORTPORTAL_JOB_LOAD_PLUGINS_CRON`, already configured in
   `docker-compose.yml`).
2. Per project, configure the BTS integration (Jira URL, project key,
   credentials) under Project Settings → Integrations.
3. Re-test the "Failure & Defect Breakdown" dashboard
   (`dashboard-kit/config/dashboards/dashboard_failure_defect_breakdown.json`)
   — once Jira links exist, consider extending `Defect Type Breakdown` /
   `Top Failed Test Cases` widgets with linked-issue counts if the RP version
   in use exposes that as a content field.

## Dashboard cleanup on a live instance

Not applicable to a fresh deployment (Phase 1 assumes none exist yet). If
this kit is later applied to a company's *existing* RP instance that already
has ad-hoc dashboards:

1. Add a `--list-existing` audit mode to `provision_dashboards.py` (or a
   sibling `cleanup_dashboards.py`) that, per project, prints all existing
   dashboards/widgets/filters with last-modified/owner info, so stakeholders
   can sign off on what gets removed.
2. Decide per-project: archive (rename with an `[ARCHIVED]` prefix) vs.
   delete outright. Archiving is safer and reversible.
3. Run `provision_dashboards.py` (Phase 1) to lay down the standard kit
   alongside/after cleanup, using `--force` only where intentional updates to
   existing same-named items are wanted.
4. Re-run `--list-existing` afterward to confirm the end state matches the
   intended dashboard kit per `dashboard-kit/README.md`.

## Forward-compatibility notes

- The `team:`/`layer:`/`service:` attribute convention
  (`dashboard-kit/ci-examples/ATTRIBUTES.md`) is designed to also work as
  Jira component/label hints once the BTS integration is configured.
- Per-project access control (today: manual via RP UI) is exactly what an
  SSO group-mapping step in Phase 2 would replace — no project restructuring
  needed.
- The umbrella-project pattern (`dashboard-kit/config/teams.yml`,
  `mode: umbrella`) scales to additional business units by adding more
  entries; no script changes required.
